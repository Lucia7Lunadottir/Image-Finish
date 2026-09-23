import numpy as np
import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QDialogButtonBox, QWidget, QFileDialog)
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QImage, QColor, QPen

from core.locale import tr
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase, DragCenterMixin

from ui import theme


class DistortCanvas(DragCenterMixin, PreviewCanvasBase):
    _center_hit_radius = 30

    def _center_active(self):
        return self.dialog.mode in ("twirl", "pinch", "spherize", "zigzag")

    def _paint_overlay_in_image_space(self, p, w, h):
        if self._center_active():
            cx, cy = self.dialog.cx, self.dialog.cy
            p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 1.5/self.zoom)))
            p.setBrush(QColor(0, 0, 0, 100))
            cr = max(4.0, 6.0/self.zoom)
            p.drawEllipse(QPointF(cx, cy), cr, cr)
            p.drawEllipse(QPointF(cx, cy), cr*3, cr*3)


class DistortDialog(QDialog):
    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.mode = mode
        self.canvas_refresh = canvas_refresh
        
        mode_title = tr('menu.distort.' + mode).replace('…', '')
        self.setWindowTitle(f"{tr('menu.distort')} - {mode_title}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1000, 700)
        
        from ui.preview_canvas_base import init_live_preview_arrays
        init_live_preview_arrays(self, layer)
        self.cx = self.orig_img.width() / 2.0
        self.cy = self.orig_img.height() / 2.0
        self.disp_arr = None
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._apply_effect)

        self._build_ui()
        self._apply_effect()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        
        self.canvas = DistortCanvas(self)
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
            
        self.amount_sl, self.amt_lbl = add_slider(tr("distort.amount"))
        self.param2_sl, self.p2_lbl = add_slider(tr("distort.param2"))
        
        def hide_p2(): self.param2_sl.hide(); self.p2_lbl.hide()
        def hide_amt(): self.amount_sl.hide(); self.amt_lbl.hide()

        if self.mode == "twirl":
            self.amount_sl.setRange(-720, 720); self.amount_sl.setValue(100); hide_p2()
        elif self.mode in ("pinch", "spherize", "shear"):
            self.amount_sl.setRange(-100, 100); self.amount_sl.setValue(50); hide_p2()
        elif self.mode == "ripple":
            self.amount_sl.setRange(1, 100); self.amount_sl.setValue(10)
            self.param2_sl.setRange(1, 100); self.param2_sl.setValue(30)
        elif self.mode == "wave":
            self.amount_sl.setRange(1, 200); self.amount_sl.setValue(20)
            self.param2_sl.setRange(1, 500); self.param2_sl.setValue(120)
        elif self.mode == "zigzag":
            self.amount_sl.setRange(-100, 100); self.amount_sl.setValue(30)
            self.param2_sl.setRange(1, 50); self.param2_sl.setValue(10)
        elif self.mode == "polar":
            hide_amt(); hide_p2()
            self.mode_combo = QComboBox()
            self.mode_combo.addItem(tr("distort.polar.r2p"), 0)
            self.mode_combo.addItem(tr("distort.polar.p2r"), 1)
            self.mode_combo.currentIndexChanged.connect(self._trigger_update)
            pl.addWidget(self.mode_combo)
        elif self.mode == "displace":
            self.amount_sl.setRange(-200, 200); self.amount_sl.setValue(20)
            self.param2_sl.setRange(-200, 200); self.param2_sl.setValue(20)
            self.load_btn = QPushButton(tr("distort.load_map"))
            self.load_btn.clicked.connect(self._load_map)
            pl.addWidget(self.load_btn)

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _load_map(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("distort.load_map"), "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            img = QImage(path).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            from core.pixel_buffer import qimage_argb_view
            self.disp_arr = qimage_argb_view(img, writable=False).copy()
            self._trigger_update()

    def _trigger_update(self):
        self._timer.start()

    def _apply_effect(self):
        amount = self.amount_sl.value()
        p2 = self.param2_sl.value()
        
        if amount == 0 and self.mode not in ("polar", "displace"):
            self.preview_img = self.orig_img.copy()
            self.canvas.update()
            return
            
        h, w = self.orig_arr.shape[:2]
        
        Y, X = np.ogrid[:h, :w]
        X_out = np.broadcast_to(X, (h, w)).astype(np.float32).copy()
        Y_out = np.broadcast_to(Y, (h, w)).astype(np.float32).copy()
        
        cx, cy = self.cx, self.cy
        rmax = max(1.0, math.hypot(w, h) / 2.0)
        
        if self.mode in ("twirl", "pinch", "spherize", "zigzag"):
            dx = X_out - cx
            dy = Y_out - cy
            r = np.hypot(dx, dy)
            theta = np.arctan2(dy, dx)
        
        if self.mode == "twirl":
            angle = np.radians(amount)
            mask = r < rmax
            theta_src = theta.copy()
            theta_src[mask] = theta[mask] - angle * ((rmax - r[mask]) / rmax)
            X_out[mask] = cx + r[mask] * np.cos(theta_src[mask])
            Y_out[mask] = cy + r[mask] * np.sin(theta_src[mask])
        elif self.mode in ("pinch", "spherize"):
            a = amount / 100.0
            if self.mode == "spherize": a = -a
            mask = r < rmax
            r_src = r.copy()
            r_src[mask] = rmax * np.power(np.maximum(r[mask], 1e-5) / rmax, 1.0 - a)
            X_out[mask] = cx + r_src[mask] * np.cos(theta[mask])
            Y_out[mask] = cy + r_src[mask] * np.sin(theta[mask])
        elif self.mode == "ripple":
            X_out += amount * np.sin(2 * np.pi * Y_out / max(1, p2))
            Y_out += amount * np.sin(2 * np.pi * X_out / max(1, p2))
        elif self.mode == "wave":
            X_out += amount * np.sin(2 * np.pi * Y_out / max(1, p2))
            Y_out += amount * np.cos(2 * np.pi * X_out / max(1, p2))
        elif self.mode == "zigzag":
            r_src = r - amount * np.sin(max(1, p2) * 2 * np.pi * r / rmax)
            X_out = cx + r_src * np.cos(theta)
            Y_out = cy + r_src * np.sin(theta)
        elif self.mode == "shear":
            X_out -= amount * np.sin(Y_out / h * np.pi)
        elif self.mode == "polar":
            if self.mode_combo.currentIndex() == 0:
                r_src, theta_src = Y_out * (rmax / h), (X_out / w) * 2 * np.pi - np.pi
                X_out, Y_out = cx + r_src * np.cos(theta_src), cy + r_src * np.sin(theta_src)
            else:
                r_dest, theta_dest = Y_out / h * rmax, (X_out / w) * 2 * np.pi - np.pi
                X_out, Y_out = cx + r_dest * np.cos(theta_dest), cy + r_dest * np.sin(theta_dest)
        elif self.mode == "displace" and self.disp_arr is not None:
            dh, dw = self.disp_arr.shape[:2]
            m_Y, m_X = np.clip((Y_out / h * dh).astype(np.int32), 0, dh - 1), np.clip((X_out / w * dw).astype(np.int32), 0, dw - 1)
            d_color = self.disp_arr[m_Y, m_X]
            X_out -= ((d_color[..., 2].astype(np.float32) - 128.0) / 128.0) * amount
            Y_out -= ((d_color[..., 1].astype(np.float32) - 128.0) / 128.0) * p2

        X_idx = np.clip(np.round(X_out).astype(np.int32), 0, w - 1)
        Y_idx = np.clip(np.round(Y_out).astype(np.int32), 0, h - 1)
        res_arr = self.orig_arr[Y_idx, X_idx]
        
        out_of_bounds = (X_out < 0) | (X_out >= w) | (Y_out < 0) | (Y_out >= h)
        if np.any(out_of_bounds): res_arr[out_of_bounds] = 0
            
        self.preview_img = QImage(res_arr.data, w, h, w*4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self.canvas.update()

    def accept(self):
        from ui.preview_canvas_base import run_full_res_commit
        if run_full_res_commit(self, self._apply_effect, scale_attrs=("cx", "cy")):
            self.layer.image = self.preview_img
            super().accept()