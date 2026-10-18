"""Make Work Path from a selection (multi-component work paths) and
Edit > Stroke."""
import pytest
from PyQt6.QtCore import QPoint, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from core.history import clone_work_path
from core.path_from_selection import selection_to_work_path
from core.selection_stroke import stroke_selection
from tools.pen_tool import (DirectSelectionTool, PenTool, build_bezier_path, has_path,
                            path_components)


def _rect(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def test_rect_selection_becomes_four_corner_nodes(qapp):
    wp = selection_to_work_path(_rect(10, 10, 50, 30))
    comps = path_components(wp)
    assert len(comps) == 1 and len(comps[0]["nodes"]) == 4 and comps[0]["closed"]
    assert all(n["c1"] == n["p"] == n["c2"] for n in comps[0]["nodes"])


def test_selection_with_hole_keeps_both_outlines(qapp):
    frame = _rect(0, 0, 100, 100).subtracted(_rect(30, 30, 40, 40))
    wp = selection_to_work_path(frame)
    assert len(path_components(wp)) == 2
    path = build_bezier_path(wp)
    assert path.contains(QPointF(10, 10)) and not path.contains(QPointF(50, 50))


def test_ellipse_gets_smooth_nodes(qapp):
    e = QPainterPath()
    e.addEllipse(QRectF(0, 0, 200, 120))
    nodes = path_components(selection_to_work_path(e))[0]["nodes"]
    assert 6 <= len(nodes) <= 40
    assert any(n["c1"] != n["p"] for n in nodes)


def test_clone_keeps_components(qapp):
    wp = selection_to_work_path(_rect(0, 0, 10, 10).united(_rect(50, 50, 10, 10)))
    clone = clone_work_path(wp)
    assert len(path_components(clone)) == 2
    clone["subpaths"][0]["nodes"][0]["p"].setX(999)
    assert path_components(wp)[0]["nodes"][0]["p"].x() != 999


def test_pen_click_after_closing_starts_new_component(qapp):
    doc = Document(100, 100)
    pen = PenTool()
    for pt in ((10, 10), (50, 10), (50, 50), (10, 10)):           # last one closes
        pen.on_press(QPoint(*pt), doc, None, None, {})
        pen.on_release(QPoint(*pt), doc, None, None, {})
    assert doc.work_path["closed"]
    pen.on_press(QPoint(70, 70), doc, None, None, {})
    comps = path_components(doc.work_path)
    assert len(comps) == 2 and comps[0]["closed"] and len(comps[1]["nodes"]) == 1


def test_direct_selection_edits_any_component(qapp):
    doc = Document(200, 200)
    doc.work_path = selection_to_work_path(_rect(10, 10, 40, 40).united(_rect(100, 100, 40, 40)))
    tool = DirectSelectionTool()
    tool.on_press(QPoint(10, 10), doc, None, None, {})          # corner of the first square
    tool.on_move(QPoint(0, 0), doc, None, None, {})
    tool.on_release(QPoint(0, 0), doc, None, None, {})
    pts = [n["p"] for c in path_components(doc.work_path) for n in c["nodes"]]
    assert QPointF(0, 0) in pts and len(path_components(doc.work_path)) == 2


def test_make_work_path_command(main_window, mocked_dialogs, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (2.0, True)))
    w = main_window
    w._add_tab(Document(100, 80), "t")
    w._document.selection = _rect(10, 10, 30, 20)
    w._make_work_path()
    assert has_path(w._document.work_path) and w._document.selection is None
    w._undo()
    assert not has_path(w._document.work_path) and w._document.selection is not None


@pytest.mark.parametrize("location, inside_px, outside_px", [
    ("inside", 255, 0), ("center", 255, 255), ("outside", 0, 255)])
def test_stroke_locations(qapp, location, inside_px, outside_px):
    doc = Document(100, 100)
    img = doc.layers[0].image
    img.fill(0)
    out = stroke_selection(img, QPoint(0, 0), _rect(20, 20, 60, 60), width=6,
                           color=QColor(255, 0, 0), location=location)
    assert out.pixelColor(22, 50).alpha() == inside_px           # just inside the edge
    assert out.pixelColor(17, 50).alpha() == outside_px          # just outside
    assert out.pixelColor(50, 50).alpha() == 0                   # middle untouched


def test_stroke_respects_layer_offset_and_preserve_transparency(qapp):
    doc = Document(100, 100)
    layer = doc.layers[0]
    layer.image.fill(0)
    layer.image.setPixelColor(5, 30, QColor(0, 0, 255))          # doc (25, 50) after offset
    layer.offset = QPoint(20, 20)
    out = stroke_selection(layer.image, layer.offset, _rect(20, 20, 60, 60), width=10,
                           color=QColor(255, 0, 0), location="inside", preserve_transparency=True)
    assert out.pixelColor(5, 30).red() == 255                    # opaque pixel recoloured
    assert out.pixelColor(5, 40).alpha() == 0                    # transparent stays transparent


def test_stroke_command_uses_dialog_settings(main_window, mocked_dialogs, monkeypatch):
    from ui.stroke_dialog import StrokeDialog, StrokeSettings
    monkeypatch.setattr(StrokeDialog, "exec", lambda self: 1)
    monkeypatch.setattr(StrokeDialog, "settings",
                        lambda self: StrokeSettings(width=4, color=QColor(0, 255, 0), location="outside"))
    w = main_window
    w._add_tab(Document(100, 80), "t")
    w._document.layers[0].image.fill(0)
    w._document.selection = _rect(20, 20, 40, 30)
    w._stroke_selection()
    img = w._document.layers[0].image
    assert img.pixelColor(18, 30).green() == 255 and img.pixelColor(30, 30).alpha() == 0
    assert w._history.undo_description()
