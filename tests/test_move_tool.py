"""Characterization tests for tools/move_tool.py's per-layer-type behavior.

MoveTool has no prior test coverage at all, and it branches on
`getattr(layer, "layer_type", "raster") == "..."` in four separate places
(on_press bounds setup, apply_transform, cancel_transform,
set_transform_params) — the same "dispatch by type string" shape that
Document._render_composite had before it was replaced with
Layer.render_into. These tests pin TODAY's behavior of that dispatch (one
case per branch, plain translate only — deterministic, no antialiasing
noise from scale/rotate) so a future polymorphic refactor of that dispatch
has a safety net, the same way test_composite.py's new tests backstopped
the render_into refactor.
"""
import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QImage

from core.document import Document
from core.layer import ArtboardLayer, FrameLayer, TextLayer, GroupLayer
from tools.move_tool import MoveTool

OPTS = {"_zoom": 1.0, "_ctrl": True}  # _ctrl=True disables snapping noise
NO_CTRL_OPTS = {"_zoom": 1.0}  # the primary (non-Ctrl) corner-drag-resize path


def _press_move(tool, doc, center: QPoint, delta: QPoint):
    tool.on_press(center, doc, QColor(), QColor(), OPTS)
    tool.on_move(center + delta, doc, QColor(), QColor(), OPTS)


def test_move_raster_no_selection_apply(qapp):
    doc = Document(200, 150)
    layer = doc.layers[0]
    layer.offset = QPoint(10, 20)
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(20, 20, 40, 40, QColor(200, 50, 50, 255))
    p.end()

    tool = MoveTool()
    # Bounds (doc coords) = nontransparent rect (20,20,40,40) + offset(10,20)
    # = (30,40,40,40); center = (50,60), safely away from any resize handle.
    _press_move(tool, doc, QPoint(50, 60), QPoint(30, -15))
    tool.apply_transform(doc)

    assert layer.offset == QPoint(40, 5)
    # Pure translate: pixel content must survive unchanged, just relocated.
    assert QColor(layer.image.pixel(20, 20)).getRgb() == (200, 50, 50, 255)


def test_move_raster_no_selection_cancel(qapp):
    doc = Document(200, 150)
    layer = doc.layers[0]
    layer.offset = QPoint(10, 20)
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(20, 20, 40, 40, QColor(200, 50, 50, 255))
    p.end()

    tool = MoveTool()
    _press_move(tool, doc, QPoint(50, 60), QPoint(30, -15))
    tool.cancel_transform(doc)

    assert layer.offset == QPoint(10, 20)
    assert QColor(layer.image.pixel(20, 20)).getRgb() == (200, 50, 50, 255)


def test_move_artboard_apply_resets_to_origin(qapp):
    """Moving the sole artboard always ends with `artboard_rect` back at
    (0,0) after `apply_transform`'s internal `doc.fit_to_artboards()` call
    (it re-anchors the document to the artboard) — a non-obvious but fully
    deterministic side effect of today's artboard branch."""
    doc = Document(100, 80)
    ab = doc.layers[0].convert_to(ArtboardLayer)
    ab.artboard_rect = QRect(0, 0, 100, 80)
    doc.layers[0] = ab
    child = doc.add_layer(name="Child")
    child.parent_id = ab.layer_id
    child.offset = QPoint(5, 5)
    doc.active_layer_index = doc.layers.index(ab)  # add_layer() re-selected the child

    tool = MoveTool()
    _press_move(tool, doc, QPoint(50, 40), QPoint(20, 10))
    tool.apply_transform(doc)

    assert ab.artboard_rect.topLeft() == QPoint(0, 0)
    assert ab.artboard_rect.width() == 100 and ab.artboard_rect.height() == 80
    # Child is a linked descendant: on_move already dragged it in lockstep
    # with the artboard (+delta), then fit_to_artboards' re-anchor shifts
    # everything by -delta (the artboard's own new topLeft) — the two
    # cancel out, so a child ends up back at its original offset.
    assert child.offset == QPoint(5, 5)


def test_move_artboard_cancel_restores_rect(qapp):
    doc = Document(100, 80)
    ab = doc.layers[0].convert_to(ArtboardLayer)
    ab.artboard_rect = QRect(0, 0, 100, 80)
    doc.layers[0] = ab

    tool = MoveTool()
    _press_move(tool, doc, QPoint(50, 40), QPoint(20, 10))
    tool.cancel_transform(doc)

    assert ab.artboard_rect == QRect(0, 0, 100, 80)


def test_move_frame_apply(qapp):
    doc = Document(200, 150)
    frame = doc.layers[0].convert_to(FrameLayer)
    frame.frame_data = {"rect": QRectF(20, 20, 40, 30), "shape": "rect"}
    frame.image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    doc.layers[0] = frame

    tool = MoveTool()
    _press_move(tool, doc, QPoint(40, 35), QPoint(15, -5))
    tool.apply_transform(doc)

    r = frame.frame_data["rect"]
    assert (round(r.x()), round(r.y()), round(r.width()), round(r.height())) == (35, 15, 40, 30)


def test_move_frame_cancel(qapp):
    doc = Document(200, 150)
    frame = doc.layers[0].convert_to(FrameLayer)
    frame.frame_data = {"rect": QRectF(20, 20, 40, 30), "shape": "rect"}
    frame.image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    doc.layers[0] = frame

    tool = MoveTool()
    _press_move(tool, doc, QPoint(40, 35), QPoint(15, -5))
    tool.cancel_transform(doc)

    r = frame.frame_data["rect"]
    assert (r.x(), r.y(), r.width(), r.height()) == (20, 20, 40, 30)


def test_move_text_apply_updates_position_and_rerenders(qapp):
    doc = Document(200, 150)
    text = doc.layers[0].convert_to(TextLayer)
    text.text_data = {"text": "Hi", "x": 30, "y": 40, "font_size": 24}
    doc.layers[0] = text

    tool = MoveTool()
    # No rendered glyphs yet -> bounds falls back to the full layer rect;
    # click its center, away from any handle.
    _press_move(tool, doc, QPoint(100, 75), QPoint(12, -8))
    tool.apply_transform(doc)

    assert text.text_data["x"] == 42
    assert text.text_data["y"] == 32
    assert not text.image.isNull()


def test_move_group_translates_children_via_linked_children(qapp):
    doc = Document(200, 150)
    group = doc.layers[0].convert_to(GroupLayer)
    doc.layers[0] = group
    child = doc.add_layer(name="Child")
    child.parent_id = group.layer_id
    child.image.fill(QColor(10, 20, 30, 255))
    child.offset = QPoint(5, 5)
    doc.active_layer_index = doc.layers.index(group)  # add_layer() re-selected the child

    tool = MoveTool()
    _press_move(tool, doc, QPoint(60, 60), QPoint(25, 10))
    # Group children are already moved live during on_move (not deferred to
    # apply_transform, which is a no-op for groups) — verify pre-commit.
    assert child.offset == QPoint(30, 15)
    tool.apply_transform(doc)
    assert child.offset == QPoint(30, 15)


def test_move_group_cancel_restores_children(qapp):
    doc = Document(200, 150)
    group = doc.layers[0].convert_to(GroupLayer)
    doc.layers[0] = group
    child = doc.add_layer(name="Child")
    child.parent_id = group.layer_id
    child.offset = QPoint(5, 5)
    doc.active_layer_index = doc.layers.index(group)  # add_layer() re-selected the child

    tool = MoveTool()
    _press_move(tool, doc, QPoint(60, 60), QPoint(25, 10))
    tool.cancel_transform(doc)

    assert child.offset == QPoint(5, 5)


def test_text_layer_edge_handle_still_hittable(qapp):
    """Edge handles stay clickable for text too — dragging one now scales
    proportionally instead of stretching just that one axis (see
    test_text_layer_edge_drag_scales_proportionally below)."""
    doc = Document(200, 150)
    text = doc.layers[0].convert_to(TextLayer)
    doc.layers[0] = text

    tool = MoveTool()
    tool.on_press(QPoint(100, 75), doc, QColor(), QColor(), OPTS)
    assert tool._get_handle_hit(QPointF(100, 2), OPTS) == "t"


def test_text_layer_edge_drag_scales_proportionally(qapp):
    """Dragging a single-axis edge handle on a text layer still moves both
    width and height together (converted into a uniform scale), instead of
    stretching only the dragged axis."""
    doc = Document(200, 150)
    text = doc.layers[0].convert_to(TextLayer)
    doc.layers[0] = text

    tool = MoveTool()
    tool.on_press(QPoint(100, 0), doc, QColor(), QColor(), NO_CTRL_OPTS)  # 't' handle
    assert tool._mode == "t"
    tool.on_move(QPoint(100, -30), doc, QColor(), QColor(), NO_CTRL_OPTS)  # drag top edge up

    params = tool.get_transform_params()
    assert params["w"] == pytest.approx(params["h"], rel=1e-6)
    assert params["w"] == pytest.approx(120.0, rel=1e-6)


def test_raster_layer_edge_drag_stretches_one_axis_only(qapp):
    """Contrast case: without the uniform-scale-only flag, an edge drag
    only ever touches the axis it belongs to."""
    doc = Document(200, 150)
    layer = doc.layers[0]
    layer.image.fill(QColor(10, 10, 10, 255))

    tool = MoveTool()
    tool.on_press(QPoint(100, 0), doc, QColor(), QColor(), NO_CTRL_OPTS)
    assert tool._mode == "t"
    tool.on_move(QPoint(100, -30), doc, QColor(), QColor(), NO_CTRL_OPTS)

    params = tool.get_transform_params()
    assert params["w"] == pytest.approx(100.0, rel=1e-6)
    assert params["h"] == pytest.approx(120.0, rel=1e-6)


def test_text_layer_corner_scale_locks_aspect_ratio(qapp):
    """A corner drag with very different x/y distances still ends up with
    equal width/height scale factors for text (forced-Shift behavior)."""
    doc = Document(200, 150)
    text = doc.layers[0].convert_to(TextLayer)
    doc.layers[0] = text

    tool = MoveTool()
    tool.on_press(QPoint(200, 150), doc, QColor(), QColor(), NO_CTRL_OPTS)  # br handle
    assert tool._mode == "br"
    tool.on_move(QPoint(300, 170), doc, QColor(), QColor(), NO_CTRL_OPTS)  # +100x, +20y

    params = tool.get_transform_params()
    assert params["w"] == pytest.approx(params["h"], rel=1e-6)
    assert params["w"] == pytest.approx(150.0, rel=1e-6)  # locked to the larger axis


def test_raster_layer_corner_scale_is_independent_per_axis(qapp):
    """Contrast case: without the uniform-scale-only flag, x/y scale freely."""
    doc = Document(200, 150)
    layer = doc.layers[0]
    layer.image.fill(QColor(10, 10, 10, 255))

    tool = MoveTool()
    tool.on_press(QPoint(200, 150), doc, QColor(), QColor(), NO_CTRL_OPTS)
    assert tool._mode == "br"
    tool.on_move(QPoint(300, 170), doc, QColor(), QColor(), NO_CTRL_OPTS)

    params = tool.get_transform_params()
    assert params["w"] != pytest.approx(params["h"], rel=1e-6)
