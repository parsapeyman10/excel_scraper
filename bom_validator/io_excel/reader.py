"""Workbook loading, sheet classification and header auto-detection.

Reads with :mod:`openpyxl` in read-only mode so 100k-row workbooks stay cheap,
and falls back to :mod:`pandas` for legacy ``.xls``/``.csv`` inputs.
"""

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ValidationProfile
from ..core import normalize as nz
from ..models import BomLine, Layer, Placement, SheetMapping

log = logging.getLogger(__name__)

Grid = list[list[Any]]
ProgressCb = Callable[[int, int, str], None] | None


class WorkbookError(RuntimeError):
    """Raised when a workbook cannot be read or understood."""


# ---------------------------------------------------------------------------
# Raw loading
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SheetData:
    name: str
    rows: Grid

    def __len__(self) -> int:
        return len(self.rows)

    def cell(self, r: int, c: int) -> Any:
        if 0 <= r < len(self.rows):
            row = self.rows[r]
            if 0 <= c < len(row):
                return row[c]
        return None

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)


class WorkbookLoader:
    """Loads any supported tabular file into plain Python grids."""

    EXCEL_EXT = {".xlsx", ".xlsm", ".xltx", ".xltm"}
    LEGACY_EXT = {".xls"}
    TEXT_EXT = {".csv", ".tsv", ".txt"}

    def __init__(self, path: str | os.PathLike[str], max_rows: int = 500_000):
        self.path = Path(path)
        self.max_rows = max_rows
        if not self.path.exists():
            raise WorkbookError(f"File not found: {self.path}")
        self._sheets: dict[str, SheetData] | None = None

    # -- public ------------------------------------------------------
    @property
    def sheets(self) -> dict[str, SheetData]:
        if self._sheets is None:
            self._sheets = self._load()
        return self._sheets

    def sheet_names(self) -> list[str]:
        return list(self.sheets)

    def get(self, name: str) -> SheetData | None:
        return self.sheets.get(name)

    # -- internals ---------------------------------------------------
    def _load(self) -> dict[str, SheetData]:
        ext = self.path.suffix.lower()
        if ext in self.EXCEL_EXT:
            return self._load_openpyxl()
        if ext in self.LEGACY_EXT:
            return self._load_pandas()
        if ext in self.TEXT_EXT:
            return self._load_text()
        # last resort: let pandas sniff it
        return self._load_pandas()

    def _load_openpyxl(self) -> dict[str, SheetData]:
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise WorkbookError("openpyxl is required to read .xlsx files") from exc
        try:
            wb = openpyxl.load_workbook(
                self.path, data_only=True, read_only=True, keep_links=False
            )
        except Exception as exc:
            raise WorkbookError(f"Cannot open workbook: {exc}") from exc
        out: dict[str, SheetData] = {}
        try:
            for ws in wb.worksheets:
                rows: Grid = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= self.max_rows:
                        log.warning("Sheet %s truncated at %d rows", ws.title, i)
                        break
                    rows.append(list(row))
                out[ws.title] = SheetData(ws.title, rows)
        finally:
            wb.close()
        return out

    def _load_pandas(self) -> dict[str, SheetData]:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise WorkbookError("pandas is required for this file type") from exc
        try:
            book = pd.read_excel(self.path, sheet_name=None, header=None)
        except Exception as exc:
            raise WorkbookError(f"Cannot open workbook: {exc}") from exc
        return {
            name: SheetData(name, df.values.tolist()) for name, df in book.items()
        }

    def _load_text(self) -> dict[str, SheetData]:
        delim = "\t" if self.path.suffix.lower() in {".tsv", ".txt"} else ","
        rows: Grid = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
            for i, row in enumerate(csv.reader(fh, delimiter=delim)):
                if i >= self.max_rows:
                    break
                rows.append(list(row))
        return {self.path.stem: SheetData(self.path.stem, rows)}


# ---------------------------------------------------------------------------
# Sheet classification
# ---------------------------------------------------------------------------


def _matches(name: str, patterns: Sequence[str]) -> bool:
    key = nz.canonical(name)
    return any(nz.canonical(p) in key for p in patterns if p)


def classify_sheets(
    names: Sequence[str], profile: ValidationProfile
) -> dict[str, list[str]]:
    """Bucket sheet names into bom / top / bot / other."""
    buckets: dict[str, list[str]] = {"bom": [], "top": [], "bot": [], "other": []}
    for name in names:
        if _matches(name, profile.bot_sheet_patterns):
            buckets["bot"].append(name)
        elif _matches(name, profile.top_sheet_patterns):
            buckets["top"].append(name)
        elif _matches(name, profile.bom_sheet_patterns):
            buckets["bom"].append(name)
        else:
            buckets["other"].append(name)
    return buckets


def pick_bom_sheet(
    loader: WorkbookLoader, profile: ValidationProfile
) -> str | None:
    """Choose the BOM sheet: name match first, then structural scoring."""
    buckets = classify_sheets(loader.sheet_names(), profile)
    if buckets["bom"]:
        return buckets["bom"][0]
    best, best_score = None, 0.0
    for name in loader.sheet_names():
        if _matches(name, profile.ignore_sheet_patterns):
            continue
        mapping = detect_header(loader.sheets[name], profile)
        if mapping.confidence > best_score:
            best, best_score = name, mapping.confidence
    return best if best_score >= 0.4 else None


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------


def _score_cell(text: str, synonyms: Sequence[str]) -> float:
    """Return 1.0 for exact synonym, 0.75 for containment, else 0."""
    if not text:
        return 0.0
    for syn in synonyms:
        s = nz.header_key(syn)
        if not s:
            continue
        if text == s:
            return 1.0
    for syn in synonyms:
        s = nz.header_key(syn)
        if len(s) >= 3 and s in text:
            return 0.75
    return 0.0


def detect_header(
    sheet: SheetData,
    profile: ValidationProfile,
    synonyms: dict[str, list[str]] | None = None,
) -> SheetMapping:
    """Find the header row and map logical field -> column index.

    Uses a two-pass strategy: score every candidate row, then merge in
    "sub-header" columns that live on the following row(s) — a very common
    pattern in Persian engineering BOMs where ``Stock No.`` sits under a
    merged banner.
    """
    syns = synonyms or profile.column_synonyms
    scan = min(profile.header_scan_rows, len(sheet))
    best = SheetMapping(sheet_name=sheet.name)

    for r in range(scan):
        row = sheet.rows[r]
        found: dict[str, tuple[int, float]] = {}
        for c, raw in enumerate(row):
            text = nz.header_key(str(raw)) if raw is not None else ""
            if not text:
                continue
            for field_name, options in syns.items():
                score = _score_cell(text, options)
                if score > 0 and (
                    field_name not in found or score > found[field_name][1]
                ):
                    found[field_name] = (c, score)
        if not found:
            continue
        # merge sub-header rows for still-missing fields
        for look in range(1, profile.header_lookahead_rows + 1):
            rr = r + look
            if rr >= len(sheet):
                break
            for c, raw in enumerate(sheet.rows[rr]):
                text = nz.header_key(str(raw)) if raw is not None else ""
                if not text:
                    continue
                for field_name, options in syns.items():
                    if field_name in found:
                        continue
                    score = _score_cell(text, options)
                    if score > 0:
                        found[field_name] = (c, score * 0.9)

        required = [f for f in profile.required_columns if f in syns]
        hit = sum(1 for f in required if f in found)
        # allow one missing required column, but never accept zero hits
        minimum = max(1, min(len(required), len(required) - 1)) if required else 0
        if required and hit < minimum:
            continue
        confidence = (
            (hit / len(required) if required else 0.0) * 0.7
            + min(len(found) / max(len(syns), 1), 1.0) * 0.3
        )
        if confidence > best.confidence:
            best = SheetMapping(
                sheet_name=sheet.name,
                header_row=r,
                columns={k: v[0] for k, v in found.items()},
                confidence=round(confidence, 4),
                detected_by="auto",
            )
    if profile.manual_mapping:
        best.columns.update(profile.manual_mapping)
        best.detected_by = "manual-override"
    return best


# ---------------------------------------------------------------------------
# Row extraction
# ---------------------------------------------------------------------------

_HEADER_ECHO_TOKENS = {
    "stockno",
    "stockid",
    "partname",
    "partdescription",
    "description",
    "qty",
    "quantity",
    "totalrequired",
    "verification",
    "designator",
    "item",
    "partno",
    "brandsupplier",
    "componentname",
    "typematerial",
}


def _is_header_echo(*values: str) -> bool:
    for v in values:
        key = nz.header_key(v)
        if key and key in _HEADER_ECHO_TOKENS:
            return True
    return False


def extract_bom_lines(
    sheet: SheetData,
    mapping: SheetMapping,
    profile: ValidationProfile,
    progress: ProgressCb = None,
) -> tuple[list[BomLine], list[tuple[int, str]]]:
    """Return (lines, skipped) where skipped is (row_index, reason)."""
    if mapping.header_row < 0:
        raise WorkbookError("No header row detected in the BOM sheet")

    col = mapping.columns
    lines: list[BomLine] = []
    skipped: list[tuple[int, str]] = []
    total = len(sheet)

    def cell(r: int, name: str) -> Any:
        idx = col.get(name, -1)
        return sheet.cell(r, idx) if idx >= 0 else None

    for r in range(mapping.header_row + 1, total):
        if progress and r % 250 == 0:
            progress(r, total, "reading BOM")

        part = nz.clean(cell(r, "part_name"))
        stock = nz.clean(cell(r, "stock_no"))
        qty_raw = cell(r, "qty")
        qty_text = nz.clean(qty_raw)
        desig_raw = cell(r, "designator")

        if not any([part, stock, qty_text, nz.clean(desig_raw)]):
            continue
        if _is_header_echo(part, stock, qty_text):
            skipped.append((r, "header echo"))
            continue

        qty = nz.to_int(qty_raw)
        if qty is None:
            # a designator list without qty is still worth keeping
            if desig_raw:
                qty = len(nz.expand_designators(desig_raw))
            else:
                skipped.append((r, f"non-numeric qty {qty_text!r}"))
                continue

        if profile.trim_trailing_dot_zero and stock.endswith(".0"):
            stock = stock[:-2]

        lines.append(
            BomLine(
                item=nz.clean(cell(r, "item")),
                stock_no=stock,
                part_name=part,
                part_no=nz.clean(cell(r, "part_no")),
                material=nz.clean(cell(r, "material")),
                size=nz.clean(cell(r, "size")),
                brand=nz.clean(cell(r, "brand")),
                note=nz.clean(cell(r, "note")),
                qty=qty,
                designators=nz.expand_designators(desig_raw),
                source_row=r + 1,
            )
        )
    if progress:
        progress(total, total, "BOM read complete")
    return lines, skipped


def extract_placements(
    sheet: SheetData,
    layer: Layer,
    profile: ValidationProfile,
    progress: ProgressCb = None,
) -> list[Placement]:
    """Parse a pick-and-place sheet into :class:`Placement` records."""
    mapping = detect_header(
        sheet,
        ValidationProfile(
            header_scan_rows=profile.header_scan_rows,
            header_lookahead_rows=1,
            required_columns=["designator"],
            column_synonyms=profile.placement_synonyms,
        ),
        synonyms=profile.placement_synonyms,
    )
    out: list[Placement] = []
    total = len(sheet)

    if mapping.header_row < 0:
        # Unstructured sheet: treat every non-empty cell as a bare key.
        for r, row in enumerate(sheet.rows):
            for value in row:
                text = nz.clean(value)
                if text:
                    out.append(
                        Placement(
                            designator="",
                            layer=layer,
                            stock_no=text,
                            source_row=r + 1,
                        )
                    )
        return out

    col = mapping.columns
    for r in range(mapping.header_row + 1, total):
        if progress and r % 500 == 0:
            progress(r, total, f"reading {layer.value}")

        def cell(name: str, _row: int = r) -> Any:
            idx = col.get(name, -1)
            return sheet.cell(_row, idx) if idx >= 0 else None

        designator = nz.clean(cell("designator"))
        stock = nz.clean(cell("stock_no"))
        if profile.trim_trailing_dot_zero and stock.endswith(".0"):
            stock = stock[:-2]
        description = nz.clean(cell("description"))
        if not any([designator, stock, description]):
            continue
        if _is_header_echo(designator, stock, description):
            continue

        row_layer = layer
        layer_text = nz.canonical(nz.clean(cell("layer")))
        if layer_text:
            if layer_text.startswith(("b", "bot")):
                row_layer = Layer.BOT
            elif layer_text.startswith(("t", "top")):
                row_layer = Layer.TOP

        out.append(
            Placement(
                designator=designator,
                layer=row_layer,
                stock_no=stock,
                description=description,
                x=nz.to_float(cell("x")),
                y=nz.to_float(cell("y")),
                rotation=nz.to_float(cell("rotation")),
                source_row=r + 1,
            )
        )
    if progress:
        progress(total, total, f"{layer.value} read complete")
    return out


def iter_preview(sheet: SheetData, rows: int = 40, cols: int = 25) -> Iterator[list[Any]]:
    for row in sheet.rows[:rows]:
        yield list(row[:cols])
