"""Undo + Redo keep the step's own name in the history.

The redo step was saved as "redo" and the re-done step pushed back as
"undo", so after Ctrl+Z, Ctrl+Shift+Z the History panel listed "undo"
(English, in every language) and the next Undo reported it too."""
from PyQt6.QtGui import QColor

from core.document import Document


def test_step_name_survives_undo_and_redo(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    w._push_history("Step A")
    w._document.get_active_layer().image.fill(QColor(255, 0, 0))
    w._undo()
    w._redo()
    assert [s.description for s in w._history._undo_stack][-1] == "Step A"
    w._undo()
    assert "Step A" in w._status.currentMessage()


def test_ctrl_i_while_editing_a_mask_inverts_the_mask(main_window, mocked_dialogs):
    from PyQt6.QtGui import QImage
    w = main_window
    w._add_tab(Document(10, 10), "t")
    layer = w._document.get_active_layer()
    layer.mask = QImage(10, 10, QImage.Format.Format_Grayscale8)
    layer.mask.fill(0)
    layer.editing_mask = True
    w._invert()
    assert QColor(w._document.get_active_layer().mask.pixel(5, 5)).red() == 255
