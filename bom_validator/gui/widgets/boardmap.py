"""Interactive PCB placement map.

Renders every pick-and-place coordinate as a marker, colour coded by the
validation status of its BOM line. Supports pan, wheel zoom, layer toggling,
search highlighting and click-to-select.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import Layer, Placement, ValidationReport
from .. import theme as th


@dataclass(slots=True)
class Marker:
    placement: Placement
    status: str
    key: str


class BoardCanvas(QWidget):
    marker_clicked = pyqtSignal(str)  # emits the placement key

    def __init__(self, parent=None, theme: str = "industrial-light"):
        super().__init__(parent)
        self.theme = theme
        self._markers: list[Marker] = []
        self._bounds = QRectF(0, 0, 100, 100)
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._last_mouse: QPointF | None = None
        self._show_top = True
        self._show_bot = True
        self._highlight = ""
        self._status_filter = ""
        self._show_labels = False
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # -- data ---------------------------------------------------------
    def set_placements(self, placements: list[Placement], report: ValidationReport | None) -> None:
        status_by_designator: dict[str, str] = {}
        status_by_key: dict[str, str] = {}
        if report:
            for r in report.results:
                for d in r.matched_top + r.matched_bot:
                    status_by_designator[d.upper()] = r.status.value
                if r.line.key:
                    status_by_key[r.line.key.upper()] = r.status.value
            for p in report.orphan_placements:
                if p.designator:
                    status_by_designator.setdefault(p.designator.upper(), "ORPHAN")
        self._markers = [
            Marker(
                p,
                status_by_designator.get(
                    p.designator.upper(),
                    status_by_key.get(p.key.upper(), "UNKNOWN"),
                ),
                p.key,
            )
            for p in placements
            if p.x is not None and p.y is not None
        ]
        self._fit()
        self.update()

    def _fit(self) -> None:
        xs = [m.placement.x for m in self._markers if m.placement.x is not None]
        ys = [m.placement.y for m in self._markers if m.placement.y is not None]
        if xs and ys:
            pad = 6
            self._bounds = QRectF(
                min(xs) - pad,
                min(ys) - pad,
                max(max(xs) - min(xs), 1) + 2 * pad,
                max(max(ys) - min(ys), 1) + 2 * pad,
            )
        else:
            self._bounds = QRectF(0, 0, 100, 100)
        self._zoom = 1.0
        self._pan = QPointF(0, 0)

    # -- view state ---------------------------------------------------
    def set_layers(self, top: bool, bot: bool) -> None:
        self._show_top, self._show_bot = top, bot
        self.update()

    def set_highlight(self, text: str) -> None:
        self._highlight = text.strip().upper()
        self.update()

    def set_status_filter(self, status: str) -> None:
        self._status_filter = status
        self.update()

    def set_show_labels(self, show: bool) -> None:
        self._show_labels = show
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self.update()

    def zoom_by(self, factor: float) -> None:
        self._zoom = max(0.2, min(40.0, self._zoom * factor))
        self.update()

    # -- geometry -----------------------------------------------------
    def _scale(self) -> float:
        if self._bounds.width() <= 0 or self._bounds.height() <= 0:
            return 1.0
        margin = 20
        sx = (self.width() - 2 * margin) / self._bounds.width()
        sy = (self.height() - 2 * margin) / self._bounds.height()
        return min(sx, sy) * self._zoom

    def _to_screen(self, x: float, y: float) -> QPointF:
        s = self._scale()
        cx = self.width() / 2 + self._pan.x()
        cy = self.height() / 2 + self._pan.y()
        return QPointF(
            cx + (x - self._bounds.center().x()) * s,
            cy - (y - self._bounds.center().y()) * s,  # Y up, like a PCB
        )

    def _visible(self, m: Marker) -> bool:
        if m.placement.layer is Layer.TOP and not self._show_top:
            return False
        if m.placement.layer is Layer.BOT and not self._show_bot:
            return False
        return not (self._status_filter and m.status != self._status_filter)

    # -- events -------------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        self.zoom_by(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() is Qt.MouseButton.LeftButton:
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_mouse is not None:
            delta = event.position() - self._last_mouse
            self._pan += delta
            self._last_mouse = event.position()
            self.update()
            return
        hit = self._hit_test(event.position())
        if hit:
            p = hit.placement
            self.setToolTip(
                f"<b>{p.designator or p.key}</b><br>{p.description}<br>"
                f"{p.layer.label} · ({p.x:.3f}, {p.y:.3f}) mm · rot {p.rotation}°<br>"
                f"stock {p.stock_no or '—'} · status {hit.status}"
            )
        else:
            self.setToolTip("")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        was_drag = self._last_mouse is not None and (
            (event.position() - self._last_mouse).manhattanLength() > 3
        )
        self._last_mouse = None
        if not was_drag:
            hit = self._hit_test(event.position())
            if hit:
                self.marker_clicked.emit(hit.placement.designator or hit.key)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.reset_view()

    def _hit_test(self, pos: QPointF) -> Marker | None:
        best, best_d = None, 9.0
        for m in self._markers:
            if not self._visible(m):
                continue
            sp = self._to_screen(m.placement.x or 0, m.placement.y or 0)
            d = (sp - pos).manhattanLength()
            if d < best_d:
                best, best_d = m, d
        return best

    # -- painting -----------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = th.palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(p["surface_alt"]))

        colors = {
            "PASS": QColor(p["pass"]),
            "WARN": QColor(p["warn"]),
            "FAIL": QColor(p["fail"]),
            "NOT_PLACED": QColor(p["crit"]),
            "ORPHAN": QColor(p["accent"]),
            "UNKNOWN": QColor(p["muted"]),
        }

        # board outline
        tl = self._to_screen(self._bounds.left(), self._bounds.top() + self._bounds.height())
        br = self._to_screen(self._bounds.left() + self._bounds.width(), self._bounds.top())
        outline = QRectF(tl, br).normalized()
        painter.setPen(QPen(QColor(p["border"]), 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(p["surface"]))
        painter.drawRoundedRect(outline, 6, 6)

        # grid every 10 mm
        s = self._scale()
        if s > 1.2:
            painter.setPen(QPen(QColor(p["border"]), 0.5, Qt.PenStyle.DotLine))
            x = int(self._bounds.left() // 10 * 10)
            while x < self._bounds.right():
                sx = self._to_screen(x, 0).x()
                if outline.left() <= sx <= outline.right():
                    painter.drawLine(QPointF(sx, outline.top()), QPointF(sx, outline.bottom()))
                x += 10
            y = int(self._bounds.top() // 10 * 10)
            while y < self._bounds.bottom():
                sy = self._to_screen(0, y).y()
                if outline.top() <= sy <= outline.bottom():
                    painter.drawLine(QPointF(outline.left(), sy), QPointF(outline.right(), sy))
                y += 10

        radius = max(2.0, min(9.0, s * 0.55))
        font = QFont()
        font.setPointSizeF(max(5.5, min(9.0, radius * 1.3)))
        painter.setFont(font)

        shown = 0
        for m in self._markers:
            if not self._visible(m):
                continue
            shown += 1
            sp = self._to_screen(m.placement.x or 0, m.placement.y or 0)
            if not self.rect().adjusted(-40, -40, 40, 40).contains(sp.toPoint()):
                continue
            color = colors.get(m.status, colors["UNKNOWN"])
            match = bool(self._highlight) and (
                self._highlight in (m.placement.designator or "").upper()
                or self._highlight in (m.key or "").upper()
            )
            if self._highlight and not match:
                color = QColor(color)
                color.setAlpha(45)
            painter.setBrush(color)
            painter.setPen(
                QPen(QColor("#FFFFFF") if match else QColor(0, 0, 0, 60), 2 if match else 0.6)
            )
            if m.placement.layer is Layer.TOP:
                painter.drawEllipse(sp, radius, radius)
            else:
                painter.drawRect(QRectF(sp.x() - radius, sp.y() - radius, radius * 2, radius * 2))
            if match:
                painter.setPen(QPen(QColor(p["accent"]), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(sp, radius * 2.6, radius * 2.6)
            if (self._show_labels and radius >= 4) or match:
                painter.setPen(QColor(p["ink"]))
                painter.drawText(
                    QRectF(sp.x() + radius + 2, sp.y() - 8, 90, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    m.placement.designator or "",
                )

        painter.setPen(QColor(p["muted"]))
        f2 = QFont()
        f2.setPointSize(8)
        painter.setFont(f2)
        painter.drawText(
            QRectF(10, self.height() - 22, self.width() - 20, 16),
            Qt.AlignmentFlag.AlignLeft,
            f"{shown} / {len(self._markers)} placements · zoom {self._zoom:.1f}× · "
            f"{self._bounds.width():.0f} × {self._bounds.height():.0f} mm · "
            "● top  ■ bottom · drag to pan, wheel to zoom, double-click to reset",
        )
        painter.end()


class BoardMapWidget(QWidget):
    """Canvas plus its toolbar."""

    designator_selected = pyqtSignal(str)

    def __init__(self, tr, theme: str = "industrial-light", parent=None):
        super().__init__(parent)
        self.tr_ = tr
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self.chk_top = QCheckBox("Top")
        self.chk_top.setChecked(True)
        self.chk_bot = QCheckBox("Bottom")
        self.chk_bot.setChecked(True)
        self.chk_labels = QCheckBox("Labels")
        self.cmb_status = QComboBox()
        self.cmb_status.addItem("All statuses", "")
        for s in ("PASS", "WARN", "FAIL", "NOT_PLACED", "ORPHAN"):
            self.cmb_status.addItem(s, s)
        self.txt_find = QLineEdit()
        self.txt_find.setPlaceholderText("Highlight designator or stock…")
        self.txt_find.setMaximumWidth(260)
        btn_in = QPushButton("+")
        btn_out = QPushButton("−")
        btn_fit = QPushButton("Fit")
        for b in (btn_in, btn_out, btn_fit):
            b.setObjectName("secondary")
            b.setMaximumWidth(46)

        bar.addWidget(QLabel("Layers:"))
        bar.addWidget(self.chk_top)
        bar.addWidget(self.chk_bot)
        bar.addWidget(self.chk_labels)
        bar.addSpacing(10)
        bar.addWidget(self.cmb_status)
        bar.addWidget(self.txt_find, 1)
        bar.addWidget(btn_out)
        bar.addWidget(btn_in)
        bar.addWidget(btn_fit)
        lay.addLayout(bar)

        self.canvas = BoardCanvas(theme=theme)
        lay.addWidget(self.canvas, 1)

        self.chk_top.toggled.connect(self._sync_layers)
        self.chk_bot.toggled.connect(self._sync_layers)
        self.chk_labels.toggled.connect(self.canvas.set_show_labels)
        self.cmb_status.currentIndexChanged.connect(
            lambda: self.canvas.set_status_filter(self.cmb_status.currentData())
        )
        self.txt_find.textChanged.connect(self.canvas.set_highlight)
        btn_in.clicked.connect(lambda: self.canvas.zoom_by(1.3))
        btn_out.clicked.connect(lambda: self.canvas.zoom_by(1 / 1.3))
        btn_fit.clicked.connect(self.canvas.reset_view)
        self.canvas.marker_clicked.connect(self.designator_selected.emit)

    def _sync_layers(self) -> None:
        self.canvas.set_layers(self.chk_top.isChecked(), self.chk_bot.isChecked())

    def set_data(self, placements, report) -> None:
        self.canvas.set_placements(placements, report)

    def set_theme(self, theme: str) -> None:
        self.canvas.set_theme(theme)

    def highlight(self, text: str) -> None:
        self.txt_find.setText(text)
