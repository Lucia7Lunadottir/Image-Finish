"""Shape layers used to be baked once from a single drag and never
touchable again — shape_data was stored but nothing re-read it. ShapesTool
now re-renders from shape_data on every edit, so an existing shape can be
picked up by a handle and resized/moved.
"""

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor

from core.document import Document
from tools.shapes_tool import ShapesTool


def _opts(**over):
    base = {"shape_type": "rect", "shape_fill": True, "brush_size": 0,
            "shape_sides": 6, "shape_angle": 0, "shape_color": QColor(255, 0, 0)}
    base.update(over)
    return base


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


def test_dragging_a_handle_resizes_the_existing_shape_in_place():
    doc = Document(100, 100)
    tool = ShapesTool()
    opts = _opts()

    tool.on_press(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(30, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(30, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    n_layers = len(doc.layers)
    layer = doc.layers[-1]
    assert layer.shape_data["rect"] == (10, 10, 21, 21)

    # Grab the bottom-right handle and drag it further out.
    tool2 = ShapesTool()
    tool2.on_press(QPoint(30, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    assert tool2._edit_layer is layer
    assert tool2._edit_mode == 'br'
    tool2.on_move(QPoint(50, 50), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool2.on_release(QPoint(50, 50), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)

    assert len(doc.layers) == n_layers  # resized in place, not duplicated
    assert layer.shape_data["rect"] == (10, 10, 41, 41)
    assert layer.image.pixelColor(45, 45).alpha() > 0
    # The old bottom-right corner (outside the new, larger shape's edge
    # padding) should still be part of the filled rect, not empty.
    assert layer.image.pixelColor(15, 15).alpha() > 0


def test_moving_a_shape_by_its_body_translates_it():
    doc = Document(100, 100)
    tool = ShapesTool()
    opts = _opts()

    tool.on_press(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(30, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(30, 30), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    layer = doc.layers[-1]

    tool2 = ShapesTool()
    tool2.on_press(QPoint(20, 20), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)  # inside the shape
    assert tool2._edit_mode == 'move'
    tool2.on_move(QPoint(40, 20), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)   # +20, +0
    tool2.on_release(QPoint(40, 20), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)

    assert layer.shape_data["rect"] == (30, 10, 21, 21)
