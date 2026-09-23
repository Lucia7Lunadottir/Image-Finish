import math
import numpy as np
import ctypes

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSpinBox, QComboBox, QPushButton, 
                             QDialogButtonBox, QWidget, QScrollArea, QFrame)
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QTimer
from PyQt6.QtGui import (QImage, QPainter, QColor, QPen,
                         QPainterPath, QRegion, QBitmap, QCursor)

from core.locale import tr
from core.adjustments.hdr_toning import _box_blur_ch
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import PreviewCanvasBase

from ui import theme

def _blur_mask(m, r):
    if r <= 0: return m
    res = _box_blur_ch(m, r)
    res = _box_blur_ch(res, r)
    res = _box_blur_ch(res, r)
    return res

class SelectAndMaskCanvas(PreviewCanvasBase):
    def __init__(self, dialog=None):
        super().__init__(dialog)
        self._drawing = False
        self._mouse_pos = QPointF(-100, -100)

    def to_img(self, widget_pos: QPointF) -> QPoint:
        x = (widget_pos.x() - self._pan.x()) / self.zoom
        y = (widget_pos.y() - self._pan.y()) / self.zoom
        return QPoint(int(x), int(y))

    def _wants_checkerboard(self) -> bool:
        return self.dialog.view_mode in ("onion", "overlay")

    def _image_clip_rect(self, w, h):
        return QRect(int(self._pan.x()), int(self._pan.y()), int(w * self.zoom), int(h * self.zoom))

    def _idle_cursor(self):
        return Qt.CursorShape.BlankCursor

    def _is_pan_trigger(self, ev) -> bool:
        return super()._is_pan_trigger(ev) or self.dialog.active_tool == "hand"

    def _paint_overlay_in_screen_space(self, p):
        if self.dialog.active_tool in ("refine", "brush", "eraser") and not self._space:
            r = (self.dialog.brush_size * self.zoom) / 2.0
            p.setPen(QPen(QColor(0, 0, 0, 150), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self._mouse_pos, r, r)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.drawEllipse(self._mouse_pos, r-1, r-1)
            if self.dialog.active_tool == "refine":
                p.drawLine(self._mouse_pos - QPointF(r, 0), self._mouse_pos + QPointF(r, 0))
                p.drawLine(self._mouse_pos - QPointF(0, r), self._mouse_pos + QPointF(0, r))

    def mousePressEvent(self, ev):
        if self._maybe_start_pan(ev):
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.dialog.active_tool in ("refine", "brush", "eraser"):
            self._drawing = True
            self.dialog.apply_stroke(self.to_img(ev.position()))

    def mouseMoveEvent(self, ev):
        self._mouse_pos = ev.position()
        if self._maybe_continue_pan(ev):
            return
        if self._drawing:
            self.dialog.apply_stroke(self.to_img(ev.position()))
        self.update()

    def mouseReleaseEvent(self, ev):
        self._panning = False
        self._drawing = False
        if self.dialog and self.dialog.active_tool == "hand":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(self._idle_cursor())
        if self.dialog:
            self.dialog.commit_stroke()


class SelectAndMaskDialog(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("sam.title"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1100, 750)
        
        self.document = document
        self.layer = document.get_active_layer()
        if not self.layer or self.layer.image.isNull():
            self.reject()
            return
            
        self.W, self.H = self.layer.width(), self.layer.height()
        
        from core.pixel_buffer import qimage_argb_view
        self.orig_arr = qimage_argb_view(self.layer.image, writable=False)[:, :self.W, :].copy()
        
        self.base_mask = np.zeros((self.H, self.W), dtype=np.float32)
        sel = document.selection
        if sel and not sel.isEmpty():
            m_img = QImage(self.W, self.H, QImage.Format.Format_Grayscale8)
            m_img.fill(0)
            p = QPainter(m_img)
            p.translate(-self.layer.offset.x(), -self.layer.offset.y())
            p.fillPath(sel, QColor(255))
            p.end()
            m_ptr = m_img.constBits()
            m_buf = (ctypes.c_uint8 * m_img.sizeInBytes()).from_address(int(m_ptr))
            self.base_mask = np.ndarray((self.H, m_img.bytesPerLine()), dtype=np.uint8, buffer=m_buf)[:, :self.W].astype(np.float32) / 255.0
            
        self.display_mask = self.base_mask.copy()
        self.preview_img = QImage(self.W, self.H, QImage.Format.Format_ARGB32_Premultiplied)
        
        self.active_tool = "refine"
        self.view_mode = "onion"
        self.brush_size = 40
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._update_display_mask)

        self._build_ui()
        self._update_display_mask()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        
        # Toolbar (Left)
        tb = QVBoxLayout()
        tb.setContentsMargins(8, 8, 8, 8)
        tb.setSpacing(4)
        
        self.btns = {}
        def add_tool(name, icon):
            b = QPushButton(icon)
            b.setFixedSize(46, 38)
            theme.apply_style(b, lambda: f"font-size: 18px; border-radius: 4px; background: {theme.SURFACE0};")
            b.clicked.connect(lambda _, n=name: self._set_tool(n))
            tb.addWidget(b)
            self.btns[name] = b
            
        add_tool("refine", "🪄🖌️")
        add_tool("brush", "🖌️")
        add_tool("eraser", "🧽")
        tb.addSpacing(15)
        add_tool("hand", "🖐")
        tb.addStretch()
        
        left_widget = QWidget()
        left_widget.setLayout(tb)
        left_widget.setFixedWidth(62)
        theme.apply_style(left_widget, lambda: f"background: {theme.MANTLE};")
        root.addWidget(left_widget)
        
        # Canvas
        self.canvas = SelectAndMaskCanvas(self)
        root.addWidget(self.canvas, 1)
        
        # Properties (Right)
        props = QWidget()
        props.setFixedWidth(280)
        theme.apply_style(props, lambda: f"background: {theme.BASE}; border-left: 1px solid {theme.SURFACE0};")
        pl = QVBoxLayout(props)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(10)
        
        def lbl(text, bold=False):
            l = QLabel(text)
            if bold: theme.apply_style(l, lambda: f"color: {theme.TEXT}; font-weight: bold; font-size: 13px; margin-top: 8px;")
            else: theme.apply_style(l, lambda: f"color: {theme.SUBTEXT}; font-size: 12px;")
            return l
            
        pl.addWidget(lbl(tr("sam.view_mode"), True))
        self.mode_combo = QComboBox()
        modes = [("onion", tr("sam.onion")), ("overlay", tr("sam.overlay")), 
                 ("black", tr("sam.on_black")), ("white", tr("sam.on_white")), 
                 ("bw", tr("sam.bw"))]
        for m, text in modes: self.mode_combo.addItem(text, m)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        pl.addWidget(self.mode_combo)
        
        self.op_sl = _JumpSlider(Qt.Orientation.Horizontal); self.op_sl.setRange(0, 100); self.op_sl.setValue(50)
        self.op_sl.valueChanged.connect(lambda v: self._render_preview())
        pl.addWidget(lbl(tr("sam.opacity")))
        pl.addWidget(self.op_sl)
        
        pl.addWidget(lbl(tr("opts.size"), True))
        self.size_sl = _JumpSlider(Qt.Orientation.Horizontal); self.size_sl.setRange(1, 500); self.size_sl.setValue(40)
        self.size_sl.valueChanged.connect(lambda v: setattr(self, "brush_size", v))
        pl.addWidget(self.size_sl)
        
        pl.addWidget(lbl(tr("sam.global"), True))
        
        self.sm_sl = _JumpSlider(Qt.Orientation.Horizontal); self.sm_sl.setRange(0, 100); self.sm_sl.setValue(0)
        self.sm_sl.valueChanged.connect(lambda v: self._timer.start(40))
        pl.addWidget(lbl(tr("sam.smooth")))
        pl.addWidget(self.sm_sl)
        
        self.ft_sl = _JumpSlider(Qt.Orientation.Horizontal); self.ft_sl.setRange(0, 100); self.ft_sl.setValue(0)
        self.ft_sl.valueChanged.connect(lambda v: self._timer.start(40))
        pl.addWidget(lbl(tr("sam.feather")))
        pl.addWidget(self.ft_sl)
        
        self.ct_sl = _JumpSlider(Qt.Orientation.Horizontal); self.ct_sl.setRange(0, 100); self.ct_sl.setValue(0)
        self.ct_sl.valueChanged.connect(lambda v: self._timer.start(40))
        pl.addWidget(lbl(tr("sam.contrast")))
        pl.addWidget(self.ct_sl)
        
        self.sh_sl = _JumpSlider(Qt.Orientation.Horizontal); self.sh_sl.setRange(-100, 100); self.sh_sl.setValue(0)
        self.sh_sl.valueChanged.connect(lambda v: self._timer.start(40))
        pl.addWidget(lbl(tr("sam.shift")))
        pl.addWidget(self.sh_sl)
        
        pl.addWidget(lbl(tr("sam.output"), True))
        self.out_combo = QComboBox()
        self.out_combo.addItem(tr("sam.out.selection"), "selection")
        self.out_combo.addItem(tr("sam.out.mask"), "mask")
        self.out_combo.addItem(tr("sam.out.new_layer"), "layer")
        self.out_combo.addItem(tr("sam.out.new_mask"), "layer_mask")
        pl.addWidget(self.out_combo)
        
        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)
        
        self._set_tool("refine")

    def _set_tool(self, name):
        self.active_tool = name
        for n, b in self.btns.items():
            b.setStyleSheet(f"font-size: 18px; border-radius: 4px; background: {theme.ACCENT};" if n == name else "font-size: 18px; border-radius: 4px; background: #313244;")
        if name == "hand": self.canvas.setCursor(Qt.CursorShape.OpenHandCursor)
        else: self.canvas.setCursor(Qt.CursorShape.BlankCursor)

    def _on_mode_change(self):
        self.view_mode = self.mode_combo.currentData()
        self._render_preview()

    def apply_stroke(self, pos):
        r = self.brush_size // 2
        x1, y1 = max(0, pos.x() - r), max(0, pos.y() - r)
        x2, y2 = min(self.W, pos.x() + r), min(self.H, pos.y() + r)
        if x1 >= x2 or y1 >= y2: return
        
        Y, X = np.ogrid[y1-pos.y():y2-pos.y(), x1-pos.x():x2-pos.x()]
        brush = (X**2 + Y**2 <= r**2)
        if not np.any(brush): return
        
        roi_m = self.base_mask[y1:y2, x1:x2]
        
        if self.active_tool == "brush":
            roi_m[brush] = np.maximum(roi_m[brush], 1.0)
        elif self.active_tool == "eraser":
            roi_m[brush] = np.minimum(roi_m[brush], 0.0)
        elif self.active_tool == "refine":
            roi_img = self.orig_arr[y1:y2, x1:x2, :3].astype(np.float32)
            fg = roi_img[roi_m > 0.8]
            bg = roi_img[roi_m < 0.2]
            
            if len(fg) > 5 and len(bg) > 5:
                fg_m = np.mean(fg, axis=0)
                bg_m = np.mean(bg, axis=0)
                diff = fg_m - bg_m
                norm = np.dot(diff, diff)
                if norm > 1e-5:
                    proj = (roi_img[..., 0] - bg_m[0])*diff[0] + (roi_img[..., 1] - bg_m[1])*diff[1] + (roi_img[..., 2] - bg_m[2])*diff[2]
                    alpha = np.clip(proj / norm, 0.0, 1.0)
                else: alpha = roi_m
            else: alpha = roi_m
            
            roi_m[brush] = roi_m[brush] * 0.5 + alpha[brush] * 0.5
            
        self.display_mask[y1:y2, x1:x2] = roi_m
        self._render_preview((x1, y1, x2, y2))

    def commit_stroke(self):
        self._update_display_mask()

    def _update_display_mask(self):
        m = self.base_mask.copy()
        smooth = self.sm_sl.value()
        feather = self.ft_sl.value()
        contrast = self.ct_sl.value()
        shift = self.sh_sl.value()
        
        if smooth > 0:
            m = _blur_mask(m, smooth)
            m = np.clip((m - 0.5) * 5.0 + 0.5, 0, 1)
        if shift != 0:
            m = np.clip(m + (shift / 100.0), 0.0, 1.0)
        if contrast > 0:
            factor = (100.0 + contrast * 2) / 100.0
            m = np.clip((m - 0.5) * factor + 0.5, 0.0, 1.0)
        if feather > 0:
            m = _blur_mask(m, feather)
            
        self.display_mask = m
        self._render_preview()

    def _render_preview(self, rect=None):
        if rect is None:
            x1, y1, x2, y2 = 0, 0, self.W, self.H
        else:
            x1, y1, x2, y2 = rect
            
        from core.pixel_buffer import qimage_argb_view
        out = qimage_argb_view(self.preview_img, writable=True)[:, :self.W, :]
        
        m = self.display_mask[y1:y2, x1:x2, np.newaxis]
        op = self.op_sl.value() / 100.0
        
        orig = self.orig_arr[y1:y2, x1:x2]
        out_roi = out[y1:y2, x1:x2]
        
        if self.view_mode == "bw":
            out_roi[..., :3] = (m * 255).astype(np.uint8)
            out_roi[..., 3] = 255
        elif self.view_mode == "onion":
            final_a = m + (1.0 - m) * (1.0 - op)
            out_roi[..., :3] = orig[..., :3]
            out_roi[..., 3] = (final_a[..., 0] * 255).astype(np.uint8)
        elif self.view_mode == "black":
            out_roi[..., :3] = orig[..., :3] * m + 0 * (1.0 - m)
            out_roi[..., 3] = 255
        elif self.view_mode == "white":
            out_roi[..., :3] = orig[..., :3] * m + 255 * (1.0 - m)
            out_roi[..., 3] = 255
        elif self.view_mode == "overlay":
            alpha = (1.0 - self.display_mask[y1:y2, x1:x2]) * op
            out_roi[..., 2] = np.clip(orig[..., 2] * (1 - alpha) + 255 * alpha, 0, 255).astype(np.uint8)
            out_roi[..., 1] = np.clip(orig[..., 1] * (1 - alpha), 0, 255).astype(np.uint8)
            out_roi[..., 0] = np.clip(orig[..., 0] * (1 - alpha), 0, 255).astype(np.uint8)
            out_roi[..., 3] = 255
            
        self.canvas.update()

    def get_result(self):
        return self.out_combo.currentData(), self.display_mask