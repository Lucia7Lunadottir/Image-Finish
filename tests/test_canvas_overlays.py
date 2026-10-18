"""Tool overlays and per-tool canvas behaviour declared on the tool classes
(REPAINT_ON_HOVER, pointer_inside) instead of the canvas listing classes
and swapping attributes."""
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage, QPainter

from core.document import Document


def test_info_pixel_respects_layer_offset(main_window):
    """The Info panel read the layer at document coordinates — on a moved
    layer it showed some other pixel."""
    w = main_window
    w._add_tab(Document(100, 80), "t")
    c = w._doc_tabs.currentWidget()
    layer = c.document.layers[0]
    layer.image.fill(QColor(255, 255, 255))
    layer.image.setPixelColor(5, 5, QColor(10, 20, 30))
    layer.offset = QPoint(30, 20)
    assert c._active_layer_pixel(35, 25) == QColor(10, 20, 30)
    assert c._active_layer_pixel(5, 5).alpha() == 0          # outside the moved layer


def _overlay_image(c):
    img = QImage(c.width(), c.height(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    c._paint_tool_overlays(p)
    p.end()
    return img


def test_pen_segment_to_cursor_hidden_outside_canvas(main_window):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    c = w._doc_tabs.currentWidget()
    c.resize(400, 300)
    w._activate_tool("Pen")
    pen = w._tools["Pen"]
    opts = dict(c.tool_opts, _zoom=1.0)
    for pos in (QPoint(20, 20), QPoint(90, 40)):
        pen.on_press(pos, c.document, QColor(), QColor(), opts)
        pen.on_release(pos, c.document, QColor(), QColor(), opts)
    pen.on_hover(QPoint(150, 120), c.document, QColor(), QColor(), opts)
    c._is_mouse_in = True
    inside = _overlay_image(c)
    c._is_mouse_in = False
    outside = _overlay_image(c)
    assert inside != outside
    assert pen.current_pos is not None          # nothing of the tool's state is touched


def test_repaint_on_hover_tools(main_window):
    hover = {n for n, t in main_window._tools.items() if t.REPAINT_ON_HOVER}
    assert hover == {"Select", "Shapes", "RotateView", "Gradient", "ObjectSelection"}
