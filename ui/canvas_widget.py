import math
import traceback

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QBrush, QPen, QImage, QCursor, QInputDevice,
                         QRadialGradient, QPainterPath, QPolygon, QPolygonF, QBitmap, QRegion, QTransform)

from tools.other_tools import (SelectTool, CropTool, ShapesTool,
                               HandTool, ZoomTool, RotateViewTool, GradientTool, PerspectiveCropTool)

# Brush tools — show circle cursor for these
_BRUSH_TOOLS = {"Brush", "Eraser", "BackgroundEraser", "Blur", "Sharpen", "Smudge", "CloneStamp", "PatternStamp",
                "Pencil", "ColorReplacement", "MixerBrush",
                "SpotHealing", "HealingBrush", "HistoryBrush",
                "Dodge", "Burn", "Sponge",
                "QuickSelection"}

_SELECTION_TOOLS = {
    "Select", "EllipseSelect",
    "Lasso", "PolygonalLasso", "MagneticLasso",
    "MagicWand", "ObjectSelection",
}

_sel_cursor_cache: dict = {}

def _make_sel_cursor(mode: str) -> QCursor:
    """Create a crosshair cursor with selection mode indicator: '' / '+' / '-' / 'x'."""
    if mode in _sel_cursor_cache:
        return _sel_cursor_cache[mode]

    SIZE = 24
    HOT  = SIZE // 2
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    mid = HOT
    gap = 4

    def _line(pen, x1, y1, x2, y2):
        p.setPen(pen)
        p.drawLine(x1, y1, x2, y2)

    white = QPen(Qt.GlobalColor.white, 2)
    black = QPen(Qt.GlobalColor.black, 1)

    for arm in [(mid, 0, mid, mid - gap),
                (mid, mid + gap, mid, SIZE - 1),
                (0, mid, mid - gap, mid),
                (mid + gap, mid, SIZE - 1, mid)]:
        _line(black, *arm)
        _line(white, *arm)

    bx, by = 15, 15
    bw = 7

    if mode == "add":
        cx, cy = bx + bw // 2, by + bw // 2
        for coords in [(cx, by, cx, by + bw), (bx, cy, bx + bw, cy)]:
            _line(black, *coords)
            _line(white, *coords)
    elif mode == "sub":
        cy = by + bw // 2
        _line(black, bx, cy, bx + bw, cy)
        _line(white, bx, cy, bx + bw, cy)
    elif mode == "intersect":
        for coords in [(bx, by, bx + bw, by + bw), (bx + bw, by, bx, by + bw)]:
            _line(black, *coords)
            _line(white, *coords)

    p.end()
    cur = QCursor(px, HOT, HOT)
    _sel_cursor_cache[mode] = cur
    return cur


class CanvasWidget(QWidget):
    document_changed = pyqtSignal()
    pixels_changed   = pyqtSignal()
    color_picked     = pyqtSignal(QColor)
    tool_state_changed = pyqtSignal(object)
    cursor_info      = pyqtSignal(int, int, QColor)  # doc x, doc y, pixel color

    def __init__(self, parent=None):
        super().__init__(parent)

        self.document    = None
        self.active_tool = None
        self.view_channel = "RGB"

        self.fg_color = QColor(0, 0, 0)
        self.bg_color = QColor(255, 255, 255)
        self.tool_opts: dict = {
            "brush_size":     10,
            "brush_opacity":  1.0,
            "brush_hardness": 1.0,
            "brush_angle":    0.0,
            "brush_angle_random": False,
            "brush_mask":     "round",
            "brush_blend_mode": "SourceOver",
            "brush_pattern_scale": 100,
            "brush_mirror_x": False,
            "brush_mirror_y": False,
            "fill_tolerance": 32,
            "fill_contiguous": True,
            "font_size":        24,
            "font_family":      "Sans Serif",
            "font_bold":        False,
            "font_italic":      False,
            "font_underline":   False,
            "font_strikeout":   False,
            "text_color":       QColor(0, 0, 0),
            "text_stroke_w":    0,
            "text_stroke_color": QColor(0, 0, 0),
            "text_shadow":      False,
            "text_shadow_color": QColor(0, 0, 0, 160),
            "text_shadow_dx":   3,
            "text_shadow_dy":   3,
            "shape_type":     "rect",
            "shape_fill":     False,
            "shape_sides":    6,
            "shape_angle":    0,
            "effect_strength": 0.5,
            "crop_overlay":   "thirds",
        }

        self.zoom: float   = 1.0
        self._pan: QPointF = QPointF(0, 0)
        self._pan_last: QPointF | None = None
        self._panning: bool = False
        self._space:   bool = False

        self._view_rotation: float = 0.0
        self._rotating:      bool  = False
        self._rotate_last_angle: float = 0.0

        self._stroke_in_progress: bool = False
        self._pre_stroke_state = None

        self._mouse_pos: QPointF = QPointF(-100, -100)
        self._show_brush_cursor: bool = False
        self._is_mouse_in: bool = False

        self._composite_cache: QImage | None = None
        self._cache_dirty: bool = True
        self._display_cache: QImage | None = None
        self._last_view_channel: str = "RGB"

        self._effect_bg_cache: QImage | None = None
        self._in_effect_stroke: bool = False

        self.show_rulers: bool = False
        self._dragging_guide = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._checker = self._build_checker()

    @staticmethod
    def _build_checker(tile: int = 16) -> QPixmap:
        pix = QPixmap(tile * 2, tile * 2)
        p = QPainter(pix)
        p.fillRect(0,    0,    tile, tile, QColor(180, 180, 180))
        p.fillRect(tile, 0,    tile, tile, QColor(220, 220, 220))
        p.fillRect(0,    tile, tile, tile, QColor(220, 220, 220))
        p.fillRect(tile, tile, tile, tile, QColor(180, 180, 180))
        p.end()
        return pix

    def set_document(self, doc):
        self.document = doc
        self._cache_dirty = True
        self._display_cache = None
        self._pre_stroke_state = None
        self._fit_to_window()
        self.update()

    def invalidate_cache(self):
        self._cache_dirty = True
        self._display_cache = None
        self.update()

    def _start_effect_stroke(self):
        """Safely cache the background beneath the active layer for effects."""
        try:
            doc = self.document
            active = doc.get_active_layer() if doc else None

            if (active is None or
                    getattr(active, "blend_mode", "Normal") not in ("Normal", "SourceOver", "") or
                    getattr(active, "clipping", False)):
                self._effect_bg_cache = None
                self._in_effect_stroke = False
                return

            was_visible = active.visible
            active.visible = False
            self._effect_bg_cache = doc.get_composite()
            active.visible = was_visible

            self._in_effect_stroke = True
            if hasattr(self.active_tool, "_stroke_preview_active"):
                self.active_tool._stroke_preview_active = True
        except Exception as e:
            print(f"Effect cache safety catch: {e}")
            self._effect_bg_cache = None
            self._in_effect_stroke = False

    def reset_zoom(self):
        self._fit_to_window()
        self.update()

    def reset_rotation(self):
        self._view_rotation = 0.0
        self.update()

    def zoom_in(self):
        self._apply_zoom(1.25, self.rect().center())

    def zoom_out(self):
        self._apply_zoom(1 / 1.25, self.rect().center())

    def to_doc(self, widget_pos: QPointF) -> QPoint:
        if self._view_rotation:
            cx = self.width()  / 2
            cy = self.height() / 2
            dx = widget_pos.x() - cx
            dy = widget_pos.y() - cy
            a  = math.radians(-self._view_rotation)
            widget_pos = QPointF(
                dx * math.cos(a) - dy * math.sin(a) + cx,
                dx * math.sin(a) + dy * math.cos(a) + cy,
            )
        x = (widget_pos.x() - self._pan.x()) / self.zoom
        y = (widget_pos.y() - self._pan.y()) / self.zoom
        return QPoint(int(x), int(y))

    def to_widget(self, doc_pos: QPoint) -> QPointF:
        x = doc_pos.x() * self.zoom + self._pan.x()
        y = doc_pos.y() * self.zoom + self._pan.y()
        if self._view_rotation:
            cx = self.width() / 2
            cy = self.height() / 2
            dx = x - cx
            dy = y - cy
            a = math.radians(self._view_rotation)
            x = dx * math.cos(a) - dy * math.sin(a) + cx
            y = dx * math.sin(a) + dy * math.cos(a) + cy
        return QPointF(x, y)

    def _doc_rect_in_widget(self) -> QRect:
        if not self.document:
            return QRect()
        return QRect(
            int(self._pan.x()), int(self._pan.y()),
            int(self.document.width  * self.zoom),
            int(self.document.height * self.zoom),
        )

    def _fit_to_window(self):
        if not self.document or self.width() == 0 or self.height() == 0:
            return
        margin = 40
        sx = (self.width()  - margin * 2) / self.document.width
        sy = (self.height() - margin * 2) / self.document.height
        self.zoom = min(sx, sy, 1.0)
        self._pan = QPointF(
            (self.width()  - self.document.width  * self.zoom) / 2,
            (self.height() - self.document.height * self.zoom) / 2,
        )

    def _apply_zoom(self, factor: float, pivot):
        if isinstance(pivot, QPoint):
            pivot = QPointF(pivot)
        new_zoom = max(0.02, min(32.0, self.zoom * factor))
        scale = new_zoom / self.zoom
        self._pan = QPointF(
            pivot.x() - (pivot.x() - self._pan.x()) * scale,
            pivot.y() - (pivot.y() - self._pan.y()) * scale,
        )
        self.zoom = new_zoom
        self.update()

    def _draw_rulers(self, painter: QPainter):
        R = 20
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, R, QColor(40, 40, 45))
        painter.fillRect(0, 0, R, h, QColor(40, 40, 45))
        painter.fillRect(0, 0, R, R, QColor(30, 30, 35))
        
        painter.setPen(QColor(150, 150, 150))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        start_x = - (self._pan.x() / self.zoom)
        end_x = start_x + w / self.zoom
        step = 100
        if self.zoom > 2: step = 10
        elif self.zoom > 0.5: step = 50
        elif self.zoom < 0.2: step = 500
        
        first_x = int(start_x // step) * step
        for x in range(first_x, int(end_x) + step, step):
            wx = int(x * self.zoom + self._pan.x())
            if wx > R:
                painter.drawLine(wx, R - 6, wx, R)
                painter.drawText(wx + 2, R - 2, str(x))
                
        start_y = - (self._pan.y() / self.zoom)
        end_y = start_y + h / self.zoom
        first_y = int(start_y // step) * step
        for y in range(first_y, int(end_y) + step, step):
            wy = int(y * self.zoom + self._pan.y())
            if wy > R:
                painter.drawLine(R - 6, wy, R, wy)
                painter.save()
                painter.translate(R - 2, wy + 2)
                painter.rotate(-90)
                painter.drawText(0, 0, str(y))
                painter.restore()

    def paintEvent(self, _event):
        """Render the scene, guarded against internal script failures."""
        try:
            painter = QPainter(self)
            if self.zoom > 0.9:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            else:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            painter.fillRect(self.rect(), QColor(30, 30, 40))

            if not self.document:
                painter.end()
                return

            if self._view_rotation:
                buf = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
                buf.fill(QColor(0, 0, 0, 0))
                bp = QPainter(buf)
                bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                self._paint_canvas_content(bp)
                bp.end()
                cx = self.width()  / 2
                cy = self.height() / 2
                painter.translate(cx, cy)
                painter.rotate(self._view_rotation)
                painter.translate(-cx, -cy)
                painter.drawImage(0, 0, buf)
                painter.resetTransform()
            else:
                self._paint_canvas_content(painter)
                
            # Draw artboard names
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for layer in self.document.layers:
                if getattr(layer, "layer_type", "") == "artboard" and getattr(layer, "artboard_rect", None):
                    ar = layer.artboard_rect
                    painter.setPen(QPen(QColor(120, 120, 120), max(1.0, 1.0/self.zoom)))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(ar)
                    painter.setPen(QColor(200, 200, 200))
                    font = painter.font()
                    font.setPointSizeF(max(10.0, 12.0/self.zoom))
                    painter.setFont(font)
                    painter.drawText(ar.left(), ar.top() - max(4, int(4/self.zoom)), layer.name)
            painter.restore()
                
            # Guarded rendering of custom tool overlays
            if self.active_tool and hasattr(self.active_tool, "draw_overlays"):
                try:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    
                    old_hovers = {}
                    if not getattr(self, "_is_mouse_in", True):
                        for attr in ["hover_pos", "_hover_pos", "current_pos", "_current_pos", "preview_end", "_preview_end"]:
                            if hasattr(self.active_tool, attr):
                                old_hovers[attr] = getattr(self.active_tool, attr)
                                setattr(self.active_tool, attr, None)
                                
                    self.active_tool.draw_overlays(painter, max(1.0, 1.0 / self.zoom), self.document)
                    
                    for attr, val in old_hovers.items():
                        setattr(self.active_tool, attr, val)
                        
                    painter.restore()
                except Exception as e:
                    print(f"Tool overlay rendering error {getattr(self.active_tool, 'name', '')}: {e}")

            if self._show_brush_cursor and not self._panning and not self._space:
                self._draw_brush_cursor(painter)

            if self.show_rulers:
                self._draw_rulers(painter)

            painter.end()
        except Exception as ce:
            print(f"Critical canvas paint loop failure: {traceback.format_exc()}")

    def _paint_canvas_content(self, painter: QPainter):
        """Internal layer-by-layer rendering of cached images and vectors."""
        dr = self._doc_rect_in_widget()
        has_artboards = any(getattr(l, "layer_type", "") == "artboard" for l in self.document.layers)

        if not has_artboards:
            painter.save()
            painter.setClipRect(dr)
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.fillRect(0, 0, self.document.width, self.document.height, QBrush(self._checker))
            painter.restore()

        if self._cache_dirty or self._composite_cache is None:
            if self._in_effect_stroke and self._effect_bg_cache is not None:
                self._composite_cache = self._effect_bg_cache
            else:
                self.document.invalidate_composite()
                self._composite_cache = self.document.get_composite()
            self._cache_dirty = False
            self._display_cache = None
            
        current_ch = getattr(self, "view_channel", "RGB")
        if self._display_cache is None or getattr(self, "_last_view_channel", "RGB") != current_ch:
            self._last_view_channel = current_ch
            if current_ch == "RGB" or self._composite_cache is None:
                self._display_cache = self._composite_cache
            else:
                import ctypes
                import numpy as np
                comp = self._composite_cache
                w, h = comp.width(), comp.height()
                ptr = comp.constBits()
                buf = (ctypes.c_uint8 * comp.sizeInBytes()).from_address(int(ptr))
                arr = np.ndarray((h, comp.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=buf)[:, :w]
                
                B = arr[..., 0].astype(np.float32)
                G = arr[..., 1].astype(np.float32)
                R = arr[..., 2].astype(np.float32)
                
                if current_ch.startswith("alpha_"):
                    idx = int(current_ch.split("_")[1])
                    if hasattr(self.document, "alpha_channels") and 0 <= idx < len(self.document.alpha_channels):
                        alpha_path = self.document.alpha_channels[idx]["path"]
                        mask_img = QImage(w, h, QImage.Format.Format_Grayscale8)
                        mask_img.fill(0)
                        p = QPainter(mask_img)
                        p.fillPath(alpha_path, QColor(255))
                        p.end()
                        m_ptr = mask_img.constBits()
                        m_buf = (ctypes.c_uint8 * mask_img.sizeInBytes()).from_address(int(m_ptr))
                        gray_u8 = np.ndarray((h, mask_img.bytesPerLine()), dtype=np.uint8, buffer=m_buf)[:, :w].copy()
                    else:
                        gray_u8 = np.zeros((h, w), dtype=np.uint8)
                else:
                    if current_ch == "R": gray = R
                    elif current_ch == "G": gray = G
                    elif current_ch == "B": gray = B
                    else:
                        C_c = 1.0 - R / 255.0
                        M_c = 1.0 - G / 255.0
                        Y_c = 1.0 - B / 255.0
                        K_c = np.minimum(C_c, np.minimum(M_c, Y_c))
                        
                        if current_ch == "K":
                            gray = K_c * 255.0
                        else:
                            safe_K = np.where(K_c >= 0.999, 1.0, 1.0 - K_c)
                            if current_ch == "C": gray = np.where(K_c >= 0.999, 0.0, (C_c - K_c) / safe_K) * 255.0
                            elif current_ch == "M": gray = np.where(K_c >= 0.999, 0.0, (M_c - K_c) / safe_K) * 255.0
                            elif current_ch == "Y": gray = np.where(K_c >= 0.999, 0.0, (Y_c - K_c) / safe_K) * 255.0
                            
                    gray_u8 = np.clip(gray, 0, 255).astype(np.uint8)
                
                disp_arr = np.empty((h, w, 4), dtype=np.uint8)
                disp_arr[..., 0] = gray_u8
                disp_arr[..., 1] = gray_u8
                disp_arr[..., 2] = gray_u8
                disp_arr[..., 3] = 255 if current_ch.startswith("alpha_") else arr[..., 3]
                
                new_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
                ctypes.memmove(int(new_img.bits()), np.ascontiguousarray(disp_arr).ctypes.data, new_img.sizeInBytes())
                self._display_cache = new_img

        display_img = self._display_cache

        painter.save()
        painter.translate(self._pan)
        painter.scale(self.zoom, self.zoom)
        painter.drawImage(0, 0, display_img)
        painter.restore()

        # Grid overlay
        if getattr(self.document, "show_grid", False):
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.setPen(QPen(QColor(128, 128, 128, 100), max(1.0, 1.0/self.zoom), Qt.PenStyle.DotLine))
            gs = max(5, getattr(self.document, "grid_size", 50))
            for x in range(0, self.document.width, gs): painter.drawLine(QPointF(x, 0), QPointF(x, self.document.height))
            for y in range(0, self.document.height, gs): painter.drawLine(QPointF(0, y), QPointF(self.document.width, y))
            painter.restore()

        # Guides
        if getattr(self.document, "show_guides", False):
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            pw = max(1.0, 1.0 / self.zoom)
            painter.setPen(QPen(QColor(0, 255, 255, 200), pw))
            for gx in getattr(self.document, "guides_v", []): painter.drawLine(QPointF(gx, -10000), QPointF(gx, 10000))
            for gy in getattr(self.document, "guides_h", []): painter.drawLine(QPointF(-10000, gy), QPointF(10000, gy))
                
            if getattr(self, "_dragging_guide", None):
                gtype, val, _ = self._dragging_guide
                painter.setPen(QPen(QColor(0, 255, 255, 255), pw))
                if gtype == 'v':
                    painter.drawLine(QPointF(val, -10000), QPointF(val, 10000))
                else:
                    painter.drawLine(QPointF(-10000, val), QPointF(10000, val))
            painter.restore()

        # Slices
        if getattr(self.document, "show_slices", True):
            slices = getattr(self.document, "slices", [])
            if slices:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                pw = max(1.0, 1.0 / self.zoom)
                painter.setPen(QPen(QColor(0, 150, 255, 200), pw))
                font = painter.font()
                font.setPointSizeF(max(8.0, 10.0 / self.zoom))
                painter.setFont(font)
                for i, r in enumerate(slices):
                    painter.setBrush(QColor(0, 150, 255, 20))
                    painter.drawRect(r)
                    badge_rect = QRectF(r.left(), r.top(), 24 / self.zoom, 16 / self.zoom)
                    painter.fillRect(badge_rect, QColor(0, 150, 255, 200))
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(i+1))
                    painter.setPen(QPen(QColor(0, 150, 255, 200), pw))
                painter.restore()

        if not has_artboards:
            painter.setPen(QPen(QColor(80, 80, 100), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(dr.adjusted(0, 0, -1, -1))

        # Brush mirror symmetry axes
        mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
        mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
        cx_pct = float(self.tool_opts.get("brush_mirror_cx", 0.5))
        cy_pct = float(self.tool_opts.get("brush_mirror_cy", 0.5))
        tool_name = getattr(self.active_tool, "name", "")
        if tool_name in _BRUSH_TOOLS and (mirror_x or mirror_y):
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            pw = max(1.0, 1.0 / self.zoom)
            pen1 = QPen(QColor(0, 0, 0, 100), pw * 3)
            pen2 = QPen(QColor(100, 200, 255, 180), pw)
            pen2.setStyle(Qt.PenStyle.DashLine)
            w, h = self.document.width, self.document.height
            sym_x = w * cx_pct
            sym_y = h * cy_pct
            if mirror_x:
                painter.setPen(pen1); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
                painter.setPen(pen2); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
            if mirror_y:
                painter.setPen(pen1); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
                painter.setPen(pen2); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
                
            r_handle = max(4.0, 6.0 / self.zoom)
            painter.setPen(QPen(QColor(0, 0, 0, 150), max(1.0, 2.0 / self.zoom)))
            painter.setBrush(QColor(100, 200, 255, 200))
            painter.drawEllipse(QPointF(sym_x, sym_y), r_handle, r_handle)
            painter.restore()

        # Marching ants selection outline
        sel = self.document.selection
        in_qm = getattr(self.document, "quick_mask_layer", None) is not None
        if sel and not sel.isEmpty() and not in_qm:
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            pw = max(1.0, 1.0 / self.zoom)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(0, 0, 0, 160), pw * 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(sel)
            pen2 = QPen(QColor(255, 255, 255, 220), pw)
            pen2.setStyle(Qt.PenStyle.DashLine)
            pen2.setDashOffset(4)
            painter.setPen(pen2)
            painter.drawPath(sel)
            painter.restore()

        # Subtract-drag preview
        if self.active_tool and hasattr(self.active_tool, "sub_drag_path"):
            try:
                sub_p = self.active_tool.sub_drag_path()
                if sub_p:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    pw = max(1.0, 1.0 / self.zoom)
                    pen = QPen(QColor(220, 60, 60), pw)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(sub_p)
                    painter.restore()
            except Exception: pass
        elif isinstance(self.active_tool, SelectTool):
            try:
                sub_r = self.active_tool.sub_drag_rect()
                if sub_r:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    pw = max(1.0, 1.0 / self.zoom)
                    pen = QPen(QColor(220, 60, 60), pw)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(sub_r)
                    painter.restore()
            except Exception: pass

        # Lasso preview
        if self.active_tool and hasattr(self.active_tool, "lasso_preview"):
            try:
                preview_data = self.active_tool.lasso_preview()
                if preview_data:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    pw = max(1.0, 1.0 / self.zoom)

                    pen1 = QPen(QColor(0, 0, 0), pw)
                    pen2 = QPen(QColor(255, 255, 255), pw)
                    pen2.setStyle(Qt.PenStyle.DashLine)

                    points = preview_data[0] if isinstance(preview_data, tuple) else preview_data
                    current_pos = preview_data[1] if isinstance(preview_data, tuple) else None

                    if len(points) > 0:
                        poly = QPolygonF(points)
                        painter.setPen(pen1)
                        painter.drawPolyline(poly)
                        painter.setPen(pen2)
                        painter.drawPolyline(poly)

                        if current_pos and getattr(self, "_is_mouse_in", True):
                            painter.setPen(pen1)
                            painter.drawLine(points[-1], current_pos)
                            painter.setPen(pen2)
                            painter.drawLine(points[-1], current_pos)
                    painter.restore()
            except Exception: pass

        # Transform layer preview (Move/Warp)
        if self.active_tool and hasattr(self.active_tool, "floating_preview"):
            try:
                fp = self.active_tool.floating_preview()
                if fp:
                    if len(fp) == 4 and fp[0] == "transform":
                        _, img, tl, transform = fp
                        painter.save()
                        painter.translate(self._pan)
                        painter.scale(self.zoom, self.zoom)
                        painter.setTransform(QTransform().translate(tl.x(), tl.y()) * transform, combine=True)
                        painter.drawImage(0, 0, img)
                        painter.restore()
                    elif len(fp) == 4 and fp[0] == "warp":
                        _, src_img, patches, fast = fp
                        painter.save()
                        painter.translate(self._pan)
                        painter.scale(self.zoom, self.zoom)
                        from tools.warp_tool import WarpTool
                        WarpTool.draw_warp_patches(painter, src_img, patches, fast)
                        painter.restore()
                    else:
                        img, tl = fp
                        painter.save()
                        painter.translate(self._pan)
                        painter.scale(self.zoom, self.zoom)
                        painter.drawImage(tl, img)
                        painter.restore()
            except Exception: pass

        # Brush stroke overlay
        if self.active_tool and hasattr(self.active_tool, "stroke_preview"):
            try:
                sp = self.active_tool.stroke_preview()
                if sp:
                    img, tl, op = sp
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    
                    if hasattr(self.active_tool, "stroke_composition_mode"):
                        painter.setCompositionMode(self.active_tool.stroke_composition_mode(self.tool_opts))
                    
                    painter.setOpacity(max(0.0, min(1.0, float(op))))
                    painter.drawImage(tl, img)
                    painter.restore()
            except Exception: pass

        # Crop preview
        if isinstance(self.active_tool, CropTool) and self.active_tool.pending_rect:
            try:
                cr = self.active_tool.pending_rect
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                
                path = QPainterPath()
                path.addRect(QRectF(0, 0, self.document.width, self.document.height))
                path.addRect(QRectF(cr))
                path.setFillRule(Qt.FillRule.OddEvenFill)
                painter.fillPath(path, QColor(0, 0, 0, 100))
                
                painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / self.zoom)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(cr)
                
                overlay = self.tool_opts.get("crop_overlay", "thirds")
                if overlay != "none":
                    painter.setPen(QPen(QColor(255, 255, 255, 150), max(1.0, 1.0 / self.zoom), Qt.PenStyle.DashLine))
                    w, h = cr.width(), cr.height()
                    if overlay == "thirds":
                        painter.drawLine(QPointF(cr.left(), cr.top() + h/3), QPointF(cr.right(), cr.top() + h/3))
                        painter.drawLine(QPointF(cr.left(), cr.top() + h*2/3), QPointF(cr.right(), cr.top() + h*2/3))
                        painter.drawLine(QPointF(cr.left() + w/3, cr.top()), QPointF(cr.left() + w/3, r.bottom() if hasattr(cr, 'bottom') else cr.top()+h))
                        painter.drawLine(QPointF(cr.left() + w*2/3, cr.top()), QPointF(cr.left() + w*2/3, cr.bottom() if hasattr(cr, 'bottom') else cr.top()+h))
                    elif overlay == "grid":
                        for i in range(1, 5):
                            painter.drawLine(QPointF(cr.left(), cr.top() + h*i/5), QPointF(cr.right(), cr.top() + h*i/5))
                            painter.drawLine(QPointF(cr.left() + w*i/5, cr.top()), QPointF(cr.left() + w*i/5, cr.bottom() if hasattr(cr, 'bottom') else cr.top()+h))
                    elif overlay == "diagonal":
                        painter.drawLine(cr.topLeft(), cr.bottomRight())
                        painter.drawLine(cr.topRight(), cr.bottomLeft())
                        
                painter.setBrush(QColor(255, 255, 255))
                pw = max(1.0, 1.0 / self.zoom)
                painter.setPen(QPen(QColor(0, 0, 0), pw))
                s = 3 * pw
                pts = [cr.topLeft(), QPointF(cr.center().x(), cr.top()), cr.topRight(),
                       QPointF(cr.right(), cr.center().y()), cr.bottomRight(),
                       QPointF(cr.center().x(), cr.bottom()), cr.bottomLeft(),
                       QPointF(cr.left(), cr.center().y())]
                for pt in pts:
                    painter.drawRect(QRectF(pt.x() - s, pt.y() - s, s*2, s*2))
                painter.restore()
            except Exception: pass

        # Perspective crop preview
        if isinstance(self.active_tool, PerspectiveCropTool):
            try:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)

                if self.active_tool.pending_quad:
                    quad = self.active_tool.pending_quad
                    path = QPainterPath()
                    path.addRect(QRectF(0, 0, self.document.width, self.document.height))
                    path.addPolygon(QPolygonF([QPointF(p) for p in quad]))
                    path.setFillRule(Qt.FillRule.OddEvenFill)
                    painter.fillPath(path, QColor(0, 0, 0, 100))

                    painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / self.zoom)))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(quad)
                    
                    overlay = self.tool_opts.get("crop_overlay", "thirds")
                    if overlay != "none" and len(quad) == 4:
                        painter.setPen(QPen(QColor(255, 255, 255, 150), max(1.0, 1.0 / self.zoom), Qt.PenStyle.DashLine))
                        pts = [QPointF(quad[i]) for i in range(4)]
                        p0, p1, p2, p3 = pts[0], pts[1], pts[2], pts[3]
                        def lerp(a, b, t): return a + (b - a) * t
                        
                        if overlay == "thirds":
                            for t in (1/3, 2/3):
                                painter.drawLine(lerp(p0, p3, t), lerp(p1, p2, t))
                                painter.drawLine(lerp(p0, p1, t), lerp(p3, p2, t))
                        elif overlay == "grid":
                            for t in (1/5, 2/5, 3/5, 4/5):
                                painter.drawLine(lerp(p0, p3, t), lerp(p1, p2, t))
                                painter.drawLine(lerp(p0, p1, t), lerp(p3, p2, t))
                        elif overlay == "diagonal":
                            painter.drawLine(p0, p2)
                            painter.drawLine(p1, p3)

                if self.active_tool.points:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    pen = QPen(QColor(255, 255, 255), max(1.0, 1.5 / self.zoom))
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(QColor(255, 255, 255, 180))

                    pts = self.active_tool.points
                    r = max(4.0, 6.0 / self.zoom)
                    for i, p in enumerate(pts):
                        painter.drawEllipse(QPointF(p), r, r)
                        if i > 0 and not self.active_tool.pending_quad:
                            painter.drawLine(pts[i-1], pts[i])
                painter.restore()
            except Exception: pass

        # Shapes preview
        if isinstance(self.active_tool, ShapesTool):
            try:
                ps = self.active_tool.preview_shape()
                if ps:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    stroke = max(1, int(self.tool_opts.get("brush_size", 3)))
                    shape_color = self.tool_opts.get("shape_color", self.fg_color)
                    pen = QPen(shape_color, stroke)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    shape = ps["shape"]
                    rect  = ps["rect"]
                    angle = ps.get("angle", 0)
                    if angle and shape != "line":
                        cx, cy = rect.center().x(), rect.center().y()
                        painter.translate(cx, cy)
                        painter.rotate(angle)
                        painter.translate(-cx, -cy)
                    if shape.startswith("custom:"):
                        custom_path = ShapesTool._load_custom_shape(shape[7:])
                        if custom_path and not custom_path.isEmpty():
                            br = custom_path.boundingRect()
                            if not br.isEmpty():
                                sx = rect.width() / br.width()
                                sy = rect.height() / br.height()
                                painter.save()
                                painter.setTransform(QTransform().translate(rect.left(), rect.top()).scale(sx, sy).translate(-br.left(), -br.top()), combine=True)
                                painter.drawPath(custom_path)
                                painter.restore()
                    elif shape == "ellipse":
                        painter.drawEllipse(rect)
                    elif shape == "triangle":
                        painter.drawPolygon(QPolygon([
                            QPoint(rect.center().x(), rect.top()),
                            QPoint(rect.left(),  rect.bottom()),
                            QPoint(rect.right(), rect.bottom()),
                        ]))
                    elif shape == "polygon":
                        painter.drawPolygon(ShapesTool._polygon_points(rect, ps["sides"]))
                    elif shape == "line":
                        painter.drawLine(ps["start"], ps["end"])
                    elif shape == "star":
                        painter.drawPolygon(ShapesTool._star_points(rect))
                    elif shape == "arrow":
                        painter.drawPath(ShapesTool._arrow_path(rect))
                    elif shape == "cross":
                        painter.drawPath(ShapesTool._cross_path(rect))
                    else:
                        painter.drawRect(rect)
                    painter.restore()
            except Exception: pass

        # Gradient line preview
        if isinstance(self.active_tool, GradientTool):
            try:
                pg = self.active_tool.preview_gradient()
                if pg:
                    p0, p1 = pg
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    pw = max(1.0, 1.0 / self.zoom)
                    pen = QPen(QColor(255, 255, 255, 200), pw * 1.5)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.drawLine(p0, p1)
                    painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
                    painter.setPen(QPen(QColor(0, 0, 0, 160), pw))
                    r = pw * 3
                    painter.drawEllipse(QPointF(p0), r, r)
                    painter.drawEllipse(QPointF(p1), r, r)
                    painter.restore()
            except Exception: pass
                
        if hasattr(self.active_tool, "artboard_preview"):
            try:
                ar = self.active_tool.artboard_preview()
                if ar:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    painter.setPen(QPen(QColor(100, 160, 255), max(1.5, 2.0 / self.zoom)))
                    painter.setBrush(QColor(255, 255, 255, 50))
                    painter.drawRect(ar)
                    painter.restore()
            except Exception: pass

        # Clone stamp source indicator
        crosshair = getattr(self.active_tool, "_crosshair_pos", None)
        if crosshair is not None:
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            pw = max(1.0, 1.0 / self.zoom)
            pen1 = QPen(QColor(0, 0, 0, 180), pw * 3)
            pen2 = QPen(QColor(255, 255, 255, 220), pw)
            r = 6 * pw
            painter.setPen(pen1)
            painter.drawLine(QPointF(crosshair.x() - r, crosshair.y()), QPointF(crosshair.x() + r, crosshair.y()))
            painter.drawLine(QPointF(crosshair.x(), crosshair.y() - r), QPointF(crosshair.x(), crosshair.y() + r))
            painter.setPen(pen2)
            painter.drawLine(QPointF(crosshair.x() - r, crosshair.y()), QPointF(crosshair.x() + r, crosshair.y()))
            painter.drawLine(QPointF(crosshair.x(), crosshair.y() - r), QPointF(crosshair.x(), crosshair.y() + r))
            painter.restore()

        # Measurement tools (Ruler and Color Sampler)
        try:
            from tools.measure_tools import ColorSamplerTool, RulerTool
            if isinstance(self.active_tool, ColorSamplerTool):
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                pw = max(1.0, 1.0 / self.zoom)
                for pt in self.active_tool.markers:
                    painter.setPen(QPen(QColor(0,0,0, 180), pw*3))
                    painter.drawLine(QPointF(pt.x() - 6*pw, pt.y()), QPointF(pt.x() + 6*pw, pt.y()))
                    painter.drawLine(QPointF(pt.x(), pt.y() - 6*pw), QPointF(pt.x(), pt.y() + 6*pw))
                    painter.setPen(QPen(QColor(255,255,255), pw))
                    painter.drawLine(QPointF(pt.x() - 6*pw, pt.y()), QPointF(pt.x() + 6*pw, pt.y()))
                    painter.drawLine(QPointF(pt.x(), pt.y() - 6*pw), QPointF(pt.x(), pt.y() + 6*pw))
                painter.restore()
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                for i, pt in enumerate(self.active_tool.markers):
                    c = QColor(0,0,0,0)
                    if self._composite_cache and 0 <= pt.x() < self._composite_cache.width() and 0 <= pt.y() < self._composite_cache.height():
                        c = QColor(self._composite_cache.pixel(pt))
                    text = f" #{i+1} R:{c.red()} G:{c.green()} B:{c.blue()} "
                    wp = self.to_widget(pt)
                    tr_rect = painter.fontMetrics().boundingRect(text)
                    tr_rect.moveTopLeft(QPoint(int(wp.x()) + 10, int(wp.y()) + 10))
                    tr_rect.adjust(-4, -2, 4, 2)
                    painter.fillRect(tr_rect, QColor(0, 0, 0, 180))
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(tr_rect, Qt.AlignmentFlag.AlignCenter, text)
                painter.restore()
            elif isinstance(self.active_tool, RulerTool):
                lines = self.active_tool.get_lines()
                if lines:
                    painter.save()
                    painter.translate(self._pan); painter.scale(self.zoom, self.zoom)
                    pw = max(1.0, 1.0 / self.zoom)
                    for p1, p2 in lines:
                        painter.setPen(QPen(QColor(0,0,0, 180), pw*3)); painter.drawLine(p1, p2)
                        painter.setPen(QPen(QColor(255,255,255), pw)); painter.drawLine(p1, p2)
                        painter.drawEllipse(QPointF(p1), 3*pw, 3*pw); painter.drawEllipse(QPointF(p2), 3*pw, 3*pw)
                    painter.restore()
                    painter.save()
                    for p1, p2 in lines:
                        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                        if dx == 0 and dy == 0: continue
                        angle = math.degrees(math.atan2(-dy, dx))
                        if angle < 0: angle += 360
                        text = f" L: {math.hypot(dx, dy):.1f} px   A: {angle:.1f}° "
                        wp = self.to_widget(QPoint(int((p1.x()+p2.x())/2), int((p1.y()+p2.y())/2)))
                        tr_rect = painter.fontMetrics().boundingRect(text)
                        tr_rect.moveTopLeft(QPoint(int(wp.x()) + 10, int(wp.y()) + 10))
                        tr_rect.adjust(-4, -2, 4, 2)
                        painter.fillRect(tr_rect, QColor(0, 0, 0, 180))
                        painter.setPen(QColor(255, 255, 255))
                        painter.drawText(tr_rect, Qt.AlignmentFlag.AlignCenter, text)
                    painter.restore()
        except Exception: pass

    def _update_brush_region(self, pos: QPointF):
        mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
        mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
        if mirror_x or mirror_y:
            self._prev_brush_wp = QPointF(pos)
            self.update()
            return

        brush_sz = int(self.tool_opts.get("brush_size", 10))
        w_size   = max(4, int(brush_sz * self.zoom))
        margin   = w_size // 2 + 6

        prv = getattr(self, "_prev_brush_wp", None) or pos
        self._prev_brush_wp = QPointF(pos)

        x1 = int(min(pos.x(), prv.x())) - margin
        y1 = int(min(pos.y(), prv.y())) - margin
        x2 = int(max(pos.x(), prv.x())) + margin
        y2 = int(max(pos.y(), prv.y())) + margin
        self.update(QRect(x1, y1, x2 - x1, y2 - y1))

    def _draw_brush_cursor(self, painter: QPainter):
        try:
            size   = int(self.tool_opts.get("brush_size", 10))
            mask   = self.tool_opts.get("brush_mask", "round")
            hard   = float(self.tool_opts.get("brush_hardness", 1.0))
            angle  = float(self.tool_opts.get("brush_angle", 0.0))

            if getattr(self.active_tool, "name", "") == "BackgroundEraser":
                mask = "round"
                hard = 1.0
                angle = 0.0
                
            mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
            mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
            cx_pct = float(self.tool_opts.get("brush_mirror_cx", 0.5))
            cy_pct = float(self.tool_opts.get("brush_mirror_cy", 0.5))
            doc_pos = self.to_doc(self._mouse_pos)
            w, h = self.document.width, self.document.height
            sym_x = w * cx_pct
            sym_y = h * cy_pct
            
            centers = [(int(self._mouse_pos.x()), int(self._mouse_pos.y()))]
            mirrors = []
            if mirror_x: mirrors.append(QPoint(int(2 * sym_x - doc_pos.x()), doc_pos.y()))
            if mirror_y: mirrors.append(QPoint(doc_pos.x(), int(2 * sym_y - doc_pos.y())))
            if mirror_x and mirror_y: mirrors.append(QPoint(int(2 * sym_x - doc_pos.x()), int(2 * sym_y - doc_pos.y())))
            
            for m in mirrors:
                wp = self.to_widget(m)
                centers.append((int(wp.x()), int(wp.y())))

            alt_pressed = bool(self.tool_opts.get("_alt", False))
            if getattr(self.active_tool, "name", "") == "CloneStamp" and alt_pressed:
                for ctx, cty in centers:
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(QPen(QColor(0,0,0, 180), 3))
                    painter.drawEllipse(QPointF(ctx, cty), 8, 8)
                    painter.setPen(QPen(QColor(255,255,255, 220), 1.5))
                    painter.drawEllipse(QPointF(ctx, cty), 8, 8)
                    painter.drawLine(ctx-12, cty, ctx+12, cty)
                    painter.drawLine(ctx, cty-12, ctx, cty+12)
                    painter.restore()
                return

            actual_mask = mask
            if isinstance(actual_mask, QPixmap):
                actual_mask = actual_mask.toImage()
            elif isinstance(actual_mask, str):
                if actual_mask == "scatter":
                    from tools.brush_tool import _make_brush_stamp
                    actual_mask = _make_brush_stamp(size, hard, "scatter")
                elif actual_mask not in ("round", "square"):
                    tmp = QImage(actual_mask)
                    if not tmp.isNull():
                        actual_mask = tmp

            w_size = max(2, int(size * self.zoom))
            r = w_size / 2.0

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            outer_pen = QPen(QColor(0, 0, 0, 160), 1.5)
            inner_pen = QPen(QColor(255, 255, 255, 200), 1)

            if isinstance(actual_mask, QImage) and not actual_mask.isNull():
                cache_key = (id(mask) if not isinstance(mask, str) else mask, w_size)
                if getattr(self, "_custom_cursor_cache_key", None) == cache_key:
                    path = self._custom_cursor_cache_path
                else:
                    scaled_img = actual_mask.scaled(w_size, w_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    if not scaled_img.hasAlphaChannel():
                        mask_img = scaled_img.createHeuristicMask()
                    else:
                        mask_img = scaled_img.createAlphaMask()
                        
                    bitmap = QBitmap.fromImage(mask_img)
                    region = QRegion(bitmap)
                    path = QPainterPath()
                    path.addRegion(region)
                    path = path.simplified()
                    self._custom_cursor_cache_key = cache_key
                    self._custom_cursor_cache_path = path

                br = path.boundingRect()
                for ctx, cty in centers:
                    c_path = QPainterPath(path)
                    c_path.translate(ctx - br.center().x(), cty - br.center().y())
                    painter.save()
                    if angle != 0.0:
                        painter.translate(ctx, cty)
                        painter.rotate(angle)
                        painter.translate(-ctx, -cty)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(outer_pen)
                    painter.drawPath(c_path)
                    painter.setPen(inner_pen)
                    painter.drawPath(c_path)
                    painter.restore()
            else:
                for ctx, cty in centers:
                    painter.save()
                    if angle != 0.0:
                        painter.translate(ctx, cty)
                        painter.rotate(angle)
                        painter.translate(-ctx, -cty)
                    
                    if hard < 0.8 and actual_mask != "square":
                        grad = QRadialGradient(ctx, cty, r)
                        grad.setColorAt(0,   QColor(255, 255, 255, 80))
                        grad.setColorAt(hard, QColor(255, 255, 255, 40))
                        grad.setColorAt(1,   QColor(255, 255, 255, 0))
                        painter.setBrush(grad)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(QPoint(ctx, cty), int(r), int(r))

                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    if actual_mask == "square":
                        rect = QRect(int(ctx - r), int(cty - r), w_size, w_size)
                        painter.setPen(outer_pen); painter.drawRect(rect.adjusted(1, 1, -1, -1))
                        painter.setPen(inner_pen); painter.drawRect(rect)
                    else:
                        painter.setPen(outer_pen); painter.drawEllipse(QPoint(ctx, cty), int(r) + 1, int(r) + 1)
                        painter.setPen(inner_pen); painter.drawEllipse(QPoint(ctx, cty), int(r), int(r))
                    painter.restore()

            if w_size > 16:
                for ctx, cty in centers:
                    painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
                    painter.drawLine(ctx - 3, cty, ctx + 3, cty)
                    painter.drawLine(ctx, cty - 3, ctx, cty + 3)

            painter.restore()
        except Exception: pass
        
    def _emit_tool_state(self):
        if hasattr(self.active_tool, "get_transform_params"):
            self.tool_state_changed.emit(self.active_tool.get_transform_params())
        else:
            self.tool_state_changed.emit(None)

    def tabletEvent(self, ev):
        self.tool_opts["_pressure"] = ev.pressure()
        ev.ignore()

    def mousePressEvent(self, ev):
        """Handles mouse press with error isolation for tool initialization."""
        if not self.document:
            return
            
        try:
            if getattr(self, "show_rulers", False):
                R = 20
                pos = ev.position()
                if pos.x() < R and pos.y() > R:
                    self._dragging_guide = ('v', self.to_doc(pos).x(), None)
                    self.setCursor(Qt.CursorShape.SplitHCursor)
                    return
                elif pos.y() < R and pos.x() > R:
                    self._dragging_guide = ('h', self.to_doc(pos).y(), None)
                    self.setCursor(Qt.CursorShape.SplitVCursor)
                    return

            if getattr(self.active_tool, "name", "") == "Move" and not self._space:
                doc_pos = self.to_doc(ev.position())
                snap = 5 / max(0.01, self.zoom)
                hit_v, hit_h = None, None
                if getattr(self.document, "show_guides", False):
                    for i, gx in enumerate(getattr(self.document, "guides_v", [])):
                        if abs(gx - doc_pos.x()) < snap: hit_v = (i, gx)
                    for i, gy in enumerate(getattr(self.document, "guides_h", [])):
                        if abs(gy - doc_pos.y()) < snap: hit_h = (i, gy)
                if hit_v:
                    self._dragging_guide = ('v', hit_v[1], hit_v[0])
                    if hasattr(self.document, "guides_v"): self.document.guides_v.pop(hit_v[0])
                    self.setCursor(Qt.CursorShape.SplitHCursor)
                    self.update()
                    return
                elif hit_h:
                    self._dragging_guide = ('h', hit_h[1], hit_h[0])
                    if hasattr(self.document, "guides_h"): self.document.guides_h.pop(hit_h[0])
                    self.setCursor(Qt.CursorShape.SplitVCursor)
                    self.update()
                    return

            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
            self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)
            self.tool_opts["_zoom"]  = self.zoom

            is_pan = (ev.button() == Qt.MouseButton.MiddleButton or (self._space and ev.button() == Qt.MouseButton.LeftButton))
            if is_pan:
                self._panning = True
                self._pan_last = ev.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

            if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
                self.tool_opts["_pressure"] = 1.0

            if ev.button() == Qt.MouseButton.LeftButton:
                if isinstance(self.active_tool, HandTool):
                    self._panning = True
                    self._pan_last = ev.position()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return
                if isinstance(self.active_tool, ZoomTool):
                    alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
                    self._apply_zoom(1 / 1.25 if alt else 1.25, ev.position())
                    return
                if isinstance(self.active_tool, RotateViewTool):
                    self._rotating = True
                    cx = self.width()  / 2
                    cy = self.height() / 2
                    self._rotate_last_angle = math.degrees(math.atan2(ev.position().y() - cy, ev.position().x() - cx))
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return

            if ev.button() == Qt.MouseButton.LeftButton and self.active_tool:
                tool_name = getattr(self.active_tool, "name", "")
                layer = self.document.get_active_layer() if self.document else None
                
                if layer:
                    ltype = getattr(layer, "layer_type", "raster")
                    if ltype in ("text", "smart_object"):
                        forbidden = {"Brush", "Eraser", "BackgroundEraser", "MagicEraser", "CloneStamp", "PatternStamp",
                                     "Pencil", "ColorReplacement", "MixerBrush", "HistoryBrush",
                                     "Fill", "Blur", "Sharpen", "Smudge", "Dodge", "Burn", "Sponge",
                                     "Gradient", "Patch", "SpotHealing", "HealingBrush", "RedEye"}
                        if ltype == "text":
                            forbidden.update({"Warp", "PuppetWarp", "PerspectiveWarp"})
                            
                        if tool_name in forbidden:
                            if hasattr(self.window(), "_status"):
                                from core.locale import tr
                                msg = tr("err.smart_object_no_draw") if ltype == "smart_object" else tr("err.text_layer_no_draw")
                                self.window()._status.showMessage(msg, 3000)
                            return

                if tool_name in _BRUSH_TOOLS:
                    mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
                    mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
                    if mirror_x or mirror_y:
                        doc_pos = self.to_doc(ev.position())
                        ctrl_pressed = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
                        
                        if ctrl_pressed:
                            self._dragging_sym_center = True
                            new_cx = max(0.0, min(1.0, doc_pos.x() / max(1, self.document.width)))
                            new_cy = max(0.0, min(1.0, doc_pos.y() / max(1, self.document.height)))
                            self.tool_opts["brush_mirror_cx"] = new_cx
                            self.tool_opts["brush_mirror_cy"] = new_cy
                            self.tool_state_changed.emit({"brush_mirror_cx": new_cx, "brush_mirror_cy": new_cy})
                            self.update()
                            return

                        sym_x = self.document.width * float(self.tool_opts.get("brush_mirror_cx", 0.5))
                        sym_y = self.document.height * float(self.tool_opts.get("brush_mirror_cy", 0.5))
                        if math.hypot(doc_pos.x() - sym_x, doc_pos.y() - sym_y) <= 15 / max(0.01, self.zoom):
                            self._dragging_sym_center = True
                            return

                self._stroke_in_progress = True

                if self.active_tool.needs_history_push():
                    from core.history import HistoryState, clone_work_path
                    self._pre_stroke_state = HistoryState(
                        description=self.active_tool.name,
                        layers_snapshot=self.document.snapshot_layers(),
                        active_layer_index=self.document.active_layer_index,
                        doc_width=self.document.width,
                        doc_height=self.document.height,
                        selection_snapshot=QPainterPath(self.document.selection) if self.document.selection else None,
                        work_path_snapshot=clone_work_path(getattr(self.document, "work_path", None)),
                        alpha_channels_snapshot=list(getattr(self.document, "alpha_channels", [])),
                        color_mode_snapshot=getattr(self.document, "color_mode", "RGB"),
                        bit_depth_snapshot=getattr(self.document, "bit_depth", 8)
                    )

                old_layer_idx = self.document.active_layer_index if self.document else -1
                doc_pos = self.to_doc(ev.position())

                if getattr(self.active_tool, "needs_background_composite", False):
                    self._start_effect_stroke()

                # Safe tool press handler
                try:
                    self.active_tool.on_press(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                except Exception as tool_ex:
                    print(f"[CanvasWidget] on_press error in {tool_name}:\n{traceback.format_exc()}")
                    if hasattr(self.window(), "_status"):
                        self.window()._status.showMessage(f"Tool {tool_name}: operation failed", 4000)
                    self._stroke_in_progress = False
                    self._pre_stroke_state = None

                self._cache_dirty = True
                self.update()

                if getattr(self.active_tool, "needs_immediate_commit", False) and self._stroke_in_progress:
                    self._stroke_in_progress = False
                    self.document_changed.emit()
                elif self.document and self.document.active_layer_index != old_layer_idx:
                    self.document_changed.emit()
                    
            self._emit_tool_state()
        except Exception as global_ex:
            print(f"[CanvasWidget] Critical mouse press error: {traceback.format_exc()}")
            self._stroke_in_progress = False

    def mouseMoveEvent(self, ev):
        """Handles mouse move for brush strokes and deformations."""
        try:
            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
            self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)
            self.tool_opts["_zoom"]  = self.zoom
            
            if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
                self.tool_opts["_pressure"] = 1.0

            self._mouse_pos = ev.position()

            if self._stroke_in_progress and not (ev.buttons() & Qt.MouseButton.LeftButton):
                doc_pos = self.to_doc(ev.position())
                if self.active_tool:
                    try: self.active_tool.on_release(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception: pass
                self._stroke_in_progress = False
                self._prev_brush_wp = None
                if self._in_effect_stroke and self.active_tool and hasattr(self.active_tool, "_stroke_preview_active"):
                    self.active_tool._stroke_preview_active = False
                self._in_effect_stroke = False
                self._effect_bg_cache = None
                self._cache_dirty = True
                self.update()
                self.document_changed.emit()

            if getattr(self, "_dragging_sym_center", False):
                doc_pos = self.to_doc(ev.position())
                new_cx = max(0.0, min(1.0, doc_pos.x() / max(1, self.document.width)))
                new_cy = max(0.0, min(1.0, doc_pos.y() / max(1, self.document.height)))
                self.tool_opts["brush_mirror_cx"] = new_cx
                self.tool_opts["brush_mirror_cy"] = new_cy
                self.tool_state_changed.emit({"brush_mirror_cx": new_cx, "brush_mirror_cy": new_cy})
                self.update()
                return

            if getattr(self, "_dragging_guide", None) is not None:
                doc_pos = self.to_doc(ev.position())
                gtype, _, orig_idx = self._dragging_guide
                self._dragging_guide = (gtype, doc_pos.x() if gtype == 'v' else doc_pos.y(), orig_idx)
                self.update()
                return

            if self._panning and self._pan_last is not None:
                delta = ev.position() - self._pan_last
                self._pan += delta
                self._pan_last = ev.position()
                self.update()
                return

            if self._rotating:
                cx = self.width()  / 2
                cy = self.height() / 2
                curr = math.degrees(math.atan2(ev.position().y() - cy, ev.position().x() - cx))
                delta = curr - self._rotate_last_angle
                if delta >  180: delta -= 360
                if delta < -180: delta += 360
                self._view_rotation += delta
                self._rotate_last_angle = curr
                self.update()
                return

            if self._show_brush_cursor:
                self._update_brush_region(ev.position())
            elif isinstance(self.active_tool, (SelectTool, ShapesTool, RotateViewTool, GradientTool)) or (
                    self.active_tool and hasattr(self.active_tool, "sub_drag_path")):
                self.update()

            if (ev.buttons() & Qt.MouseButton.LeftButton and self._stroke_in_progress and self.active_tool):
                doc_pos = self.to_doc(ev.position())
                
                # Safe tool move handler
                try:
                    self.active_tool.on_move(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                except Exception as move_ex:
                    print(f"[CanvasWidget] on_move error in {getattr(self.active_tool, 'name', '')}:\n{traceback.format_exc()}")
                    if hasattr(self.window(), "_status"):
                        self.window()._status.showMessage("Tool move step failed", 1000)

                if getattr(self.active_tool, "modifies_canvas_on_move", False):
                    is_brush_preview = (
                        self._stroke_in_progress and
                        hasattr(self.active_tool, "stroke_preview") and
                        not getattr(self.active_tool, "needs_background_composite", False) and
                        not getattr(self.active_tool, "needs_composite_refresh", False)
                    )
                    is_effect_optimized = self._stroke_in_progress and self._in_effect_stroke
                    if not is_brush_preview and not is_effect_optimized:
                        self._cache_dirty = True

                if self._stroke_in_progress and hasattr(self.active_tool, "stroke_preview"):
                    self._update_brush_region(ev.position())
                else:
                    self.update()
                self.pixels_changed.emit()
                
                self._move_counter = getattr(self, "_move_counter", 0) + 1
            else:
                if self.active_tool and hasattr(self.active_tool, "on_hover"):
                    try:
                        doc_pos = self.to_doc(ev.position())
                        self.active_tool.on_hover(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception: pass
                    self._update_cursor()
            self._emit_tool_state()

            if self.document:
                dp = self.to_doc(ev.position())
                cx, cy = dp.x(), dp.y()
                if 0 <= cx < self.document.width and 0 <= cy < self.document.height:
                    layer = self.document.get_active_layer()
                    if layer and 0 <= cx < layer.image.width() and 0 <= cy < layer.image.height():
                        color = QColor(layer.image.pixel(cx, cy))
                    else:
                        color = QColor(0, 0, 0, 0)
                    self.cursor_info.emit(cx, cy, color)
        except Exception as global_move_ex:
            print(f"[CanvasWidget] Critical mouse move error: {global_move_ex}")

    def mouseReleaseEvent(self, ev):
        """Handles mouse release to finalize strokes."""
        try:
            if getattr(self, "_dragging_sym_center", False) and ev.button() == Qt.MouseButton.LeftButton:
                self._dragging_sym_center = False
                self._update_cursor()
                return
                
            if getattr(self, "_dragging_guide", None) is not None:
                gtype, val, _ = self._dragging_guide
                wx, wy = self.to_widget(QPoint(int(val), 0)).x(), self.to_widget(QPoint(0, int(val))).y()
                R = 20 if self.show_rulers else 0
                if gtype == 'v' and wx > R:
                    if not hasattr(self.document, "guides_v"): self.document.guides_v = []
                    self.document.guides_v.append(val)
                elif gtype == 'h' and wy > R:
                    if not hasattr(self.document, "guides_h"): self.document.guides_h = []
                    self.document.guides_h.append(val)
                self._dragging_guide = None
                self._update_cursor()
                self.update()
                return
                
            if ev.button() == Qt.MouseButton.MiddleButton or (self._panning and ev.button() == Qt.MouseButton.LeftButton):
                self._panning = False
                self._pan_last = None
                self._update_cursor()
                return

            if self._rotating and ev.button() == Qt.MouseButton.LeftButton:
                self._rotating = False
                self._update_cursor()
                return

            if ev.button() == Qt.MouseButton.LeftButton and self._stroke_in_progress:
                doc_pos = self.to_doc(ev.position())
                tool_name = getattr(self.active_tool, "name", "")
                
                # Safe tool release handler
                if self.active_tool:
                    try:
                        self.active_tool.on_release(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception as rel_ex:
                        print(f"[CanvasWidget] on_release error in {tool_name}:\n{traceback.format_exc()}")
                        if hasattr(self.window(), "_status"):
                            self.window()._status.showMessage("Tool release failed", 4000)

                self._stroke_in_progress = False
                self._prev_brush_wp = None
                if self._in_effect_stroke and self.active_tool and hasattr(self.active_tool, "_stroke_preview_active"):
                    self.active_tool._stroke_preview_active = False
                self._in_effect_stroke = False
                self._effect_bg_cache = None
                self._cache_dirty = True
                self.update()
                self.document_changed.emit()
            self._emit_tool_state()
        except Exception as global_release_ex:
            print(f"[CanvasWidget] Critical mouse release error: {global_release_ex}")
            self._stroke_in_progress = False

    def enterEvent(self, ev):
        self._is_mouse_in = True
        self._update_cursor()

    def leaveEvent(self, ev):
        try:
            self._is_mouse_in = False
            self._show_brush_cursor = False
            if self.active_tool and hasattr(self.active_tool, "on_leave"):
                self.active_tool.on_leave()
            if self.active_tool:
                for attr in ["_hover_pos", "_current_mouse_pos", "_mouse_pos", "hover_pos", "current_pos", "_current_pos", "_preview_end", "preview_end", "_last_pos"]:
                    if hasattr(self.active_tool, attr):
                        setattr(self.active_tool, attr, None)
            self.update()
        except Exception: pass

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self._apply_zoom(factor, ev.position())
        else:
            super().wheelEvent(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Control: self.tool_opts["_ctrl"] = True
        if k == Qt.Key.Key_Shift: self.tool_opts["_shift"] = True
        if k == Qt.Key.Key_Alt: self.tool_opts["_alt"] = True
        
        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self._update_cursor()
        elif k == Qt.Key.Key_Plus or k == Qt.Key.Key_Equal:
            self.zoom_in()
        elif k == Qt.Key.Key_Minus:
            self.zoom_out()
        elif k == Qt.Key.Key_0:
            self.reset_zoom()
        elif k == Qt.Key.Key_BracketLeft:
            new_size = max(1, self.tool_opts.get("brush_size", 10) - 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        elif k == Qt.Key.Key_BracketRight:
            new_size = min(500, self.tool_opts.get("brush_size", 10) + 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        elif k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            self._update_cursor()
            super().keyPressEvent(ev)
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Control: self.tool_opts["_ctrl"] = False
        if k == Qt.Key.Key_Shift: self.tool_opts["_shift"] = False
        if k == Qt.Key.Key_Alt: self.tool_opts["_alt"] = False
        
        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self._update_cursor()
        elif k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            self._update_cursor()
            super().keyReleaseEvent(ev)
        else:
            super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pan == QPointF(0, 0):
            self._fit_to_window()

    def _update_cursor(self):
        try:
            if getattr(self, "_panning", False) or getattr(self, "_space", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor if getattr(self, "_panning", False) else Qt.CursorShape.OpenHandCursor)
                return
                
            if getattr(self, "_rotating", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
                
            if getattr(self, "_dragging_sym_center", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.CrossCursor)
                return

            tool_name = getattr(self.active_tool, "name", "") if self.active_tool else ""
            if tool_name in _BRUSH_TOOLS:
                mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
                mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
                is_hovering_sym = False
                ctrl_pressed = bool(self.tool_opts.get("_ctrl", False))
                
                if (mirror_x or mirror_y) and self.document:
                    if ctrl_pressed:
                        self._show_brush_cursor = False
                        self.setCursor(Qt.CursorShape.CrossCursor)
                        return

                    cx_pct = float(self.tool_opts.get("brush_mirror_cx", 0.5))
                    cy_pct = float(self.tool_opts.get("brush_mirror_cy", 0.5))
                    sym_x = self.document.width * cx_pct
                    sym_y = self.document.height * cy_pct
                    doc_pos = self.to_doc(self._mouse_pos)
                    hit_radius = 15 / max(0.01, self.zoom)
                    if math.hypot(doc_pos.x() - sym_x, doc_pos.y() - sym_y) <= hit_radius:
                        is_hovering_sym = True
                if is_hovering_sym:
                    self._show_brush_cursor = False
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self._show_brush_cursor = True
                    self.setCursor(Qt.CursorShape.BlankCursor)
            elif tool_name in _SELECTION_TOOLS:
                self._show_brush_cursor = False
                ctrl = bool(self.tool_opts.get("_ctrl", False))
                alt  = bool(self.tool_opts.get("_alt",  False))
                if ctrl and alt: mode = "intersect"
                elif ctrl: mode = "add"
                elif alt: mode = "sub"
                else: mode = "new"
                self.setCursor(_make_sel_cursor(mode))
            else:
                self._show_brush_cursor = False
                if self.active_tool:
                    self.setCursor(QCursor(self.active_tool.cursor()))
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            self.setCursor(Qt.CursorShape.ArrowCursor)