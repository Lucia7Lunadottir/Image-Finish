"""Regression tests for a real bug found while auditing pixel-bridging code:
in this PyQt6 build (6.11.0 / Qt 6.11.2), `QColor(QImage.pixel(x, y))`
always reports alpha=255 regardless of the actual pixel — `QImage.pixel()`
itself returns the correct ARGB int (verified: `(raw >> 24) & 0xFF` is
right), but the `QColor(int)` constructor PyQt6 picks silently drops the
alpha byte. `QImage.pixelColor(x, y)` (or `QColor.fromRgba(raw)`) reads it
correctly. Found 9 call sites across the app using the broken pattern;
switched all of them to `.pixelColor()`. Two had a real, live behavioral
bug (this file); the rest either had an explicit follow-up `setAlpha(255)`
already, only ever read RGB, or sampled genuinely-opaque data (a desktop
screenshot) — fixed anyway for consistency, but no test needed there.
"""
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from tools.brush_tool import MixerBrushTool


def test_pixelcolor_reads_alpha_correctly(qapp):
    """The actual bug, isolated: QColor(img.pixel(...)) vs img.pixelColor(...)."""
    from PyQt6.QtGui import QImage
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 100, 50, 128))
    assert img.pixelColor(0, 0).alpha() == 128


def test_mixer_brush_does_not_pull_color_from_transparent_canvas(qapp):
    """MixerBrushTool.on_move gates its color-mixing on
    `canvas_color.alpha() > 0` specifically to skip sampling empty canvas.
    Before the fix, that check was always true (bug), so dragging over a
    transparent area pulled the mix color toward black. With the fix,
    sampling a transparent pixel must leave _mix_color untouched."""
    doc = Document(100, 80)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))  # fully transparent canvas

    tool = MixerBrushTool()
    opts = {"brush_size": 10, "brush_hardness": 1.0, "brush_opacity": 1.0,
            "brush_mask": "round", "brush_blend_mode": "SourceOver"}
    fg = QColor(10, 200, 10)
    tool.on_press(QPoint(50, 40), doc, fg, QColor(), opts)
    mix_before = QColor(tool._mix_color)
    tool.on_move(QPoint(55, 40), doc, tool._mix_color, QColor(), opts)

    assert tool._mix_color.getRgb() == mix_before.getRgb()


def test_mixer_brush_does_pull_color_from_opaque_canvas(qapp):
    """Contrast case: sampling an opaque area should shift the mix color."""
    doc = Document(100, 80)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 80, QColor(250, 10, 10, 255))
    p.end()

    tool = MixerBrushTool()
    opts = {"brush_size": 10, "brush_hardness": 1.0, "brush_opacity": 1.0,
            "brush_mask": "round", "brush_blend_mode": "SourceOver"}
    fg = QColor(10, 200, 10)
    tool.on_press(QPoint(50, 40), doc, fg, QColor(), opts)
    mix_before = QColor(tool._mix_color)
    tool.on_move(QPoint(55, 40), doc, tool._mix_color, QColor(), opts)

    assert tool._mix_color.getRgb() != mix_before.getRgb()
