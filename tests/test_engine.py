"""End-to-end engine, reader and rule tests."""

import pytest

from bom_validator import ValidationProfile, validate_file
from bom_validator.core.engine import BomValidationEngine
from bom_validator.io_excel import reader as rd
from bom_validator.models import Layer, Status


class TestReader:
    def test_loads_all_sheets(self, make_workbook):
        f = make_workbook()
        loader = rd.WorkbookLoader(f)
        assert set(loader.sheet_names()) >= {"top", "bot"}

    def test_missing_file(self, tmp_path):
        with pytest.raises(rd.WorkbookError):
            rd.WorkbookLoader(tmp_path / "nope.xlsx")

    def test_classify_sheets(self, make_workbook):
        f = make_workbook()
        loader = rd.WorkbookLoader(f)
        buckets = rd.classify_sheets(loader.sheet_names(), ValidationProfile())
        assert buckets["top"] == ["top"]
        assert buckets["bot"] == ["bot"]
        assert buckets["bom"]

    def test_header_detection(self, make_workbook):
        f = make_workbook(header_offset=5)
        loader = rd.WorkbookLoader(f)
        sheet = loader.get("مونتاژ ماشینی")
        mapping = rd.detect_header(sheet, ValidationProfile())
        assert mapping.header_row == 5
        assert mapping.confidence > 0.8
        assert "qty" in mapping.columns
        assert "stock_no" in mapping.columns
        assert "part_name" in mapping.columns

    def test_extract_placements(self, make_workbook):
        f = make_workbook()
        loader = rd.WorkbookLoader(f)
        places = rd.extract_placements(loader.get("top"), Layer.TOP, ValidationProfile())
        assert len(places) == 4
        assert places[0].designator == "C1"
        assert places[0].layer is Layer.TOP
        assert places[0].x == pytest.approx(10.0)
        assert places[0].stock_no == "1000001"

    def test_csv_input(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("Part Name,QTY,Stock No\nCap,3,1001\n", encoding="utf-8")
        loader = rd.WorkbookLoader(p)
        assert len(loader.sheet_names()) == 1


class TestHappyPath:
    def test_all_pass(self, make_workbook):
        report = validate_file(make_workbook())
        assert report.summary.total_lines == 3
        assert report.summary.passed == 3
        assert report.summary.failed == 0
        assert report.summary.health_score == 100.0
        assert report.summary.coverage == pytest.approx(100.0)

    def test_layer_counts(self, make_workbook):
        report = validate_file(make_workbook())
        cap = next(r for r in report.results if r.line.stock_no == "1000001")
        assert cap.top_count == 2
        assert cap.bot_count == 1
        assert cap.placed_total == 3
        assert cap.delta == 0

    def test_report_metadata(self, make_workbook):
        report = validate_file(make_workbook())
        assert len(report.source_sha256) == 64
        assert report.mapping.header_row >= 0
        assert report.duration_ms > 0
        assert report.metadata["sheet_roles"]["top"] == ["top"]


class TestShortage:
    def test_missing_placement_flags_fail(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1, 1, 0, "1000001", "Capacitor 100nF"),
                 ("R1", 2, 2, 0, "1000002", "Resistor 10k"),
                 ("U1", 3, 3, 0, "1000003", "MCU STM32")],
            bot=[("R2", 4, 4, 0, "1000002", "Resistor 10k")],
        )
        report = validate_file(f)
        cap = next(r for r in report.results if r.line.stock_no == "1000001")
        assert cap.status is Status.FAIL
        assert cap.delta == -2
        assert any(i.code == "QTY_MISMATCH" for i in cap.issues)
        assert set(cap.missing_designators) == {"C2", "C3"}

    def test_never_placed_is_critical(self, make_workbook):
        f = make_workbook(
            top=[("R1", 1, 1, 0, "1000002", "Resistor 10k")],
            bot=[("R2", 2, 2, 0, "1000002", "Resistor 10k")],
        )
        report = validate_file(f)
        cap = next(r for r in report.results if r.line.stock_no == "1000001")
        assert cap.status is Status.NOT_PLACED
        assert any(i.code == "NOT_PLACED" for i in cap.issues)

    def test_surplus(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1, 1, 0, "1000001", "Capacitor 100nF"),
                 ("C2", 2, 2, 0, "1000001", "Capacitor 100nF"),
                 ("C4", 3, 3, 0, "1000001", "Capacitor 100nF"),
                 ("R1", 4, 4, 0, "1000002", "Resistor 10k"),
                 ("U1", 5, 5, 0, "1000003", "MCU STM32")],
            bot=[("C3", 6, 6, 0, "1000001", "Capacitor 100nF"),
                 ("R2", 7, 7, 0, "1000002", "Resistor 10k")],
        )
        report = validate_file(f)
        cap = next(r for r in report.results if r.line.stock_no == "1000001")
        assert cap.delta == 1
        assert cap.extra_designators == ("C4",)


class TestOrphans:
    def test_orphan_detected(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1, 1, 0, "1000001", "Capacitor"),
                 ("C2", 2, 2, 0, "1000001", "Capacitor"),
                 ("R1", 3, 3, 0, "1000002", "Resistor 10k"),
                 ("U1", 4, 4, 0, "1000003", "MCU STM32"),
                 ("X9", 9, 9, 0, "9999999", "Mystery part")],
            bot=[("C3", 5, 5, 0, "1000001", "Capacitor"),
                 ("R2", 6, 6, 0, "1000002", "Resistor 10k")],
        )
        report = validate_file(f)
        assert report.summary.orphan_placements == 1
        assert report.orphan_placements[0].designator == "X9"
        assert any(i.code == "ORPHAN_PLACEMENT" for i in report.global_issues)


class TestProfiles:
    def test_tolerance_absorbs_delta(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1, 1, 0, "1000001", "Capacitor 100nF"),
                 ("R1", 2, 2, 0, "1000002", "Resistor 10k"),
                 ("U1", 3, 3, 0, "1000003", "MCU STM32")],
            bot=[("C3", 4, 4, 0, "1000001", "Capacitor 100nF"),
                 ("R2", 5, 5, 0, "1000002", "Resistor 10k")],
        )
        strict = validate_file(f, ValidationProfile(qty_tolerance=0))
        lenient = validate_file(f, ValidationProfile(qty_tolerance=1))
        cap_s = next(r for r in strict.results if r.line.stock_no == "1000001")
        cap_l = next(r for r in lenient.results if r.line.stock_no == "1000001")
        assert any(i.code == "QTY_MISMATCH" for i in cap_s.issues)
        assert not any(i.code == "QTY_MISMATCH" for i in cap_l.issues)

    def test_builtin_profiles_load(self):
        for name in ("default", "strict", "lenient", "smt-ipc"):
            p = ValidationProfile.load_by_name(name)
            assert p.name == name

    def test_roundtrip(self, tmp_path):
        p = ValidationProfile(name="unit", qty_tolerance=7, fuzzy_threshold=0.91)
        path = p.save(tmp_path / "unit.json")
        back = ValidationProfile.load(path)
        assert back.qty_tolerance == 7
        assert back.fuzzy_threshold == pytest.approx(0.91)

    def test_rule_subset(self, make_workbook):
        f = make_workbook(top=[], bot=[])
        p = ValidationProfile(enabled_rules=["QTY_MISMATCH"])
        report = validate_file(f, p)
        codes = {i.code for r in report.results for i in r.issues}
        assert codes <= {"QTY_MISMATCH"}

    def test_disable_orphan_rule(self, make_workbook):
        f = make_workbook(
            top=[("ZZ1", 1, 1, 0, "8888", "Ghost")],
            bot=[],
        )
        p = ValidationProfile(warn_on_orphan_placement=False)
        report = validate_file(f, p)
        assert not any(i.code == "ORPHAN_PLACEMENT" for i in report.global_issues)


class TestGeometryRules:
    def test_off_board_detected(self, make_workbook):
        f = make_workbook(
            top=[("C1", 5000.0, 1.0, 0, "1000001", "Capacitor 100nF")],
            bot=[],
        )
        p = ValidationProfile(board_extent_x=100.0, board_extent_y=100.0)
        report = validate_file(f, p)
        assert any(i.code == "OFF_BOARD" for i in report.global_issues)

    def test_bad_rotation(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1.0, 1.0, 900, "1000001", "Capacitor 100nF")],
            bot=[],
        )
        report = validate_file(f, ValidationProfile(max_rotation=360))
        assert any(i.code == "BAD_ROTATION" for i in report.global_issues)

    def test_coincident(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1.0, 1.0, 0, "1000001", "Capacitor 100nF"),
                 ("C2", 1.0, 1.0, 0, "1000001", "Capacitor 100nF")],
            bot=[],
        )
        report = validate_file(f)
        assert any(i.code == "COINCIDENT" for i in report.global_issues)

    def test_duplicate_designator(self, make_workbook):
        f = make_workbook(
            top=[("C1", 1.0, 1.0, 0, "1000001", "Capacitor 100nF")],
            bot=[("C1", 9.0, 9.0, 0, "1000001", "Capacitor 100nF")],
        )
        report = validate_file(f)
        assert report.summary.duplicate_designators >= 1
        assert any(i.code == "DUP_DESIGNATOR" for i in report.global_issues)


class TestRealWorkbook:
    def test_sample_parses(self, sample_file):
        report = validate_file(sample_file)
        assert report.summary.total_lines > 50
        assert report.summary.total_placed > 500
        assert report.mapping.confidence >= 0.9
        assert report.mapping.sheet_name == "مونتاژ ماشینی"

    def test_sample_is_mostly_clean(self, sample_file):
        report = validate_file(sample_file)
        assert report.summary.pass_rate > 80
        assert report.summary.coverage > 95

    def test_deterministic(self, sample_file):
        a = validate_file(sample_file)
        b = validate_file(sample_file)
        assert a.summary.to_dict() == b.summary.to_dict()
        assert a.source_sha256 == b.source_sha256


class TestErrors:
    def test_no_bom_sheet(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        wb.active.title = "junk"
        wb.active.append(["a", "b"])
        p = tmp_path / "junk.xlsx"
        wb.save(p)
        with pytest.raises(rd.WorkbookError):
            validate_file(p)

    def test_cancellation(self, sample_file):
        engine = BomValidationEngine()
        from bom_validator.core.engine import ValidationCancelled

        with pytest.raises(ValidationCancelled):
            engine.run(sample_file, cancel=lambda: True)
