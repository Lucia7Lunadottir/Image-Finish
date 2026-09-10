import math
import random

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QPainter, QPen, QBrush, QPolygon, QPainterPath, QTransform, QColor
from tools.base_tool import BaseTool

from core.app_logging import get_logger

logger = get_logger("shapes_tool")


class ShapesTool(BaseTool):
    """Vector shape layers store their geometry in `layer.shape_data` and
    are re-rendered from it on every edit (via `_bake_shape`), rather than
    being fixed pixels from the moment they're drawn — so an existing shape
    can be picked up by its handles and resized/moved after the fact."""

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

        # Re-editing an existing shape layer's handles
        self._edit_layer:        object | None = None
        self._edit_mode:         str | None    = None   # 'move' | 'tl' | 't' | ...
        self._edit_orig_rect:    QRect | None  = None
        self._edit_start_pos:    QPoint | None = None
        self._edit_pending_rect: QRect | None  = None
        self._hover_mode:        str | None    = None

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

    @staticmethod
    def _find_edit_target(doc, pos: QPoint, zoom: float):
        """Hit-tests existing vector layers' handles/body, topmost first.
        Returns (layer, handle_name) or (None, None)."""
        hit_dist = 8 / max(0.01, zoom)
        for layer in reversed(doc.layers):
            if not layer.visible or layer.locked:
                continue
            if getattr(layer, "layer_type", "raster") != "vector":
                continue
            sd = getattr(layer, "shape_data", None)
            if not sd or "rect" not in sd:
                continue
            rx, ry, rw, rh = sd["rect"]
            r = QRectF(rx, ry, rw, rh)
            handles = {
                'tl': r.topLeft(), 't': QPointF(r.center().x(), r.top()), 'tr': r.topRight(),
                'r':  QPointF(r.right(), r.center().y()), 'br': r.bottomRight(),
                'b':  QPointF(r.center().x(), r.bottom()), 'bl': r.bottomLeft(),
                'l':  QPointF(r.left(), r.center().y()),
            }
            min_d, best = float('inf'), None
            for name, pt in handles.items():
                d = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                if d < min_d:
                    min_d, best = d, name
            if min_d <= hit_dist:
                return layer, best
            if r.contains(QPointF(pos)):
                return layer, 'move'
        return None, None

    # ── Tool interface ────────────────────────────────────────────────────────

    def on_press(self, pos, doc, fg, bg, opts):
        hit_layer, hit_mode = self._find_edit_target(doc, pos, opts.get("_zoom", 1.0))
        if hit_layer is not None:
            doc.active_layer_index = doc.layers.index(hit_layer)
            self._edit_layer     = hit_layer
            self._edit_mode      = hit_mode
            self._edit_start_pos = pos
            rx, ry, rw, rh = hit_layer.shape_data["rect"]
            self._edit_orig_rect    = QRect(int(rx), int(ry), int(rw), int(rh))
            self._edit_pending_rect = QRect(self._edit_orig_rect)
            self._start = None
            return

        self._edit_layer = None
        self._start       = pos
        self._preview_end = pos
        self._shape_type  = opts.get("shape_type", "rect")
        self._shift       = bool(opts.get("_shift", False))
        self._sides       = int(opts.get("shape_sides", 6))
        self._angle       = int(opts.get("shape_angle", 0))
        if opts.get("shape_angle_random", False):
            self._angle = random.randint(0, 359)

    def on_move(self, pos, doc, fg, bg, opts):
        if self._edit_layer is not None:
            r = QRect(self._edit_orig_rect)
            dx = pos.x() - self._edit_start_pos.x()
            dy = pos.y() - self._edit_start_pos.y()
            if self._edit_mode == 'move':
                r.translate(dx, dy)
            else:
                if 'l' in self._edit_mode: r.setLeft(r.left() + dx)
                if 'r' in self._edit_mode: r.setRight(r.right() + dx)
                if 't' in self._edit_mode: r.setTop(r.top() + dy)
                if 'b' in self._edit_mode: r.setBottom(r.bottom() + dy)
            r = r.normalized()
            if r.width() < 1 or r.height() < 1:
                return

            self._edit_pending_rect = r
            sd = dict(self._edit_layer.shape_data)
            sd["rect"]  = (r.x(), r.y(), r.width(), r.height())
            sd["start"] = (r.left(), r.top())
            sd["end"]   = (r.right(), r.bottom())
            self._edit_layer.image.fill(Qt.GlobalColor.transparent)
            self._bake_shape(self._edit_layer.image, sd, doc.selection)
            return

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

        if self._edit_layer is not None:
            layer = self._edit_layer
            rect = self._edit_pending_rect
            self._edit_layer = None
            self._edit_mode = None
            self._edit_orig_rect = None
            self._edit_pending_rect = None
            if rect is not None:
                sd = dict(layer.shape_data)
                sd["rect"]  = (rect.x(), rect.y(), rect.width(), rect.height())
                sd["start"] = (rect.left(), rect.top())
                sd["end"]   = (rect.right(), rect.bottom())
                layer.shape_data = sd
            return

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

        from core.layer import Layer
        n = sum(1 for l in doc.layers if getattr(l, "layer_type", "raster") == "vector") + 1
        new_layer = Layer(f"Shape {n}", doc.width, doc.height)
        new_layer.layer_type = "vector"

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

    def on_hover(self, pos: QPoint, doc, fg, bg, opts):
        _layer, self._hover_mode = self._find_edit_target(doc, pos, opts.get("_zoom", 1.0))

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        m = self._hover_mode
        if m == 'move': return Qt.CursorShape.SizeAllCursor
        if m in ('tl', 'br'): return Qt.CursorShape.SizeFDiagCursor
        if m in ('tr', 'bl'): return Qt.CursorShape.SizeBDiagCursor
        if m in ('l', 'r'): return Qt.CursorShape.SizeHorCursor
        if m in ('t', 'b'): return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.CrossCursor
