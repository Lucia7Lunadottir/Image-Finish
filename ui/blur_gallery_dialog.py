"""Filter > Blur Gallery (see ui/filter_gallery.py). Every mode has a
draggable centre; Iris / Tilt-Shift / Path draw their focus geometry."""
import numpy as np
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from tools.tool_utils import fast_box_blur_np
from ui.filter_gallery import FilterGalleryDialog, FilterMode, Slider, paint_center_rings

_BLUR = Slider("blur", "blur_gallery.amount", 0, 150, 15, spatial=True)
_FOCUS = Slider("focus", "blur_gallery.focus", 0, 100, 20)
_TRANSITION = Slider("transition", "blur_gallery.transition", 0, 100, 30)
_ANGLE = Slider("angle", "blur_gallery.angle", -180, 180, 0)


class _GalleryBlur(FilterMode):
    center = True

    def paint_overlay(self, p, dialog, w, h):
        paint_center_rings(p, dialog, dialog.canvas.zoom)
        params = dialog._params()
        zoom = dialog.canvas.zoom
        focus = params.get("focus", 0) / 100.0 * max(w, h) / 2.0
        trans = params.get("transition", 0) / 100.0 * max(w, h) / 2.0
        p.setPen(QPen(QColor(255, 255, 255, 100), max(1.0, 1.0 / zoom), Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._paint_geometry(p, dialog, w, focus, trans, params, zoom)

    def _paint_geometry(self, p, dialog, w, focus, trans, params, zoom):
        pass


class _MaskedBlur(_GalleryBlur):
    """Field / Iris / Tilt-Shift: the source blended with a blurred copy by a mask."""

    def __init__(self):
        self._cache_key = None
        self._cache = None

    def _blurred(self, src, r):
        key = (r, src.shape)
        if self._cache_key != key:
            # Double pass for softness (pseudo-Gaussian)
            self._cache = fast_box_blur_np(fast_box_blur_np(src, r // 2), r // 2)
            self._cache_key = key
        return self._cache

    def _mask(self, src, p, ctx):
        raise NotImplementedError

    def apply(self, src, p, ctx):
        r = p["blur"]
        if r == 0:
            return ctx.orig_img.copy()
        blurred = self._blurred(src, r)
        mask = self._mask(src, p, ctx)
        return (src.astype(np.float32) * (1.0 - mask) + blurred.astype(np.float32) * mask).astype(np.uint8)


class FieldBlur(_MaskedBlur):
    key, title_key = "field", "menu.blur.field"
    params = (_BLUR,)

    def _mask(self, src, p, ctx):
        h, w = src.shape[:2]
        return np.ones((h, w, 1), dtype=np.float32)


class IrisBlur(_MaskedBlur):
    key, title_key = "iris", "menu.blur.iris"
    params = (_BLUR, _FOCUS, _TRANSITION)

    def _distance(self, X, Y, p, ctx):
        return np.sqrt((X - ctx.cx) ** 2 + (Y - ctx.cy) ** 2)

    def _mask(self, src, p, ctx):
        h, w = src.shape[:2]
        Y, X = np.ogrid[:h, :w]
        max_dim = max(h, w)
        focus = (p["focus"] / 100.0) * (max_dim / 2.0)
        trans = max(1.0, (p["transition"] / 100.0) * (max_dim / 2.0))
        m = np.clip((self._distance(X, Y, p, ctx) - focus) / trans, 0.0, 1.0)[..., np.newaxis]
        return m * m * (3.0 - 2.0 * m)     # smoothstep

    def _paint_geometry(self, p, dialog, w, focus, trans, params, zoom):
        c = QPointF(dialog.cx, dialog.cy)
        p.drawEllipse(c, focus, focus)
        p.drawEllipse(c, focus + trans, focus + trans)


class TiltShiftBlur(IrisBlur):
    key, title_key = "tilt_shift", "menu.blur.tilt_shift"
    params = (_BLUR, _FOCUS, _TRANSITION, _ANGLE)

    def _distance(self, X, Y, p, ctx):
        theta = np.radians(p["angle"])
        return np.abs((X - ctx.cx) * np.sin(theta) + (Y - ctx.cy) * np.cos(theta))

    def _paint_geometry(self, p, dialog, w, focus, trans, params, zoom):
        p.translate(dialog.cx, dialog.cy)
        p.rotate(-params["angle"])
        p.drawLine(QPointF(-w * 2, -focus), QPointF(w * 2, -focus))
        p.drawLine(QPointF(-w * 2, focus), QPointF(w * 2, focus))
        p.setPen(QPen(QColor(255, 255, 255, 50), max(1.0, 1.0 / zoom), Qt.PenStyle.DotLine))
        p.drawLine(QPointF(-w * 2, -(focus + trans)), QPointF(w * 2, -(focus + trans)))
        p.drawLine(QPointF(-w * 2, focus + trans), QPointF(w * 2, focus + trans))


class _StepBlur(_GalleryBlur):
    """Path / Spin: the source drawn many times, shifted or rotated."""

    def _step(self, painter, i, steps, r, p):
        raise NotImplementedError

    def apply(self, src, p, ctx):
        r = p["blur"]
        if r == 0:
            return ctx.orig_img.copy()
        h, w = src.shape[:2]
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)
        painter = QPainter(out)
        steps = min(40, max(5, r))      # adaptive step count
        painter.setOpacity(1.0 / steps)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.translate(ctx.cx, ctx.cy)
        for i in range(steps):
            painter.save()
            self._step(painter, i, steps, r, p)
            painter.drawImage(QPointF(-ctx.cx, -ctx.cy), ctx.orig_img)
            painter.restore()
        painter.end()
        # Compensate brightness and alpha lost to 8-bit QPainter compositing
        step_alpha = int(round(255.0 / steps))
        if step_alpha > 0 and step_alpha * steps < 255:
            from core.pixel_buffer import qimage_argb_view
            arr = qimage_argb_view(out, writable=True)[:, :w, :]
            arr[...] = np.clip(arr.astype(np.float32) * (255.0 / (step_alpha * steps)), 0, 255).astype(np.uint8)
        return out


class PathBlur(_StepBlur):
    key, title_key = "path", "menu.blur.path"
    params = (_BLUR, _ANGLE)

    def _step(self, painter, i, steps, r, p):
        theta = np.radians(p["angle"])
        offset = (i - steps / 2) * (r / steps)
        painter.translate(np.cos(theta) * offset, np.sin(theta) * offset)

    def _paint_geometry(self, p, dialog, w, focus, trans, params, zoom):
        p.translate(dialog.cx, dialog.cy)
        p.rotate(-params["angle"])
        p.drawLine(QPointF(-w * 2, 0), QPointF(w * 2, 0))


class SpinBlur(_StepBlur):
    key, title_key = "spin", "menu.blur.spin"
    params = (_BLUR,)

    def _step(self, painter, i, steps, r, p):
        painter.rotate((i - steps / 2) * (r / steps) * 2.0)      # degrees


class BlurGalleryDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.blur_gallery"
    MODES = {m.key: m for m in (FieldBlur, IrisBlur, PathBlur, SpinBlur, TiltShiftBlur)}
