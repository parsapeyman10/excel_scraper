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


def _drain(qapp, predicate, timeout_ms: int = 30_000) -> bool:
    """Spin the event loop until *predicate* holds (or we give up)."""
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(50)
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestBackgroundWorkers:
    def test_workbook_load_worker(self, qapp, make_workbook):
        from bom_validator.gui.workers import WorkbookLoadWorker

        got: list = []
        worker = WorkbookLoadWorker(str(make_workbook()))
        worker.signals.finished.connect(lambda loader, names: got.append(names))
        worker.signals.failed.connect(lambda m: got.append(m))
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(got))
        assert "top" in got[0] and "bot" in got[0]

    def test_workbook_load_worker_reports_failure(self, qapp, tmp_path):
        from bom_validator.gui.workers import WorkbookLoadWorker

        failures: list[str] = []
        worker = WorkbookLoadWorker(str(tmp_path / "missing.xlsx"))
        worker.signals.failed.connect(failures.append)
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(failures))
        assert "missing.xlsx" in failures[0]

    def test_validation_worker_returns_placements(self, qapp, make_workbook):
        from bom_validator.config import ValidationProfile
        from bom_validator.gui.workers import ValidationWorker

        done: list[tuple] = []
        worker = ValidationWorker(str(make_workbook()), ValidationProfile())
        worker.signals.finished.connect(lambda r, p: done.append((r, p)))
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(done))
        report, placements = done[0]
        assert report.summary.total_lines == 3
        assert len(placements) == 6

    def test_validation_worker_can_be_cancelled(self, qapp, make_workbook):
        from bom_validator.config import ValidationProfile
        from bom_validator.gui.workers import ValidationWorker

        events: list[str] = []
        worker = ValidationWorker(str(make_workbook()), ValidationProfile())
        worker.signals.cancelled.connect(lambda: events.append("cancelled"))
        worker.signals.finished.connect(lambda *_: events.append("finished"))
        worker.cancel()
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(events))
        assert events == ["cancelled"]

    def test_history_save_worker(self, qapp, make_workbook, tmp_path):
        from bom_validator.gui.workers import HistorySaveWorker
        from bom_validator.storage.history import HistoryStore

        store = HistoryStore(tmp_path / "h.sqlite3")
        report = validate_file(make_workbook())
        ids: list[int] = []
        worker = HistorySaveWorker(store, report, "operator-1")
        worker.signals.finished.connect(ids.append)
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(ids))
        assert ids[0] > 0
        assert store.recent(5)[0].operator == "operator-1"

    def test_batch_worker_processes_every_file(self, qapp, make_workbook, tmp_path):
        from bom_validator.config import ValidationProfile
        from bom_validator.gui.workers import BatchWorker

        files = [str(make_workbook(f"batch{i}.xlsx")) for i in range(4)]
        out = tmp_path / "reports"
        counts: list[int] = []
        seen: list[str] = []
        worker = BatchWorker(files, ValidationProfile(), str(out), ["json"], workers=3)
        worker.signals.file_done.connect(lambda f, r: seen.append(f))
        worker.signals.finished.connect(counts.append)
        QThreadPool.globalInstance().start(worker)
        assert _drain(qapp, lambda: bool(counts))
        assert counts[0] == 4
        assert sorted(seen) == sorted(files)
        assert len(list(out.glob("*.json"))) == 4


class TestSearchModel:
    def test_multi_token_search_is_anded(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_text("resistor 10k")
        assert proxy.rowCount() == 1
        proxy.set_text("resistor capacitor")
        assert proxy.rowCount() == 0

    def test_search_is_case_insensitive(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_text("MCU")
        assert proxy.rowCount() == 1

    def test_haystack_tracks_note_edits(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        col = [c[0] for c in ResultTableModel.COLUMNS].index("note")
        m.setData(m.index(0, col), "needs rework", Qt.ItemDataRole.EditRole)
        proxy = ResultFilterProxy()
        proxy.setSourceModel(m)
        proxy.set_text("rework")
        assert proxy.rowCount() == 1

    def test_shared_brushes_are_reused(self, qapp, report):
        m = ResultTableModel(Translator("en"))
        m.set_report(report)
        a = m.data(m.index(0, 1), Qt.ItemDataRole.BackgroundRole)
        b = m.data(m.index(0, 2), Qt.ItemDataRole.BackgroundRole)
        assert a is b


class TestWindowAsyncLoading:
    def test_sheet_list_populates_asynchronously(self, qapp, make_workbook):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.open_file(str(make_workbook()))
        assert _drain(qapp, lambda: w.cmb_sheet.count() > 0)
        names = [w.cmb_sheet.itemText(i) for i in range(w.cmb_sheet.count())]
        assert "top" in names and "bot" in names
        w.close()

    def test_stale_load_is_ignored(self, qapp, make_workbook):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.current_file = "/some/other/file.xlsx"
        w._on_workbook_loaded("/an/older/file.xlsx", {}, ["ghost"])
        assert w.cmb_sheet.count() == 0
        w.close()

    def test_repeated_theme_apply_is_a_noop(self, qapp):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.apply_theme("industrial-dark")
        css = w.styleSheet()
        w.apply_theme("industrial-dark")
        assert w.styleSheet() == css
        w.apply_theme("industrial-light")
        assert w.styleSheet() != css
        w.close()


class TestAsyncDiff:
    def test_compare_runs_off_the_ui_thread(self, qapp, make_workbook, monkeypatch):
        from PyQt6.QtWidgets import QDialog, QFileDialog

        from bom_validator.gui.main_window import MainWindow

        a = str(make_workbook("rev_a.xlsx"))
        b = str(make_workbook("rev_b.xlsx", lines=[
            ("1", "C1, C2, C3", "Capacitor 100nF", "SMD", "0402", 3, "ACME", "1000001"),
        ]))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *x, **k: (b, ""))
        monkeypatch.setattr(QDialog, "exec", lambda self: 0)

        w = MainWindow()
        w.open_file(a)
        assert _drain(qapp, lambda: w.report is not None)
        w.compare_revision()
        assert _drain(qapp, lambda: "change" in w.statusBar().currentMessage())
        w.close()

    def test_compare_failure_is_reported(self, qapp, make_workbook, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from bom_validator.gui.main_window import MainWindow

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *x, **k: ("/no/such/file.xlsx", "")
        )
        shown: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "critical", lambda *a, **k: shown.append(str(a[2]))
        )
        w = MainWindow()
        w.open_file(str(make_workbook()))
        assert _drain(qapp, lambda: w.report is not None)
        w.compare_revision()
        assert _drain(qapp, lambda: bool(shown))
        assert "file.xlsx" in shown[0].lower()
        w.close()


class TestSourcePanel:
    def _panel(self):
        from bom_validator.gui.widgets.sources import SourcePanel

        return SourcePanel(Translator("en"))

    def test_starts_in_single_mode_and_empty(self, qapp):
        p = self._panel()
        assert p.mode == "single"
        assert p.sources() is None
        assert not p.is_ready()

    def test_single_mode_selection(self, qapp, make_workbook):
        p = self._panel()
        f = make_workbook()
        p.slot_workbook.set_path(str(f))
        src = p.sources()
        assert src is not None and not src.is_multi
        assert src.primary == f.resolve()
        assert p.is_ready()

    def test_multi_mode_needs_a_placement_file(self, qapp, make_split_workbooks):
        from bom_validator.sources import SourceError

        bom, _top, _bot = make_split_workbooks()
        p = self._panel()
        p.set_mode("multi")
        p.slot_bom.set_path(str(bom))
        with pytest.raises(SourceError):
            p.sources()
        assert not p.is_ready()

    def test_multi_mode_three_slots(self, qapp, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        p = self._panel()
        p.set_mode("multi")
        p.slot_bom.set_path(str(bom))
        p.slot_top.set_path(str(top))
        p.slot_bot.set_path(str(bot))
        src = p.sources()
        assert src.is_multi
        assert src.top == top.resolve() and src.bot == bot.resolve()
        assert p.is_ready()

    def test_switching_mode_keeps_each_selection(self, qapp, make_workbook,
                                                 make_split_workbooks):
        bom, top, _ = make_split_workbooks()
        single = make_workbook()
        p = self._panel()
        p.slot_workbook.set_path(str(single))
        p.set_mode("multi")
        p.slot_bom.set_path(str(bom))
        p.slot_top.set_path(str(top))
        assert p.sources().is_multi
        p.set_mode("single")
        assert p.sources().primary == single.resolve()

    def test_clearing_an_optional_slot(self, qapp, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        p = self._panel()
        p.set_mode("multi")
        p.slot_bom.set_path(str(bom))
        p.slot_top.set_path(str(top))
        p.slot_bot.set_path(str(bot))
        p.slot_bot.clear()
        assert p.sources().bot is None

    def test_set_sources_restores_the_layout(self, qapp, make_split_workbooks):
        from bom_validator.sources import SourceSet

        bom, top, bot = make_split_workbooks()
        p = self._panel()
        p.set_sources(SourceSet.multi(bom, top, bot))
        assert p.mode == "multi"
        assert p.stack.currentIndex() == 1
        assert p.sources().bot == bot.resolve()

    def test_hint_only_shows_problems(self, qapp, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        p = self._panel()
        p.set_mode("multi")
        p.slot_bom.set_path(str(bom))
        # BOM only → the panel must explain what is still missing
        assert "placement file" in p.lbl_hint.text()
        assert p.lbl_hint.isVisible() or not p.isVisible()
        p.slot_top.set_path(str(top))
        p.slot_bot.set_path(str(bot))
        assert p.lbl_hint.text() == ""


class TestMainWindowThreeFiles:
    def test_validates_split_files(self, qapp, make_split_workbooks):
        from bom_validator.gui.main_window import MainWindow
        from bom_validator.sources import SourceSet

        bom, top, bot = make_split_workbooks()
        w = MainWindow()
        w.sources_panel.set_sources(SourceSet.multi(bom, top, bot))
        w.open_sources(w.sources_panel.sources())
        assert _drain(qapp, lambda: w.report is not None)
        assert w.report.summary.top_placed == 4
        assert w.report.summary.bot_placed == 2
        assert w.report.metadata["source_mode"] == "multi"
        w.close()

    def test_preview_lists_sheets_of_every_file(self, qapp, make_split_workbooks):
        from bom_validator.gui.main_window import MainWindow
        from bom_validator.sources import SourceSet

        bom, top, bot = make_split_workbooks()
        w = MainWindow()
        w.sources_panel.set_sources(SourceSet.multi(bom, top, bot))
        w.open_sources(w.sources_panel.sources())
        assert _drain(qapp, lambda: w.cmb_sheet.count() >= 3)
        labels = [w.cmb_sheet.itemText(i) for i in range(w.cmb_sheet.count())]
        assert any("top_export.xlsx" in x for x in labels)
        assert any("bot_export.xlsx" in x for x in labels)
        w.close()

    def test_single_mode_still_works(self, qapp, make_workbook):
        from bom_validator.gui.main_window import MainWindow

        w = MainWindow()
        w.open_file(str(make_workbook()))
        assert _drain(qapp, lambda: w.report is not None)
        assert w.report.metadata["source_mode"] == "single"
        assert w.cmb_sheet.count() == 3
        w.close()

    def test_open_file_fills_the_bom_slot_in_multi_mode(self, qapp, make_split_workbooks):
        from bom_validator.gui.main_window import MainWindow

        bom, _top, _bot = make_split_workbooks()
        w = MainWindow()
        w.sources_panel.set_mode("multi")
        w.open_file(str(bom))  # incomplete: no placement file yet
        assert w.sources_panel.slot_bom.path() == str(bom.resolve())
        assert w.report is None
        assert "placement file" in w.statusBar().currentMessage()
        w.close()

    def test_recent_menu_restores_a_three_file_entry(self, qapp, make_split_workbooks):
        from bom_validator.gui.main_window import MainWindow
        from bom_validator.sources import SourceSet

        bom, top, bot = make_split_workbooks()
        w = MainWindow()
        w.sources_panel.set_sources(SourceSet.multi(bom, top, bot))
        w.open_sources(w.sources_panel.sources())
        assert _drain(qapp, lambda: w.report is not None)
        labels = [a.text() for a in w.menu_recent.actions()]
        assert any("TOP:top_export.xlsx" in x for x in labels)
        w.close()
