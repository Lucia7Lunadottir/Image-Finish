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


def test_dragging_a_handle_resizes_the_existing_shape_in_place(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(w, doc)
    assert layer.shape_data["rect"] == (10, 10, 21, 21)
    n_layers = len(doc.layers)

    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    assert overlay._active
    item = overlay._items[layer.layer_id]

    item.handle_drag_started()
    item.handle_dragged('br', QPointF(20, 20))
    item.handle_drag_finished()

    assert len(doc.layers) == n_layers  # resized in place, not duplicated
    assert layer.shape_data["rect"] == (10, 10, 41, 41)
    assert layer.image.pixelColor(45, 45).alpha() > 0
    assert layer.image.pixelColor(15, 15).alpha() > 0
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


def test_switching_away_from_shapes_tool_hides_the_overlay(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    _make_shape_layer(w, doc)

    w._activate_tool("Shapes")
    assert w._canvas._shape_overlay._active

    w._activate_tool("Brush")
    assert not w._canvas._shape_overlay._active


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
    assert w._canvas._shape_overlay._active

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
