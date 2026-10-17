"""VectorLayer v1: a Pen-Tool-drawn path used to be rasterized once into
`layer.image` at creation time (ui/main_window.py's "shape" pen_action
handler did `QPainter(new_layer.image).fillPath(...)`) — a real bezier
`vector_mask` existed already (used as a compositing clip), but the
visible pixels were a one-shot bake, degrading under any future transform
like any other raster layer. `path_style` fills/strokes `vector_mask`
directly every render instead, so it stays exact.

v2 (2026-09-30): ShapesTool primitives (`shape_data` — rect/ellipse/star/
line/...) got the same treatment, via `VectorLayer._get_source_image`
rather than a `render_into` override — that hook already existed for
`FillLayer`'s "no real `.image`, render on demand" case, so masks/
clipping/layer styles/blend-mode/opacity all keep working for shape_data
layers exactly as before, unaffected by the switch. `.image` is still kept
baked after every edit (`ShapesTool._bake_shape`), but purely so the
Layers-panel thumbnail — which reads `layer.image` directly, not through
the composite pipeline — has something to show.
"""
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainterPath, QImage, QPainter

from core.document import Document
from core.layer import VectorLayer


def _doc_with_pen_shape(rect=QRectF(20, 20, 30, 30)):
    doc = Document(100, 80)
    path = QPainterPath()
    path.addEllipse(rect)
    layer = doc.add_layer(name="Path", layer_cls=VectorLayer)
    layer.vector_mask = path
    layer.vector_mask_enabled = True
    layer.path_style = {"fill_color": QColor(200, 30, 30), "stroke_color": None, "stroke_width": 0.0}
    return doc, layer


def test_vector_layer_fills_from_vector_mask_live(qapp):
    doc, layer = _doc_with_pen_shape()
    doc.invalidate_composite()
    comp = doc.get_composite()
    assert comp.pixelColor(35, 35).getRgb()[:3] == (200, 30, 30)   # inside the ellipse
    assert comp.pixelColor(5, 5).getRgb() == (255, 255, 255, 255)  # outside: default white background


def test_vector_layer_never_rasterized_to_image(qapp):
    """The whole point of the fix: no baking step, `image` stays blank."""
    doc, layer = _doc_with_pen_shape()
    assert layer.image.pixelColor(35, 35).alpha() == 0


def test_vector_layer_reflects_mask_mutation_without_rebaking(qapp):
    """Directly prove it's live: mutate `vector_mask` in place (no re-bake
    call anywhere) and the composite must reflect the new geometry."""
    doc, layer = _doc_with_pen_shape(QRectF(10, 10, 10, 10))
    doc.invalidate_composite()
    comp1 = doc.get_composite()
    assert comp1.pixelColor(60, 60).getRgb() == (255, 255, 255, 255)  # not covered by the small ellipse

    bigger = QPainterPath()
    bigger.addEllipse(QRectF(10, 10, 70, 70))
    layer.vector_mask = bigger
    doc.invalidate_composite()
    comp2 = doc.get_composite()
    assert comp2.pixelColor(60, 60).getRgb()[:3] == (200, 30, 30)  # now covered


def test_vector_layer_with_stroke(qapp):
    doc, layer = _doc_with_pen_shape()
    layer.path_style = {"fill_color": None, "stroke_color": QColor(0, 0, 200), "stroke_width": 4.0}
    doc.invalidate_composite()
    comp = doc.get_composite()
    # Interior (fill=None) shows the background through, but the ring near
    # the ellipse's edge is stroked.
    assert comp.pixelColor(35, 35).getRgb() == (255, 255, 255, 255)
    edge_colors = [comp.pixelColor(20 + i, 35).getRgb()[:3] for i in range(0, 3)]
    assert (0, 0, 200) in edge_colors


def test_vector_layer_move_tool_bounds_uses_path_not_full_canvas(qapp):
    doc, layer = _doc_with_pen_shape(QRectF(20, 20, 30, 30))
    bounds = layer.move_tool_bounds()
    assert bounds.width() < 90  # not the full 100x80 canvas fallback
    assert 15 < bounds.left() < 25


def test_vector_layer_shape_data_renders_live_ignoring_stale_image(qapp):
    """ShapesTool's primitive shapes (rect/ellipse/star/...) render live
    from shape_data now, the same way path_style does — VectorLayer.
    _get_source_image draws fresh every composite instead of reading
    `.image`. `.image` is still kept baked by ShapesTool._bake_shape after
    edits (see ShapeLayerItem._commit_to_layer), but purely for the
    Layers-panel thumbnail, which reads it directly; the composite must
    NOT be affected by whatever's sitting in `.image` — proven here by
    manually painting something else into `.image` and asserting the
    composite shows the shape_data-described rect instead."""
    doc = Document(100, 80)
    layer = doc.add_layer(name="Rect", layer_cls=VectorLayer)
    layer.shape_data = {"shape": "rect", "rect": (10, 10, 20, 20),
                        "fill": True, "fg": "#0ac80a", "size": 0}
    p = QPainter(layer.image)
    p.fillRect(10, 10, 20, 20, QColor(200, 10, 10, 255))  # stale/wrong color in .image
    p.end()

    doc.invalidate_composite()
    comp = doc.get_composite()
    assert comp.pixelColor(15, 15).getRgb()[:3] == (10, 200, 10)  # the real shape_data color, not .image's


def test_vector_layer_shape_data_reflects_mutation_without_rebaking(qapp):
    """Directly prove it's live, mirroring the path_style test above:
    mutate shape_data in place (no _bake_shape call anywhere) and the
    composite must reflect the new geometry."""
    doc = Document(100, 100)
    layer = doc.add_layer(name="Rect", layer_cls=VectorLayer)
    layer.shape_data = {"shape": "rect", "rect": (10, 10, 10, 10),
                        "fill": True, "fg": "#0000c8", "size": 0}
    doc.invalidate_composite()
    comp1 = doc.get_composite()
    assert comp1.pixelColor(60, 60).getRgb() == (255, 255, 255, 255)  # not covered by the small rect

    layer.shape_data = dict(layer.shape_data, rect=(10, 10, 70, 70))
    doc.invalidate_composite()
    comp2 = doc.get_composite()
    assert comp2.pixelColor(60, 60).getRgb()[:3] == (0, 0, 200)  # now covered


def test_vector_layer_shape_data_still_respects_a_layer_mask(qapp):
    """The switch to VectorLayer._get_source_image (rather than a
    render_into override) means shape_data now goes through the exact same
    generic mask/clip/opacity/blend-mode pipeline every other layer kind
    does — proven directly: a shape spanning the whole canvas, masked to
    only its left half, must not show up on the right half."""
    doc = Document(100, 100)
    layer = doc.add_layer(name="Rect", layer_cls=VectorLayer)
    layer.shape_data = {"shape": "rect", "rect": (0, 0, 100, 100),
                        "fill": True, "fg": "#0ac80a", "size": 0}

    mask = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255, 255))
    mp = QPainter(mask)
    mp.fillRect(50, 0, 50, 100, QColor(0, 0, 0, 255))  # right half fully masked out
    mp.end()
    layer.mask = mask

    doc.invalidate_composite()
    comp = doc.get_composite()
    assert comp.pixelColor(20, 50).getRgb()[:3] == (10, 200, 10)   # left half: shape shows
    assert comp.pixelColor(80, 50).getRgb() == (255, 255, 255, 255)  # right half: masked away


def test_vector_layer_shape_data_image_stays_baked_for_the_thumbnail(qapp):
    """Layers-panel thumbnails read layer.image directly (not through the
    composite pipeline) — ShapesTool._bake_shape must still keep it
    populated even though the canvas itself ignores it now."""
    from tools.shapes_tool import ShapesTool
    doc = Document(100, 80)
    layer = doc.add_layer(name="Rect", layer_cls=VectorLayer)
    sd = {"shape": "rect", "rect": (10, 10, 20, 20), "fill": True, "fg": "#0ac80a", "size": 0}
    ShapesTool._bake_shape(layer.image, sd, None)
    layer.shape_data = sd
    assert layer.image.pixelColor(15, 15).getRgb()[:3] == (10, 200, 10)
