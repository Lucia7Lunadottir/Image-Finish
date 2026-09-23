import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QDialogButtonBox, QWidget, QSpinBox, QGridLayout)
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QImage

from core.locale import tr
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase
from tools.tool_utils import fast_box_blur_np

from ui import theme


class OtherFiltersCanvas(PreviewCanvasBase):
    pass


class OtherFiltersDialog(QDialog):
    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.mode = mode
        self.canvas_refresh = canvas_refresh
        
        title = tr(f"menu.other.{mode}").replace('…', '')
        self.setWindowTitle(f"{tr('menu.other')} - {title}")
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
        
        self.canvas = OtherFiltersCanvas(self)
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
            
        self.radius_sl, self.rad_lbl = add_slider(tr("other.radius"))
        
        self.dx_lbl = QLabel(tr("other.horiz"))
        self.dx_sp = QSpinBox(); self.dx_sp.setRange(-9999, 9999); self.dx_sp.valueChanged.connect(self._trigger_update)
        self.dy_lbl = QLabel(tr("other.vert"))
        self.dy_sp = QSpinBox(); self.dy_sp.setRange(-9999, 9999); self.dy_sp.valueChanged.connect(self._trigger_update)
        self.edge_lbl = QLabel(tr("other.edge"))
        self.edge_combo = QComboBox()
        self.edge_combo.addItem(tr("other.wrap"), 0)
        self.edge_combo.addItem(tr("other.repeat"), 1)
        self.edge_combo.addItem(tr("other.bg"), 2)
        self.edge_combo.currentIndexChanged.connect(self._trigger_update)
        
        for w in [self.dx_lbl, self.dx_sp, self.dy_lbl, self.dy_sp, self.edge_lbl, self.edge_combo]: pl.addWidget(w)

        # Custom 3x3 matrix
        self.matrix_w = QWidget()
        grid = QGridLayout(self.matrix_w)
        grid.setContentsMargins(0,0,0,0); grid.setSpacing(4)
        self.k_spins = []
        for i in range(3):
            row = []
            for j in range(3):
                sp = QSpinBox(); sp.setRange(-999, 999); sp.setValue(1 if i==1 and j==1 else 0)
                sp.valueChanged.connect(self._trigger_update)
                grid.addWidget(sp, i, j)
                row.append(sp)
            self.k_spins.append(row)
            
        self.scale_lbl = QLabel(tr("other.scale"))
        self.scale_sp = QSpinBox(); self.scale_sp.setRange(1, 9999); self.scale_sp.setValue(1)
        self.scale_sp.valueChanged.connect(self._trigger_update)
        self.offset_lbl = QLabel(tr("other.offset_val"))
        self.offset_sp = QSpinBox(); self.offset_sp.setRange(-9999, 9999); self.offset_sp.setValue(0)
        self.offset_sp.valueChanged.connect(self._trigger_update)
        
        for w in [self.matrix_w, self.scale_lbl, self.scale_sp, self.offset_lbl, self.offset_sp]: pl.addWidget(w)

        for wg in [self.radius_sl, self.rad_lbl, self.dx_lbl, self.dx_sp, self.dy_lbl, self.dy_sp, 
                   self.edge_lbl, self.edge_combo, self.matrix_w, self.scale_lbl, self.scale_sp, self.offset_lbl, self.offset_sp]:
            wg.hide()

        if self.mode == "high_pass":
            self.radius_sl.setRange(1, 250); self.radius_sl.setValue(10)
            self.radius_sl.show(); self.rad_lbl.show()
        elif self.mode in ("minimum", "maximum"):
            self.radius_sl.setRange(1, 100); self.radius_sl.setValue(1)
            self.radius_sl.show(); self.rad_lbl.show()
        elif self.mode == "offset":
            for wg in [self.dx_lbl, self.dx_sp, self.dy_lbl, self.dy_sp, self.edge_lbl, self.edge_combo]: wg.show()
        elif self.mode == "custom":
            for wg in [self.matrix_w, self.scale_lbl, self.scale_sp, self.offset_lbl, self.offset_sp]: wg.show()

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _trigger_update(self):
        self._timer.start()

    def _apply_effect(self):
        res_arr = self.orig_arr.copy()
        h, w = res_arr.shape[:2]
        
        if self.mode == "high_pass":
            r = self.radius_sl.value()
            blurred = fast_box_blur_np(self.orig_arr, r)
            res = self.orig_arr[..., :3].astype(np.float32) - blurred[..., :3].astype(np.float32) + 128.0
            res_arr[..., :3] = np.clip(res, 0, 255).astype(np.uint8)
            
        elif self.mode in ("minimum", "maximum"):
            r = self.radius_sl.value()
            op = np.minimum if self.mode == "minimum" else np.maximum
            
            padded_x = np.pad(self.orig_arr[..., :3], ((0,0), (r,r), (0,0)), mode='edge')
            tmp = padded_x[:, r:w+r, :]
            for i in range(-r, r+1): tmp = op(tmp, padded_x[:, r+i : w+r+i, :]) if i != -r else padded_x[:, r+i : w+r+i, :]
                
            padded_y = np.pad(tmp, ((r,r), (0,0), (0,0)), mode='edge')
            res = padded_y[r:h+r, :, :]
            for i in range(-r, r+1): res = op(res, padded_y[r+i : h+r+i, :, :]) if i != -r else padded_y[r+i : h+r+i, :, :]
                
            res_arr[..., :3] = res
            
        elif self.mode == "offset":
            dx, dy = self.dx_sp.value(), self.dy_sp.value()
            edge_mode = self.edge_combo.currentIndex()
            if edge_mode == 0:
                res_arr = np.roll(np.roll(self.orig_arr, dy, axis=0), dx, axis=1)
            elif edge_mode == 1:
                Y, X = np.ogrid[:h, :w]
                Y = np.clip(Y - dy, 0, h - 1); X = np.clip(X - dx, 0, w - 1)
                res_arr = self.orig_arr[Y, X]
            elif edge_mode == 2:
                res_arr.fill(0)
                y1_src, y2_src = max(0, -dy), min(h, h - dy); x1_src, x2_src = max(0, -dx), min(w, w - dx)
                y1_dst, y2_dst = max(0, dy), min(h, h + dy); x1_dst, x2_dst = max(0, dx), min(w, w + dx)
                if y1_src < y2_src and x1_src < x2_src: res_arr[y1_dst:y2_dst, x1_dst:x2_dst] = self.orig_arr[y1_src:y2_src, x1_src:x2_src]
                
        elif self.mode == "custom":
            kernel = np.array([[self.k_spins[i][j].value() for j in range(3)] for i in range(3)], dtype=np.float32)
            scale, offset = self.scale_sp.value(), self.offset_sp.value()
            padded = np.pad(self.orig_arr[..., :3].astype(np.float32), ((1,1),(1,1),(0,0)), mode='edge')
            res = np.zeros((h, w, 3), dtype=np.float32)
            for dy in range(3):
                for dx in range(3):
                    if kernel[dy, dx] != 0: res += padded[dy:h+dy, dx:w+dx] * kernel[dy, dx]
            res_arr[..., :3] = np.clip(res / scale + offset, 0, 255).astype(np.uint8)
            
        self.preview_img = QImage(res_arr.data, w, h, w*4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self.canvas.update()

    def accept(self):
        from ui.preview_canvas_base import run_full_res_commit
        if run_full_res_commit(self, self._apply_effect):
            self.layer.image = self.preview_img
            super().accept()