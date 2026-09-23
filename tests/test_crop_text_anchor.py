"""Regression: cropping the canvas used to leave a text/shape layer's stored
local-space anchor (text_data/shape_data x,y) pointing at its pre-crop
position, so re-editing the layer afterwards redrew it in the wrong spot.
"""

from PyQt6.QtCore import QRect, QPoint

from core.document import Document
from core.layer import TextLayer, VectorLayer


def test_crop_shifts_text_anchor_to_match_new_local_origin():
    doc = Document(100, 100)
    layer = TextLayer("Text 1", 100, 100)
    layer.text_data = {"text": "Hi", "x": 40, "y": 40, "font_size": 24}
    doc.layers.append(layer)
    doc.active_layer_index = len(doc.layers) - 1

    doc.apply_crop(QRect(20, 20, 50, 50))

    # The crop's top-left is (20, 20); the anchor must move by the same
    # amount so it still points at the same visual spot inside the
    # now-smaller, re-based layer image.
    assert layer.text_data["x"] == 20
    assert layer.text_data["y"] == 20


def test_crop_shifts_shape_anchor_rect_start_end():
    doc = Document(100, 100)
    layer = VectorLayer("Shape 1", 100, 100)
    layer.shape_data = {
        "shape": "rect", "rect": (30, 30, 20, 20),
        "start": (30, 30), "end": (50, 50),
        "sides": 6, "angle": 0, "fill": True, "size": 3,
        "fg": "#ff0000", "bg": "#ff0000",
    }
    doc.layers.append(layer)
    doc.active_layer_index = len(doc.layers) - 1

    doc.apply_crop(QRect(10, 10, 60, 60))

    assert layer.shape_data["rect"] == (20, 20, 20, 20)
    assert layer.shape_data["start"] == (20, 20)
    assert layer.shape_data["end"] == (40, 40)


def test_crop_does_not_touch_layers_without_content_data():
    doc = Document(100, 100)
    layer = doc.get_active_layer()
    layer.offset = QPoint(5, 5)

    doc.apply_crop(QRect(5, 5, 40, 40))

    assert layer.offset == QPoint(0, 0)
    assert doc.width == 40 and doc.height == 40
