"""Compositing correctness, including the layer-style result cache."""

import hashlib

from PyQt6.QtGui import QColor, QPainter

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
