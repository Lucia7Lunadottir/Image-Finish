"""Gradient Map adjustment: full gradient (core/gradient_model.Gradient).

The adjustment *layer* used to do nothing at all: its dialog stored the
colors under widget-attribute keys ("shadow_btn"/"highlight_btn") while the
renderer read "shadows"/"highlights" — and then tried to tuple-unpack the
QColor defaults, which raised inside a catch-all."""
from PyQt6.QtGui import QColor

from core.document import Document
from core.gradient_model import Gradient, ColorStop
from core.layer import AdjustmentLayer
from core.adjustments.gradient_map import apply_gradient_map, gradient_map_from_data


def _doc_with_map(data, fill=QColor(255, 255, 255)):
    doc = Document(10, 10)
    doc.layers[0].image.fill(fill)
    layer = doc.add_layer(name="gm", layer_cls=AdjustmentLayer)
    layer.adjustment_data = dict(data, type="gradient_map")
    return doc


def test_adjustment_layer_applies_the_gradient():
    g = Gradient(color_stops=[ColorStop(0, QColor(255, 0, 0)), ColorStop(1, QColor(0, 0, 255))])
    white = _doc_with_map({"gradient": g.to_dict()}).get_composite().pixelColor(5, 5)
    black = _doc_with_map({"gradient": g.to_dict()}, QColor(0, 0, 0)).get_composite().pixelColor(5, 5)
    assert white.getRgb()[:3] == (0, 0, 255) and black.getRgb()[:3] == (255, 0, 0)


def test_old_two_color_data_and_reverse():
    d = {"shadows": QColor(0, 255, 0), "highlights": QColor(255, 0, 255), "reverse": True}
    assert _doc_with_map(d).get_composite().pixelColor(5, 5).getRgb()[:3] == (0, 255, 0)


def test_midpoints_and_multiple_stops_are_used(qapp):
    from PyQt6.QtGui import QImage
    g = Gradient(color_stops=[ColorStop(0, QColor(0, 0, 0)), ColorStop(0.5, QColor(255, 0, 0)),
                              ColorStop(1, QColor(255, 255, 255))])
    img = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(128, 128, 128))
    assert apply_gradient_map(img, g).pixelColor(0, 0).red() > 240
    assert apply_gradient_map(img, g).pixelColor(0, 0).green() < 15


def test_dialog_saves_explicit_data_and_restores_it_on_reopen(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.add_layer(name="gm", layer_cls=AdjustmentLayer)
    g = Gradient(color_stops=[ColorStop(0, QColor(10, 20, 30)), ColorStop(1, QColor(200, 100, 50))])
    layer.adjustment_data = {"type": "gradient_map", "gradient": g.to_dict(), "reverse": True}
    dlg = w._get_adj_dialog(layer, "gradient_map")
    assert dlg._reverse.isChecked()                       # restored, not reset to defaults
    assert dlg.adjustment_data()["gradient"] == g.to_dict()
    assert layer.adjustment_data["gradient"] == g.to_dict()
    restored = gradient_map_from_data(layer.adjustment_data)
    assert restored.reverse and restored.color_at(1.0).red() == 10
