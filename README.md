# Industrial BOM Validator

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

Reconciles an electronic **Bill of Material** against the **SMT pick-and-place**
files for both board layers — line by line, designator by designator — and tells
you exactly which components will stop the line before the line stops.

Originally a 300-line Excel scraper, now a full validation platform: a PyQt6
desktop application, a headless CLI for CI pipelines, a pluggable rule engine,
seven report formats and a local audit trail.

---

## What it does

Given one workbook containing a BOM sheet plus `top` / `bot` placement sheets, it:

1. **Finds the sheets automatically** — Persian or English names, fuzzy matched.
2. **Detects the header row** with a confidence score, merging split
   sub-headers (the classic `Stock No.` sitting one row below the banner).
3. **Normalises everything** — Persian/Arabic digits, Arabic yeh/kaf, zero-width
   joiners, Excel's `1110101.0` float artefacts.
4. **Expands designator ranges** — `C1-C10` becomes ten references.
5. **Matches** each BOM line to its placements by stock number, then description,
   then fuzzy similarity.
6. **Applies twelve rules** and produces a per-line verdict plus a 0–100 health score.
7. **Exports** to Excel, HTML, PDF, CSV, JSON, Markdown or JUnit XML.

---

## Screens

| Results grid | Board map |
|---|---|
| Every BOM line colour-coded PASS / WARN / FAIL / NOT PLACED, with a live detail pane listing which exact designators are missing. | Interactive PCB placement map — pan, zoom, filter by layer, click a component to jump to its BOM row. |

| Dashboard | Reports |
|---|---|
| Health gauge, finding distribution donut, and a historical trend line for the board. | Formatted multi-sheet Excel with charts, or a self-contained interactive HTML report. |

---

## Install

```bash
git clone https://github.com/parsapeyman10/excel_scraper
cd excel_scraper
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[all]"
```

Core validation only needs `openpyxl`. `PyQt6` is required for the desktop app,
`pandas` only for legacy `.xls` files.

---

## Use

### Desktop

```bash
bom-validator                      # or: python -m bom_validator
bom-validator board.xlsx           # open a file directly
```

### Command line

```bash
# validate and gate a CI build
bomv validate board.xlsx --profile strict --fail-on error

# write several reports at once
bomv validate board.xlsx -r xlsx:out.xlsx -r html:out.html -r junit:results.xml

# validate an entire folder (parallel by default; -j 1 forces sequential)
bomv batch ./boards --glob "*.xlsx" --out ./reports --format xlsx,json
bomv batch ./boards -j 8

# compare two revisions
bomv diff rev_a.xlsx rev_b.xlsx --md changes.md

# see how the workbook was interpreted before trusting the result
bomv inspect board.xlsx --preview 12

# manage profiles and inspect the rule catalog
bomv profile list
bomv profile rules
bomv profile init myplant --base strict

# browse the audit trail
bomv history --limit 20 --stats
```

Exit codes: `0` clean, `1` findings at or above `--fail-on`, `2` hard error.

### Python API

```python
from bom_validator import validate_file, ValidationProfile

report = validate_file("board.xlsx", ValidationProfile.load_by_name("strict"))

print(report.summary.health_score)          # 95.0
for line in report.failing:
    print(line.line.stock_no, line.status.value, line.missing_designators)

from bom_validator.reporting import exporters
exporters.export(report, "html", "report.html")
```

---

## Performance

The pipeline is tuned so the app feels instant on the shop floor, and every
long operation runs off the UI thread.

| Where | What changed |
|---|---|
| Workbook loading | Parsed grids are memoised in a byte-budgeted LRU cache keyed by path + mtime + size, so the preview, the validation run and the board map share a single parse instead of three. Concurrent first-time loads of the same file are de-duplicated. |
| Header detection | Synonym tables are normalised once (not once per cell) and each sheet memoises its detected mapping per profile. |
| Text normalisation | `clean()` has a fast path for the plain-ASCII cells that dominate real workbooks; `canonical()`, `header_key()`, designator expansion and similarity are all memoised. |
| Fuzzy matching | `similarity_at_least()` discards hopeless candidates with an O(n) upper-bound probe before running the O(n·m) matcher — same scores, far fewer comparisons. |
| Batch / CLI | `bomv batch` processes files on a thread pool (`-j`), with output ordered deterministically regardless of completion order. |
| GUI | Workbook parsing, validation, comparison, export and history writes all run on `QThreadPool`. The results table pre-computes its display and search strings, shares brushes and fonts, and the search box is debounced. |

Measured on this repo's sample plus two synthetic workbooks (4 000 BOM lines /
14 000 placements, and a fuzzy-match-heavy 600-line board):

| Workbook | Before | After |
|---|---|---|
| Sample board | 0.11 s | 0.10 s (0.01 s cached) |
| 4 000 lines, 14 000 placements | 1.70 s | 1.50 s (0.37 s cached) |
| Fuzzy-match heavy | 6.37 s | 1.41 s |

Every optimisation is output-preserving: the test suite asserts byte-identical
reports against the previous implementation for all built-in profiles.

Caches are process-local and can be dropped at any time:

```python
from bom_validator import clear_caches
clear_caches()
```

---

## Validation rules

| Code | Severity | What it catches |
|---|---|---|
| `QTY_MISMATCH` | Error | BOM quantity ≠ number of placements (with configurable tolerance) |
| `NOT_PLACED` | Critical | A required component has zero placements anywhere |
| `ZERO_QTY` | Error | A BOM line declares a zero or negative quantity |
| `DESIG_COUNT` | Warning | Designator list length disagrees with the declared quantity |
| `DESIG_MISMATCH` | Error | Specific designators in the BOM were never placed, or vice versa |
| `DUP_DESIGNATOR` | Error | The same reference appears twice across the two layers |
| `DUP_STOCK` | Warning | One stock number is spread across multiple BOM rows |
| `MISSING_STOCK` | Warning | A line has no stock number and fell back to name matching |
| `ORPHAN_PLACEMENT` | Error | The machine will place something the BOM never ordered |
| `BAD_ROTATION` | Warning | Rotation outside the allowed range |
| `OFF_BOARD` | Error | X/Y coordinates fall outside the declared board outline |
| `COINCIDENT` | Warning | Two parts share identical coordinates on the same layer |
| `DESC_DRIFT` | Warning | Placement description diverges from the BOM description |
| `LAYER_SPLIT` | Info | A part is populated on both sides |

Enable, disable or re-weight any of them per profile.

---

## Profiles

Profiles encode a plant's conventions: sheet naming, column synonyms, tolerances,
which rules run, board geometry.

| Built-in | Intent |
|---|---|
| `default` | Balanced settings for everyday use |
| `strict` | Zero tolerance, no fuzzy matching — release gate |
| `lenient` | Prototype runs, ±1 tolerance, orphans ignored |
| `smt-ipc` | Adds geometric checks against a 300×300 mm outline |

Custom profiles are plain JSON in the user data directory
(`~/.local/share/bom-validator/profiles` on Linux, `%APPDATA%\bom-validator` on
Windows). Create one from the GUI (`Tools → Validation profiles`) or with
`bomv profile init`.

```jsonc
{
  "name": "myplant",
  "qty_tolerance": 0,
  "bom_sheet_patterns": ["مونتاژ", "bom"],
  "column_synonyms": { "stock_no": ["stockno", "sapcode", "کدانبار"] },
  "enabled_rules": ["QTY_MISMATCH", "NOT_PLACED", "ORPHAN_PLACEMENT"],
  "board_extent_x": 160.0,
  "board_extent_y": 100.0
}
```

---

## Architecture

```
bom_validator/
├── models.py            immutable domain types (BomLine, Placement, Issue…)
├── config.py            profiles, app settings, cross-platform data dirs
├── cli.py               argparse CLI: validate | batch | diff | inspect | …
├── core/
│   ├── normalize.py     unicode/digit folding, designator range expansion
│   ├── rules.py         the pluggable rule registry
│   ├── engine.py        orchestration: read → match → judge
│   └── diff.py          revision-to-revision comparison
├── io_excel/reader.py   openpyxl reader, sheet classifier, header detector
├── reporting/           xlsx · html · pdf · csv · json · md · junit
├── storage/history.py   SQLite audit trail with trend queries
└── gui/                 PyQt6: main window, Qt models, themes, board map
```

The core has **no Qt dependency** — it runs identically in a container, a
notebook or a CI job.

### Adding your own rule

```python
from bom_validator.core.rules import Rule, register
from bom_validator.models import Severity

@register
class MoistureSensitiveRule(Rule):
    code = "MSL_CHECK"
    title = "MSL part on the bottom side"
    severity = Severity.WARNING

    def check_line(self, result, ctx):
        if "BGA" in result.line.material.upper() and result.bot_count:
            yield self.issue("MSL-rated BGA populated on the bottom side.",
                             result.line.key)
```

It appears immediately in the GUI rule list, the CLI catalog and every report.

---

## Development

```bash
pip install -e ".[dev,all]"
pytest                      # 193 tests
pytest --cov=bom_validator  # with coverage
ruff check bom_validator
mypy bom_validator
```

GUI tests run headless via `QT_QPA_PLATFORM=offscreen` and skip automatically
when Qt is unavailable (including when PyQt6 is installed but the container
lacks `libGL`/`libEGL`).

### Continuous integration

A ready-to-use GitHub Actions workflow lives at
[`docs/github-actions-ci.yml`](docs/github-actions-ci.yml). It is shipped as a
template rather than an active workflow; copy it into place to enable it:

```bash
mkdir -p .github/workflows
cp docs/github-actions-ci.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml && git commit -m "Enable CI"
```

It runs ruff and the full suite on Python 3.10–3.12, installs the Qt system
libraries needed for the offscreen GUI tests, and uploads the generated
reports as build artifacts.

---

## Migration from `excel scraper.py`

The old script still works — it now forwards to the new GUI. Behavioural changes
worth knowing:

- Matching is layer-aware and consumes each placement exactly once, so a stock
  number used on several BOM rows no longer double-counts.
- Header detection scans 25 rows and merges sub-headers instead of assuming
  the first 15.
- `nan`, `1110101.0` and Persian digits are normalised before comparison, which
  removes a large class of false FAILs.
- The verdict is a four-state status rather than PASS/FAIL, so a description
  mismatch no longer looks like a quantity error.

---

## License

MIT
