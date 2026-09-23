"""tools/tool_utils.py::cut_floating_selection replaces an identical ~25
line block that used to be copy-pasted in move_tool.py, puppet_warp_tool.py
and perspective_warp_tool.py (none of which had any test coverage for this
path). One shared implementation now, exercised here directly and through
MoveTool's own floating-selection branch.
"""
from PyQt6.QtCore import QPoint, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath

from core.document import Document
from tools.tool_utils import cut_floating_selection
from tools.move_tool import MoveTool
from tools.warp_tool import WarpTool


def _doc_with_selection(sel_rect=QRect(20, 10, 30, 30)):
    doc = Document(80, 60)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(0, 0, 80, 60, QColor(200, 60, 40, 255))
    p.end()
    sel = QPainterPath()
    sel.addRect(QRectF(sel_rect))
    doc.selection = sel
    return doc, layer, sel


def test_cut_floating_selection_punches_hole_and_returns_cut_piece(qapp):
    doc, layer, sel = _doc_with_selection()
    original_img, original_offset, sel_origin, ok = cut_floating_selection(layer, sel)

    assert ok is True
    assert original_offset == QPoint(20, 10)
    # Cut piece holds the selected color...
    assert QColor(original_img.pixel(5, 5)).getRgb()[:3] == (200, 60, 40)
    # ...and the source layer now has a hole where the selection was.
    assert layer.image.pixelColor(30, 20).alpha() == 0
    # Outside the selection, the layer is untouched.
    assert layer.image.pixelColor(5, 5).getRgb() == (200, 60, 40, 255)


def test_cut_floating_selection_empty_intersection_reports_not_ok(qapp):
    doc = Document(80, 60)
    layer = doc.layers[0]
    sel = QPainterPath()
    sel.addRect(QRectF(200, 200, 10, 10))  # entirely outside the layer

    original_img, original_offset, sel_origin, ok = cut_floating_selection(layer, sel)
    assert ok is False
    assert original_img is None


def test_move_tool_floating_selection_drag_via_shared_cut(qapp):
    doc, layer, sel = _doc_with_selection()

    tool = MoveTool()
    tool.on_press(QPoint(35, 25), doc, QColor(), QColor(), {"_zoom": 1.0, "_ctrl": True})
    assert tool.is_transforming
    assert tool._is_floating is True
    assert layer.image.pixelColor(30, 20).alpha() == 0  # hole punched


def test_warp_tool_floating_selection_drag_via_shared_cut(qapp):
    doc, layer, sel = _doc_with_selection()

    tool = WarpTool()
    tool.on_press(QPoint(35, 25), doc, QColor(), QColor(), {})
    assert tool.is_transforming
    assert tool._is_floating is True
    assert layer.image.pixelColor(30, 20).alpha() == 0  # hole punched
