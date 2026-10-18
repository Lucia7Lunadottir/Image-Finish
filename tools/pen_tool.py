import math
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainterPath, QColor, QPen
from tools.base_tool import BaseTool

def _lerp(p1: QPointF, p2: QPointF, t: float) -> QPointF:
    return QPointF(p1.x() + (p2.x() - p1.x()) * t, p1.y() + (p2.y() - p1.y()) * t)

def _bezier_point(p0, p1, p2, p3, t):
    q0 = _lerp(p0, p1, t); q1 = _lerp(p1, p2, t); q2 = _lerp(p2, p3, t)
    r0 = _lerp(q0, q1, t); r1 = _lerp(q1, q2, t)
    return _lerp(r0, r1, t)

def _split_bezier(p0, p1, p2, p3, t):
    q0 = _lerp(p0, p1, t); q1 = _lerp(p1, p2, t); q2 = _lerp(p2, p3, t)
    r0 = _lerp(q0, q1, t); r1 = _lerp(q1, q2, t)
    s0 = _lerp(r0, r1, t)
    return q0, r0, s0, r1, q2


# A work path / saved path is {"nodes": [...], "closed": bool} — the
# component the pen tools are editing — plus optional "subpaths": a list
# of finished components of the same shape (Make Work Path from a
# selection with several parts or holes, or a new component started after
# closing one, as in Photoshop). Old paths without "subpaths" read as
# before.

def path_components(wp: dict | None) -> list[dict]:
    """Every component with nodes, the edited one last."""
    if not wp:
        return []
    comps = [c for c in wp.get("subpaths", []) if c.get("nodes")]
    if wp.get("nodes"):
        comps.append({"nodes": wp["nodes"], "closed": wp.get("closed", False)})
    return comps


def has_path(wp: dict | None) -> bool:
    return bool(path_components(wp))


def clear_path(wp: dict) -> None:
    wp["nodes"], wp["closed"], wp["subpaths"] = [], False, []


def start_new_component(wp: dict) -> None:
    """Keep the edited component as finished; the next nodes start a new one."""
    if wp.get("nodes"):
        wp.setdefault("subpaths", []).append({"nodes": wp["nodes"], "closed": wp.get("closed", False)})
    wp["nodes"], wp["closed"] = [], False


def focus_component(wp: dict, index: int) -> None:
    """Make component `index` (of path_components) the edited one."""
    comps = path_components(wp)
    if not 0 <= index < len(comps) or index == len(comps) - 1 and wp.get("nodes"):
        return
    chosen = comps.pop(index)
    wp["subpaths"] = comps
    wp["nodes"], wp["closed"] = chosen["nodes"], chosen["closed"]


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
            pts += [_bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], k / 16) for k in range(1, 16)]
        for q in pts:
            d = math.hypot(pos.x() - q.x(), pos.y() - q.y())
            if d < best_d:
                best, best_d = ci, d
    return best


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


class BasePenTool(BaseTool):
    CONTEXT_MENU = "path"
    def __init__(self):
        super().__init__()
        self.current_pos = None

    def _get_wp(self, doc):
        if not hasattr(doc, "work_path"):
            doc.work_path = {"nodes": [], "closed": False}
        return doc.work_path

    def on_hover(self, pos, doc, fg, bg, opts):
        self.current_pos = QPointF(pos)

    def _build_path(self, wp) -> QPainterPath:
        return build_bezier_path(wp)

    def _focus_at(self, doc, pos, tolerance: float = 15):
        """Editing tools: the component under the click becomes the edited
        one (paths made from a selection have several)."""
        wp = self._get_wp(doc)
        idx = component_at(wp, pos, tolerance)
        if idx is not None:
            focus_component(wp, idx)
        return wp

    def draw_overlays(self, painter, pw, doc):
        wp = self._get_wp(doc)
        nodes = wp.get('nodes', [])
        if not has_path(wp): return

        path = self._build_path(wp)
        if nodes and getattr(self, 'name', '') == 'Pen' and self.current_pos and self.pointer_inside and not wp.get('closed') and getattr(self, 'dragging_idx', -1) == -1:
            n0 = nodes[-1]
            path.cubicTo(n0['c2'], self.current_pos, self.current_pos)

        painter.setPen(QPen(QColor(0, 150, 255), max(1.0, pw * 1.5)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setPen(QPen(QColor(0, 0, 0), pw))
        for n in nodes:
            painter.setBrush(QColor(255, 255, 255))
            painter.drawRect(QRectF(n['p'].x() - pw*2, n['p'].y() - pw*2, pw*4, pw*4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if n['c1'] != n['p']:
                painter.drawLine(n['c1'], n['p'])
                painter.drawEllipse(n['c1'], pw*2, pw*2)
            if n['c2'] != n['p']:
                painter.drawLine(n['c2'], n['p'])
                painter.drawEllipse(n['c2'], pw*2, pw*2)

    def perform_action(self, doc, action, fg_color):
        wp = self._get_wp(doc)
        if action == "clear":
            clear_path(wp)
            return None

        path = self._build_path(wp)
        if path.isEmpty(): return None
        clear_path(wp)
        return (action, path)

    def _dist(self, p1, p2): return math.hypot(p1.x() - p2.x(), p1.y() - p2.y())
    def needs_history_push(self): return True
    def cursor(self): return Qt.CursorShape.CrossCursor

class PenTool(BasePenTool):
    name = "Pen"
    icon = "✒️"
    shortcut = "P"
    def __init__(self):
        super().__init__()
        self.dragging_idx = -1

    def on_press(self, pos, doc, fg, bg, opts):
        self.current_pos = QPointF(pos)
        wp = self._get_wp(doc)
        if wp['closed']:
            start_new_component(wp)
        nodes = wp['nodes']
        if nodes and not wp['closed'] and self._dist(pos, nodes[0]['p']) < 10:
            wp['closed'] = True
            self.dragging_idx = 0
            return
        nodes.append({'p': QPointF(pos), 'c1': QPointF(pos), 'c2': QPointF(pos)})
        self.dragging_idx = len(nodes) - 1

    def on_move(self, pos, doc, fg, bg, opts):
        self.current_pos = QPointF(pos)
        if self.dragging_idx >= 0:
            node = self._get_wp(doc)['nodes'][self.dragging_idx]
            node['c2'] = QPointF(pos)
            node['c1'] = QPointF(node['p'].x() * 2.0 - node['c2'].x(), node['p'].y() * 2.0 - node['c2'].y())

    def on_release(self, pos, doc, fg, bg, opts):
        self.dragging_idx = -1

class FreeformPenTool(BasePenTool):
    name = "FreeformPen"
    icon = "✍️"
    shortcut = "P"

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._get_wp(doc)
        start_new_component(wp)
        wp['nodes'] = [{'p': QPointF(pos), 'c1': QPointF(pos), 'c2': QPointF(pos)}]

    def on_move(self, pos, doc, fg, bg, opts):
        nodes = self._get_wp(doc)['nodes']
        if not nodes: return
        if self._dist(pos, nodes[-1]['p']) > 15:
            nodes.append({'p': QPointF(pos), 'c1': QPointF(pos), 'c2': QPointF(pos)})

class CurvaturePenTool(BasePenTool):
    name = "CurvaturePen"
    icon = "〰️"
    shortcut = "P"
    def __init__(self):
        super().__init__()
        self.drag_idx = -1

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._get_wp(doc)
        nodes = wp['nodes']
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < 10:
                self.drag_idx = i
                return
        if nodes and not wp['closed'] and self._dist(pos, nodes[0]['p']) < 10:
            wp['closed'] = True
            self._smooth(wp); self.drag_idx = -1
            return
        if wp['closed']:
            start_new_component(wp)
            nodes = wp['nodes']
        nodes.append({'p': QPointF(pos), 'c1': QPointF(pos), 'c2': QPointF(pos)})
        self.drag_idx = len(nodes) - 1
        self._smooth(wp)

    def on_move(self, pos, doc, fg, bg, opts):
        if self.drag_idx >= 0:
            self._get_wp(doc)['nodes'][self.drag_idx]['p'] = QPointF(pos)
            self._smooth(self._get_wp(doc))

    def on_release(self, pos, doc, fg, bg, opts):
        self.drag_idx = -1

    def _smooth(self, wp):
        nodes = wp['nodes']
        n = len(nodes)
        closed = wp['closed']
        for i in range(n):
            prev_i = (i - 1) % n if closed else max(0, i - 1)
            next_i = (i + 1) % n if closed else min(n - 1, i + 1)
            p_prev, p, p_next = nodes[prev_i]['p'], nodes[i]['p'], nodes[next_i]['p']
            if not closed and (i == 0 or i == n - 1):
                nodes[i]['c1'] = p; nodes[i]['c2'] = p
                continue
            dx, dy = p_next.x() - p_prev.x(), p_next.y() - p_prev.y()
            d1, d2 = self._dist(p, p_prev), self._dist(p_next, p)
            total = d1 + d2
            if total == 0: continue
            t1, t2 = (d1 / total * 0.3), (d2 / total * 0.3)
            nodes[i]['c1'] = QPointF(p.x() - dx * t1, p.y() - dy * t1)
            nodes[i]['c2'] = QPointF(p.x() + dx * t2, p.y() + dy * t2)

class AddAnchorPointTool(BasePenTool):
    name = "AddAnchor"
    icon = "✒️+"
    shortcut = "P"

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._focus_at(doc, pos)
        nodes = wp['nodes']
        if len(nodes) < 2: return
        best_dist = float('inf')
        best_t, best_idx = 0, -1
        n_segments = len(nodes) if wp['closed'] else len(nodes) - 1
        for i in range(n_segments):
            n0, n1 = nodes[i], nodes[(i+1)%len(nodes)]
            for step in range(1, 20):
                t = step / 20.0
                pt = _bezier_point(n0['p'], n0['c2'], n1['c1'], n1['p'], t)
                d = self._dist(pos, pt)
                if d < best_dist:
                    best_dist = d; best_t = t; best_idx = i
        if best_dist < 15:
            n0, n1 = nodes[best_idx], nodes[(best_idx+1)%len(nodes)]
            q0, r0, s0, r1, q2 = _split_bezier(n0['p'], n0['c2'], n1['c1'], n1['p'], best_t)
            n0['c2'], n1['c1'] = q0, q2
            nodes.insert(best_idx + 1, {'p': s0, 'c1': r0, 'c2': r1})

class DeleteAnchorPointTool(BasePenTool):
    name = "DeleteAnchor"
    icon = "✒️-"
    shortcut = "P"
    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._focus_at(doc, pos)
        nodes = wp['nodes']
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < 10:
                nodes.pop(i)
                if len(nodes) < 3: wp['closed'] = False
                return

class ConvertPointTool(BasePenTool):
    name = "ConvertPoint"
    icon = "^"
    shortcut = "P"
    def __init__(self):
        super().__init__()
        self.drag_target = None

    def on_press(self, pos, doc, fg, bg, opts):
        self.drag_target = None
        nodes = self._focus_at(doc, pos)['nodes']
        for i, n in enumerate(nodes):
            # A handle lying on its anchor (corner point) is not a separate
            # target — the click goes to the anchor below.
            for key in ('c1', 'c2'):
                if self._dist(n[key], n['p']) > 1 and self._dist(pos, n[key]) < 8:
                    self.drag_target = (i, key); return
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < 8:
                if self._dist(n['p'], n['c1']) > 1 or self._dist(n['p'], n['c2']) > 1:
                    n['c1'] = QPointF(n['p']); n['c2'] = QPointF(n['p'])
                else:
                    self.drag_target = (i, 'smooth')
                return

    def on_move(self, pos, doc, fg, bg, opts):
        if not self.drag_target: return
        idx, ttype = self.drag_target
        n = self._get_wp(doc)['nodes'][idx]
        if ttype == 'c1': n['c1'] = QPointF(pos)
        elif ttype == 'c2': n['c2'] = QPointF(pos)
        elif ttype == 'smooth':
            n['c2'] = QPointF(pos)
            n['c1'] = QPointF(n['p'].x() * 2 - pos.x(), n['p'].y() * 2 - pos.y())

class PathSelectionTool(BasePenTool):
    name = "PathSelection"
    icon = "↖"
    shortcut = "A"
    def __init__(self):
        super().__init__()
        self._dragging = False
        self._start_pos = None
        self._orig_nodes = []
        self._moved = []

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._get_wp(doc)
        if not has_path(wp): return
        path = self._build_path(wp)
        # Check if we clicked near the path bounding box
        if path.boundingRect().adjusted(-10, -10, 10, 10).contains(QPointF(pos)):
            self._dragging = True
            self._start_pos = QPointF(pos)
            self._moved = [n for comp in path_components(wp) for n in comp['nodes']]
            self._orig_nodes = [{'p': QPointF(n['p']), 'c1': QPointF(n['c1']), 'c2': QPointF(n['c2'])} for n in self._moved]

    def on_move(self, pos, doc, fg, bg, opts):
        if not self._dragging: return
        delta = QPointF(pos) - self._start_pos
        for i, n in enumerate(self._moved):
            orig = self._orig_nodes[i]
            n['p'] = orig['p'] + delta
            n['c1'] = orig['c1'] + delta
            n['c2'] = orig['c2'] + delta

    def on_release(self, pos, doc, fg, bg, opts):
        self._dragging = False
        self._orig_nodes = []
        self._moved = []

    def cursor(self): return Qt.CursorShape.ArrowCursor

class DirectSelectionTool(ConvertPointTool):
    name = "DirectSelection"
    icon = "↗"
    shortcut = "A"
    def on_press(self, pos, doc, fg, bg, opts):
        self.drag_target = None
        nodes = self._focus_at(doc, pos)['nodes']
        for i, n in enumerate(nodes):
            # A handle lying on its anchor (corner point) is not a separate
            # target — the click goes to the anchor below.
            for key in ('c1', 'c2'):
                if self._dist(n[key], n['p']) > 1 and self._dist(pos, n[key]) < 8:
                    self.drag_target = (i, key); return
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < 8:
                self.drag_target = (i, 'p')
                self._start_pos = QPointF(pos)
                self._orig_n = {'p': QPointF(n['p']), 'c1': QPointF(n['c1']), 'c2': QPointF(n['c2'])}
                return

    def on_move(self, pos, doc, fg, bg, opts):
        if not self.drag_target: return
        idx, ttype = self.drag_target
        n = self._get_wp(doc)['nodes'][idx]
        if ttype == 'c1': n['c1'] = QPointF(pos)
        elif ttype == 'c2': n['c2'] = QPointF(pos)
        elif ttype == 'p':
            delta = QPointF(pos) - self._start_pos
            n['p'] = self._orig_n['p'] + delta
            n['c1'] = self._orig_n['c1'] + delta
            n['c2'] = self._orig_n['c2'] + delta
            
    def cursor(self): return Qt.CursorShape.ArrowCursor