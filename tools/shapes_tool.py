import random

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPainter, QPolygon, QPainterPath, QColor
from tools.base_tool import BaseTool

from core.app_logging import get_logger
from core.shape_kinds import (
    draw_shape, polygon_points, star_points, arrow_path, cross_path,
    load_custom_shape_path,
)
from core.shape_model import ShapeSpec, BOOLEAN_OPS

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
        self._corner_radius: int         = 20

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
        return polygon_points(rect, sides)

    @staticmethod
    def _star_points(rect: QRect, points: int = 5, inner: float = 0.4) -> QPolygon:
        return star_points(rect, points, inner)

    @staticmethod
    def _arrow_path(rect: QRect) -> QPainterPath:
        return arrow_path(rect)

    @staticmethod
    def _cross_path(rect: QRect) -> QPainterPath:
        return cross_path(rect)

    @staticmethod
    def _load_custom_shape(filepath: str) -> QPainterPath:
        return load_custom_shape_path(filepath)

    # ── Drawing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _draw_shape(painter: QPainter, shape: str, rect: QRect,
                    start: QPoint, end: QPoint, sides: int, angle: int,
                    fill: bool, fg, bg, size: int, corner_radius: int = 0):
        """Back-compat positional entry point (tests call it); renders
        through the one ShapeSpec renderer in core/shape_model.py."""
        draw_shape(painter, shape, rect, start, end, sides, angle, fill, fg, bg, size,
                  extra={"corner_radius": corner_radius})

    @staticmethod
    def _bake_shape(image, shape_data: dict, doc_selection=None):
        """Renders a shape_data dict into `image` (Layers-panel thumbnail
        source — the canvas renders shape_data live, see VectorLayer)."""
        # `doc_selection` is accepted for call-site compatibility but
        # deliberately ignored: like Photoshop's shape layers, a shape isn't
        # clipped by the pixel selection (the live canvas render never was —
        # clipping only the thumbnail made the two disagree).
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ShapeSpec.from_dict(shape_data).paint(painter)
        painter.end()

    @staticmethod
    def rebake(layer, doc_selection=None):
        """Clear + re-bake a shape layer's thumbnail image from its
        shape_data (after any edit)."""
        layer.image.fill(Qt.GlobalColor.transparent)
        ShapesTool._bake_shape(layer.image, layer.shape_data, doc_selection)

    # ── Tool interface ────────────────────────────────────────────────────────

    def on_press(self, pos, doc, fg, bg, opts):
        self._start       = pos
        self._preview_end = pos
        self._shift       = bool(opts.get("_shift", False))
        self._angle       = int(opts.get("shape_angle", 0))
        if opts.get("shape_angle_random", False):
            self._angle = random.randint(0, 359)
        self._shape_type  = opts.get("shape_type", "rect")
        self._sides       = int(opts.get("shape_sides", 6))
        self._corner_radius = int(opts.get("shape_corner_radius", 20))

    def on_move(self, pos, doc, fg, bg, opts):
        self._preview_end = pos
        self._shift       = bool(opts.get("_shift", False))
        self._sides       = int(opts.get("shape_sides", 6))
        self._corner_radius = int(opts.get("shape_corner_radius", 20))

    def _end_point(self, pos, shift: bool) -> QPoint:
        return self._constrain(self._start, pos) if shift else pos

    def preview_shape(self) -> dict | None:
        """Return a dict describing the live shape preview, or None."""
        if self._start is None or self._preview_end is None:
            return None
        end = self._end_point(self._preview_end, self._shift)
        return {
            "shape": self._shape_type,
            "start": self._start,
            "end":   end,
            "rect":  QRect(self._start, end).normalized(),
            "sides": self._sides,
            "angle": self._angle,
            "corner_radius": self._corner_radius,
        }

    def preview_shape_data(self, opts, fg) -> dict | None:
        """The in-progress drag as a full shape_data dict, styled exactly
        like the shape on_release will create — the creation preview
        renders through the same ShapeSpec as the finished layer."""
        ps = self.preview_shape()
        if ps is None:
            return None
        return shape_data_from_opts(opts, fg, ps["start"], ps["end"], self._angle)

    def on_release(self, pos, doc, fg, bg, opts):
        self._preview_end = None

        if self._start is None:
            return

        end   = self._end_point(pos, bool(opts.get("_shift", False)))
        rect  = QRect(self._start, end).normalized()
        if rect.isEmpty():
            self._start = None
            return

        shape_data = shape_data_from_opts(opts, fg, self._start, end, self._angle)
        self._start = None

        from core.layer import VectorLayer
        op = opts.get("shape_path_op", "new")
        target = doc.get_active_layer()
        if (op in BOOLEAN_OPS and isinstance(target, VectorLayer)
                and target.has_vector_geometry() and not target.locked):
            # Photoshop's path operations: the new shape is combined into
            # the selected shape layer instead of becoming a layer of its own.
            target.combine_with(ShapeSpec.from_dict(shape_data).boolean_operand(), op)
            return

        n = sum(1 for l in doc.layers if getattr(l, "layer_type", "raster") == "vector") + 1
        new_layer = VectorLayer(f"Shape {n}", doc.width, doc.height)
        new_layer.shape_data = shape_data
        self._bake_shape(new_layer.image, shape_data)

        doc.layers.append(new_layer)
        doc.active_layer_index = len(doc.layers) - 1

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.CrossCursor


def _opt_color(opts, key, fallback) -> QColor:
    v = opts.get(key)
    return QColor(v) if v is not None else QColor(fallback)


def shape_data_from_opts(opts: dict, fg, start: QPoint, end: QPoint, angle: int) -> dict:
    """Builds a new shape's shape_data from the Shapes tool options.
    `shape_color` (the old single color) is the fallback for both fill and
    stroke colors; `brush_size` the fallback stroke width (older callers
    and tests), `shape_stroke_width` the real Shapes-tool setting — the
    brush tools share `brush_size`, a shape's stroke shouldn't."""
    from core.shape_model import ShapeAppearance
    from core.gradient_model import Gradient
    base = _opt_color(opts, "shape_color", fg)
    rect = QRect(start, end).normalized()
    width = opts.get("shape_stroke_width", opts.get("brush_size", 3))
    r = int(opts.get("shape_corner_radius", 20))
    radii = opts.get("shape_corner_radii") or [r, r, r, r]
    appearance = ShapeAppearance(
        fill_enabled=bool(opts.get("shape_fill", False)),
        fill_type=opts.get("shape_fill_type", "solid"),
        fill_color=_opt_color(opts, "shape_fill_color", base),
        gradient=(Gradient.from_dict(opts["shape_gradient"]) if opts.get("shape_gradient")
                  else Gradient.two_color(_opt_color(opts, "shape_fill_color", base), QColor(255, 255, 255))),
        stroke_width=max(0.0, float(width or 0)),
        stroke_enabled=bool(opts.get("shape_stroke", True)),
        stroke_color=_opt_color(opts, "shape_stroke_color", base),
        stroke_style=opts.get("shape_stroke_style", "solid"),
        stroke_align=opts.get("shape_stroke_align", "center"),
        stroke_cap=opts.get("shape_stroke_cap", "butt"),
        stroke_join=opts.get("shape_stroke_join", "miter"),
    )
    sd = {
        "shape": opts.get("shape_type", "rect"),
        "rect":  (rect.x(), rect.y(), rect.width(), rect.height()),
        "start": (int(start.x()), int(start.y())),
        "end":   (int(end.x()), int(end.y())),
        "sides": int(opts.get("shape_sides", 6)),
        "angle": angle,
        "corner_radius": int(radii[0]),
        "corner_radii": [int(v) for v in radii],
        "star_points": int(opts.get("shape_star_points", 5)),
        "star_inner": float(opts.get("shape_star_inner", 40)) / 100.0,
        # Legacy single-color field kept in sync for older readers.
        "fg": base.name(), "bg": base.name(),
    }
    appearance.write_shape_data(sd)
    return sd
