"""GUI bootstrap."""

from __future__ import annotations

import logging
import os
import sys

from ..config import AppSettings
from ..version import APP_ID, APP_NAME, ORG_NAME, __version__

log = logging.getLogger(__name__)


def run_gui(initial_file: str | None = None) -> int:
    """Create the QApplication and show the main window."""
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont, QGuiApplication
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(
            "PyQt6 is not installed. Install the desktop extras with:\n"
            "    pip install 'bom-validator[gui]'\n"
            "or use the command line: python -m bom_validator validate FILE",
            file=sys.stderr,
        )
        return 2

    from .main_window import MainWindow

    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setDesktopFileName(APP_ID)

    settings = AppSettings.load()
    font = QFont("Segoe UI" if os.name == "nt" else "Sans Serif")
    font.setPointSize(settings.font_size)
    app.setFont(font)
    if settings.language in {"fa", "ar", "he", "ur"}:
        QGuiApplication.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def excepthook(exc_type, exc, tb) -> None:
        import traceback

        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", text)
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Unexpected error")
        box.setText(f"{exc_type.__name__}: {exc}")
        box.setDetailedText(text)
        box.exec()

    sys.excepthook = excepthook

    window = MainWindow(initial_file)
    window.show()
    return app.exec()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run_gui(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    sys.exit(main())
