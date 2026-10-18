import math
import numpy as np

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QPainter, QColor
from tools.base_tool import BaseTool
from core.blend_modes import composition_mode
from core.gradient_model import Gradient, GRADIENT_STYLES


def gradient_from_opts(opts: dict, fg, bg) -> Gradient:
    """The Gradient tool's gradient: the edited one (opts["gradient"]),
    or foreground -> background until the editor has been used. Style and
    reverse come from the options bar, not from the gradient itself."""
    if opts.get("gradient"):
        g = Gradient.from_dict(opts["gradient"])
    elif opts.get("gradient_stops"):
        g = Gradient.from_merged_stops(opts["gradient_stops"])
    else:
        g = Gradient.two_color(QColor(fg), QColor(bg))
    style = opts.get("gradient_type", "linear")
    g.style = style if style in GRADIENT_STYLES else "linear"
    g.reverse = bool(opts.get("gradient_reverse", False))
    return g


class GradientTool(BaseTool):
    REPAINT_ON_HOVER = True
    PIXEL_OP = "paint"
    name     = "Gradient"
    icon     = "🌈"
    shortcut = "G"

    def __init__(self):
        self._start:    QPoint | None = None
        self._end:      QPoint | None = None
        self._dragging: bool          = False

    def on_press(self, pos, doc, fg, bg, opts):
        self._start    = pos
        self._end      = pos
        self._dragging = True

    def on_move(self, pos, doc, fg, bg, opts):
        self._end = pos

    def preview_gradient(self):
        if self._dragging and self._start is not None:
            return self._start, self._end
        return None

    def on_release(self, pos, doc, fg, bg, opts):
        self._dragging = False
        if self._start is None:
            return
        layer = doc.get_active_layer()
        if not layer or layer.locked or getattr(layer, "lock_pixels", False):
            self._start = None
            return

        sx, sy = self._start.x() - layer.offset.x(), self._start.y() - layer.offset.y()
        ex, ey = pos.x() - layer.offset.x(), pos.y() - layer.offset.y()
        if sx == ex and sy == ey:
            self._start = None
            return

        gradient = gradient_from_opts(opts, fg, bg)
        opacity = float(opts.get("gradient_opacity", 100)) / 100
        if bool(opts.get("_shift", False)):
            ex, ey = self._snap_45(sx, sy, ex, ey)

        if getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None:
            target_img = layer.mask
            lock_a = False
        else:
            target_img = layer.image
            lock_a = getattr(layer, "lock_alpha", False)
            
        if lock_a:
            from core.pixel_buffer import qimage_argb_view
            w = target_img.width()
            arr = qimage_argb_view(target_img, writable=True)[:, :w, :]
            orig_alpha = arr[..., 3].copy()

        painter = QPainter(target_img)
        painter.setOpacity(opacity)
        painter.setCompositionMode(composition_mode(opts.get("gradient_mode", "SourceOver")))
        if doc.selection and not doc.selection.isEmpty():
            painter.setClipPath(doc.selection.translated(-layer.offset.x(), -layer.offset.y()))
        area = target_img.rect()
        painter.fillRect(area, gradient.brush_for_drag(QPointF(sx, sy), QPointF(ex, ey),
                                                      device_area=area))
        painter.end()

        if lock_a:
            new_alpha = arr[..., 3].astype(np.float32)
            new_alpha[new_alpha == 0] = 1.0
            ratio = orig_alpha.astype(np.float32) / new_alpha
            arr[..., 0] = np.clip(arr[..., 0] * ratio, 0, 255).astype(np.uint8)
            arr[..., 1] = np.clip(arr[..., 1] * ratio, 0, 255).astype(np.uint8)
            arr[..., 2] = np.clip(arr[..., 2] * ratio, 0, 255).astype(np.uint8)
            arr[..., 3] = orig_alpha
            
        self._start = None

    @staticmethod
    def _snap_45(sx, sy, ex, ey):
        """Shift: constrain the drag to multiples of 45° (Photoshop)."""
        dx, dy = ex - sx, ey - sy
        length = math.hypot(dx, dy)
        a = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        return sx + length * math.cos(a), sy + length * math.sin(a)

    def cursor(self):
        return Qt.CursorShape.CrossCursor
