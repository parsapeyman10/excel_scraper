"""Compare two validation reports (revision A vs revision B)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import LineResult, ValidationReport
from . import normalize as nz


@dataclass(slots=True)
class LineDelta:
    key: str
    description: str = ""
    old_qty: int | None = None
    new_qty: int | None = None
    old_placed: int | None = None
    new_placed: int | None = None
    old_status: str = ""
    new_status: str = ""
    change: str = ""  # added | removed | qty_changed | status_changed | unchanged

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "description": self.description,
            "old_qty": self.old_qty,
            "new_qty": self.new_qty,
            "old_placed": self.old_placed,
            "new_placed": self.new_placed,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "change": self.change,
        }


@dataclass(slots=True)
class ReportDiff:
    old_label: str = ""
    new_label: str = ""
    added: list[LineDelta] = field(default_factory=list)
    removed: list[LineDelta] = field(default_factory=list)
    changed: list[LineDelta] = field(default_factory=list)
    unchanged: int = 0
    health_delta: float = 0.0

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "old": self.old_label,
            "new": self.new_label,
            "health_delta": round(self.health_delta, 2),
            "unchanged": self.unchanged,
            "added": [d.to_dict() for d in self.added],
            "removed": [d.to_dict() for d in self.removed],
            "changed": [d.to_dict() for d in self.changed],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# BOM diff: {self.old_label} → {self.new_label}",
            "",
            f"- Added: **{len(self.added)}**",
            f"- Removed: **{len(self.removed)}**",
            f"- Changed: **{len(self.changed)}**",
            f"- Unchanged: {self.unchanged}",
            f"- Health score change: **{self.health_delta:+.1f}**",
            "",
        ]
        if self.changed:
            lines += [
                "## Changed lines",
                "",
                "| Key | Description | Qty | Placed | Status |",
                "|---|---|---|---|---|",
            ]
            for d in self.changed:
                lines.append(
                    f"| `{d.key}` | {d.description[:44]} | "
                    f"{d.old_qty} → {d.new_qty} | {d.old_placed} → {d.new_placed} | "
                    f"{d.old_status} → {d.new_status} |"
                )
            lines.append("")
        for title, items in (("Added lines", self.added), ("Removed lines", self.removed)):
            if items:
                lines += [f"## {title}", ""]
                lines += [
                    f"- `{d.key}` {d.description[:60]} (qty "
                    f"{d.new_qty if d.new_qty is not None else d.old_qty})"
                    for d in items
                ]
                lines.append("")
        return "\n".join(lines)


def _index(report: ValidationReport) -> dict[str, LineResult]:
    out: dict[str, LineResult] = {}
    for r in report.results:
        out[nz.canonical(r.line.key)] = r
    return out


def diff_reports(old: ValidationReport, new: ValidationReport) -> ReportDiff:
    a, b = _index(old), _index(new)
    d = ReportDiff(
        old_label=f"{old.source_file} @ {old.generated_at:%Y-%m-%d %H:%M}",
        new_label=f"{new.source_file} @ {new.generated_at:%Y-%m-%d %H:%M}",
        health_delta=new.summary.health_score - old.summary.health_score,
    )
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        if ra and not rb:
            d.removed.append(
                LineDelta(
                    key=ra.line.key,
                    description=ra.line.part_name,
                    old_qty=ra.line.qty,
                    old_placed=ra.placed_total,
                    old_status=ra.status.value,
                    change="removed",
                )
            )
        elif rb and not ra:
            d.added.append(
                LineDelta(
                    key=rb.line.key,
                    description=rb.line.part_name,
                    new_qty=rb.line.qty,
                    new_placed=rb.placed_total,
                    new_status=rb.status.value,
                    change="added",
                )
            )
        elif ra and rb:
            same = (
                ra.line.qty == rb.line.qty
                and ra.placed_total == rb.placed_total
                and ra.status is rb.status
            )
            if same:
                d.unchanged += 1
            else:
                d.changed.append(
                    LineDelta(
                        key=rb.line.key,
                        description=rb.line.part_name,
                        old_qty=ra.line.qty,
                        new_qty=rb.line.qty,
                        old_placed=ra.placed_total,
                        new_placed=rb.placed_total,
                        old_status=ra.status.value,
                        new_status=rb.status.value,
                        change="qty_changed"
                        if ra.line.qty != rb.line.qty
                        else "status_changed",
                    )
                )
    return d
