"""Paint-style canvas edge handles, Document.resize_canvas, and the brush
size keys ([ ] and Ctrl + keypad +/−)."""
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent

from core.brush_size_steps import step_size
from core.document import Document
from core.layer import ArtboardLayer


def _canvas(w, size=(200, 150)):
    w._add_tab(Document(*size), "t")
    c = w._doc_tabs.currentWidget()
    c.resize(600, 450)
    c.reset_zoom()
    return c


def _mouse(c, kind, pos, buttons=Qt.MouseButton.LeftButton):
    btn = Qt.MouseButton.LeftButton
    ev = QMouseEvent(kind, QPointF(pos), QPointF(pos), btn,
                     Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else buttons,
                     Qt.KeyboardModifier.NoModifier)
    getattr(c, {QEvent.Type.MouseButtonPress: "mousePressEvent",
                QEvent.Type.MouseMove: "mouseMoveEvent",
                QEvent.Type.MouseButtonRelease: "mouseReleaseEvent"}[kind])(ev)


def test_resize_canvas_fills_background_with_bg_colour(qapp):
    doc = Document(100, 80)
    doc.layers[0].image.fill(QColor(255, 255, 255))
    top = doc.add_layer(name="top")
    doc.resize_canvas(150, 120, QColor(10, 20, 30))
    assert (doc.width, doc.height) == (150, 120)
    bg = doc.layers[0].image
    assert bg.pixelColor(140, 110) == QColor(10, 20, 30)
    assert bg.pixelColor(50, 50) == QColor(255, 255, 255)
    assert top.image.width() >= 150 and top.image.pixelColor(140, 110).alpha() == 0
    doc.resize_canvas(60, 50)                      # smaller: pixels kept beyond it
    assert (doc.width, doc.height) == (60, 50) and bg.width() >= 150


def test_transparent_background_is_not_filled(qapp):
    doc = Document(100, 80)
    doc.layers[0].image.fill(0)
    doc.resize_canvas(150, 120, QColor(10, 20, 30))
    assert doc.layers[0].image.pixelColor(140, 110).alpha() == 0


def test_dragging_corner_handle_resizes_canvas(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    corner = c._resize_handles._rects()["br"].center()
    target = c.to_widget(QPointF(260, 190))
    _mouse(c, QEvent.Type.MouseButtonPress, corner)
    _mouse(c, QEvent.Type.MouseMove, target)
    assert c._resize_handles._size == (260, 190)
    _mouse(c, QEvent.Type.MouseButtonRelease, target)
    assert (c.document.width, c.document.height) == (260, 190)
    w._undo()
    assert (w._document.width, w._document.height) == (200, 150)


def test_right_handle_changes_width_only(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    right = c._resize_handles._rects()["r"].center()
    target = right + QPointF(30 * c.zoom, 40)
    _mouse(c, QEvent.Type.MouseButtonPress, right)
    _mouse(c, QEvent.Type.MouseMove, target)
    _mouse(c, QEvent.Type.MouseButtonRelease, target)
    assert c.document.height == 150 and c.document.width > 200


def test_handles_hidden_with_artboards(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    art = c.document.add_layer(name="a", layer_cls=ArtboardLayer)
    art.artboard_rect = QRect(0, 0, 100, 100)
    assert c._resize_handles.hit(c._resize_handles._rects()["br"].center()) is None


def test_brush_size_steps():
    assert step_size(5, 1) == 6 and step_size(37, 1) == 40 and step_size(37, -1) == 30
    assert step_size(100, 1) == 125 and step_size(125, -1) == 100
    assert step_size(1, -1) == 1 and step_size(5000, 1) == 5000


def _key(c, key, mods=Qt.KeyboardModifier.NoModifier, scan=0, text=""):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, scan, 0, 0, text)
    c.keyPressEvent(ev)


def test_bracket_keys_change_brush_size_everywhere(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    w._activate_tool("Brush")
    w._on_opt_changed("brush_size", 37)
    _key(c, Qt.Key.Key_BracketRight)
    assert c.tool_opts["brush_size"] == 40
    assert w._opts_bar.page_for("Brush")._size.value() == 40     # options bar follows
    _key(c, Qt.Key.Key_BracketLeft)
    assert c.tool_opts["brush_size"] == 30


def test_bracket_keys_work_in_russian_layout(main_window, mocked_dialogs):
    """On a Russian layout the [ key arrives as Х — found by its scan code."""
    w = main_window
    c = _canvas(w)
    w._activate_tool("Brush")
    w._on_opt_changed("brush_size", 20)
    _key(c, 0x0425, scan=35, text="ъ")            # Cyrillic letter on the ] key
    assert c.tool_opts["brush_size"] == 30


def test_ctrl_keypad_plus_is_brush_size_not_zoom(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    w._activate_tool("Brush")
    w._on_opt_changed("brush_size", 10)
    zoom = c.zoom
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier
    _key(c, Qt.Key.Key_Plus, mods)
    assert c.tool_opts["brush_size"] == 20 and c.zoom == zoom


def test_size_keys_ignored_for_non_brush_tools(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    w._activate_tool("Move")
    w._on_opt_changed("brush_size", 10)
    _key(c, Qt.Key.Key_BracketRight)
    assert c.tool_opts["brush_size"] == 10
