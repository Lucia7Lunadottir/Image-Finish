import math
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QTransform, QPen, QPolygonF
from tools.transform_base import TransformTool, bake_transform


class PerspectiveWarpTool(TransformTool):
    """Four clicks lay a quad over the content; dragging its corners maps
    the content through the projective transform between the two quads."""
    name = "PerspectiveWarp"
    icon = "🗺️"
    shortcut = "W"

    def _clear_tool_state(self):
        self._src_poly = []
        self._dst_poly = []
        self._drag_idx = None
        self._local_transform = QTransform()

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not self._can_transform(layer, doc):
            return
        if not self.is_transforming and not self._begin(layer, doc):
            return

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

    def _bake(self, doc, layer):
        img, offset = bake_transform(self._original_img, self._original_offset, self._local_transform)
        self._place(layer, img, offset)

    def cursor(self): return Qt.CursorShape.CrossCursor
