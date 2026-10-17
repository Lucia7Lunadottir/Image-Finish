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

from PyQt6.QtGui import QPainterPath

from core.document import Document
from core.layer import ArtboardLayer, FrameLayer, TextLayer, GroupLayer, VectorLayer
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


def _path_style_layer(doc, rect=(50, 50, 40, 30)):
    layer = VectorLayer("Shape", doc.width, doc.height)
    path = QPainterPath()
    path.addRect(*rect)
    layer.vector_mask = path
    layer.path_style = {"fill_color": QColor(255, 0, 0, 255),
                        "stroke_color": None, "stroke_width": 0}
    doc.layers = [layer]
    doc.active_layer_index = 0
    return layer


def test_vector_path_style_move_translates_vector_mask_live(qapp):
    """Real bug: MoveTool used to transform self.image for every layer
    kind uniformly — for a path_style VectorLayer, self.image never holds
    the actual shape (render_into paints vector_mask directly), so
    dragging one visibly did nothing at all, during the drag or after."""
    doc = Document(200, 200)
    layer = _path_style_layer(doc)

    tool = MoveTool()
    tool.on_press(QPoint(70, 65), doc, QColor(), QColor(), OPTS)

    # Live preview while still dragging must reflect the in-progress drag.
    tool.on_move(QPoint(90, 85), doc, QColor(), QColor(), OPTS)
    fp = tool.floating_preview()
    assert fp[0] == "live"
    assert fp[1].vector_mask.boundingRect() == QRectF(70, 70, 40, 30)

    tool.apply_transform(doc)
    assert layer.vector_mask.boundingRect() == QRectF(70, 70, 40, 30)
    assert layer.path_style is not None  # untouched
    assert layer.image.size() == doc.layers[0].image.size()  # restored to canvas size, not 1x1


def test_vector_path_style_corner_scale(qapp):
    doc = Document(200, 200)
    layer = _path_style_layer(doc, rect=(0, 0, 100, 100))

    tool = MoveTool()
    tool.on_press(QPoint(100, 100), doc, QColor(), QColor(), NO_CTRL_OPTS)  # br handle
    assert tool._mode == "br"
    tool.on_move(QPoint(150, 150), doc, QColor(), QColor(), NO_CTRL_OPTS)  # scale 1.5x
    tool.apply_transform(doc)

    b = layer.vector_mask.boundingRect()
    assert b.width() == pytest.approx(150.0, rel=1e-6)
    assert b.height() == pytest.approx(150.0, rel=1e-6)


def test_vector_path_style_cancel_leaves_geometry_unchanged(qapp):
    doc = Document(200, 200)
    layer = _path_style_layer(doc)
    original_bounds = layer.vector_mask.boundingRect()

    tool = MoveTool()
    tool.on_press(QPoint(70, 65), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(90, 85), doc, QColor(), QColor(), OPTS)
    tool.cancel_transform(doc)

    assert layer.vector_mask.boundingRect() == original_bounds


def _shape_data_layer(doc, rect=(20, 20, 30, 30)):
    layer = VectorLayer("Shape", doc.width, doc.height)
    sd = {"shape": "rect", "rect": rect, "start": rect[:2], "end": (rect[0]+rect[2], rect[1]+rect[3]),
         "fill": True, "fg": "#00c800", "bg": "#00c800", "size": 0, "sides": 6, "angle": 0}
    layer.shape_data = sd
    from tools.shapes_tool import ShapesTool
    ShapesTool._bake_shape(layer.image, sd, None)
    doc.layers = [layer]
    doc.active_layer_index = 0
    return layer


def test_vector_shape_data_move_updates_rect_and_rebakes(qapp):
    """Real bug: MoveTool used to fall through to the generic raster path
    for shape_data VectorLayers too — same as any plain bitmap, it
    transformed the current *baked pixels*, not the shape's own
    parametric rect, unlike ShapesTool's own handles (ui/shape_scene_overlay.py)
    which always re-bake fresh at the target geometry. That's the same
    live-quality guarantee this hook restores for MoveTool."""
    doc = Document(200, 200)
    layer = _shape_data_layer(doc)

    tool = MoveTool()
    tool.on_press(QPoint(35, 35), doc, QColor(), QColor(), OPTS)
    fp = tool.floating_preview()
    assert fp[0] == "live"  # crisp re-rendered preview, not the stale baked bitmap
    tool.on_move(QPoint(45, 45), doc, QColor(), QColor(), OPTS)
    tool.apply_transform(doc)

    assert layer.shape_data["rect"] == (30, 30, 30, 30)  # +10,+10
    assert layer.image.pixelColor(45, 45).green() == 200   # freshly baked at the new spot
    assert layer.image.pixelColor(25, 25).alpha() == 0     # old spot cleared, not smeared


def test_vector_shape_data_live_preview_reflects_in_progress_drag(qapp):
    """Real bug report: the Move Tool's live preview while dragging a
    ShapesTool shape looked rasterized (blurry stretched bitmap) even
    though the final committed result was fine — because the preview
    reused the stale baked image instead of redrawing the shape
    procedurally like ShapeLayerItem's own drag already does."""
    doc = Document(200, 200)
    layer = _shape_data_layer(doc, rect=(20, 20, 30, 30))

    tool = MoveTool()
    tool.on_press(QPoint(35, 35), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(55, 55), doc, QColor(), QColor(), OPTS)  # +20, +20, mid-drag

    fp = tool.floating_preview()
    assert fp[0] == "live"
    assert fp[1].shape_data["rect"] == (40, 40, 30, 30)
    assert layer.shape_data["rect"] == (20, 20, 30, 30)   # the real layer is untouched mid-drag


def test_vector_shape_data_corner_scale_rebakes_crisp_not_stretched(qapp):
    doc = Document(200, 200)
    layer = _shape_data_layer(doc, rect=(0, 0, 40, 40))

    tool = MoveTool()
    tool.on_press(QPoint(40, 40), doc, QColor(), QColor(), NO_CTRL_OPTS)  # br handle
    assert tool._mode == "br"
    tool.on_move(QPoint(80, 80), doc, QColor(), QColor(), NO_CTRL_OPTS)  # 2x scale
    tool.apply_transform(doc)

    assert layer.shape_data["rect"] == (0, 0, 80, 80)
    assert layer.image.pixelColor(70, 70).green() == 200  # filled all the way to the new edge


def test_vector_shape_data_hidden_from_composite_while_move_tool_drags_it(qapp):
    """Real regression this catches: VectorLayer._get_source_image renders
    shape_data live now (2026-09-30), ignoring .image entirely — so the
    old trick of swapping .image for a 1x1 blank to hide the original
    while floating_preview() shows the live drag on top (see on_press)
    stopped hiding anything for these layers. Without _live_edit_hidden,
    the composite would show the shape at its OLD position (live-rendered
    from the as-yet-unchanged shape_data) underneath MoveTool's own
    "shape_transform" preview at the NEW position — the exact kind of
    doubled/ghosted render she reported for ShapeLayerItem's handles,
    just via the Move tool instead."""
    doc = Document(200, 200)
    layer = _shape_data_layer(doc, rect=(20, 20, 30, 30))

    tool = MoveTool()
    assert not layer._live_edit_hidden
    tool.on_press(QPoint(35, 35), doc, QColor(), QColor(), OPTS)
    assert layer._live_edit_hidden

    doc.invalidate_composite()
    comp = doc.get_composite()
    assert comp.pixelColor(35, 35).alpha() == 0  # old position: contributes nothing while hidden

    tool.on_move(QPoint(45, 45), doc, QColor(), QColor(), OPTS)
    tool.apply_transform(doc)
    assert not layer._live_edit_hidden


def test_vector_shape_data_cancel_also_clears_the_hidden_flag(qapp):
    doc = Document(200, 200)
    layer = _shape_data_layer(doc)

    tool = MoveTool()
    tool.on_press(QPoint(35, 35), doc, QColor(), QColor(), OPTS)
    assert layer._live_edit_hidden
    tool.on_move(QPoint(45, 45), doc, QColor(), QColor(), OPTS)
    tool.cancel_transform(doc)

    assert not layer._live_edit_hidden


def test_vector_shape_data_cancel_leaves_shape_data_unchanged(qapp):
    doc = Document(200, 200)
    layer = _shape_data_layer(doc)
    original = dict(layer.shape_data)

    tool = MoveTool()
    tool.on_press(QPoint(35, 35), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(45, 45), doc, QColor(), QColor(), OPTS)
    tool.cancel_transform(doc)

    assert layer.shape_data == original


def test_text_move_preview_is_the_committed_result(qapp):
    """Text used to preview as its baked bitmap stretched; the preview is
    now the layer re-rendered with the same geometry the commit applies."""
    from core.text_model import TextData, CharStyle
    doc = Document(200, 200)
    layer = TextLayer("t", 200, 200)
    layer.set_data(TextData(text="Hi", runs=[(2, CharStyle(size=24))], x=40, y=40))
    layer.rebake_thumbnail()
    doc.layers.append(layer)
    doc.active_layer_index = 1

    tool = MoveTool()
    c = layer.content_bounds().center().toPoint()
    tool.on_press(c, doc, QColor(), QColor(), OPTS)
    tool.on_move(c + QPoint(30, 10), doc, QColor(), QColor(), OPTS)
    fp = tool.floating_preview()
    assert fp[0] == "live"
    preview = fp[1].data()
    tool.apply_transform(doc)
    committed = layer.data()
    assert (preview.x, preview.y, preview.angle) == (committed.x, committed.y, committed.angle)
    assert committed.x == 70 and committed.y == 50


def test_numeric_transform_panel_scales_text_uniformly(qapp):
    from core.text_model import TextData, CharStyle
    doc = Document(200, 200)
    layer = TextLayer("t", 200, 200)
    layer.set_data(TextData(text="Hi", runs=[(2, CharStyle(size=20))], x=40, y=40))
    layer.rebake_thumbnail()
    doc.layers.append(layer)
    doc.active_layer_index = 1
    tool = MoveTool()
    c = layer.content_bounds().center().toPoint()
    tool.on_press(c, doc, QColor(), QColor(), OPTS)
    params = tool.get_transform_params()
    tool.set_transform_params(doc, dict(params, w=200.0, h=100.0))   # only W changed
    tool.apply_transform(doc)
    assert layer.data().runs[0][1].size == 40
