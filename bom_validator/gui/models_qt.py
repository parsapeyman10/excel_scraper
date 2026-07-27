"""Qt item models: fast virtualised views over the validation report."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PyQt6.QtGui import QBrush, QColor, QFont

from ..models import LineResult, Placement, Status, ValidationReport
from . import theme as th

CHECK = Qt.CheckState


class ResultTableModel(QAbstractTableModel):
    """One row per BOM line. Column 0 is a sign-off checkbox."""

    COLUMNS = [
        ("select", "select", 42),
        ("item", "Item", 56),
        ("stock", "stock", 110),
        ("part", "part", 380),
        ("size", "Size", 100),
        ("brand", "Brand", 150),
        ("top", "top", 90),
        ("bot", "bot", 90),
        ("placed", "placed", 90),
        ("delta", "delta", 62),
        ("status", "status", 110),
        ("findings", "findings", 460),
        ("note", "note", 200),
    ]

    def __init__(self, tr, theme: str = "industrial-light", parent=None):
        super().__init__(parent)
        self.tr_ = tr
        self.theme = theme
        self._rows: list[LineResult] = []
        self._colors = th.status_colors(theme)

    # -- data plumbing -------------------------------------------------
    def set_report(self, report: ValidationReport | None) -> None:
        self.beginResetModel()
        self._rows = list(report.results) if report else []
        self.endResetModel()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self._colors = th.status_colors(theme)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(self.COLUMNS) - 1),
            )

    def result_at(self, row: int) -> LineResult | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation is Qt.Orientation.Horizontal:
            key, fallback, _ = self.COLUMNS[section]
            return self.tr_(fallback) if fallback.islower() else fallback
        return section + 1

    def flags(self, index: QModelIndex):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col = index.column()
        if col == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if self.COLUMNS[col][0] == "note":
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    # -- rendering -----------------------------------------------------
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.CheckStateRole and key == "select":
            return CHECK.Checked if r.signed_off else CHECK.Unchecked

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return {
                "select": "",
                "item": r.line.item,
                "stock": r.line.stock_no,
                "part": r.line.part_name,
                "size": r.line.size,
                "brand": r.line.brand,
                "top": r.top_count,
                "bot": r.bot_count,
                "placed": r.placed_total,
                "delta": f"{r.delta:+d}" if r.delta else "0",
                "status": r.status.value,
                "findings": " • ".join(i.message for i in r.issues),
                "note": r.operator_note,
            }.get(key, "")

        if role == Qt.ItemDataRole.UserRole:  # sorting payload
            return {
                "top": r.top_count,
                "bot": r.bot_count,
                "placed": r.placed_total,
                "delta": r.delta,
                "status": -r.status.severity,
                "item": r.line.source_row,
            }.get(key, self.data(index, Qt.ItemDataRole.DisplayRole))

        if role == Qt.ItemDataRole.UserRole + 1:  # status for proxy filtering
            return r.status.value

        bg, fg = self._colors.get(r.status.value, ("#FFFFFF", "#000000"))
        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(QColor(bg))
        if role == Qt.ItemDataRole.ForegroundRole:
            if key in ("status", "delta"):
                return QBrush(QColor(fg))
            return None
        if role == Qt.ItemDataRole.FontRole and key in ("status", "stock"):
            f = QFont()
            f.setBold(key == "status")
            if key == "stock":
                f.setFamily("Consolas, monospace")
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in ("part", "findings", "note", "brand"):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"<b>{r.line.part_name}</b>", f"Stock: {r.line.stock_no or '—'}"]
            if r.line.designators:
                parts.append(
                    "BOM designators: " + ", ".join(r.line.designators[:40])
                    + ("…" if len(r.line.designators) > 40 else "")
                )
            if r.matched_top:
                parts.append("Top: " + ", ".join(r.matched_top[:40]))
            if r.matched_bot:
                parts.append("Bot: " + ", ".join(r.matched_bot[:40]))
            if r.missing_designators:
                parts.append(
                    "<span style='color:#c5221f'>Missing: "
                    + ", ".join(r.missing_designators[:40])
                    + "</span>"
                )
            if r.extra_designators:
                parts.append("Extra: " + ", ".join(r.extra_designators[:40]))
            for i in r.issues:
                parts.append(f"[{i.severity.label}] {i.code}: {i.message}")
            parts.append(f"<i>source row {r.line.source_row}</i>")
            return "<br>".join(parts)
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        r = self._rows[index.row()]
        key = self.COLUMNS[index.column()][0]
        if role == Qt.ItemDataRole.CheckStateRole and key == "select":
            r.signed_off = CHECK(value) == CHECK.Checked
            self.dataChanged.emit(index, index, [role])
            return True
        if role == Qt.ItemDataRole.EditRole and key == "note":
            r.operator_note = str(value)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    # -- bulk helpers --------------------------------------------------
    def set_all_signed(self, signed: bool) -> None:
        for r in self._rows:
            r.signed_off = signed
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, 0)
            )

    def signed_count(self) -> int:
        return sum(1 for r in self._rows if r.signed_off)


class ResultFilterProxy(QSortFilterProxyModel):
    """Text + status + severity filtering with natural numeric sorting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._status: set[str] = set()
        self._only_failing = False
        self._text = ""

    def set_status_filter(self, statuses: Sequence[str]) -> None:
        self._status = {s for s in statuses if s}
        self.invalidateFilter()

    def set_only_failing(self, only: bool) -> None:
        self._only_failing = only
        self.invalidateFilter()

    def set_text(self, text: str) -> None:
        self._text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        status = model.index(row, 0, parent).data(Qt.ItemDataRole.UserRole + 1)
        if self._only_failing and status == Status.PASS.value:
            return False
        if self._status and status not in self._status:
            return False
        if self._text:
            for c in range(model.columnCount()):
                v = model.index(row, c, parent).data(Qt.ItemDataRole.DisplayRole)
                if v is not None and self._text in str(v).lower():
                    return True
            return False
        return True


class IssueTableModel(QAbstractTableModel):
    HEADERS = ["Scope", "Severity", "Code", "Key", "Message"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str, str, str, str, int]] = []

    def set_report(self, report: ValidationReport | None) -> None:
        self.beginResetModel()
        self._rows = []
        if report:
            for r in report.results:
                for i in r.issues:
                    self._rows.append(
                        ("line", i.severity.label, i.code, i.line_key, i.message, int(i.severity))
                    )
            for i in report.global_issues:
                self._rows.append(
                    ("global", i.severity.label, i.code, i.line_key, i.message, int(i.severity))
                )
            self._rows.sort(key=lambda t: -t[5])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation is Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return row[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QBrush(
                QColor(
                    {"Critical": "#8B1A0E", "Error": "#C5221F", "Warning": "#B06000"}.get(
                        row[1], "#6B7280"
                    )
                )
            )
        if role == Qt.ItemDataRole.UserRole:
            return row[5] if index.column() == 1 else row[index.column()]
        return None


class PlacementTableModel(QAbstractTableModel):
    HEADERS = ["Designator", "Layer", "Stock No", "Description", "X (mm)", "Y (mm)", "Rot", "Row"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[Placement] = []

    def set_placements(self, placements: Sequence[Placement]) -> None:
        self.beginResetModel()
        self._rows = list(placements)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation is Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole):
            return [
                p.designator,
                p.layer.label,
                p.stock_no,
                p.description,
                p.x,
                p.y,
                p.rotation,
                p.source_row,
            ][index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() >= 4:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class DesignatorTableModel(QAbstractTableModel):
    HEADERS = ["Stock No", "Part", "Layer", "Designator", "State"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str, str, str, str]] = []

    def set_report(self, report: ValidationReport | None) -> None:
        self.beginResetModel()
        self._rows = []
        if report:
            for r in report.results:
                for d in r.matched_top:
                    self._rows.append((r.line.stock_no, r.line.part_name, "Top", d, "placed"))
                for d in r.matched_bot:
                    self._rows.append((r.line.stock_no, r.line.part_name, "Bot", d, "placed"))
                for d in r.missing_designators:
                    self._rows.append((r.line.stock_no, r.line.part_name, "—", d, "missing"))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation is Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole):
            return row[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and row[4] == "missing":
            return QBrush(QColor("#C5221F"))
        return None


class SheetPreviewModel(QAbstractTableModel):
    """Read-only grid preview of a raw worksheet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[list[Any]] = []
        self._header_row = -1
        self._mapped: dict[int, str] = {}

    def set_sheet(self, rows: Sequence[Sequence[Any]], header_row: int = -1,
                  mapped: dict[int, str] | None = None) -> None:
        self.beginResetModel()
        self._rows = [list(r) for r in rows]
        self._header_row = header_row
        self._mapped = mapped or {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else max((len(r) for r in self._rows), default=0)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation is Qt.Orientation.Horizontal:
            name = self._mapped.get(section)
            letter = _col_letter(section)
            return f"{letter} · {name}" if name else letter
        return section + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        value = row[index.column()] if index.column() < len(row) else None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self._header_row:
                return QBrush(QColor("#FFF3C4"))
            if index.column() in self._mapped:
                return QBrush(QColor("#EAF3FB"))
        if role == Qt.ItemDataRole.FontRole and index.row() == self._header_row:
            f = QFont()
            f.setBold(True)
            return f
        return None


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s
