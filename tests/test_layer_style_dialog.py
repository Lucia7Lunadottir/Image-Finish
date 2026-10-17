"""Layer Style dialog: Ctrl+Z inside it, and Undo after OK.

Undo after OK did nothing (the history snapshot was taken after the dialog
had already applied the styles), there was no undo inside the dialog, and
re-opening a layer showed sliders at their defaults next to the real
values."""
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import QApplication

from core.document import Document
from core.layer import RasterLayer


def _dialog(layer=None):
    from ui.layer_style_dialog import LayerStyleDialog
    layer = layer or RasterLayer("r", 20, 20)
    return LayerStyleDialog(layer, lambda: None), layer


def _set_blend(dlg, mode):
    combo = dlg.pages["gradient_overlay"]["inputs"]["blend_mode"]
    combo.setCurrentIndex(combo.findData(mode))


def test_undo_and_redo_inside_the_dialog(qapp):
    dlg, layer = _dialog()
    _set_blend(dlg, "Multiply")
    dlg._edit_open = False                         # next edit is a new step
    _set_blend(dlg, "Screen")
    assert dlg.current_styles["gradient_overlay"]["blend_mode"] == "Screen"
    dlg.undo()
    assert dlg.current_styles["gradient_overlay"]["blend_mode"] == "Multiply"
    assert layer.layer_styles["gradient_overlay"]["blend_mode"] == "Multiply"
    dlg.undo()
    assert dlg.current_styles["gradient_overlay"]["blend_mode"] == "SourceOver"
    dlg.redo()
    assert dlg.current_styles["gradient_overlay"]["blend_mode"] == "Multiply"
    dlg.reject()


def test_ctrl_z_reaches_the_dialog_even_from_a_spin_box(qapp):
    dlg, layer = _dialog()
    dlg.show()
    dlg.activateWindow()
    spin = dlg.pages["gradient_overlay"]["inputs"]["opacity"]
    spin.setValue(40)
    assert dlg._undo_stack
    if dlg.isActiveWindow():                       # offscreen platforms may not activate windows
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QApplication.sendEvent(spin, ev)
        assert dlg.current_styles["gradient_overlay"]["opacity"] == 100
    dlg.reject()


def test_one_undo_step_per_slider_drag(qapp):
    dlg, _ = _dialog()
    spin = dlg.pages["drop_shadow"]["inputs"]["opacity"]
    for v in (70, 60, 50, 40):
        spin.setValue(v)
    assert len(dlg._undo_stack) == 1
    dlg.undo()
    assert dlg.current_styles["drop_shadow"]["opacity"] == 75
    dlg.reject()


def test_reopened_dialog_shows_saved_values_on_the_sliders(qapp):
    layer = RasterLayer("r", 20, 20)
    layer.layer_styles = {"drop_shadow": {"enabled": True, "opacity": 33, "angle": 45}}
    dlg, _ = _dialog(layer)
    inputs = dlg.pages["drop_shadow"]["inputs"]
    assert inputs["opacity"].partner.value() == 33
    assert inputs["angle"].partner.value() == 45
    dlg.reject()


def test_undo_after_ok_restores_the_previous_styles(main_window, mocked_dialogs, monkeypatch):
    from ui.layer_style_dialog import LayerStyleDialog
    w = main_window
    w._add_tab(Document(20, 20), "t")
    layer = w._document.get_active_layer()

    def exec_and_ok(self, *a):
        _set_blend(self, "Multiply")
        self.accept()
        return 1
    monkeypatch.setattr(LayerStyleDialog, "exec", exec_and_ok)
    w._open_layer_styles(w._document.active_layer_index)
    assert w._document.get_active_layer().layer_styles["gradient_overlay"]["blend_mode"] == "Multiply"
    w._undo()
    assert not (w._document.get_active_layer().layer_styles or {}).get("gradient_overlay")
