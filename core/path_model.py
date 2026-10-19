"""Bezier paths as the pen tools edit them — the work path, saved paths and
the nodes of Pen-style shape layers all use this format.

A path is {"nodes": [...], "closed": bool} — the component being edited —
plus optional "subpaths": a list of finished components of the same shape
(Make Work Path from a selection with several parts or holes, or a new
component started after closing one, as in Photoshop). A node is
{"p": anchor, "c1": incoming handle, "c2": outgoing handle} (QPointF);
a handle lying on its anchor means a corner. A component may carry "op"
("unite" / "subtract" / "intersect" / "exclude"): how a shape layer
combines it with the components before it. Old paths without "subpaths"
or "op" read as before."""
import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainterPath

PATH_OPS = ("unite", "subtract", "intersect", "exclude")


# ── bezier math ──────────────────────────────────────────────────────────────

def lerp(p1: QPointF, p2: QPointF, t: float) -> QPointF:
    return QPointF(p1.x() + (p2.x() - p1.x()) * t, p1.y() + (p2.y() - p1.y()) * t)


def bezier_point(p0, p1, p2, p3, t):
    q0 = lerp(p0, p1, t); q1 = lerp(p1, p2, t); q2 = lerp(p2, p3, t)
    r0 = lerp(q0, q1, t); r1 = lerp(q1, q2, t)
    return lerp(r0, r1, t)


def split_bezier(p0, p1, p2, p3, t):
    """De Casteljau split at t: (q0, r0, s0, r1, q2) — the first half is
    p0 q0 r0 s0, the second s0 r1 q2 p3."""
    q0 = lerp(p0, p1, t); q1 = lerp(p1, p2, t); q2 = lerp(p2, p3, t)
    r0 = lerp(q0, q1, t); r1 = lerp(q1, q2, t)
    s0 = lerp(r0, r1, t)
    return q0, r0, s0, r1, q2


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _same_point(a: QPointF, b: QPointF, eps: float = 1e-6) -> bool:
    return abs(a.x() - b.x()) < eps and abs(a.y() - b.y()) < eps


def corner_node(p: QPointF) -> dict:
    return {"p": QPointF(p), "c1": QPointF(p), "c2": QPointF(p)}


# ── components ───────────────────────────────────────────────────────────────

def path_components(wp: dict | None) -> list[dict]:
    """Every component with nodes, the edited one last."""
    if not wp:
        return []
    comps = [c for c in wp.get("subpaths", []) if c.get("nodes")]
    if wp.get("nodes"):
        comp = {"nodes": wp["nodes"], "closed": wp.get("closed", False)}
        if wp.get("op"):
            comp["op"] = wp["op"]
        comps.append(comp)
    return comps


def has_path(wp: dict | None) -> bool:
    return bool(path_components(wp))


def clear_path(wp: dict) -> None:
    wp["nodes"], wp["closed"], wp["subpaths"] = [], False, []
    wp.pop("op", None)


def start_new_component(wp: dict, op: str | None = None) -> None:
    """Keep the edited component as finished; the next nodes start a new
    one (combined by `op` on a shape layer)."""
    if wp.get("nodes"):
        done = {"nodes": wp["nodes"], "closed": wp.get("closed", False)}
        if wp.get("op"):
            done["op"] = wp["op"]
        wp.setdefault("subpaths", []).append(done)
    wp["nodes"], wp["closed"] = [], False
    if op:
        wp["op"] = op
    else:
        wp.pop("op", None)


def focus_component(wp: dict, index: int) -> None:
    """Make component `index` (of path_components) the edited one."""
    comps = path_components(wp)
    if not 0 <= index < len(comps) or index == len(comps) - 1 and wp.get("nodes"):
        return
    chosen = comps.pop(index)
    wp["subpaths"] = comps
    wp["nodes"], wp["closed"] = chosen["nodes"], chosen["closed"]
    if chosen.get("op"):
        wp["op"] = chosen["op"]
    else:
        wp.pop("op", None)


def component_at(wp: dict, pos, tolerance: float) -> int | None:
    """Index of the component with a node, handle or curve point nearest
    to `pos` within `tolerance`, or None."""
    best, best_d = None, tolerance
    for ci, comp in enumerate(path_components(wp)):
        nodes = comp["nodes"]
        pts = [q for n in nodes for q in (n["p"], n["c1"], n["c2"])]
        segs = len(nodes) if comp["closed"] else len(nodes) - 1
        for i in range(max(0, segs)):
            n0, n1 = nodes[i], nodes[(i + 1) % len(nodes)]
            pts += [bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], k / 16) for k in range(1, 16)]
        for q in pts:
            d = math.hypot(pos.x() - q.x(), pos.y() - q.y())
            if d < best_d:
                best, best_d = ci, d
    return best


def segment_at(nodes: list, closed: bool, pos, tolerance: float):
    """(segment index, t) of the curve point nearest `pos` within
    `tolerance`, or None. Segment i runs from node i to node i+1."""
    best, best_d = None, tolerance
    segs = len(nodes) if closed else len(nodes) - 1
    for i in range(max(0, segs)):
        n0, n1 = nodes[i], nodes[(i + 1) % len(nodes)]
        for k in range(1, 40):
            t = k / 40
            q = bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], t)
            d = math.hypot(pos.x() - q.x(), pos.y() - q.y())
            if d < best_d:
                best, best_d = (i, t), d
    return best


def insert_node_on_segment(nodes: list, seg: int, t: float) -> int:
    """Split segment `seg` at `t` keeping its shape; returns the new
    node's index."""
    n0, n1 = nodes[seg], nodes[(seg + 1) % len(nodes)]
    q0, r0, s0, r1, q2 = split_bezier(n0["p"], n0["c2"], n1["c1"], n1["p"], t)
    n0["c2"], n1["c1"] = q0, q2
    nodes.insert(seg + 1, {"p": s0, "c1": r0, "c2": r1})
    return seg + 1


def clone_path(wp: dict | None) -> dict:
    """Deep copy, finished components and ops included."""
    def comp(c):
        out = {"nodes": [{"p": QPointF(n["p"]), "c1": QPointF(n["c1"]), "c2": QPointF(n["c2"])}
                         for n in c.get("nodes", [])],
               "closed": c.get("closed", False)}
        if c.get("op"):
            out["op"] = c["op"]
        return out
    if not wp:
        return {"nodes": [], "closed": False}
    clone = comp(wp)
    if wp.get("subpaths"):
        clone["subpaths"] = [comp(c) for c in wp["subpaths"]]
    return clone


def translate_path(wp: dict | None, dx: float, dy: float) -> None:
    """Move every node (and handle) of every component in place."""
    for comp in path_components(wp):
        for n in comp["nodes"]:
            for key in ("p", "c1", "c2"):
                n[key] = QPointF(n[key].x() + dx, n[key].y() + dy)


# ── QPainterPath conversion ──────────────────────────────────────────────────

def _append_component(path: QPainterPath, comp: dict) -> None:
    nodes = comp["nodes"]
    path.moveTo(nodes[0]["p"])
    for i in range(1, len(nodes)):
        n0, n1 = nodes[i - 1], nodes[i]
        path.cubicTo(n0["c2"], n1["c1"], n1["p"])
    if comp.get("closed") and len(nodes) > 1:
        n0, n1 = nodes[-1], nodes[0]
        path.cubicTo(n0["c2"], n1["c1"], n1["p"])
        path.closeSubpath()


def build_bezier_path(wp: dict) -> QPainterPath:
    """Single source of truth for turning a work path / saved path (format
    above) into a QPainterPath — the pen tools' overlay, the Paths panel's
    Make Selection/Fill/Stroke, Render filters."""
    path = QPainterPath()
    for comp in path_components(wp):
        _append_component(path, comp)
    return path


def build_shape_path(wp: dict) -> QPainterPath:
    """A shape layer's outline. Components without an op simply add up
    (odd-even, so a selection's holes stay holes); once any component has
    an op, they're combined in order like Photoshop's path operations."""
    comps = path_components(wp)
    if not any(c.get("op") for c in comps):
        return build_bezier_path(wp)
    from core.shape_model import combine_paths
    result = QPainterPath()
    for i, comp in enumerate(comps):
        part = QPainterPath()
        _append_component(part, comp)
        if len(comp["nodes"]) < 2:
            continue
        if i == 0 or result.isEmpty():
            result = part
        else:
            result = combine_paths(result, part, comp.get("op") or "unite")
    return result


def path_to_work_path(path: QPainterPath) -> dict:
    """The inverse of build_bezier_path: a QPainterPath back into the work
    path format (lines become corner nodes). A subpath that ends where it
    started is closed; its closing segment's handle goes back onto the
    first node."""
    comps, nodes = [], None
    E = QPainterPath.ElementType
    i, n = 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        pt = QPointF(e.x, e.y)
        if e.type == E.MoveToElement:
            nodes = [corner_node(pt)]
            comps.append(nodes)
            i += 1
        elif e.type == E.CurveToElement and nodes and i + 2 < n:
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            nodes[-1]["c2"] = pt
            nodes.append({"p": QPointF(end.x, end.y), "c1": QPointF(c2.x, c2.y),
                          "c2": QPointF(end.x, end.y)})
            i += 3
        else:                                   # LineTo
            if nodes is not None:
                nodes.append(corner_node(pt))
            i += 1
    result = []
    for nodes in comps:
        closed = len(nodes) > 2 and _same_point(nodes[0]["p"], nodes[-1]["p"])
        if closed:
            nodes[0]["c1"] = nodes.pop()["c1"]
        if len(nodes) > 1:
            result.append({"nodes": nodes, "closed": closed})
    if not result:
        return {"nodes": [], "closed": False, "subpaths": []}
    last = result.pop()
    return {"nodes": last["nodes"], "closed": last["closed"], "subpaths": result}


# ── rounding corners ─────────────────────────────────────────────────────────

def _unit(dx: float, dy: float):
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-9 else None


def _tangent_in(prev: dict, n: dict):
    """Direction the curve arrives at `n` with (from prev)."""
    for q in (n["c1"], prev["c2"], prev["p"]):
        u = _unit(n["p"].x() - q.x(), n["p"].y() - q.y())
        if u:
            return u
    return None


def _tangent_out(n: dict, nxt: dict):
    """Direction the curve leaves `n` with (towards nxt)."""
    for q in (n["c2"], nxt["c1"], nxt["p"]):
        u = _unit(q.x() - n["p"].x(), q.y() - n["p"].y())
        if u:
            return u
    return None


def _segment_samples(n0, n1, steps=48):
    pts = [bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], k / steps) for k in range(steps + 1)]
    return pts


def _t_at_distance_from_end(n0, n1, d, from_start: bool) -> float:
    """Curve parameter whose arc distance from the start (or the end) of
    segment n0→n1 is about `d`."""
    pts = _segment_samples(n0, n1)
    steps = len(pts) - 1
    order = range(steps) if from_start else range(steps, 0, -1)
    acc = 0.0
    for k in order:
        a, b = (pts[k], pts[k + 1]) if from_start else (pts[k], pts[k - 1])
        seg = _dist(a, b)
        if acc + seg >= d:
            frac = (d - acc) / seg if seg > 0 else 0.0
            return (k + frac) / steps if from_start else (k - frac) / steps
        acc += seg
    return 1.0 if from_start else 0.0


def _arc_length(n0, n1) -> float:
    pts = _segment_samples(n0, n1, 24)
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def _sub_bezier(n0: dict, n1: dict, ts: float, te: float):
    """The piece [ts, te] of segment n0→n1 as (start, h1, h2, end)."""
    p0, p1, p2, p3 = n0["p"], n0["c2"], n1["c1"], n1["p"]
    if te < 1.0:
        q0, r0, s0, _r1, _q2 = split_bezier(p0, p1, p2, p3, te)
        p1, p2, p3 = q0, r0, s0
    if ts > 0.0:
        _q0, _r0, s0, r1, q2 = split_bezier(p0, p1, p2, p3, ts / te if te > 0 else 0.0)
        p0, p1, p2 = s0, r1, q2
    return p0, p1, p2, p3


def _round_component(nodes: list, closed: bool, radius: float) -> int:
    """Replace each sharp corner of one component by a circular-looking
    fillet of `radius`. Returns how many corners were rounded.

    Two passes on the original geometry: decide every corner's cut
    distance first, then trim each segment once at both ends and rebuild
    the nodes — so neighbouring corners never cut an already-cut curve."""
    count = len(nodes)
    n_segs = count if closed else count - 1
    if n_segs < 2:
        return 0
    seg = lambda j: (nodes[j], nodes[(j + 1) % count])
    lengths = [_arc_length(*seg(j)) for j in range(n_segs)]
    plans = {}                                       # node -> (d, handle)
    for i in range(count):
        if not closed and (i == 0 or i == count - 1):
            continue
        prev, n, nxt = nodes[i - 1], nodes[i], nodes[(i + 1) % count]
        tin, tout = _tangent_in(prev, n), _tangent_out(n, nxt)
        if not tin or not tout:
            continue
        turn = math.acos(max(-1.0, min(1.0, tin[0] * tout[0] + tin[1] * tout[1])))
        if turn < math.radians(8) or turn > math.radians(178):
            continue                                 # smooth already / a spike
        d = min(radius * math.tan(turn / 2), 0.45 * lengths[i - 1], 0.45 * lengths[i % n_segs])
        if d <= 0.05:
            continue
        r_eff = d / math.tan(turn / 2)
        plans[i] = (d, 4.0 / 3.0 * math.tan(turn / 4) * r_eff)
    if not plans:
        return 0

    trimmed = []
    for j in range(n_segs):
        a, b = seg(j)
        ia, ib = j, (j + 1) % count
        ts = _t_at_distance_from_end(a, b, plans[ia][0], from_start=True) if ia in plans else 0.0
        te = _t_at_distance_from_end(a, b, plans[ib][0], from_start=False) if ib in plans else 1.0
        trimmed.append(_sub_bezier(a, b, ts, te))

    out = []
    for i in range(count):
        n = nodes[i]
        seg_in = trimmed[i - 1] if (closed or i > 0) else None
        seg_out = trimmed[i] if i < n_segs else None
        if i in plans:
            _d, handle = plans[i]
            end, h2 = seg_in[3], seg_in[2]
            u = _unit(end.x() - h2.x(), end.y() - h2.y()) or _tangent_in(nodes[i - 1], n)
            out.append({"p": end, "c1": h2,
                        "c2": QPointF(end.x() + u[0] * handle, end.y() + u[1] * handle)})
            start, h1 = seg_out[0], seg_out[1]
            u = _unit(h1.x() - start.x(), h1.y() - start.y()) or _tangent_out(n, nodes[(i + 1) % count])
            out.append({"p": start, "c1": QPointF(start.x() - u[0] * handle, start.y() - u[1] * handle),
                        "c2": h1})
        else:
            out.append({"p": QPointF(n["p"]),
                        "c1": QPointF(seg_in[2]) if seg_in else QPointF(n["c1"]),
                        "c2": QPointF(seg_out[1]) if seg_out else QPointF(n["c2"])})
    nodes[:] = out
    return len(plans)


def round_corners(wp: dict, radius: float) -> int:
    """Round every sharp corner of every component of `wp` in place (open
    paths keep their two ends). Returns the number of corners rounded."""
    if radius <= 0:
        return 0
    total = 0
    for comp in wp.get("subpaths", []):
        total += _round_component(comp["nodes"], comp.get("closed", False), radius)
    if wp.get("nodes"):
        total += _round_component(wp["nodes"], wp.get("closed", False), radius)
    return total
