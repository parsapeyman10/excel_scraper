"""Command line interface — headless validation for CI, batch and shop floor.

Examples
--------
    bomv validate board.xlsx --profile strict --report html:out.html --fail-on error
    bomv validate montaj.xlsx --top-file top.xlsx --bot-file bot.xlsx
    bomv batch ./boards --glob "*.xlsx" --out ./reports --format xlsx,json
    bomv diff old.xlsx new.xlsx --md diff.md
    bomv inspect board.xlsx
    bomv profile list
    bomv history --limit 20
    bomv gui
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import BUILTIN_PROFILES, ValidationProfile, profiles_dir
from .core.diff import diff_reports
from .core.engine import BomValidationEngine, validate_file
from .core.rules import rule_catalog
from .io_excel import reader as rd
from .models import Severity, Status
from .reporting import exporters
from .sources import SourceError, SourceSet
from .storage.history import HistoryStore
from .version import APP_NAME, __version__

log = logging.getLogger("bomv")

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

_SEVERITY_GATES = {
    "never": None,
    "warning": Severity.WARNING,
    "error": Severity.ERROR,
    "critical": Severity.CRITICAL,
}

_C = {
    "ok": "\033[92m",
    "warn": "\033[93m",
    "err": "\033[91m",
    "dim": "\033[90m",
    "b": "\033[1m",
    "0": "\033[0m",
}


def _color(enabled: bool):
    return _C if enabled and sys.stdout.isatty() else dict.fromkeys(_C, "")


# ---------------------------------------------------------------------------


def _resolve_jobs(requested: int, n_files: int) -> int:
    """How many workbooks to process concurrently."""
    import os

    if requested and requested > 0:
        return max(1, min(requested, n_files))
    if requested == 0:  # auto
        return max(1, min((os.cpu_count() or 2), n_files, 8))
    return 1


def _load_profile(name_or_path: str | None) -> ValidationProfile:
    if not name_or_path:
        return ValidationProfile()
    p = Path(name_or_path)
    if p.exists() and p.suffix == ".json":
        return ValidationProfile.load(p)
    return ValidationProfile.load_by_name(name_or_path)


def _apply_overrides(profile: ValidationProfile, args: argparse.Namespace) -> None:
    if getattr(args, "tolerance", None) is not None:
        profile.qty_tolerance = args.tolerance
    if getattr(args, "no_fuzzy", False):
        profile.fuzzy_matching = False
    if getattr(args, "rules", None):
        profile.enabled_rules = [r.strip() for r in args.rules.split(",") if r.strip()]
    if getattr(args, "bom_sheet", None):
        profile.bom_sheet_patterns = [args.bom_sheet]
    if getattr(args, "top_sheet", None):
        profile.top_sheet_patterns = [args.top_sheet]
    if getattr(args, "bot_sheet", None):
        profile.bot_sheet_patterns = [args.bot_sheet]


def _sources_from_args(args: argparse.Namespace) -> SourceSet:
    """Build the input set: one workbook, or BOM + top + bot files."""
    top = getattr(args, "top_file", None)
    bot = getattr(args, "bot_file", None)
    if top or bot:
        return SourceSet.multi(args.file, top, bot).validate()
    return SourceSet.single(args.file).validate()


def _print_summary(report, colored: bool = True) -> None:
    c = _color(colored)
    s = report.summary
    print(f"\n{c['b']}{report.source_label}{c['0']}  "
          f"{c['dim']}profile={report.profile_name} "
          f"sheet='{report.mapping.sheet_name}' "
          f"conf={report.mapping.confidence:.0%} "
          f"{report.duration_ms:.0f} ms{c['0']}")
    print(
        f"  lines {s.total_lines}   "
        f"{c['ok']}pass {s.passed}{c['0']}   "
        f"{c['warn']}warn {s.warnings}{c['0']}   "
        f"{c['err']}fail {s.failed}{c['0']}   "
        f"{c['err']}unplaced {s.not_placed}{c['0']}"
    )
    print(
        f"  required {s.total_required}  placed {s.total_placed} "
        f"(top {s.top_placed} / bot {s.bot_placed})  "
        f"coverage {s.coverage:.1f}%  health {c['b']}{s.health_score:.1f}{c['0']}/100"
    )
    if s.orphan_placements:
        print(f"  {c['warn']}orphan placements: {s.orphan_placements}{c['0']}")


def _print_findings(report, limit: int, colored: bool = True) -> None:
    c = _color(colored)
    bad = report.failing
    if not bad and not report.global_issues:
        print(f"  {c['ok']}✓ no findings{c['0']}")
        return
    if bad:
        print(f"\n  {c['b']}Line findings ({len(bad)}){c['0']}")
        for r in bad[:limit]:
            tint = c["err"] if r.status in (Status.FAIL, Status.NOT_PLACED) else c["warn"]
            print(
                f"   {tint}{r.status.value:<11}{c['0']} "
                f"{(r.line.stock_no or r.line.part_name)[:22]:<22} "
                f"qty={r.line.qty:<5} placed={r.placed_total:<5} Δ={r.delta:+d}"
            )
            for i in r.issues[:3]:
                print(f"      {c['dim']}{i.code}: {i.message[:110]}{c['0']}")
        if len(bad) > limit:
            print(f"   {c['dim']}… {len(bad) - limit} more{c['0']}")
    if report.global_issues:
        print(f"\n  {c['b']}Global findings ({len(report.global_issues)}){c['0']}")
        for i in report.global_issues[:limit]:
            print(f"   {c['warn']}{i.severity.label:<9}{c['0']} {i.code}: {i.message[:110]}")
        if len(report.global_issues) > limit:
            print(f"   {c['dim']}… {len(report.global_issues) - limit} more{c['0']}")


def _gate(report, gate: str) -> int:
    threshold = _SEVERITY_GATES.get(gate)
    if threshold is None:
        return EXIT_OK
    worst = Severity.INFO
    for r in report.results:
        worst = max(worst, r.max_severity)
    for i in report.global_issues:
        worst = max(worst, i.severity)
    return EXIT_FINDINGS if worst >= threshold else EXIT_OK


def _write_reports(report, specs: Sequence[str], out_dir: Path | None) -> list[Path]:
    written = []
    for spec in specs:
        if ":" in spec:
            fmt, target = spec.split(":", 1)
        else:
            fmt, target = spec, ""
        fmt = fmt.strip().lower()
        if target:
            path = Path(target)
        else:
            base = out_dir or Path.cwd()
            path = base / exporters.default_filename(report, fmt)
        written.append(exporters.export(report, fmt, path))
    return written


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile)
    _apply_overrides(profile, args)
    engine = BomValidationEngine(profile)

    def progress(done: int, total: int, msg: str) -> None:
        if args.verbose:
            print(f"\r  [{done:>3}/{total}] {msg:<28}", end="", file=sys.stderr)

    try:
        sources = _sources_from_args(args)
        report = engine.run(sources, progress=progress if args.verbose else None)
    except (rd.WorkbookError, SourceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if args.verbose:
        print(file=sys.stderr)

    if args.json_only:
        print(report.to_json())
    else:
        _print_summary(report, not args.no_color)
        if not args.quiet:
            _print_findings(report, args.limit, not args.no_color)

    if args.report:
        for p in _write_reports(report, args.report, Path(args.out) if args.out else None):
            if not args.json_only:
                print(f"  → wrote {p}")

    if not args.no_history:
        try:
            HistoryStore().save(report, operator=args.operator or "")
        except Exception as exc:
            log.warning("Could not record history: %s", exc)

    return _gate(report, args.fail_on)


def cmd_batch(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile)
    _apply_overrides(profile, args)
    root = Path(args.directory)
    files = sorted(
        f
        for pattern in args.glob.split(",")
        for f in root.rglob(pattern.strip())
        if f.is_file() and not f.name.startswith("~$")
    )
    if not files:
        print(f"error: no files matching {args.glob!r} under {root}", file=sys.stderr)
        return EXIT_ERROR

    out_dir = Path(args.out) if args.out else root / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    store = HistoryStore() if not args.no_history else None
    jobs = _resolve_jobs(getattr(args, "jobs", 0), len(files))

    def work(path: Path):
        # one engine per file so worker threads never share mutable state
        report = BomValidationEngine(profile).run(path)
        for fmt in formats:
            exporters.export(report, fmt, out_dir / exporters.default_filename(report, fmt))
        return report

    worst = EXIT_OK
    rows = []
    results: list[tuple[Path, Any]] = []

    if jobs > 1:
        import concurrent.futures as _cf

        with _cf.ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="batch") as ex:
            futures = {ex.submit(work, f): f for f in files}
            for fut in _cf.as_completed(futures):
                f = futures[fut]
                try:
                    results.append((f, fut.result()))
                except Exception as exc:
                    print(f"  ✗ {f.name}: {exc}", file=sys.stderr)
                    worst = EXIT_ERROR
        # deterministic output order regardless of completion order
        results.sort(key=lambda kv: files.index(kv[0]))
    else:
        for f in files:
            try:
                results.append((f, work(f)))
            except Exception as exc:
                print(f"  ✗ {f.name}: {exc}", file=sys.stderr)
                worst = EXIT_ERROR

    for f, report in results:
        _print_summary(report, not args.no_color)
        if store:
            store.save(report, operator=args.operator or "")
        rows.append(
            {
                "file": f.name,
                "lines": report.summary.total_lines,
                "passed": report.summary.passed,
                "failed": report.summary.failed,
                "not_placed": report.summary.not_placed,
                "health": round(report.summary.health_score, 1),
            }
        )
        worst = max(worst, _gate(report, args.fail_on))

    index = out_dir / "batch_summary.json"
    index.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(
        f"\nProcessed {len(rows)} file(s) with {jobs} worker(s) → {out_dir}"
    )
    return worst


def cmd_diff(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile)
    old = validate_file(args.old, profile)
    new = validate_file(args.new, profile)
    d = diff_reports(old, new)
    if args.json:
        Path(args.json).write_text(
            json.dumps(d.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    if args.md:
        Path(args.md).write_text(d.to_markdown(), encoding="utf-8")
        print(f"wrote {args.md}")
    if not args.json and not args.md:
        print(d.to_markdown())
    return EXIT_FINDINGS if d.total_changes else EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile)
    sources = _sources_from_args(args)
    print(f"\n{APP_NAME} — workbook inspection\n{'=' * 60}")
    print(f"Mode   : {sources.mode}")
    for file_path in sources.paths:
        loader = rd.WorkbookLoader(file_path)
        buckets = rd.classify_sheets(loader.sheet_names(), profile)
        print(f"\nFile   : {file_path}  [{sources.role_of(file_path)}]")
        print(f"Sheets : {len(loader.sheet_names())}")
        for role, names in buckets.items():
            if names:
                print(f"  {role:<6}: {', '.join(names)}")
        for name, sheet in loader.sheets.items():
            mapping = rd.detect_header(sheet, profile)
            print(f"\n--- {name}  ({len(sheet)} rows × {sheet.width} cols)")
            if mapping.header_row >= 0:
                print(
                    f"    header row {mapping.header_row + 1}, "
                    f"confidence {mapping.confidence:.0%}"
                )
                for field_name, idx in sorted(
                    mapping.columns.items(), key=lambda kv: kv[1]
                ):
                    header = sheet.cell(mapping.header_row, idx)
                    print(f"      {field_name:<12} → col {idx:>3}  {str(header)[:40]!r}")
            else:
                print("    no header detected")
            if args.preview:
                for row in rd.iter_preview(sheet, rows=args.preview, cols=12):
                    print(
                        "      "
                        + " | ".join(
                            str(v)[:16] if v is not None else "" for v in row
                        )
                    )
    return EXIT_OK


def cmd_profile(args: argparse.Namespace) -> int:
    if args.action == "list":
        print("Available profiles:")
        for name in ValidationProfile.list_available():
            builtin = " (builtin)" if name in BUILTIN_PROFILES else ""
            try:
                p = ValidationProfile.load_by_name(name)
                print(f"  {name:<14}{builtin:<11} {p.description}")
            except Exception:
                print(f"  {name:<14}{builtin}")
        print(f"\nUser profiles live in: {profiles_dir()}")
    elif args.action == "show":
        p = _load_profile(args.name)
        print(json.dumps(p.to_dict(), ensure_ascii=False, indent=2))
    elif args.action == "init":
        p = _load_profile(args.base or "default")
        p.name = args.name or "custom"
        p.description = f"Derived from {args.base or 'default'}"
        target = p.save(args.output)
        print(f"wrote {target}")
    elif args.action == "rules":
        print(f"{'CODE':<20}{'SEV':<10}{'SCOPE':<8}TITLE")
        for r in rule_catalog():
            print(f"{r['code']:<20}{r['severity']:<10}{r['scope']:<8}{r['title']}")
    return EXIT_OK


def cmd_history(args: argparse.Namespace) -> int:
    store = HistoryStore()
    if args.purge is not None:
        removed = store.purge(args.purge)
        print(f"purged {removed} old run(s)")
        return EXIT_OK
    if args.stats:
        print(json.dumps(store.stats(), indent=2))
        return EXIT_OK
    runs = store.recent(args.limit, args.file)
    if not runs:
        print("no runs recorded yet")
        return EXIT_OK
    print(f"{'ID':<6}{'WHEN':<22}{'FILE':<34}{'LINES':>6}{'PASS':>6}{'FAIL':>6}{'HEALTH':>8}")
    for r in runs:
        print(
            f"{r.id:<6}{r.created_at[:19]:<22}{r.source_name[:33]:<34}"
            f"{r.total_lines:>6}{r.passed:>6}{r.failed:>6}{r.health_score:>8.1f}"
        )
    return EXIT_OK


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui.app import run_gui

    return run_gui(args.file)


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bomv",
        description=f"{APP_NAME} v{__version__} — BOM integrity & placement validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true", help="verbose progress")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    sub = ap.add_subparsers(dest="command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-color", action="store_true", help="disable ANSI colours")
        p.add_argument("-v", "--verbose", action="store_true", help="verbose progress")

    def add_profile_opts(p: argparse.ArgumentParser) -> None:
        add_common(p)
        p.add_argument("-p", "--profile", help="profile name or .json path")
        p.add_argument("--tolerance", type=int, help="override quantity tolerance")
        p.add_argument("--no-fuzzy", action="store_true", help="disable fuzzy matching")
        p.add_argument("--rules", help="comma separated rule codes to enable")
        p.add_argument("--bom-sheet", help="explicit BOM sheet name pattern")
        p.add_argument("--top-sheet", help="explicit top sheet name pattern")
        p.add_argument("--bot-sheet", help="explicit bottom sheet name pattern")

    v = sub.add_parser(
        "validate",
        help="validate one workbook, or a BOM plus separate top/bot files",
    )
    v.add_argument("file", help="the workbook (or, with --top-file/--bot-file, the BOM)")
    add_profile_opts(v)
    v.add_argument(
        "-r", "--report", action="append", default=[],
        help="format[:path] — xlsx, csv, json, html, md, junit, pdf (repeatable)",
    )
    v.add_argument("-o", "--out", help="output directory for reports")
    v.add_argument("--fail-on", choices=list(_SEVERITY_GATES), default="error")
    v.add_argument("--limit", type=int, default=25, help="max findings printed")
    v.add_argument("--json-only", action="store_true", help="print machine JSON only")
    v.add_argument("-q", "--quiet", action="store_true", help="summary only")
    v.add_argument(
        "--top-file",
        help="separate TOP pick-and-place file (three-file mode)",
    )
    v.add_argument(
        "--bot-file",
        help="separate BOT pick-and-place file (three-file mode)",
    )
    v.add_argument("--operator", help="operator name recorded in history")
    v.add_argument("--no-history", action="store_true")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("batch", help="validate every workbook in a folder")
    b.add_argument("directory")
    add_profile_opts(b)
    b.add_argument("--glob", default="*.xlsx", help="comma separated glob patterns")
    b.add_argument("-o", "--out", help="report output directory")
    b.add_argument("-f", "--format", default="xlsx,json", help="comma separated formats")
    b.add_argument("--fail-on", choices=list(_SEVERITY_GATES), default="error")
    b.add_argument("--operator")
    b.add_argument("--no-history", action="store_true")
    b.add_argument(
        "-j", "--jobs", type=int, default=0,
        help="parallel workers (0 = auto, 1 = sequential)",
    )
    b.set_defaults(func=cmd_batch)

    d = sub.add_parser("diff", help="compare two workbooks")
    add_common(d)
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("-p", "--profile")
    d.add_argument("--json", help="write JSON diff here")
    d.add_argument("--md", help="write Markdown diff here")
    d.set_defaults(func=cmd_diff)

    i = sub.add_parser("inspect", help="show sheets, detected headers and a preview")
    add_common(i)
    i.add_argument("file")
    i.add_argument("-p", "--profile")
    i.add_argument("--preview", type=int, default=0, help="preview N rows per sheet")
    i.add_argument("--top-file", help="separate TOP placement file")
    i.add_argument("--bot-file", help="separate BOT placement file")
    i.set_defaults(func=cmd_inspect)

    pr = sub.add_parser("profile", help="manage validation profiles")
    add_common(pr)
    pr.add_argument("action", choices=["list", "show", "init", "rules"])
    pr.add_argument("name", nargs="?")
    pr.add_argument("--base", help="profile to derive from")
    pr.add_argument("-o", "--output", help="output path for init")
    pr.set_defaults(func=cmd_profile)

    h = sub.add_parser("history", help="browse the local audit trail")
    add_common(h)
    h.add_argument("--limit", type=int, default=25)
    h.add_argument("--file", help="filter by source file name")
    h.add_argument("--stats", action="store_true")
    h.add_argument("--purge", type=int, nargs="?", const=500, help="keep only N newest")
    h.set_defaults(func=cmd_history)

    g = sub.add_parser("gui", help="launch the desktop application")
    add_common(g)
    g.add_argument("file", nargs="?")
    g.set_defaults(func=cmd_gui)

    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not getattr(args, "command", None):
        # no subcommand → open the GUI, like a normal desktop app
        try:
            from .gui.app import run_gui

            return run_gui(None)
        except Exception:
            ap.print_help()
            return EXIT_OK
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except Exception as exc:
        log.exception("Unhandled error")
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
