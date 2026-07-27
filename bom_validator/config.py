"""Configuration, validation profiles and persistent user settings.

A *profile* captures every tunable of the validation pipeline so that a plant
can encode its own BOM conventions once and re-use them across runs, machines
and CI pipelines.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .version import APP_ID

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def app_data_dir() -> Path:
    """Cross-platform per-user data directory."""
    env = os.environ.get("BOM_VALIDATOR_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / APP_ID
    elif os.sys.platform == "darwin":  # type: ignore[attr-defined]
        p = Path.home() / "Library/Application Support" / APP_ID
    else:
        p = (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            / APP_ID
        )
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_dir() -> Path:
    p = app_data_dir() / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------
# Column synonyms — the heart of the auto-detection
# --------------------------------------------------------------------------

DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "item": ["item", "no", "row", "#", "ردیف", "شماره"],
    "designator": [
        "designator",
        "designators",
        "refdes",
        "reference",
        "references",
        "refdesignator",
        "location",
        "position",
        "مرجع",
    ],
    "part_name": [
        "partname",
        "part",
        "component",
        "componentname",
        "componentdescription",
        "description",
        "value",
        "نامقطعه",
    ],
    "part_no": ["partno", "partnumber", "mpn", "manufacturerpartnumber", "pn"],
    "material": ["type", "material", "typematerial", "package", "footprint", "mount"],
    "size": ["size", "case", "dimension", "dimensions"],
    "qty": ["qty", "quantity", "qnty", "count", "amount", "تعداد"],
    "brand": ["brand", "supplier", "manufacturer", "mfg", "vendor", "brandsupplier"],
    "stock_no": [
        "stockno",
        "stockid",
        "stocknumber",
        "spcostocknumber",
        "sapcode",
        "itemcode",
        "materialcode",
        "کدانبار",
    ],
    "note": ["note", "notes", "remark", "comment", "توضیحات"],
    "mana": ["mana", "mana."],
}

PLACEMENT_SYNONYMS: dict[str, list[str]] = {
    "designator": ["designator", "refdes", "reference", "component", "name", "part"],
    "x": ["centerx", "centerxmm", "x", "posx", "midx", "locationx"],
    "y": ["centery", "centerymm", "y", "posy", "midy", "locationy"],
    "rotation": ["rotation", "rot", "angle", "theta"],
    "stock_no": [
        "spcostocknumber",
        "stocknumber",
        "stockno",
        "stockid",
        "itemcode",
        "partid",
    ],
    "description": ["description", "comment", "value", "partname", "footprint"],
    "layer": ["layer", "side", "tb", "topbottom"],
}


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


@dataclass
class ValidationProfile:
    """All knobs that change how a workbook is parsed and judged."""

    name: str = "default"
    description: str = "Factory default profile"

    # --- sheet discovery -------------------------------------------------
    bom_sheet_patterns: list[str] = field(
        default_factory=lambda: ["مونتاژ", "ماشین", "bom", "bill of material", "smd"]
    )
    top_sheet_patterns: list[str] = field(
        default_factory=lambda: ["top", "رو", "t-side", "topside", "pnp_top"]
    )
    bot_sheet_patterns: list[str] = field(
        default_factory=lambda: ["bot", "bottom", "زیر", "b-side", "pnp_bot"]
    )
    ignore_sheet_patterns: list[str] = field(default_factory=lambda: ["sheet1", "temp"])

    # --- header detection ------------------------------------------------
    header_scan_rows: int = 25
    header_lookahead_rows: int = 2
    required_columns: list[str] = field(
        default_factory=lambda: ["part_name", "qty", "stock_no"]
    )
    column_synonyms: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_SYNONYMS.items()}
    )
    placement_synonyms: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in PLACEMENT_SYNONYMS.items()}
    )
    manual_mapping: dict[str, int] = field(default_factory=dict)

    # --- normalisation ---------------------------------------------------
    normalize_digits: bool = True  # Persian/Arabic digits -> ASCII
    normalize_unicode: bool = True  # NFKC + Arabic yeh/kaf unification
    case_insensitive_keys: bool = True
    strip_leading_zeros: bool = False
    trim_trailing_dot_zero: bool = True
    key_strategy: str = "stock_then_part"  # or "stock_only" | "part_only"
    fuzzy_matching: bool = True
    fuzzy_threshold: float = 0.88

    # --- rules -----------------------------------------------------------
    enabled_rules: list[str] = field(default_factory=list)  # empty = all
    qty_tolerance: int = 0
    warn_on_designator_mismatch: bool = True
    warn_on_orphan_placement: bool = True
    warn_on_duplicate_designator: bool = True
    warn_on_duplicate_stock: bool = True
    warn_on_missing_stock: bool = True
    warn_on_single_layer_split: bool = False
    fail_on_zero_qty: bool = True
    max_rotation: float = 360.0
    board_extent_x: float = 0.0  # 0 = disabled
    board_extent_y: float = 0.0

    # --- output ----------------------------------------------------------
    locale: str = "fa"
    theme: str = "industrial-light"
    auto_export_dir: str = ""

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationProfile:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else profiles_dir() / f"{self.name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> ValidationProfile:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def load_by_name(cls, name: str) -> ValidationProfile:
        if name in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[name]()
        p = profiles_dir() / f"{name}.json"
        if p.exists():
            return cls.load(p)
        raise FileNotFoundError(f"Profile not found: {name}")

    @staticmethod
    def list_available() -> list[str]:
        names = list(BUILTIN_PROFILES)
        names += [p.stem for p in profiles_dir().glob("*.json") if p.stem not in names]
        return sorted(names)


def _profile_default() -> ValidationProfile:
    return ValidationProfile()


def _profile_strict() -> ValidationProfile:
    return ValidationProfile(
        name="strict",
        description="Zero tolerance — every deviation is an error",
        qty_tolerance=0,
        fuzzy_matching=False,
        warn_on_single_layer_split=True,
        warn_on_missing_stock=True,
        fail_on_zero_qty=True,
    )


def _profile_lenient() -> ValidationProfile:
    return ValidationProfile(
        name="lenient",
        description="Prototype / engineering runs — small deltas tolerated",
        qty_tolerance=1,
        fuzzy_matching=True,
        fuzzy_threshold=0.80,
        warn_on_orphan_placement=False,
        fail_on_zero_qty=False,
    )


def _profile_smt_ipc() -> ValidationProfile:
    return ValidationProfile(
        name="smt-ipc",
        description="SMT line profile with geometric checks enabled",
        qty_tolerance=0,
        warn_on_designator_mismatch=True,
        warn_on_duplicate_designator=True,
        board_extent_x=300.0,
        board_extent_y=300.0,
    )


BUILTIN_PROFILES = {
    "default": _profile_default,
    "strict": _profile_strict,
    "lenient": _profile_lenient,
    "smt-ipc": _profile_smt_ipc,
}


# --------------------------------------------------------------------------
# App settings (UI level)
# --------------------------------------------------------------------------


@dataclass
class AppSettings:
    theme: str = "industrial-light"
    language: str = "fa"
    last_profile: str = "default"
    recent_files: list[str] = field(default_factory=list)
    # richer history that remembers three-file selections; recent_files stays
    # in sync so older settings files (and code paths) keep working
    recent_sources: list[dict[str, str]] = field(default_factory=list)
    max_recent: int = 12
    source_mode: str = "single"  # "single" | "multi"
    auto_process_on_open: bool = True
    watch_files: bool = False
    font_size: int = 9
    remember_geometry: bool = True
    geometry_b64: str = ""
    window_state_b64: str = ""
    export_dir: str = ""
    telemetry_local_only: bool = True

    @property
    def path(self) -> Path:
        return app_data_dir() / "settings.json"

    def push_recent(self, file_path: str) -> None:
        p = str(Path(file_path).resolve())
        if p in self.recent_files:
            self.recent_files.remove(p)
        self.recent_files.insert(0, p)
        del self.recent_files[self.max_recent :]

    def push_recent_sources(self, entry: dict[str, str]) -> None:
        """Remember a whole input selection (single file or BOM+top+bot)."""
        norm = {
            "mode": entry.get("mode", "single"),
            "bom": str(Path(entry["bom"]).resolve()),
            "top": str(Path(entry["top"]).resolve()) if entry.get("top") else "",
            "bot": str(Path(entry["bot"]).resolve()) if entry.get("bot") else "",
        }
        self.recent_sources = [e for e in self.recent_sources if e != norm]
        self.recent_sources.insert(0, norm)
        del self.recent_sources[self.max_recent :]
        self.source_mode = norm["mode"]
        self.push_recent(norm["bom"])

    def recent_source_sets(self) -> list[dict[str, str]]:
        """Recent selections, back-filled from the legacy ``recent_files``."""
        out = list(self.recent_sources)
        known = {e["bom"] for e in out}
        for f in self.recent_files:
            if f not in known:
                out.append({"mode": "single", "bom": f, "top": "", "bot": ""})
        return out[: self.max_recent]

    def save(self) -> Path:
        self.path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.path

    @classmethod
    def load(cls) -> AppSettings:
        p = app_data_dir() / "settings.json"
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()
