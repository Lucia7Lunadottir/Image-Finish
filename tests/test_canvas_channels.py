"""Channel views on the canvas (Channels panel)."""
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainterPath

from core.document import Document


def test_alpha_channel_view_renders(main_window):
    """Was a NameError (`ctypes` never imported) swallowed by the paint
    loop's catch-all: selecting an alpha channel left the canvas blank."""
    w = main_window
    doc = Document(40, 30)
    path = QPainterPath()
    path.addRect(QRectF(0, 0, 20, 30))
    doc.alpha_channels = [{"name": "Alpha 1", "path": path}]
    w._add_tab(doc, "t")
    canvas = w._canvas
    canvas.view_channel = "alpha_0"
    canvas._recompute_composite()
    canvas._cache_dirty = False
    canvas._display_cache = None
    from PyQt6.QtGui import QImage, QPainter
    img = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    canvas._paint_canvas_content(p, gpu=False)
    p.end()
    shown = canvas._display_cache
    assert shown is not None
    assert shown.pixelColor(5, 5).red() == 255 and shown.pixelColor(35, 5).red() == 0
