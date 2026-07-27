"""Offscreen GUI smoke tests.

Skipped automatically when PyQt6 or a usable Qt platform plugin is missing.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# PyQt6 may be installed yet unusable — a headless container often lacks
# libGL/libEGL/libxkbcommon, which surfaces as an ImportError on the shared
# object rather than a missing module. Skip the whole module in that case
# instead of failing collection.
try:
    from PyQt6.QtCore import Qt, QThreadPool
    from PyQt6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        f"PyQt6 is unavailable in this environment ({exc})",
        allow_module_level=True,
    )

from bom_validator import validate_file  # noqa: E402
from bom_validator.gui import theme as th  # noqa: E402
from bom_validator.gui.i18n import Translator  # noqa: E402
from bom_validator.gui.models_qt import (  # noqa: E402
    DesignatorTableModel,
    IssueTableModel,
    PlacementTableModel,
    ResultFilterProxy,
    ResultTableModel,
)
from bom_validator.models import Status  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def report(make_workbook):
    return validate_file(make_workbook())


class TestTheme:
    @pytest.mark.parametrize("name", th.THEMES)
    def test_stylesheet_renders(self, name):
        css = th.stylesheet(name)
        assert "QMainWindow" in css
        assert "{" in css and "}" in css

    def test_unknown_theme_falls_back(self):
        assert th.stylesheet("nope") == th.stylesheet("industrial-light")

    def test_status_colors(self):
        colors = th.status_colors("industrial-dark")
        assert set(colors) >= {"PASS", "WARN", "FAIL", "NOT_PLACED"}


class TestTranslator:
    def test_persian_default(self):
        tr = Translator("fa")
        assert tr.is_rtl
        assert tr("process") != "process"

    def test_english(self):
        tr = Translator("en")
        assert not tr.is_rtl
        assert tr("status") == "Status"

    def test_unknown_key_returns_key(self):
        assert Translator("en")("no_such_key_xyz") == "no_such_key_xyz"

    def test_unknown_language_falls_back(self):
        assert Translator("zz").language == "en"


class TestResultModel:
    def test_populates(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        assert m.rowCount() == report.summary.total_lines
        assert m.columnCount() == len(ResultTableModel.COLUMNS)

    def test_display_values(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        stocks = {
            m.data(m.index(r, 2), Qt.ItemDataRole.DisplayRole)
            for r in range(m.rowCount())
        }
        assert "1000001" in stocks

    def test_checkbox_signoff(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        idx = m.index(0, 0)
        assert m.data(idx, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
        m.setData(idx, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        assert m.signed_count() == 1
        m.set_all_signed(True)
        assert m.signed_count() == m.rowCount()
        m.set_all_signed(False)
        assert m.signed_count() == 0

    def test_note_editing(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        col = [c[0] for c in ResultTableModel.COLUMNS].index("note")
        idx = m.index(0, col)
        m.setData(idx, "checked by AB", Qt.ItemDataRole.EditRole)
        assert m.data(idx, Qt.ItemDataRole.DisplayRole) == "checked by AB"

    def test_tooltip_is_html(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        tip = m.data(m.index(0, 2), Qt.ItemDataRole.ToolTipRole)
        assert "<b>" in tip

    def test_clear(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        m.set_report(None)
        assert m.rowCount() == 0


class TestFilterProxy:
    def test_text_filter(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_text("Resistor")
        assert 0 < proxy.rowCount() < m.rowCount()
        proxy.set_text("")
        assert proxy.rowCount() == m.rowCount()

    def test_status_filter(self, qapp, make_workbook):
        r = validate_file(make_workbook(top=[], bot=[]))
        m = ResultTableModel(Translator("en"))
        m.set_report(r)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_status_filter([Status.PASS.value])
        assert proxy.rowCount() == 0
        proxy.set_status_filter([Status.NOT_PLACED.value])
        assert proxy.rowCount() == m.rowCount()

    def test_only_failing(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_only_failing(True)
        assert proxy.rowCount() == 0


class TestAuxModels:
    def test_issue_model(self, qapp, make_workbook):
        r = validate_file(make_workbook(top=[], bot=[]))
        m = IssueTableModel()
        m.set_report(r)
        assert m.rowCount() > 0
        assert m.columnCount() == 5

    def test_designator_model(self, qapp, report):
        m = DesignatorTableModel()
        m.set_report(report)
        assert m.rowCount() == report.summary.total_placed

    def test_placement_model(self, qapp, report):
        m = PlacementTableModel()
        m.set_placements(report.orphan_placements)
        assert m.rowCount() == len(report.orphan_placements)


class TestWidgets:
    def test_gauge_clamps(self, qapp):
        from bom_validator.gui.widgets.kpi import GaugeWidget

        g = GaugeWidget()
        g.set_value(500)
        assert g._value == 100.0
        g.set_value(-20)
        assert g._value == 0.0

    def test_kpi_strip(self, qapp, report):
        from bom_validator.gui.widgets.kpi import KpiStrip

        strip = KpiStrip(Translator("en"))
        strip.set_summary(report.summary)
        assert strip.cards["lines"].lbl_value.text() == str(report.summary.total_lines)
        strip.set_summary(None)
        assert strip.cards["lines"].lbl_value.text() == "—"

    def test_board_canvas(self, qapp, make_workbook):
        from bom_validator.config import ValidationProfile
        from bom_validator.gui.widgets.boardmap import BoardMapWidget
        from bom_validator.io_excel import reader as rd
        from bom_validator.models import Layer

        f = make_workbook()
        r = validate_file(f)
        loader = rd.WorkbookLoader(f)
        p = ValidationProfile()
        places = rd.extract_placements(loader.get("top"), Layer.TOP, p)
        places += rd.extract_placements(loader.get("bot"), Layer.BOT, p)
        w = BoardMapWidget(Translator("en"))
        w.set_data(places, r)
        assert len(w.canvas._markers) == len(places)
        w.canvas.zoom_by(2.0)
        assert w.canvas._zoom > 1
        w.canvas.reset_view()
        assert w.canvas._zoom == 1.0
        w.canvas.set_layers(True, False)
        assert sum(1 for m in w.canvas._markers if w.canvas._visible(m)) == 4


class TestMainWindow:
    def test_opens_and_validates(self, qapp, make_workbook, tmp_path):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.settings.auto_process_on_open = True
        w.open_file(str(make_workbook()))
        QThreadPool.globalInstance().waitForDone(60_000)
        for _ in range(40):
            qapp.processEvents()
        assert w.report is not None
        assert w.model.rowCount() == 3
        assert w.issue_model.rowCount() >= 0
        w.close()

    def test_theme_switching(self, qapp):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        for name in th.THEMES:
            w.apply_theme(name)
            assert w.settings.theme == name
        w.toggle_dark()
        w.close()

    def test_tabs_render(self, qapp, make_workbook):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.open_file(str(make_workbook()))
        QThreadPool.globalInstance().waitForDone(60_000)
        for _ in range(40):
            qapp.processEvents()
        for i in range(w.tabs.count()):
            w.tabs.setCurrentIndex(i)
            qapp.processEvents()
        assert w.tabs.count() == 7
        w.close()

    def test_export_from_window(self, qapp, make_workbook, tmp_path):
        from bom_validator.gui.main_window import MainWindow
        from bom_validator.reporting import exporters

        w = MainWindow()
        w.open_file(str(make_workbook()))
        QThreadPool.globalInstance().waitForDone(60_000)
        for _ in range(40):
            qapp.processEvents()
        out = exporters.export(w.report, "html", tmp_path / "x.html")
        assert out.exists()
        w.close()

    def test_missing_file_is_handled(self, qapp, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        from bom_validator.gui.main_window import MainWindow

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
        w = MainWindow()
        w.open_file(str(tmp_path / "ghost.xlsx"))
        assert w.report is None
        w.close()
