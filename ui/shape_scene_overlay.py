from PyQt6.QtCore import Qt, QPointF, QRect, QRectF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QTransform, QMouseEvent
from PyQt6.QtWidgets import (QApplication, QGraphicsView, QGraphicsScene,
                             QGraphicsObject, QGraphicsRectItem, QGraphicsItem)

from tools.shapes_tool import ShapesTool
from core.locale import tr

_HANDLE_SIZE = 8
_HANDLE_NAMES = ('tl', 't', 'tr', 'r', 'br', 'b', 'bl', 'l')


class _HandleItem(QGraphicsRectItem):
    """One corner/edge drag handle of a ShapeLayerItem. Geometry math lives
    on the parent shape (`handle_dragged`); this class only turns raw scene
    mouse deltas into that call, the same delta-from-drag-start approach the
    old hand-rolled ShapesTool re-edit code used."""

    def __init__(self, name: str, parent_shape: "ShapeLayerItem"):
        super().__init__(-_HANDLE_SIZE / 2, -_HANDLE_SIZE / 2, _HANDLE_SIZE, _HANDLE_SIZE, parent_shape)
        self.name = name
        self._shape = parent_shape
        self.setBrush(QBrush(QColor(122, 162, 247)))
        self.setPen(QPen(QColor(20, 20, 30), 1))
        self.setZValue(10)
        self.setCursor(parent_shape.cursor_for_handle(name))
        self._drag_start = None

    def mousePressEvent(self, ev):
        self._drag_start = ev.scenePos()
        self._shape.handle_drag_started()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_start is None:
            return
        self._shape.handle_dragged(self.name, ev.scenePos() - self._drag_start)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_start = None
        self._shape.handle_drag_finished()
        ev.accept()


class ShapeLayerItem(QGraphicsObject):
    """A vector shape layer as a real, persistent scene object instead of
    baked pixels you have to re-hit-test by scanning coordinates: it owns
    its own geometry, paints itself (via the exact same `ShapesTool._draw_shape`
    used for the final bake, so there's no drift between live and committed
    look), and carries its own resize/move handles.

    Editing still ends by writing pixels into `layer.image` — the document's
    compositor has no separate "vector object" concept — but the *pixels are
    a projection of this object's state*, not the object itself, mirroring
    how the layer's `shape_data` was always meant to be the source of truth.
    """

    def __init__(self, layer, doc, overlay):
        super().__init__()
        self.layer = layer
        self.doc = doc
        self.overlay = overlay
        self.setAcceptHoverEvents(True)

        self._rect = self._rect_from_layer()
        self._drag_orig_rect: QRectF | None = None
        self._drag_start_scene: QPointF | None = None
        self._history_open = False

        self._handles = {name: _HandleItem(name, self) for name in _HANDLE_NAMES}
        self._layout_handles()

    def _rect_from_layer(self) -> QRectF:
        rx, ry, rw, rh = self.layer.shape_data["rect"]
        return QRectF(rx, ry, rw, rh)

    def sync_from_layer(self):
        """Re-reads geometry from the layer (e.g. after an undo/redo)."""
        self.prepareGeometryChange()
        self._rect = self._rect_from_layer()
        self._layout_handles()
        self.update()

    def cursor_for_handle(self, name: str):
        if name in ('tl', 'br'): return Qt.CursorShape.SizeFDiagCursor
        if name in ('tr', 'bl'): return Qt.CursorShape.SizeBDiagCursor
        if name in ('l', 'r'): return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    # ------------------------------------------------------------- painting
    def boundingRect(self) -> QRectF:
        pad = int(self.layer.shape_data.get("size", 3)) + 6
        return self._rect.adjusted(-pad, -pad, pad, pad)

    def paint(self, painter: QPainter, option, widget=None):
        from PyQt6.QtCore import QPoint, QRect
        sd = self.layer.shape_data
        rect = QRect(int(self._rect.x()), int(self._rect.y()),
                     int(self._rect.width()), int(self._rect.height()))
        start = QPoint(*sd.get("start", (rect.x(), rect.y())))
        end = QPoint(*sd.get("end", (rect.right(), rect.bottom())))
        color = QColor(sd.get("fg", "#000000"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ShapesTool._draw_shape(painter, sd.get("shape", "rect"), rect, start, end,
                               sd.get("sides", 6), sd.get("angle", 0),
                               sd.get("fill", False), color, color, sd.get("size", 3))

    def _layout_handles(self):
        r = self._rect
        positions = {
            'tl': r.topLeft(),                          't': QPointF(r.center().x(), r.top()),
            'tr': r.topRight(),                          'r': QPointF(r.right(), r.center().y()),
            'br': r.bottomRight(),                       'b': QPointF(r.center().x(), r.bottom()),
            'bl': r.bottomLeft(),                        'l': QPointF(r.left(), r.center().y()),
        }
        for name, item in self._handles.items():
            item.setPos(positions[name])

    # ------------------------------------------------------------ resizing
    # While a drag is in progress we only move *this graphics item* — a
    # cheap, GPU-side repaint of one small object — and never touch
    # layer.image or trigger a document recomposite. Brush strokes in this
    # app follow the same rule (paint a live preview, only commit real
    # pixels once, on release) for the same reason: recompositing the whole
    # document on every mouse-move event is what made this laggy before.
    def handle_drag_started(self):
        self._ensure_history_open()
        self._drag_orig_rect = QRectF(self._rect)
        self._begin_visual_drag()

    def handle_dragged(self, name: str, delta: QPointF):
        r = QRectF(self._drag_orig_rect)
        if name == 'tl': r.setTopLeft(r.topLeft() + delta)
        elif name == 't': r.setTop(r.top() + delta.y())
        elif name == 'tr': r.setTopRight(r.topRight() + delta)
        elif name == 'r': r.setRight(r.right() + delta.x())
        elif name == 'br': r.setBottomRight(r.bottomRight() + delta)
        elif name == 'b': r.setBottom(r.bottom() + delta.y())
        elif name == 'bl': r.setBottomLeft(r.bottomLeft() + delta)
        elif name == 'l': r.setLeft(r.left() + delta.x())
        r = r.normalized()
        if r.width() < 2 or r.height() < 2:
            return
        self._set_live_rect(r)

    def handle_drag_finished(self):
        self._drag_orig_rect = None
        self._layout_handles()
        self._commit_to_layer()
        self._close_history()

    # --------------------------------------------------------- moving (body)
    def mousePressEvent(self, ev):
        self._ensure_history_open()
        self._drag_start_scene = ev.scenePos()
        self._drag_orig_rect = QRectF(self._rect)
        self._begin_visual_drag()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_start_scene is None:
            return
        delta = ev.scenePos() - self._drag_start_scene
        self._set_live_rect(self._drag_orig_rect.translated(delta))
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_start_scene = None
        self._drag_orig_rect = None
        self._layout_handles()
        self._commit_to_layer()
        self._close_history()
        ev.accept()

    # --------------------------------------------------------------- commit
    def _set_live_rect(self, r: QRectF):
        """Cheap per-move update: only this item repaints, nothing is
        written to the layer or the document composite yet."""
        self.prepareGeometryChange()
        self._rect = r
        self._layout_handles()
        self.update()

    def _dirty_region(self, *rects: QRectF) -> QRect:
        """Union of the given rects, padded for stroke width, clamped to
        the layer bounds — the same "only touch what actually changed"
        idea `Document.get_composite(dirty_rect=...)` already uses for
        brush strokes. On an 8K canvas the difference between this and a
        full-document recomposite is the whole story: ~190ms vs ~17ms."""
        pad = int(self.layer.shape_data.get("size", 3)) + 6
        u = QRectF(rects[0])
        for r in rects[1:]:
            u = u.united(r)
        u = u.adjusted(-pad, -pad, pad, pad).toAlignedRect()
        return u.intersected(self.layer.image.rect())

    def _clear_region(self, rect):
        p = QPainter(self.layer.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(rect, Qt.GlobalColor.transparent)
        p.end()

    def _begin_visual_drag(self):
        """Hide the stale baked shape from the real composite for the
        duration of the drag — this item's own paint() is the only visible
        representation of the shape until _commit_to_layer runs. Only the
        shape's own (small) region is touched, not the whole layer image."""
        dirty = self._dirty_region(self._rect)
        self._clear_region(dirty)
        self.overlay.notify_layer_changed(dirty)

    def _commit_to_layer(self):
        r = self._rect
        dirty = self._dirty_region(self._drag_orig_rect or r, r)
        sd = dict(self.layer.shape_data)
        # shape_data is int-based everywhere else (QPoint/QRect, not the
        # QRectF this item drags with).
        sd["rect"]  = (int(r.x()), int(r.y()), int(r.width()), int(r.height()))
        sd["start"] = (int(r.left()), int(r.top()))
        sd["end"]   = (int(r.right()), int(r.bottom()))
        self.layer.shape_data = sd
        self._clear_region(dirty)
        ShapesTool._bake_shape(self.layer.image, sd, self.doc.selection)
        self.overlay.notify_layer_changed(dirty)

    def _ensure_history_open(self):
        if not self._history_open:
            self._history_open = True
            self.overlay.begin_shape_edit(self.layer)

    def _close_history(self):
        self._history_open = False


class ShapeSceneOverlay(QGraphicsView):
    """Lives on top of CanvasWidget, active only while the Shapes tool is
    selected. Shows every vector shape layer as a real ShapeLayerItem;
    clicks that don't land on an existing shape/handle are forwarded to the
    canvas underneath so drawing a brand-new shape still works exactly as
    before."""

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
        self._active = False
        self.hide()

    # ------------------------------------------------------------ lifecycle
    def set_active(self, active: bool):
        self._active = active
        if active:
            self.show()
            self.raise_()
            self.refresh_items()
        else:
            self._clear_items()
            self.hide()

    def refresh_items(self):
        if not self._active:
            return
        doc = self.canvas.document
        if doc is None:
            self._clear_items()
            return
        live_ids = set()
        for layer in doc.layers:
            if getattr(layer, "layer_type", "raster") != "vector":
                continue
            sd = getattr(layer, "shape_data", None)
            if not sd or "rect" not in sd:
                continue
            live_ids.add(layer.layer_id)
            item = self._items.get(layer.layer_id)
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

        for lid in [lid for lid in self._items if lid not in live_ids]:
            self._scene.removeItem(self._items.pop(lid))

        self.sync_transform()

    def _clear_items(self):
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items.clear()

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
