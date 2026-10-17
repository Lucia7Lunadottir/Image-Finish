import math
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QImage, QTransform, QPen, QPolygonF
from tools.base_tool import BaseTool
from core.document import Document

class PerspectiveWarpTool(BaseTool):
    PIXEL_OP = "transform"
    name = "PerspectiveWarp"
    icon = "🗺️"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self.is_transforming = False
        self._target_layer = None
        self._layer_backup = None
        self._offset_backup = None
        self._original_img = None
        self._original_offset = None
        self._sel_origin = None
        self._is_floating = False

        self._src_poly = []
        self._dst_poly = []
        self._drag_idx = None
        self._local_transform = QTransform()

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked: return
        if layer._is_container: return

        if not self.is_transforming:
            self.is_transforming = True
            self._target_layer = layer
            self._layer_backup = layer.image.copy()
            self._offset_backup = QPoint(layer.offset)

            sel = doc.selection
            if sel and not sel.isEmpty():
                from tools.tool_utils import cut_floating_selection
                self._is_floating = True

                original_img, original_offset, sel_origin, ok = cut_floating_selection(layer, sel)
                if not ok:
                    self.is_transforming = False; return
                self._original_img = original_img
                self._original_offset = original_offset
                self._sel_origin = sel_origin
            else:
                self._is_floating = False
                br = Document._nontransparent_bounds(layer.image)
                if br.isEmpty(): br = QRect(0, 0, layer.width() or 100, layer.height() or 100)
                self._original_img = layer.image.copy(br)
                self._original_offset = layer.offset + br.topLeft()
                self._sel_origin = None
                layer.image = QImage(1, 1, QImage.Format.Format_ARGB32)
                layer.image.fill(Qt.GlobalColor.transparent)

        if len(self._src_poly) < 4:
            self._src_poly.append(QPointF(pos))
            if len(self._src_poly) == 4:
                self._dst_poly = [QPointF(p) for p in self._src_poly]
                self._update_transform()
        else:
            hit_dist = 10 / max(0.01, opts.get("_zoom", 1.0))
            self._drag_idx = None
            for i, p in enumerate(self._dst_poly):
                if math.hypot(pos.x() - p.x(), pos.y() - p.y()) < hit_dist:
                    self._drag_idx = i
                    break

    def on_move(self, pos, doc, fg, bg, opts):
        if self.is_transforming and len(self._dst_poly) == 4 and self._drag_idx is not None:
            self._dst_poly[self._drag_idx] = QPointF(pos)
            self._update_transform()

    def on_release(self, pos, doc, fg, bg, opts): 
        self._drag_idx = None

    def _update_transform(self):
        t = QTransform()
        if QTransform.quadToQuad(QPolygonF(self._src_poly), QPolygonF(self._dst_poly), t):
            ox, oy = self._original_offset.x(), self._original_offset.y()
            self._local_transform = QTransform().translate(ox, oy) * t * QTransform().translate(-ox, -oy)

    def floating_preview(self):
        if self.is_transforming and self._original_img and len(self._src_poly) == 4: 
            return ("transform", self._original_img, self._original_offset, self._local_transform)
        return None

    def draw_overlays(self, painter: QPainter, pw: float, doc):
        if not self.is_transforming: return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if len(self._src_poly) < 4:
            painter.setPen(QPen(QColor(255, 255, 255), max(1.0, pw*1.5), Qt.PenStyle.DashLine))
            for i, p in enumerate(self._src_poly):
                painter.drawEllipse(p, 4*pw, 4*pw)
                if i > 0: painter.drawLine(self._src_poly[i-1], p)
        else:
            painter.setPen(QPen(QColor(0, 0, 0, 180), pw)); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(QPolygonF(self._dst_poly))
            painter.setPen(QPen(QColor(255, 255, 255, 200), pw, Qt.PenStyle.DashLine))
            painter.drawPolygon(QPolygonF(self._dst_poly))
            painter.setPen(QPen(QColor(0,0,0), pw)); painter.setBrush(QColor(255,255,255))
            for p in self._dst_poly:
                painter.drawRect(QRectF(p.x() - 3*pw, p.y() - 3*pw, 6*pw, 6*pw))
        painter.restore()

    def apply_transform(self, doc):
        if not self.is_transforming: return
        from tools.move_tool import MoveTool
        # Borrow the final bake logic from MoveTool for QTransform
        mt = MoveTool()
        mt.is_transforming, mt._target_layer, mt._original_img = True, self._target_layer, self._original_img
        mt._original_offset, mt._total_transform = self._original_offset, self._local_transform
        mt._is_floating = self._is_floating
        mt.apply_transform(doc)
        self._reset_state()

    def cancel_transform(self, doc):
        if self._layer_backup is not None and getattr(self, "_target_layer", None):
            self._target_layer.image = self._layer_backup
            self._target_layer.offset = self._offset_backup
            if self._sel_origin: doc.selection = self._sel_origin
        self._reset_state()

    def _reset_state(self):
        self.is_transforming = False
        self._target_layer = self._layer_backup = self._original_img = None
        self._src_poly = []; self._dst_poly = []

    def needs_history_push(self): return False
    def cursor(self): return Qt.CursorShape.CrossCursor