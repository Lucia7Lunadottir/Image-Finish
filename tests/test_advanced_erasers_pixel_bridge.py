"""advanced_erasers.py used a read-copy-then-explicit-writeback ctypes
pattern (np.empty + memmove in, mutate, memmove back out). Migrated to a
direct writable core.pixel_buffer.qimage_argb_view (mutating it IS mutating
the QImage — no separate write-back needed, one fewer full-canvas copy).
No prior test coverage existed for either eraser.
"""
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from tools.advanced_erasers import MagicEraserTool, BackgroundEraserTool


def test_magic_eraser_clears_contiguous_matching_region(qapp):
    doc = Document(60, 40)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(10, 10, 20, 20, QColor(200, 50, 50, 255))
    p.fillRect(40, 10, 10, 10, QColor(10, 200, 10, 255))  # unrelated island
    p.end()

    tool = MagicEraserTool()
    tool.on_press(QPoint(15, 15), doc, QColor(), QColor(), {"fill_tolerance": 10, "fill_contiguous": True})

    assert layer.image.pixelColor(15, 15).alpha() == 0
    assert layer.image.pixelColor(29, 29).alpha() == 0
    assert layer.image.pixelColor(45, 15).getRgb() == (10, 200, 10, 255)  # untouched island


def test_background_eraser_clears_matching_color_in_radius(qapp):
    doc = Document(60, 40)
    layer = doc.layers[0]
    layer.image.fill(QColor(80, 80, 200, 255))  # uniform background

    tool = BackgroundEraserTool()
    tool.on_press(QPoint(30, 20), doc, QColor(), QColor(), {"brush_size": 10, "fill_tolerance": 20})

    assert layer.image.pixelColor(30, 20).alpha() == 0
    assert layer.image.pixelColor(0, 0).getRgb() == (80, 80, 200, 255)  # outside brush radius
