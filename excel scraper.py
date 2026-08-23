"""
BOM Integrity & Placement Validator — نسخهٔ کلاسیک تکامل‌یافته
==============================================================

مبنای این فایل «اولین نسخهٔ» برنامه (همان ~342 خطِ کامیت «first items») است؛
منطق استخراج و تطبیق قطعات دست‌نخورده حفظ شده (در bom_classic_core.py) و این
افزوده‌ها به آن اضافه شده است:

* **دو حالت ورودی**
    1. حالت تک‌فایل (همان کد اولیه): یک اکسل شامل شیت «مونتاژ ماشینی» + شیت‌های top/bot
    2. حالت سه‌فایل: اکسل BOM + اکسل TOP + اکسل BOT جداگانه، با خروجیِ اکسلی که
       ۱۰۰٪ ساختار/عنوان BOM را حفظ می‌کند و فقط مقادیر top و bot (به‌همراه
       مختصات PCB) از فایل‌های جدید داخلش قرار می‌گیرد + شیت گزارش اعتبارسنجی
* **رابط کاربری مدرن‌تر** با کارت‌های آماری، جست‌وجوی زنده، انتخاب همه و نوار پیشرفت
* **سیستم لایسنس تک‌کاربره** بر اساس Device ID (۱/۳/۶ ماهه) — بدون لایسنس معتبر
  برنامه اجرا نمی‌شود (ماژول license_core.py و ابزار مالک license_generator.py)

اجرا:
    python "excel scraper.py"
"""

from __future__ import annotations

import os
import sys

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import license_core
from bom_classic_core import (
    _pick_sheet_name,
    build_all_outputs,
    evaluate_rows,
    extract_bom_rows,
    extract_data,
    find_bom_sheet_name,
    find_first_matching_headers,
    load_placement_values,
    load_single_file_values,
)

APP_VERSION = "2.1.0"
APP_TITLE = "BOM Integrity & Placement Validator"


# ---------------------------------------------------------------------------
# رابط کاربری
# ---------------------------------------------------------------------------

class KpiCard(QFrame):
    """کارت آماری کوچک بالای صفحه."""

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setStyleSheet(
            "QFrame#kpiCard{background:#1B2432;border:1px solid #2A3550;"
            "border-radius:10px;}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.lbl_value = QLabel("0")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_value.setStyleSheet(
            f"color:{color};font-size:22px;font-weight:bold;border:none;")
        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("color:#8B93A7;font-size:11px;border:none;")
        lay.addWidget(self.lbl_value)
        lay.addWidget(lbl_title)

    def set_value(self, value) -> None:
        self.lbl_value.setText(str(value))


class ActivationDialog(QDialog):
    """دیالوگ فعال‌سازی لایسنس — بدون لایسنس معتبر برنامه در دسترس نیست."""

    def __init__(self, state: license_core.LicenseState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("فعال‌سازی لایسنس — BOM Validator")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._build(state)

    def _build(self, state: license_core.LicenseState) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("🔒 فعال‌سازی نرم‌افزار")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#E5E9F0;")
        layout.addWidget(title)

        self.lbl_reason = QLabel(state.reason)
        self.lbl_reason.setStyleSheet("color:#F87171;font-weight:bold;")
        self.lbl_reason.setWordWrap(True)
        layout.addWidget(self.lbl_reason)

        layout.addWidget(QLabel("شناسهٔ دستگاه شما (برای دریافت لایسنس به فروشنده بفرستید):"))
        row = QHBoxLayout()
        self.ed_device = QLineEdit(license_core.get_device_id())
        self.ed_device.setReadOnly(True)
        self.ed_device.setStyleSheet("font-family:Consolas;")
        btn_copy = QPushButton("کپی شناسه")
        btn_copy.clicked.connect(self._copy_device)
        row.addWidget(self.ed_device, 1)
        row.addWidget(btn_copy)
        layout.addLayout(row)

        layout.addWidget(QLabel("کلید لایسنس (از فروشنده دریافت می‌کنید):"))
        self.ed_key = QPlainTextEdit()
        self.ed_key.setPlaceholderText("BOM2-XXXXX-XXXXX-…")
        self.ed_key.setMaximumHeight(90)
        self.ed_key.setStyleSheet("font-family:Consolas;")
        layout.addWidget(self.ed_key)

        btns = QHBoxLayout()
        self.btn_activate = QPushButton("فعال‌سازی")
        self.btn_activate.setObjectName("primaryBtn")
        self.btn_activate.setMinimumHeight(34)
        self.btn_activate.clicked.connect(self._activate)
        btn_exit = QPushButton("خروج")
        btn_exit.clicked.connect(self.reject)
        btns.addWidget(self.btn_activate)
        btns.addWidget(btn_exit)
        layout.addLayout(btns)

    def _copy_device(self) -> None:
        QGuiApplication.clipboard().setText(self.ed_device.text())
        self.lbl_reason.setText("شناسهٔ دستگاه در کلیپ‌بورد کپی شد.")
        self.lbl_reason.setStyleSheet("color:#34D399;font-weight:bold;")

    def _activate(self) -> None:
        key = self.ed_key.toPlainText().strip()
        if not key:
            self.lbl_reason.setText("کلید لایسنس را وارد کنید.")
            self.lbl_reason.setStyleSheet("color:#FBBF24;font-weight:bold;")
            return
        state = license_core.activate(key)
        if state.ok:
            QMessageBox.information(self, "فعال‌سازی موفق", "لایسنس با موفقیت فعال شد.")
            self.accept()
        else:
            self.lbl_reason.setText(f"خطا: {state.reason}")
            self.lbl_reason.setStyleSheet("color:#F87171;font-weight:bold;")


class LicenseInfoDialog(QDialog):
    """نمایش جزئیات لایسنس فعلی."""

    def __init__(self, parent=None, on_change=None):
        super().__init__(parent)
        self._on_change = on_change
        self.setWindowTitle("وضعیت لایسنس")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        state = license_core.current_state()
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        layout.addWidget(self.lbl)

        device = QLabel(f"شناسهٔ دستگاه:\n{license_core.get_device_id()}")
        device.setStyleSheet("font-family:Consolas;color:#8B93A7;")
        device.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(device)

        if state.ok:
            self.lbl.setStyleSheet("color:#34D399;font-weight:bold;font-size:13px;")
            self.lbl.setText(f"✅ {state.short_label}")
        else:
            self.lbl.setStyleSheet("color:#F87171;font-weight:bold;font-size:13px;")
            self.lbl.setText(f"⛔ {state.reason}")

        btns = QHBoxLayout()
        btn_close = QPushButton("بستن")
        btn_close.clicked.connect(self.accept)
        btns.addStretch(1)
        if state.ok:
            btn_deact = QPushButton("حذف لایسنس از این دستگاه")
            btn_deact.setObjectName("dangerBtn")
            btn_deact.clicked.connect(self._deactivate)
            btns.addWidget(btn_deact)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _deactivate(self) -> None:
        ret = QMessageBox.question(
            self, "حذف لایسنس",
            "لایسنس از این دستگاه حذف شود؟ برنامه تا فعال‌سازی مجدد کار نمی‌کند.",
        )
        if ret == QMessageBox.StandardButton.Yes:
            license_core.deactivate()
            if self._on_change:
                self._on_change()
            self.accept()


class IndustrialBOMValidator(QMainWindow):
    """پنجرهٔ اصلی — تکامل‌یافته از کلاس اصلی نسخهٔ اولیهٔ 342 خطی."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — v{APP_VERSION}")
        self.resize(1250, 800)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        # کش داده‌ها (همان نام‌های نسخهٔ اولیه + افزوده‌های جدید)
        self.extracted_data_cache: list[dict] = []
        self.top_data_cache: list[str] = []
        self.bot_data_cache: list[str] = []
        self.results_cache: list[dict] = []
        self.target_file = ""
        self.bom_file = ""
        self.top_file = ""
        self.bot_file = ""
        self.top_sheet_used = "-"
        self.bot_sheet_used = "-"

        self.setup_ui()
        self.apply_industrial_theme()
        self.refresh_license_badge()

    # -- ساخت رابط -----------------------------------------------------
    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # نوار بالایی: عنوان + نشان لایسنس
        top_bar = QHBoxLayout()
        lbl_logo = QLabel("🧩 " + APP_TITLE)
        lbl_logo.setStyleSheet("font-size:15px;font-weight:bold;color:#E5E9F0;")
        self.badge_license = QPushButton()
        self.badge_license.setFlat(True)
        self.badge_license.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge_license.clicked.connect(self.show_license_info)
        top_bar.addWidget(self.badge_license)
        top_bar.addStretch(1)
        top_bar.addWidget(lbl_logo)
        main_layout.addLayout(top_bar)

        # سربرگ حالت‌های ورود فایل + تب لایسنس
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_single_tab(), "📄 حالت تک‌فایل (BOM کامل)")
        self.tabs.addTab(self._build_triple_tab(), "📑 حالت سه‌فایل (BOM + TOP + BOT)")
        self.tabs.addTab(self._build_license_tab(), "🔐 لایسنس")
        self.tabs.currentChanged.connect(self._on_tab_change)
        main_layout.addWidget(self.tabs)

        # کارت‌های آماری
        kpi_group = QGroupBox("نمای کلی تحلیل")
        kpi_layout = QHBoxLayout(kpi_group)
        self.kpi_total = KpiCard("کل قطعات BOM", "#60A5FA")
        self.kpi_pass = KpiCard("PASS", "#34D399")
        self.kpi_fail = KpiCard("FAIL", "#F87171")
        self.kpi_top = KpiCard("نقشه‌های TOP", "#FBBF24")
        self.kpi_bot = KpiCard("نقشه‌های BOT", "#C084FC")
        for card in (self.kpi_total, self.kpi_pass, self.kpi_fail,
                     self.kpi_top, self.kpi_bot):
            kpi_layout.addWidget(card)
        main_layout.addWidget(kpi_group)

        # نوار ابزار جدول
        tools = QHBoxLayout()
        self.chk_select_all = QCheckBox("انتخاب همه")
        self.chk_select_all.stateChanged.connect(self._toggle_select_all)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 جست‌وجو بر اساس Stock یا Part Name…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filter)
        self.btn_copy_fails = QPushButton("کپی موارد FAIL")
        self.btn_copy_fails.clicked.connect(self.copy_fail_rows)
        self.btn_export = QPushButton("💾 ساخت ۳ خروجی (TOP / BOT / BOM)")
        self.btn_export.setObjectName("successBtn")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_combined_excel)
        tools.addWidget(self.chk_select_all)
        tools.addWidget(self.search_box, 1)
        tools.addWidget(self.btn_copy_fails)
        tools.addWidget(self.btn_export)
        main_layout.addLayout(tools)

        # جدول خروجی — همان ۷ ستون نسخهٔ اولیه
        data_group = QGroupBox("خروجی تحلیل لایه‌های مونتاژ")
        data_layout = QVBoxLayout(data_group)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels([
            "انتخاب", "Stock ID", "Part Description", "Top Placements",
            "Bot Placements", "Total Required", "Verification Status",
        ])
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(3, 7):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.verticalHeader().setDefaultSectionSize(26)
        data_layout.addWidget(self.table_widget)
        main_layout.addWidget(data_group, stretch=1)

        # نوار وضعیت + پیشرفت
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.showMessage("سیستم آماده به کار است.")

    def _build_single_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel(
            "حالت اصلی برنامه: یک فایل اکسل که هم شیت BOM (مونتاژ ماشینی) و هم "
            "شیت‌های top و bot را داخل خودش دارد انتخاب کنید."
        )
        info.setStyleSheet("color:#8B93A7;")
        info.setWordWrap(True)
        layout.addWidget(info)

        control_group = QGroupBox("پنل کنترل عملیات")
        control_layout = QHBoxLayout(control_group)
        self.btn_load = QPushButton("📂 انتخاب فایل اکسل")
        self.btn_load.setObjectName("primaryBtn")
        self.btn_load.setMinimumHeight(35)
        self.btn_load.clicked.connect(self.select_file)
        self.lbl_file_path = QLabel("فایلی انتخاب نشده است")
        self.lbl_file_path.setStyleSheet("color:#8B93A7;")
        self.btn_process = QPushButton("⚙ پردازش و اعتبارسنجی")
        self.btn_process.setObjectName("primaryBtn")
        self.btn_process.setMinimumHeight(35)
        self.btn_process.setEnabled(False)
        self.btn_process.clicked.connect(self.process_excel)
        control_layout.addWidget(self.btn_load)
        control_layout.addWidget(self.lbl_file_path, stretch=1)
        control_layout.addWidget(self.btn_process)
        layout.addWidget(control_group)
        layout.addStretch(1)
        return tab

    def _build_triple_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel(
            "اکسل BOM + دو فایل TOP/BOT را انتخاب کنید. سه خروجی ساخته می‌شود: "
            "نسخهٔ TOP (فقط قطعات لایهٔ top + مختصات PCB)، نسخهٔ BOT و BOM بازتولیدشده — "
            "هر سه با همان فرمت و نام فایل اصلی + v1 و با G4 قفل‌شده (P.Parsa)."
        )
        info.setStyleSheet("color:#8B93A7;")
        info.setWordWrap(True)
        layout.addWidget(info)

        grid = QGroupBox("انتخاب سه فایل ورودی")
        g = QGridLayout(grid)
        self.btn_bom = QPushButton("1️⃣ اکسل BOM")
        self.btn_top = QPushButton("2️⃣ اکسل TOP")
        self.btn_bot = QPushButton("3️⃣ اکسل BOT")
        for b in (self.btn_bom, self.btn_top, self.btn_bot):
            b.setObjectName("primaryBtn")
            b.setMinimumHeight(34)
        self.lbl_bom = QLabel("انتخاب نشده")
        self.lbl_top = QLabel("انتخاب نشده")
        self.lbl_bot = QLabel("انتخاب نشده")
        for lbl in (self.lbl_bom, self.lbl_top, self.lbl_bot):
            lbl.setStyleSheet("color:#8B93A7;")
        self.btn_bom.clicked.connect(lambda: self._select_role_file("bom"))
        self.btn_top.clicked.connect(lambda: self._select_role_file("top"))
        self.btn_bot.clicked.connect(lambda: self._select_role_file("bot"))
        g.addWidget(self.btn_bom, 0, 0)
        g.addWidget(self.lbl_bom, 0, 1)
        g.addWidget(self.btn_top, 1, 0)
        g.addWidget(self.lbl_top, 1, 1)
        g.addWidget(self.btn_bot, 2, 0)
        g.addWidget(self.lbl_bot, 2, 1)
        layout.addWidget(grid)

        self.btn_process3 = QPushButton("⚙ پردازش و اعتبارسنجی (سه‌فایل)")
        self.btn_process3.setObjectName("primaryBtn")
        self.btn_process3.setMinimumHeight(36)
        self.btn_process3.setEnabled(False)
        self.btn_process3.clicked.connect(self.process_triple)
        layout.addWidget(self.btn_process3)
        layout.addStretch(1)
        return tab

    def _build_license_tab(self) -> QWidget:
        """تب لایسنس — نمایش وضعیت، شناسهٔ دستگاه و ثبت کلید لایسنس."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        self.lbl_license_status = QLabel()
        self.lbl_license_status.setStyleSheet("font-size:14px;font-weight:bold;")
        layout.addWidget(self.lbl_license_status)

        info = QLabel("برای فعال‌سازی دائمی، شناسهٔ دستگاه را برای فروشنده بفرستید "
                      "و کلید لایسنس دریافتی را اینجا ثبت کنید.")
        info.setStyleSheet("color:#8B93A7;")
        info.setWordWrap(True)
        layout.addWidget(info)

        group = QGroupBox("شناسهٔ دستگاه")
        g = QHBoxLayout(group)
        self.ed_device_id = QLineEdit(license_core.get_device_id())
        self.ed_device_id.setReadOnly(True)
        self.ed_device_id.setStyleSheet("font-family:Consolas;")
        btn_copy_dev = QPushButton("کپی شناسه")
        btn_copy_dev.clicked.connect(self._copy_device_id)
        g.addWidget(self.ed_device_id, 1)
        g.addWidget(btn_copy_dev)
        layout.addWidget(group)

        group2 = QGroupBox("کلید لایسنس")
        g2 = QVBoxLayout(group2)
        self.ed_license_key = QPlainTextEdit()
        self.ed_license_key.setPlaceholderText("BOM2-XXXXX-XXXXX-…")
        self.ed_license_key.setMaximumHeight(80)
        self.ed_license_key.setStyleSheet("font-family:Consolas;")
        g2.addWidget(self.ed_license_key)
        layout.addWidget(group2)

        btns = QHBoxLayout()
        self.btn_license_activate = QPushButton("فعال‌سازی لایسنس")
        self.btn_license_activate.setObjectName("primaryBtn")
        self.btn_license_activate.setMinimumHeight(34)
        self.btn_license_activate.clicked.connect(self._activate_from_tab)
        self.btn_license_remove = QPushButton("حذف لایسنس")
        self.btn_license_remove.setObjectName("dangerBtn")
        self.btn_license_remove.clicked.connect(self._deactivate_from_tab)
        btns.addWidget(self.btn_license_activate)
        btns.addWidget(self.btn_license_remove)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.lbl_license_msg = QLabel("")
        self.lbl_license_msg.setWordWrap(True)
        layout.addWidget(self.lbl_license_msg)
        layout.addStretch(1)
        return tab

    def _copy_device_id(self) -> None:
        QGuiApplication.clipboard().setText(self.ed_device_id.text())
        self.lbl_license_msg.setStyleSheet("color:#34D399;")
        self.lbl_license_msg.setText("شناسهٔ دستگاه در کلیپ‌بورد کپی شد.")

    def _activate_from_tab(self) -> None:
        key = self.ed_license_key.toPlainText().strip()
        if not key:
            self.lbl_license_msg.setStyleSheet("color:#FBBF24;")
            self.lbl_license_msg.setText("کلید لایسنس را وارد کنید.")
            return
        state = license_core.activate(key)
        if state.ok:
            self.lbl_license_msg.setStyleSheet("color:#34D399;")
            self.lbl_license_msg.setText("لایسنس با موفقیت فعال شد.")
            self.ed_license_key.clear()
        else:
            self.lbl_license_msg.setStyleSheet("color:#F87171;")
            self.lbl_license_msg.setText(f"خطا: {state.reason}")
        self.refresh_license_badge()

    def _deactivate_from_tab(self) -> None:
        ret = QMessageBox.question(
            self, "حذف لایسنس",
            "لایسنس از این دستگاه حذف شود؟",
        )
        if ret == QMessageBox.StandardButton.Yes:
            license_core.deactivate()
            self.lbl_license_msg.setStyleSheet("color:#8B93A7;")
            self.lbl_license_msg.setText("لایسنس حذف شد.")
            self.refresh_license_badge()

    # -- تم -----------------------------------------------------------
    def apply_industrial_theme(self):
        style_sheet = """
            QMainWindow, QWidget {
                background-color: #0F1420;
                color: #E5E9F0;
                font-family: Tahoma, "Segoe UI";
            }
            QTabWidget::pane { border: 1px solid #2A3550; border-radius: 8px; }
            QTabBar::tab {
                background: #161D2B; color: #8B93A7; padding: 8px 18px;
                border-top-left-radius: 8px; border-top-right-radius: 8px;
                margin-left: 4px;
            }
            QTabBar::tab:selected { background: #1B2432; color: #60A5FA; font-weight: bold; }
            QGroupBox {
                border: 1px solid #2A3550;
                border-radius: 10px;
                margin-top: 12px;
                background-color: #161D2B;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 6px; color: #93A4C3;
            }
            QPushButton {
                background-color: #242F47; color: #E5E9F0;
                border: 1px solid #334267; border-radius: 6px;
                padding: 6px 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2E3B5C; }
            QPushButton:pressed { background-color: #1D2638; }
            QPushButton:disabled { background-color: #1A2130; color: #5A6478; border-color: #242F47; }
            QPushButton#primaryBtn { background-color: #2563EB; border-color: #1D4ED8; }
            QPushButton#primaryBtn:hover { background-color: #3B82F6; }
            QPushButton#primaryBtn:disabled { background-color: #1A2130; color: #5A6478; }
            QPushButton#successBtn { background-color: #059669; border-color: #047857; }
            QPushButton#successBtn:hover { background-color: #10B981; }
            QPushButton#successBtn:disabled { background-color: #1A2130; color: #5A6478; }
            QPushButton#dangerBtn { background-color: #B91C1C; border-color: #991B1B; }
            QLineEdit, QPlainTextEdit {
                background-color: #0D1420; color: #E5E9F0;
                border: 1px solid #2A3550; border-radius: 6px; padding: 6px;
                selection-background-color: #2563EB;
            }
            QLineEdit:focus, QPlainTextEdit:focus { border-color: #3B82F6; }
            QTableWidget {
                gridline-color: #242F47; border: 1px solid #2A3550;
                border-radius: 8px; background-color: #0D1420;
                alternate-background-color: #141B2A;
                selection-background-color: #1E3A8A; selection-color: white;
            }
            QHeaderView::section {
                background-color: #1B2432; color: #93A4C3;
                padding: 8px; border: none; border-left: 1px solid #242F47;
                border-bottom: 2px solid #2563EB; font-weight: bold;
            }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QProgressBar {
                border: 1px solid #2A3550; border-radius: 6px;
                text-align: center; background: #0D1420; color: #E5E9F0;
            }
            QProgressBar::chunk { background-color: #2563EB; border-radius: 5px; }
            QStatusBar { background-color: #0B0F1A; color: #8B93A7; border-top: 1px solid #2A3550; }
            QMessageBox QLabel { color: #E5E9F0; }
            QDialog { background-color: #0F1420; }
            QComboBox {
                background-color: #0D1420; border: 1px solid #2A3550;
                border-radius: 6px; padding: 4px 8px;
            }
        """
        self.setStyleSheet(style_sheet)

    # -- لایسنس ------------------------------------------------------
    def refresh_license_badge(self) -> None:
        state = license_core.current_state()
        icons = {"ok": "🔓", "trial": "🧪"}
        icon = icons.get(state.code, "🔒")
        self.badge_license.setText(f"{icon} {state.short_label}")
        self.setWindowTitle(f"{APP_TITLE} — v{APP_VERSION}")
        # به‌روزرسانی تب لایسنس
        if hasattr(self, "lbl_license_status"):
            colors = {"ok": "#34D399", "trial": "#FBBF24"}
            color = colors.get(state.code, "#F87171")
            self.lbl_license_status.setStyleSheet(
                f"font-size:14px;font-weight:bold;color:{color};")
            self.lbl_license_status.setText(
                f"{icon} وضعیت: {state.short_label if state.ok else state.reason}")

    def _require_license(self) -> bool:
        """هر عملیات حساس از اینجا عبور می‌کند؛ بدون لایسنس معتبر متوقف می‌شود."""
        state = license_core.current_state()
        if state.ok:
            return True
        dlg = ActivationDialog(state, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_license_badge()
            return True
        self.status_bar.showMessage("عملیات لغو شد: لایسنس معتبر نیست.")
        return False

    def show_license_info(self) -> None:
        dlg = LicenseInfoDialog(self, on_change=self.refresh_license_badge)
        dlg.exec()
        self.refresh_license_badge()

    # -- حالت تک‌فایل (منطق نسخهٔ اولیه) -------------------------------
    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل BOM", "", "Excel Files (*.xlsx *.xls)"
        )
        if file_name:
            self.target_file = file_name
            self.lbl_file_path.setText(file_name)
            self.btn_process.setEnabled(True)
            self.status_bar.showMessage("فایل بارگذاری شد. آماده پردازش.")

    def process_excel(self):
        if not self._require_license():
            return
        self.table_widget.setRowCount(0)
        self._set_busy(True, "در حال تحلیل داده‌ها…")
        QApplication.processEvents()

        try:
            xls = pd.ExcelFile(self.target_file, engine='openpyxl')

            target_sheet = find_bom_sheet_name(xls.sheet_names)
            if not target_sheet:
                QMessageBox.warning(self, "خطای اعتبارسنجی", "شیت مرجع 'مونتاژ ماشینی' یافت نشد.")
                self.status_bar.showMessage("خطا در یافتن شیت هدف.")
                return

            df_main = pd.read_excel(xls, sheet_name=target_sheet, header=None)

            top_name = _pick_sheet_name(list(xls.sheet_names), "top")
            bot_name = _pick_sheet_name(list(xls.sheet_names), "bot")
            self.top_sheet_used = top_name or "-"
            self.bot_sheet_used = bot_name or "-"
            self.top_data_cache = load_single_file_values(xls, top_name) if top_name else []
            self.bot_data_cache = load_single_file_values(xls, bot_name) if bot_name else []

            header_row, col_part, col_qty, col_stock = find_first_matching_headers(df_main)
            if header_row == -1 or col_part == -1 or col_qty == -1 or col_stock == -1:
                QMessageBox.warning(self, "خطای ساختاری",
                                    "عناوین اصلی Part Name، Qty و Stock طبق قانون یافت نشدند.")
                self.status_bar.showMessage("خطا در ساختار ستون‌ها.")
                return

            self.extracted_data_cache = extract_data(
                df_main, header_row, col_part, col_qty, col_stock)
            self.evaluate_and_display(self.extracted_data_cache,
                                      self.top_data_cache, self.bot_data_cache)
            license_core.note_successful_run()

        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "خطای پردازشگر",
                                 f"توقف سیستم به دلیل خطای پیش‌بینی نشده:\n{str(e)}")
            self.status_bar.showMessage("پردازش متوقف شد.")
        finally:
            self._set_busy(False)

    # -- حالت سه‌فایل --------------------------------------------------
    def _select_role_file(self, role: str) -> None:
        titles = {
            "bom": ("انتخاب اکسل BOM (منبع عنوان و ساختار)", self.lbl_bom),
            "top": ("انتخاب اکسل نقشهٔ TOP", self.lbl_top),
            "bot": ("انتخاب اکسل نقشهٔ BOT", self.lbl_bot),
        }
        title, label = titles[role]
        file_name, _ = QFileDialog.getOpenFileName(
            self, title, "", "Excel Files (*.xlsx *.xls)"
        )
        if not file_name:
            return
        setattr(self, f"{role}_file", file_name)
        label.setText(os.path.basename(file_name))
        label.setStyleSheet("color:#34D399;")
        self._update_triple_state()
        self.status_bar.showMessage(f"فایل {role.upper()} انتخاب شد.")

    def _update_triple_state(self) -> None:
        ready = bool(self.bom_file and self.top_file and self.bot_file)
        self.btn_process3.setEnabled(ready)

    def process_triple(self):
        if not self._require_license():
            return
        if not (self.bom_file and self.top_file and self.bot_file):
            QMessageBox.warning(self, "ناقص", "هر سه فایل BOM و TOP و BOT باید انتخاب شوند.")
            return

        self.table_widget.setRowCount(0)
        self._set_busy(True, "در حال پردازش سه فایل…")
        QApplication.processEvents()
        try:
            self.extracted_data_cache = extract_bom_rows(self.bom_file)
            self.top_data_cache, self.top_sheet_used = load_placement_values(self.top_file, "top")
            self.bot_data_cache, self.bot_sheet_used = load_placement_values(self.bot_file, "bot")
            self.evaluate_and_display(self.extracted_data_cache,
                                      self.top_data_cache, self.bot_data_cache)
            self.btn_export.setEnabled(bool(self.results_cache))
            license_core.note_successful_run()
            self.status_bar.showMessage(
                f"سه‌فایل پردازش شد. TOP: «{self.top_sheet_used}»، BOT: «{self.bot_sheet_used}» — "
                "حالا می‌توانید اکسل خروجی بسازید."
            )
        except ValueError as e:
            QMessageBox.warning(self, "خطای ساختاری", str(e))
            self.status_bar.showMessage("خطا در ساختار فایل‌ها.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "خطای پردازشگر",
                                 f"توقف سیستم به دلیل خطای پیش‌بینی نشده:\n{str(e)}")
            self.status_bar.showMessage("پردازش متوقف شد.")
        finally:
            self._set_busy(False)

    def export_combined_excel(self):
        if not self._require_license():
            return
        if not self.results_cache:
            QMessageBox.information(self, "بدون داده", "ابتدا پردازش سه‌فایل را انجام دهید.")
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "پوشهٔ ذخیرهٔ سه خروجی (TOP / BOT / BOM)",
            os.path.dirname(self.bom_file) or "",
        )
        if not out_dir:
            return
        self._set_busy(True, "در حال ساخت سه اکسل خروجی…")
        QApplication.processEvents()
        try:
            paths = build_all_outputs(
                self.bom_file, self.top_file, self.bot_file,
                self.results_cache, out_dir,
                top_sheet_name=self.top_sheet_used if self.top_sheet_used != "-" else "top",
                bot_sheet_name=self.bot_sheet_used if self.bot_sheet_used != "-" else "bot",
            )
            license_core.note_successful_run()
            listing = "\n".join(
                f"• {os.path.basename(p)}" for p in (paths["top"], paths["bot"], paths["bom"])
            )
            self.status_bar.showMessage(f"سه خروجی در «{out_dir}» ساخته شد.")
            QMessageBox.information(
                self, "موفق",
                "سه فایل خروجی با فرمت و نام فایل اصلی (+ v1) ساخته شد:\n\n"
                f"{listing}\n\n"
                "در هر سه فایل سلول G4 = \"P.Parsa\" و قفل است.\n"
                "نسخهٔ TOP فقط قطعات لایهٔ top + مختصات PCB را دارد و نسخهٔ BOT فقط bot."
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "خطای نوشتن خروجی", str(e))
            self.status_bar.showMessage("ساخت خروجی ناموفق بود.")
        finally:
            self._set_busy(False)

    # -- نمایش نتایج (نسخهٔ ارتقایافتهٔ همان تابع اولیه) -----------------
    def evaluate_and_display(self, data: list[dict], top_data_list: list[str],
                             bot_data_list: list[str]):
        self._apply_filter_silent_reset()
        results = evaluate_rows(data, top_data_list, bot_data_list)
        self.results_cache = results
        self.table_widget.setRowCount(len(results))

        for row_idx, item in enumerate(results):
            stock = item['Stock']
            part_name = item['Part Name']
            qty = item['Qty']
            is_valid = item['Valid']
            status_text = item['Status']

            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_box = QCheckBox()
            chk_box.setChecked(False)
            chk_layout.addWidget(chk_box)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table_widget.setCellWidget(row_idx, 0, chk_widget)

            items = [
                None,
                QTableWidgetItem(stock),
                QTableWidgetItem(part_name),
                QTableWidgetItem(str(item['Top'])),
                QTableWidgetItem(str(item['Bot'])),
                QTableWidgetItem(str(qty)),
                QTableWidgetItem(status_text),
            ]

            bg_color = QColor(24, 68, 45) if is_valid else QColor(78, 32, 36)
            text_color = QColor(52, 211, 153) if is_valid else QColor(248, 113, 113)

            for col_idx, table_item in enumerate(items):
                if col_idx > 0:
                    table_item.setBackground(bg_color)
                    if col_idx == 6:
                        table_item.setForeground(text_color)
                        font = QFont()
                        font.setBold(True)
                        table_item.setFont(font)

                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col_idx == 2:
                        table_item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                    self.table_widget.setItem(row_idx, col_idx, table_item)

        # به‌روزرسانی کارت‌ها
        total = len(results)
        passed = sum(1 for r in results if r['Valid'])
        self.kpi_total.set_value(total)
        self.kpi_pass.set_value(passed)
        self.kpi_fail.set_value(total - passed)
        self.kpi_top.set_value(sum(r['Top'] for r in results))
        self.kpi_bot.set_value(sum(r['Bot'] for r in results))
        self.chk_select_all.setChecked(False)

        self.status_bar.showMessage(
            f"پردازش با موفقیت انجام شد. {total} قطعه بررسی گردید — "
            f"TOP sheet: «{self.top_sheet_used}» | BOT sheet: «{self.bot_sheet_used}»"
        )

    # -- ابزارهای جدول -------------------------------------------------
    def _toggle_select_all(self, state) -> None:
        checked = state == Qt.CheckState.Checked.value
        for row in range(self.table_widget.rowCount()):
            widget = self.table_widget.cellWidget(row, 0)
            if widget and not self.table_widget.isRowHidden(row):
                box = widget.findChild(QCheckBox)
                if box:
                    box.setChecked(checked)

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        visible = 0
        for row in range(self.table_widget.rowCount()):
            stock = (self.table_widget.item(row, 1).text()
                     if self.table_widget.item(row, 1) else "")
            part = (self.table_widget.item(row, 2).text()
                    if self.table_widget.item(row, 2) else "")
            match = (not query) or (query in stock.lower()) or (query in part.lower())
            self.table_widget.setRowHidden(row, not match)
            visible += match
        if self.results_cache:
            self.status_bar.showMessage(f"{visible} ردیف نمایش داده می‌شود (فیلتر فعال).")

    def _apply_filter_silent_reset(self) -> None:
        self.search_box.blockSignals(True)
        self.search_box.clear()
        self.search_box.blockSignals(False)

    def copy_fail_rows(self) -> None:
        fails = [r for r in self.results_cache if not r['Valid']]
        if not fails:
            QMessageBox.information(self, "بدون خطا", "مورد FAIL وجود ندارد.")
            return
        lines = ["Stock ID\tPart Name\tQty\tTOP\tBOT"]
        for r in fails:
            lines.append(f"{r['Stock']}\t{r['Part Name']}\t{r['Qty']}\t{r['Top']}\t{r['Bot']}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.status_bar.showMessage(f"{len(fails)} مورد FAIL در کلیپ‌بورد کپی شد.")

    def _on_tab_change(self, index: int) -> None:
        if index != 1:
            self.btn_export.setEnabled(False)
        else:
            self.btn_export.setEnabled(bool(self.results_cache))
        self.status_bar.showMessage(
            "حالت تک‌فایل فعال است." if index == 0 else "حالت سه‌فایل فعال است."
        )

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)  # حالت نامشخص
            self.status_bar.showMessage(message)
        else:
            self.progress.setRange(0, 1)


# ---------------------------------------------------------------------------
# نقطهٔ ورود — برنامه باز می‌شود؛ دسترسی بر اساس لایسنس/آزمایشی
# ---------------------------------------------------------------------------

def ensure_license() -> bool:
    """
    برنامه همیشه باز می‌شود؛ اما:
    * با لایسنس معتبر یا در دورهٔ آزمایشی یک‌ماهه → ادامهٔ عادی
    * پایان آزمایش بدون لایسنس → دیالوگ اجباری فعال‌سازی؛ انصراف = خروج از برنامه
    """
    state = license_core.current_state()
    if state.ok:
        return True
    dlg = ActivationDialog(state)
    return dlg.exec() == QDialog.DialogCode.Accepted


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)

    font = app.font()
    font.setFamily("Tahoma")
    font.setPointSize(9)
    app.setFont(font)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    app.setStyleSheet(
        "QToolTip { background:#1B2432; color:#E5E9F0; border:1px solid #2A3550; }")

    window = IndustrialBOMValidator()
    window.show()

    # پس از نمایش پنجره: اگر دورهٔ آزمایشی تمام و لایسنسی نیست، فعال‌سازی اجباری است
    if not ensure_license():
        return 0

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
