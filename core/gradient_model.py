"""A gradient as data, modeled on Photoshop's Gradient Editor: separate
color stops and opacity stops (each with a midpoint to the next stop),
plus how it's laid out over an area — style, angle, scale, reverse.

Used by shape fills (core/shape_model.py) and edited by
ui/gradient_editor.py. `merged_stops()` flattens it to the plain
[(position, QColor-with-alpha)] list older code (the Gradient tool) uses.
"""
import math
from dataclasses import dataclass, field, replace

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QGradient, QImage,
                         QLinearGradient, QRadialGradient, QTransform)

GRADIENT_STYLES = ("linear", "radial", "angle", "reflected", "diamond")


@dataclass
class ColorStop:
    position: float
    color: QColor            # opaque RGB; alpha lives in the opacity stops
    midpoint: float = 0.5    # where between this stop and the next the 50/50 mix sits


@dataclass
class OpacityStop:
    position: float
    opacity: float           # 0..1
    midpoint: float = 0.5


def _mix_t(t: float, midpoint: float) -> float:
    """Photoshop-style midpoint: a power curve that puts the half-way mix
    at `midpoint` (0.5 = plain linear)."""
    m = min(0.95, max(0.05, midpoint))
    if abs(m - 0.5) < 1e-6 or t <= 0 or t >= 1:
        return t
    return t ** (math.log(0.5) / math.log(m))


def _segment(stops, t):
    """(left, right, local t) of the stop segment containing t."""
    if t <= stops[0].position:
        return stops[0], stops[0], 0.0
    if t >= stops[-1].position:
        return stops[-1], stops[-1], 0.0
    for a, b in zip(stops, stops[1:]):
        if a.position <= t <= b.position:
            span = b.position - a.position
            local = (t - a.position) / span if span > 0 else 0.0
            return a, b, _mix_t(local, a.midpoint)
    return stops[-1], stops[-1], 0.0


@dataclass
class Gradient:
    color_stops: list = field(default_factory=lambda: [ColorStop(0.0, QColor(0, 0, 0)),
                                                       ColorStop(1.0, QColor(255, 255, 255))])
    opacity_stops: list = field(default_factory=lambda: [OpacityStop(0.0, 1.0), OpacityStop(1.0, 1.0)])
    style: str = "linear"
    angle: float = 0.0       # degrees, 0 = left -> right
    scale: float = 100.0     # percent of the shape's own extent
    reverse: bool = False

    # ── construction ────────────────────────────────────────────────
    @classmethod
    def two_color(cls, a: QColor, b: QColor, **kw) -> "Gradient":
        return cls(color_stops=[ColorStop(0.0, _opaque(a)), ColorStop(1.0, _opaque(b))],
                   opacity_stops=[OpacityStop(0.0, QColor(a).alphaF()), OpacityStop(1.0, QColor(b).alphaF())],
                   **kw)

    @classmethod
    def from_merged_stops(cls, stops, **kw) -> "Gradient":
        """From [(pos, QColor-with-alpha)] — the Gradient tool's format."""
        stops = sorted(((float(p), QColor(c)) for p, c in stops), key=lambda s: s[0])
        if not stops:
            return cls(**kw)
        if len(stops) == 1:
            stops = [stops[0], (1.0, stops[0][1])]
        return cls(color_stops=[ColorStop(p, _opaque(c)) for p, c in stops],
                   opacity_stops=[OpacityStop(p, c.alphaF()) for p, c in stops], **kw)

    def copy(self) -> "Gradient":
        return Gradient.from_dict(self.to_dict())

    def sorted(self) -> "Gradient":
        return replace(self,
                       color_stops=sorted(self.color_stops, key=lambda s: s.position),
                       opacity_stops=sorted(self.opacity_stops, key=lambda s: s.position))

    # ── serialization ───────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "color_stops": [[round(s.position, 4), s.color.name(), round(s.midpoint, 4)]
                            for s in self.color_stops],
            "opacity_stops": [[round(s.position, 4), round(s.opacity, 4), round(s.midpoint, 4)]
                              for s in self.opacity_stops],
            "style": self.style, "angle": self.angle, "scale": self.scale, "reverse": self.reverse,
        }

    @classmethod
    def from_dict(cls, d: dict | None, fallback: QColor | None = None) -> "Gradient":
        """Reads the current format, and the 2026-10-17 two-color shape
        format {"start", "end", "angle"}."""
        d = d or {}
        common = dict(style=d.get("style") if d.get("style") in GRADIENT_STYLES else "linear",
                      angle=float(d.get("angle", 0.0) or 0.0),
                      scale=float(d.get("scale", 100.0) or 100.0),
                      reverse=bool(d.get("reverse", False)))
        if d.get("color_stops"):
            cs = [ColorStop(float(s[0]), _opaque(QColor(s[1])), float(s[2]) if len(s) > 2 else 0.5)
                  for s in d["color_stops"]]
            os_ = [OpacityStop(float(s[0]), float(s[1]), float(s[2]) if len(s) > 2 else 0.5)
                   for s in (d.get("opacity_stops") or [[0, 1], [1, 1]])]
            return cls(color_stops=cs, opacity_stops=os_, **common).sorted()
        start = QColor(d["start"]) if d.get("start") else QColor(fallback or QColor(0, 0, 0))
        end = QColor(d["end"]) if d.get("end") else QColor(255, 255, 255)
        return cls.two_color(start, end, **common)

    # ── sampling ────────────────────────────────────────────────────
    def color_at(self, t: float) -> QColor:
        g = self.sorted()
        if self.reverse:
            t = 1.0 - t
        t = min(1.0, max(0.0, t))
        a, b, u = _segment(g.color_stops, t)
        c = QColor(
            round(a.color.red() + (b.color.red() - a.color.red()) * u),
            round(a.color.green() + (b.color.green() - a.color.green()) * u),
            round(a.color.blue() + (b.color.blue() - a.color.blue()) * u))
        oa, ob, ou = _segment(g.opacity_stops, t)
        c.setAlphaF(min(1.0, max(0.0, oa.opacity + (ob.opacity - oa.opacity) * ou)))
        return c

    def qt_stops(self) -> list:
        """Stops for a QGradient: every real stop position, plus extra
        samples inside segments whose midpoint isn't linear (a QGradient
        can only interpolate linearly between its stops)."""
        g = self.sorted()
        positions = {0.0, 1.0}
        for stops in (g.color_stops, g.opacity_stops):
            for a, b in zip(stops, stops[1:]):
                positions.update((a.position, b.position))
                if abs(a.midpoint - 0.5) > 1e-3:
                    positions.update(a.position + (b.position - a.position) * k / 16 for k in range(1, 16))
        out = []
        for p in sorted(positions):
            p = min(1.0, max(0.0, p))
            out.append((p, self.color_at(p)))
        return out

    def merged_stops(self) -> list:
        return self.qt_stops()

    def lut(self, n: int = 256):
        import numpy as np
        arr = np.empty((n, 4), dtype=np.float32)   # premultiplied B, G, R, A in 0..255
        for i in range(n):
            c = self.color_at(i / (n - 1))
            a = c.alphaF()
            arr[i] = (c.blue() * a, c.green() * a, c.red() * a, a * 255.0)
        return arr

    # ── laying it out ───────────────────────────────────────────────
    # Two ways to place a gradient, one implementation (_axis_brush):
    # over a frame (shape fill, fill layer, Gradient Overlay style) with the
    # gradient's own angle/scale, or along a mouse drag (Gradient tool).

    def brush(self, frame: QRectF, frame_angle: float, to_device: QTransform,
              device_area=None) -> QBrush:
        """Fills `frame` (rotated by `frame_angle` around its center) using
        this gradient's angle and scale. For a painter whose transform has
        been reset to device space; `device_area` (QRect) bounds the
        texture of the diamond style."""
        c = frame.center()
        rot = QTransform().translate(c.x(), c.y()).rotate(frame_angle).translate(-c.x(), -c.y())
        a = math.radians(self.angle)
        dx, dy = math.cos(a), math.sin(a)
        k = max(0.01, self.scale / 100.0)
        half = (abs(frame.width() / 2 * dx) + abs(frame.height() / 2 * dy)) * k
        radius = math.hypot(frame.width() / 2, frame.height() / 2) * k
        return self._axis_brush(c, dx, dy, half, radius, self.angle, rot * to_device, device_area)

    def brush_for_drag(self, start: QPointF, end: QPointF, to_device: QTransform = QTransform(),
                       device_area=None) -> QBrush:
        """Photoshop Gradient-tool geometry: linear runs start->end;
        radial/angle/reflected/diamond are centered on `start` with the
        drag length as their size and the drag direction as their angle."""
        vx, vy = end.x() - start.x(), end.y() - start.y()
        length = max(0.5, math.hypot(vx, vy))
        dx, dy = vx / length, vy / length
        angle = math.degrees(math.atan2(vy, vx))
        if self.style == "linear":
            center = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            return self._axis_brush(center, dx, dy, length / 2, length, angle, to_device, device_area)
        return self._axis_brush(QPointF(start), dx, dy, length, length, angle, to_device, device_area)

    def _axis_brush(self, c: QPointF, dx: float, dy: float, half: float, radius: float,
                    angle: float, to_dev: QTransform, device_area) -> QBrush:
        half = max(half, 0.5)
        if self.style == "diamond":
            return self._diamond_brush(c, dx, dy, half, to_dev, device_area)
        if self.style == "radial":
            grad: QGradient = QRadialGradient(c, max(0.5, radius))
        elif self.style == "angle":
            # Qt's conical angle runs counter-clockwise; ours is screen-
            # clockwise like every other angle in the app.
            grad = QConicalGradient(c, -angle)
        elif self.style == "reflected":
            grad = QLinearGradient(c, QPointF(c.x() + dx * half, c.y() + dy * half))
            grad.setSpread(QGradient.Spread.ReflectSpread)
        else:
            grad = QLinearGradient(QPointF(c.x() - dx * half, c.y() - dy * half),
                                   QPointF(c.x() + dx * half, c.y() + dy * half))
        stops = self.qt_stops()
        if self.style == "angle":
            # ...and sweeps counter-clockwise: mirror the stops so it goes
            # clockwise from the angle, matching Photoshop.
            stops = [(1.0 - p, col) for p, col in reversed(stops)]
        grad.setStops(stops)
        brush = QBrush(grad)
        brush.setTransform(to_dev)
        return brush

    def _diamond_brush(self, c, dx, dy, half, to_dev, device_area) -> QBrush:
        """No native Qt diamond gradient: rasterize one at device
        resolution over the area being painted."""
        import numpy as np
        from core.pixel_buffer import qimage_argb_view
        if device_area is None or device_area.isEmpty():
            return QBrush(self.color_at(0.0))
        w, h = device_area.width(), device_area.height()
        inv, ok = to_dev.inverted()
        if not ok:
            return QBrush(self.color_at(0.0))
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        xs += device_area.x() + 0.5
        ys += device_area.y() + 0.5
        lx = inv.m11() * xs + inv.m21() * ys + inv.dx() - c.x()
        ly = inv.m12() * xs + inv.m22() * ys + inv.dy() - c.y()
        u = lx * dx + ly * dy
        v = -lx * dy + ly * dx
        t = np.clip((np.abs(u) + np.abs(v)) / half, 0.0, 1.0)
        lut = self.lut(256)
        px = lut[(t * 255).astype(np.int32)]
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        view = qimage_argb_view(img, writable=True)
        view[:, :w, :] = np.clip(px + 0.5, 0, 255).astype(np.uint8)
        del view
        brush = QBrush(img)
        brush.setTransform(QTransform.fromTranslate(device_area.x(), device_area.y()))
        return brush


def _opaque(c) -> QColor:
    c = QColor(c)
    c.setAlpha(255)
    return c


# ── presets ────────────────────────────────────────────────────────────────

def builtin_presets(fg: QColor, bg: QColor) -> list:
    """(translation key, Gradient) pairs shown first in the editor."""
    def stops(*cs):
        n = len(cs) - 1
        return Gradient(color_stops=[ColorStop(i / n, QColor(c)) for i, c in enumerate(cs)])
    fg_t = Gradient(color_stops=[ColorStop(0, _opaque(fg)), ColorStop(1, _opaque(fg))],
                    opacity_stops=[OpacityStop(0, 1.0), OpacityStop(1, 0.0)])
    return [
        ("gradient_editor.preset.fg_bg", Gradient.two_color(fg, bg)),
        ("gradient_editor.preset.fg_transparent", fg_t),
        ("gradient_editor.preset.black_white", stops("#000000", "#ffffff")),
        ("gradient_editor.preset.white_black", stops("#ffffff", "#000000")),
        ("gradient_editor.preset.rainbow", stops("#ff0000", "#ff9900", "#ffff00", "#00ff00",
                                                 "#0066ff", "#4b0082", "#9400d3")),
        ("gradient_editor.preset.sunset", stops("#2b1055", "#d53369", "#f8b500")),
        ("gradient_editor.preset.ocean", stops("#001f3f", "#0074d9", "#7fdbff")),
        ("gradient_editor.preset.chrome", stops("#2d2d2d", "#f2f2f2", "#5a5a5a", "#ffffff", "#3a3a3a")),
        ("gradient_editor.preset.copper", stops("#3b1f0e", "#c46d3b", "#f5c49a", "#8c4a24")),
        ("gradient_editor.preset.violet_orange", stops("#5b2a86", "#ff8c2b")),
    ]
