"""VectorLayer v1: a Pen-Tool-drawn path used to be rasterized once into
`layer.image` at creation time (ui/main_window.py's "shape" pen_action
handler did `QPainter(new_layer.image).fillPath(...)`) — a real bezier
`vector_mask` existed already (used as a compositing clip), but the
visible pixels were a one-shot bake, degrading under any future transform
like any other raster layer. `Layer.render_into` now has no override for
this case at all; `VectorLayer.render_into` fills/strokes `vector_mask`
directly every render instead, so it stays exact.
"""
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainterPath

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


def test_vector_layer_without_path_style_falls_back_to_pixel_layer(qapp):
    """ShapesTool's primitive shapes (rect/ellipse/star/...) still bake
    into `image` via `_bake_shape` — that path must keep working exactly
    as before, render_into just draws `image` like a raster layer."""
    doc = Document(100, 80)
    layer = doc.add_layer(name="Rect", layer_cls=VectorLayer)
    layer.shape_data = {"shape": "rect", "rect": (10, 10, 20, 20)}
    from PyQt6.QtGui import QPainter
    p = QPainter(layer.image)
    p.fillRect(10, 10, 20, 20, QColor(10, 200, 10, 255))
    p.end()

    doc.invalidate_composite()
    comp = doc.get_composite()
    assert comp.pixelColor(15, 15).getRgb() == (10, 200, 10, 255)
