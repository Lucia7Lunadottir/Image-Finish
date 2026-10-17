"""core/pixel_buffer.py mask helpers and the features built on them.

Five copies of "paint a path into a grayscale mask" used QColor(255) —
the RGB integer 0x0000FF (blue), which lands on a Grayscale8 image as 39,
not 255. Modify > Smooth produced an empty selection, Feather was nearly
invisible, Select and Mask started at 15%, Patch blended at 15%."""
import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from core.pixel_buffer import path_mask, stroke_mask, mask_to_path, gray_mask_image


def _rect_path(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def test_path_mask_is_full_white_inside(qapp):
    m = path_mask(_rect_path(10, 10, 20, 20), 50, 50)
    assert m[20, 20] == 255 and m[5, 5] == 0


def test_path_mask_offset(qapp):
    m = path_mask(_rect_path(110, 110, 20, 20), 50, 50, QPoint(100, 100))
    assert m[20, 20] == 255 and m[40, 40] == 0


def test_stroke_mask_is_full_white_on_the_stroke(qapp):
    m = stroke_mask([QPointF(5, 25), QPointF(45, 25)], 6, 50, 50)
    assert m[25, 25] == 255 and m[5, 25] == 0


def test_mask_to_path_roundtrip_and_thresholds(qapp):
    mask = np.zeros((40, 40), dtype=np.float32)
    mask[10:30, 10:30] = 0.8
    mask[0:5, 0:5] = 0.3                      # below 50%: not selected
    path = mask_to_path(mask, QPoint(100, 0))
    assert path.contains(QPointF(120, 20)) and not path.contains(QPointF(102, 2))
    assert mask_to_path(np.zeros((5, 5), dtype=bool)).isEmpty()


def test_gray_mask_image_values(qapp):
    img = gray_mask_image(np.array([[0.0, 1.0]], dtype=np.float32))
    assert img.pixelColor(0, 0).green() == 0 and img.pixelColor(1, 0).green() == 255


def test_modify_smooth_keeps_the_selection(main_window):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    w._document.selection = _rect_path(20, 20, 50, 50)
    from PyQt6.QtWidgets import QInputDialog
    orig = QInputDialog.getInt
    QInputDialog.getInt = staticmethod(lambda *a, **k: (4, True))
    try:
        w._modify_selection("smooth")
    finally:
        QInputDialog.getInt = orig
    sel = w._document.selection
    assert sel is not None and sel.contains(QPointF(45, 45))


def test_fill_respects_the_selection(qapp):
    from tools.fill_tool import FillTool
    doc = Document(60, 60)
    doc.selection = _rect_path(0, 0, 30, 60)
    tool = FillTool()
    opts = {"fill_tolerance": 32, "fill_contiguous": True}
    tool.on_press(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(255, 255, 255), opts)
    tool.on_release(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(255, 255, 255), opts)
    img = doc.layers[0].image
    assert img.pixelColor(10, 30).getRgb()[:3] == (255, 0, 0)
    assert img.pixelColor(50, 30).getRgb()[:3] == (255, 255, 255)
