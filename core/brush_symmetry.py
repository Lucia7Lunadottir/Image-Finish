"""Brush symmetry (mirror painting): one place for the geometry.

The mirror axes come from the tool options `brush_mirror_x/_y` (on/off)
and `brush_mirror_cx/_cy` (centre as a fraction of the document size).
This used to be re-derived from the options in seven places — four paint
paths in tools/brush_tool.py, the canvas press handler, its cursor
choice and the brush-cursor overlay — plus the axes overlay.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BrushSymmetry:
    mirror_x: bool
    mirror_y: bool
    cx: float           # document coordinates of the mirror centre
    cy: float

    HIT_RADIUS_PX = 15  # screen pixels around the centre handle

    @classmethod
    def from_opts(cls, opts: dict, doc_w: int, doc_h: int) -> "BrushSymmetry":
        return cls(bool(opts.get("brush_mirror_x", False)),
                   bool(opts.get("brush_mirror_y", False)),
                   doc_w * float(opts.get("brush_mirror_cx", 0.5)),
                   doc_h * float(opts.get("brush_mirror_cy", 0.5)))

    @property
    def active(self) -> bool:
        return self.mirror_x or self.mirror_y

    def mirror_all(self, points: list) -> list:
        """`points` ((x, y) tuples) plus their mirror images: across the
        vertical axis first, then everything across the horizontal one."""
        out = list(points)
        if self.mirror_x:
            out += [(2 * self.cx - x, y) for x, y in out]
        if self.mirror_y:
            out += [(x, 2 * self.cy - y) for x, y in out]
        return out

    def mirror_segments(self, segments: list) -> list:
        """Same for ((x1, y1), (x2, y2)) segments."""
        out = list(segments)
        if self.mirror_x:
            out += [((2 * self.cx - a[0], a[1]), (2 * self.cx - b[0], b[1])) for a, b in out]
        if self.mirror_y:
            out += [((a[0], 2 * self.cy - a[1]), (b[0], 2 * self.cy - b[1])) for a, b in out]
        return out

    def near_center(self, x: float, y: float, zoom: float) -> bool:
        """Is document point (x, y) on the centre handle at this zoom?"""
        r = self.HIT_RADIUS_PX / max(0.01, zoom)
        return (x - self.cx) ** 2 + (y - self.cy) ** 2 <= r * r
