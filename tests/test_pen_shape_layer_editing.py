"""Path-editing tools on a Pen-style shape layer.

Real bug: a shape made from a work path (Pen > Shape, e.g. right after
Make Work Path from a selection) kept only a bare `vector_mask`; the work
path was cleared, and the path selection / direct selection / anchor tools
only ever edited `doc.work_path` — so nothing could edit the shape."""
import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainterPath
from PyQt6.QtWidgets import QInputDialog

from core.document import Document
from tools.pen_tool import (AddAnchorPointTool, DirectSelectionTool, PathSelectionTool,
                            PenTool, build_bezier_path, path_to_work_path)

OPTS = {}


def _node(x, y, c1=None, c2=None):
    p = QPointF(x, y)
    return {"p": p, "c1": QPointF(*c1) if c1 else QPointF(p), "c2": QPointF(*c2) if c2 else QPointF(p)}


def _points(wp):
    return [[(n["p"].x(), n["p"].y(), n["c1"].x(), n["c1"].y(), n["c2"].x(), n["c2"].y())
             for n in comp["nodes"]] + [comp["closed"]]
            for comp in wp.get("subpaths", []) + [wp]]


def test_path_to_work_path_inverts_build_bezier_path():
    wp = {"nodes": [_node(10, 10, c2=(20, 0)), _node(40, 10, c1=(30, 0)), _node(40, 40)],
          "closed": True,
          "subpaths": [{"nodes": [_node(100, 100), _node(120, 100), _node(120, 130)], "closed": False}]}
    back = path_to_work_path(build_bezier_path(wp))
    assert _points(back) == _points(wp)


def test_path_to_work_path_reads_plain_lines():
    path = QPainterPath()
    path.addRect(QRectF(5, 5, 10, 20))
    wp = path_to_work_path(path)
    assert wp["closed"] and [(n["p"].x(), n["p"].y()) for n in wp["nodes"]] == [(5, 5), (15, 5), (15, 25), (5, 25)]


def _shape_from_selection(w):
    w._add_tab(Document(200, 200), "t")
    doc = w._document
    sel = QPainterPath()
    sel.addRect(QRectF(50, 50, 60, 40))
    doc.selection = sel
    w._make_work_path()
    w._activate_tool("Pen")
    w._opt_cmd_pen_action("shape")
    layer = doc.get_active_layer()
    assert layer._is_path_layer()
    assert not doc.work_path["nodes"]
    return doc, layer


@pytest.fixture()
def shape(main_window, mocked_dialogs, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (2.0, True)))
    return _shape_from_selection(main_window)


def test_direct_selection_drags_a_corner_of_the_shape(shape):
    doc, layer = shape
    tool = DirectSelectionTool()
    tool.on_press(QPoint(50, 50), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(30, 20), doc, QColor(), QColor(), OPTS)
    assert layer.vector_mask.boundingRect().topLeft() == QPointF(30, 20)   # live
    tool.on_release(QPoint(30, 20), doc, QColor(), QColor(), OPTS)
    assert layer.vector_mask.boundingRect() == QRectF(30, 20, 80, 70)
    assert not doc.work_path["nodes"]                 # the work path wasn't touched


def test_path_selection_moves_the_whole_shape(shape):
    doc, layer = shape
    tool = PathSelectionTool()
    tool.on_press(QPoint(80, 70), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(90, 75), doc, QColor(), QColor(), OPTS)
    tool.on_release(QPoint(90, 75), doc, QColor(), QColor(), OPTS)
    assert layer.vector_mask.boundingRect() == QRectF(60, 55, 60, 40)


def test_add_anchor_adds_a_node_to_the_shape(shape):
    doc, layer = shape
    tool = AddAnchorPointTool()
    tool.on_press(QPoint(80, 50), doc, QColor(), QColor(), OPTS)
    tool.on_release(QPoint(80, 50), doc, QColor(), QColor(), OPTS)
    assert len(path_to_work_path(layer.vector_mask)["nodes"]) == 5


def test_shape_overlay_shows_the_layer_nodes(shape):
    doc, layer = shape
    assert len(DirectSelectionTool()._get_wp(doc)["nodes"]) == 4
    assert PenTool()._get_wp(doc) is doc.work_path      # drawing still goes to the work path


def test_without_a_shape_layer_the_work_path_is_edited(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    doc.work_path = {"nodes": [_node(10, 10), _node(50, 10), _node(50, 50)], "closed": True}
    tool = DirectSelectionTool()
    tool.on_press(QPoint(10, 10), doc, QColor(), QColor(), OPTS)
    tool.on_move(QPoint(5, 5), doc, QColor(), QColor(), OPTS)
    tool.on_release(QPoint(5, 5), doc, QColor(), QColor(), OPTS)
    assert doc.work_path["nodes"][0]["p"] == QPointF(5, 5)


def _ev(kind, pos):
    button = Qt.MouseButton.LeftButton
    buttons = button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    return QMouseEvent(kind, QPointF(*pos), QPointF(*pos), button, buttons, Qt.KeyboardModifier.NoModifier)


def test_edit_through_the_canvas_is_one_undo_step(main_window, shape):
    w = main_window
    doc, layer = shape
    c = w._canvas
    c.resize(400, 400)
    c.zoom, c._pan = 1.0, QPointF(0, 0)
    w._activate_tool("DirectSelection")
    c.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, (110, 90)))
    c.mouseMoveEvent(_ev(QEvent.Type.MouseMove, (150, 120)))
    c.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, (150, 120)))
    assert doc.get_active_layer().vector_mask.boundingRect() == QRectF(50, 50, 100, 70)
    w._undo()
    assert w._document.get_active_layer().vector_mask.boundingRect() == QRectF(50, 50, 60, 40)


# ── zoom: overlay sizes and hit distances are screen pixels ──────────────────

def _open_path(doc):
    doc.work_path = {"nodes": [_node(100, 100), _node(200, 100), _node(200, 200)], "closed": False}


@pytest.mark.parametrize("zoom, closes", [(4.0, False), (0.5, True)])
def test_closing_the_path_uses_screen_distance(zoom, closes):
    doc = Document(400, 400)
    _open_path(doc)
    PenTool().on_press(QPoint(106, 100), doc, QColor(), QColor(), {"_zoom": zoom})
    # 6 document px from the first node: 24 screen px at 400 %, 3 at 50 %
    assert doc.work_path["closed"] is closes


@pytest.mark.parametrize("zoom, grabs", [(4.0, False), (1.0, True)])
def test_grabbing_a_node_uses_screen_distance(zoom, grabs):
    doc = Document(400, 400)
    _open_path(doc)
    tool = DirectSelectionTool()
    tool.on_press(QPoint(105, 100), doc, QColor(), QColor(), {"_zoom": zoom})
    assert (tool.drag_target is not None) is grabs


def _anchor_width_on_screen(zoom):
    from PyQt6.QtGui import QImage, QPainter
    doc = Document(100, 100)
    doc.work_path = {"nodes": [_node(10, 10), _node(20, 10)], "closed": False}
    img = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.translate(200 - 10 * zoom, 200 - 10 * zoom)     # node (10, 10) at screen (200, 200)
    p.scale(zoom, zoom)
    tool = DirectSelectionTool()
    tool.draw_overlays(p, max(1.0, 1.0 / zoom), doc)
    p.end()
    # walk left from the node centre along a row just below the path line
    row = 200 + 2
    xs = [x for x in range(150, 201) if img.pixelColor(x, row).alpha() > 0]
    return 200 - min(xs)


def test_anchor_squares_keep_their_screen_size_when_zooming():
    assert _anchor_width_on_screen(1.0) == _anchor_width_on_screen(8.0)


def test_switching_tool_or_layer_repaints_the_canvas(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    w._add_tab(Document(50, 50), "t")
    w._document.add_layer("second")
    calls = []
    monkeypatch.setattr(w._canvas, "update", lambda *a: calls.append(a))
    w._activate_tool("DirectSelection")
    assert calls
    calls.clear()
    w._on_layer_selected(0)
    assert calls
