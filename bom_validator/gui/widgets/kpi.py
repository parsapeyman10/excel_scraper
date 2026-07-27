"""KPI cards, gauges and lightweight charts drawn with QPainter (no deps)."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...models import ValidationSummary
from .. import theme as th


class KpiCard(QFrame):
    """A single click-able metric tile."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, value: str = "—", accent: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("kpiCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(140, 82)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.lbl_key = QLabel(title.upper())
        self.lbl_key.setObjectName("kpiKey")
        self.lbl_value = QLabel(value)
        self.lbl_value.setObjectName("kpiValue")
        self.lbl_sub = QLabel("")
        self.lbl_sub.setObjectName("hint")
        lay.addWidget(self.lbl_key)
        lay.addWidget(self.lbl_value)
        lay.addWidget(self.lbl_sub)
        self._accent = accent
        if accent:
            self.lbl_value.setStyleSheet(f"color:{accent};")

    def set_value(self, value, sub: str = "") -> None:
        self.lbl_value.setText(str(value))
        self.lbl_sub.setText(sub)

    def set_title(self, title: str) -> None:
        self.lbl_key.setText(title.upper())

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.lbl_value.setStyleSheet(f"color:{color};")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class GaugeWidget(QWidget):
    """Semi-circular health gauge, 0..100."""

    def __init__(self, parent=None, theme: str = "industrial-light"):
        super().__init__(parent)
        self._value = 0.0
        self._label = "HEALTH"
        self.theme = theme
        self.setMinimumSize(190, 130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_value(self, value: float, label: str = "HEALTH") -> None:
        self._value = max(0.0, min(100.0, float(value)))
        self._label = label
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def _color(self) -> QColor:
        p = th.palette(self.theme)
        if self._value >= 85:
            return QColor(p["pass"])
        if self._value >= 60:
            return QColor(p["warn"])
        return QColor(p["fail"])

    def paintEvent(self, event) -> None:  # noqa: N802
        p = th.palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 16
        side = min(w - 2 * margin, (h - margin) * 2)
        rect = QRectF((w - side) / 2, margin, side, side)

        pen = QPen(QColor(p["border"]), 15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 180 * 16, -180 * 16)

        pen.setColor(self._color())
        painter.setPen(pen)
        painter.drawArc(rect, 180 * 16, int(-180 * 16 * self._value / 100))

        painter.setPen(QColor(p["ink"]))
        f = QFont()
        f.setPointSize(22)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(
            QRectF(rect.left(), rect.center().y() - 24, rect.width(), 40),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._value:.0f}",
        )
        f.setPointSize(8)
        f.setBold(False)
        painter.setFont(f)
        painter.setPen(QColor(p["muted"]))
        painter.drawText(
            QRectF(rect.left(), rect.center().y() + 12, rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )
        painter.end()


class StackedBar(QWidget):
    """Horizontal proportional bar: pass / warn / fail / not-placed."""

    def __init__(self, parent=None, theme: str = "industrial-light"):
        super().__init__(parent)
        self._segments: list[tuple[str, int, str]] = []
        self.theme = theme
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_summary(self, s: ValidationSummary) -> None:
        p = th.palette(self.theme)
        self._segments = [
            ("PASS", s.passed, p["pass"]),
            ("WARN", s.warnings, p["warn"]),
            ("FAIL", s.failed, p["fail"]),
            ("UNPLACED", s.not_placed, p["crit"]),
        ]
        self.setToolTip(
            " · ".join(f"{n}: {v}" for n, v, _ in self._segments if v)
        )
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = th.palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(v for _, v, _ in self._segments) or 1
        w, h = self.width(), self.height()
        radius = h / 2
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.setClipPath(path)
        painter.fillRect(0, 0, w, h, QColor(p["surface_alt"]))
        x = 0.0
        for name, value, color in self._segments:
            if not value:
                continue
            seg_w = w * value / total
            painter.fillRect(QRectF(x, 0, seg_w, h), QColor(color))
            if seg_w > 46:
                painter.setPen(QColor("#FFFFFF"))
                f = QFont()
                f.setPointSize(8)
                f.setBold(True)
                painter.setFont(f)
                painter.drawText(
                    QRectF(x, 0, seg_w, h),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{name} {value}",
                )
            x += seg_w
        painter.end()


class SparklineChart(QWidget):
    """Trend line for historical health scores."""

    def __init__(self, parent=None, theme: str = "industrial-light"):
        super().__init__(parent)
        self._values: list[float] = []
        self._title = ""
        self.theme = theme
        self.setMinimumHeight(110)

    def set_values(self, values: Sequence[float], title: str = "") -> None:
        self._values = [float(v) for v in values]
        self._title = title
        self.setToolTip(title)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = th.palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 12
        painter.setPen(QColor(p["muted"]))
        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)
        if self._title:
            painter.drawText(QRectF(pad, 2, w, 16), Qt.AlignmentFlag.AlignLeft, self._title)
        if len(self._values) < 2:
            painter.drawText(
                QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "not enough history"
            )
            painter.end()
            return
        top, bottom = pad + 16, h - pad
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        step = (w - 2 * pad) / (len(self._values) - 1)
        pts = [
            QPointF(pad + i * step, bottom - (v - lo) / span * (bottom - top))
            for i, v in enumerate(self._values)
        ]
        area = QPainterPath(QPointF(pts[0].x(), bottom))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(pts[-1].x(), bottom)
        area.closeSubpath()
        grad = QLinearGradient(0, top, 0, bottom)
        c = QColor(p["accent"])
        c.setAlpha(90)
        grad.setColorAt(0, c)
        c2 = QColor(p["accent"])
        c2.setAlpha(0)
        grad.setColorAt(1, c2)
        painter.fillPath(area, grad)
        painter.setPen(QPen(QColor(p["accent"]), 2))
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        painter.drawPath(line)
        painter.setBrush(QColor(p["accent"]))
        painter.drawEllipse(pts[-1], 3.5, 3.5)
        painter.end()


class DonutChart(QWidget):
    """Category donut used for issue-code distribution."""

    def __init__(self, parent=None, theme: str = "industrial-light"):
        super().__init__(parent)
        self._items: list[tuple[str, int, str]] = []
        self.theme = theme
        self.setMinimumHeight(160)

    def set_items(self, items: Sequence[tuple[str, int, str]]) -> None:
        self._items = list(items)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = th.palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        total = sum(v for _, v, _ in self._items)
        size = min(h - 16, w * 0.45)
        rect = QRectF(12, (h - size) / 2, size, size)
        if not total:
            painter.setPen(QColor(p["muted"]))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "no findings")
            painter.end()
            return
        start = 90 * 16
        for _name, value, color in self._items:
            span = int(-360 * 16 * value / total)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(rect, start, span)
            start += span
        inner = rect.adjusted(size * 0.28, size * 0.28, -size * 0.28, -size * 0.28)
        painter.setBrush(QColor(p["surface"]))
        painter.drawEllipse(inner)
        painter.setPen(QColor(p["ink"]))
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, str(total))

        f.setPointSize(8)
        f.setBold(False)
        painter.setFont(f)
        y = 14
        lx = rect.right() + 18
        for name, value, color in self._items[:8]:
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(lx, y, 10, 10), 2, 2)
            painter.setPen(QColor(p["ink"]))
            painter.drawText(
                QRectF(lx + 16, y - 2, w - lx - 24, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{name} — {value}",
            )
            y += 17
        painter.end()


class KpiStrip(QWidget):
    """The row of KPI cards + gauge shown above the results table."""

    card_clicked = pyqtSignal(str)

    def __init__(self, tr, theme: str = "industrial-light", parent=None):
        super().__init__(parent)
        self.tr_ = tr
        self.theme = theme
        p = th.palette(theme)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.cards: dict[str, KpiCard] = {}
        spec = [
            ("lines", "kpi_lines", p["ink"]),
            ("pass", "kpi_pass", p["pass"]),
            ("warn", "kpi_warn", p["warn"]),
            ("fail", "kpi_fail", p["fail"]),
            ("unplaced", "kpi_unplaced", p["crit"]),
            ("coverage", "kpi_coverage", p["accent"]),
            ("orphan", "kpi_orphan", p["muted"]),
        ]
        for key, label, color in spec:
            card = KpiCard(key, tr(label), "—", color)
            card.clicked.connect(self.card_clicked.emit)
            self.cards[key] = card
            lay.addWidget(card)

        self.gauge = GaugeWidget(theme=theme)
        self.gauge.setMaximumWidth(200)
        lay.addWidget(self.gauge)

    def set_summary(self, s: ValidationSummary | None) -> None:
        if s is None:
            for c in self.cards.values():
                c.set_value("—", "")
            self.gauge.set_value(0, self.tr_("kpi_health"))
            return
        self.cards["lines"].set_value(s.total_lines, f"{s.total_required} pcs required")
        self.cards["pass"].set_value(s.passed, f"{s.pass_rate:.1f}%")
        self.cards["warn"].set_value(s.warnings)
        self.cards["fail"].set_value(s.failed)
        self.cards["unplaced"].set_value(s.not_placed)
        self.cards["coverage"].set_value(
            f"{s.coverage:.1f}%", f"{s.top_placed} top / {s.bot_placed} bot"
        )
        self.cards["orphan"].set_value(
            s.orphan_placements, f"{s.duplicate_designators} dup refs"
        )
        self.gauge.set_value(s.health_score, self.tr_("kpi_health"))

    def retranslate(self, tr) -> None:
        self.tr_ = tr
        labels = {
            "lines": "kpi_lines",
            "pass": "kpi_pass",
            "warn": "kpi_warn",
            "fail": "kpi_fail",
            "unplaced": "kpi_unplaced",
            "coverage": "kpi_coverage",
            "orphan": "kpi_orphan",
        }
        for key, card in self.cards.items():
            card.set_title(tr(labels[key]))

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        p = th.palette(theme)
        colors = {
            "lines": p["ink"],
            "pass": p["pass"],
            "warn": p["warn"],
            "fail": p["fail"],
            "unplaced": p["crit"],
            "coverage": p["accent"],
            "orphan": p["muted"],
        }
        for key, card in self.cards.items():
            card.set_accent(colors[key])
        self.gauge.set_theme(theme)
