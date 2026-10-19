"""Sharp display of vector content when zoomed in: the document rendered
at screen resolution (Document.render_view) instead of the magnified
document-resolution composite. Moved out of CanvasWidget, where it was
four methods and five fields."""
import math
import time

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QTransform

from core.app_logging import get_logger

logger = get_logger("canvas")


class HiresView:
    def __init__(self, canvas):
        self._canvas = canvas
        self.image: QImage | None = None
        self.origin = QPointF()
        self.key = None
        self.render_ms = 0.0
        self.failed = False
        self.timer = QTimer(canvas)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)

    def reset(self):
        self.image = None
        self.key = None

    def _view_key(self):
        c = self._canvas
        return (round(c.zoom, 6), round(c._pan.x(), 3), round(c._pan.y(), 3),
                c.width(), c.height(), c.devicePixelRatioF())

    def wanted(self, channel: str) -> bool:
        c = self._canvas
        if self.failed or c.document is None or c._composite_cache is None:
            return False
        if channel != "RGB" or c._in_effect_stroke:
            return False
        if c.zoom * c.devicePixelRatioF() <= 1.0001:
            return False   # the document-resolution composite is already as sharp as the screen
        return c.document.has_vector_content()

    def draw(self, painter: QPainter, channel: str) -> bool:
        """Draws the screen-resolution render if it matches what's on
        screen now; otherwise schedules one and returns False (the caller
        draws the normal composite meanwhile)."""
        c = self._canvas
        if not self.wanted(channel):
            self.reset()
            return False
        key = (c._composite_cache.cacheKey(), self._view_key())
        if self.image is not None and self.key == key:
            painter.drawImage(self.origin, self.image)
            return True
        same_view = self.key is not None and self.key[1] == key[1]
        # Mid-gesture (brush stroke, drag) the composite changes every
        # frame — never render synchronously then (the debounced timer
        # below fires once the gesture pauses), unless it's a drag of
        # vector content that renders fast (Move of a shape or text).
        interacting = self._interacting()
        if same_view and self._may_render_now(interacting):
            # Only the content changed (a shape edit committed) and a render
            # is cheap: do it now, so the shape doesn't flash blurry first.
            self.render()
            if self.image is not None and self.key == key:
                painter.drawImage(self.origin, self.image)
                return True
            return False
        self.timer.start(90 if (interacting or not same_view) else 0)
        return False

    # A render at most this slow happens right away when the view hasn't
    # moved; mid-drag the budget is tighter so dragging stays smooth.
    _IDLE_BUDGET_MS = 60
    _DRAG_BUDGET_MS = 40

    @staticmethod
    def _interacting() -> bool:
        from PyQt6.QtWidgets import QApplication
        return QApplication.mouseButtons() != Qt.MouseButton.NoButton

    def _sharp_drag(self) -> bool:
        tool = self._canvas.active_tool
        return tool is not None and getattr(tool, "sharp_while_dragging", lambda: False)()

    def _may_render_now(self, interacting: bool) -> bool:
        if not interacting:
            return self.render_ms < self._IDLE_BUDGET_MS
        return self._sharp_drag() and self.render_ms < self._DRAG_BUDGET_MS

    def render(self):
        c = self._canvas
        if c.document is None or c._cache_dirty or c._composite_cache is None:
            return
        if self._interacting() and not self._may_render_now(True):
            self.timer.start(90)   # still mid-gesture: try again shortly
            return
        if not self.wanted(getattr(c, "view_channel", "RGB")):
            return
        region = c.rect().intersected(c._doc_rect_in_widget().adjusted(-1, -1, 1, 1))
        if region.isEmpty():
            return
        dpr = c.devicePixelRatioF()
        s = c.zoom * dpr
        transform = QTransform(s, 0, 0, s, (c._pan.x() - region.x()) * dpr,
                               (c._pan.y() - region.y()) * dpr)
        size = QSize(max(1, math.ceil(region.width() * dpr)), max(1, math.ceil(region.height() * dpr)))
        t0 = time.perf_counter()
        try:
            img = c.document.render_view(transform, size)
        except Exception:
            logger.exception("Screen-resolution render failed — falling back to the composite")
            self.failed = True
            self.image = None
            return
        self.render_ms = (time.perf_counter() - t0) * 1000
        img.setDevicePixelRatio(dpr)
        self.image = img
        self.origin = QPointF(region.topLeft())
        self.key = (c._composite_cache.cacheKey(), self._view_key())
        c.update()
