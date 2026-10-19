"""Canvas edge handles on all four sides (Document.extend_canvas moving the
content when the canvas grows on the left / top), and the Delete key on
every kind of layer."""
import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainterPath
from PyQt6.QtWidgets import QMessageBox

from core.document import Document
from core.layer import AdjustmentLayer, FillLayer, RasterLayer, TextLayer, VectorLayer
from core.path_model import path_components


def _opaque_doc(w=100, h=80, color=QColor(255, 255, 255)):
    doc = Document(w, h)
    doc.layers[0].image.fill(color)
    return doc


def _rect_path(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


# ── Document.extend_canvas ───────────────────────────────────────────────────

def test_growing_left_and_top_moves_pixels_and_fills_the_background(qapp):
    doc = _opaque_doc()
    top = doc.add_layer(name="dot")
    top.image.setPixelColor(10, 10, QColor(255, 0, 0))
    doc.extend_canvas(20, 30, 0, 0, QColor(1, 2, 3))
    assert (doc.width, doc.height) == (120, 110)
    comp = doc.get_composite()
    assert comp.pixelColor(30, 40) == QColor(255, 0, 0)             # moved with the canvas
    assert comp.pixelColor(5, 5) == QColor(1, 2, 3)                 # new strip: background colour
    assert comp.pixelColor(60, 60) == QColor(255, 255, 255)
    assert doc.layers[0].offset == QPoint(0, 0)                     # background stays a plain layer


def test_growing_on_all_sides_at_once(qapp):
    doc = _opaque_doc()
    doc.extend_canvas(5, 6, 7, 8, QColor(9, 9, 9))
    assert (doc.width, doc.height) == (112, 94)
    comp = doc.get_composite()
    for x, y in ((1, 1), (110, 92), (1, 90), (110, 1)):
        assert comp.pixelColor(x, y) == QColor(9, 9, 9)


def test_shrinking_from_the_left_keeps_the_pixels(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    layer.image.fill(0)
    layer.image.setPixelColor(5, 5, QColor(0, 255, 0))
    doc.extend_canvas(-10, 0, 0, 0)
    assert doc.width == 90
    doc.extend_canvas(10, 0, 0, 0)                                   # back again
    assert doc.get_composite().pixelColor(5, 5) == QColor(0, 255, 0)


def test_text_shape_and_pen_layers_move(qapp):
    doc = _opaque_doc(200, 150)
    text = doc.add_layer(name="T", layer_cls=TextLayer)
    text.text_data = {"text": "Hi", "x": 10, "y": 20, "font_size": 20}
    shape = doc.add_layer(name="S", layer_cls=VectorLayer)
    shape.shape_data = {"shape": "rect", "rect": (40, 40, 20, 20), "fg": "#ff0000", "bg": "#ff0000",
                        "fill": True, "size": 0, "sides": 6, "angle": 0}
    pen = doc.add_layer(name="P", layer_cls=VectorLayer)
    pen.path_style = {"fill_color": QColor(0, 0, 255), "stroke_color": None, "stroke_width": 0}
    pen.path_nodes = {"nodes": [{"p": QPointF(x, y), "c1": QPointF(x, y), "c2": QPointF(x, y)}
                                for x, y in ((100, 100), (140, 100), (140, 140))],
                      "closed": True, "subpaths": [], "op": "unite"}
    pen.update_path()
    text_before = text.content_bounds()
    shape_before = shape.vector_bounds()
    doc.extend_canvas(15, 25, 0, 0)
    assert text.data().x == 25 and text.data().y == 45
    assert text.content_bounds().topLeft() == text_before.topLeft() + QPointF(15, 25)
    assert shape.vector_bounds().topLeft() == shape_before.topLeft() + QPointF(15, 25)
    assert pen._path_nodes_valid() and pen.path_nodes.get("op") == "unite"
    assert pen.vector_mask.boundingRect() == QRectF(115, 125, 40, 40)


def test_fill_and_adjustment_layers_still_cover_the_canvas(qapp):
    doc = _opaque_doc(60, 40)
    fill = doc.add_layer(name="F", layer_cls=FillLayer)
    fill.fill_data = {"type": "solid", "color": "#00ff00"}
    mask = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255))
    mask.setPixelColor(0, 0, QColor(0, 0, 0))
    adj = doc.add_layer(name="A", layer_cls=AdjustmentLayer)
    adj.adjustment_data = {"type": "invert"}
    adj.mask = mask
    doc.extend_canvas(10, 10, 0, 0, QColor(255, 255, 255))
    assert fill.offset == QPoint(0, 0)
    assert adj.mask.pixelColor(10, 10) == QColor(0, 0, 0)          # the mask moved with the content
    assert adj.mask.pixelColor(2, 2) == QColor(255, 255, 255)       # new area: revealed


def test_guides_selection_and_paths_move(qapp):
    doc = _opaque_doc()
    doc.guides_v, doc.guides_h = [10], [20]
    doc.slices = [QRect(1, 1, 5, 5)]
    doc.selection = _rect_path(0, 0, 10, 10)
    doc.work_path = {"nodes": [{"p": QPointF(3, 4), "c1": QPointF(3, 4), "c2": QPointF(3, 4)}], "closed": False}
    doc.saved_paths = [{"nodes": [{"p": QPointF(1, 1), "c1": QPointF(1, 1), "c2": QPointF(1, 1)}],
                        "closed": False, "name": "p"}]
    doc.extend_canvas(5, 7, 0, 0)
    assert doc.guides_v == [15] and doc.guides_h == [27]
    assert doc.slices == [QRect(6, 8, 5, 5)]
    assert doc.selection.boundingRect() == QRectF(5, 7, 10, 10)
    assert doc.work_path["nodes"][0]["p"] == QPointF(8, 11)
    assert doc.saved_paths[0]["nodes"][0]["p"] == QPointF(6, 8)


# ── the handles ──────────────────────────────────────────────────────────────

def _canvas(w, size=(200, 150)):
    w._add_tab(Document(*size), "t")
    c = w._doc_tabs.currentWidget()
    c.document.layers[0].image.fill(QColor(255, 255, 255))
    c.resize(600, 450)
    c.reset_zoom()
    return c


def _mouse(c, kind, pos):
    btn = Qt.MouseButton.LeftButton
    ev = QMouseEvent(kind, QPointF(pos), QPointF(pos), btn,
                     Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else btn,
                     Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: c.mousePressEvent, QEvent.Type.MouseMove: c.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: c.mouseReleaseEvent}[kind](ev)


def _drag(c, handle, doc_target):
    start = c._resize_handles._rects()[handle].center()
    target = c.to_widget(QPointF(*doc_target))
    _mouse(c, QEvent.Type.MouseButtonPress, start)
    _mouse(c, QEvent.Type.MouseMove, target)
    size = c._resize_handles._size
    _mouse(c, QEvent.Type.MouseButtonRelease, target)
    return size


def test_there_are_handles_on_every_side(main_window, mocked_dialogs):
    c = _canvas(main_window)
    rects = c._resize_handles._rects()
    assert set(rects) == {"l", "r", "t", "b", "tl", "tr", "bl", "br"}
    dr = QRectF(c.to_widget(QPointF(0, 0)), c.to_widget(QPointF(200, 150)))
    assert rects["l"].right() < dr.left() and rects["t"].bottom() < dr.top()
    assert rects["r"].left() > dr.right() and rects["b"].top() > dr.bottom()


def test_dragging_the_left_handle_grows_the_canvas_to_the_left(main_window, mocked_dialogs):
    w = main_window
    c = _canvas(w)
    c.document.layers[0].image.setPixelColor(0, 0, QColor(255, 0, 0))
    screen_before = c.to_widget(QPointF(0, 0))
    assert _drag(c, "l", (-40, 75)) == (240, 150)
    doc = c.document
    assert (doc.width, doc.height) == (240, 150)
    assert doc.get_composite().pixelColor(40, 0) == QColor(255, 0, 0)
    assert c.to_widget(QPointF(40, 0)) == screen_before              # the picture didn't jump
    w._undo()
    assert (w._document.width, w._document.height) == (200, 150)


def test_top_left_corner_and_bottom_left_handles(main_window, mocked_dialogs):
    c = _canvas(main_window)
    assert _drag(c, "tl", (-10, -20)) == (210, 170)
    assert _drag(c, "bl", (5, 200)) == (205, 200)      # left edge moved in, bottom out


def test_canvas_never_shrinks_below_one_pixel(main_window, mocked_dialogs):
    c = _canvas(main_window)
    assert _drag(c, "l", (500, 75)) == (1, 150)


# ── Delete ───────────────────────────────────────────────────────────────────

def _doc_with(w, layer_cls, **attrs):
    w._add_tab(Document(60, 60), "t")
    doc = w._document
    layer = doc.add_layer(name="L", layer_cls=layer_cls)
    for k, v in attrs.items():
        setattr(layer, k, v)
    doc.active_layer_index = doc.layers.index(layer)
    return doc, layer


@pytest.mark.parametrize("layer_cls, attrs", [
    (TextLayer, {"text_data": {"text": "Hi", "x": 5, "y": 5, "font_size": 20}}),
    (VectorLayer, {"shape_data": {"shape": "rect", "rect": (5, 5, 20, 20), "fg": "#f00", "bg": "#f00",
                                  "fill": True, "size": 0, "sides": 6, "angle": 0}}),
    (FillLayer, {"fill_data": {"type": "solid", "color": "#00ff00"}}),
    (AdjustmentLayer, {"adjustment_data": {"type": "invert"}}),
])
def test_delete_without_selection_removes_a_layer_drawn_from_data(main_window, mocked_dialogs, layer_cls, attrs):
    w = main_window
    doc, layer = _doc_with(w, layer_cls, **attrs)
    w._clear_layer()
    assert layer not in doc.layers
    w._undo()
    assert any(type(l) is layer_cls for l in w._document.layers)


def test_delete_without_selection_still_clears_a_pixel_layer(main_window, mocked_dialogs):
    w = main_window
    doc, layer = _doc_with(w, RasterLayer)
    layer.image.fill(QColor(255, 0, 0))
    w._clear_layer()
    assert layer in doc.layers and layer.image.pixelColor(5, 5).alpha() == 0


def test_delete_with_selection_on_text_rasterizes_then_clears(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with(w, TextLayer, text_data={"text": "HHHH", "x": 0, "y": 0, "font_size": 40})
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    doc.selection = _rect_path(0, 0, 60, 60)
    w._clear_layer()
    new = doc.get_active_layer()
    assert type(new) is RasterLayer
    assert all(new.image.pixelColor(x, y).alpha() == 0 for x in range(0, 60, 7) for y in range(0, 60, 7))


def test_delete_with_selection_on_an_adjustment_layer_says_why(main_window, mocked_dialogs):
    w = main_window
    doc, layer = _doc_with(w, AdjustmentLayer, adjustment_data={"type": "invert"})
    doc.selection = _rect_path(0, 0, 10, 10)
    before = len(w._history._undo_stack)
    w._clear_layer()
    assert layer in doc.layers and len(w._history._undo_stack) == before
    assert w._status.currentMessage()


def test_delete_while_editing_a_mask_hides_the_selected_area(main_window, mocked_dialogs):
    w = main_window
    doc, layer = _doc_with(w, RasterLayer)
    layer.image.fill(QColor(255, 0, 0))
    mask = QImage(60, 60, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255))
    layer.mask, layer.editing_mask = mask, True
    doc.selection = _rect_path(0, 0, 10, 10)
    w._clear_layer()
    assert layer.mask.pixelColor(5, 5) == QColor(0, 0, 0)
    assert layer.mask.pixelColor(30, 30) == QColor(255, 255, 255)
    assert layer.image.pixelColor(5, 5) == QColor(255, 0, 0)        # pixels untouched
