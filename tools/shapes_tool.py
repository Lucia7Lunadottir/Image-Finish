import math
import random

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QPainter, QPen, QBrush, QPolygon, QPainterPath, QTransform, QColor
from tools.base_tool import BaseTool

from core.app_logging import get_logger

logger = get_logger("shapes_tool")


class ShapesTool(BaseTool):
    """Vector shape layers store their geometry in `layer.shape_data` and
    are re-rendered from it (via `_bake_shape`) rather than being fixed
    pixels from the moment they're drawn.

    This tool only handles drawing a brand-new shape by dragging on empty
    canvas. Once a shape layer exists, resizing/moving it is owned by a
    real scene object — see `ui/shape_scene_overlay.py::ShapeLayerItem` —
    not by hit-testing raw mouse coordinates against a stored rect here."""

    name = "Shapes"
    icon = "🔷"
    shortcut = "U"

    def __init__(self):
        self._start:       QPoint | None = None
        self._preview_end: QPoint | None = None
        self._shape_type:  str           = "rect"
        self._shift:       bool          = False
        self._sides:       int           = 6
        self._angle:       int           = 0

    # ── Geometry helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _constrain(start: QPoint, end: QPoint) -> QPoint:
        """Constrain end so the bounding box is square."""
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        side = min(abs(dx), abs(dy))
        return QPoint(
            start.x() + (side if dx >= 0 else -side),
            start.y() + (side if dy >= 0 else -side),
        )

    @staticmethod
    def _polygon_points(rect: QRect, sides: int) -> QPolygon:
        """Regular N-gon inscribed in the bounding ellipse of rect."""
        cx = rect.center().x()
        cy = rect.center().y()
        rx = rect.width()  / 2
        ry = rect.height() / 2
        pts = []
        for i in range(sides):
            a = -math.pi / 2 + 2 * math.pi * i / sides
            pts.append(QPoint(int(cx + rx * math.cos(a)),
                              int(cy + ry * math.sin(a))))
        return QPolygon(pts)

    @staticmethod
    def _star_points(rect: QRect, points: int = 5, inner: float = 0.4) -> QPolygon:
        """Star polygon with `points` tips, inner radius = outer * inner."""
        cx = rect.center().x()
        cy = rect.center().y()
        rx = rect.width()  / 2
        ry = rect.height() / 2
        pts = []
        for i in range(points * 2):
            a = -math.pi / 2 + math.pi * i / points
            r = 1.0 if i % 2 == 0 else inner
            pts.append(QPoint(int(cx + rx * r * math.cos(a)),
                              int(cy + ry * r * math.sin(a))))
        return QPolygon(pts)

    @staticmethod
    def _arrow_path(rect: QRect) -> QPainterPath:
        """Right-pointing arrow fitting the bounding rect."""
        l, t = rect.left(), rect.top()
        r, b = rect.right(), rect.bottom()
        w, h = rect.width(), rect.height()
        shaft_x = l + w * 0.60
        shaft_t = t + h * 0.35
        shaft_b = b - h * 0.35
        path = QPainterPath()
        path.moveTo(l, shaft_t)
        path.lineTo(shaft_x, shaft_t)
        path.lineTo(shaft_x, t)
        path.lineTo(r, t + h / 2)
        path.lineTo(shaft_x, b)
        path.lineTo(shaft_x, shaft_b)
        path.lineTo(l, shaft_b)
        path.closeSubpath()
        return path

    @staticmethod
    def _cross_path(rect: QRect) -> QPainterPath:
        """Plus/cross shape fitting the bounding rect."""
        l, t = rect.left(), rect.top()
        r, b = rect.right(), rect.bottom()
        w, h = rect.width(), rect.height()
        cx1, cx2 = l + w / 3, r - w / 3
        cy1, cy2 = t + h / 3, b - h / 3
        path = QPainterPath()
        path.moveTo(cx1, t)
        path.lineTo(cx2, t)
        path.lineTo(cx2, cy1)
        path.lineTo(r,   cy1)
        path.lineTo(r,   cy2)
        path.lineTo(cx2, cy2)
        path.lineTo(cx2, b)
        path.lineTo(cx1, b)
        path.lineTo(cx1, cy2)
        path.lineTo(l,   cy2)
        path.lineTo(l,   cy1)
        path.lineTo(cx1, cy1)
        path.closeSubpath()
        return path

    @staticmethod
    def _load_custom_shape(filepath: str) -> QPainterPath:
        import json
        path = QPainterPath()
        try:
            with open(filepath, "r") as f: data = json.load(f)
            i = 0
            while i < len(data):
                d = data[i]
                t = d["type"]
                if t == 0:
                    path.moveTo(d["x"], d["y"]); i += 1
                elif t == 1:
                    path.lineTo(d["x"], d["y"]); i += 1
                elif t == 2:
                    if i + 2 < len(data):
                        d1 = data[i+1]; d2 = data[i+2]
                        path.cubicTo(d["x"], d["y"], d1["x"], d1["y"], d2["x"], d2["y"])
                    i += 3
                else: i += 1
        except Exception:
            logger.exception("Failed to parse shape path data")
        return path

    # ── Drawing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _draw_shape(painter: QPainter, shape: str, rect: QRect,
                    start: QPoint, end: QPoint, sides: int, angle: int,
                    fill: bool, fg, bg, size: int):
        painter.save()
        if angle and shape != "line":
            cx, cy = rect.center().x(), rect.center().y()
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.translate(-cx, -cy)

        painter.setPen(QPen(fg, size) if size > 0 else Qt.PenStyle.NoPen)
        if shape == "line":
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setBrush(QBrush(bg) if fill else QBrush(Qt.BrushStyle.NoBrush))

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
            painter.drawPolygon(ShapesTool._polygon_points(rect, max(3, sides)))
        elif shape == "line":
            painter.drawLine(start, end)
        elif shape == "star":
            painter.drawPolygon(ShapesTool._star_points(rect))
        elif shape == "arrow":
            painter.drawPath(ShapesTool._arrow_path(rect))
        elif shape == "cross":
            painter.drawPath(ShapesTool._cross_path(rect))
        else:
            painter.drawRect(rect)
        painter.restore()

    @staticmethod
    def _bake_shape(image, shape_data: dict, doc_selection=None):
        """Renders a shape_data dict into `image` from scratch. The single
        source of truth used both when a shape is first created and every
        time it's resized/moved afterwards, so the layer's pixels always
        match its stored geometry exactly."""
        rx, ry, rw, rh = shape_data["rect"]
        rect = QRect(int(rx), int(ry), int(rw), int(rh))
        sx, sy = shape_data.get("start", (rx, ry))
        ex, ey = shape_data.get("end", (rx + rw, ry + rh))
        color = QColor(shape_data.get("fg", "#000000"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if doc_selection and not doc_selection.isEmpty():
            painter.setClipPath(doc_selection)
        ShapesTool._draw_shape(
            painter, shape_data.get("shape", "rect"), rect,
            QPoint(int(sx), int(sy)), QPoint(int(ex), int(ey)),
            shape_data.get("sides", 6), shape_data.get("angle", 0),
            shape_data.get("fill", False), color, color, shape_data.get("size", 3),
        )
        painter.end()

    # ── Tool interface ────────────────────────────────────────────────────────

    def on_press(self, pos, doc, fg, bg, opts):
        self._start       = pos
        self._preview_end = pos
        self._shape_type  = opts.get("shape_type", "rect")
        self._shift       = bool(opts.get("_shift", False))
        self._sides       = int(opts.get("shape_sides", 6))
        self._angle       = int(opts.get("shape_angle", 0))
        if opts.get("shape_angle_random", False):
            self._angle = random.randint(0, 359)

    def on_move(self, pos, doc, fg, bg, opts):
        self._preview_end = pos
        self._shift       = bool(opts.get("_shift", False))
        self._sides       = int(opts.get("shape_sides", 6))

    def preview_shape(self) -> dict | None:
        """Return a dict describing the live shape preview, or None."""
        if self._start is None or self._preview_end is None:
            return None
        end = (self._constrain(self._start, self._preview_end)
               if self._shift else self._preview_end)
        return {
            "shape": self._shape_type,
            "start": self._start,
            "end":   end,
            "rect":  QRect(self._start, end).normalized(),
            "sides": self._sides,
            "angle": self._angle,
        }

    def on_release(self, pos, doc, fg, bg, opts):
        self._preview_end = None

        if self._start is None:
            return

        end   = self._constrain(self._start, pos) if bool(opts.get("_shift", False)) else pos
        rect  = QRect(self._start, end).normalized()
        if rect.isEmpty():
            self._start = None
            return

        size  = int(opts.get("brush_size", 3))
        shape = opts.get("shape_type", "rect")
        fill  = bool(opts.get("shape_fill", False))
        sides = int(opts.get("shape_sides", 6))
        angle = self._angle
        shape_color = opts.get("shape_color", fg)

        from core.layer import VectorLayer
        n = sum(1 for l in doc.layers if getattr(l, "layer_type", "raster") == "vector") + 1
        new_layer = VectorLayer(f"Shape {n}", doc.width, doc.height)

        shape_data = {
            "shape": shape,
            "rect":  (rect.x(), rect.y(), rect.width(), rect.height()),
            "start": (int(self._start.x()), int(self._start.y())),
            "end":   (int(end.x()), int(end.y())),
            "sides": sides, "angle": angle, "fill": fill, "size": size,
            "fg":    shape_color.name(), "bg": shape_color.name(),
        }
        self._bake_shape(new_layer.image, shape_data, doc.selection)
        new_layer.shape_data = shape_data

        doc.layers.append(new_layer)
        doc.active_layer_index = len(doc.layers) - 1
        self._start = None

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.CrossCursor
