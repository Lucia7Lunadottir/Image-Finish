"""Compositing correctness, including the layer-style result cache."""

import hashlib

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter

from core.document import Document


def _digest(img):
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return hashlib.md5(bytes(ptr)).hexdigest()


def test_composite_stable_across_passes(qapp):
    doc = Document(200, 150)
    doc.add_layer()
    doc.layers[1].image.fill(QColor(0, 128, 255, 180))
    doc.layers[1].layer_styles = {
        "drop_shadow": {"enabled": True, "color": QColor(0, 0, 0),
                        "opacity": 75, "distance": 5, "size": 8},
    }
    doc.invalidate_composite()
    first = _digest(doc.get_composite())
    for _ in range(3):  # subsequent passes hit the style cache
        doc.invalidate_composite()
        assert _digest(doc.get_composite()) == first


def test_style_cache_invalidates_on_paint(qapp):
    doc = Document(200, 150)
    doc.layers[0].layer_styles = {
        "outer_glow": {"enabled": True, "color": QColor(255, 255, 0),
                       "opacity": 60, "size": 6},
    }
    doc.invalidate_composite()
    before = _digest(doc.get_composite())
    p = QPainter(doc.layers[0].image)
    p.fillRect(20, 20, 60, 60, QColor(255, 0, 0))
    p.end()
    doc.invalidate_composite()
    assert _digest(doc.get_composite()) != before


def test_style_cache_invalidates_on_style_change(qapp):
    doc = Document(200, 150)
    styles = {"outer_glow": {"enabled": True, "color": QColor(255, 255, 0),
                             "opacity": 60, "size": 6}}
    doc.layers[0].layer_styles = styles
    # Small opaque shape on a transparent layer: the glow lands on canvas,
    # so a glow color change must change composite pixels.
    doc.layers[0].image.fill(0)
    p = QPainter(doc.layers[0].image)
    p.fillRect(80, 60, 40, 30, QColor(30, 30, 30))
    p.end()
    doc.invalidate_composite()
    before = _digest(doc.get_composite())
    styles["outer_glow"]["color"] = QColor(255, 0, 255)
    doc.invalidate_composite()
    assert _digest(doc.get_composite()) != before


def test_save_load_composite_identical(qapp, tmp_path):
    from core.serialization import load_document, save_document
    doc = Document(120, 90)
    doc.add_layer()
    doc.layers[1].image.fill(QColor(10, 200, 30, 200))
    doc.invalidate_composite()
    before = _digest(doc.get_composite())

    path = str(tmp_path / "x.imfn")
    save_document(doc, path)
    doc2, _ = load_document(path)
    doc2.invalidate_composite()
    assert _digest(doc2.get_composite()) == before


# ─────────────────────────────────────────────── incremental (dirty-rect) recompositing

def test_incremental_matches_full_recompute_blend_stack(qapp):
    doc = Document(200, 150)
    doc.add_layer()
    doc.layers[1].image.fill(QColor(0, 128, 255, 180))
    doc.layers[1].blend_mode = "Multiply"
    doc.invalidate_composite()
    doc.get_composite()  # warm the cache the incremental path blits into

    # Paint a small stroke, like a brush would, then recompute only its rect.
    p = QPainter(doc.layers[1].image)
    p.fillRect(30, 40, 20, 20, QColor(255, 0, 0, 255))
    p.end()
    dirty = QRect(25, 35, 30, 30)
    incremental = doc.get_composite(dirty_rect=dirty).copy()

    doc.invalidate_composite()
    full = doc.get_composite()
    assert _digest(incremental) == _digest(full)


def test_incremental_matches_full_recompute_with_mask(qapp):
    doc = Document(200, 150)
    layer = doc.layers[0]
    layer.image.fill(QColor(200, 200, 200, 255))

    mask = QImage(200, 150, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255, 255))
    mp = QPainter(mask)
    mp.fillRect(0, 0, 100, 150, QColor(80, 80, 80, 255))  # partial mask
    mp.end()
    layer.mask = mask

    doc.invalidate_composite()
    doc.get_composite()

    p = QPainter(layer.image)
    p.fillRect(60, 60, 25, 25, QColor(10, 200, 30, 255))
    p.end()
    dirty = QRect(55, 55, 35, 35)
    incremental = doc.get_composite(dirty_rect=dirty).copy()

    doc.invalidate_composite()
    full = doc.get_composite()
    assert _digest(incremental) == _digest(full)


def test_incremental_matches_full_recompute_single_layer_fast_path(qapp):
    # Exercises the single-visible-raster-layer shortcut in _render_composite.
    doc = Document(80, 60)
    doc.layers[0].image.fill(QColor(10, 20, 30, 255))
    doc.invalidate_composite()
    doc.get_composite()

    p = QPainter(doc.layers[0].image)
    p.fillRect(10, 10, 15, 15, QColor(250, 250, 250, 255))
    p.end()
    dirty = QRect(5, 5, 25, 25)
    incremental = doc.get_composite(dirty_rect=dirty).copy()

    doc.invalidate_composite()
    full = doc.get_composite()
    assert _digest(incremental) == _digest(full)


def test_incremental_leaves_untouched_pixels_alone(qapp):
    """The point of the dirty rect: painting near the top-left must not
    perturb pixels far away, even transiently."""
    doc = Document(200, 150)
    doc.layers[0].image.fill(QColor(255, 255, 255, 255))
    doc.invalidate_composite()
    doc.get_composite()

    p = QPainter(doc.layers[0].image)
    p.fillRect(5, 5, 10, 10, QColor(0, 0, 0, 255))
    p.end()
    result = doc.get_composite(dirty_rect=QRect(0, 0, 20, 20))
    assert QColor(result.pixel(190, 140)) == QColor(255, 255, 255, 255)
    assert QColor(result.pixel(8, 8)) == QColor(0, 0, 0, 255)


def test_eligibility_excludes_exotic_layers(qapp):
    doc = Document(50, 50)
    assert doc._composite_eligible_for_partial() is True

    doc.layers[0].layer_styles = {"outer_glow": {"enabled": True}}
    assert doc._composite_eligible_for_partial() is False
    doc.layers[0].layer_styles = None

    doc.layers[0].clipping = True
    assert doc._composite_eligible_for_partial() is False
    doc.layers[0].clipping = False

    doc.layers[0].layer_type = "adjustment"
    assert doc._composite_eligible_for_partial() is False
    doc.layers[0].layer_type = "artboard"
    assert doc._composite_eligible_for_partial() is False
    doc.layers[0].layer_type = "raster"

    assert doc._composite_eligible_for_partial() is True
    doc.quick_mask_layer = doc.layers[0].copy(deep_image=False)
    assert doc._composite_eligible_for_partial() is False
    doc.quick_mask_layer = None


def test_incremental_falls_back_to_full_when_not_eligible(qapp):
    """Styled layers disable the partial path (a shadow can spread outside
    whatever rect a caller supplies). If a caller invalidates and still
    passes a stale dirty_rect anyway, eligibility must force a full,
    correct recompute rather than a partial render of excluded content."""
    doc = Document(120, 90)
    doc.layers[0].layer_styles = {
        "drop_shadow": {"enabled": True, "color": QColor(0, 0, 0),
                        "opacity": 75, "distance": 5, "size": 8},
    }
    doc.layers[0].image.fill(0)
    p = QPainter(doc.layers[0].image)
    p.fillRect(40, 30, 20, 20, QColor(200, 30, 30, 255))
    p.end()

    doc.invalidate_composite()
    reference = doc.get_composite().copy()  # ground truth: full recompute, no dirty_rect

    doc.invalidate_composite()
    result = doc.get_composite(dirty_rect=QRect(38, 28, 24, 24))
    assert _digest(result) == _digest(reference)


def test_incremental_matches_full_via_real_brush_tool(qapp):
    """End-to-end: BrushTool.get_dirty_rect() feeding get_composite()
    directly, the same wiring CanvasWidget._recompute_composite() uses."""
    from PyQt6.QtCore import QPoint
    from tools.brush_tool import BrushTool

    doc = Document(200, 150)
    doc.add_layer()
    doc.layers[1].blend_mode = "Multiply"
    doc.layers[1].image.fill(QColor(0, 128, 255, 180))
    doc.invalidate_composite()
    doc.get_composite()

    tool = BrushTool()
    opts = {"brush_size": 20, "brush_hardness": 1.0, "brush_opacity": 1.0,
            "brush_mask": "round", "brush_blend_mode": "SourceOver"}
    fg = QColor(255, 0, 0)
    tool.on_press(QPoint(50, 50), doc, fg, QColor(), opts)
    tool.on_move(QPoint(70, 60), doc, fg, QColor(), opts)
    tool.on_release(QPoint(70, 60), doc, fg, QColor(), opts)

    dirty = tool.get_dirty_rect()
    assert dirty is not None and not dirty.isEmpty()
    incremental = doc.get_composite(dirty_rect=dirty).copy()

    doc.invalidate_composite()
    full = doc.get_composite()
    assert _digest(incremental) == _digest(full)
