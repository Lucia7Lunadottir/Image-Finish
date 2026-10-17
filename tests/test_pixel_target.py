"""ui/actions/pixel_target.py — the gate in front of every pixel command.

Filters and Image > Adjustments used to edit whatever the active layer's
`image` was: on text/shape/fill layers only an invisible baked copy (no
change on the canvas, but an undo step), on adjustment layers an unused
image."""
import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox

from core.document import Document
from core.layer import AdjustmentLayer, TextLayer


def _doc_with(w, layer_cls, **attrs):
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.add_layer(name="L", layer_cls=layer_cls)
    for k, v in attrs.items():
        setattr(layer, k, v)
    doc.active_layer_index = doc.layers.index(layer)
    return doc, layer


def _answer(monkeypatch, button):
    asked = []
    def question(*a, **k):
        asked.append(a)
        return button
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


@pytest.mark.parametrize("command", ["_gaussian_blur", "_brightness_contrast", "_invert",
                                     "_open_noise", "_match_color"])
def test_adjustment_layer_is_refused_without_an_undo_step(main_window, mocked_dialogs, command):
    w = main_window
    doc, layer = _doc_with(w, AdjustmentLayer, adjustment_data={"type": "invert"})
    before = len(w._history._undo_stack)
    fn = getattr(w, command)
    fn("add") if command == "_open_noise" else fn()
    assert len(w._history._undo_stack) == before
    assert doc.layers[doc.active_layer_index] is layer
    assert w._status.currentMessage()


def test_text_layer_cancel_keeps_it_text(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with(w, TextLayer, text_data={"text": "hi", "x": 2, "y": 2, "font_size": 12})
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    w._gaussian_blur()
    assert asked
    assert doc.get_active_layer() is layer and layer.layer_type == "text"


def test_text_layer_ok_rasterizes_then_runs(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with(w, TextLayer, text_data={"text": "hi", "x": 2, "y": 2, "font_size": 12})
    _answer(monkeypatch, QMessageBox.StandardButton.Ok)
    w._invert()
    active = doc.get_active_layer()
    assert active.layer_type == "raster" and active.name == "L"


def test_raster_layer_goes_straight_through(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.get_active_layer()
    layer.image.fill(QColor(10, 20, 30))
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    w._invert()
    assert not asked
    assert doc.get_active_layer().image.pixelColor(0, 0) == QColor(245, 235, 225)
