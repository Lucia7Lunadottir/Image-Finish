"""Warp Text (Photoshop's Type > Warp Text): bends a text layer's glyph
outlines while the text stays live — editable, vector, sharp at any zoom.

A warp is a style plus Bend, Horizontal and Vertical Distortion (each
-100..100 %, as in Photoshop) and an orientation. Each style is a
`WarpStyle` mapping a point of the text's frame, in "half-size" units
(x in -hw..hw, y in -hh..hh around the frame centre, y down), to its
warped position; distortions are applied on top. The shapes follow
Photoshop's presets by look, not by Adobe's exact (undocumented) mesh
formulas.

`TextWarp.map_path` warps a QPainterPath: curves are split into short
pieces whose control points are mapped, lines become short cubics, so
the result stays smooth instead of turning into a polyline."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath


# ── styles ───────────────────────────────────────────────────────────────────

class WarpStyle:
    """One warp preset. `bend` is -1..1; x, y in half-size units.
    Displacements scale with the frame's smaller half-size, so a vertical
    warp of a long line bends it as much as a horizontal one, instead of
    by its whole length."""
    key = ""

    def map(self, x: float, y: float, hw: float, hh: float, bend: float):
        raise NotImplementedError


class _Arc(WarpStyle):
    """The text follows a circular arc; letters turn with it."""
    key = "arc"

    def map(self, x, y, hw, hh, bend):
        sign = 1.0 if bend > 0 else -1.0
        theta_max = abs(bend) * math.pi / 2                 # ±90° at 100 %
        if theta_max < 1e-4:
            return x, y
        # The centre line keeps its length — unless that circle would be
        # smaller than the band being bent (tall text, or vertical warp of
        # a wide line): then the far side would fold through the centre.
        radius = max(hw / theta_max, hh * 1.1)
        yy = y * sign
        theta = x / hw * theta_max
        r = radius - yy
        nx = r * math.sin(theta)
        ny = radius - r * math.cos(theta)
        return nx, ny * sign


class _ArcLower(WarpStyle):
    key = "arc_lower"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y + bend * min(hw, hh) * (1 - u * u) * (v + 1) / 2


class _ArcUpper(WarpStyle):
    key = "arc_upper"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y - bend * min(hw, hh) * (1 - u * u) * (1 - v) / 2


class _Arch(WarpStyle):
    """The whole text arches up; letters stay upright."""
    key = "arch"

    def map(self, x, y, hw, hh, bend):
        u = x / hw
        return x, y - bend * min(hw, hh) * (1 - u * u)


class _Bulge(WarpStyle):
    key = "bulge"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y + bend * min(hw, hh) * (1 - u * u) * v * 0.6


class _ShellLower(WarpStyle):
    key = "shell_lower"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y - bend * min(hw, hh) * u * u * (v + 1) / 2


class _ShellUpper(WarpStyle):
    key = "shell_upper"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y + bend * min(hw, hh) * u * u * (1 - v) / 2


class _Flag(WarpStyle):
    key = "flag"

    def map(self, x, y, hw, hh, bend):
        u = x / hw
        return x, y + bend * min(hw, hh) * 0.6 * math.sin(math.pi * u)


class _Wave(WarpStyle):
    """Like Flag, but top and bottom swing out of phase."""
    key = "wave"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x, y + bend * min(hw, hh) * 0.5 * math.sin(math.pi * u + v * math.pi / 4)


class _Fish(WarpStyle):
    key = "fish"

    def map(self, x, y, hw, hh, bend):
        u = x / hw
        scale = 1 + bend * 0.7 * (1 - u * u) * (1 - 0.5 * u)
        return x, y * scale + bend * min(hw, hh) * 0.25 * math.sin(math.pi * u)


class _Rise(WarpStyle):
    key = "rise"

    def map(self, x, y, hw, hh, bend):
        u = x / hw
        return x, y - bend * min(hw, hh) * math.sin(math.pi * u / 2)


class _Fisheye(WarpStyle):
    key = "fisheye"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        r2 = u * u + v * v
        if r2 >= 1:
            return x, y
        f = 1 + bend * 0.5 * (1 - r2) ** 2          # smooth to nothing at the rim
        return x * f, y * f


class _Inflate(WarpStyle):
    key = "inflate"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x * (1 + bend * 0.12 * (1 - v * v)), y * (1 + bend * 0.5 * (1 - u * u))


class _Squeeze(WarpStyle):
    key = "squeeze"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        return x * (1 + bend * 0.25 * (1 - v * v)), y * (1 - bend * 0.5 * (1 - u * u))


class _Twist(WarpStyle):
    key = "twist"

    def map(self, x, y, hw, hh, bend):
        u, v = x / hw, y / hh
        r = math.hypot(u, v)
        if r >= 1:
            return x, y
        # Rotation around the centre, strongest there, fading out at the
        # rim — in real (unstretched) coordinates, so letters turn instead
        # of shearing apart.
        a = bend * (math.pi / 6) * (1 - r) ** 2
        c, s = math.cos(a), math.sin(a)
        return x * c - y * s, x * s + y * c


WARP_STYLES: dict[str, WarpStyle] = {s.key: s for s in (
    _Arc(), _ArcLower(), _ArcUpper(), _Arch(), _Bulge(), _ShellLower(), _ShellUpper(),
    _Flag(), _Wave(), _Fish(), _Rise(), _Fisheye(), _Inflate(), _Squeeze(), _Twist(),
)}
STYLE_KEYS = ("none",) + tuple(WARP_STYLES)


def _clamp100(v) -> float:
    try:
        return max(-100.0, min(100.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


# ── the warp ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TextWarp:
    style: str = "none"
    horizontal: bool = True
    bend: float = 50.0          # %
    hdist: float = 0.0          # % horizontal distortion
    vdist: float = 0.0          # % vertical distortion

    def is_active(self) -> bool:
        """A style is chosen and it changes something (as in Photoshop, the
        distortions need a style too)."""
        return self.style in WARP_STYLES and bool(self.bend or self.hdist or self.vdist)

    # ── serialization ───────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {"style": self.style, "horizontal": self.horizontal,
                "bend": self.bend, "hdist": self.hdist, "vdist": self.vdist}

    @classmethod
    def from_dict(cls, d: dict | None) -> "TextWarp":
        d = d or {}
        style = d.get("style", "none")
        return cls(style=style if style in STYLE_KEYS else "none",
                   horizontal=bool(d.get("horizontal", True)),
                   bend=_clamp100(d.get("bend", 50)), hdist=_clamp100(d.get("hdist", 0)),
                   vdist=_clamp100(d.get("vdist", 0)))

    # ── geometry ────────────────────────────────────────────────────
    def map_point(self, p: QPointF, frame: QRectF) -> QPointF:
        cx, cy = frame.center().x(), frame.center().y()
        hw, hh = max(frame.width() / 2, 1e-6), max(frame.height() / 2, 1e-6)
        x, y = p.x() - cx, p.y() - cy
        if not self.horizontal:                 # vertical: warp in the transposed frame
            x, y, hw, hh = y, x, hh, hw
        style = WARP_STYLES.get(self.style)
        if style is not None:
            x, y = style.map(x, y, hw, hh, self.bend / 100.0)
        # Distortions: perspective-like scaling across the frame.
        hd, vd = self.hdist / 100.0, self.vdist / 100.0
        if hd:
            y *= max(0.05, 1 + hd * 0.6 * x / hw)
            x *= 1 + hd * 0.2 * (x / hw)
        if vd:
            x *= max(0.05, 1 + vd * 0.6 * y / hh)
            y *= 1 + vd * 0.2 * (y / hh)
        if not self.horizontal:
            x, y = y, x
        return QPointF(cx + x, cy + y)

    def map_path(self, path: QPainterPath, frame: QRectF) -> QPainterPath:
        """`path` warped within `frame` (the text's own, unwarped frame)."""
        step = max(frame.width(), frame.height()) / 48.0 or 1.0
        m = lambda q: self.map_point(q, frame)
        out = QPainterPath()
        out.setFillRule(path.fillRule())
        E = QPainterPath.ElementType
        i, n = 0, path.elementCount()
        cur = start = QPointF()
        while i < n:
            e = path.elementAt(i)
            pt = QPointF(e.x, e.y)
            if e.type == E.MoveToElement:
                if i and _same(cur, start):
                    out.closeSubpath()
                out.moveTo(m(pt))
                cur = start = pt
                i += 1
            elif e.type == E.CurveToElement and i + 2 < n:
                c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
                pts = (cur, pt, QPointF(c2.x, c2.y), QPointF(end.x, end.y))
                length = sum(_dist(a, b) for a, b in zip(pts, pts[1:]))
                for piece in _split_cubic(pts, max(1, math.ceil(length / step))):
                    out.cubicTo(m(piece[1]), m(piece[2]), m(piece[3]))
                cur = pts[3]
                i += 3
            else:                                # LineTo: short cubics, so it can bend
                k = max(1, math.ceil(_dist(cur, pt) / step))
                for j in range(k):
                    a = _lerp(cur, pt, j / k)
                    b = _lerp(cur, pt, (j + 1) / k)
                    out.cubicTo(m(_lerp(a, b, 1 / 3)), m(_lerp(a, b, 2 / 3)), m(b))
                cur = pt
                i += 1
        if n and _same(cur, start):
            out.closeSubpath()
        return out


def _same(a: QPointF, b: QPointF) -> bool:
    return abs(a.x() - b.x()) < 1e-6 and abs(a.y() - b.y()) < 1e-6


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _lerp(a: QPointF, b: QPointF, t: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)


def _split_cubic(pts, k: int):
    """A cubic as k consecutive cubics (equal parameter steps)."""
    pieces = []
    p0, p1, p2, p3 = pts
    for j in range(k, 0, -1):
        t = 1.0 / j                              # split off the next 1/k of what's left
        q0, q1, q2 = _lerp(p0, p1, t), _lerp(p1, p2, t), _lerp(p2, p3, t)
        r0, r1 = _lerp(q0, q1, t), _lerp(q1, q2, t)
        s0 = _lerp(r0, r1, t)
        pieces.append((p0, q0, r0, s0))
        p0, p1, p2 = s0, r1, q2
    return pieces
