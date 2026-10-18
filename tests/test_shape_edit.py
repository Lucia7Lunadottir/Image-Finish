"""Shape layers store their geometry in shape_data and re-render from it.
ShapesTool itself only draws brand-new shapes by dragging on empty canvas;
resizing/moving an *existing* shape is owned by a real scene object
(ShapeLayerItem in ui/shape_scene_overlay.py), exercised here via the real
CanvasWidget/ShapeSceneOverlay wiring (main_window fixture) rather than by
hit-testing raw mouse coordinates.
"""

from PyQt6.QtCore import QPoint, QPointF
from PyQt6.QtGui import QColor

from core.document import Document
from tools.shapes_tool import ShapesTool


def _opts(**over):
    base = {"shape_type": "rect", "shape_fill": True, "brush_size": 0,
            "shape_sides": 6, "shape_angle": 0, "shape_color": QColor(255, 0, 0)}
    base.update(over)
    return base


class _FakeMouseEvent:
    """Duck-types just enough of QGraphicsSceneMouseEvent for
    ShapeLayerItem's body-drag handlers (they only call scenePos()/accept())."""
    def __init__(self, pos: QPointF):
        self._pos = pos

    def scenePos(self):
        return self._pos

    def accept(self):
        pass


def test_dragging_creates_a_vector_layer_matching_shape_data():
    doc = Document(100, 100)
    tool = ShapesTool()
    opts = _opts()

    tool.on_press(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(40, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(40, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)

    layer = doc.layers[-1]
    assert layer.layer_type == "vector"
    # QRect(p1, p2).normalized() is inclusive of both endpoints.
    assert layer.shape_data["rect"] == (10, 10, 31, 21)
    # The bounding box should actually contain rendered (non-transparent) pixels.
    assert layer.image.pixelColor(25, 20).alpha() > 0


def _make_shape_layer(w, doc, rect=(10, 10, 21, 21)):
    tool = ShapesTool()
    opts = _opts()
    x, y, rw, rh = rect
    tool.on_press(QPoint(x, y), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(x + rw - 1, y + rh - 1), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(x + rw - 1, y + rh - 1), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    return doc.layers[-1]


def _make_line_layer(w, doc, start=(10, 10), end=(40, 15)):
    tool = ShapesTool()
    opts = _opts(shape_type="line")
    tool.on_press(QPoint(*start), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(*end), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(*end), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    return doc.layers[-1]


def test_dragging_a_handle_resizes_the_existing_shape_in_place(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)
    assert layer.shape_data["rect"] == (10, 10, 21, 21)
    n_layers = len(doc.layers)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    assert overlay._interactive
    item = overlay._items[layer.layer_id]

    item.handle_drag_started()
    item.handle_dragged('br', QPointF(20, 20))
    item.handle_drag_finished()

    assert len(doc.layers) == n_layers  # resized in place, not duplicated
    assert layer.shape_data["rect"] == (10, 10, 41, 41)
    assert layer.image.pixelColor(45, 45).alpha() > 0
    assert layer.image.pixelColor(15, 15).alpha() > 0
    assert w._history.can_undo()


def test_shape_item_only_draws_itself_while_a_drag_is_in_progress(main_window):
    """Real bug: ShapeLayerItem.paint() used to run unconditionally, every
    frame, for every shape layer — so the already-baked, already-composited
    raster (canvas's own GL rendering) and this item's own separately-
    transformed redraw (ShapeSceneOverlay's QGraphicsView) were BOTH
    visible at once whenever the Shapes tool was active, not just mid-
    drag. She saw this as "draws the shape twice, raster version behind."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]
    assert not item._live_drawing  # idle right after creation: nothing to draw

    item.handle_drag_started()
    assert item._live_drawing  # mid-drag: this item is the only visible copy
    item.handle_dragged('br', QPointF(20, 20))
    item.handle_drag_finished()
    assert not item._live_drawing  # committed: back to raster-only


def test_only_the_active_shapes_handles_are_visible(main_window):
    """Real bug report: drawing a second shape while the Shapes tool stayed
    active left the FIRST shape's drag handles on screen forever too — every
    ShapeLayerItem ever created showed its handles unconditionally, with no
    concept of "selected" vs "not selected". Handles must track
    doc.active_layer_index instead."""
    w = main_window
    w._add_tab(Document(200, 200), "t")
    doc = w._document
    layer1 = _make_shape_layer(w, doc, rect=(10, 10, 21, 21))

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item1 = overlay._items[layer1.layer_id]
    assert item1._handles["tl"].isVisible()  # only shape so far, and active

    layer2 = _make_shape_layer(w, doc, rect=(60, 60, 21, 21))
    doc.active_layer_index = doc.layers.index(layer2)
    overlay.refresh_items()  # what document_changed triggers in the real app

    item1 = overlay._items[layer1.layer_id]
    item2 = overlay._items[layer2.layer_id]
    assert not item1._handles["tl"].isVisible()  # no longer active -> hidden
    assert item2._handles["tl"].isVisible()      # newly active -> shown


def test_handles_ignore_view_transformations_for_fixed_screen_size(main_window):
    """Real bug: handle squares were sized in scene/document coordinates,
    so ShapeSceneOverlay's zoom transform scaled them along with the
    shape itself — tiny at low zoom, huge at high zoom, instead of a
    constant on-screen size like MoveTool's own handles."""
    from PyQt6.QtWidgets import QGraphicsItem
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]
    for handle in item._handles.values():
        assert handle.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def test_clicking_an_inactive_shapes_body_selects_it(main_window):
    """Real bug: with handles now shown only for the active shape, clicking
    a *different* shape's body while the Shapes tool stayed active did
    nothing to select it — there was no way back to editing/resizing that
    other shape short of switching to the Layers panel."""
    w = main_window
    w._add_tab(Document(200, 200), "t")
    doc = w._document
    layer1 = _make_shape_layer(w, doc, rect=(10, 10, 21, 21))
    layer2 = _make_shape_layer(w, doc, rect=(60, 60, 21, 21))
    doc.active_layer_index = doc.layers.index(layer2)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    overlay.refresh_items()
    item1 = overlay._items[layer1.layer_id]
    assert not item1._handles["tl"].isVisible()  # not active yet

    item1.mousePressEvent(_FakeMouseEvent(QPointF(15, 15)))
    item1.mouseReleaseEvent(_FakeMouseEvent(QPointF(15, 15)))

    assert doc.active_layer_index == doc.layers.index(layer1)
    item1 = overlay._items[layer1.layer_id]
    item2 = overlay._items[layer2.layer_id]
    assert item1._handles["tl"].isVisible()       # now selected -> shown
    assert not item2._handles["tl"].isVisible()   # no longer active -> hidden


def test_clicking_a_shapes_body_also_syncs_the_options_bar(main_window):
    w = main_window
    w._add_tab(Document(200, 200), "t")
    doc = w._document
    layer1 = _make_shape_layer(w, doc, rect=(10, 10, 21, 21))
    layer2 = _make_shape_layer(w, doc, rect=(60, 60, 21, 21))
    layer2.shape_data = dict(layer2.shape_data, shape="rounded_rect", corner_radius=17, corner_radii=[17] * 4)
    doc.active_layer_index = doc.layers.index(layer2)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    overlay.refresh_items()
    item1 = overlay._items[layer1.layer_id]

    item1.mousePressEvent(_FakeMouseEvent(QPointF(15, 15)))
    item1.mouseReleaseEvent(_FakeMouseEvent(QPointF(15, 15)))

    page = w._opts_bar.page_for("Shapes")
    assert page._radius_sps[0].value() == layer1.shape_data["corner_radius"]
    assert page._radius_sps[0].value() != 17  # not left over from layer2


def test_rounded_rect_shows_radius_handle_only_when_active_and_rounded(main_window):
    """The corner-radius handle is a 9th, circular handle distinct from the
    8 square resize handles — it should only ever appear for a shape that
    is both a rounded_rect AND the active layer, same rule as the resize
    handles but with an extra shape-type condition."""
    w = main_window
    w._add_tab(Document(200, 200), "t")
    doc = w._document
    plain = _make_shape_layer(w, doc, rect=(10, 10, 21, 21))
    rounded = _make_shape_layer(w, doc, rect=(60, 60, 41, 41))
    rounded.shape_data = dict(rounded.shape_data, shape="rounded_rect", corner_radius=10, corner_radii=[10] * 4)
    doc.active_layer_index = doc.layers.index(rounded)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    overlay.refresh_items()

    plain_item = overlay._items[plain.layer_id]
    rounded_item = overlay._items[rounded.layer_id]
    assert not plain_item._radius_handles[0].isVisible()   # not rounded, not active
    assert rounded_item._radius_handles[0].isVisible()     # rounded AND active

    doc.active_layer_index = doc.layers.index(plain)
    overlay.refresh_items()
    plain_item = overlay._items[plain.layer_id]
    rounded_item = overlay._items[rounded.layer_id]
    assert not rounded_item._radius_handles[0].isVisible()  # rounded but no longer active


def test_dragging_the_radius_handle_changes_corner_radius_and_rebakes(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc, rect=(10, 10, 41, 41))
    layer.shape_data = dict(layer.shape_data, shape="rounded_rect", corner_radius=0, corner_radii=[0] * 4)
    from tools.shapes_tool import ShapesTool
    ShapesTool._bake_shape(layer.image, layer.shape_data, doc.selection)
    assert layer.image.pixelColor(11, 11).alpha() > 0   # square corner at radius 0

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    overlay.refresh_items()
    item = overlay._items[layer.layer_id]

    item.radius_handle_drag_started()
    item.radius_handle_dragged(QPointF(25, 25))   # 15px in from the (10, 10) corner
    item.radius_handle_drag_finished()

    assert layer.shape_data["corner_radius"] == 15
    assert layer.image.pixelColor(11, 11).alpha() == 0   # corner now rounded away
    assert layer.image.pixelColor(30, 30).alpha() > 0    # center still filled
    assert w._history.can_undo()


def test_moving_a_shape_by_its_body_translates_it(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]

    item.mousePressEvent(_FakeMouseEvent(QPointF(20, 20)))
    item.mouseMoveEvent(_FakeMouseEvent(QPointF(40, 20)))   # +20, +0
    item.mouseReleaseEvent(_FakeMouseEvent(QPointF(40, 20)))

    assert layer.shape_data["rect"] == (30, 10, 21, 21)


def test_switching_away_from_shapes_tool_hides_the_overlay_and_leaves_the_composite_alone(main_window):
    """The overlay is only an editing aid now: off the Shapes tool it's
    hidden and passes mouse input through, and the shape itself is drawn
    by the canvas composite (sharp at zoom via Document.render_view, in
    correct layer order) — never hidden from it outside an active drag."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    assert w._canvas._shape_overlay._interactive

    w._activate_tool("Brush")
    overlay = w._canvas._shape_overlay
    assert not overlay._interactive
    assert not overlay.isVisible()
    assert not layer._live_edit_hidden


def test_ctrl_wheel_zoom_still_works_while_shapes_tool_active(main_window):
    """Regression: the ShapeSceneOverlay (a QGraphicsView covering the whole
    canvas) swallowed wheel events for its own scrolling, silently breaking
    Ctrl+wheel zoom whenever a shape layer existed and Shapes was active."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent, QVector2D
    from PyQt6.QtCore import Qt as _Qt

    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    _make_shape_layer(w, doc, rect=(10, 10, 21, 21))
    w._activate_tool("Shapes")
    assert w._canvas._shape_overlay._interactive

    zoom_before = w._canvas.zoom
    pos = QPointF(50, 50)
    ev = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, 120),
                     _Qt.MouseButton.NoButton, _Qt.KeyboardModifier.ControlModifier,
                     _Qt.ScrollPhase.NoScrollPhase, False)
    w._canvas._shape_overlay.wheelEvent(ev)

    assert w._canvas.zoom != zoom_before


def test_shape_item_stays_in_sync_after_undo(main_window):
    """Regression: undo/redo rebuild doc.layers with fresh Layer objects
    (Document.restore_layers). A ShapeLayerItem created before that kept
    pointing at the old, now-orphaned object, so editing a shape right
    after an undo silently edited nothing the document could see."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]

    item.handle_drag_started()
    item.handle_dragged('br', QPointF(20, 20))
    item.handle_drag_finished()
    assert layer.shape_data["rect"] == (10, 10, 41, 41)

    w._undo()

    # The document now holds a *different* Layer object for this shape.
    current_layer = doc.layers[-1]
    assert current_layer is not layer
    item_after = overlay._items[current_layer.layer_id]
    assert item_after.layer is current_layer

    # Editing after the undo must land on the document's real layer.
    item_after.handle_drag_started()
    item_after.handle_dragged('br', QPointF(5, 5))
    item_after.handle_drag_finished()
    assert current_layer.shape_data["rect"] == (10, 10, 26, 26)


def test_a_line_shows_start_end_handles_not_the_8_rect_handles(main_window):
    """Real bug report: a line's editing was 'broken' — it got the same 8
    corner/edge resize handles as every other shape, but dragging a
    bounding-box corner has no sensible meaning for a line's two actual
    endpoints."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_line_layer(w, doc, start=(10, 10), end=(40, 15))

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]

    assert set(item._handles.keys()) == {"start", "end"}
    assert item._handles["start"].pos() == QPointF(10, 10)
    assert item._handles["end"].pos() == QPointF(40, 15)


def test_dragging_a_lines_end_handle_moves_only_that_endpoint(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_line_layer(w, doc, start=(10, 10), end=(40, 15))

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]

    item.handle_drag_started()
    item.handle_dragged('end', QPointF(10, 20))   # +10, +20
    item.handle_drag_finished()

    assert layer.shape_data["start"] == (10, 10)   # untouched
    assert layer.shape_data["end"] == (50, 35)
    assert w._history.can_undo()


def test_moving_a_lines_body_translates_both_endpoints(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_line_layer(w, doc, start=(10, 10), end=(40, 15))

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    item = overlay._items[layer.layer_id]

    # Click somewhere on the line's body (its bounding-rect padding makes
    # even a point not exactly on the segment a valid click target here).
    item.mousePressEvent(_FakeMouseEvent(QPointF(25, 12)))
    item.mouseMoveEvent(_FakeMouseEvent(QPointF(35, 22)))   # +10, +10
    item.mouseReleaseEvent(_FakeMouseEvent(QPointF(35, 22)))

    assert layer.shape_data["start"] == (20, 20)
    assert layer.shape_data["end"] == (50, 25)
