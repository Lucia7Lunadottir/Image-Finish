"""Pen tools (Pen, Freeform Pen, Curvature Pen, Add/Delete/Convert Anchor,
Path Selection, Direct Selection), modeled on Photoshop's.

What a pen tool edits — its *target* — is either the document's work path
or the nodes of a shape layer: a Pen-style one (VectorLayer with
`path_style`) or a live Shapes-tool primitive (`shape_data`), which, as in
Photoshop, turns into a regular path the moment its points are edited
(moving it whole with Path Selection keeps it live):

  * Pen / Freeform / Curvature in "shape" mode (`pen_mode` option) draw a
    shape layer directly: the first click creates it, later clicks extend
    it, and with a path operation other than "new" a new component is
    added to the selected shape. In "path" mode they draw the work path.
  * The editing tools edit the active shape layer's path if there is one,
    else the work path.
  * The Pen also edits as it goes, like Photoshop's: Ctrl = temporary
    Direct Selection, Alt = temporary Convert Point, and (Auto Add/Delete)
    hovering a segment adds an anchor, hovering an anchor deletes it.

Every pen tool's on_press/on_move/on_release is wrapped so each event
writes the edited nodes back to a shape layer (`VectorLayer.update_path`).
The path data format itself lives in core/path_model.py."""
import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QCursor, QPainterPath, QPen, QTransform

from core.path_model import (PATH_OPS, bezier_point as _bezier_point, build_bezier_path,  # noqa: F401
                             clear_path, clone_path, component_at, corner_node, focus_component,
                             has_path, insert_node_on_segment, path_components, path_offset,
                             path_to_work_path, segment_at, split_bezier as _split_bezier,
                             start_new_component)
from tools.base_tool import BaseTool
from tools.pen_cursors import pen_cursor


# ── targets ──────────────────────────────────────────────────────────────────

class _WorkPathTarget:
    """The document's work path."""
    is_shape = False

    def __init__(self, doc):
        if not hasattr(doc, "work_path"):
            doc.work_path = {"nodes": [], "closed": False}
        self.wp = doc.work_path

    def is_current(self, doc) -> bool:
        return getattr(doc, "work_path", None) is self.wp

    def commit(self, final: bool) -> None:
        pass                                    # edited in place


class _ShapeLayerPathTarget:
    """A Pen-style shape layer's nodes (VectorLayer.editable_path); every
    commit rebuilds its vector_mask (a new object, so undo snapshots keep
    the old one)."""
    is_shape = True

    def __init__(self, layer):
        self.layer = layer
        self.wp = layer.editable_path()

    def is_current(self, doc) -> bool:
        layer = self.layer
        return (doc.get_active_layer() is layer and layer._path_nodes_valid()
                and layer.path_nodes is self.wp)

    def commit(self, final: bool) -> None:
        self.layer.update_path()
        if final:
            self.layer.rebake_thumbnail()


class _LiveShapeTarget:
    """A live Shapes-tool primitive. The tools edit a node copy of its
    outline; the first edit that is more than moving the whole outline
    turns the layer into a Pen-style path layer with those nodes (and this
    target into that layer's _ShapeLayerPathTarget). A whole-outline move
    moves the shape itself, which stays live."""
    is_shape = True

    def __init__(self, layer):
        self.layer = layer
        self._orig_sd = layer.shape_data
        self._sd = layer.shape_data
        self._offset = QPoint(layer.offset)
        self._base = layer.live_shape_nodes()
        self.wp = clone_path(self._base)
        self._converted = None

    @property
    def is_live(self) -> bool:
        return self._converted is None

    def is_current(self, doc) -> bool:
        if self._converted is not None:
            return self._converted.is_current(doc)
        layer = self.layer
        return (doc.get_active_layer() is layer and layer.shape_data is self._sd
                and layer.offset == self._offset)

    def commit(self, final: bool) -> None:
        if self._converted is not None:
            self._converted.commit(final)
            return
        layer = self.layer
        shift = path_offset(self._base, self.wp)
        if shift is None:
            layer.convert_to_path_layer(self.wp)
            self._converted = _ShapeLayerPathTarget(layer)
            self.wp = self._converted.wp
            self._converted.commit(final)
            return
        if shift != (0.0, 0.0) or layer.shape_data is not self._orig_sd:
            layer.shape_data = self._orig_sd
            layer.apply_move_geometry(QTransform.fromTranslate(*shift))
            self._sd = layer.shape_data
        if final:
            layer.rebake_thumbnail()


def _active_shape_target(doc):
    """The target for the active layer if it's a shape layer pen tools can
    edit (Pen-style or live), else None."""
    layer = doc.get_active_layer()
    if layer is None or getattr(layer, "locked", False):
        return None
    if getattr(layer, "is_pen_path_layer", lambda: False)():
        return _ShapeLayerPathTarget
    if getattr(layer, "is_live_shape", lambda: False)():
        return _LiveShapeTarget
    return None


def _committing(handler, final: bool):
    def wrapper(self, pos, doc, fg, bg, opts):
        self._opts = opts
        result = handler(self, pos, doc, fg, bg, opts)
        target = (self._owner or self)._target
        if target is not None and target.is_current(doc):
            target.commit(final)
        return result
    wrapper._commits_path = True
    wrapper.__name__ = handler.__name__
    wrapper.__doc__ = handler.__doc__
    return wrapper


# ── base ─────────────────────────────────────────────────────────────────────

class BasePenTool(BaseTool):
    CONTEXT_MENU = "path"
    TARGETS_SHAPE_LAYERS = False   # editing tools: the active shape layer's path
    CREATES_PATHS = False          # Pen / Freeform / Curvature: honour pen_mode

    # Overlay sizes and hit distances are in screen pixels, so handles look
    # and grab the same at any zoom.
    ANCHOR_PX = 7
    HANDLE_PX = 6
    HIT_PX = 8
    CLOSE_PX = 10
    COMPONENT_PX = 15

    def __init__(self, owner=None):
        super().__init__()
        self.current_pos = None
        self._target = None
        # A tool the Pen borrows for Ctrl/Alt/auto add-delete edits shares
        # the Pen's target instead of choosing its own.
        self._owner = owner
        self._opts: dict = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name in ("on_press", "on_move", "on_release"):
            handler = getattr(cls, name, None)      # inherited ones too
            if handler is not None and not getattr(handler, "_commits_path", False):
                setattr(cls, name, _committing(handler, final=name == "on_release"))

    # ── target ──────────────────────────────────────────────────────────
    def _mode(self) -> str:
        return self._opts.get("pen_mode", "path")

    def _wants_shape_layer(self) -> bool:
        return self.TARGETS_SHAPE_LAYERS or (self.CREATES_PATHS and self._mode() == "shape")

    def _path_target(self, doc):
        if self._owner is not None:
            return self._owner._path_target(doc)
        kind = _active_shape_target(doc) if self._wants_shape_layer() else None
        t = self._target
        if t is not None and t.is_current(doc) and t.is_shape == (kind is not None):
            return t
        self._target = kind(doc.get_active_layer()) if kind is not None else _WorkPathTarget(doc)
        return self._target

    def _get_wp(self, doc):
        return self._path_target(doc).wp

    def _work_path(self, doc):
        return _WorkPathTarget(doc).wp

    def _draws_new_shape(self, target) -> bool:
        """Shape mode with no shape layer selected: whatever the work path
        looks like, a click starts a new shape and edits nothing."""
        return self.CREATES_PATHS and self._mode() == "shape" and not target.is_shape

    def _begin_drawing(self, doc, fg, opts, continue_open: bool = True) -> dict:
        """The path a creating tool's new nodes go into. In shape mode: the
        open path of the selected shape layer, a new component of it (path
        operation other than "new"), or a brand-new shape layer."""
        target = self._path_target(doc)
        if not (self.CREATES_PATHS and self._mode() == "shape"):
            return target.wp
        if target.is_shape:
            wp = target.wp
            # A live line isn't a path being drawn — never continued.
            if (continue_open and wp["nodes"] and not wp["closed"]
                    and not getattr(target, "is_live", False)):
                return wp
            op = opts.get("shape_path_op", "new")
            if op in PATH_OPS:
                start_new_component(wp, op)
                return wp
        layer = self._new_shape_layer(doc, fg, opts)
        self._target = _ShapeLayerPathTarget(layer)
        return self._target.wp

    @staticmethod
    def _new_shape_layer(doc, fg, opts):
        from core.layer import VectorLayer
        from tools.shapes_tool import appearance_from_opts
        index = doc.active_layer_index + 1 if doc.layers else None
        layer = doc.add_layer(doc.next_layer_name(VectorLayer, "layer.name.shape"), index,
                              layer_cls=VectorLayer)
        layer.path_style = appearance_from_opts(opts, fg).to_path_style()
        layer.path_nodes = {"nodes": [], "closed": False, "subpaths": []}
        layer.update_path()
        return layer

    def finish_path(self, doc) -> bool:
        """Enter / Esc: end the open path; the next click starts a new one."""
        target = self._path_target(doc)
        wp = target.wp
        if not wp["nodes"] or wp["closed"] or getattr(target, "is_live", False):
            return False
        start_new_component(wp)
        target.commit(True)
        return True

    # ── shared helpers ──────────────────────────────────────────────────
    def on_hover(self, pos, doc, fg, bg, opts):
        self._opts = opts
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

    def _closes_path(self, wp, pos, opts) -> bool:
        """Would a click at `pos` close the open path (near its first node)?"""
        nodes = wp['nodes']
        return (len(nodes) > 1 and not wp['closed'] and
                self._dist(pos, nodes[0]['p']) < self.screen_px(opts, self.CLOSE_PX))

    def _overlay_preview(self, wp):
        """Rubber band from the last node to the cursor (Pen only)."""
        return None

    def _overlay_close_hint(self, wp, opts) -> bool:
        return False

    def draw_overlays(self, painter, pw, doc):
        wp = self._get_wp(doc)
        nodes = wp.get('nodes', [])
        if not has_path(wp):
            return
        t = painter.worldTransform()
        px = 1.0 / max(1e-6, math.hypot(t.m11(), t.m12()))     # one screen pixel

        path = self._build_path(wp)
        preview = self._overlay_preview(wp)
        if preview is not None:
            path.cubicTo(*preview)

        line = QPen(QColor(0, 150, 255), 1.5)
        line.setCosmetic(True)
        painter.setPen(line)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        outline = QPen(QColor(0, 0, 0), 1.0)
        outline.setCosmetic(True)
        painter.setPen(outline)
        a, h = self.ANCHOR_PX * px / 2, self.HANDLE_PX * px / 2
        for comp in path_components(wp):
            if comp['nodes'] is nodes:
                continue
            painter.setBrush(QColor(255, 255, 255))
            for n in comp['nodes']:
                painter.drawRect(QRectF(n['p'].x() - a, n['p'].y() - a, 2 * a, 2 * a))
        for n in nodes:
            painter.setBrush(QColor(255, 255, 255))
            painter.drawRect(QRectF(n['p'].x() - a, n['p'].y() - a, 2 * a, 2 * a))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for key in ('c1', 'c2'):
                if n[key] != n['p']:
                    painter.drawLine(n[key], n['p'])
                    painter.drawEllipse(n[key], h, h)
        if self._overlay_close_hint(wp, {"_zoom": 1.0 / px}):
            painter.setBrush(QColor(0, 150, 255))
            painter.drawEllipse(nodes[0]['p'], a * 1.6, a * 1.6)

    def perform_action(self, doc, action, fg_color):
        # Make Selection / Shape / Clear always act on the work path, never
        # on a shape layer the editing tools happen to be showing.
        wp = self._work_path(doc)
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


def _keep_smooth(n: dict, moved: str) -> None:
    """After handle `moved` of a smooth node was dragged, turn the other
    handle to stay opposite it (keeping its own length) — the node stays
    smooth, as with Photoshop's Direct Selection."""
    other = "c1" if moved == "c2" else "c2"
    p, m, o = n["p"], n[moved], n[other]
    dm = math.hypot(m.x() - p.x(), m.y() - p.y())
    do = math.hypot(o.x() - p.x(), o.y() - p.y())
    if dm < 1e-6 or do < 1e-6:
        return
    n[other] = QPointF(p.x() - (m.x() - p.x()) / dm * do, p.y() - (m.y() - p.y()) / dm * do)


def _segment_drag_weight(t: float) -> float:
    """How a segment drag at curve parameter `t` is shared between the two
    handles (0 = all on the start handle) — Inkscape's curve-drag split:
    near an end only that end's handle moves."""
    if t <= 1 / 6:
        return 0.0
    if t <= 0.5:
        return ((6 * t - 1) / 2) ** 3 / 2
    if t <= 5 / 6:
        return (1 - ((6 * (1 - t) - 1) / 2) ** 3) / 2 + 0.5
    return 1.0


def _is_straight(n0: dict, n1: dict) -> bool:
    return n0["c2"] == n0["p"] and n1["c1"] == n1["p"]


def _is_smooth(n: dict) -> bool:
    p, a, b = n["p"], n["c1"], n["c2"]
    va, vb = (a.x() - p.x(), a.y() - p.y()), (b.x() - p.x(), b.y() - p.y())
    la, lb = math.hypot(*va), math.hypot(*vb)
    if la < 1e-6 or lb < 1e-6:
        return False
    return (va[0] * vb[0] + va[1] * vb[1]) / (la * lb) < -0.995        # opposite


# ── drawing tools ────────────────────────────────────────────────────────────

class PenTool(BasePenTool):
    CREATES_PATHS = True
    REPAINT_ON_HOVER = True
    name = "Pen"
    icon = "✒️"
    shortcut = "P"

    def __init__(self, owner=None):
        super().__init__(owner)
        self.dragging_idx = -1
        self._drag_out_only = False
        self._delegate = None
        self._helpers: dict = {}

    # ── what a click would do ───────────────────────────────────────────
    def action_at(self, doc, pos, opts) -> str:
        """'direct' (Ctrl), 'convert' (Alt), 'close', 'corner' (the open
        path's last node: drops its outgoing handle), 'delete' / 'add'
        (Auto Add/Delete over an anchor / a segment), 'new' (a click starts
        a new path), or 'draw' (the next node of the open path)."""
        self._opts = opts
        target = self._path_target(doc)
        if self._draws_new_shape(target):
            return "new"
        wp = target.wp
        if opts.get("_ctrl") and has_path(wp):
            return "direct"
        if opts.get("_alt") and has_path(wp):
            return "convert"
        nodes = wp["nodes"]
        drawing = bool(nodes) and not wp["closed"]
        if self._closes_path(wp, pos, opts):
            return "close"
        hit = self.screen_px(opts, self.HIT_PX)
        if drawing and self._dist(pos, nodes[-1]["p"]) < hit:
            return "corner"
        if opts.get("pen_auto_add_delete", True):
            for comp in path_components(wp):
                if any(self._dist(pos, n["p"]) < hit for n in comp["nodes"]):
                    return "delete"
            for comp in path_components(wp):
                if segment_at(comp["nodes"], comp["closed"], pos, hit) is not None:
                    return "add"
        return "draw" if drawing else "new"

    def _helper(self, cls):
        if cls not in self._helpers:
            self._helpers[cls] = cls(owner=self)
        return self._helpers[cls]

    # ── events ──────────────────────────────────────────────────────────
    def on_press(self, pos, doc, fg, bg, opts):
        self.current_pos = QPointF(pos)
        self.dragging_idx = -1
        action = self.action_at(doc, pos, opts)
        helper_cls = {"direct": DirectSelectionTool, "convert": ConvertPointTool,
                      "add": AddAnchorPointTool, "delete": DeleteAnchorPointTool}.get(action)
        if helper_cls is not None:
            self._delegate = self._helper(helper_cls)
            self._delegate.on_press(pos, doc, fg, bg, opts)
            return
        self._delegate = None

        if action == "close":
            wp = self._get_wp(doc)
            wp['closed'] = True
            self.dragging_idx, self._drag_out_only = 0, False
            return
        if action == "corner":
            wp = self._get_wp(doc)
            last = wp['nodes'][-1]
            last['c2'] = QPointF(last['p'])
            self.dragging_idx, self._drag_out_only = len(wp['nodes']) - 1, True
            return

        wp = self._begin_drawing(doc, fg, opts)
        if wp['closed']:
            start_new_component(wp)
        wp['nodes'].append(corner_node(pos))
        self.dragging_idx, self._drag_out_only = len(wp['nodes']) - 1, False

    def on_move(self, pos, doc, fg, bg, opts):
        self.current_pos = QPointF(pos)
        if self._delegate is not None:
            self._delegate.on_move(pos, doc, fg, bg, opts)
            return
        if self.dragging_idx >= 0:
            nodes = self._get_wp(doc)['nodes']
            if self.dragging_idx >= len(nodes):
                return
            node = nodes[self.dragging_idx]
            node['c2'] = QPointF(pos)
            if not self._drag_out_only:
                node['c1'] = QPointF(node['p'].x() * 2.0 - pos.x(), node['p'].y() * 2.0 - pos.y())

    def on_release(self, pos, doc, fg, bg, opts):
        if self._delegate is not None:
            self._delegate.on_release(pos, doc, fg, bg, opts)
        self._delegate = None
        self.dragging_idx = -1

    # ── look ────────────────────────────────────────────────────────────
    _BADGES = {"close": "o", "corner": "^", "convert": "^", "add": "+", "delete": "-",
               "new": "*", "draw": ""}

    def cursor(self):
        doc = getattr(self, "_hover_doc", None)
        if doc is None or self.current_pos is None:
            return pen_cursor("*")
        action = self.action_at(doc, self.current_pos, self._opts)
        if action == "direct":
            return QCursor(Qt.CursorShape.ArrowCursor)
        return pen_cursor(self._BADGES.get(action, ""))

    def on_hover(self, pos, doc, fg, bg, opts):
        super().on_hover(pos, doc, fg, bg, opts)
        self._hover_doc = doc

    def _overlay_preview(self, wp):
        nodes = wp['nodes']
        if (nodes and self.current_pos and self.pointer_inside and not wp.get('closed')
                and self.dragging_idx == -1 and self._delegate is None):
            return (nodes[-1]['c2'], self.current_pos, self.current_pos)
        return None

    def _overlay_close_hint(self, wp, opts) -> bool:
        return (self._overlay_preview(wp) is not None
                and self._closes_path(wp, self.current_pos, opts))


class FreeformPenTool(BasePenTool):
    CREATES_PATHS = True
    name = "FreeformPen"
    icon = "✍️"
    shortcut = "P"

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._begin_drawing(doc, fg, opts, continue_open=False)
        op = wp.get("op")
        start_new_component(wp, op)
        wp['nodes'] = [corner_node(pos)]

    def on_move(self, pos, doc, fg, bg, opts):
        nodes = self._get_wp(doc)['nodes']
        if not nodes: return
        if self._dist(pos, nodes[-1]['p']) > 15:
            nodes.append(corner_node(pos))

    def on_release(self, pos, doc, fg, bg, opts):
        # A freeform stroke is finished as soon as it's drawn: in shape
        # mode, the next stroke is a new shape / component.
        wp = self._get_wp(doc)
        if self._mode() == "shape" and wp['nodes']:
            wp['closed'] = len(wp['nodes']) > 2


class CurvaturePenTool(BasePenTool):
    CREATES_PATHS = True
    name = "CurvaturePen"
    icon = "〰️"
    shortcut = "P"

    def __init__(self, owner=None):
        super().__init__(owner)
        self.drag_idx = -1

    def on_press(self, pos, doc, fg, bg, opts):
        target = self._path_target(doc)
        wp = target.wp
        nodes = [] if self._draws_new_shape(target) else wp['nodes']
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < self.screen_px(opts, self.HIT_PX):
                self.drag_idx = i
                return
        if nodes and self._closes_path(wp, pos, opts):
            wp['closed'] = True
            self._smooth(wp); self.drag_idx = -1
            return
        wp = self._begin_drawing(doc, fg, opts)
        if wp['closed']:
            start_new_component(wp)
        nodes = wp['nodes']
        nodes.append(corner_node(pos))
        self.drag_idx = len(nodes) - 1
        self._smooth(wp)

    def on_move(self, pos, doc, fg, bg, opts):
        if self.drag_idx >= 0:
            wp = self._get_wp(doc)
            if self.drag_idx < len(wp['nodes']):
                wp['nodes'][self.drag_idx]['p'] = QPointF(pos)
                self._smooth(wp)

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


# ── editing tools ────────────────────────────────────────────────────────────

class AddAnchorPointTool(BasePenTool):
    TARGETS_SHAPE_LAYERS = True
    name = "AddAnchor"
    icon = "✒️+"
    shortcut = "P"

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._focus_at(doc, pos, self.screen_px(opts, self.COMPONENT_PX))
        nodes = wp['nodes']
        if len(nodes) < 2: return
        hit = segment_at(nodes, wp['closed'], pos, self.screen_px(opts, self.COMPONENT_PX))
        if hit is not None:
            insert_node_on_segment(nodes, *hit)

    def cursor(self): return pen_cursor("+")


class DeleteAnchorPointTool(BasePenTool):
    TARGETS_SHAPE_LAYERS = True
    name = "DeleteAnchor"
    icon = "✒️-"
    shortcut = "P"
    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._focus_at(doc, pos, self.screen_px(opts, self.COMPONENT_PX))
        nodes = wp['nodes']
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < self.screen_px(opts, self.HIT_PX):
                nodes.pop(i)
                if len(nodes) < 3: wp['closed'] = False
                return

    def cursor(self): return pen_cursor("-")


class ConvertPointTool(BasePenTool):
    TARGETS_SHAPE_LAYERS = True
    name = "ConvertPoint"
    icon = "^"
    shortcut = "P"
    def __init__(self, owner=None):
        super().__init__(owner)
        self.drag_target = None

    def on_press(self, pos, doc, fg, bg, opts):
        self.drag_target = None
        nodes = self._focus_at(doc, pos, self.screen_px(opts, self.COMPONENT_PX))['nodes']
        for i, n in enumerate(nodes):
            # A handle lying on its anchor (corner point) is not a separate
            # target — the click goes to the anchor below.
            for key in ('c1', 'c2'):
                if self._dist(n[key], n['p']) > 1 and self._dist(pos, n[key]) < self.screen_px(opts, self.HIT_PX):
                    self.drag_target = (i, key); return
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < self.screen_px(opts, self.HIT_PX):
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

    def cursor(self): return pen_cursor("^")


class PathSelectionTool(BasePenTool):
    TARGETS_SHAPE_LAYERS = True
    name = "PathSelection"
    icon = "↖"
    shortcut = "A"
    def __init__(self, owner=None):
        super().__init__(owner)
        self._dragging = False
        self._start_pos = None
        self._orig_nodes = []
        self._moved = []

    def on_press(self, pos, doc, fg, bg, opts):
        wp = self._get_wp(doc)
        if not has_path(wp): return
        path = self._build_path(wp)
        m = self.screen_px(opts, self.CLOSE_PX)
        if path.boundingRect().adjusted(-m, -m, m, m).contains(QPointF(pos)):
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
    """Drags anchors, handles and segments, like Photoshop's. Dragging a
    handle of a smooth node turns the opposite handle with it (the node
    stays smooth) unless Alt is held. Dragging a straight segment moves its
    two anchors; dragging a curved one reshapes it so the grabbed point
    follows the cursor (its two handles change, smooth ends stay smooth)."""
    name = "DirectSelection"
    icon = "↗"
    shortcut = "A"
    def on_press(self, pos, doc, fg, bg, opts):
        self.drag_target = None
        self._was_smooth = False
        wp = self._focus_at(doc, pos, self.screen_px(opts, self.COMPONENT_PX))
        nodes = wp['nodes']
        for i, n in enumerate(nodes):
            # A handle lying on its anchor (corner point) is not a separate
            # target — the click goes to the anchor below.
            for key in ('c1', 'c2'):
                if self._dist(n[key], n['p']) > 1 and self._dist(pos, n[key]) < self.screen_px(opts, self.HIT_PX):
                    self.drag_target = (i, key)
                    self._was_smooth = _is_smooth(n)
                    return
        for i, n in enumerate(nodes):
            if self._dist(pos, n['p']) < self.screen_px(opts, self.HIT_PX):
                self.drag_target = (i, 'p')
                self._start_pos = QPointF(pos)
                self._orig_n = {'p': QPointF(n['p']), 'c1': QPointF(n['c1']), 'c2': QPointF(n['c2'])}
                return
        if len(nodes) > 1:
            hit = segment_at(nodes, wp['closed'], pos, self.screen_px(opts, self.HIT_PX))
            if hit is not None:
                seg, t = hit
                n0, n1 = nodes[seg], nodes[(seg + 1) % len(nodes)]
                self.drag_target = (seg, 'segment')
                self._start_pos = QPointF(pos)
                self._seg_t = t
                self._seg_orig = [{k: QPointF(n[k]) for k in ('p', 'c1', 'c2')} for n in (n0, n1)]
                self._seg_straight = _is_straight(n0, n1)
                self._seg_smooth = (_is_smooth(n0), _is_smooth(n1))

    def _drag_segment(self, nodes, seg, pos, opts):
        n0, n1 = nodes[seg], nodes[(seg + 1) % len(nodes)]
        o0, o1 = self._seg_orig
        d = QPointF(pos) - self._start_pos
        if self._seg_straight:
            for n, o in ((n0, o0), (n1, o1)):
                for k in ('p', 'c1', 'c2'):
                    n[k] = o[k] + d
            return
        t = self._seg_t
        w = _segment_drag_weight(t)
        # The curve point at t moves by exactly d (Inkscape's formula).
        n0['c2'] = o0['c2'] + d * ((1 - w) / (3 * t * (1 - t) * (1 - t)))
        n1['c1'] = o1['c1'] + d * (w / (3 * t * t * (1 - t)))
        if not opts.get("_alt"):
            if self._seg_smooth[0]:
                n0['c1'] = QPointF(o0['c1'])
                _keep_smooth(n0, 'c2')
            if self._seg_smooth[1]:
                n1['c2'] = QPointF(o1['c2'])
                _keep_smooth(n1, 'c1')

    def on_move(self, pos, doc, fg, bg, opts):
        if not self.drag_target: return
        idx, ttype = self.drag_target
        nodes = self._get_wp(doc)['nodes']
        if ttype == 'segment':
            if len(nodes) > 1:
                self._drag_segment(nodes, idx, pos, opts)
            return
        n = nodes[idx]
        if ttype in ('c1', 'c2'):
            n[ttype] = QPointF(pos)
            if self._was_smooth and not opts.get("_alt"):
                _keep_smooth(n, ttype)
        elif ttype == 'p':
            delta = QPointF(pos) - self._start_pos
            n['p'] = self._orig_n['p'] + delta
            n['c1'] = self._orig_n['c1'] + delta
            n['c2'] = self._orig_n['c2'] + delta

    def cursor(self): return Qt.CursorShape.ArrowCursor
