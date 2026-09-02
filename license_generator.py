"""
ابزار صدور لایسنس — مخصوص مالک نرم‌افزار (SPCO)
================================================

⚠️  این فایل را **هرگز به مشتری ندهید**. هر کسی به این فایل و license_core.py
    دسترسی داشته باشد می‌تواند برای هر دستگاهی لایسنس بسازد.

کاربرد:
------

حالت گرافیکی (پیش‌فرض):

    python license_generator.py

حالت خط فرمان:

    python license_generator.py --device ABCDE-12345-... --plan 3
    python license_generator.py --device <شناسه> --plan 1        # ۱ ماهه
    python license_generator.py --device <شناسه> --plan 6        # ۶ ماهه

بازرسی یک کلید (مشاهدهٔ محتوای آن بدون نیاز به دستگاه مشتری):

    python license_generator.py --inspect "BOM2-XXXXX-..."
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

import license_core

OWNER_WARNING = (
    "این ابزار فقط برای مالک نرم‌افزار است؛ به مشتری تحویل داده نشود."
)


def _make_key(device: str, months: int) -> str:
    key = license_core.build_license_key(device, months)
    state = license_core.verify_license_key(key, device_id=device)
    exp = state.expires_at.strftime("%Y-%m-%d %H:%M") if state.expires_at else "?"
    print(f"Device        : {device}")
    print(f"Plan          : {months} ماهه ({license_core.PLAN_TITLES.get(f'M{months}', '')})")
    print(f"Expires       : {exp}")
    print("License Key   :")
    print(key)
    return key


def _inspect(key: str) -> None:
    decoded = license_core._decode_key(key)
    if decoded is None:
        print("کلید نامعتبر است (قالب ناشناخته).")
        sys.exit(2)
    payload_bytes, sig = decoded
    import hashlib
    import hmac
    import json

    expect = hmac.new(license_core._master_key(), payload_bytes, hashlib.sha256).digest()
    print("Signature OK  :", hmac.compare_digest(expect, sig))
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        print("محتوای لایسنس خوانا نیست.")
        sys.exit(2)
    print("Device        :", payload.get("dev"))
    print("Plan          :", license_core.PLAN_TITLES.get(payload.get("plan", ""), payload.get("plan")))
    print("Issued        :", datetime.fromtimestamp(int(payload.get("iat", 0))))
    print("Expires       :", datetime.fromtimestamp(int(payload.get("exp", 0))))


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="صدور لایسنس BOM Validator — " + OWNER_WARNING
    )
    parser.add_argument("--device", help="شناسهٔ دستگاه مشتری (از داخل برنامه کپی می‌شود)")
    parser.add_argument("--plan", type=int, choices=[1, 3, 6], help="مدت لایسنس به ماه")
    parser.add_argument("--inspect", metavar="KEY", help="بازرسی محتوای یک کلید لایسنس")
    parser.add_argument("--gui", action="store_true", help="اجرای رابط گرافیکی")
    args = parser.parse_args(argv)

    if args.inspect:
        _inspect(args.inspect)
        return 0

    if args.device and args.plan:
        _make_key(args.device.strip(), args.plan)
        return 0

    if args.gui or (not args.device and not args.plan):
        return run_gui()

    parser.error("هم --device و هم --plan لازم است")
    return 2


# ---------------------------------------------------------------------------
# رابط گرافیکی کوچک مخصوص مالک
# ---------------------------------------------------------------------------
def run_gui() -> int:
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont, QGuiApplication
        from PyQt6.QtWidgets import (
            QApplication,
            QComboBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("PyQt6 نصب نیست؛ از حالت خط فرمان استفاده کنید:")
        print("  python license_generator.py --device <شناسه> --plan <1|3|6>")
        return 1

    app = QApplication(sys.argv)
    app.setFont(QFont("Tahoma", 9))
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    win = QWidget()
    win.setWindowTitle("صدور لایسنس — فقط برای مالک (SPCO)")
    win.setMinimumWidth(560)
    layout = QVBoxLayout(win)
    layout.setSpacing(8)

    warn = QLabel("⚠ " + OWNER_WARNING)
    warn.setStyleSheet("color:#b91c1c;font-weight:bold;")
    layout.addWidget(warn)

    layout.addWidget(QLabel("شناسهٔ دستگاه مشتری:"))
    ed_device = QLineEdit()
    ed_device.setPlaceholderText("مثال: ABCDE-12345-…")
    layout.addWidget(ed_device)

    row = QHBoxLayout()
    row.addWidget(QLabel("مدت لایسنس:"))
    cmb_plan = QComboBox()
    cmb_plan.addItem("یک‌ماهه", 1)
    cmb_plan.addItem("سه‌ماهه", 3)
    cmb_plan.addItem("شش‌ماهه", 6)
    cmb_plan.setCurrentIndex(1)
    row.addWidget(cmb_plan, 1)
    layout.addLayout(row)

    btn_make = QPushButton("ساخت کلید لایسنس")
    btn_make.setMinimumHeight(34)
    layout.addWidget(btn_make)

    out = QPlainTextEdit()
    out.setReadOnly(True)
    out.setPlaceholderText("کلید ساخته‌شده اینجا نمایش داده می‌شود…")
    layout.addWidget(out)

    btn_copy = QPushButton("کپی کلید در کلیپ‌بورد")
    layout.addWidget(btn_copy)

    def make():
        device = ed_device.text().strip()
        if not device:
            QMessageBox.warning(win, "خطا", "شناسهٔ دستگاه را وارد کنید.")
            return
        months = int(cmb_plan.currentData())
        try:
            key = license_core.build_license_key(device, months)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(win, "خطا", str(exc))
            return
        state = license_core.verify_license_key(key, device_id=device)
        exp = state.expires_at.strftime("%Y/%m/%d") if state.expires_at else "?"
        out.setPlainText(f"{key}\n\n(پلن {months} ماهه — انقضا: {exp})")

    def copy():
        QGuiApplication.clipboard().setText(out.toPlainText().splitlines()[0] if out.toPlainText() else "")

    btn_make.clicked.connect(make)
    btn_copy.clicked.connect(copy)

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
