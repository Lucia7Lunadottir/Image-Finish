import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QDialogButtonBox, QWidget)
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QImage

from core.locale import tr, current as locale_current
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase
from tools.tool_utils import fast_box_blur_np

from ui import theme

def apply_conv3x3(arr, kernel):
    h, w = arr.shape[:2]
    padded = np.pad(arr[..., :3].astype(np.float32), ((1,1),(1,1),(0,0)), mode='edge')
    res = np.zeros((h, w, 3), dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            if kernel[dy, dx] != 0:
                res += padded[dy:h+dy, dx:w+dx] * kernel[dy, dx]
    return np.clip(res, 0, 255).astype(np.uint8)


class SharpenCanvas(PreviewCanvasBase):
    pass


class SharpenDialog(QDialog):
    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.mode = mode
        self.canvas_refresh = canvas_refresh
        
        title = tr(f"menu.sharpen.{mode}").replace('…', '')
        self.setWindowTitle(f"{tr('menu.sharpen_gallery')} - {title}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1000, 700)
        
        from ui.preview_canvas_base import init_live_preview_arrays
        init_live_preview_arrays(self, layer)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._apply_effect)

        self._build_ui()
        self._apply_effect()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        
        self.canvas = SharpenCanvas(self)
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
            
        self.amount_sl, self.amt_lbl = add_slider(tr("sharpen.amount"))
        self.radius_sl, self.rad_lbl = add_slider(tr("sharpen.radius"))
        self.noise_sl, self.noise_lbl = add_slider(tr("sharpen.reduce_noise"))
        self.thresh_sl, self.thr_lbl = add_slider(tr("sharpen.threshold"))

        for wg in [self.amount_sl, self.amt_lbl, self.radius_sl, self.rad_lbl, 
                   self.noise_sl, self.noise_lbl, self.thresh_sl, self.thr_lbl]: wg.hide()

        if self.mode == "unsharp":
            self.amount_sl.setRange(1, 500); self.amount_sl.setValue(50)
            self.radius_sl.setRange(1, 250); self.radius_sl.setValue(10) # Divide by 10 for float (1.0)
            self.thresh_sl.setRange(0, 255); self.thresh_sl.setValue(0)
            for w in [self.amount_sl, self.amt_lbl, self.radius_sl, self.rad_lbl, self.thresh_sl, self.thr_lbl]: w.show()
        elif self.mode == "smart":
            self.amount_sl.setRange(1, 500); self.amount_sl.setValue(100)
            self.radius_sl.setRange(1, 250); self.radius_sl.setValue(10)
            self.noise_sl.setRange(0, 100); self.noise_sl.setValue(10)
            for w in [self.amount_sl, self.amt_lbl, self.radius_sl, self.rad_lbl, self.noise_sl, self.noise_lbl]: w.show()
        elif self.mode in ("sharpen", "edges", "more"):
            msg = "Этот фильтр не имеет\nнастраиваемых параметров." if locale_current() == "ru" else "This filter has no\nadjustable parameters."
            lbl = QLabel(msg)
            theme.apply_style(lbl, lambda: f"color: {theme.SUBTEXT}; font-size: 12px; font-style: italic;")
            pl.addWidget(lbl)

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _trigger_update(self):
        self._timer.start()

    def _apply_effect(self):
        res_arr = self.orig_arr.copy()
        
        if self.mode == "sharpen":
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            res_arr[..., :3] = apply_conv3x3(self.orig_arr, kernel)
            
        elif self.mode == "more":
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
            res_arr[..., :3] = apply_conv3x3(self.orig_arr, kernel)
            
        elif self.mode == "edges":
            gray = 0.299 * self.orig_arr[..., 2] + 0.587 * self.orig_arr[..., 1] + 0.114 * self.orig_arr[..., 0]
            gy = np.abs(np.roll(gray, -1, axis=0) - gray)
            gx = np.abs(np.roll(gray, -1, axis=1) - gray)
            edges = (gx + gy) > 15
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            sharp = apply_conv3x3(self.orig_arr, kernel)
            res_arr[edges, :3] = sharp[edges]
            
        elif self.mode in ("unsharp", "smart"):
            amt = self.amount_sl.value() / 100.0
            rad = max(1, self.radius_sl.value() // 10)
            
            base = self.orig_arr[..., :3].copy()
            if self.mode == "smart" and self.noise_sl.value() > 0:
                base = fast_box_blur_np(base, max(1, self.noise_sl.value() // 10))
                
            blurred = fast_box_blur_np(base, rad)
            diff = self.orig_arr[..., :3].astype(np.int16) - blurred.astype(np.int16)
            
            if self.mode == "unsharp":
                thresh = self.thresh_sl.value()
                mask = np.max(np.abs(diff), axis=-1, keepdims=True) > thresh
            else:
                mask = True # Smart Sharpen applies difference everywhere
                
            res_arr[..., :3] = np.where(mask, np.clip(self.orig_arr[..., :3].astype(np.float32) + diff * amt, 0, 255).astype(np.uint8), self.orig_arr[..., :3])
            
        h, w = res_arr.shape[:2]
        self.preview_img = QImage(res_arr.data, w, h, w*4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self.canvas.update()

    def accept(self):
        from ui.preview_canvas_base import run_full_res_commit
        if run_full_res_commit(self, self._apply_effect):
            self.layer.image = self.preview_img
            super().accept()