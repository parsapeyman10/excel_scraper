# -*- mode: python ; coding: utf-8 -*-
"""
مشخصات PyInstaller — ساخت exe تک‌فایلیِ «BOM Validator» با آیکون.

اجرا (از ریشهٔ پروژه، روی ویندوز):
    pyinstaller app.spec --clean --noconfirm

* آیکون: فایل app_icon.* یا web-data-scraping-icon-svg-download-png-3587064.*
  در کنار همین فایل باشد تا خودکار پیدا، تبدیل و روی exe و پنجره نصب شود.
* خروجی:  dist/BOM Validator.exe  (تک‌فایل، بدون پنجرهٔ کنسول)
* license_generator.py عمداً داخل exe قرار نمی‌گیرد — فقط نزد مالک می‌ماند.
"""

import os
import sys

sys.path.insert(0, os.getcwd())

from build_icons import prepare_icons  # noqa: E402

block_cipher = None
PROJECT_DIR = os.getcwd()

icons = prepare_icons(PROJECT_DIR, os.path.join("build", "assets"))

datas = []
if icons["runtime_icon"]:
    # در ریشهٔ بسته قرار می‌گیرد تا excel scraper.py آن را از _MEIPASS بخواند
    datas.append((icons["runtime_icon"], "."))

a = Analysis(
    ["excel scraper.py"],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ماژول‌های سنگین Qt/Py که در این برنامه استفاده نمی‌شوند (حجم خروجی)
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
        "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtQuickWidgets",
        "PyQt6.QtQml", "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput",
        "PyQt6.QtCharts", "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtNetwork", "PyQt6.QtSql", "PyQt6.QtBluetooth", "PyQt6.QtNfc",
        "PyQt6.QtSerialPort", "PyQt6.QtPositioning", "PyQt6.QtSensors",
        "PyQt6.QtTest", "PyQt6.QtDesigner", "PyQt6.QtPdf", "PyQt6.QtPdfWidgets",
        "PyQt5", "PySide2", "PySide6",
        "matplotlib", "tkinter", "IPython", "jupyter", "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BOM Validator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX گاهی هشدار کاذب آنتی‌ویروس می‌دهد
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # برنامهٔ پنجره‌ای — بدون کنسول سیاه
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icons["exe_icon"],
)
