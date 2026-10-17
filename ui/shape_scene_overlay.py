import math

from PyQt6.QtCore import Qt, QPointF, QRect, QRectF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QTransform, QMouseEvent, QPainterPath
from PyQt6.QtWidgets import (QApplication, QGraphicsView, QGraphicsScene,
                             QGraphicsObject, QGraphicsRectItem, QGraphicsEllipseItem,
                             QGraphicsItem, QGraphicsLineItem)

from tools.shapes_tool import ShapesTool
from core.shape_model import ShapeSpec
from core.layer import VectorLayer
from core.locale import tr

_HANDLE_SIZE = 8
_HANDLE_NAMES = ('tl', 't', 'tr', 'r', 'br', 'b', 'bl', 'l')
_ROTATE_HANDLE_DISTANCE = 26     # screen px above the top edge
_CORNER_NAMES = ('tl', 'tr', 'br', 'bl')   # order of ShapeParams.corner_radii

# Local (unrotated) unit position of each resize handle on the box, and
# which edges it moves: (x factor, y factor) in 0..1, plus moved edges.
_HANDLE_GEOMETRY = {
    'tl': ((0, 0), "lt"), 't': ((0.5, 0), "t"), 'tr': ((1, 0), "rt"),
    'r': ((1, 0.5), "r"), 'br': ((1, 1), "rb"), 'b': ((0.5, 1), "b"),
    'bl': ((0, 1), "lb"), 'l': ((0, 0.5), "l"),
}


def _modifiers(ev):
    try:
        return ev.modifiers()
    except AttributeError:      # test doubles only implement scenePos()
        return Qt.KeyboardModifier.NoModifier


class _HandleItem(QGraphicsRectItem):
    """One corner/edge drag handle of a ShapeLayerItem. Geometry math lives
    on the parent shape (`handle_dragged`); this class only turns raw scene
    mouse deltas into that call."""

    def __init__(self, name: str, parent_shape: "ShapeLayerItem"):
        super().__init__(-_HANDLE_SIZE / 2, -_HANDLE_SIZE / 2, _HANDLE_SIZE, _HANDLE_SIZE, parent_shape)
        self.name = name
        self._shape = parent_shape
        self.setBrush(QBrush(QColor(122, 162, 247)))
        self.setPen(QPen(QColor(20, 20, 30), 1))
        self.setZValue(10)
        self.setCursor(parent_shape.cursor_for_handle(name))
        # Fixed on-screen size at any zoom (the overlay's view transform
        # would otherwise scale the handle along with the document).
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self._drag_start = None

    def mousePressEvent(self, ev):
        self._drag_start = ev.scenePos()
        self._shape.handle_drag_started()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_start is None:
            return
        self._shape.handle_dragged(self.name, ev.scenePos() - self._drag_start, _modifiers(ev))
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_start = None
        self._shape.handle_drag_finished()
        ev.accept()


class _RadiusHandleItem(QGraphicsEllipseItem):
    """Circular amber handle for one corner's radius of a rounded rect —
    visually distinct from the square resize handles, the convention
    Figma/Photoshop use. Sits inset diagonally from its corner by the
    current radius. Dragging changes all four corners together; with Alt,
    only this one (Photoshop's live-shape corner widgets work the same)."""

    def __init__(self, corner: int, parent_shape: "ShapeLayerItem"):
        super().__init__(-_HANDLE_SIZE / 2, -_HANDLE_SIZE / 2, _HANDLE_SIZE, _HANDLE_SIZE, parent_shape)
        self.corner = corner
        self._shape = parent_shape
        self.setBrush(QBrush(QColor(247, 183, 49)))
        self.setPen(QPen(QColor(20, 20, 30), 1))
        self.setZValue(11)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)

    def mousePressEvent(self, ev):
        self._shape.radius_handle_drag_started()
        ev.accept()

    def mouseMoveEvent(self, ev):
        alt = bool(_modifiers(ev) & Qt.KeyboardModifier.AltModifier)
        self._shape.radius_handle_dragged(ev.scenePos(), corner=self.corner, only_this=alt)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._shape.radius_handle_drag_finished()
        ev.accept()


class _RotateHandleItem(QGraphicsEllipseItem):
    """Round handle on a stalk above the shape's top edge; dragging it
    rotates the shape around its center (Shift snaps to 15°). A child of
    the 't' resize handle, so its offset is in screen pixels and it keeps
    the same distance from the shape at any zoom."""

    def __init__(self, parent_shape: "ShapeLayerItem", anchor: _HandleItem):
        size = _HANDLE_SIZE + 2
        super().__init__(-size / 2, -size / 2, size, size, anchor)
        self._shape = parent_shape
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(20, 20, 30), 1))
        self.setZValue(12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stalk = QGraphicsLineItem(anchor)
        self._stalk.setPen(QPen(QColor(122, 162, 247), 1))
        self._stalk.setZValue(9)

    def place(self, angle_deg: float):
        a = math.radians(angle_deg)
        # "Up" (0, -d) rotated by the shape's angle, in screen pixels.
        x, y = _ROTATE_HANDLE_DISTANCE * math.sin(a), -_ROTATE_HANDLE_DISTANCE * math.cos(a)
        self.setPos(x, y)
        self._stalk.setLine(0, 0, x, y)

    def setVisible(self, visible):
        super().setVisible(visible)
        self._stalk.setVisible(visible)

    def mousePressEvent(self, ev):
        self._shape.rotate_drag_started(ev.scenePos())
        ev.accept()

    def mouseMoveEvent(self, ev):
        snap = bool(_modifiers(ev) & Qt.KeyboardModifier.ShiftModifier)
        self._shape.rotate_dragged(ev.scenePos(), snap)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._shape.rotate_drag_finished()
        ev.accept()


class ShapeLayerItem(QGraphicsObject):
    """A shape layer as an editable scene object: it owns a live
    `ShapeSpec` (the layer's shape_data, parsed), carries its own resize/
    rotate/corner-radius handles, and only writes back to the layer when a
    drag ends.

    While a drag is in progress the layer is hidden from the composite
    (`layer._live_edit_hidden`) and this item paints the shape itself — a
    cheap repaint of one object instead of a document recomposite per
    mouse move. Idle, it paints nothing: the canvas shows the shape (sharp
    at any zoom, see Document.render_view)."""

    def __init__(self, layer, doc, overlay):
        super().__init__()
        self.layer = layer
        self.doc = doc
        self.overlay = overlay
        self.setAcceptHoverEvents(True)

        self._spec = ShapeSpec.from_dict(self.layer.shape_data)
        self._is_line = self._spec.kind.is_open
        self._drag_orig: ShapeSpec | None = None
        self._drag_start_scene: QPointF | None = None
        self._rotate_start_angle = 0.0
        self._history_open = False
        self._live_drawing = False
        self._active = False

        handle_names = ('start', 'end') if self._is_line else _HANDLE_NAMES
        self._handles = {name: _HandleItem(name, self) for name in handle_names}
        self._radius_handles = [_RadiusHandleItem(i, self) for i in range(4)]
        self._rotate_handle = (None if self._is_line
                               else _RotateHandleItem(self, self._handles['t']))
        self._layout_handles()
        self.set_active(False)  # ShapeSceneOverlay.refresh_items() sets the real state right after construction

    @property
    def _rect(self) -> QRectF:
        return self._spec.params.rect

    def _is_rounded_rect(self) -> bool:
        return self._spec.kind.uses_corner_radii

    def set_active(self, is_active: bool):
        """Only the document's active layer gets handles."""
        self._active = is_active
        for h in self._handles.values():
            h.setVisible(is_active)
        for h in self._radius_handles:
            h.setVisible(is_active and self._is_rounded_rect())
        if self._rotate_handle is not None:
            self._rotate_handle.setVisible(is_active and self._spec.kind.supports_rotation)

    def sync_from_layer(self):
        """Re-reads geometry from the layer (e.g. after an undo/redo)."""
        self.prepareGeometryChange()
        self._spec = ShapeSpec.from_dict(self.layer.shape_data)
        self._layout_handles()
        self.set_active(self._active)
        self.setVisible(self.layer.visible)
        self.update()

    def cursor_for_handle(self, name: str):
        if name in ('start', 'end'): return Qt.CursorShape.CrossCursor
        if name in ('tl', 'br'): return Qt.CursorShape.SizeFDiagCursor
        if name in ('tr', 'bl'): return Qt.CursorShape.SizeBDiagCursor
        if name in ('l', 'r'): return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    # ------------------------------------------------------------- geometry
    def _local_handle_pos(self, name: str, rect: QRectF | None = None) -> QPointF:
        r = rect or self._rect
        (fx, fy), _ = _HANDLE_GEOMETRY[name]
        return QPointF(r.left() + r.width() * fx, r.top() + r.height() * fy)

    def _radius_handle_local(self, corner: int) -> QPointF:
        r = self._rect
        from core.shape_kinds import clamp_corner_radii
        radius = clamp_corner_radii(r, self._spec.params.corner_radii)[corner]
        # The handle sits *on* the corner's arc center diagonal; keep it a
        # few pixels inside at radius 0 so it doesn't hide under the
        # corner resize handle.
        inset = max(radius, min(r.width(), r.height()) * 0.12, 6.0)
        inset = min(inset, min(r.width(), r.height()) / 2)
        sx = 1 if corner in (0, 3) else -1
        sy = 1 if corner in (0, 1) else -1
        corner_pt = {0: r.topLeft(), 1: r.topRight(), 2: r.bottomRight(), 3: r.bottomLeft()}[corner]
        return QPointF(corner_pt.x() + sx * inset, corner_pt.y() + sy * inset)

    # ------------------------------------------------------------- painting
    def boundingRect(self) -> QRectF:
        return self._spec.bounds().adjusted(-2, -2, 2, 2)

    def shape(self) -> QPainterPath:
        """Exact hit area: clicking empty space inside the bounding box of
        a rotated or non-rectangular shape must not grab it."""
        area = self._spec.filled_area()
        # A hairline or thin unfilled outline would be near-impossible to
        # click; give it a minimum grab width (in document units).
        from PyQt6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        return area.united(stroker.createStroke(self._spec.outline()))

    def paint(self, painter: QPainter, option, widget=None):
        if not self.layer.visible or not self._live_drawing:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.layer.opacity)
        self._spec.paint(painter)

    def _layout_handles(self):
        rot = self._spec.rotation()
        if self._is_line:
            self._handles['start'].setPos(self._spec.params.start)
            self._handles['end'].setPos(self._spec.params.end)
        else:
            for name, item in self._handles.items():
                item.setPos(rot.map(self._local_handle_pos(name)))
            if self._rotate_handle is not None:
                self._rotate_handle.place(self._spec.angle)
        for i, h in enumerate(self._radius_handles):
            h.setPos(rot.map(self._radius_handle_local(i)))

    def _set_live_spec(self, spec: ShapeSpec):
        self.prepareGeometryChange()
        self._spec = spec
        self._layout_handles()
        self.update()

    # ------------------------------------------------------------ resizing
    def handle_drag_started(self):
        self._ensure_history_open()
        self._drag_orig = self._spec
        self._begin_visual_drag()

    def handle_dragged(self, name: str, delta: QPointF, modifiers=None):
        orig = self._drag_orig
        if orig is None:
            return
        modifiers = modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier
        if self._is_line:
            p = orig.params
            start = p.start + delta if name == 'start' else p.start
            end = p.end + delta if name == 'end' else p.end
            self._set_live_spec(orig.with_geometry(rect=QRectF(start, end).normalized(),
                                                   start=start, end=end))
            return

        # Work in the shape's own (unrotated) frame: the dragged handle
        # follows the mouse there, the opposite side stays put.
        rot = orig.rotation()
        inv, _ = rot.inverted()
        grab_world = rot.map(self._local_handle_pos(name, orig.params.rect))
        mouse = inv.map(grab_world + delta)
        r = QRectF(orig.params.rect)
        _, edges = _HANDLE_GEOMETRY[name]
        from_center = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        c = r.center()
        if "l" in edges:
            r.setLeft(mouse.x())
            if from_center: r.setRight(2 * c.x() - mouse.x())
        if "r" in edges:
            r.setRight(mouse.x())
            if from_center: r.setLeft(2 * c.x() - mouse.x())
        if "t" in edges:
            r.setTop(mouse.y())
            if from_center: r.setBottom(2 * c.y() - mouse.y())
        if "b" in edges:
            r.setBottom(mouse.y())
            if from_center: r.setTop(2 * c.y() - mouse.y())
        if (modifiers & Qt.KeyboardModifier.ShiftModifier) and len(edges) == 2:
            r = self._keep_aspect(r, orig.params.rect, edges, from_center)
        r = r.normalized()
        if r.width() < 2 or r.height() < 2:
            return
        if orig.angle:
            # Rotation is about the rect's own center; re-center so the
            # fixed side stays where it was on screen.
            r.moveCenter(rot.map(r.center()))
        self._set_live_spec(orig.with_geometry(rect=r, start=r.topLeft(), end=r.bottomRight()))

    @staticmethod
    def _keep_aspect(r: QRectF, orig: QRectF, edges: str, from_center: bool) -> QRectF:
        if orig.width() <= 0 or orig.height() <= 0:
            return r
        scale = max(abs(r.width()) / orig.width(), abs(r.height()) / orig.height())
        w, h = orig.width() * scale, orig.height() * scale
        if from_center:
            c = orig.center()
            return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        out = QRectF(r)
        if "l" in edges: out.setLeft(r.right() - w)
        else: out.setRight(r.left() + w)
        if "t" in edges: out.setTop(r.bottom() - h)
        else: out.setBottom(r.top() + h)
        return out

    def handle_drag_finished(self):
        self._commit_to_layer()
        self._drag_orig = None
        self._close_history()

    # ---------------------------------------------------------- radius drag
    def radius_handle_drag_started(self):
        self._ensure_history_open()
        self._drag_orig = self._spec
        self._begin_visual_drag()

    def radius_handle_dragged(self, scene_pos: QPointF, corner: int = 0, only_this: bool = False):
        spec = self._drag_orig or self._spec
        r = spec.params.rect
        inv, _ = spec.rotation().inverted()
        local = inv.map(scene_pos)
        corner_pt = {0: r.topLeft(), 1: r.topRight(), 2: r.bottomRight(), 3: r.bottomLeft()}[corner]
        sx = 1 if corner in (0, 3) else -1
        sy = 1 if corner in (0, 1) else -1
        inward_x = (local.x() - corner_pt.x()) * sx
        inward_y = (local.y() - corner_pt.y()) * sy
        radius = max(0.0, min((inward_x + inward_y) / 2, min(r.width(), r.height()) / 2))
        radii = list(spec.params.corner_radii)
        if only_this:
            radii[corner] = radius
        else:
            radii = [radius] * 4
        self._set_live_spec(self._spec.with_geometry(corner_radii=tuple(radii)))

    def radius_handle_drag_finished(self):
        self._commit_to_layer()
        self._drag_orig = None
        self._close_history()

    # -------------------------------------------------------- rotation drag
    def rotate_drag_started(self, scene_pos: QPointF):
        self._ensure_history_open()
        self._drag_orig = self._spec
        c = self._rect.center()
        self._rotate_start_angle = math.degrees(math.atan2(scene_pos.y() - c.y(), scene_pos.x() - c.x()))
        self._begin_visual_drag()

    def rotate_dragged(self, scene_pos: QPointF, snap: bool = False):
        orig = self._drag_orig
        if orig is None:
            return
        c = orig.params.rect.center()
        now = math.degrees(math.atan2(scene_pos.y() - c.y(), scene_pos.x() - c.x()))
        angle = (orig.angle + now - self._rotate_start_angle) % 360
        if snap:
            angle = round(angle / 15.0) * 15.0 % 360
        self._set_live_spec(orig.with_geometry(angle=angle))

    def rotate_drag_finished(self):
        self._commit_to_layer()
        self._drag_orig = None
        self._close_history()

    # --------------------------------------------------------- moving (body)
    def mousePressEvent(self, ev):
        # Handles only exist on the active layer, but any shape's body is
        # clickable: clicking a different shape selects it first.
        if self.doc.get_active_layer() is not self.layer:
            self.overlay.select_layer(self.layer)
        self._ensure_history_open()
        self._drag_start_scene = ev.scenePos()
        self._drag_orig = self._spec
        self._begin_visual_drag()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_start_scene is None or self._drag_orig is None:
            return
        delta = ev.scenePos() - self._drag_start_scene
        p = self._drag_orig.params
        self._set_live_spec(self._drag_orig.with_geometry(
            rect=p.rect.translated(delta), start=p.start + delta, end=p.end + delta))
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_start_scene = None
        self._commit_to_layer()
        self._drag_orig = None
        self._close_history()
        ev.accept()

    # --------------------------------------------------------------- commit
    def _dirty_region(self, *specs: ShapeSpec) -> QRect:
        """Union of the given shapes' painted bounds, clamped to the layer
        — only that region of the composite is re-rendered."""
        u = QRectF()
        for spec in specs:
            u = u.united(spec.bounds())
        u = u.adjusted(-2, -2, 2, 2).toAlignedRect()
        return u.intersected(self.layer.image.rect())

    def _begin_visual_drag(self):
        """Hide the layer from the real composite for the drag — this
        item's paint() is the only visible copy until _commit_to_layer."""
        self._live_drawing = True
        self.layer._live_edit_hidden = True
        self.update()
        self.overlay.notify_layer_changed(self._dirty_region(self._spec))

    def _commit_to_layer(self):
        old = ShapeSpec.from_dict(self.layer.shape_data)
        self.layer.shape_data = self._spec.to_dict(base=self.layer.shape_data)
        # Re-read what was stored (ints), so the item shows exactly that.
        self._spec = ShapeSpec.from_dict(self.layer.shape_data)
        self._layout_handles()
        ShapesTool.rebake(self.layer)
        self._live_drawing = False
        self.layer._live_edit_hidden = False
        self.update()
        self.overlay.notify_layer_changed(self._dirty_region(old, self._spec))

    def _ensure_history_open(self):
        if not self._history_open:
            self._history_open = True
            self.overlay.begin_shape_edit(self.layer)

    def _close_history(self):
        self._history_open = False


class ShapeSceneOverlay(QGraphicsView):
    """Lives on top of CanvasWidget and holds one ShapeLayerItem per shape
    layer. Only shown (and only receiving mouse input) while the Shapes
    tool is active — see set_interactive(). It never draws an idle shape:
    the canvas itself renders shapes sharp at any zoom, in correct layer
    order (Document.render_view), which an always-on-top overlay can't."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)
        # QGraphicsView centers scene content in the viewport by default,
        # which adds its own offset on top of our manual zoom/pan transform
        # below — pin it top-left and freeze the scene rect so our transform
        # is the only thing that decides where items land.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSceneRect(-100000, -100000, 200000, 200000)

        self._items: dict[str, ShapeLayerItem] = {}
        self._forwarding = False
        self._interactive = False
        # Non-interactive by default: Qt routes mouse events straight
        # through to the canvas underneath, untouched, exactly like this
        # widget wasn't there at all.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------ lifecycle
    def set_interactive(self, interactive: bool):
        """Shapes tool is (or isn't) the active tool — only affects handle
        visibility and whether this view accepts mouse input; live
        rendering itself (refresh_items) runs regardless."""
        self._interactive = interactive
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not interactive)
        self.refresh_items()

    def refresh_items(self):
        doc = self.canvas.document
        if doc is None:
            self._clear_items()
            return
        self.setVisible(self._interactive)
        active_layer = doc.get_active_layer()

        live_ids = set()
        for layer in doc.layers:
            if not isinstance(layer, VectorLayer):
                continue
            sd = getattr(layer, "shape_data", None)
            if not sd or "rect" not in sd:
                continue
            live_ids.add(layer.layer_id)
            item = self._items.get(layer.layer_id)
            if item is not None and item._is_line != (sd.get("shape") == "line"):
                self._scene.removeItem(self._items.pop(layer.layer_id))
                item = None
            if item is None:
                item = ShapeLayerItem(layer, doc, self)
                self._scene.addItem(item)
                self._items[layer.layer_id] = item
            else:
                # Undo/redo rebuild the whole layer list with fresh Layer
                # objects (same layer_id, different identity) — rebind
                # before reading, or this item keeps editing an orphaned
                # object that's no longer part of the document at all.
                item.layer = layer
                item.doc = doc
                item.sync_from_layer()
            item.setVisible(layer.visible)
            item.set_active(layer is active_layer and self._interactive)

        for lid in [lid for lid in self._items if lid not in live_ids]:
            self._scene.removeItem(self._items.pop(lid))

        self.raise_()
        self.sync_transform()

    def _clear_items(self):
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items.clear()
        self.hide()

    # ------------------------------------------------------- canvas callbacks
    def notify_layer_changed(self, dirty_rect=None):
        doc = self.canvas.document
        if doc is None:
            return
        if dirty_rect is not None:
            # Mirrors CanvasWidget._recompute_composite's incremental path —
            # only the touched region is re-rendered instead of every layer
            # over the whole (possibly 8K+) canvas.
            self.canvas._composite_cache = doc.get_composite(dirty_rect=dirty_rect)
            self.canvas._cache_dirty = False
            self.canvas._display_cache = None
            self.canvas.update()
        else:
            win = self.canvas.window()
            if hasattr(win, "_canvas_refresh"):
                win._canvas_refresh()

    def begin_shape_edit(self, layer):
        win = self.canvas.window()
        if not hasattr(win, "_push_history"):
            return
        doc = self.canvas.document
        idx = doc.layers.index(layer) if layer in doc.layers else None
        win._push_history(tr("history.edit_shape"), idx)

    def select_layer(self, layer):
        """Makes `layer` the document's active layer and refreshes both the
        handle-visibility state here and the Layers panel — used when
        clicking a shape's body while the Shapes tool is active, so a
        non-active shape can be selected (and then resized/moved) without
        switching to the Layers panel first."""
        doc = self.canvas.document
        if doc is None or layer not in doc.layers:
            return
        doc.active_layer_index = doc.layers.index(layer)
        self.refresh_items()
        win = self.canvas.window()
        if hasattr(win, "_refresh_layers"):
            win._refresh_layers()
        if hasattr(win, "_sync_shape_options_from_layer"):
            win._sync_shape_options_from_layer(layer)

    # ----------------------------------------------------------------- view
    def sync_transform(self):
        c = self.canvas
        self.setGeometry(0, 0, c.width(), c.height())
        self.setTransform(QTransform(c.zoom, 0, 0, c.zoom, c._pan.x(), c._pan.y()))
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    # ------------------------------------------- click-through for empty space
    def mousePressEvent(self, ev):
        if self.itemAt(ev.pos()) is None:
            self._forwarding = True
            self._forward(ev)
            return
        self._forwarding = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._forwarding:
            self._forward(ev)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._forwarding:
            self._forward(ev)
            self._forwarding = False
            return
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        # QGraphicsView otherwise swallows wheel events for its own
        # scrolling (which does nothing useful here — scrollbars are
        # disabled), which silently broke Ctrl+wheel zoom while a shape
        # layer existed. Zoom/pan belong to the canvas, never to us.
        from PyQt6.QtGui import QWheelEvent
        new_ev = QWheelEvent(ev.position(), ev.globalPosition(), ev.pixelDelta(),
                             ev.angleDelta(), ev.buttons(), ev.modifiers(),
                             ev.phase(), ev.inverted())
        QApplication.instance().sendEvent(self.canvas, new_ev)
        ev.accept()

    def _forward(self, ev):
        new_ev = QMouseEvent(ev.type(), ev.position(), ev.globalPosition(),
                             ev.button(), ev.buttons(), ev.modifiers())
        QApplication.instance().sendEvent(self.canvas, new_ev)
