"""Make Work Path from a selection (Photoshop: Paths panel > Make Work
Path, tolerance in pixels).

Each outline of the selection — separate parts and holes alike — becomes
one closed component of the work path (tools/pen_tool.py format). The
outline is simplified to within `tolerance` px (Douglas–Peucker), then
nodes where the outline bends gently get smooth handles and sharp turns
stay corners, so a rectangle stays four corner points and an ellipse
becomes a few smooth ones instead of hundreds of straight steps.
"""
import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainterPath

SMOOTH_TURN_DEG = 50.0   # turns gentler than this get smooth handles


def selection_to_work_path(selection: QPainterPath, tolerance: float = 2.0) -> dict:
    comps = []
    for poly in selection.simplified().toSubpathPolygons():
        pts = [QPointF(p) for p in poly]
        if len(pts) > 1 and _close(pts[0], pts[-1]):
            pts.pop()
        pts = _simplify_closed(pts, max(0.1, float(tolerance)))
        if len(pts) >= 3:
            comps.append({"nodes": _nodes(pts), "closed": True})
    if not comps:
        return {"nodes": [], "closed": False}
    edited = comps.pop()
    return {"nodes": edited["nodes"], "closed": True, "subpaths": comps}


def _close(a, b, eps=1e-6) -> bool:
    return abs(a.x() - b.x()) < eps and abs(a.y() - b.y()) < eps


def _seg_distance(p, a, b) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / length2))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


def _douglas_peucker(pts, tol):
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, best_d = None, tol
        for k in range(i + 1, j):
            d = _seg_distance(pts[k], pts[i], pts[j])
            if d > best_d:
                best, best_d = k, d
        if best is not None:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [p for p, k in zip(pts, keep) if k]


def _simplify_closed(pts, tol):
    """A closed outline: split at the point farthest from the first, so
    neither half degenerates, and simplify each half."""
    if len(pts) < 4:
        return pts
    far = max(range(len(pts)), key=lambda k: math.hypot(pts[k].x() - pts[0].x(), pts[k].y() - pts[0].y()))
    first = _douglas_peucker(pts[:far + 1], tol)
    second = _douglas_peucker(pts[far:] + [pts[0]], tol)
    return first[:-1] + second[:-1]


def _nodes(pts):
    n = len(pts)
    nodes = []
    for i, p in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % n]
        a1 = math.atan2(p.y() - prev.y(), p.x() - prev.x())
        a2 = math.atan2(nxt.y() - p.y(), nxt.x() - p.x())
        turn = abs(math.degrees((a2 - a1 + math.pi) % (2 * math.pi) - math.pi))
        if turn >= SMOOTH_TURN_DEG:
            nodes.append({"p": QPointF(p), "c1": QPointF(p), "c2": QPointF(p)})
            continue
        tx, ty = nxt.x() - prev.x(), nxt.y() - prev.y()
        tl = math.hypot(tx, ty) or 1.0
        tx, ty = tx / tl, ty / tl
        d_in = math.hypot(p.x() - prev.x(), p.y() - prev.y()) / 3
        d_out = math.hypot(nxt.x() - p.x(), nxt.y() - p.y()) / 3
        nodes.append({"p": QPointF(p),
                      "c1": QPointF(p.x() - tx * d_in, p.y() - ty * d_in),
                      "c2": QPointF(p.x() + tx * d_out, p.y() + ty * d_out)})
    return nodes
