"""ui/canvas_guides.GuideDrag through the canvas's real mouse handlers."""
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from core.document import Document


def _ev(kind, pos, button=Qt.MouseButton.LeftButton):
    buttons = button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    return QMouseEvent(kind, QPointF(*pos), QPointF(*pos), button, buttons, Qt.KeyboardModifier.NoModifier)


def _canvas(w):
    w._add_tab(Document(400, 300), "t")
    c = w._canvas
    c.resize(500, 400)
    c.zoom, c._pan = 1.0, QPointF(30, 30)
    c.show_rulers = True
    c.document.show_guides = True
    return c


def test_drag_a_guide_out_of_the_ruler(main_window, mocked_dialogs):
    c = _canvas(main_window)
    c.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, (5, 100)))          # vertical ruler
    c.mouseMoveEvent(_ev(QEvent.Type.MouseMove, (130, 100)))
    assert c._guides.active
    c.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, (130, 100)))
    assert c.document.guides_v == [100] and not c._guides.active


def test_move_and_delete_an_existing_guide(main_window, mocked_dialogs):
    c = _canvas(main_window)
    main_window._activate_tool("Move")
    c.document.guides_h = [50.0]
    y = 50 + 30                                                             # widget y of the guide
    c.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, (200, y + 2)))
    assert c._guides.active and c.document.guides_h == []
    c.mouseMoveEvent(_ev(QEvent.Type.MouseMove, (200, 150)))
    c.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, (200, 150)))
    assert c.document.guides_h == [120]
    # dropped back onto the ruler = deleted
    c.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, (200, 150)))
    c.mouseMoveEvent(_ev(QEvent.Type.MouseMove, (200, 5)))
    c.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, (200, 5)))
    assert c.document.guides_h == []
