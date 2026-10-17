"""Filter > Camera Raw / Lens Correction / Liquify (see ui/filter_gallery.py)."""
import math

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen

from ui.filter_gallery import FilterGalleryDialog, FilterMode, Slider
from ui.preview_canvas_base import PreviewCanvasBase


class CameraRaw(FilterMode):
    key, title_key = "camera_raw", "menu.filter.camera_raw"
    params = tuple(Slider(k, f"spec.{k}", -100, 100, 0)
                   for k in ("temp", "tint", "exposure", "contrast", "highlights", "shadows"))

    def apply(self, src, p, ctx):
        res = src.copy()
        temp, tint, exposure, contrast, highlights, shadows = (
            p[k] / 100.0 for k in ("temp", "tint", "exposure", "contrast", "highlights", "shadows"))
        f = src[..., :3].astype(np.float32)
        # White balance
        f[..., 2] += temp * 40.0   # red
        f[..., 0] -= temp * 40.0   # blue
        f[..., 1] += tint * 40.0   # green
        f[..., 2] -= tint * 20.0   # magenta compensation
        f[..., 0] -= tint * 20.0
        f *= (2.0 ** exposure)
        f = (f - 128.0) * math.tan((contrast + 1) * math.pi / 4) + 128.0
        luma = 0.299 * f[..., 2] + 0.587 * f[..., 1] + 0.114 * f[..., 0]
        f += np.clip(1.0 - (luma / 128.0), 0.0, 1.0)[..., np.newaxis] * shadows * 100.0
        f += np.clip((luma - 128.0) / 128.0, 0.0, 1.0)[..., np.newaxis] * highlights * 100.0
        res[..., :3] = np.clip(f, 0, 255).astype(np.uint8)
        return res


class LensCorrection(FilterMode):
    key, title_key = "lens_correction", "menu.filter.lens_correction"
    params = (Slider("distortion", "spec.distortion", -100, 100, 0),
              Slider("vignette", "spec.vignette", -100, 100, 0))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        k, vig = p["distortion"] / 100.0, p["vignette"] / 100.0
        Y, X = np.ogrid[:h, :w]
        cy, cx = h / 2.0, w / 2.0
        max_r = math.hypot(cx, cy)
        r2 = ((X - cx) / max_r) ** 2 + ((Y - cy) / max_r) ** 2
        factor = 1.0 + k * r2
        sx = np.clip(cx + (X - cx) * factor, 0, w - 1).astype(int)
        sy = np.clip(cy + (Y - cy) * factor, 0, h - 1).astype(int)
        base = src[sy, sx, :3].astype(np.float32)
        if vig != 0:
            v = 1.0 - np.clip(r2 * abs(vig), 0.0, 1.0)
            base = base * v[..., np.newaxis] if vig < 0 else 255 - (255 - base) * v[..., np.newaxis]
        res[..., :3] = np.clip(base, 0, 255).astype(np.uint8)
        return res


class LiquifyCanvas(PreviewCanvasBase):
    """Forward-warp brush strokes on the preview."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self._drawing = False
        self._last_mouse = None

    def _liquify(self):
        return self.dialog.filter

    def _paint_overlay_in_screen_space(self, painter):
        if not self._space and self._last_mouse:
            r = (self.dialog._params()["size"] * self.zoom) / 2.0
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._last_mouse, r, r)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
            painter.drawEllipse(self._last_mouse, r - 1, r - 1)

    def mousePressEvent(self, ev):
        if self._maybe_start_pan(ev):
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self._liquify().push_undo()
            self._drawing = True
            self._last_mouse = ev.position()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._maybe_continue_pan(ev):
            return
        if self._drawing and self._last_mouse:
            to_img = lambda q: ((q.x() - self._pan.x()) / self.zoom, (q.y() - self._pan.y()) / self.zoom)
            if self._liquify().warp(*to_img(self._last_mouse), *to_img(pos), self.dialog._params()):
                self.dialog._on_change()
        self._last_mouse = pos
        self.update()

    def mouseReleaseEvent(self, ev):
        self._drawing = False
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Z and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.dialog._liquify_undo()
        else:
            super().keyPressEvent(ev)


class Liquify(FilterMode):
    """A per-pixel backward displacement map edited by brush strokes. It
    is tied 1:1 to the working resolution and edits are cheap bounded ROIs,
    so it never runs on a downscaled proxy."""
    key, title_key = "liquify", "menu.filter.liquify"
    params = (Slider("size", "spec.liquify.size", 10, 800, 100),
              Slider("pressure", "spec.liquify.press", 1, 100, 50))
    allow_proxy = False
    canvas_cls = LiquifyCanvas
    _UNDO_DEPTH = 30

    def on_open(self, dialog):
        h, w = dialog.orig_arr.shape[:2]
        Y, X = np.ogrid[:h, :w]
        self.disp_x = np.broadcast_to(X, (h, w)).astype(np.float32).copy()
        self.disp_y = np.broadcast_to(Y, (h, w)).astype(np.float32).copy()
        self._undo = []
        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+Z"), dialog).activated.connect(dialog._liquify_undo)

    def push_undo(self):
        self._undo.append((self.disp_x.copy(), self.disp_y.copy()))
        if len(self._undo) > self._UNDO_DEPTH:
            self._undo.pop(0)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.disp_x, self.disp_y = self._undo.pop()
        return True

    def warp(self, x1, y1, x2, y2, p) -> bool:
        """Forward warp from (x1, y1) to (x2, y2); True if anything moved."""
        h, w = self.disp_x.shape
        r = p["size"] / 2.0
        strength = p["pressure"] / 100.0
        dx, dy = x2 - x1, y2 - y1
        if math.hypot(dx, dy) < 1:
            return False
        min_x, max_x = max(0, int(min(x1, x2) - r)), min(w, int(max(x1, x2) + r + 1))
        min_y, max_y = max(0, int(min(y1, y2) - r)), min(h, int(max(y1, y2) + r + 1))
        if min_x >= max_x or min_y >= max_y:
            return False
        Y, X = np.ogrid[min_y:max_y, min_x:max_x]
        weight = np.clip(1.0 - (((X - x1) ** 2 + (Y - y1) ** 2) / (r ** 2)), 0.0, 1.0)
        weight = weight * weight * strength
        # Shift the map in reverse, pulling pixels toward the cursor
        self.disp_x[min_y:max_y, min_x:max_x] -= dx * weight
        self.disp_y[min_y:max_y, min_x:max_x] -= dy * weight
        return True

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        sx = np.clip(self.disp_x, 0, w - 1).astype(int)
        sy = np.clip(self.disp_y, 0, h - 1).astype(int)
        res[..., :3] = src[sy, sx, :3]
        return res


class SpecificFiltersDialog(FilterGalleryDialog):
    MODES = {m.key: m for m in (CameraRaw, LensCorrection, Liquify)}

    def _liquify_undo(self):
        if self.filter.undo():
            self._on_change()
