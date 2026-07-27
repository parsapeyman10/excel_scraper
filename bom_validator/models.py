"""Domain models for the BOM validation engine.

Everything here is pure Python (no Qt, no pandas types leaking out) so the
core can be unit-tested and reused from the CLI, a web service or a batch job.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class Severity(enum.IntEnum):
    """Severity ordering used for sorting and filtering issues."""

    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40

    @property
    def label(self) -> str:
        return self.name.title()


class Status(enum.Enum):
    """Verification verdict for a single BOM line."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_PLACED = "NOT_PLACED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_ok(self) -> bool:
        return self is Status.PASS

    @property
    def severity(self) -> Severity:
        return {
            Status.PASS: Severity.INFO,
            Status.WARN: Severity.WARNING,
            Status.FAIL: Severity.ERROR,
            Status.NOT_PLACED: Severity.CRITICAL,
            Status.UNKNOWN: Severity.WARNING,
        }[self]


class Layer(enum.Enum):
    TOP = "top"
    BOT = "bot"

    @property
    def label(self) -> str:
        return "Top" if self is Layer.TOP else "Bottom"


@dataclass(frozen=True, slots=True)
class Placement:
    """A single machine placement read from a pick-and-place sheet."""

    designator: str
    layer: Layer
    stock_no: str = ""
    description: str = ""
    x: float | None = None
    y: float | None = None
    rotation: float | None = None
    source_row: int = 0

    @property
    def key(self) -> str:
        return self.stock_no or self.description

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layer"] = self.layer.value
        return d


@dataclass(slots=True)
class BomLine:
    """A single row of the BOM (Bill of Material)."""

    item: str = ""
    stock_no: str = ""
    part_name: str = ""
    part_no: str = ""
    material: str = ""
    size: str = ""
    brand: str = ""
    note: str = ""
    qty: int = 0
    designators: tuple[str, ...] = ()
    source_row: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Primary matching key: stock number, falling back to part name."""
        return self.stock_no or self.part_name

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["designators"] = list(self.designators)
        d.pop("raw", None)
        return d


@dataclass(slots=True)
class Issue:
    """A single validation finding attached to a BOM line (or global)."""

    code: str
    severity: Severity
    message: str
    line_key: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.label
        return d


@dataclass(slots=True)
class LineResult:
    """The validation outcome for one BOM line."""

    line: BomLine
    top_count: int = 0
    bot_count: int = 0
    status: Status = Status.UNKNOWN
    issues: list[Issue] = field(default_factory=list)
    matched_top: tuple[str, ...] = ()
    matched_bot: tuple[str, ...] = ()
    missing_designators: tuple[str, ...] = ()
    extra_designators: tuple[str, ...] = ()
    signed_off: bool = False
    operator_note: str = ""

    @property
    def placed_total(self) -> int:
        return self.top_count + self.bot_count

    @property
    def delta(self) -> int:
        """placed - required. Negative = shortage, positive = surplus."""
        return self.placed_total - self.line.qty

    @property
    def max_severity(self) -> Severity:
        if not self.issues:
            return Severity.INFO
        return max(i.severity for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.line.to_dict(),
            "top_count": self.top_count,
            "bot_count": self.bot_count,
            "placed_total": self.placed_total,
            "delta": self.delta,
            "status": self.status.value,
            "signed_off": self.signed_off,
            "operator_note": self.operator_note,
            "missing_designators": list(self.missing_designators),
            "extra_designators": list(self.extra_designators),
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass(slots=True)
class SheetMapping:
    """Detected column mapping for the BOM sheet."""

    sheet_name: str = ""
    header_row: int = -1
    columns: dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0
    detected_by: str = "auto"

    def get(self, name: str) -> int:
        return self.columns.get(name, -1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationSummary:
    total_lines: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    not_placed: int = 0
    total_required: int = 0
    total_placed: int = 0
    top_placed: int = 0
    bot_placed: int = 0
    orphan_placements: int = 0
    duplicate_designators: int = 0

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total_lines * 100.0) if self.total_lines else 0.0

    @property
    def coverage(self) -> float:
        return (
            (self.total_placed / self.total_required * 100.0)
            if self.total_required
            else 0.0
        )

    @property
    def health_score(self) -> float:
        """0-100 composite score used by the dashboard gauge."""
        if not self.total_lines:
            return 0.0
        penalty = (
            self.failed * 1.0
            + self.not_placed * 1.5
            + self.warnings * 0.4
            + self.orphan_placements * 0.25
            + self.duplicate_designators * 0.5
        )
        score = 100.0 - (penalty / max(self.total_lines, 1)) * 100.0
        return max(0.0, min(100.0, score))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pass_rate"] = round(self.pass_rate, 2)
        d["coverage"] = round(self.coverage, 2)
        d["health_score"] = round(self.health_score, 2)
        return d


@dataclass(slots=True)
class ValidationReport:
    """The complete result of one validation run."""

    source_file: str = ""
    source_sha256: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile_name: str = "default"
    mapping: SheetMapping = field(default_factory=SheetMapping)
    results: list[LineResult] = field(default_factory=list)
    global_issues: list[Issue] = field(default_factory=list)
    orphan_placements: list[Placement] = field(default_factory=list)
    duplicate_designators: dict[str, list[str]] = field(default_factory=dict)
    summary: ValidationSummary = field(default_factory=ValidationSummary)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    # populated by the engine; ``None`` for reports rebuilt from JSON
    sources: Any = None

    @property
    def source_label(self) -> str:
        """Human label of the input(s) — one file name, or all three."""
        if self.sources is not None:
            return self.sources.label
        from pathlib import Path as _P

        return _P(self.source_file).name

    def recompute_summary(self) -> ValidationSummary:
        s = ValidationSummary()
        s.total_lines = len(self.results)
        for r in self.results:
            if r.status is Status.PASS:
                s.passed += 1
            elif r.status is Status.FAIL:
                s.failed += 1
            elif r.status is Status.NOT_PLACED:
                s.not_placed += 1
            elif r.status is Status.WARN:
                s.warnings += 1
            s.total_required += r.line.qty
            s.total_placed += r.placed_total
            s.top_placed += r.top_count
            s.bot_placed += r.bot_count
        s.orphan_placements = len(self.orphan_placements)
        s.duplicate_designators = len(self.duplicate_designators)
        self.summary = s
        return s

    @property
    def failing(self) -> list[LineResult]:
        return [r for r in self.results if r.status is not Status.PASS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bom-validation-report/1.0",
            "source_file": self.source_file,
            "sources": (
                self.sources.to_dict()
                if self.sources is not None
                else {"mode": "single", "bom": self.source_file, "top": "", "bot": ""}
            ),
            "source_sha256": self.source_sha256,
            "generated_at": self.generated_at.isoformat(),
            "profile": self.profile_name,
            "duration_ms": round(self.duration_ms, 2),
            "mapping": self.mapping.to_dict(),
            "summary": self.summary.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "global_issues": [i.to_dict() for i in self.global_issues],
            "orphan_placements": [p.to_dict() for p in self.orphan_placements],
            "duplicate_designators": self.duplicate_designators,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def flatten(values: Iterable[Iterable[Any]]) -> list[Any]:
    return [v for row in values for v in row]
