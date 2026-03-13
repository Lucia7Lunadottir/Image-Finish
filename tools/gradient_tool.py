import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import (QPainter, QColor, QLinearGradient,
                         QRadialGradient, QConicalGradient, QBrush, QGradient)
from tools.base_tool import BaseTool


class GradientTool(BaseTool):
    name     = "Gradient"
    icon     = "🌈"
    shortcut = ""

    def __init__(self):
        self._start:    QPoint | None = None
        self._end:      QPoint | None = None
        self._dragging: bool          = False

    # ── Tool interface ────────────────────────────────────────────────────────

    def on_press(self, pos, doc, fg, bg, opts):
        self._start    = pos
        self._end      = pos
        self._dragging = True

    def on_move(self, pos, doc, fg, bg, opts):
        self._end = pos

    def preview_gradient(self):
        """Return (start, end) for the live dashed-line overlay, or None."""
        if self._dragging and self._start is not None:
            return self._start, self._end
        return None

    def on_release(self, pos, doc, fg, bg, opts):
        self._dragging = False
        if self._start is None:
            return
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            self._start = None
            return

        sx, sy = self._start.x(), self._start.y()
        ex, ey = pos.x(), pos.y()
        if sx == ex and sy == ey:
            self._start = None
            return

        gtype   = opts.get("gradient_type",    "linear")
        mode    = opts.get("gradient_mode",    "fg_bg")
        opacity = float(opts.get("gradient_opacity", 100)) / 100
        reverse = bool(opts.get("gradient_reverse",  False))

        c1, c2 = self._make_colors(mode, fg, bg)
        if reverse:
            c1, c2 = c2, c1

        painter = QPainter(layer.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(opacity)
        if doc.selection and not doc.selection.isEmpty():
            painter.setClipPath(doc.selection)

        self._apply_gradient(painter, gtype,
                             layer.image.width(), layer.image.height(),
                             sx, sy, ex, ey, c1, c2)
        painter.end()
        self._start = None

    # ── Colour helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _make_colors(mode: str, fg: QColor, bg: QColor) -> tuple[QColor, QColor]:
        transparent = QColor(0, 0, 0, 0)
        if mode == "fg_bg":
            return QColor(fg), QColor(bg)
        elif mode == "fg_transparent":
            return QColor(fg), QColor(fg.red(), fg.green(), fg.blue(), 0)
        elif mode == "bg_fg":
            return QColor(bg), QColor(fg)
        else:  # bg_transparent
            return QColor(bg), QColor(bg.red(), bg.green(), bg.blue(), 0)

    # ── Gradient application ──────────────────────────────────────────────────

    @staticmethod
    def _apply_gradient(painter: QPainter, gtype: str,
                        w: int, h: int,
                        sx: int, sy: int, ex: int, ey: int,
                        c1: QColor, c2: QColor):
        rect = QRectF(0, 0, w, h)
        r    = math.hypot(ex - sx, ey - sy)

        if gtype == "radial":
            grad = QRadialGradient(QPointF(sx, sy), max(r, 1))
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            grad.setSpread(QGradient.Spread.PadSpread)

        elif gtype == "angle":
            angle = math.degrees(math.atan2(ey - sy, ex - sx))
            grad = QConicalGradient(QPointF(sx, sy), angle)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(0.5, c2)
            grad.setColorAt(1.0, c1)

        elif gtype == "reflected":
            # Symmetric around start: c2 — c1 — c2
            mx = 2 * sx - ex
            my = 2 * sy - ey
            grad = QLinearGradient(QPointF(mx, my), QPointF(ex, ey))
            grad.setColorAt(0.0, c2)
            grad.setColorAt(0.5, c1)
            grad.setColorAt(1.0, c2)
            grad.setSpread(QGradient.Spread.PadSpread)

        else:  # linear
            grad = QLinearGradient(QPointF(sx, sy), QPointF(ex, ey))
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            grad.setSpread(QGradient.Spread.PadSpread)

        painter.fillRect(rect, QBrush(grad))

    def cursor(self):
        return Qt.CursorShape.CrossCursor
