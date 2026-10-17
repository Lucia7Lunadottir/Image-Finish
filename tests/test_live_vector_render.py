"""Vector layers stay sharp at any zoom WITHOUT leaving the layer stack.

History: on 2026-09-30 permanently-live shapes were drawn by
ui/shape_scene_overlay.py on top of the whole canvas. That broke layer
order — a shape under an opaque photo layer showed through it (and a
shape inside a hidden group stayed visible). Replaced by
Document.render_view: the canvas re-renders the visible part of the whole
composite at screen resolution, vector layers painting themselves at that
resolution (VectorLayer._render_direct) inside the normal render_into
chain, so order/masks/clipping/adjustments behave exactly as in
get_composite.
"""
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QTransform

from core.document import Document
from core.layer import VectorLayer, GroupLayer, AdjustmentLayer


def _shape_layer(doc, rect=(10, 10, 20, 20), shape="rect", color="#ff0000", **extra):
    layer = doc.add_layer(name="Shape", layer_cls=VectorLayer)
    layer.shape_data = dict({
        "shape": shape, "rect": rect, "fg": color, "bg": color,
        "fill": True, "size": 0, "sides": 6, "angle": 0,
    }, **extra)
    return layer


def _view(doc, scale, w=None, h=None):
    w = w or int(doc.width * scale)
    h = h or int(doc.height * scale)
    return doc.render_view(QTransform.fromScale(scale, scale), QSize(w, h))


def test_render_view_respects_layer_order_shape_under_opaque_layer():
    doc = Document(60, 60)
    _shape_layer(doc, rect=(10, 10, 30, 30))
    top = doc.add_layer(name="photo")
    top.image.fill(QColor("#0000ff"))
    img = _view(doc, 4)
    assert img.pixelColor(25 * 4, 25 * 4).getRgb()[:3] == (0, 0, 255)


def test_render_view_skips_shape_inside_hidden_group():
    doc = Document(60, 60)
    group = doc.add_layer(name="G", layer_cls=GroupLayer)
    group.visible = False
    shape = _shape_layer(doc, rect=(10, 10, 30, 30))
    shape.parent_id = group.layer_id
    img = _view(doc, 4)
    assert img.pixelColor(25 * 4, 25 * 4).getRgb()[:3] == (255, 255, 255)


def test_render_view_matches_composite_colors():
    doc = Document(40, 40)
    _shape_layer(doc, rect=(10, 10, 20, 20))
    img = _view(doc, 3)
    comp = doc.get_composite()
    for x, y in ((15, 15), (5, 5), (35, 35)):
        assert img.pixelColor(x * 3 + 1, y * 3 + 1) == comp.pixelColor(x, y)


def _partial_alpha_run(img, y, x0, x1):
    return sum(1 for x in range(x0, x1) if 0 < img.pixelColor(x, y).alpha() < 255)


def test_shape_edge_is_sharp_in_render_view_not_magnified_pixels():
    """An ellipse edge at 8x: the screen-resolution render has a ~1px
    antialiased edge; the document-resolution composite magnified 8x (what
    the canvas used to show) has edge pixels in 8px blocks."""
    doc = Document(40, 40)
    doc.layers[0].image.fill(QColor(0, 0, 0, 0))
    _shape_layer(doc, rect=(5, 5, 30, 30), shape="ellipse")
    scale = 8
    view = _view(doc, scale)
    magnified = doc.get_composite().scaled(40 * scale, 40 * scale)  # nearest neighbour
    y = int(12.3 * scale)
    left_half = (0, 20 * scale)
    assert _partial_alpha_run(view, y, *left_half) <= 3
    assert _partial_alpha_run(magnified, y, *left_half) >= scale


def test_render_view_applies_adjustment_layer_above_shape():
    doc = Document(40, 40)
    _shape_layer(doc, rect=(10, 10, 20, 20))
    adj = doc.add_layer(name="inv", layer_cls=AdjustmentLayer)
    adj.adjustment_data = {"type": "invert"}
    img = _view(doc, 2)
    assert img.pixelColor(30, 30).getRgb()[:3] == (0, 255, 255)   # inverted red
    assert img.pixelColor(4, 4).getRgb()[:3] == (0, 0, 0)          # inverted white


def test_render_view_adjustment_mask_lines_up_at_zoom():
    import numpy as np
    from core.pixel_buffer import qimage_argb_view
    doc = Document(40, 40)
    adj = doc.add_layer(name="inv", layer_cls=AdjustmentLayer)
    adj.adjustment_data = {"type": "invert"}
    from PyQt6.QtGui import QImage
    mask = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(0, 0, 0))
    arr = qimage_argb_view(mask, writable=True)
    arr[:, 20:40, :] = 255         # only the right half is affected
    del arr
    adj.mask = mask
    _shape_layer(doc, rect=(0, 0, 1, 1))  # vector content present, irrelevant here
    img = _view(doc, 4)
    assert img.pixelColor(10 * 4, 20 * 4).getRgb()[:3] == (255, 255, 255)   # left: untouched
    assert img.pixelColor(30 * 4, 20 * 4).getRgb()[:3] == (0, 0, 0)         # right: inverted


def test_layer_clipped_onto_shape_uses_shape_alpha():
    doc = Document(40, 40)
    _shape_layer(doc, rect=(10, 10, 10, 10))
    clipped = doc.add_layer(name="c")
    clipped.image.fill(QColor("#00ff00"))
    clipped.clipping = True
    comp = doc.get_composite()
    assert comp.pixelColor(15, 15).getRgb()[:3] == (0, 255, 0)      # inside the shape
    assert comp.pixelColor(30, 30).getRgb()[:3] == (255, 255, 255)  # outside: clipped away


def test_opacity_applies_to_fill_and_stroke_as_one():
    """Fill + centered stroke at 50% opacity: where the stroke overlaps the
    fill, only the stroke color shows (no red bleeding through), exactly
    like an opacity on a flattened pixel layer."""
    doc = Document(60, 60)
    doc.layers[0].image.fill(QColor(0, 0, 0, 0))
    layer = _shape_layer(doc, rect=(10, 10, 40, 40), size=10, stroke_color="#0000ff")
    layer.opacity = 0.5
    c = doc.get_composite().pixelColor(12, 30)   # inner half of the left stroke
    assert c.red() == 0 and c.blue() > 0
    assert 110 <= c.alpha() <= 140


def test_get_composite_hides_live_hidden_shape_by_default_but_not_with_respect_live_hidden_false():
    doc = Document(100, 100)
    layer = _shape_layer(doc, rect=(10, 10, 20, 20))
    layer._live_edit_hidden = True  # what a shape drag does for its duration
    doc.invalidate_composite()

    hidden = doc.get_composite()
    assert hidden.pixelColor(15, 15).getRgb()[:3] == (255, 255, 255)

    ground_truth = doc.get_composite(respect_live_hidden=False)
    assert ground_truth.pixelColor(15, 15).getRgb()[:3] == (255, 0, 0)

    # The bypass must not have poisoned the cache the default path reads.
    assert doc.get_composite().pixelColor(15, 15).getRgb()[:3] == (255, 255, 255)


def test_get_composite_respect_live_hidden_false_is_a_noop_when_nothing_is_hidden():
    doc = Document(100, 100)
    _shape_layer(doc, rect=(10, 10, 20, 20))
    doc.invalidate_composite()
    assert (doc.get_composite(respect_live_hidden=False).pixelColor(15, 15).getRgb()
            == doc.get_composite().pixelColor(15, 15).getRgb())


def test_canvas_uses_screen_resolution_render_when_zoomed_in(main_window):
    w = main_window
    doc = Document(50, 50)
    _shape_layer(doc, rect=(10, 10, 20, 20), shape="ellipse")
    w._add_tab(doc, "t")
    canvas = w._canvas
    canvas.resize(400, 300)
    canvas.zoom = 4.0
    canvas._recompute_composite()
    canvas._cache_dirty = False
    assert canvas._hires_wanted("RGB")
    canvas._render_hires()
    assert canvas._hires_image is not None
    assert canvas._hires_key[0] == canvas._composite_cache.cacheKey()

    canvas.zoom = 0.5
    assert not canvas._hires_wanted("RGB")   # zoomed out: the composite is already sharp enough


def test_canvas_does_not_bother_without_vector_layers(main_window):
    w = main_window
    w._add_tab(Document(50, 50), "t")
    canvas = w._canvas
    canvas.zoom = 8.0
    canvas._recompute_composite()
    assert not canvas._hires_wanted("RGB")


def test_masked_shape_stays_sharp_and_masked_in_render_view():
    from PyQt6.QtGui import QImage, QPainter
    doc = Document(40, 40)
    doc.layers[0].image.fill(QColor(0, 0, 0, 0))
    layer = _shape_layer(doc, rect=(5, 5, 30, 30), shape="ellipse")
    mask = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255))
    mp = QPainter(mask)
    mp.fillRect(20, 0, 20, 40, QColor(0, 0, 0))   # right half masked out
    mp.end()
    layer.mask = mask
    view = _view(doc, 8)
    assert view.pixelColor(30 * 8, 20 * 8).alpha() == 0          # masked
    assert view.pixelColor(12 * 8, 20 * 8).alpha() == 255        # visible
    assert _partial_alpha_run(view, int(12.3 * 8), 0, 20 * 8) <= 3   # left edge still sharp


def test_shape_clipped_onto_raster_below_in_composite_and_view():
    doc = Document(40, 40)
    base = doc.add_layer(name="base")
    from PyQt6.QtGui import QPainter
    p = QPainter(base.image)
    p.fillRect(0, 0, 20, 40, QColor("#0000ff"))   # only the left half has pixels
    p.end()
    shape = _shape_layer(doc, rect=(0, 0, 40, 40))
    shape.clipping = True
    comp = doc.get_composite()
    assert comp.pixelColor(10, 20).getRgb()[:3] == (255, 0, 0)     # shape over base pixels
    assert comp.pixelColor(30, 20).getRgb()[:3] == (255, 255, 255)  # clipped away
    view = _view(doc, 4)
    assert view.pixelColor(10 * 4, 20 * 4).getRgb()[:3] == (255, 0, 0)
    assert view.pixelColor(30 * 4, 20 * 4).getRgb()[:3] == (255, 255, 255)
