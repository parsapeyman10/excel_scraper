"""Qt stylesheets — industrial light, dark and high-contrast variants."""

from __future__ import annotations

from functools import lru_cache

PALETTES = {
    "industrial-light": {
        "bg": "#F0F2F5",
        "surface": "#FFFFFF",
        "surface_alt": "#F7F9FA",
        "border": "#C6CDD3",
        "ink": "#1F2933",
        "muted": "#6B7280",
        "accent": "#2980B9",
        "accent_hi": "#3498DB",
        "accent_dim": "#1B5E85",
        "header": "#34495E",
        "header_ink": "#FFFFFF",
        "pass": "#1E8E3E",
        "pass_bg": "#E6F4EA",
        "warn": "#B06000",
        "warn_bg": "#FEF7E0",
        "fail": "#C5221F",
        "fail_bg": "#FCE8E6",
        "crit": "#8B1A0E",
        "crit_bg": "#F9DCD6",
    },
    "industrial-dark": {
        "bg": "#16191D",
        "surface": "#1E2227",
        "surface_alt": "#23282E",
        "border": "#343B44",
        "ink": "#E6E9EC",
        "muted": "#9AA4AF",
        "accent": "#3498DB",
        "accent_hi": "#5DADE2",
        "accent_dim": "#21618C",
        "header": "#11151A",
        "header_ink": "#DCE3EA",
        "pass": "#5CD68A",
        "pass_bg": "#17331F",
        "warn": "#F0B429",
        "warn_bg": "#3A2E10",
        "fail": "#FF6B6B",
        "fail_bg": "#3A1A1A",
        "crit": "#FF8A65",
        "crit_bg": "#3F2015",
    },
    "high-contrast": {
        "bg": "#000000",
        "surface": "#0A0A0A",
        "surface_alt": "#141414",
        "border": "#FFFFFF",
        "ink": "#FFFFFF",
        "muted": "#D0D0D0",
        "accent": "#00A3FF",
        "accent_hi": "#33BBFF",
        "accent_dim": "#0077BB",
        "header": "#000000",
        "header_ink": "#FFFF00",
        "pass": "#00FF6A",
        "pass_bg": "#002A12",
        "warn": "#FFD400",
        "warn_bg": "#2B2300",
        "fail": "#FF3B30",
        "fail_bg": "#2E0000",
        "crit": "#FF9500",
        "crit_bg": "#2E1A00",
    },
}

THEMES = list(PALETTES)

_TEMPLATE = """
QWidget {{ color: {ink}; font-family: 'Segoe UI', Tahoma, 'Iran Sans', sans-serif; }}
QMainWindow, QDialog {{ background: {bg}; }}
QToolBar {{ background: {surface}; border-bottom: 1px solid {border}; spacing: 4px;
           padding: 4px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 5px; color: {ink}; }}
QToolBar QToolButton:hover {{ background: {accent}; color: #fff; }}
QToolBar QToolButton:disabled {{ color: {muted}; }}
QToolBar QToolButton:checked {{ background: {accent_dim}; color: #fff; }}
QMenuBar {{ background: {surface}; border-bottom: 1px solid {border}; }}
QMenuBar::item:selected {{ background: {accent}; color: #fff; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent}; color: #fff; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px;
             background: {surface}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px;
                    color: {accent}; }}

QPushButton {{ background: {accent}; color: #fff; border: none; border-radius: 5px;
               font-weight: 600; padding: 7px 16px; }}
QPushButton:hover {{ background: {accent_hi}; }}
QPushButton:pressed {{ background: {accent_dim}; }}
QPushButton:disabled {{ background: {border}; color: {muted}; }}
QPushButton[flat="true"], QPushButton#secondary {{ background: {surface_alt};
    color: {ink}; border: 1px solid {border}; }}
QPushButton#secondary:hover {{ background: {border}; }}
QPushButton#danger {{ background: {fail}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QDateEdit {{
    background: {surface}; border: 1px solid {border}; border-radius: 5px;
    padding: 5px 8px; selection-background-color: {accent}; color: {ink}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border};
    selection-background-color: {accent}; selection-color: #fff; }}

QTableView, QTreeView, QListView {{ background: {surface}; alternate-background-color:
    {surface_alt}; gridline-color: {border}; border: 1px solid {border};
    border-radius: 6px; selection-background-color: {accent};
    selection-color: #fff; }}
QHeaderView::section {{ background: {header}; color: {header_ink}; padding: 7px 6px;
    border: none; border-right: 1px solid {border}; font-weight: 600; }}
QHeaderView::section:hover {{ background: {accent_dim}; }}
QTableCornerButton::section {{ background: {header}; border: none; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px;
    background: {surface}; top: -1px; }}
QTabBar::tab {{ background: {surface_alt}; color: {muted}; padding: 8px 18px;
    border: 1px solid {border}; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {surface}; color: {accent}; font-weight: 700;
    border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {ink}; }}

QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{ border: 1px solid {border}; border-radius: 5px; background: {surface_alt};
    text-align: center; height: 16px; color: {ink}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {accent}; }}
QDockWidget {{ titlebar-close-icon: none; color: {ink}; }}
QDockWidget::title {{ background: {surface_alt}; padding: 7px; border: 1px solid {border};
    border-radius: 5px; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator:unchecked {{ border: 1px solid {border}; border-radius: 3px;
    background: {surface}; }}
QCheckBox::indicator:checked {{ border: 1px solid {accent}; border-radius: 3px;
    background: {accent}; }}
QToolTip {{ background: {header}; color: {header_ink}; border: 1px solid {accent};
    padding: 5px; border-radius: 4px; }}
QLabel#kpiValue {{ font-size: 26px; font-weight: 800; }}
QLabel#kpiKey {{ color: {muted}; font-size: 10px; letter-spacing: 1px; }}
QLabel#hint {{ color: {muted}; }}
QFrame#kpiCard {{ background: {surface}; border: 1px solid {border}; border-radius: 9px; }}
"""


@lru_cache(maxsize=8)
def stylesheet(theme: str = "industrial-light") -> str:
    """Formatted QSS. Cached — re-applying a theme should be instant."""
    palette = PALETTES.get(theme, PALETTES["industrial-light"])
    return _TEMPLATE.format(**palette)


def palette(theme: str = "industrial-light") -> dict[str, str]:
    return PALETTES.get(theme, PALETTES["industrial-light"])


@lru_cache(maxsize=8)
def _status_colors_cached(theme: str) -> dict[str, tuple[str, str]]:
    p = palette(theme)
    return {
        "PASS": (p["pass_bg"], p["pass"]),
        "WARN": (p["warn_bg"], p["warn"]),
        "FAIL": (p["fail_bg"], p["fail"]),
        "NOT_PLACED": (p["crit_bg"], p["crit"]),
        "UNKNOWN": (p["surface_alt"], p["muted"]),
    }


def status_colors(theme: str) -> dict[str, tuple[str, str]]:
    """status value -> (background, foreground). Returns a private copy."""
    return dict(_status_colors_cached(theme))
