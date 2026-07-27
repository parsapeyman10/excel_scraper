"""The main application window."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from PyQt6.QtCore import (
    QFileSystemWatcher,
    QItemSelectionModel,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSlot,
)
from PyQt6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..config import AppSettings, ValidationProfile
from ..core.diff import diff_reports
from ..models import Status, ValidationReport
from ..reporting import exporters
from ..storage.history import HistoryStore
from ..version import APP_NAME, __version__
from . import theme as th
from .dialogs import (
    AboutDialog,
    HistoryDialog,
    MappingDialog,
    ProfileDialog,
    SettingsDialog,
)
from .i18n import Translator
from .models_qt import (
    DesignatorTableModel,
    IssueTableModel,
    PlacementTableModel,
    ResultFilterProxy,
    ResultTableModel,
    SheetPreviewModel,
)
from .widgets.boardmap import BoardMapWidget
from .widgets.kpi import DonutChart, KpiStrip, SparklineChart, StackedBar
from .workers import ExportWorker, ValidationWorker

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.settings = AppSettings.load()
        self.tr_ = Translator(self.settings.language)
        self.profile = self._load_profile(self.settings.last_profile)
        self.report: ValidationReport | None = None
        self.placements = []
        self.previous_report: ValidationReport | None = None
        self.current_file: str = ""
        self.worker: ValidationWorker | None = None
        self.pool = QThreadPool.globalInstance()
        self.history = HistoryStore()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_file_changed)
        self._watch_debounce = QTimer(self)
        self._watch_debounce.setSingleShot(True)
        self._watch_debounce.setInterval(900)
        self._watch_debounce.timeout.connect(self.validate)

        self.setWindowTitle(f"{APP_NAME} — v{__version__}")
        self.resize(1560, 940)
        self._build_ui()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self.apply_theme(self.settings.theme)
        self._restore_geometry()
        self._update_state()

        if initial_file:
            QTimer.singleShot(120, lambda: self.open_file(initial_file))

    # ==================================================================
    # construction
    # ==================================================================
    def _load_profile(self, name: str) -> ValidationProfile:
        try:
            return ValidationProfile.load_by_name(name)
        except Exception:
            return ValidationProfile()

    def _build_ui(self) -> None:
        tr = self.tr_
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(10)

        # ---- control strip -------------------------------------------
        control = QGroupBox(tr("control_panel"))
        cl = QHBoxLayout(control)
        cl.setSpacing(8)
        self.btn_open = QPushButton(tr("open"))
        self.btn_open.setMinimumHeight(34)
        self.lbl_file = QLabel(tr("no_file"))
        self.lbl_file.setObjectName("hint")
        self.lbl_file.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumWidth(160)
        self._reload_profiles()
        self.btn_validate = QPushButton(tr("process"))
        self.btn_validate.setMinimumHeight(34)
        self.btn_validate.setEnabled(False)
        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setVisible(False)
        cl.addWidget(self.btn_open)
        cl.addWidget(self.lbl_file, 1)
        cl.addWidget(QLabel(tr("profiles") + ":"))
        cl.addWidget(self.cmb_profile)
        cl.addWidget(self.btn_validate)
        cl.addWidget(self.btn_cancel)
        root.addWidget(control)

        # ---- KPI strip ------------------------------------------------
        self.kpi = KpiStrip(tr, self.settings.theme)
        root.addWidget(self.kpi)
        self.bar_status = StackedBar(theme=self.settings.theme)
        root.addWidget(self.bar_status)

        # ---- tabs -----------------------------------------------------
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_results_tab(), tr("results"))
        self.tabs.addTab(self._build_board_tab(), "Board map")
        self.tabs.addTab(self._build_issues_tab(), tr("issues"))
        self.tabs.addTab(self._build_designator_tab(), tr("designators"))
        self.tabs.addTab(self._build_orphan_tab(), tr("orphans"))
        self.tabs.addTab(self._build_preview_tab(), tr("preview"))
        self.tabs.addTab(self._build_dashboard_tab(), tr("dashboard"))

        # ---- detail dock ---------------------------------------------
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.dock_detail = QDockWidget("Line detail", self)
        self.dock_detail.setWidget(self.detail)
        self.dock_detail.setObjectName("dockDetail")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_detail)
        self.dock_detail.setMinimumWidth(330)

        # ---- status bar -----------------------------------------------
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(230)
        self.progress.setVisible(False)
        self.lbl_engine = QLabel("")
        self.lbl_engine.setObjectName("hint")
        sb.addPermanentWidget(self.lbl_engine)
        sb.addPermanentWidget(self.progress)
        sb.showMessage(tr("ready"))

        # ---- signals ---------------------------------------------------
        self.btn_open.clicked.connect(self.choose_file)
        self.btn_validate.clicked.connect(self.validate)
        self.btn_cancel.clicked.connect(self.cancel_validation)
        self.cmb_profile.currentTextChanged.connect(self._on_profile_changed)

    def _build_results_tab(self) -> QWidget:
        tr = self.tr_
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(tr("search"))
        self.txt_search.setClearButtonEnabled(True)
        self.cmb_status = QComboBox()
        self.cmb_status.addItem(tr("all"), "")
        for s in (Status.PASS, Status.WARN, Status.FAIL, Status.NOT_PLACED):
            self.cmb_status.addItem(s.value, s.value)
        self.chk_failing = QCheckBox(tr("show_only_failing"))
        btn_all = QPushButton(tr("select_all"))
        btn_all.setObjectName("secondary")
        btn_none = QPushButton(tr("clear_selection"))
        btn_none.setObjectName("secondary")
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("hint")

        bar.addWidget(self.txt_search, 2)
        bar.addWidget(QLabel(tr("filter_status") + ":"))
        bar.addWidget(self.cmb_status)
        bar.addWidget(self.chk_failing)
        bar.addWidget(btn_all)
        bar.addWidget(btn_none)
        bar.addWidget(self.lbl_count)
        lay.addLayout(bar)

        self.model = ResultTableModel(tr, self.settings.theme, self)
        self.proxy = ResultFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for i, (_key, _label, width) in enumerate(ResultTableModel.COLUMNS):
            self.table.setColumnWidth(i, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        lay.addWidget(self.table, 1)

        self.txt_search.textChanged.connect(self.proxy.set_text)
        self.cmb_status.currentIndexChanged.connect(
            lambda: self.proxy.set_status_filter([self.cmb_status.currentData()])
        )
        self.chk_failing.toggled.connect(self.proxy.set_only_failing)
        self.proxy.rowsInserted.connect(self._update_count)
        self.proxy.rowsRemoved.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)
        self.table.customContextMenuRequested.connect(self._table_menu)
        btn_all.clicked.connect(lambda: self.model.set_all_signed(True))
        btn_none.clicked.connect(lambda: self.model.set_all_signed(False))
        QTimer.singleShot(0, self._connect_selection)
        return w

    def _connect_selection(self) -> None:
        sm = self.table.selectionModel()
        if sm:
            sm.currentRowChanged.connect(self._on_row_selected)

    def _build_board_tab(self) -> QWidget:
        self.board = BoardMapWidget(self.tr_, self.settings.theme)
        self.board.designator_selected.connect(self._select_by_designator)
        return self.board

    def _build_issues_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.issue_model = IssueTableModel(self)
        self.issue_view = QTableView()
        self.issue_view.setModel(self.issue_model)
        self.issue_view.setSortingEnabled(True)
        self.issue_view.setAlternatingRowColors(True)
        self.issue_view.horizontalHeader().setStretchLastSection(True)
        self.issue_view.setColumnWidth(0, 70)
        self.issue_view.setColumnWidth(1, 90)
        self.issue_view.setColumnWidth(2, 170)
        self.issue_view.setColumnWidth(3, 150)
        self.issue_view.verticalHeader().setVisible(False)
        lay.addWidget(self.issue_view)
        return w

    def _build_designator_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.desig_filter = QLineEdit()
        self.desig_filter.setPlaceholderText(self.tr_("search"))
        self.desig_filter.setClearButtonEnabled(True)
        lay.addWidget(self.desig_filter)
        self.desig_model = DesignatorTableModel(self)
        from PyQt6.QtCore import QSortFilterProxyModel

        self.desig_proxy = QSortFilterProxyModel(self)
        self.desig_proxy.setSourceModel(self.desig_model)
        self.desig_proxy.setFilterKeyColumn(-1)
        self.desig_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.desig_view = QTableView()
        self.desig_view.setModel(self.desig_proxy)
        self.desig_view.setSortingEnabled(True)
        self.desig_view.setAlternatingRowColors(True)
        self.desig_view.horizontalHeader().setStretchLastSection(True)
        self.desig_view.verticalHeader().setVisible(False)
        self.desig_filter.textChanged.connect(self.desig_proxy.setFilterFixedString)
        lay.addWidget(self.desig_view)
        return w

    def _build_orphan_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(
            QLabel(
                "Placements present in the machine files but absent from the BOM — "
                "the classic cause of a line stop."
            )
        )
        self.orphan_model = PlacementTableModel(self)
        self.orphan_view = QTableView()
        self.orphan_view.setModel(self.orphan_model)
        self.orphan_view.setSortingEnabled(True)
        self.orphan_view.setAlternatingRowColors(True)
        self.orphan_view.horizontalHeader().setStretchLastSection(True)
        self.orphan_view.verticalHeader().setVisible(False)
        lay.addWidget(self.orphan_view)
        return w

    def _build_preview_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.cmb_sheet = QComboBox()
        self.cmb_sheet.setMinimumWidth(240)
        btn_map = QPushButton(self.tr_("column_mapping"))
        btn_map.setObjectName("secondary")
        bar.addWidget(QLabel("Sheet:"))
        bar.addWidget(self.cmb_sheet)
        bar.addWidget(btn_map)
        bar.addStretch(1)
        self.lbl_mapping = QLabel("")
        self.lbl_mapping.setObjectName("hint")
        bar.addWidget(self.lbl_mapping)
        lay.addLayout(bar)

        self.preview_model = SheetPreviewModel(self)
        self.preview_view = QTableView()
        self.preview_view.setModel(self.preview_model)
        self.preview_view.setAlternatingRowColors(True)
        lay.addWidget(self.preview_view)
        self.cmb_sheet.currentTextChanged.connect(self._load_preview)
        btn_map.clicked.connect(self._edit_mapping)
        return w

    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Finding distribution</b>"))
        self.donut = DonutChart(theme=self.settings.theme)
        ll.addWidget(self.donut, 1)
        ll.addWidget(QLabel("<b>Health trend for this board</b>"))
        self.spark = SparklineChart(theme=self.settings.theme)
        ll.addWidget(self.spark)
        split.addWidget(left)

        self.summary_html = QTextBrowser()
        split.addWidget(self.summary_html)
        split.setSizes([600, 620])
        lay.addWidget(split, 1)
        return w

    # ==================================================================
    # actions / menu / toolbar
    # ==================================================================
    def _act(self, text: str, slot, shortcut: str = "", tip: str = "",
             checkable: bool = False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        tr = self.tr_
        self.act_open = self._act(tr("open"), self.choose_file, "Ctrl+O")
        self.act_reload = self._act(tr("reload"), self.reload_file, "Ctrl+R")
        self.act_validate = self._act(tr("process"), self.validate, "F5")
        self.act_xlsx = self._act(tr("export_excel"), lambda: self.export("xlsx"), "Ctrl+E")
        self.act_html = self._act(tr("export_html"), lambda: self.export("html"), "Ctrl+Shift+E")
        self.act_pdf = self._act(tr("export_pdf"), lambda: self.export("pdf"), "Ctrl+P")
        self.act_csv = self._act(tr("export_csv"), lambda: self.export("csv"))
        self.act_json = self._act(tr("export_json"), lambda: self.export("json"))
        self.act_junit = self._act(tr("export_junit"), lambda: self.export("junit"))
        self.act_md = self._act("Export Markdown", lambda: self.export("md"))
        self.act_diff = self._act(tr("diff"), self.compare_revision, "Ctrl+Shift+D")
        self.act_history = self._act(tr("history"), self.show_history, "Ctrl+H")
        self.act_profiles = self._act(tr("profiles"), self.edit_profile, "Ctrl+Shift+P")
        self.act_settings = self._act(tr("settings"), self.edit_settings, "Ctrl+,")
        self.act_dark = self._act("Toggle dark theme", self.toggle_dark, "Ctrl+D", checkable=True)
        self.act_dark.setChecked(self.settings.theme == "industrial-dark")
        self.act_about = self._act(tr("about"), self.show_about, "F1")
        self.act_quit = self._act(tr("quit"), self.close, "Ctrl+Q")
        self.act_find = self._act("Find", lambda: self.txt_search.setFocus(), "Ctrl+F")
        self.addAction(self.act_find)
        self.act_copy = self._act(tr("copy_row"), self.copy_selection, "Ctrl+C")
        self.addAction(self.act_copy)
        self.act_watch = self._act(
            tr("auto_refresh"), self.toggle_watch, checkable=True
        )
        self.act_watch.setChecked(self.settings.watch_files)

    def _build_menu(self) -> None:
        tr = self.tr_
        mb = self.menuBar()
        m_file = mb.addMenu(tr("menu_file"))
        m_file.addAction(self.act_open)
        self.menu_recent = QMenu(tr("open_recent"), self)
        m_file.addMenu(self.menu_recent)
        m_file.addAction(self.act_reload)
        m_file.addSeparator()
        m_file.addAction(self.act_validate)
        m_file.addSeparator()
        m_export = m_file.addMenu(tr("export"))
        for a in (
            self.act_xlsx, self.act_html, self.act_pdf, self.act_csv,
            self.act_json, self.act_md, self.act_junit,
        ):
            m_export.addAction(a)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_view = mb.addMenu(tr("menu_view"))
        m_theme = m_view.addMenu(tr("theme"))
        group = QActionGroup(self)
        for name in th.THEMES:
            a = QAction(name, self, checkable=True)
            a.setChecked(name == self.settings.theme)
            a.triggered.connect(lambda _c, n=name: self.apply_theme(n))
            group.addAction(a)
            m_theme.addAction(a)
        m_lang = m_view.addMenu(tr("language"))
        for code, label in (("fa", "فارسی"), ("en", "English")):
            a = QAction(label, self, checkable=True)
            a.setChecked(code == self.settings.language)
            a.triggered.connect(lambda _c, c=code: self.set_language(c))
            m_lang.addAction(a)
        m_view.addSeparator()
        m_view.addAction(self.dock_detail.toggleViewAction())
        m_view.addAction(self.act_dark)

        m_tools = mb.addMenu(tr("menu_tools"))
        m_tools.addAction(self.act_profiles)
        m_tools.addAction(self.act_diff)
        m_tools.addAction(self.act_history)
        m_tools.addAction(self.act_watch)
        m_tools.addSeparator()
        m_tools.addAction(self.act_settings)

        m_help = mb.addMenu(tr("menu_help"))
        m_help.addAction(self.act_about)
        self._refresh_recent()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        for a in (self.act_open, self.act_reload, self.act_validate):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_xlsx, self.act_html, self.act_pdf):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_diff, self.act_history, self.act_profiles):
            tb.addAction(a)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        tb.addAction(self.act_settings)
        tb.addAction(self.act_about)

    # ==================================================================
    # file handling
    # ==================================================================
    def choose_file(self) -> None:
        start = self.settings.recent_files[0] if self.settings.recent_files else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr_("open"),
            str(Path(start).parent) if start else "",
            "Workbooks (*.xlsx *.xlsm *.xls *.csv *.tsv);;All files (*)",
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, self.tr_("error"), f"File not found:\n{path}")
            self.settings.recent_files = [
                f for f in self.settings.recent_files if f != str(p)
            ]
            self._refresh_recent()
            return
        if self.report:
            self.previous_report = self.report
        self.current_file = str(p.resolve())
        self.lbl_file.setText(self.current_file)
        self.settings.push_recent(self.current_file)
        self.settings.save()
        self._refresh_recent()
        self.btn_validate.setEnabled(True)
        self.statusBar().showMessage(f"{p.name} loaded.")
        self._populate_sheets()
        self._sync_watcher()
        if self.settings.auto_process_on_open:
            self.validate()

    def reload_file(self) -> None:
        if self.current_file:
            self.open_file(self.current_file)

    def _refresh_recent(self) -> None:
        self.menu_recent.clear()
        for f in self.settings.recent_files:
            a = QAction(f, self)
            a.triggered.connect(lambda _c, path=f: self.open_file(path))
            self.menu_recent.addAction(a)
        if self.settings.recent_files:
            self.menu_recent.addSeparator()
            clear = QAction("Clear list", self)
            clear.triggered.connect(self._clear_recent)
            self.menu_recent.addAction(clear)

    def _clear_recent(self) -> None:
        self.settings.recent_files = []
        self.settings.save()
        self._refresh_recent()

    def _sync_watcher(self) -> None:
        for f in self.watcher.files():
            self.watcher.removePath(f)
        if self.settings.watch_files and self.current_file:
            self.watcher.addPath(self.current_file)

    def toggle_watch(self, checked: bool) -> None:
        self.settings.watch_files = checked
        self.settings.save()
        self._sync_watcher()
        self.statusBar().showMessage(
            f"File watching {'enabled' if checked else 'disabled'}."
        )

    def _on_file_changed(self, path: str) -> None:
        if Path(path).exists():
            self._watch_debounce.start()
            if path not in self.watcher.files():
                self.watcher.addPath(path)

    # ==================================================================
    # validation
    # ==================================================================
    def validate(self) -> None:
        if not self.current_file:
            self.choose_file()
            return
        if self.worker is not None:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_validate.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.statusBar().showMessage(self.tr_("processing"))

        self.worker = ValidationWorker(self.current_file, self.profile)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_finished)
        self.worker.signals.failed.connect(self._on_failed)
        self.worker.signals.cancelled.connect(self._on_cancelled)
        self.pool.start(self.worker)

    def cancel_validation(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelling…")

    @pyqtSlot(int, int, str)
    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setValue(int(done / max(total, 1) * 100))
        self.statusBar().showMessage(f"{self.tr_('processing')} {message}")

    @pyqtSlot(object, object)
    def _on_finished(self, report: ValidationReport, placements) -> None:
        self.worker = None
        self.report = report
        self.placements = placements or []
        self._teardown_progress()
        self._render_report()
        try:
            self.history.save(report, operator=os.environ.get("USERNAME", ""))
        except Exception as exc:
            log.warning("history save failed: %s", exc)
        s = report.summary
        self.statusBar().showMessage(
            f"{self.tr_('done')}  {s.total_lines} lines · {s.passed} pass · "
            f"{s.failed} fail · {s.not_placed} unplaced · health {s.health_score:.0f}"
        )

    @pyqtSlot(str, str)
    def _on_failed(self, message: str, tb: str) -> None:
        self.worker = None
        self._teardown_progress()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(self.tr_("error"))
        box.setText(message)
        box.setDetailedText(tb)
        box.exec()
        self.statusBar().showMessage("Validation failed.")

    @pyqtSlot()
    def _on_cancelled(self) -> None:
        self.worker = None
        self._teardown_progress()
        self.statusBar().showMessage(self.tr_("cancelled"))

    def _teardown_progress(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_validate.setEnabled(bool(self.current_file))
        self._update_state()

    # ==================================================================
    # rendering
    # ==================================================================
    def _render_report(self) -> None:
        r = self.report
        self.model.set_report(r)
        self.issue_model.set_report(r)
        self.desig_model.set_report(r)
        self.orphan_model.set_placements(r.orphan_placements if r else [])
        self.kpi.set_summary(r.summary if r else None)
        if r:
            self.bar_status.set_summary(r.summary)
        self.board.set_data(self.placements, r)
        self._connect_selection()
        self._update_count()
        self._render_dashboard()
        self._load_preview()
        if r:
            self.lbl_engine.setText(
                f"sheet '{r.mapping.sheet_name}' · header row "
                f"{r.mapping.header_row + 1} · conf {r.mapping.confidence:.0%} · "
                f"{r.duration_ms:.0f} ms"
            )
        self.table.resizeRowsToContents()
        for i, (_k, _l, wpx) in enumerate(ResultTableModel.COLUMNS):
            if self.table.columnWidth(i) < 30:
                self.table.setColumnWidth(i, wpx)

    def _render_dashboard(self) -> None:
        r = self.report
        if not r:
            self.donut.set_items([])
            self.spark.set_values([])
            self.summary_html.setHtml("")
            return
        p = th.palette(self.settings.theme)
        counts: dict[str, int] = {}
        for res in r.results:
            for i in res.issues:
                counts[i.code] = counts.get(i.code, 0) + 1
        for i in r.global_issues:
            counts[i.code] = counts.get(i.code, 0) + 1
        palette_cycle = [
            p["fail"], p["warn"], p["accent"], p["crit"], p["pass"],
            "#8E44AD", "#16A085", "#D35400",
        ]
        items = [
            (code, n, palette_cycle[i % len(palette_cycle)])
            for i, (code, n) in enumerate(
                sorted(counts.items(), key=lambda kv: -kv[1])[:8]
            )
        ]
        self.donut.set_items(items)

        try:
            trend = self.history.trend(Path(r.source_file).name, 40)
            self.spark.set_values(
                [t[1] for t in trend],
                f"{len(trend)} historical run(s) — latest {r.summary.health_score:.1f}",
            )
        except Exception:
            self.spark.set_values([])

        s = r.summary
        diff_html = ""
        if self.previous_report:
            d = diff_reports(self.previous_report, r)
            diff_html = (
                f"<h4>Change vs previous run</h4>"
                f"<p>added <b>{len(d.added)}</b>, removed <b>{len(d.removed)}</b>, "
                f"changed <b>{len(d.changed)}</b>, "
                f"health <b>{d.health_delta:+.1f}</b></p>"
            )
        rows = "".join(
            f"<tr><td>{k}</td><td align=right><b>{v}</b></td></tr>"
            for k, v in s.to_dict().items()
        )
        top_bad = "".join(
            f"<tr><td><code>{res.line.stock_no}</code></td>"
            f"<td>{res.line.part_name[:44]}</td>"
            f"<td align=right>{res.delta:+d}</td>"
            f"<td>{res.status.value}</td></tr>"
            for res in sorted(r.failing, key=lambda x: -abs(x.delta))[:15]
        )
        self.summary_html.setHtml(
            f"""
            <h3>{Path(r.source_file).name}</h3>
            <p style='color:#888'>profile <b>{r.profile_name}</b> ·
            sha256 <code>{r.source_sha256[:20]}…</code> ·
            {r.generated_at:%Y-%m-%d %H:%M:%S} UTC</p>
            <table cellpadding=4 width=100%>{rows}</table>
            {diff_html}
            <h4>Largest deviations</h4>
            <table cellpadding=4 width=100%>
            <tr><th align=left>Stock</th><th align=left>Part</th>
            <th align=right>Δ</th><th align=left>Status</th></tr>
            {top_bad or '<tr><td colspan=4>none</td></tr>'}</table>
            """
        )

    def _update_count(self) -> None:
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        signed = self.model.signed_count()
        self.lbl_count.setText(f"{shown}/{total} rows · {signed} signed")

    def _on_row_selected(self, current, _previous) -> None:
        if not current.isValid():
            return
        src = self.proxy.mapToSource(current)
        r = self.model.result_at(src.row())
        if not r:
            return
        p = th.palette(self.settings.theme)
        color = {
            Status.PASS: p["pass"],
            Status.WARN: p["warn"],
            Status.FAIL: p["fail"],
            Status.NOT_PLACED: p["crit"],
        }.get(r.status, p["muted"])
        issues = "".join(
            f"<li><b>{i.severity.label}</b> <code>{i.code}</code><br>{i.message}</li>"
            for i in r.issues
        )
        def chips(items, tint, ink=None):
            ink = ink or p["ink"]
            return " ".join(
                f"<span style='background:{tint};color:{ink};padding:1px 6px;"
                f"border-radius:8px;margin:1px;display:inline-block'>{d}</span>"
                for d in items[:120]
            ) or "<i>none</i>"

        self.detail.setHtml(
            f"""
            <h3 style='color:{color};margin-bottom:2px'>{r.status.value}</h3>
            <p style='margin-top:0'><b>{r.line.part_name}</b></p>
            <table cellpadding=3>
            <tr><td>Stock no</td><td><code>{r.line.stock_no or '—'}</code></td></tr>
            <tr><td>Part no</td><td>{r.line.part_no or '—'}</td></tr>
            <tr><td>Type</td><td>{r.line.material or '—'} {r.line.size or ''}</td></tr>
            <tr><td>Brand</td><td>{r.line.brand or '—'}</td></tr>
            <tr><td>Required</td><td><b>{r.line.qty}</b></td></tr>
            <tr><td>Placed</td><td><b>{r.placed_total}</b>
                (top {r.top_count} / bot {r.bot_count})</td></tr>
            <tr><td>Delta</td><td><b>{r.delta:+d}</b></td></tr>
            <tr><td>Source row</td><td>{r.line.source_row}</td></tr>
            </table>
            <h4>Top placements ({len(r.matched_top)})</h4>
            {chips(r.matched_top, p['pass_bg'], p['pass'])}
            <h4>Bottom placements ({len(r.matched_bot)})</h4>
            {chips(r.matched_bot, p['surface_alt'], p['ink'])}
            <h4 style='color:{p["fail"]}'>Missing ({len(r.missing_designators)})</h4>
            {chips(r.missing_designators, p['fail_bg'], p['fail'])}
            <h4>Unexpected ({len(r.extra_designators)})</h4>
            {chips(r.extra_designators, p['warn_bg'], p['warn'])}
            <h4>Findings</h4><ul>{issues or '<li><i>none</i></li>'}</ul>
            """
        )
        if r.line.stock_no:
            self.board.canvas.set_highlight(r.line.stock_no)

    def _select_by_designator(self, designator: str) -> None:
        target = designator.strip().upper()
        for row in range(self.model.rowCount()):
            res = self.model.result_at(row)
            if not res:
                continue
            if target in {d.upper() for d in res.matched_top + res.matched_bot} or (
                res.line.stock_no.upper() == target
            ):
                proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
                if proxy_index.isValid():
                    self.tabs.setCurrentIndex(0)
                    self.table.selectionModel().setCurrentIndex(
                        proxy_index,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect
                        | QItemSelectionModel.SelectionFlag.Rows,
                    )
                    self.table.scrollTo(proxy_index)
                return

    def _table_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(self.tr_("copy_row"), self.copy_selection)
        menu.addAction("Copy designators", self._copy_designators)
        menu.addSeparator()
        menu.addAction("Show on board map", self._show_on_board)
        menu.addAction("Toggle sign-off", self._toggle_signoff)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _selected_results(self):
        out = []
        for idx in self.table.selectionModel().selectedRows():
            r = self.model.result_at(self.proxy.mapToSource(idx).row())
            if r:
                out.append(r)
        return out

    def copy_selection(self) -> None:
        rows = self._selected_results()
        if not rows:
            return
        text = "\n".join(
            "\t".join(
                str(v)
                for v in (
                    r.line.item, r.line.stock_no, r.line.part_name, r.line.qty,
                    r.top_count, r.bot_count, r.placed_total, r.delta, r.status.value,
                )
            )
            for r in rows
        )
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {len(rows)} row(s).")

    def _copy_designators(self) -> None:
        rows = self._selected_results()
        text = "\n".join(
            ", ".join(r.matched_top + r.matched_bot) for r in rows
        )
        QGuiApplication.clipboard().setText(text)

    def _show_on_board(self) -> None:
        rows = self._selected_results()
        if rows:
            self.tabs.setCurrentIndex(1)
            self.board.highlight(rows[0].line.stock_no or rows[0].line.part_name)

    def _toggle_signoff(self) -> None:
        for idx in self.table.selectionModel().selectedRows():
            src = self.proxy.mapToSource(idx)
            r = self.model.result_at(src.row())
            if r:
                self.model.setData(
                    self.model.index(src.row(), 0),
                    Qt.CheckState.Unchecked if r.signed_off else Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        self._update_count()

    # ==================================================================
    # preview & mapping
    # ==================================================================
    def _populate_sheets(self) -> None:
        self.cmb_sheet.blockSignals(True)
        self.cmb_sheet.clear()
        try:
            from ..io_excel import reader as rd

            self._loader = rd.WorkbookLoader(self.current_file)
            self.cmb_sheet.addItems(self._loader.sheet_names())
        except Exception as exc:
            log.warning("preview load failed: %s", exc)
            self._loader = None
        self.cmb_sheet.blockSignals(False)
        self._load_preview()

    def _load_preview(self) -> None:
        loader = getattr(self, "_loader", None)
        name = self.cmb_sheet.currentText()
        if not loader or not name:
            return
        sheet = loader.get(name)
        if not sheet:
            return
        from ..io_excel import reader as rd

        mapping = rd.detect_header(sheet, self.profile)
        mapped = {idx: field for field, idx in mapping.columns.items()}
        self.preview_model.set_sheet(sheet.rows[:400], mapping.header_row, mapped)
        self.lbl_mapping.setText(
            f"header row {mapping.header_row + 1} · confidence {mapping.confidence:.0%} · "
            f"{len(sheet)} rows × {sheet.width} cols"
        )
        self.preview_view.resizeColumnsToContents()

    def _edit_mapping(self) -> None:
        loader = getattr(self, "_loader", None)
        if not loader:
            QMessageBox.information(self, self.tr_("info"), "Open a workbook first.")
            return
        from ..io_excel import reader as rd

        name = self.cmb_sheet.currentText()
        sheet = loader.get(name)
        mapping = rd.detect_header(sheet, self.profile)
        headers = []
        if mapping.header_row >= 0:
            row = sheet.rows[mapping.header_row]
            headers = [str(v) if v is not None else "" for v in row]
        else:
            headers = [f"col {i}" for i in range(sheet.width)]
        dlg = MappingDialog(mapping, headers, self.tr_, self)
        if dlg.exec():
            self.profile.manual_mapping = dlg.overrides()
            self.profile.bom_sheet_patterns = [name]
            self.statusBar().showMessage("Manual column mapping applied — re-validating…")
            self.validate()

    # ==================================================================
    # exports / tools
    # ==================================================================
    def export(self, fmt: str) -> None:
        if not self.report:
            QMessageBox.information(self, self.tr_("info"), "Run a validation first.")
            return
        filters = {
            "xlsx": "Excel workbook (*.xlsx)",
            "csv": "CSV (*.csv)",
            "json": "JSON (*.json)",
            "html": "HTML report (*.html)",
            "md": "Markdown (*.md)",
            "junit": "JUnit XML (*.xml)",
            "pdf": "PDF (*.pdf)",
        }
        base = self.settings.export_dir or str(Path(self.current_file).parent)
        suggestion = str(Path(base) / exporters.default_filename(self.report, fmt))
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr_("export"), suggestion, filters.get(fmt, "All files (*)")
        )
        if not path:
            return
        self.statusBar().showMessage(f"Exporting {fmt.upper()}…")
        worker = ExportWorker(self.report, fmt, path)
        worker.signals.finished.connect(self._on_export_done)
        worker.signals.failed.connect(
            lambda m: QMessageBox.critical(self, self.tr_("error"), m)
        )
        self.pool.start(worker)

    @pyqtSlot(str)
    def _on_export_done(self, path: str) -> None:
        self.statusBar().showMessage(f"Report written to {path}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.tr_("export"))
        box.setText(f"Report saved:\n{path}")
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            self._reveal(path)

    @staticmethod
    def _reveal(path: str) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def compare_revision(self) -> None:
        if not self.report:
            QMessageBox.information(self, self.tr_("info"), "Validate a file first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the other revision", "", "Workbooks (*.xlsx *.xlsm *.xls)"
        )
        if not path:
            return
        try:
            from ..core.engine import validate_file

            other = validate_file(path, self.profile)
        except Exception as exc:
            QMessageBox.critical(self, self.tr_("error"), str(exc))
            return
        d = diff_reports(other, self.report)
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        from PyQt6.QtWidgets import QVBoxLayout as VB

        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr_("diff"))
        dlg.resize(920, 640)
        lay = VB(dlg)
        view = QTextBrowser()
        view.setMarkdown(d.to_markdown())
        lay.addWidget(view)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        lay.addWidget(bb)
        bb.rejected.connect(dlg.reject)

        def save() -> None:
            out, _ = QFileDialog.getSaveFileName(dlg, "Save diff", "diff.md", "Markdown (*.md)")
            if out:
                Path(out).write_text(d.to_markdown(), encoding="utf-8")

        bb.accepted.connect(save)
        dlg.exec()

    def show_history(self) -> None:
        HistoryDialog(self.history, self.tr_, self).exec()

    def edit_profile(self) -> None:
        dlg = ProfileDialog(self.profile, self.tr_, self)
        if dlg.exec():
            self.profile = dlg.result_profile()
            self.settings.last_profile = self.profile.name
            self.settings.save()
            self._reload_profiles()
            if self.current_file:
                self.validate()

    def edit_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.tr_, self)
        if dlg.exec():
            self.settings.save()
            self.apply_theme(self.settings.theme)
            self.set_language(self.settings.language)
            f = QApplication.instance().font()
            f.setPointSize(self.settings.font_size)
            QApplication.instance().setFont(f)
            self._sync_watcher()

    def show_about(self) -> None:
        AboutDialog(self.tr_, self).exec()

    # ==================================================================
    # appearance
    # ==================================================================
    def apply_theme(self, name: str) -> None:
        self.settings.theme = name
        self.settings.save()
        self.setStyleSheet(th.stylesheet(name))
        self.model.set_theme(name)
        self.kpi.set_theme(name)
        self.bar_status.set_theme(name)
        self.donut.set_theme(name)
        self.spark.set_theme(name)
        self.board.set_theme(name)
        self.act_dark.setChecked(name == "industrial-dark")
        if self.report:
            self.bar_status.set_summary(self.report.summary)
            self._render_dashboard()

    def toggle_dark(self) -> None:
        self.apply_theme(
            "industrial-dark"
            if self.settings.theme != "industrial-dark"
            else "industrial-light"
        )

    def set_language(self, code: str) -> None:
        if code == self.tr_.language:
            return
        self.tr_.set_language(code)
        self.settings.language = code
        self.settings.save()
        QGuiApplication.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if self.tr_.is_rtl else Qt.LayoutDirection.LeftToRight
        )
        QMessageBox.information(
            self,
            self.tr_("info"),
            "Language changed. Some labels update after restart.",
        )
        self.kpi.retranslate(self.tr_)
        self.btn_open.setText(self.tr_("open"))
        self.btn_validate.setText(self.tr_("process"))
        self.btn_cancel.setText(self.tr_("cancel"))

    def _reload_profiles(self) -> None:
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        self.cmb_profile.addItems(ValidationProfile.list_available())
        idx = self.cmb_profile.findText(self.profile.name)
        if idx >= 0:
            self.cmb_profile.setCurrentIndex(idx)
        self.cmb_profile.blockSignals(False)

    def _on_profile_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self.profile = ValidationProfile.load_by_name(name)
        except Exception as exc:
            QMessageBox.warning(self, self.tr_("error"), str(exc))
            return
        self.settings.last_profile = name
        self.settings.save()
        self.statusBar().showMessage(f"Profile '{name}': {self.profile.description}")
        if self.current_file:
            self.validate()

    def _update_state(self) -> None:
        has = self.report is not None
        for a in (
            self.act_xlsx, self.act_html, self.act_pdf, self.act_csv,
            self.act_json, self.act_md, self.act_junit, self.act_diff,
        ):
            a.setEnabled(has)

    # ==================================================================
    # geometry persistence
    # ==================================================================
    def _restore_geometry(self) -> None:
        if not self.settings.remember_geometry:
            return
        try:
            if self.settings.geometry_b64:
                self.restoreGeometry(base64.b64decode(self.settings.geometry_b64))
            if self.settings.window_state_b64:
                self.restoreState(base64.b64decode(self.settings.window_state_b64))
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.settings.remember_geometry:
            self.settings.geometry_b64 = base64.b64encode(
                bytes(self.saveGeometry())
            ).decode()
            self.settings.window_state_b64 = base64.b64encode(
                bytes(self.saveState())
            ).decode()
        self.settings.save()
        if self.worker:
            self.worker.cancel()
        super().closeEvent(event)
