"""The validation engine: ties reader, matcher and rules together."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..config import ValidationProfile
from ..io_excel import reader as rd
from ..models import (
    BomLine,
    Issue,
    Layer,
    LineResult,
    Placement,
    Severity,
    Status,
    ValidationReport,
    sha256_file,
)
from . import normalize as nz
from .rules import RuleContext, build_rules

log = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None] | None
CancelCb = Callable[[], bool] | None


class ValidationCancelled(RuntimeError):
    pass


class BomValidationEngine:
    """Stateless-ish orchestrator; one instance per run is cheapest."""

    def __init__(self, profile: ValidationProfile | None = None):
        self.profile = profile or ValidationProfile()

    # ------------------------------------------------------------------
    def run(
        self,
        file_path: str | Path,
        *,
        progress: ProgressCb = None,
        cancel: CancelCb = None,
    ) -> ValidationReport:
        started = time.perf_counter()
        path = Path(file_path)

        def tick(done: int, total: int, msg: str) -> None:
            if cancel and cancel():
                raise ValidationCancelled("Validation cancelled by user")
            if progress:
                progress(done, total, msg)

        tick(0, 100, "opening workbook")
        loader = rd.WorkbookLoader(path)
        names = loader.sheet_names()
        buckets = rd.classify_sheets(names, self.profile)

        report = ValidationReport(
            source_file=str(path),
            source_sha256=sha256_file(str(path)),
            profile_name=self.profile.name,
        )
        report.metadata = {
            "sheets": names,
            "sheet_roles": buckets,
            "file_size_bytes": path.stat().st_size,
            "engine_version": 2,
        }

        # -- BOM sheet ------------------------------------------------
        tick(5, 100, "locating BOM sheet")
        bom_name = rd.pick_bom_sheet(loader, self.profile)
        if not bom_name:
            raise rd.WorkbookError(
                "No BOM sheet could be identified. Available sheets: "
                + ", ".join(names)
            )
        bom_sheet = loader.sheets[bom_name]
        mapping = rd.detect_header(bom_sheet, self.profile)
        if mapping.header_row < 0:
            raise rd.WorkbookError(
                f"Could not detect a header row in sheet '{bom_name}'."
            )
        report.mapping = mapping

        tick(15, 100, "reading BOM rows")
        lines, skipped = rd.extract_bom_lines(
            bom_sheet, mapping, self.profile, progress=None
        )
        if skipped:
            report.metadata["skipped_rows"] = skipped[:200]

        # -- placement sheets ------------------------------------------
        tick(40, 100, "reading placement sheets")
        placements: list[Placement] = []
        for name in buckets["top"]:
            placements += rd.extract_placements(
                loader.sheets[name], Layer.TOP, self.profile
            )
        for name in buckets["bot"]:
            placements += rd.extract_placements(
                loader.sheets[name], Layer.BOT, self.profile
            )
        if not placements:
            report.global_issues.append(
                Issue(
                    "NO_PLACEMENT_SHEET",
                    Severity.CRITICAL,
                    "No 'top' or 'bot' placement sheet was found; every line will "
                    "report zero placements.",
                )
            )

        # -- match & judge ---------------------------------------------
        tick(60, 100, "matching components")
        report.results, ctx = self.match(lines, placements)
        report.orphan_placements = ctx.orphans
        report.duplicate_designators = ctx.duplicates

        tick(80, 100, "applying rules")
        self.apply_rules(report, ctx)

        report.recompute_summary()
        report.duration_ms = (time.perf_counter() - started) * 1000
        tick(100, 100, "done")
        log.info(
            "Validated %s: %d lines in %.0f ms",
            path.name,
            len(report.results),
            report.duration_ms,
        )
        return report

    # ------------------------------------------------------------------
    def match(
        self, lines: list[BomLine], placements: list[Placement]
    ) -> tuple[list[LineResult], RuleContext]:
        """Index placements and attach them to BOM lines."""
        p = self.profile

        def key_of(text: str) -> str:
            return nz.canonical(
                text,
                case_insensitive=p.case_insensitive_keys,
                strip_zeros=p.strip_leading_zeros,
                trim_dot_zero=p.trim_trailing_dot_zero,
            )

        by_key: dict[str, list[Placement]] = defaultdict(list)
        by_desc: dict[str, list[Placement]] = defaultdict(list)
        by_designator: dict[str, list[Placement]] = defaultdict(list)

        for pl in placements:
            if pl.stock_no:
                by_key[key_of(pl.stock_no)].append(pl)
            if pl.description:
                by_desc[key_of(pl.description)].append(pl)
            if pl.designator:
                by_designator[key_of(pl.designator)].append(pl)

        consumed: set[int] = set()
        results: list[LineResult] = []

        for line in lines:
            candidates = self._candidates_for(line, by_key, by_desc, key_of)
            # avoid double counting when several BOM rows share a key
            fresh = [pl for pl in candidates if id(pl) not in consumed]
            for pl in fresh:
                consumed.add(id(pl))

            top = [pl for pl in fresh if pl.layer is Layer.TOP]
            bot = [pl for pl in fresh if pl.layer is Layer.BOT]

            placed_desigs = {
                key_of(pl.designator) for pl in fresh if pl.designator
            }
            bom_desigs = {key_of(d): d for d in line.designators}
            missing = tuple(
                sorted(
                    (orig for k, orig in bom_desigs.items() if k not in placed_desigs),
                    key=nz.designator_sort_key,
                )
            )
            extra = tuple(
                sorted(
                    (
                        pl.designator
                        for pl in fresh
                        if pl.designator and key_of(pl.designator) not in bom_desigs
                    ),
                    key=nz.designator_sort_key,
                )
                if line.designators
                else ()
            )

            results.append(
                LineResult(
                    line=line,
                    top_count=len(top),
                    bot_count=len(bot),
                    matched_top=tuple(
                        sorted(
                            (pl.designator for pl in top if pl.designator),
                            key=nz.designator_sort_key,
                        )
                    ),
                    matched_bot=tuple(
                        sorted(
                            (pl.designator for pl in bot if pl.designator),
                            key=nz.designator_sort_key,
                        )
                    ),
                    missing_designators=missing,
                    extra_designators=extra,
                )
            )

        orphans = [pl for pl in placements if id(pl) not in consumed]

        duplicates: dict[str, list[str]] = {}
        seen: dict[str, list[Placement]] = defaultdict(list)
        for pl in placements:
            if pl.designator:
                seen[key_of(pl.designator)].append(pl)
        for group in seen.values():
            if len(group) > 1:
                duplicates[group[0].designator] = [
                    f"{g.layer.value}:row{g.source_row}" for g in group
                ]

        ctx = RuleContext(
            profile=p,
            results=results,
            placements=placements,
            placement_index=dict(by_key),
            designator_index=dict(by_designator),
            orphans=orphans,
            duplicates=duplicates,
        )
        return results, ctx

    # ------------------------------------------------------------------
    def _candidates_for(
        self,
        line: BomLine,
        by_key: dict[str, list[Placement]],
        by_desc: dict[str, list[Placement]],
        key_of: Callable[[str], str],
    ) -> list[Placement]:
        p = self.profile
        out: list[Placement] = []

        if p.key_strategy in ("stock_then_part", "stock_only") and line.stock_no:
            out = list(by_key.get(key_of(line.stock_no), ()))
        if (
            not out
            and p.key_strategy in ("stock_then_part", "part_only")
            and line.part_name
        ):
            out = list(by_desc.get(key_of(line.part_name), ()))
        if not out and p.fuzzy_matching and line.part_name:
            target = key_of(line.part_name)
            best, best_score = None, p.fuzzy_threshold
            for k, group in by_desc.items():
                score = nz.similarity(target, k)
                if score >= best_score:
                    best, best_score = group, score
            if best:
                out = list(best)
        if not out and line.designators:
            # last resort: match by explicit designator list
            pass
        return out

    # ------------------------------------------------------------------
    def apply_rules(self, report: ValidationReport, ctx: RuleContext) -> None:
        rules = build_rules(self.profile)
        line_rules = [r for r in rules if r.scope == "line"]
        global_rules = [r for r in rules if r.scope == "global"]

        for result in report.results:
            issues: list[Issue] = []
            for rule in line_rules:
                try:
                    issues.extend(rule.check_line(result, ctx))
                except Exception:  # a broken rule must not kill the run
                    log.exception("Rule %s failed on line %s", rule.code, result.line.key)
            result.issues = sorted(issues, key=lambda i: -i.severity)
            result.status = self._verdict(result)

        for rule in global_rules:
            try:
                report.global_issues.extend(rule.check_global(ctx))
            except Exception:
                log.exception("Global rule %s failed", rule.code)
        report.global_issues.sort(key=lambda i: -i.severity)

    def _verdict(self, result: LineResult) -> Status:
        sev = result.max_severity
        if any(i.code == "NOT_PLACED" for i in result.issues):
            return Status.NOT_PLACED
        if sev >= Severity.ERROR:
            return Status.FAIL
        if sev >= Severity.WARNING:
            return Status.WARN
        return Status.PASS


def validate_file(
    path: str | Path,
    profile: ValidationProfile | None = None,
    **kwargs,
) -> ValidationReport:
    """Convenience one-liner used by the CLI and tests."""
    return BomValidationEngine(profile).run(path, **kwargs)
