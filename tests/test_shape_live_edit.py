"""ui/actions/shape_actions.py::ShapeActionsMixin — when the Shapes tool is
active and the active layer already has shape_data, editing color/fill/
stroke-width/sides/angle/corner-radius from the options bar re-bakes that
*existing* shape live, instead of only affecting the next shape drawn."""

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor

from core.document import Document
from tools.shapes_tool import ShapesTool


def _opts(**over):
    base = {"shape_type": "rect", "shape_fill": True, "brush_size": 0,
            "shape_sides": 6, "shape_angle": 0, "shape_color": QColor(255, 0, 0)}
    base.update(over)
    return base


def _make_shape_layer(doc, rect=(10, 10, 21, 21), **opt_overrides):
    tool = ShapesTool()
    opts = _opts(**opt_overrides)
    x, y, rw, rh = rect
    tool.on_press(QPoint(x, y), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_move(QPoint(x + rw - 1, y + rh - 1), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(x + rw - 1, y + rh - 1), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    return doc.layers[-1]


def test_shape_color_option_live_edits_the_active_shape(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")

    w._on_opt_changed("shape_color", QColor(0, 255, 0))

    assert layer.shape_data["fg"] == "#00ff00"
    assert layer.image.pixelColor(20, 20) == QColor(0, 255, 0)
    assert w._history.can_undo()


def test_shape_corner_radius_option_live_edits_the_active_rounded_rect(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc, rect=(10, 10, 41, 41), shape_type="rounded_rect")
    layer.shape_data = dict(layer.shape_data, corner_radius=0, corner_radii=[0] * 4)
    ShapesTool._bake_shape(layer.image, layer.shape_data, doc.selection)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")
    assert layer.image.pixelColor(11, 11).alpha() > 0   # square corner at radius 0

    w._on_opt_changed("shape_corner_radius", 15)

    assert layer.shape_data["corner_radius"] == 15
    assert layer.image.pixelColor(11, 11).alpha() == 0  # now rounded away


def test_shape_type_option_does_not_live_edit_an_existing_shape(main_window):
    """Unlike color/fill/etc, the shape *kind* stays creation-time-only —
    matching Illustrator/Photoshop, which also don't let you swap a
    rectangle into a star after the fact."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")

    w._on_opt_changed("shape_type", "star")

    assert layer.shape_data["shape"] == "rect"


def test_shape_option_edit_is_a_noop_when_shapes_tool_not_active(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Brush")

    w._on_opt_changed("shape_color", QColor(0, 255, 0))

    assert layer.shape_data["fg"] == "#ff0000"


def test_selecting_a_shape_layer_syncs_the_options_bar_to_its_own_values(main_window):
    """Real risk: without this, the corner-radius spinbox would keep
    showing whatever was left over from the last shape drawn/edited, so
    turning it on a newly-selected shape would jump from the wrong
    starting number instead of that shape's actual current radius."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc, rect=(10, 10, 41, 41), shape_type="rounded_rect",
                              shape_color=QColor(0, 128, 255))
    layer.shape_data = dict(layer.shape_data, corner_radius=33, corner_radii=[33] * 4)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")

    page = w._opts_bar._pages["Shapes"]
    assert page._radius_sp.value() != 33  # sanity: didn't already happen to match

    w._on_layer_selected_wrap(doc.active_layer_index)

    assert page._radius_sp.value() == 33
    assert page._color_btn._color.name() == "#0080ff"


def test_rapid_shape_option_edits_coalesce_into_one_history_entry(main_window):
    """A slider drag fires many valueChanged signals in a row — that must
    not spam the undo stack with one entry per intermediate value."""
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = _make_shape_layer(doc, rect=(10, 10, 41, 41), shape_type="rounded_rect")
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")

    before = len(w._history._undo_stack)
    for radius in range(0, 16):
        w._on_opt_changed("shape_corner_radius", radius)
    after = len(w._history._undo_stack)

    assert after == before + 1
    assert layer.shape_data["corner_radius"] == 15
