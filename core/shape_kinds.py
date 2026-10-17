"""One class per shape primitive the Shapes tool can draw.

Each `ShapeKind` only knows its own *outline*: `build_path()` returns an
unrotated `QPainterPath` in document coordinates. Everything else — fill,
stroke, rotation, rendering at any zoom — is done once, on that path, by
`core/shape_model.py` (`ShapeSpec` / `ShapeAppearance`). A path (rather than
"draw yourself with this painter", which is what this module used to do)
is what makes boolean operations, accurate hit-testing and inside/outside
stroke alignment possible at all: they all need the geometry as data.
"""
import math
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QPolygon, QPolygonF, QPainterPath, QTransform

from core.app_logging import get_logger

logger = get_logger("shape_kinds")


@dataclass
class ShapeParams:
    """The geometry-only part of a shape: what `ShapeKind.build_path`
    needs. Kept separate from styling (colors, stroke) so kinds can't grow
    accidental dependencies on how they're painted."""
    rect: QRectF
    start: QPointF
    end: QPointF
    sides: int = 6
    # Per-corner radii, clockwise from top-left: (tl, tr, br, bl).
    corner_radii: tuple = (0.0, 0.0, 0.0, 0.0)
    star_points: int = 5
    star_inner: float = 0.4


# ── Path builders (float geometry; also used directly by tests) ─────────────

def _regular_points(rect: QRectF, count: int, radius_at) -> list[QPointF]:
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2, rect.height() / 2
    pts = []
    for i in range(count):
        a = -math.pi / 2 + 2 * math.pi * i / count
        r = radius_at(i)
        pts.append(QPointF(cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
    return pts


def polygon_points(rect, sides: int) -> QPolygon:
    """Regular N-gon inscribed in the bounding ellipse of rect (int points,
    kept for callers that still want a QPolygon)."""
    pts = _regular_points(QRectF(rect), max(3, sides), lambda i: 1.0)
    return QPolygon([QPoint(int(p.x()), int(p.y())) for p in pts])


def star_points(rect, points: int = 5, inner: float = 0.4) -> QPolygon:
    pts = _regular_points(QRectF(rect), max(3, points) * 2, lambda i: 1.0 if i % 2 == 0 else inner)
    return QPolygon([QPoint(int(p.x()), int(p.y())) for p in pts])


def _closed_polygon_path(points: list[QPointF]) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF(points))
    path.closeSubpath()
    return path


def arrow_path(rect) -> QPainterPath:
    """Right-pointing arrow fitting the bounding rect."""
    rect = QRectF(rect)
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    w, h = rect.width(), rect.height()
    shaft_x = l + w * 0.60
    shaft_t = t + h * 0.35
    shaft_b = b - h * 0.35
    return _closed_polygon_path([
        QPointF(l, shaft_t), QPointF(shaft_x, shaft_t), QPointF(shaft_x, t),
        QPointF(r, t + h / 2), QPointF(shaft_x, b), QPointF(shaft_x, shaft_b),
        QPointF(l, shaft_b),
    ])


def cross_path(rect) -> QPainterPath:
    """Plus/cross shape fitting the bounding rect."""
    rect = QRectF(rect)
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    w, h = rect.width(), rect.height()
    cx1, cx2 = l + w / 3, r - w / 3
    cy1, cy2 = t + h / 3, b - h / 3
    return _closed_polygon_path([
        QPointF(cx1, t), QPointF(cx2, t), QPointF(cx2, cy1), QPointF(r, cy1),
        QPointF(r, cy2), QPointF(cx2, cy2), QPointF(cx2, b), QPointF(cx1, b),
        QPointF(cx1, cy2), QPointF(l, cy2), QPointF(l, cy1), QPointF(cx1, cy1),
    ])


def clamp_corner_radii(rect: QRectF, radii) -> tuple:
    """CSS border-radius rule: negative radii become 0, and if two radii
    sharing an edge add up to more than that edge, all four are scaled
    down by the same factor — so a shape never self-intersects and the
    *proportions* between corners survive (unlike clamping each one alone)."""
    tl, tr, br, bl = (max(0.0, float(r)) for r in radii)
    w, h = abs(rect.width()), abs(rect.height())
    f = 1.0
    for total, edge in ((tl + tr, w), (bl + br, w), (tl + bl, h), (tr + br, h)):
        if total > edge > 0:
            f = min(f, edge / total)
        elif edge <= 0:
            f = 0.0
    return tl * f, tr * f, br * f, bl * f


def rounded_rect_path(rect, radii) -> QPainterPath:
    """Rectangle with an independent radius per corner (tl, tr, br, bl)."""
    rect = QRectF(rect)
    tl, tr, br, bl = clamp_corner_radii(rect, radii)
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    path = QPainterPath()
    path.moveTo(l + tl, t)
    path.lineTo(r - tr, t)
    if tr > 0:
        path.arcTo(QRectF(r - 2 * tr, t, 2 * tr, 2 * tr), 90, -90)
    path.lineTo(r, b - br)
    if br > 0:
        path.arcTo(QRectF(r - 2 * br, b - 2 * br, 2 * br, 2 * br), 0, -90)
    path.lineTo(l + bl, b)
    if bl > 0:
        path.arcTo(QRectF(l, b - 2 * bl, 2 * bl, 2 * bl), 270, -90)
    path.lineTo(l, t + tl)
    if tl > 0:
        path.arcTo(QRectF(l, t, 2 * tl, 2 * tl), 180, -90)
    path.closeSubpath()
    return path


def load_custom_shape_path(filepath: str) -> QPainterPath:
    import json
    path = QPainterPath()
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
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
                    d1 = data[i + 1]; d2 = data[i + 2]
                    path.cubicTo(d["x"], d["y"], d1["x"], d1["y"], d2["x"], d2["y"])
                i += 3
            else:
                i += 1
    except Exception:
        logger.exception("Failed to parse shape path data")
    return path


# ── Kinds ───────────────────────────────────────────────────────────────────

class ShapeKind:
    """Base class for a shape primitive. Subclasses implement only the
    outline (`build_path`); `core/shape_model.py` owns painting."""

    key = ""
    supports_rotation = True
    supports_fill = True
    is_open = False           # an open path (a line): no fill, no inside/outside
    uses_corner_radii = False
    uses_sides = False
    uses_star = False

    def build_path(self, p: ShapeParams) -> QPainterPath:
        raise NotImplementedError


class RectShapeKind(ShapeKind):
    key = "rect"

    def build_path(self, p):
        path = QPainterPath()
        path.addRect(p.rect)
        return path


class RoundedRectShapeKind(ShapeKind):
    key = "rounded_rect"
    uses_corner_radii = True

    def build_path(self, p):
        return rounded_rect_path(p.rect, p.corner_radii)


class EllipseShapeKind(ShapeKind):
    key = "ellipse"

    def build_path(self, p):
        path = QPainterPath()
        path.addEllipse(p.rect)
        return path


class TriangleShapeKind(ShapeKind):
    key = "triangle"

    def build_path(self, p):
        r = p.rect
        return _closed_polygon_path([
            QPointF(r.center().x(), r.top()), QPointF(r.left(), r.bottom()),
            QPointF(r.right(), r.bottom()),
        ])


class PolygonShapeKind(ShapeKind):
    key = "polygon"
    uses_sides = True

    def build_path(self, p):
        return _closed_polygon_path(_regular_points(p.rect, max(3, p.sides), lambda i: 1.0))


class LineShapeKind(ShapeKind):
    key = "line"
    supports_rotation = False
    supports_fill = False
    is_open = True

    def build_path(self, p):
        path = QPainterPath()
        path.moveTo(p.start)
        path.lineTo(p.end)
        return path


class StarShapeKind(ShapeKind):
    key = "star"
    uses_star = True

    def build_path(self, p):
        inner = min(0.99, max(0.01, p.star_inner))
        return _closed_polygon_path(_regular_points(
            p.rect, max(3, p.star_points) * 2, lambda i: 1.0 if i % 2 == 0 else inner))


class ArrowShapeKind(ShapeKind):
    key = "arrow"

    def build_path(self, p):
        return arrow_path(p.rect)


class CrossShapeKind(ShapeKind):
    key = "cross"

    def build_path(self, p):
        return cross_path(p.rect)


class CustomShapeKind(ShapeKind):
    """A user-defined shape loaded from a `shapes/*.json` path file, scaled
    to fill the target rect. `key` carries the full `custom:<filepath>`
    string so the registry can round-trip it."""

    _cache: dict[str, QPainterPath] = {}

    def __init__(self, filepath: str):
        self.key = f"custom:{filepath}"
        self._filepath = filepath

    def build_path(self, p):
        src = self._cache.get(self._filepath)
        if src is None:
            src = load_custom_shape_path(self._filepath)
            self._cache[self._filepath] = src
        br = src.boundingRect()
        if src.isEmpty() or br.width() <= 0 or br.height() <= 0:
            return QPainterPath()
        r = p.rect
        t = (QTransform().translate(r.left(), r.top())
             .scale(r.width() / br.width(), r.height() / br.height())
             .translate(-br.left(), -br.top()))
        return t.map(src)


_REGISTRY: dict[str, ShapeKind] = {
    kind.key: kind for kind in (
        RectShapeKind(), RoundedRectShapeKind(), EllipseShapeKind(), TriangleShapeKind(),
        PolygonShapeKind(), LineShapeKind(), StarShapeKind(),
        ArrowShapeKind(), CrossShapeKind(),
    )
}
_DEFAULT_KIND = _REGISTRY["rect"]


def get_shape_kind(shape: str) -> ShapeKind:
    """Look up a `ShapeKind` by its `shape_data["shape"]` string. Unknown
    keys fall back to a plain rectangle."""
    if shape.startswith("custom:"):
        return CustomShapeKind(shape[7:])
    return _REGISTRY.get(shape, _DEFAULT_KIND)


def draw_shape(painter, shape: str, rect, start, end, sides: int, angle, fill: bool,
               fg, bg, size, extra: dict | None = None) -> None:
    """Back-compat entry point (positional arguments of the pre-ShapeSpec
    API). Builds a `ShapeSpec` and paints it — there is only one renderer."""
    from core.shape_model import ShapeSpec
    extra = extra or {}
    r = extra.get("corner_radius", 0)
    spec = ShapeSpec.from_dict({
        "shape": shape,
        "rect": (rect.x(), rect.y(), rect.width(), rect.height()),
        "start": (start.x(), start.y()), "end": (end.x(), end.y()),
        "sides": sides, "angle": angle, "fill": fill, "size": size,
        "fill_color": bg, "stroke_color": fg,
        "corner_radii": extra.get("corner_radii", [r, r, r, r]),
    })
    spec.paint(painter)
