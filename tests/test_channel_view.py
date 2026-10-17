"""core/channel_view.py and the artboard-frame overlay (moved out of the
canvas paint routine)."""
from PyQt6.QtCore import QPointF, QRect
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath

from core.channel_view import channel_view


def _img(c):
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(c)
    return img


def test_rgb_and_cmyk_channels(qapp):
    src = _img(QColor(200, 100, 50))
    assert channel_view(src, "R").pixelColor(1, 1) == QColor(200, 200, 200)
    assert channel_view(src, "G").pixelColor(1, 1) == QColor(100, 100, 100)
    assert channel_view(src, "B").pixelColor(1, 1) == QColor(50, 50, 50)
    k = channel_view(src, "K").pixelColor(1, 1).red()
    assert k == round((1 - 200 / 255) * 255) or abs(k - 55) <= 1
    assert channel_view(_img(QColor(0, 0, 0)), "C").pixelColor(0, 0).red() == 0   # pure black: no inks but K


def test_alpha_channel_is_opaque_greyscale_of_its_path(qapp):
    path = QPainterPath()
    path.addRect(0, 0, 2, 4)
    v = channel_view(_img(QColor(10, 10, 10, 0)), "alpha_0", [{"path": path}])
    assert v.pixelColor(0, 0) == QColor(255, 255, 255) and v.pixelColor(3, 0) == QColor(0, 0, 0)
    assert channel_view(_img(QColor(1, 2, 3)), "alpha_9", []).pixelColor(0, 0) == QColor(0, 0, 0)


def test_artboard_frames_overlay(qapp):
    from core.document import Document
    from core.layer import ArtboardLayer
    from ui.overlay_renderers import draw_artboard_frames
    doc = Document(100, 80)
    art = doc.add_layer(name="A", layer_cls=ArtboardLayer)
    art.artboard_rect = QRect(10, 20, 50, 40)
    out = QImage(120, 100, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p = QPainter(out)
    draw_artboard_frames(p, doc=doc, pan=QPointF(0, 0), zoom=1.0)
    p.end()
    assert out.pixelColor(10, 40).alpha() > 0        # left edge of the frame
    assert out.pixelColor(35, 40).alpha() == 0       # inside stays clear
