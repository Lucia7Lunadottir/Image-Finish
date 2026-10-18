import math
import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from tools.transform_base import MeshWarpTool


class WarpTool(MeshWarpTool):
    """Bezier-surface warp: a 4×4 grid of control points over the content."""
    name = "Warp"
    icon = "🕸️"
    shortcut = "V"
    AUTO_SELECT = True

    def _clear_tool_state(self):
        super()._clear_tool_state()
        self._pts = []   # 4×4 rows of QPointF

    def _get_handle_hit(self, pos: QPointF, zoom: float):
        hit_dist = 8 / max(0.01, zoom)
        best_dist, best_idx = float('inf'), None
        for r in range(len(self._pts)):
            for c in range(4):
                pt = self._pts[r][c]
                d = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                if d < best_dist and d <= hit_dist:
                    best_dist, best_idx = d, (r, c)
        return best_idx

    def on_press(self, pos, doc, fg, bg, opts):
        self._auto_select(pos, doc, opts)
        layer = doc.get_active_layer()
        if not self._can_transform(layer, doc):
            return
        if not self.is_transforming:
            if not self._begin(layer, doc):
                return
            b = self._bounds
            self._pts = [[QPointF(b.left() + b.width() * c / 3.0, b.top() + b.height() * r / 3.0)
                          for c in range(4)] for r in range(4)]
            self._update_preview()
        self._drag_idx = self._get_handle_hit(QPointF(pos), opts.get("_zoom", 1.0))

    def _calc_grid(self, steps_u, steps_v):
        """Vectorized Bezier surface computation via NumPy matrix multiplication."""
        u = np.linspace(0, 1, steps_u)
        v = np.linspace(0, 1, steps_v)
        bu = np.array([(1-u)**3, 3*u*(1-u)**2, 3*u**2*(1-u), u**3])
        bv = np.array([(1-v)**3, 3*v*(1-v)**2, 3*v**2*(1-v), v**3])
        pts_x = np.array([[self._pts[r][c].x() for c in range(4)] for r in range(4)])
        pts_y = np.array([[self._pts[r][c].y() for c in range(4)] for r in range(4)])
        return bv.T @ pts_x @ bu, bv.T @ pts_y @ bu

    def on_move(self, pos, doc, fg, bg, opts):
        if not self.is_transforming or self._drag_idx is None: return
        r, c = self._drag_idx
        self._pts[r][c] = QPointF(pos)
        self._update_preview(fast=True)

    def draw_overlays(self, painter: QPainter, pw: float, doc):
        if not self.is_transforming or not self._pts: return

        xs_h, ys_h = self._calc_grid(21, 4)
        xs_v, ys_v = self._calc_grid(4, 21)

        polys_h = [QPolygonF([QPointF(xs_h[i, j], ys_h[i, j]) for j in range(21)]) for i in range(4)]
        polys_v = [QPolygonF([QPointF(xs_v[i, j], ys_v[i, j]) for i in range(21)]) for j in range(4)]

        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, 180), pw * 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        for poly in polys_h + polys_v: painter.drawPolyline(poly)

        painter.setPen(QPen(QColor(0, 0, 0, 150), pw))
        for poly in polys_h + polys_v: painter.drawPolyline(poly)

        painter.setPen(QPen(QColor(100, 100, 100, 150), pw))
        for r in range(4):
            for c in range(3): painter.drawLine(self._pts[r][c], self._pts[r][c+1])
        for c in range(4):
            for r in range(3): painter.drawLine(self._pts[r][c], self._pts[r+1][c])

        painter.setPen(QPen(QColor(0, 0, 0), pw)); painter.setBrush(QColor(255, 255, 255))
        s = 3 * pw
        for r in range(4):
            for c in range(4): painter.drawEllipse(self._pts[r][c], s, s)
        painter.restore()
