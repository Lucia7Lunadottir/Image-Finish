import math
import numpy as np
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QPainter, QPen
from tools.transform_base import MeshWarpTool


class PuppetWarpTool(MeshWarpTool):
    """Pins: click adds one, drag moves it, Alt+click removes it; the mesh
    follows the pins by inverse-distance weighting."""
    name = "PuppetWarp"
    icon = "📌"
    shortcut = "W"

    def _clear_tool_state(self):
        super()._clear_tool_state()
        self._pins = []   # [{'orig': QPointF, 'curr': QPointF}]

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not self._can_transform(layer, doc):
            return
        if not self.is_transforming:
            if not self._begin(layer, doc):
                return
            self._update_preview()

        hit_dist = 10 / max(0.01, opts.get("_zoom", 1.0))
        self._drag_idx = None
        for i, pin in enumerate(self._pins):
            if math.hypot(pos.x() - pin['curr'].x(), pos.y() - pin['curr'].y()) < hit_dist:
                self._drag_idx = i
                break

        if self._drag_idx is not None:
            if opts.get("_alt", False):
                self._pins.pop(self._drag_idx)
                self._drag_idx = None
                self._update_preview()
        else:
            self._pins.append({'orig': QPointF(pos), 'curr': QPointF(pos)})
            self._drag_idx = len(self._pins) - 1
            self._update_preview()

    def _calc_grid(self, steps_u, steps_v):
        x0, y0 = self._bounds.left(), self._bounds.top()
        w, h = self._bounds.width(), self._bounds.height()
        uu, vv = np.meshgrid(np.linspace(0, 1, steps_u), np.linspace(0, 1, steps_v))
        grid_x = x0 + uu * w
        grid_y = y0 + vv * h

        if not self._pins: return grid_x, grid_y
        if len(self._pins) == 1:
            dx = self._pins[0]['curr'].x() - self._pins[0]['orig'].x()
            dy = self._pins[0]['curr'].y() - self._pins[0]['orig'].y()
            return grid_x + dx, grid_y + dy

        P = np.array([[p['orig'].x(), p['orig'].y()] for p in self._pins])
        Q = np.array([[p['curr'].x(), p['curr'].y()] for p in self._pins])
        D = Q - P

        dx = grid_x[..., None] - P[:, 0]
        dy = grid_y[..., None] - P[:, 1]
        dist_sq = np.maximum(dx**2 + dy**2, 1e-5)
        w_dist = 1.0 / (dist_sq ** 2) # Inverse distance power 4
        w_norm = w_dist / np.sum(w_dist, axis=-1, keepdims=True)

        disp_x = np.sum(w_norm * D[:, 0], axis=-1)
        disp_y = np.sum(w_norm * D[:, 1], axis=-1)

        return grid_x + disp_x, grid_y + disp_y

    def on_move(self, pos, doc, fg, bg, opts):
        if not self.is_transforming or self._drag_idx is None: return
        self._pins[self._drag_idx]['curr'] = QPointF(pos)
        self._update_preview(fast=True)

    def draw_overlays(self, painter: QPainter, pw: float, doc):
        if not self.is_transforming: return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, pin in enumerate(self._pins):
            painter.setPen(QPen(QColor(0, 0, 0, 180), pw * 2))
            painter.setBrush(QColor(255, 255, 255) if i != self._drag_idx else QColor(200, 200, 255))
            painter.drawEllipse(pin['curr'], 5*pw, 5*pw)
        painter.restore()
