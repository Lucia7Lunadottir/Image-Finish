"""Right-click menu on the canvas (ui/canvas_context_menu.py) and the
commands it brought: Layer via Copy/Cut, Free Transform, rotating and
flipping an open transform, path fill/stroke on the work path."""
import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from core.locale import tr
from ui.canvas_context_menu import MenuContext, build_canvas_menu
from ui.tool_catalog import TOOLS


def _paint(layer, rect, color=QColor(200, 0, 0)):
    layer.image.fill(0)
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            layer.image.setPixelColor(x, y, color)


def _open(w, size=(100, 80)):
    w._add_tab(Document(*size), "t")
    _paint(w._document.layers[0], QRect(10, 10, 20, 20))
    return w._doc_tabs.currentWidget()


def _menu_texts(w, pos=QPoint(15, 15)):
    c = w._canvas
    menu = build_canvas_menu(MenuContext(w, c, c.document, c.active_tool, pos), w)
    return None if menu is None else [a.text() for a in menu.actions() if a.text()]


def _select(doc, rect):
    sel = QPainterPath()
    sel.addRect(QRectF(rect))
    doc.selection = sel


def test_every_tool_builds_its_menu(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    for name in TOOLS:
        w._activate_tool(name)
        texts = _menu_texts(w)
        assert (texts is not None) == (w._tools[name].CONTEXT_MENU is not None), (name, texts)


def test_selection_menu_with_and_without_selection(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    w._activate_tool("Select")
    assert tr("menu.select_all") in _menu_texts(w)
    _select(w._document, QRect(5, 5, 10, 10))
    texts = _menu_texts(w)
    assert tr("menu.deselect") in texts and tr("menu.layer_via_copy") in texts
    assert tr("menu.select_all") not in texts


def test_open_transform_takes_over_the_menu(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    w._free_transform()
    texts = _menu_texts(w)
    assert texts[:2] == [tr("opts.apply"), tr("opts.cancel")]
    assert tr("ctx.transform.flip_h") in texts


def test_move_menu_lists_layers_under_pointer(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    doc = w._document
    top = doc.add_layer(name="top")
    _paint(top, QRect(12, 12, 4, 4))
    w._activate_tool("Move")
    texts = _menu_texts(w, QPoint(13, 13))
    assert texts[:2] == ["top", doc.layers[0].name]
    assert "top" not in _menu_texts(w, QPoint(25, 25))


def test_layer_via_copy_and_cut_on_offset_layer(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    doc = w._document
    src = doc.layers[0]
    src.offset = QPoint(30, 20)                 # red at doc (40..59, 30..49)
    _select(doc, QRect(40, 30, 10, 10))
    w._layer_via_copy()
    copy = doc.layers[1]
    assert copy is doc.get_active_layer() and copy is not src
    assert (copy.offset.x(), copy.offset.y()) == (40, 30)
    assert copy.image.pixelColor(5, 5).red() == 200
    assert src.image.pixelColor(15, 15).alpha() == 255          # copy leaves it
    doc.active_layer_index = 0
    w._layer_via_cut()
    assert src.image.pixelColor(15, 15).alpha() == 0            # cut removes it
    w._undo()
    assert w._document.layers[0].image.pixelColor(15, 15).alpha() == 255


def test_layer_via_copy_without_selection_duplicates(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    w._layer_via_copy()
    assert len(w._document.layers) == 2


def test_free_transform_rotate_and_flip(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    layer = w._document.layers[0]
    _paint(layer, QRect(10, 10, 30, 10))                        # 30 wide, 10 tall
    layer.image.setPixelColor(10, 10, QColor(0, 0, 255))        # marker: top-left
    w._free_transform()
    tool = w._tools["Move"]
    assert tool.is_transforming
    w._transform_rotate(90)
    w._commit_transforms()
    from core.document import Document as _D
    br = _D._nontransparent_bounds(w._document.layers[0].image)
    assert abs(br.width() - 10) <= 1 and abs(br.height() - 30) <= 1

    _paint(layer := w._document.layers[0], QRect(10, 10, 30, 10))
    layer.offset = QPoint(0, 0)
    layer.image.setPixelColor(10, 10, QColor(0, 0, 255))
    w._free_transform()
    w._transform_flip(True)
    w._commit_transforms()
    img, off = w._document.layers[0].image, w._document.layers[0].offset
    right = img.pixelColor(39 - off.x(), 10 - off.y())
    assert right.blue() > 200 and right.red() < 50              # marker now on the right
    assert w._history.undo_description() == tr("tool.move")


def test_path_fill_respects_layer_offset(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    layer = w._document.layers[0]
    layer.image.fill(0)
    layer.offset = QPoint(30, 20)
    wp = {"nodes": [{"p": QPointF(x, y), "c1": QPointF(x, y), "c2": QPointF(x, y)}
                    for x, y in ((40, 30), (60, 30), (60, 50), (40, 50))], "closed": True}
    w._path_fill(wp)
    assert layer.image.pixelColor(20, 20).alpha() == 255        # doc (50, 40)
    assert layer.image.pixelColor(45, 35).alpha() == 0


def test_crop_menu_cancel(main_window, mocked_dialogs):
    w = main_window
    _open(w)
    w._activate_tool("Crop")
    tool = w._tools["Crop"]
    tool.pending_rect = QRect(5, 5, 50, 40)
    w._cancel_crop(tool)
    assert tool.pending_rect is None


def test_brush_picker_edits_follow_everywhere(main_window, mocked_dialogs):
    """The picker writes through the option handler: every open document,
    the options bar and the Brushes panel show the same brush."""
    from ui.brush_picker import BrushPicker
    w = main_window
    c = _open(w)
    w._activate_tool("Brush")
    picker = build_canvas_menu(MenuContext(w, c, c.document, c.active_tool, QPoint(15, 15)), w)
    assert isinstance(picker, BrushPicker)
    picker._size.spin.setValue(800)                              # past the slider's 500
    assert c.tool_opts["brush_size"] == 800
    assert picker._size.slider.value() == 500 and picker._size.value() == 800
    picker._hardness.slider.setValue(40)
    assert c.tool_opts["brush_hardness"] == pytest.approx(0.4)
    page = w._opts_bar.page_for("Brush")
    assert page._size.value() == 800 and page._hardness.value() == 40
    tip = next(t.value for t in __import__("ui.brush_widgets", fromlist=["x"]).tip_library().tips()
               if t.value == "square")
    picker._grid._on_click(tip)
    assert c.tool_opts["brush_mask"] == "square"
    assert page._mask_combo.currentData() == "square"
    assert w._brushes_panel._grid.current() == "square"


def test_brush_picker_pins_outline_while_open(main_window, mocked_dialogs):
    w = main_window
    c = _open(w)
    w._activate_tool("Brush")
    picker = build_canvas_menu(MenuContext(w, c, c.document, c.active_tool, QPoint(15, 15)), w)
    picker.exec(QPoint(10, 10))
    assert c._brush_outline_at is not None
    picker.close()
    assert c._brush_outline_at is None


def test_brushes_panel_selection_reaches_options_bar(main_window, mocked_dialogs):
    """Picking a tip in the Brushes panel used to change only the current
    canvas — the options bar kept showing the old tip."""
    w = main_window
    c = _open(w)
    w._brushes_panel.brush_selected.emit("scatter")
    assert c.tool_opts["brush_mask"] == "scatter"
    assert w._opts_bar.page_for("Brush")._mask_combo.currentData() == "scatter"


def test_every_tip_lists_the_same_everywhere(main_window):
    from ui.brush_widgets import tip_library
    w = main_window
    values = [t.value for t in tip_library().tips()]
    combo = w._opts_bar.page_for("Brush")._mask_combo
    assert [combo.itemData(i) for i in range(combo.count() - 1)] == values   # last: "Load…"
    assert [t.value for t in w._brushes_panel._grid._thumbs] == values
