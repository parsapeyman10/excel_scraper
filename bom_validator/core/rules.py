"""Pluggable validation rules.

Each rule is a small class registered in :data:`RULE_REGISTRY`. A rule receives
the whole :class:`RuleContext` and yields :class:`Issue` objects. Adding a
plant-specific check means writing one class and decorating it — no changes to
the engine.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from ..config import ValidationProfile
from ..models import Issue, Layer, LineResult, Placement, Severity
from . import normalize as nz

RULE_REGISTRY: dict[str, type[Rule]] = {}


def register(cls: type[Rule]) -> type[Rule]:
    RULE_REGISTRY[cls.code] = cls
    return cls


@dataclass(slots=True)
class RuleContext:
    """Everything a rule may need to reach a verdict."""

    profile: ValidationProfile
    results: list[LineResult]
    placements: list[Placement]
    placement_index: dict[str, list[Placement]] = field(default_factory=dict)
    designator_index: dict[str, list[Placement]] = field(default_factory=dict)
    orphans: list[Placement] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)

    def top(self) -> Iterator[Placement]:
        return (p for p in self.placements if p.layer is Layer.TOP)

    def bot(self) -> Iterator[Placement]:
        return (p for p in self.placements if p.layer is Layer.BOT)


class Rule:
    """Base class for all rules."""

    code: str = "RULE"
    title: str = ""
    description: str = ""
    severity: Severity = Severity.WARNING
    scope: str = "line"  # "line" | "global"
    default_enabled: bool = True

    def __init__(self, profile: ValidationProfile):
        self.profile = profile

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        return ()

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        return ()

    def issue(self, message: str, line_key: str = "", **context) -> Issue:
        return Issue(
            code=self.code,
            severity=self.severity,
            message=message,
            line_key=line_key,
            context=context,
        )


# ---------------------------------------------------------------------------
# Quantity rules
# ---------------------------------------------------------------------------


@register
class QuantityMatchRule(Rule):
    code = "QTY_MISMATCH"
    title = "Quantity mismatch"
    description = "BOM quantity must equal the number of machine placements."
    severity = Severity.ERROR

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        delta = result.delta
        tol = self.profile.qty_tolerance
        if abs(delta) <= tol:
            return ()
        direction = "surplus" if delta > 0 else "shortage"
        return [
            self.issue(
                f"{direction.title()} of {abs(delta)}: BOM requires "
                f"{result.line.qty}, placement files contain {result.placed_total}.",
                result.line.key,
                required=result.line.qty,
                placed=result.placed_total,
                delta=delta,
            )
        ]


@register
class NotPlacedRule(Rule):
    code = "NOT_PLACED"
    title = "Component never placed"
    description = "A BOM line with a positive quantity has zero placements."
    severity = Severity.CRITICAL

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if result.line.qty > 0 and result.placed_total == 0:
            return [
                self.issue(
                    f"No placement found for '{result.line.key}' "
                    f"(quantity {result.line.qty} required).",
                    result.line.key,
                    required=result.line.qty,
                )
            ]
        return ()


@register
class ZeroQuantityRule(Rule):
    code = "ZERO_QTY"
    title = "Zero or negative quantity"
    description = "BOM lines must declare a positive quantity."
    severity = Severity.ERROR

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if result.line.qty <= 0:
            sev = Severity.ERROR if self.profile.fail_on_zero_qty else Severity.WARNING
            return [
                Issue(
                    self.code,
                    sev,
                    f"Quantity is {result.line.qty} for '{result.line.key}'.",
                    result.line.key,
                )
            ]
        return ()


@register
class DesignatorCountRule(Rule):
    code = "DESIG_COUNT"
    title = "Designator count vs quantity"
    description = "The designator list length should equal the declared quantity."
    severity = Severity.WARNING

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        d = result.line.designators
        if not d:
            return ()
        if len(d) != result.line.qty:
            return [
                self.issue(
                    f"Designator list has {len(d)} entries but quantity is "
                    f"{result.line.qty}.",
                    result.line.key,
                    designators=len(d),
                    qty=result.line.qty,
                )
            ]
        return ()


# ---------------------------------------------------------------------------
# Designator / traceability rules
# ---------------------------------------------------------------------------


@register
class DesignatorMismatchRule(Rule):
    code = "DESIG_MISMATCH"
    title = "Designator set mismatch"
    description = "Every BOM designator must appear in a placement file, and vice versa."
    severity = Severity.ERROR

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_designator_mismatch:
            return ()
        if not result.line.designators:
            return ()
        out: list[Issue] = []
        if result.missing_designators:
            preview = ", ".join(result.missing_designators[:12])
            more = (
                f" (+{len(result.missing_designators) - 12} more)"
                if len(result.missing_designators) > 12
                else ""
            )
            out.append(
                self.issue(
                    f"{len(result.missing_designators)} designator(s) in the BOM "
                    f"have no placement: {preview}{more}",
                    result.line.key,
                    missing=list(result.missing_designators),
                )
            )
        if result.extra_designators:
            preview = ", ".join(result.extra_designators[:12])
            more = (
                f" (+{len(result.extra_designators) - 12} more)"
                if len(result.extra_designators) > 12
                else ""
            )
            out.append(
                Issue(
                    self.code,
                    Severity.WARNING,
                    f"{len(result.extra_designators)} placed designator(s) are not "
                    f"listed in the BOM: {preview}{more}",
                    result.line.key,
                    {"extra": list(result.extra_designators)},
                )
            )
        return out


@register
class DuplicateDesignatorRule(Rule):
    code = "DUP_DESIGNATOR"
    title = "Duplicate designator"
    description = "A reference designator must be unique across both layers."
    severity = Severity.ERROR
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_duplicate_designator:
            return ()
        out: list[Issue] = []
        for designator, places in sorted(ctx.duplicates.items()):
            out.append(
                self.issue(
                    f"Designator '{designator}' appears {len(places)} times "
                    f"({', '.join(places)}).",
                    designator,
                    occurrences=places,
                )
            )
        return out


@register
class DuplicateStockRule(Rule):
    code = "DUP_STOCK"
    title = "Duplicate BOM key"
    description = "The same stock number appears on multiple BOM lines."
    severity = Severity.WARNING
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_duplicate_stock:
            return ()
        seen: dict[str, list[int]] = {}
        for r in ctx.results:
            key = nz.canonical(r.line.key)
            if key:
                seen.setdefault(key, []).append(r.line.source_row)
        return [
            self.issue(
                f"Key '{key}' is declared on {len(rows)} BOM rows "
                f"(rows {', '.join(map(str, rows))}); placements were split "
                f"across them.",
                key,
                rows=rows,
            )
            for key, rows in seen.items()
            if len(rows) > 1
        ]


@register
class MissingStockRule(Rule):
    code = "MISSING_STOCK"
    title = "Missing stock number"
    description = "Lines without a stock number fall back to fuzzy name matching."
    severity = Severity.WARNING

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_missing_stock:
            return ()
        if not result.line.stock_no and result.line.part_name:
            return [
                self.issue(
                    "No stock number on this line; matched by part name only.",
                    result.line.key,
                )
            ]
        return ()


@register
class OrphanPlacementRule(Rule):
    code = "ORPHAN_PLACEMENT"
    title = "Orphan placement"
    description = "A placement exists for a component that is not in the BOM."
    severity = Severity.ERROR
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_orphan_placement or not ctx.orphans:
            return ()
        grouped: dict[str, list[Placement]] = {}
        for p in ctx.orphans:
            grouped.setdefault(p.key or "?", []).append(p)
        out = []
        for key, places in sorted(grouped.items()):
            refs = ", ".join(sorted({p.designator for p in places if p.designator})[:10])
            out.append(
                self.issue(
                    f"{len(places)} placement(s) reference '{key}' which is absent "
                    f"from the BOM{': ' + refs if refs else ''}.",
                    key,
                    count=len(places),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Geometry / process rules
# ---------------------------------------------------------------------------


@register
class RotationRangeRule(Rule):
    code = "BAD_ROTATION"
    title = "Rotation out of range"
    description = "Placement rotation must be within 0..max_rotation degrees."
    severity = Severity.WARNING
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        limit = self.profile.max_rotation
        if limit <= 0:
            return ()
        bad = [
            p
            for p in ctx.placements
            if p.rotation is not None and not (-0.001 <= p.rotation <= limit + 0.001)
        ]
        return [
            self.issue(
                f"Placement {p.designator or p.key} on {p.layer.label} has rotation "
                f"{p.rotation}° outside 0..{limit:g}°.",
                p.key,
                designator=p.designator,
                rotation=p.rotation,
            )
            for p in bad[:200]
        ]


@register
class BoardExtentRule(Rule):
    code = "OFF_BOARD"
    title = "Placement outside board extent"
    description = "X/Y coordinates must fall inside the declared board outline."
    severity = Severity.ERROR
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        ex, ey = self.profile.board_extent_x, self.profile.board_extent_y
        if ex <= 0 and ey <= 0:
            return ()
        out = []
        for p in ctx.placements:
            if p.x is None or p.y is None:
                continue
            if (ex > 0 and not (0 <= p.x <= ex)) or (ey > 0 and not (0 <= p.y <= ey)):
                out.append(
                    self.issue(
                        f"Placement {p.designator or p.key} at ({p.x}, {p.y}) mm lies "
                        f"outside the {ex:g}×{ey:g} mm board extent.",
                        p.key,
                        designator=p.designator,
                        x=p.x,
                        y=p.y,
                    )
                )
        return out[:200]


@register
class CoincidentPlacementRule(Rule):
    code = "COINCIDENT"
    title = "Coincident placements"
    description = "Two components share the same coordinates on the same layer."
    severity = Severity.WARNING
    scope = "global"

    def check_global(self, ctx: RuleContext) -> Iterable[Issue]:
        buckets: dict[tuple[str, float, float], list[Placement]] = {}
        for p in ctx.placements:
            if p.x is None or p.y is None:
                continue
            buckets.setdefault(
                (p.layer.value, round(p.x, 3), round(p.y, 3)), []
            ).append(p)
        out = []
        for (layer, x, y), group in buckets.items():
            if len(group) > 1:
                refs = ", ".join(p.designator or p.key for p in group)
                out.append(
                    self.issue(
                        f"{len(group)} components share ({x}, {y}) mm on {layer}: {refs}.",
                        group[0].key,
                        layer=layer,
                        x=x,
                        y=y,
                    )
                )
        return out[:200]


@register
class LayerSplitRule(Rule):
    code = "LAYER_SPLIT"
    title = "Component split across both layers"
    description = "Informational: the part is placed on top and bottom."
    severity = Severity.INFO

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.warn_on_single_layer_split:
            return ()
        if result.top_count and result.bot_count:
            return [
                self.issue(
                    f"Placed on both layers (top={result.top_count}, "
                    f"bot={result.bot_count}).",
                    result.line.key,
                )
            ]
        return ()


@register
class DescriptionConsistencyRule(Rule):
    code = "DESC_DRIFT"
    title = "Description drift"
    description = "BOM part name and placement description differ significantly."
    severity = Severity.WARNING

    def check_line(self, result: LineResult, ctx: RuleContext) -> Iterable[Issue]:
        if not self.profile.fuzzy_matching or not result.line.part_name:
            return ()
        key = nz.canonical(result.line.key)
        places = ctx.placement_index.get(key) or []
        descriptions = {p.description for p in places if p.description}
        if not descriptions:
            return ()
        bom_desc = nz.canonical(result.line.part_name)
        worst, worst_text = 1.0, ""
        for d in descriptions:
            score = nz.similarity(bom_desc, nz.canonical(d))
            if score < worst:
                worst, worst_text = score, d
        if worst < 0.55:
            return [
                self.issue(
                    f"Placement description '{worst_text}' differs from BOM "
                    f"'{result.line.part_name}' (similarity {worst:.0%}).",
                    result.line.key,
                    similarity=round(worst, 3),
                )
            ]
        return ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_rules(profile: ValidationProfile) -> list[Rule]:
    enabled = set(profile.enabled_rules) if profile.enabled_rules else None
    rules: list[Rule] = []
    for code, cls in RULE_REGISTRY.items():
        if enabled is not None and code not in enabled:
            continue
        if enabled is None and not cls.default_enabled:
            continue
        rules.append(cls(profile))
    return rules


def rule_catalog() -> list[dict[str, str]]:
    return [
        {
            "code": cls.code,
            "title": cls.title,
            "description": cls.description,
            "severity": cls.severity.label,
            "scope": cls.scope,
        }
        for cls in RULE_REGISTRY.values()
    ]
