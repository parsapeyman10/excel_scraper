"""Dialogs: profile editor, column mapping, history browser, about."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import BUILTIN_PROFILES, AppSettings, ValidationProfile, profiles_dir
from ..core.rules import rule_catalog
from ..storage.history import HistoryStore
from ..version import APP_NAME, ORG_NAME, __version__
from . import theme as th
from .i18n import STRINGS


class ProfileDialog(QDialog):
    """Full editor for a :class:`ValidationProfile`."""

    def __init__(self, profile: ValidationProfile, tr, parent=None):
        super().__init__(parent)
        self.tr_ = tr
        self.profile = ValidationProfile.from_dict(profile.to_dict())
        self.setWindowTitle(tr("profiles"))
        self.resize(880, 700)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(ValidationProfile.list_available())
        idx = self.cmb_profile.findText(profile.name)
        if idx >= 0:
            self.cmb_profile.setCurrentIndex(idx)
        btn_load = QPushButton("Load")
        btn_load.setObjectName("secondary")
        btn_import = QPushButton("Import…")
        btn_import.setObjectName("secondary")
        btn_export = QPushButton("Export…")
        btn_export.setObjectName("secondary")
        top.addWidget(QLabel("Profile:"))
        top.addWidget(self.cmb_profile, 1)
        top.addWidget(btn_load)
        top.addWidget(btn_import)
        top.addWidget(btn_export)
        root.addLayout(top)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # --- general -------------------------------------------------
        g = QWidget()
        gf = QFormLayout(g)
        self.txt_name = QLineEdit(self.profile.name)
        self.txt_desc = QLineEdit(self.profile.description)
        self.spn_tolerance = QSpinBox()
        self.spn_tolerance.setRange(0, 10_000)
        self.spn_tolerance.setValue(self.profile.qty_tolerance)
        self.chk_fuzzy = QCheckBox("Enable fuzzy description matching")
        self.chk_fuzzy.setChecked(self.profile.fuzzy_matching)
        self.spn_fuzzy = QDoubleSpinBox()
        self.spn_fuzzy.setRange(0.5, 1.0)
        self.spn_fuzzy.setSingleStep(0.01)
        self.spn_fuzzy.setValue(self.profile.fuzzy_threshold)
        self.cmb_key = QComboBox()
        self.cmb_key.addItems(["stock_then_part", "stock_only", "part_only"])
        self.cmb_key.setCurrentText(self.profile.key_strategy)
        self.chk_zeros = QCheckBox("Strip leading zeros from numeric keys")
        self.chk_zeros.setChecked(self.profile.strip_leading_zeros)
        self.chk_case = QCheckBox("Case-insensitive key matching")
        self.chk_case.setChecked(self.profile.case_insensitive_keys)
        self.chk_digits = QCheckBox("Normalise Persian/Arabic digits")
        self.chk_digits.setChecked(self.profile.normalize_digits)
        gf.addRow("Name", self.txt_name)
        gf.addRow("Description", self.txt_desc)
        gf.addRow("Quantity tolerance", self.spn_tolerance)
        gf.addRow("", self.chk_fuzzy)
        gf.addRow("Fuzzy threshold", self.spn_fuzzy)
        gf.addRow("Key strategy", self.cmb_key)
        gf.addRow("", self.chk_zeros)
        gf.addRow("", self.chk_case)
        gf.addRow("", self.chk_digits)
        tabs.addTab(g, "General")

        # --- sheets --------------------------------------------------
        s = QWidget()
        sf = QFormLayout(s)
        self.txt_bom = QLineEdit(", ".join(self.profile.bom_sheet_patterns))
        self.txt_top = QLineEdit(", ".join(self.profile.top_sheet_patterns))
        self.txt_bot = QLineEdit(", ".join(self.profile.bot_sheet_patterns))
        self.txt_ignore = QLineEdit(", ".join(self.profile.ignore_sheet_patterns))
        self.spn_scan = QSpinBox()
        self.spn_scan.setRange(1, 200)
        self.spn_scan.setValue(self.profile.header_scan_rows)
        self.spn_look = QSpinBox()
        self.spn_look.setRange(0, 10)
        self.spn_look.setValue(self.profile.header_lookahead_rows)
        sf.addRow("BOM sheet patterns", self.txt_bom)
        sf.addRow("Top sheet patterns", self.txt_top)
        sf.addRow("Bottom sheet patterns", self.txt_bot)
        sf.addRow("Ignore patterns", self.txt_ignore)
        sf.addRow("Header scan rows", self.spn_scan)
        sf.addRow("Header lookahead rows", self.spn_look)
        tabs.addTab(s, "Sheets & headers")

        # --- synonyms ------------------------------------------------
        syn = QWidget()
        sy = QVBoxLayout(syn)
        sy.addWidget(
            QLabel("Column synonyms — one field per row, comma separated aliases.")
        )
        self.tbl_syn = QTableWidget(0, 2)
        self.tbl_syn.setHorizontalHeaderLabels(["Field", "Aliases"])
        self.tbl_syn.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._fill_syn(self.profile.column_synonyms)
        sy.addWidget(self.tbl_syn)
        tabs.addTab(syn, "Column synonyms")

        # --- rules ---------------------------------------------------
        r = QWidget()
        rl = QVBoxLayout(r)
        rl.addWidget(QLabel("Enable or disable individual checks:"))
        self.lst_rules = QListWidget()
        enabled = set(self.profile.enabled_rules)
        for rule in rule_catalog():
            item = QListWidgetItem(
                f"{rule['code']}  —  {rule['title']}  [{rule['severity']}]"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if (not enabled or rule["code"] in enabled)
                else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, rule["code"])
            item.setToolTip(rule["description"])
            self.lst_rules.addItem(item)
        rl.addWidget(self.lst_rules)

        box = QGroupBox("Geometric checks")
        bf = QFormLayout(box)
        self.spn_rot = QDoubleSpinBox()
        self.spn_rot.setRange(0, 3600)
        self.spn_rot.setValue(self.profile.max_rotation)
        self.spn_bx = QDoubleSpinBox()
        self.spn_bx.setRange(0, 10_000)
        self.spn_bx.setSuffix(" mm")
        self.spn_bx.setValue(self.profile.board_extent_x)
        self.spn_by = QDoubleSpinBox()
        self.spn_by.setRange(0, 10_000)
        self.spn_by.setSuffix(" mm")
        self.spn_by.setValue(self.profile.board_extent_y)
        bf.addRow("Max rotation (0 = off)", self.spn_rot)
        bf.addRow("Board extent X (0 = off)", self.spn_bx)
        bf.addRow("Board extent Y (0 = off)", self.spn_by)
        rl.addWidget(box)
        tabs.addTab(r, tr("rules"))

        # --- raw JSON -------------------------------------------------
        raw = QWidget()
        rw = QVBoxLayout(raw)
        self.txt_json = QPlainTextEdit()
        self.txt_json.setFont(QFont("Consolas, monospace", 9))
        self.txt_json.setPlainText(json.dumps(self.profile.to_dict(), ensure_ascii=False, indent=2))
        btn_apply_json = QPushButton("Apply JSON to form")
        btn_apply_json.setObjectName("secondary")
        rw.addWidget(self.txt_json)
        rw.addWidget(btn_apply_json)
        tabs.addTab(raw, "Raw JSON")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        root.addWidget(buttons)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save_named)

        btn_load.clicked.connect(self._load_selected)
        btn_import.clicked.connect(self._import)
        btn_export.clicked.connect(self._export)
        btn_apply_json.clicked.connect(self._apply_json)

    # ------------------------------------------------------------------
    def _fill_syn(self, synonyms: dict[str, list[str]]) -> None:
        self.tbl_syn.setRowCount(0)
        for field_name, aliases in sorted(synonyms.items()):
            row = self.tbl_syn.rowCount()
            self.tbl_syn.insertRow(row)
            item = QTableWidgetItem(field_name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_syn.setItem(row, 0, item)
            self.tbl_syn.setItem(row, 1, QTableWidgetItem(", ".join(aliases)))

    def _collect(self) -> ValidationProfile:
        p = self.profile
        p.name = self.txt_name.text().strip() or "custom"
        p.description = self.txt_desc.text()
        p.qty_tolerance = self.spn_tolerance.value()
        p.fuzzy_matching = self.chk_fuzzy.isChecked()
        p.fuzzy_threshold = self.spn_fuzzy.value()
        p.key_strategy = self.cmb_key.currentText()
        p.strip_leading_zeros = self.chk_zeros.isChecked()
        p.case_insensitive_keys = self.chk_case.isChecked()
        p.normalize_digits = self.chk_digits.isChecked()

        def split(text: str) -> list[str]:
            return [t.strip() for t in text.split(",") if t.strip()]

        p.bom_sheet_patterns = split(self.txt_bom.text())
        p.top_sheet_patterns = split(self.txt_top.text())
        p.bot_sheet_patterns = split(self.txt_bot.text())
        p.ignore_sheet_patterns = split(self.txt_ignore.text())
        p.header_scan_rows = self.spn_scan.value()
        p.header_lookahead_rows = self.spn_look.value()

        syn: dict[str, list[str]] = {}
        for row in range(self.tbl_syn.rowCount()):
            key_item = self.tbl_syn.item(row, 0)
            val_item = self.tbl_syn.item(row, 1)
            if key_item:
                syn[key_item.text()] = split(val_item.text() if val_item else "")
        if syn:
            p.column_synonyms = syn

        checked, total = [], self.lst_rules.count()
        for i in range(total):
            item = self.lst_rules.item(i)
            if item.checkState() is Qt.CheckState.Checked:
                checked.append(item.data(Qt.ItemDataRole.UserRole))
        p.enabled_rules = [] if len(checked) == total else checked

        p.max_rotation = self.spn_rot.value()
        p.board_extent_x = self.spn_bx.value()
        p.board_extent_y = self.spn_by.value()
        return p

    def _apply_json(self) -> None:
        try:
            data = json.loads(self.txt_json.toPlainText())
            self.profile = ValidationProfile.from_dict(data)
        except Exception as exc:
            QMessageBox.warning(self, "JSON", f"Invalid profile JSON:\n{exc}")
            return
        self._reload_form()

    def _reload_form(self) -> None:
        p = self.profile
        self.txt_name.setText(p.name)
        self.txt_desc.setText(p.description)
        self.spn_tolerance.setValue(p.qty_tolerance)
        self.chk_fuzzy.setChecked(p.fuzzy_matching)
        self.spn_fuzzy.setValue(p.fuzzy_threshold)
        self.cmb_key.setCurrentText(p.key_strategy)
        self.txt_bom.setText(", ".join(p.bom_sheet_patterns))
        self.txt_top.setText(", ".join(p.top_sheet_patterns))
        self.txt_bot.setText(", ".join(p.bot_sheet_patterns))
        self.txt_ignore.setText(", ".join(p.ignore_sheet_patterns))
        self.spn_scan.setValue(p.header_scan_rows)
        self.spn_look.setValue(p.header_lookahead_rows)
        self._fill_syn(p.column_synonyms)
        self.spn_rot.setValue(p.max_rotation)
        self.spn_bx.setValue(p.board_extent_x)
        self.spn_by.setValue(p.board_extent_y)

    def _load_selected(self) -> None:
        try:
            self.profile = ValidationProfile.load_by_name(self.cmb_profile.currentText())
        except Exception as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return
        self._reload_form()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "JSON (*.json)")
        if path:
            self.profile = ValidationProfile.load(path)
            self._reload_form()

    def _export(self) -> None:
        p = self._collect()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile", f"{p.name}.json", "JSON (*.json)"
        )
        if path:
            p.save(path)
            QMessageBox.information(self, "Profile", f"Saved to {path}")

    def _save_named(self) -> None:
        p = self._collect()
        if p.name in BUILTIN_PROFILES:
            QMessageBox.warning(
                self, "Profile", f"'{p.name}' is a built-in profile. Rename it first."
            )
            return
        target = p.save()
        QMessageBox.information(self, "Profile", f"Saved to {target}")
        self.cmb_profile.clear()
        self.cmb_profile.addItems(ValidationProfile.list_available())
        self.cmb_profile.setCurrentText(p.name)

    def _accept(self) -> None:
        self.profile = self._collect()
        self.accept()

    def result_profile(self) -> ValidationProfile:
        return self.profile


class MappingDialog(QDialog):
    """Manually override the detected column mapping."""

    def __init__(self, mapping, sheet_headers: list[str], tr, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("column_mapping"))
        self.resize(560, 520)
        self.mapping = mapping
        lay = QVBoxLayout(self)
        lay.addWidget(
            QLabel(
                f"Sheet <b>{mapping.sheet_name}</b>, header row "
                f"{mapping.header_row + 1}, confidence {mapping.confidence:.0%}"
            )
        )
        self.combos: dict[str, QComboBox] = {}
        form = QFormLayout()
        options = ["— none —"] + [
            f"{i}: {h[:40]}" for i, h in enumerate(sheet_headers)
        ]
        fields = [
            "item",
            "designator",
            "part_name",
            "part_no",
            "material",
            "size",
            "qty",
            "brand",
            "stock_no",
            "note",
        ]
        for field_name in fields:
            cmb = QComboBox()
            cmb.addItems(options)
            idx = mapping.columns.get(field_name, -1)
            cmb.setCurrentIndex(idx + 1 if 0 <= idx < len(sheet_headers) else 0)
            form.addRow(field_name, cmb)
            self.combos[field_name] = cmb
        lay.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def overrides(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for field_name, cmb in self.combos.items():
            i = cmb.currentIndex()
            if i > 0:
                out[field_name] = i - 1
        return out


class HistoryDialog(QDialog):
    """Browse and reopen historic runs."""

    def __init__(self, store: HistoryStore, tr, parent=None):
        super().__init__(parent)
        self.store = store
        self.tr_ = tr
        self.selected_run: int | None = None
        self.setWindowTitle(tr("history"))
        self.resize(1000, 620)

        lay = QVBoxLayout(self)
        stats = store.stats()
        lay.addWidget(
            QLabel(
                f"<b>{stats['runs']}</b> runs recorded · "
                f"<b>{stats['lines_checked']}</b> BOM lines checked · "
                f"average health <b>{stats['avg_health']}</b>"
            )
        )

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["ID", "When", "File", "Profile", "Lines", "Pass", "Fail", "Health", "Operator"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        split.addWidget(self.table)

        self.detail = QTextBrowser()
        split.addWidget(self.detail)
        split.setSizes([400, 200])
        lay.addWidget(split, 1)

        bar = QHBoxLayout()
        btn_delete = QPushButton("Delete")
        btn_delete.setObjectName("danger")
        btn_purge = QPushButton("Keep newest 100")
        btn_purge.setObjectName("secondary")
        btn_export = QPushButton("Export JSON…")
        btn_export.setObjectName("secondary")
        bar.addWidget(btn_delete)
        bar.addWidget(btn_purge)
        bar.addWidget(btn_export)
        bar.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bar.addWidget(buttons)
        lay.addLayout(bar)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        btn_delete.clicked.connect(self._delete)
        btn_purge.clicked.connect(self._purge)
        btn_export.clicked.connect(self._export)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self._reload()

    def _reload(self) -> None:
        runs = self.store.recent(500)
        self.table.setRowCount(len(runs))
        for r, run in enumerate(runs):
            values = [
                str(run.id),
                run.created_at[:19].replace("T", " "),
                run.source_name,
                run.profile,
                str(run.total_lines),
                str(run.passed),
                str(run.failed),
                f"{run.health_score:.1f}",
                run.operator,
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c in (0, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)

    def _current_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.text()) if item else None

    def _show_detail(self) -> None:
        run_id = self._current_id()
        if run_id is None:
            return
        self.selected_run = run_id
        payload = self.store.payload(run_id) or {}
        s = payload.get("summary", {})
        lines = [
            f"<h3>Run #{run_id}</h3>",
            f"<p><b>{payload.get('source_file', '')}</b><br>"
            f"sha256 <code>{payload.get('source_sha256', '')[:24]}…</code><br>"
            f"profile {payload.get('profile')} · "
            f"{payload.get('duration_ms', 0):.0f} ms</p>",
            "<table cellpadding=4>"
            + "".join(f"<tr><td>{k}</td><td><b>{v}</b></td></tr>" for k, v in s.items())
            + "</table>",
        ]
        issues = payload.get("global_issues", [])[:20]
        if issues:
            lines.append("<h4>Global findings</h4><ul>")
            lines += [f"<li>[{i['severity']}] {i['code']}: {i['message']}</li>" for i in issues]
            lines.append("</ul>")
        self.detail.setHtml("".join(lines))

    def _delete(self) -> None:
        run_id = self._current_id()
        if run_id is not None:
            self.store.delete(run_id)
            self._reload()

    def _purge(self) -> None:
        n = self.store.purge(100)
        QMessageBox.information(self, "History", f"Removed {n} run(s).")
        self._reload()

    def _export(self) -> None:
        run_id = self._current_id()
        if run_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export run", f"run_{run_id}.json", "JSON (*.json)"
        )
        if path:
            Path(path).write_text(
                json.dumps(self.store.payload(run_id), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, tr, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("settings"))
        self.resize(460, 380)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(th.THEMES)
        self.cmb_theme.setCurrentText(settings.theme)
        self.cmb_lang = QComboBox()
        for code in STRINGS:
            self.cmb_lang.addItem({"fa": "فارسی", "en": "English"}.get(code, code), code)
        i = self.cmb_lang.findData(settings.language)
        if i >= 0:
            self.cmb_lang.setCurrentIndex(i)
        self.spn_font = QSpinBox()
        self.spn_font.setRange(7, 18)
        self.spn_font.setValue(settings.font_size)
        self.chk_auto = QCheckBox("Validate immediately after opening a file")
        self.chk_auto.setChecked(settings.auto_process_on_open)
        self.chk_watch = QCheckBox("Watch the open file and re-validate on change")
        self.chk_watch.setChecked(settings.watch_files)
        self.chk_geom = QCheckBox("Remember window geometry")
        self.chk_geom.setChecked(settings.remember_geometry)
        self.txt_export = QLineEdit(settings.export_dir)
        btn_browse = QPushButton("…")
        btn_browse.setMaximumWidth(36)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.txt_export, 1)
        rl.addWidget(btn_browse)

        form.addRow(tr("theme"), self.cmb_theme)
        form.addRow(tr("language"), self.cmb_lang)
        form.addRow("Font size", self.spn_font)
        form.addRow("", self.chk_auto)
        form.addRow("", self.chk_watch)
        form.addRow("", self.chk_geom)
        form.addRow("Default export folder", row)
        lay.addLayout(form)
        lay.addStretch(1)
        lay.addWidget(QLabel(f"<span style='color:#888'>Data folder: {profiles_dir().parent}</span>"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(buttons)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        btn_browse.clicked.connect(self._browse)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.txt_export.text())
        if d:
            self.txt_export.setText(d)

    def _accept(self) -> None:
        s = self.settings
        s.theme = self.cmb_theme.currentText()
        s.language = self.cmb_lang.currentData()
        s.font_size = self.spn_font.value()
        s.auto_process_on_open = self.chk_auto.isChecked()
        s.watch_files = self.chk_watch.isChecked()
        s.remember_geometry = self.chk_geom.isChecked()
        s.export_dir = self.txt_export.text()
        self.accept()


ABOUT_HTML = f"""
<h2>{APP_NAME}</h2>
<p>Version <b>{__version__}</b> — {ORG_NAME}</p>
<p>An industrial-grade integrity checker for electronic Bills of Material and
SMT pick-and-place data. It reconciles every BOM line against the machine
placement files, layer by layer and designator by designator.</p>
<h4>Capabilities</h4>
<ul>
<li>Automatic sheet and header detection with confidence scoring</li>
<li>Persian/Arabic digit and letter normalisation</li>
<li>Designator range expansion (C1-C10) and per-reference reconciliation</li>
<li>Twelve pluggable validation rules with configurable severity</li>
<li>Interactive PCB placement map with layer filtering</li>
<li>Reports in Excel, HTML, PDF, CSV, JSON, Markdown and JUnit XML</li>
<li>SQLite audit trail with trend charts and revision diffing</li>
<li>Headless CLI for CI pipelines (<code>bomv validate --fail-on error</code>)</li>
</ul>
<h4>Keyboard shortcuts</h4>
<table cellpadding=3>
<tr><td><b>Ctrl+O</b></td><td>Open workbook</td></tr>
<tr><td><b>F5</b></td><td>Validate / re-validate</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Export Excel report</td></tr>
<tr><td><b>Ctrl+Shift+E</b></td><td>Export HTML report</td></tr>
<tr><td><b>Ctrl+P</b></td><td>Print / PDF</td></tr>
<tr><td><b>Ctrl+F</b></td><td>Focus search box</td></tr>
<tr><td><b>Ctrl+D</b></td><td>Toggle dark theme</td></tr>
<tr><td><b>Ctrl+H</b></td><td>Run history</td></tr>
<tr><td><b>Ctrl+,</b></td><td>Settings</td></tr>
<tr><td><b>F1</b></td><td>This dialog</td></tr>
</table>
"""


class AboutDialog(QDialog):
    def __init__(self, tr, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about"))
        self.resize(620, 620)
        lay = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(ABOUT_HTML)
        browser.setOpenExternalLinks(True)
        lay.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
