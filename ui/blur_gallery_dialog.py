import numpy as np
import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QDialogButtonBox, QWidget)
from PyQt6.QtCore import Qt, QPointF, QRect, QTimer
from PyQt6.QtGui import QImage, QPainter, QColor, QPen

from core.locale import tr
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase, DragCenterMixin
from tools.tool_utils import fast_box_blur_np

from ui import theme


class BlurGalleryCanvas(DragCenterMixin, PreviewCanvasBase):
    _center_hit_radius = 20

    def _paint_overlay_in_image_space(self, p, w, h):
        cx, cy = self.dialog.cx, self.dialog.cy
        p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 1.5/self.zoom)))
        p.setBrush(QColor(0, 0, 0, 100))
        cr = max(4.0, 6.0/self.zoom)
        p.drawEllipse(QPointF(cx, cy), cr, cr)
        p.drawEllipse(QPointF(cx, cy), cr*3, cr*3)

        mode = self.dialog.mode
        focus = self.dialog.focus_sl.value() / 100.0 * max(w, h) / 2.0
        trans = self.dialog.trans_sl.value() / 100.0 * max(w, h) / 2.0

        p.setPen(QPen(QColor(255, 255, 255, 100), max(1.0, 1.0/self.zoom), Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if mode == "iris":
            p.drawEllipse(QPointF(cx, cy), focus, focus)
            p.drawEllipse(QPointF(cx, cy), focus + trans, focus + trans)
        elif mode in ("tilt_shift", "path"):
            p.translate(cx, cy)
            p.rotate(-self.dialog.angle_sl.value())

            if mode == "tilt_shift":
                p.drawLine(QPointF(-w*2, -focus), QPointF(w*2, -focus))
                p.drawLine(QPointF(-w*2, focus), QPointF(w*2, focus))
                p.setPen(QPen(QColor(255, 255, 255, 50), max(1.0, 1.0/self.zoom), Qt.PenStyle.DotLine))
                p.drawLine(QPointF(-w*2, -(focus + trans)), QPointF(w*2, -(focus + trans)))
                p.drawLine(QPointF(-w*2, focus + trans), QPointF(w*2, focus + trans))
            else: # path
                p.drawLine(QPointF(-w*2, 0), QPointF(w*2, 0))

    def keyReleaseEvent(self, ev):
        super().keyReleaseEvent(ev)
        self.update()


class BlurGalleryDialog(QDialog):
    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("menu.blur_gallery") + f" - {mode.replace('_', ' ').title()}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1000, 700)
        
        self.layer = layer
        self.mode = mode
        self.canvas_refresh = canvas_refresh
        
        from ui.preview_canvas_base import init_live_preview_arrays
        init_live_preview_arrays(self, layer)
        self.cx = self.orig_img.width() / 2.0
        self.cy = self.orig_img.height() / 2.0

        self.blurred_cache = None
        self.last_blur_radius = -1
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._apply_effect)

        self._build_ui()
        self._apply_effect()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        
        # Canvas
        self.canvas = BlurGalleryCanvas(self)
        
        # Initial Zoom fit
        w, h = self.orig_img.width(), self.orig_img.height()
        scale = min(700 / max(1, w), 600 / max(1, h))
        self.canvas.zoom = scale
        self.canvas._pan = QPointF(50, 50)
        
        root.addWidget(self.canvas, 1)
        
        # Controls Right Panel
        props = QWidget()
        props.setFixedWidth(280)
        theme.apply_style(props, lambda: f"background: {theme.BASE}; border-left: 1px solid {theme.SURFACE0};")
        pl = QVBoxLayout(props)
        pl.setContentsMargins(15, 15, 15, 15)
        pl.setSpacing(15)
        
        def add_slider(name, lo, hi, val):
            pl.addWidget(QLabel(name))
            sl = _JumpSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(val)
            sl.valueChanged.connect(self._trigger_update)
            pl.addWidget(sl)
            return sl
            
        self.blur_sl = add_slider("Blur (Amount):", 0, 150, 15)
        
        self.focus_sl = add_slider("Focus zone:", 0, 100, 20)
        self.trans_sl = add_slider("Transition smoothness:", 0, 100, 30)
        self.angle_sl = add_slider("Tilt angle:", -180, 180, 0)
        
        # Hide irrelevant sliders depending on mode
        if self.mode == "field":
            for sl in (self.focus_sl, self.trans_sl, self.angle_sl):
                pl.itemAt(pl.indexOf(sl)).widget().hide()
                pl.itemAt(pl.indexOf(sl)-1).widget().hide()
        elif self.mode == "iris":
            self.angle_sl.hide()
            pl.itemAt(pl.indexOf(self.angle_sl)-1).widget().hide()
        elif self.mode in ("spin", "path"):
            self.focus_sl.hide(); self.trans_sl.hide()
            pl.itemAt(pl.indexOf(self.focus_sl)-1).widget().hide()
            pl.itemAt(pl.indexOf(self.trans_sl)-1).widget().hide()
            if self.mode == "spin":
                self.angle_sl.hide()
                pl.itemAt(pl.indexOf(self.angle_sl)-1).widget().hide()

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _trigger_update(self):
        self._timer.start()
        self.canvas.update()

    def _apply_effect(self):
        r = self.blur_sl.value()
        if r == 0:
            self.preview_img = self.orig_img.copy()
            self.canvas.update()
            return
            
        h, w = self.orig_arr.shape[:2]
        
        if self.mode in ("field", "iris", "tilt_shift"):
            # Cache blur for speed
            if self.last_blur_radius != r or self.blurred_cache is None:
                # Double pass for softness (pseudo-Gaussian)
                self.blurred_cache = fast_box_blur_np(fast_box_blur_np(self.orig_arr, r//2), r//2)
                self.last_blur_radius = r
                
            Y, X = np.ogrid[:h, :w]
            
            if self.mode == "field":
                mask = np.ones((h, w, 1), dtype=np.float32)
            else:
                max_dim = max(h, w)
                focus = (self.focus_sl.value() / 100.0) * (max_dim / 2.0)
                trans = max(1.0, (self.trans_sl.value() / 100.0) * (max_dim / 2.0))
                
                if self.mode == "iris":
                    dist = np.sqrt((X - self.cx)**2 + (Y - self.cy)**2)
                else: # tilt_shift
                    theta = np.radians(self.angle_sl.value())
                    dist = np.abs((X - self.cx) * np.sin(theta) + (Y - self.cy) * np.cos(theta))
                    
                m = (dist - focus) / trans
                mask = np.clip(m, 0.0, 1.0)[..., np.newaxis]
                mask = mask * mask * (3.0 - 2.0 * mask) # Smoothstep
                
            res_arr = (self.orig_arr.astype(np.float32) * (1.0 - mask) + self.blurred_cache.astype(np.float32) * mask).astype(np.uint8)
            
            # Update the image
            self.preview_img = QImage(res_arr.data, w, h, w*4, QImage.Format.Format_ARGB32_Premultiplied).copy()
            
        elif self.mode in ("path", "spin"):
            # For motion/spin blur it is simpler and faster to use QPainter
            res_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            res_img.fill(0)
            p = QPainter(res_img)
            steps = min(40, max(5, r)) # Adaptive step count
            p.setOpacity(1.0 / steps)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.translate(self.cx, self.cy)
            
            theta = np.radians(self.angle_sl.value())
            
            for i in range(steps):
                p.save()
                if self.mode == "path":
                    offset = (i - steps/2) * (r / steps)
                    p.translate(np.cos(theta) * offset, np.sin(theta) * offset)
                elif self.mode == "spin":
                    a = (i - steps/2) * (r / steps) * 2.0 # Degrees
                    p.rotate(a)
                p.drawImage(QPointF(-self.cx, -self.cy), self.orig_img)
                p.restore()
            p.end()
            
            # Compensate brightness and alpha loss from 8-bit QPainter compositing errors
            step_alpha = int(round(255.0 / steps))
            if step_alpha > 0:
                max_possible = step_alpha * steps
                if max_possible < 255:
                    from core.pixel_buffer import qimage_argb_view
                    arr = qimage_argb_view(res_img, writable=True)[:, :w, :]
                    ratio = 255.0 / max_possible
                    arr[...] = np.clip(arr.astype(np.float32) * ratio, 0, 255).astype(np.uint8)
                    
            self.preview_img = res_img
            
        self.canvas.update()

    def accept(self):
        from ui.preview_canvas_base import run_full_res_commit
        # blurred_cache is keyed only by radius, not array shape — it's
        # still sized to the downscaled preview at this point and would
        # otherwise broadcast-mismatch against the restored full-res
        # orig_arr, so it's invalidated via pre_apply (cheap, stays
        # synchronous) before the threaded _apply_effect() re-runs.
        if run_full_res_commit(self, self._apply_effect, scale_attrs=("cx", "cy"),
                                pre_apply=lambda: setattr(self, "blurred_cache", None)):
            self.layer.image = self.preview_img
            super().accept()