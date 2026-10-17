"""Shape layers as data: `ShapeSpec` (geometry + appearance) is the single
source of truth for turning a `shape_data` dict into pixels, at any scale.

Every place that used to unpack `shape_data` by hand and call the drawing
code with ten positional arguments (layer compositing, thumbnail bake,
creation-drag preview, MoveTool preview, ShapeLayerItem's drag paint) now
does `ShapeSpec.from_dict(sd).paint(painter)` — so a new styling option
(stroke alignment, dashes, gradient fill, per-corner radius...) is added in
exactly one place and can't render differently in one of those five.

Painting happens in *device* space: the outline is mapped through the
painter's current transform first and stroked/filled with an identity
transform. That's what keeps a shape sharp at 1600% zoom (the outline is
re-flattened at screen resolution, not at document resolution) and lets
inside/outside stroke alignment use exact path boolean ops instead of a
non-antialiased clip.

`ShapeAppearance` is shared with Pen Tool layers (`path_style`), so both
kinds of vector layer get the same fill/stroke options.
"""
import math
from dataclasses import dataclass, field, replace

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QPainter, QPainterPath,
                         QPainterPathStroker, QTransform)

from core.gradient_model import Gradient
from core.shape_kinds import ShapeParams, get_shape_kind

STROKE_STYLES = ("solid", "dash", "dot")
STROKE_ALIGNS = ("center", "inside", "outside")
STROKE_CAPS = ("butt", "round", "square")
STROKE_JOINS = ("miter", "round", "bevel")
FILL_TYPES = ("solid", "gradient")

_CAP = {"square": Qt.PenCapStyle.SquareCap, "butt": Qt.PenCapStyle.FlatCap,
        "round": Qt.PenCapStyle.RoundCap}
_JOIN = {"miter": Qt.PenJoinStyle.MiterJoin, "round": Qt.PenJoinStyle.RoundJoin,
         "bevel": Qt.PenJoinStyle.BevelJoin}
# In units of the stroke width, like QPen's own dash patterns. Dots are
# zero-length dashes drawn with round caps (Photoshop's dotted preset).
_DASH = {"dash": [4.0, 2.0], "dot": [0.001, 2.0]}
_MITER_LIMIT = 4.0   # Illustrator/Photoshop default


def _color(value, default="#000000") -> QColor:
    if isinstance(value, QColor):
        return QColor(value)
    if value is None:
        return QColor(default)
    return QColor(value)


def _pick(value, allowed, default):
    return value if value in allowed else default


@dataclass
class ShapeAppearance:
    """How a vector outline is painted: fill (none/solid/linear gradient)
    and stroke (width, color, dash style, alignment, caps, joins)."""
    fill_enabled: bool = True
    fill_type: str = "solid"
    fill_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    gradient: Gradient = field(default_factory=Gradient)
    stroke_width: float = 0.0
    # Separate from the width so switching the stroke off and on again
    # keeps the width the user chose (Photoshop's "no stroke" swatch).
    stroke_enabled: bool = True
    stroke_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    stroke_style: str = "solid"
    stroke_align: str = "center"
    stroke_cap: str = "butt"
    stroke_join: str = "miter"

    # ── serialization ──────────────────────────────────────────────────
    @classmethod
    def from_shape_data(cls, sd: dict) -> "ShapeAppearance":
        # Pre-2026-10 shape_data had one color ("fg", mirrored into "bg")
        # used for both fill and stroke; it's the fallback for both now.
        legacy = sd.get("fg", "#000000")
        grad = sd.get("gradient") or {}
        return cls(
            fill_enabled=bool(sd.get("fill", False)),
            fill_type=_pick(sd.get("fill_type"), FILL_TYPES, "solid"),
            fill_color=_color(sd.get("fill_color", legacy)),
            gradient=Gradient.from_dict(grad, fallback=_color(sd.get("fill_color", legacy))),
            stroke_width=max(0.0, float(sd.get("size", 0) or 0)),
            stroke_enabled=bool(sd.get("stroke_enabled", True)),
            stroke_color=_color(sd.get("stroke_color", legacy)),
            stroke_style=_pick(sd.get("stroke_style"), STROKE_STYLES, "solid"),
            stroke_align=_pick(sd.get("stroke_align"), STROKE_ALIGNS, "center"),
            stroke_cap=_pick(sd.get("stroke_cap"), STROKE_CAPS, "butt"),
            stroke_join=_pick(sd.get("stroke_join"), STROKE_JOINS, "miter"),
        )

    def write_shape_data(self, sd: dict) -> None:
        sd["fill"] = self.fill_enabled
        sd["fill_type"] = self.fill_type
        sd["fill_color"] = self.fill_color.name(QColor.NameFormat.HexArgb)
        sd["gradient"] = self.gradient.to_dict()
        sd["size"] = self.stroke_width
        sd["stroke_enabled"] = self.stroke_enabled
        sd["stroke_color"] = self.stroke_color.name(QColor.NameFormat.HexArgb)
        sd["stroke_style"] = self.stroke_style
        sd["stroke_align"] = self.stroke_align
        sd["stroke_cap"] = self.stroke_cap
        sd["stroke_join"] = self.stroke_join

    @classmethod
    def from_path_style(cls, ps: dict) -> "ShapeAppearance":
        """Pen Tool layers: {"fill_color", "stroke_color", "stroke_width"}
        (None color = disabled), plus the same optional extras as shapes."""
        fill = ps.get("fill_color")
        stroke = ps.get("stroke_color")
        grad = ps.get("gradient") or {}
        return cls(
            fill_enabled=fill is not None,
            fill_type=_pick(ps.get("fill_type"), FILL_TYPES, "solid"),
            fill_color=_color(fill),
            gradient=Gradient.from_dict(grad, fallback=_color(fill)),
            stroke_width=float(ps.get("stroke_width", 0) or 0),
            stroke_enabled=stroke is not None,
            stroke_color=_color(stroke),
            stroke_style=_pick(ps.get("stroke_style"), STROKE_STYLES, "solid"),
            stroke_align=_pick(ps.get("stroke_align"), STROKE_ALIGNS, "center"),
            stroke_cap=_pick(ps.get("stroke_cap"), STROKE_CAPS, "butt"),
            stroke_join=_pick(ps.get("stroke_join"), STROKE_JOINS, "miter"),
        )

    def to_path_style(self) -> dict:
        return {
            "fill_color": QColor(self.fill_color) if self.fill_enabled else None,
            "fill_type": self.fill_type,
            "gradient": self.gradient.to_dict(),
            "stroke_color": QColor(self.stroke_color) if self.stroke_enabled else None,
            "stroke_width": self.stroke_width,
            "stroke_style": self.stroke_style,
            "stroke_align": self.stroke_align,
            "stroke_cap": self.stroke_cap,
            "stroke_join": self.stroke_join,
        }

    @property
    def effective_stroke_width(self) -> float:
        return self.stroke_width if self.stroke_enabled else 0.0

    # ── geometry of the stroke ────────────────────────────────────────
    def stroke_region(self, path: QPainterPath, closed: bool, scale: float = 1.0) -> QPainterPath:
        """The area the stroke covers, as a fillable path, in `path`'s own
        coordinate space (`scale` = how many of those units one stroke-
        width unit is). Inside/outside alignment is a stroke twice as wide,
        intersected with / subtracted from the outline — exact, unlike
        clipping, which QPainter doesn't antialias."""
        width = self.effective_stroke_width * scale
        if width <= 0 or path.isEmpty():
            return QPainterPath()
        align = self.stroke_align if closed else "center"
        stroker = QPainterPathStroker()
        stroker.setWidth(width if align == "center" else width * 2)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap if self.stroke_style == "dot"
                            else _CAP[self.stroke_cap])
        stroker.setJoinStyle(_JOIN[self.stroke_join])
        stroker.setMiterLimit(_MITER_LIMIT)
        dash = _DASH.get(self.stroke_style)
        if dash:
            # Dash lengths are relative to the stroker's width; keep them
            # relative to the *visible* width when it's doubled for alignment.
            stroker.setDashPattern([d / 2 for d in dash] if align != "center" else dash)
        region = stroker.createStroke(path)
        if align == "inside":
            region = region.intersected(path)
        elif align == "outside":
            region = region.subtracted(path)
        return region

    def outer_extent(self) -> float:
        """How far (document units) painting can reach outside the outline."""
        if self.effective_stroke_width <= 0 or self.stroke_align == "inside":
            return 1.0
        w = self.stroke_width if self.stroke_align == "outside" else self.stroke_width / 2
        return w * _MITER_LIMIT + 1.0

    # ── painting ─────────────────────────────────────────────────────
    def _fill_brush(self, frame: QRectF, frame_angle: float, to_device: QTransform,
                    device_area) -> QBrush:
        if self.fill_type != "gradient":
            return QBrush(self.fill_color)
        return self.gradient.brush(frame, frame_angle, to_device, device_area)

    def paint(self, painter: QPainter, path: QPainterPath, closed: bool = True,
              frame: QRectF | None = None, frame_angle: float = 0.0) -> None:
        """Fill then stroke `path` (document coordinates). `frame` (+ its
        rotation) is what a gradient fill spans — the shape's own unrotated
        box, so the gradient turns with the shape."""
        if path.isEmpty():
            return
        to_device = painter.transform()
        scale = math.sqrt(abs(to_device.determinant())) or 1.0
        device_path = to_device.map(path)
        painter.save()
        painter.setTransform(QTransform())
        if closed and self.fill_enabled:
            area = device_path.boundingRect().toAlignedRect()
            dev = painter.device()
            if dev is not None and dev.width() > 0:
                area = area.intersected(QRect(0, 0, dev.width(), dev.height()))
            painter.fillPath(device_path, self._fill_brush(
                frame if frame is not None else path.boundingRect(), frame_angle, to_device, area))
        if self.effective_stroke_width > 0:
            region = self.stroke_region(device_path, closed, scale)
            if not region.isEmpty():
                painter.fillPath(region, QBrush(self.stroke_color))
        painter.restore()


@dataclass
class ShapeSpec:
    """A `shape_data` dict, parsed: which primitive, where, and how it's
    painted. Immutable-by-convention — edits go through `replace()` and
    `to_dict()`, so the dict stays the persisted source of truth."""
    shape: str
    params: ShapeParams
    angle: float
    appearance: ShapeAppearance

    @classmethod
    def from_dict(cls, sd: dict) -> "ShapeSpec":
        rx, ry, rw, rh = sd.get("rect", (0, 0, 0, 0))
        sx, sy = sd.get("start", (rx, ry))
        ex, ey = sd.get("end", (rx + rw, ry + rh))
        radii = sd.get("corner_radii")
        if not radii or len(radii) != 4:
            r = sd.get("corner_radius", 0) or 0
            radii = (r, r, r, r)
        return cls(
            shape=sd.get("shape", "rect"),
            params=ShapeParams(
                rect=QRectF(rx, ry, rw, rh), start=QPointF(sx, sy), end=QPointF(ex, ey),
                sides=int(sd.get("sides", 6)),
                corner_radii=tuple(float(v) for v in radii),
                star_points=int(sd.get("star_points", 5)),
                star_inner=float(sd.get("star_inner", 0.4)),
            ),
            angle=float(sd.get("angle", 0) or 0),
            appearance=ShapeAppearance.from_shape_data(sd),
        )

    def to_dict(self, base: dict | None = None) -> dict:
        """Writes this spec over `base` (unknown keys survive). Geometry is
        stored as ints, matching every existing shape_data consumer."""
        sd = dict(base or {})
        p = self.params
        r = p.rect
        sd["shape"] = self.shape
        sd["rect"] = (round(r.x()), round(r.y()), round(r.width()), round(r.height()))
        sd["start"] = (round(p.start.x()), round(p.start.y()))
        sd["end"] = (round(p.end.x()), round(p.end.y()))
        sd["sides"] = p.sides
        sd["angle"] = round(self.angle) % 360
        sd["corner_radii"] = [round(v) for v in p.corner_radii]
        # Legacy single-radius field, still read by older code/tests.
        sd["corner_radius"] = round(p.corner_radii[0])
        sd["star_points"] = p.star_points
        sd["star_inner"] = p.star_inner
        self.appearance.write_shape_data(sd)
        return sd

    @property
    def kind(self):
        return get_shape_kind(self.shape)

    def with_geometry(self, rect: QRectF | None = None, angle: float | None = None,
                      start: QPointF | None = None, end: QPointF | None = None,
                      corner_radii: tuple | None = None) -> "ShapeSpec":
        params = self.params
        changes = {}
        if rect is not None: changes["rect"] = QRectF(rect)
        if start is not None: changes["start"] = QPointF(start)
        if end is not None: changes["end"] = QPointF(end)
        if corner_radii is not None: changes["corner_radii"] = tuple(corner_radii)
        if changes:
            params = replace(params, **changes)
        return replace(self, params=params, angle=self.angle if angle is None else angle)

    # ── geometry ────────────────────────────────────────────────────
    def rotation(self) -> QTransform:
        kind = self.kind
        if not self.angle or not kind.supports_rotation:
            return QTransform()
        c = self.params.rect.center()
        return QTransform().translate(c.x(), c.y()).rotate(self.angle).translate(-c.x(), -c.y())

    def local_path(self) -> QPainterPath:
        """Outline before rotation."""
        return self.kind.build_path(self.params)

    def outline(self) -> QPainterPath:
        """Outline in document coordinates (rotation applied)."""
        return self.rotation().map(self.local_path())

    def filled_area(self) -> QPainterPath:
        """Everything this shape paints, as one closed region (outline plus
        any stroke outside it). Used for boolean operations and hit-testing;
        a line's area is its stroke."""
        outline = self.outline()
        closed = not self.kind.is_open
        stroke = self.appearance.stroke_region(outline, closed)
        if not closed:
            return stroke
        return outline.united(stroke) if not stroke.isEmpty() else outline

    def boolean_operand(self) -> QPainterPath:
        """The region path operations combine: the outline for a closed
        shape (like Photoshop, ops act on paths, not on stroke pixels), the
        stroked area for a line, which has no inside of its own."""
        if self.kind.is_open:
            return self.appearance.stroke_region(self.outline(), closed=False)
        return self.outline()

    def bounds(self) -> QRectF:
        pad = self.appearance.outer_extent()
        return self.outline().boundingRect().adjusted(-pad, -pad, pad, pad)

    # ── painting ────────────────────────────────────────────────────
    def paint(self, painter: QPainter) -> None:
        kind = self.kind
        self.appearance.paint(painter, self.outline(), closed=not kind.is_open and kind.supports_fill,
                              frame=self.params.rect,
                              frame_angle=self.angle if kind.supports_rotation else 0.0)


# ── Boolean operations ──────────────────────────────────────────────────────

BOOLEAN_OPS = ("unite", "subtract", "intersect", "exclude")

# QPainterPath's boolean ops flatten curves into polygons with a fixed
# absolute tolerance. Doing the op in a space blown up by this factor (and
# mapping back) makes that tolerance 1/64 px in document units — curves
# stay smooth even when the result is later viewed at high zoom.
_BOOLEAN_PRECISION = 64.0


def combine_paths(base: QPainterPath, other: QPainterPath, op: str) -> QPainterPath:
    """Photoshop's path operations: unite, subtract front (`other` removed
    from `base`), intersect, exclude overlapping."""
    up = QTransform.fromScale(_BOOLEAN_PRECISION, _BOOLEAN_PRECISION)
    down = QTransform.fromScale(1 / _BOOLEAN_PRECISION, 1 / _BOOLEAN_PRECISION)
    a, b = up.map(base), up.map(other)
    a.setFillRule(Qt.FillRule.WindingFill)
    b.setFillRule(Qt.FillRule.WindingFill)
    if op == "unite":
        r = a.united(b)
    elif op == "subtract":
        r = a.subtracted(b)
    elif op == "intersect":
        r = a.intersected(b)
    elif op == "exclude":
        r = a.united(b).subtracted(a.intersected(b))
    else:
        raise ValueError(f"unknown boolean op {op!r}")
    # Qt's boolean ops return holes as oppositely-nested subpaths meant for
    # the odd-even rule (forcing winding would fill them back in).
    return down.map(r.simplified())
