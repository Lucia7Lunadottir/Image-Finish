import numpy as np
import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QDialogButtonBox, QWidget)
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QImage, QColor, QPen

from core.locale import tr, current as locale_current
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase

from ui import theme


class LiquifyCanvas(PreviewCanvasBase):
    def __init__(self, dialog):
        super().__init__(dialog)
        self._drawing = False
        self._last_mouse = None

    def _paint_overlay_in_screen_space(self, painter):
        if self.dialog.mode == "liquify" and not self._space and self._last_mouse:
            r = (self.dialog.sl1.value() * self.zoom) / 2.0
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._last_mouse, r, r)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
            painter.drawEllipse(self._last_mouse, r-1, r-1)

    def mousePressEvent(self, ev):
        if self._maybe_start_pan(ev):
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.dialog.mode == "liquify":
            self.dialog.push_undo()
            self._drawing = True
            self._last_mouse = ev.position()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._maybe_continue_pan(ev):
            return
        if self._drawing and self.dialog.mode == "liquify":
            if self._last_mouse:
                p1_x = (self._last_mouse.x() - self._pan.x()) / self.zoom
                p1_y = (self._last_mouse.y() - self._pan.y()) / self.zoom
                p2_x = (pos.x() - self._pan.x()) / self.zoom
                p2_y = (pos.y() - self._pan.y()) / self.zoom
                self.dialog.apply_warp(p1_x, p1_y, p2_x, p2_y)
            self._last_mouse = pos
            self.update()
        else:
            self._last_mouse = pos
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drawing = False
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Z and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.dialog.undo()
        else:
            super().keyPressEvent(ev)


class SpecificFiltersDialog(QDialog):
    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.mode = mode
        self.canvas_refresh = canvas_refresh
        
        title = tr(f"menu.filter.{mode}").replace('…', '')
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1000, 700)
        
        # Liquify keeps a per-pixel displacement map (self.disp_x/disp_y) tied
        # 1:1 to the working resolution and edited via bounded-ROI strokes —
        # it's already cheap regardless of image size, and downscaling would
        # need to resample that map back up on accept() (not just a scalar
        # rescale like cx/cy elsewhere). camera_raw/lens_correction are plain
        # per-pixel/LUT math over the whole image with no such state, so they
        # get the same live-preview downscaling as the other filter dialogs.
        if self.mode == "liquify":
            self.orig_img = layer.image.copy()
            self.preview_img = layer.image.copy()
            self.orig_img_full = None
            from core.pixel_buffer import qimage_argb_view
            self.orig_arr = qimage_argb_view(self.orig_img, writable=False)[:, :self.orig_img.width(), :].copy()
        else:
            from ui.preview_canvas_base import init_live_preview_arrays
            init_live_preview_arrays(self, layer)

        h, w = self.orig_arr.shape[:2]
        if self.mode == "liquify":
            Y, X = np.ogrid[:h, :w]
            self.disp_x = np.broadcast_to(X, (h, w)).astype(np.float32).copy()
            self.disp_y = np.broadcast_to(Y, (h, w)).astype(np.float32).copy()
            self._undo_stack = []
            
            from PyQt6.QtGui import QShortcut, QKeySequence
            QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo)
            
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._apply_effect)

        self._build_ui()
        self._apply_effect()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        
        self.canvas = LiquifyCanvas(self)
        w, h = self.orig_img.width(), self.orig_img.height()
        scale = min(700 / max(1, w), 600 / max(1, h))
        self.canvas.zoom = scale
        self.canvas._pan = QPointF(50, 50)
        root.addWidget(self.canvas, 1)
        
        props = QWidget()
        props.setFixedWidth(280)
        theme.apply_style(props, lambda: f"background: {theme.BASE}; border-left: 1px solid {theme.SURFACE0};")
        pl = QVBoxLayout(props)
        pl.setContentsMargins(15, 15, 15, 15); pl.setSpacing(15)
        
        def add_slider(name):
            lbl = QLabel(name)
            pl.addWidget(lbl)
            sl = _JumpSlider(Qt.Orientation.Horizontal)
            sl.valueChanged.connect(self._trigger_update)
            pl.addWidget(sl)
            return sl, lbl
            
        self.sl1, self.lbl1 = add_slider("Param1")
        self.sl2, self.lbl2 = add_slider("Param2")
        self.sl3, self.lbl3 = add_slider("Param3")
        self.sl4, self.lbl4 = add_slider("Param4")
        self.sl5, self.lbl5 = add_slider("Param5")
        self.sl6, self.lbl6 = add_slider("Param6")

        for wg in [self.sl1, self.lbl1, self.sl2, self.lbl2, self.sl3, self.lbl3, 
                   self.sl4, self.lbl4, self.sl5, self.lbl5, self.sl6, self.lbl6]:
            wg.hide()

        if self.mode == "camera_raw":
            self.lbl1.setText(tr("spec.temp"));      self.sl1.setRange(-100, 100); self.sl1.setValue(0)
            self.lbl2.setText(tr("spec.tint"));      self.sl2.setRange(-100, 100); self.sl2.setValue(0)
            self.lbl3.setText(tr("spec.exposure"));  self.sl3.setRange(-100, 100); self.sl3.setValue(0)
            self.lbl4.setText(tr("spec.contrast"));  self.sl4.setRange(-100, 100); self.sl4.setValue(0)
            self.lbl5.setText(tr("spec.highlights"));self.sl5.setRange(-100, 100); self.sl5.setValue(0)
            self.lbl6.setText(tr("spec.shadows"));   self.sl6.setRange(-100, 100); self.sl6.setValue(0)
            for w in [self.sl1, self.lbl1, self.sl2, self.lbl2, self.sl3, self.lbl3,
                      self.sl4, self.lbl4, self.sl5, self.lbl5, self.sl6, self.lbl6]: w.show()
                      
        elif self.mode == "lens_correction":
            self.lbl1.setText(tr("spec.distortion"));self.sl1.setRange(-100, 100); self.sl1.setValue(0)
            self.lbl2.setText(tr("spec.vignette"));  self.sl2.setRange(-100, 100); self.sl2.setValue(0)
            for w in [self.sl1, self.lbl1, self.sl2, self.lbl2]: w.show()
            
        elif self.mode == "liquify":
            self.lbl1.setText(tr("spec.liquify.size")); self.sl1.setRange(10, 800); self.sl1.setValue(100)
            self.lbl2.setText(tr("spec.liquify.press"));self.sl2.setRange(1, 100);  self.sl2.setValue(50)
            for w in [self.sl1, self.lbl1, self.sl2, self.lbl2]: w.show()

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _trigger_update(self):
        self._timer.start()
        
    def push_undo(self):
        if self.mode == "liquify":
            self._undo_stack.append((self.disp_x.copy(), self.disp_y.copy()))
            if len(self._undo_stack) > 30:
                self._undo_stack.pop(0)

    def undo(self):
        if self.mode == "liquify" and self._undo_stack:
            self.disp_x, self.disp_y = self._undo_stack.pop()
            self._trigger_update()

    def apply_warp(self, x1, y1, x2, y2):
        """Interactive Forward Warp for Liquify."""
        h, w = self.orig_arr.shape[:2]
        r = self.sl1.value() / 2.0
        strength = self.sl2.value() / 100.0
        
        dx, dy = x2 - x1, y2 - y1
        dist_move = math.hypot(dx, dy)
        if dist_move < 1: return
        
        # Limit ROI for performance
        min_x = max(0, int(min(x1, x2) - r))
        max_x = min(w, int(max(x1, x2) + r + 1))
        min_y = max(0, int(min(y1, y2) - r))
        max_y = min(h, int(max(y1, y2) + r + 1))
        
        if min_x >= max_x or min_y >= max_y: return
        
        Y, X = np.ogrid[min_y:max_y, min_x:max_x]
        dist_sq = (X - x1)**2 + (Y - y1)**2
        
        # Warp brush (smooth falloff)
        weight = np.clip(1.0 - (dist_sq / (r**2)), 0.0, 1.0)
        weight = weight * weight * strength
        
        # Shift the coordinate map in reverse (to pull pixels towards the mouse)
        self.disp_x[min_y:max_y, min_x:max_x] -= dx * weight
        self.disp_y[min_y:max_y, min_x:max_x] -= dy * weight
        
        self._trigger_update()

    def _apply_effect(self):
        res_arr = self.orig_arr.copy()
        h, w = res_arr.shape[:2]
        
        if self.mode == "camera_raw":
            temp = self.sl1.value() / 100.0
            tint = self.sl2.value() / 100.0
            exposure = self.sl3.value() / 100.0
            contrast = self.sl4.value() / 100.0
            highlights = self.sl5.value() / 100.0
            shadows = self.sl6.value() / 100.0
            
            arr_f = self.orig_arr[..., :3].astype(np.float32)
            
            # Temperature and Tint (White Balance)
            arr_f[..., 2] += temp * 40.0   # Red
            arr_f[..., 0] -= temp * 40.0   # Blue
            arr_f[..., 1] += tint * 40.0   # Green
            arr_f[..., 2] -= tint * 20.0   # Magenta compensation
            arr_f[..., 0] -= tint * 20.0
            
            # Exposure (Multiplication)
            arr_f *= (2.0 ** exposure)
            
            # Contrast
            arr_f = (arr_f - 128.0) * math.tan((contrast + 1) * math.pi/4) + 128.0
            
            # Shadows / Highlights
            luma = 0.299 * arr_f[..., 2] + 0.587 * arr_f[..., 1] + 0.114 * arr_f[..., 0]
            
            shadow_mask = np.clip(1.0 - (luma / 128.0), 0.0, 1.0)
            arr_f += shadow_mask[..., np.newaxis] * shadows * 100.0
            
            high_mask = np.clip((luma - 128.0) / 128.0, 0.0, 1.0)
            arr_f += high_mask[..., np.newaxis] * highlights * 100.0
            
            res_arr[..., :3] = np.clip(arr_f, 0, 255).astype(np.uint8)
            
        elif self.mode == "lens_correction":
            k = self.sl1.value() / 100.0 # Lens distortion
            vig = self.sl2.value() / 100.0
            
            Y, X = np.ogrid[:h, :w]
            cy, cx = h / 2.0, w / 2.0
            max_r = math.hypot(cx, cy)
            
            yn = (Y - cy) / max_r
            xn = (X - cx) / max_r
            r2 = xn**2 + yn**2
            
            factor = 1.0 + k * r2
            src_X = np.clip(cx + (X - cx) * factor, 0, w - 1).astype(int)
            src_Y = np.clip(cy + (Y - cy) * factor, 0, h - 1).astype(int)
            
            base = self.orig_arr[src_Y, src_X, :3].astype(np.float32)
            
            # Vignette
            if vig != 0:
                v_mask = 1.0 - np.clip(r2 * abs(vig), 0.0, 1.0)
                if vig < 0: base *= v_mask[..., np.newaxis] # Darken
                else: base = 255 - (255 - base) * v_mask[..., np.newaxis] # Lighten
                
            res_arr[..., :3] = np.clip(base, 0, 255).astype(np.uint8)
            
        elif self.mode == "liquify":
            # Render from displacement map
            src_X = np.clip(self.disp_x, 0, w - 1).astype(int)
            src_Y = np.clip(self.disp_y, 0, h - 1).astype(int)
            res_arr[..., :3] = self.orig_arr[src_Y, src_X, :3]
            
        self.preview_img = QImage(res_arr.data, w, h, w*4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self.canvas.update()

    def accept(self):
        from ui.preview_canvas_base import run_full_res_commit
        if run_full_res_commit(self, self._apply_effect):
            self.layer.image = self.preview_img
            super().accept()