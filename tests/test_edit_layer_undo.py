"""Undo after editing a fill / adjustment layer's settings (double-click).

The history snapshot used to be taken after the dialog had already applied
the new settings to the layer, so Undo restored exactly those."""
from PyQt6.QtGui import QColor

from core.document import Document
from core.layer import AdjustmentLayer, FillLayer


def test_undo_after_editing_a_fill_layer(main_window, mocked_dialogs, monkeypatch):
    from ui.fill_layer_dialog import FillLayerDialog
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = FillLayer("f", 20, 20)
    layer.fill_data = {"type": "solid", "color": QColor(10, 20, 30)}
    doc.layers.append(layer)
    doc.active_layer_index = len(doc.layers) - 1

    def edit_and_ok(self, *a):
        self.layer.fill_data = {"type": "solid", "color": QColor(200, 0, 0)}
        return 1
    monkeypatch.setattr(FillLayerDialog, "exec", edit_and_ok)
    w._on_edit_layer()
    assert doc.layers[-1].fill_data["color"] == QColor(200, 0, 0)
    w._undo()
    assert w._document.layers[-1].fill_data["color"] == QColor(10, 20, 30)


def test_undo_after_editing_an_adjustment_layer(main_window, mocked_dialogs, monkeypatch):
    from ui.adjustments_dialog import BrightnessContrastDialog
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.add_layer(name="adj", layer_cls=AdjustmentLayer)
    layer.adjustment_data = {"type": "vibrance", "vibrance": 10, "saturation": 0}
    doc.active_layer_index = doc.layers.index(layer)

    from core.adjustments.vibrance import VibranceDialog

    def edit_and_ok(self, *a):
        self._vib.set_value(80)
        self._on_change()
        self.accept()
        return 1
    monkeypatch.setattr(VibranceDialog, "exec", edit_and_ok)
    w._on_edit_layer()
    assert doc.get_active_layer().adjustment_data["vibrance"] == 80
    w._undo()
    assert w._document.get_active_layer().adjustment_data["vibrance"] == 10
