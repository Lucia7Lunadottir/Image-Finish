"""The pen tools working like Photoshop's: Shape / Path mode, Ctrl / Alt and
Auto Add/Delete on the Pen itself, Enter to finish, Round Corners."""
import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from core.layer import VectorLayer
from core.path_model import (build_bezier_path, clone_path, path_components, path_to_work_path,
                             round_corners)
from tools.pen_tool import ConvertPointTool, DirectSelectionTool, PenTool

SHAPE = {"pen_mode": "shape", "shape_stroke_width": 4, "shape_stroke": True}


def _press(tool, doc, pos, opts, drag=None):
    tool.on_press(QPoint(*pos), doc, QColor(), QColor(), opts)
    if drag:
        tool.on_move(QPoint(*drag), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(*(drag or pos)), doc, QColor(), QColor(), opts)


def _draw(tool, doc, pts, opts):
    for p in pts:
        _press(tool, doc, p, opts)


def _pen_layers(doc):
    return [l for l in doc.layers if isinstance(l, VectorLayer) and l.path_style]


TRIANGLE = ((50, 50), (150, 50), (150, 150))


# ── shape mode ───────────────────────────────────────────────────────────────

def test_shape_mode_first_click_creates_a_shape_layer_that_grows_live(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _press(pen, doc, (50, 50), SHAPE)
    assert len(_pen_layers(doc)) == 1
    layer = doc.get_active_layer()
    assert layer.path_style["stroke_width"] == 4
    _draw(pen, doc, TRIANGLE[1:], SHAPE)
    assert layer.vector_mask.boundingRect() == QRectF(50, 50, 100, 100)
    _press(pen, doc, (50, 50), SHAPE)                     # closes
    assert layer.path_nodes["closed"] and len(_pen_layers(doc)) == 1
    assert not doc.work_path["nodes"]                     # the work path isn't used


def test_next_shape_with_new_op_is_a_new_layer(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, TRIANGLE + ((50, 50),), SHAPE)
    _press(pen, doc, (200, 200), SHAPE)
    assert len(_pen_layers(doc)) == 2


def test_subtract_op_cuts_a_hole_in_the_selected_shape(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, ((20, 20), (200, 20), (200, 200), (20, 200), (20, 20)), SHAPE)
    layer = doc.get_active_layer()
    sub = dict(SHAPE, shape_path_op="subtract")
    _draw(pen, doc, ((80, 80), (140, 80), (140, 140), (80, 140), (80, 80)), sub)
    assert len(_pen_layers(doc)) == 1
    comps = path_components(layer.path_nodes)
    assert len(comps) == 2 and comps[1]["op"] == "subtract"
    assert layer.vector_mask.contains(QPointF(40, 40))
    assert not layer.vector_mask.contains(QPointF(110, 110))


def test_path_mode_still_draws_the_work_path(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, TRIANGLE, {"pen_mode": "path"})
    assert len(doc.work_path["nodes"]) == 3 and not _pen_layers(doc)


def test_enter_finishes_the_open_shape(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, TRIANGLE, SHAPE)
    assert pen.finish_path(doc)
    _press(pen, doc, (250, 250), SHAPE)
    assert len(_pen_layers(doc)) == 2
    assert not pen.finish_path(Document(10, 10))           # nothing open: not handled


def test_shape_mode_ignores_an_open_work_path(qapp):
    doc = Document(300, 300)
    doc.work_path = path_to_work_path(QPainterPath(QPointF(50, 50)))
    doc.work_path["nodes"] = [{"p": QPointF(50, 50), "c1": QPointF(50, 50), "c2": QPointF(50, 50)},
                              {"p": QPointF(90, 50), "c1": QPointF(90, 50), "c2": QPointF(90, 50)}]
    pen = PenTool()
    assert pen.action_at(doc, QPointF(50, 50), SHAPE) == "new"


# ── editing with the Pen itself ──────────────────────────────────────────────

def _closed_triangle(opts=SHAPE):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, TRIANGLE + ((50, 50),), opts)
    return doc, pen, doc.get_active_layer()


def test_ctrl_drags_an_anchor(qapp):
    doc, pen, layer = _closed_triangle()
    _press(pen, doc, (150, 150), dict(SHAPE, _ctrl=True), drag=(170, 180))
    assert layer.vector_mask.boundingRect() == QRectF(50, 50, 120, 130)
    assert len(_pen_layers(doc)) == 1


def test_auto_add_and_delete(qapp):
    doc, pen, layer = _closed_triangle()
    assert pen.action_at(doc, QPointF(100, 50), SHAPE) == "add"
    _press(pen, doc, (100, 50), SHAPE)
    assert len(layer.path_nodes["nodes"]) == 4
    assert pen.action_at(doc, QPointF(100, 50), SHAPE) == "delete"
    _press(pen, doc, (100, 50), SHAPE)
    assert len(layer.path_nodes["nodes"]) == 3


def test_auto_add_delete_off_starts_a_new_shape_instead(qapp):
    doc, pen, layer = _closed_triangle()
    opts = dict(SHAPE, pen_auto_add_delete=False)
    assert pen.action_at(doc, QPointF(100, 50), opts) == "new"


def test_alt_converts_a_corner_into_a_smooth_point(qapp):
    doc, pen, layer = _closed_triangle()
    _press(pen, doc, (150, 50), dict(SHAPE, _alt=True), drag=(170, 50))
    n = [n for n in layer.path_nodes["nodes"] if n["p"] == QPointF(150, 50)][0]
    assert n["c2"] == QPointF(170, 50) and n["c1"] == QPointF(130, 50)


def test_click_on_the_last_node_drops_its_outgoing_handle(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _press(pen, doc, (50, 50), SHAPE)
    _press(pen, doc, (150, 50), SHAPE, drag=(180, 80))     # smooth node
    last = doc.get_active_layer().path_nodes["nodes"][-1]
    assert last["c2"] != last["p"]
    assert pen.action_at(doc, QPointF(150, 50), SHAPE) == "corner"
    _press(pen, doc, (150, 50), SHAPE)
    assert last["c2"] == last["p"] and last["c1"] != last["p"]


def test_close_hint_and_screen_tolerance(qapp):
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, TRIANGLE, SHAPE)
    assert pen.action_at(doc, QPointF(55, 50), dict(SHAPE, _zoom=1.0)) == "close"
    assert pen.action_at(doc, QPointF(55, 50), dict(SHAPE, _zoom=8.0)) != "close"


# ── direct selection keeps smooth points smooth ──────────────────────────────

def _smooth_path_doc():
    doc = Document(200, 200)
    doc.work_path = {"nodes": [
        {"p": QPointF(20, 100), "c1": QPointF(20, 100), "c2": QPointF(20, 100)},
        {"p": QPointF(100, 100), "c1": QPointF(70, 100), "c2": QPointF(130, 100)},
        {"p": QPointF(180, 100), "c1": QPointF(180, 100), "c2": QPointF(180, 100)}], "closed": False}
    return doc


def test_dragging_a_handle_turns_the_opposite_one():
    doc = _smooth_path_doc()
    tool = DirectSelectionTool()
    _press(tool, doc, (130, 100), {}, drag=(100, 60))           # handle straight up
    n = doc.work_path["nodes"][1]
    assert n["c1"].x() == pytest.approx(100) and n["c1"].y() == pytest.approx(130)   # 30 long, opposite


def test_alt_drag_breaks_the_handles_apart():
    doc = _smooth_path_doc()
    tool = DirectSelectionTool()
    _press(tool, doc, (130, 100), {"_alt": True}, drag=(100, 60))
    assert doc.work_path["nodes"][1]["c1"] == QPointF(70, 100)


# ── nodes vs. the mask ───────────────────────────────────────────────────────

def test_move_tool_then_pen_edit_keeps_the_move(qapp):
    doc, pen, layer = _closed_triangle()
    moved = QPainterPath(layer.vector_mask).translated(30, 0)
    layer.vector_mask = moved                                  # what Move / Free Transform do
    tool = DirectSelectionTool()
    _press(tool, doc, (180, 150), {}, drag=(200, 150))
    assert layer.vector_mask.boundingRect().left() == pytest.approx(80)
    assert layer.vector_mask.boundingRect().right() == pytest.approx(200)


def test_copy_keeps_nodes_valid_and_independent(qapp):
    doc, pen, layer = _closed_triangle()
    clone = layer.copy(deep_image=False)
    assert clone._path_nodes_valid() and clone.path_nodes is not layer.path_nodes
    clone.path_nodes["nodes"][0]["p"].setX(999)
    assert layer.path_nodes["nodes"][0]["p"].x() != 999


def test_nodes_and_ops_survive_save_and_load(qapp, tmp_path):
    from core.serialization import load_document, save_document
    doc = Document(300, 300)
    pen = PenTool()
    _draw(pen, doc, ((20, 20), (200, 20), (200, 200), (20, 200), (20, 20)), SHAPE)
    _draw(pen, doc, ((80, 80), (140, 80), (140, 140)), dict(SHAPE, shape_path_op="subtract"))
    path = str(tmp_path / "p.imfn")
    save_document(doc, path)
    loaded, _ = load_document(path)
    layer = [l for l in loaded.layers if isinstance(l, VectorLayer)][0]
    assert layer._path_nodes_valid()
    comps = path_components(layer.editable_path())
    assert [c["closed"] for c in comps] == [True, False]
    assert comps[1]["op"] == "subtract"
    assert isinstance(comps[1]["nodes"][0]["p"], QPointF)


# ── round corners ────────────────────────────────────────────────────────────

def _square(size=100):
    p = QPainterPath()
    p.addRect(QRectF(0, 0, size, size))
    return path_to_work_path(p)


def test_round_corners_on_a_square_makes_circular_fillets():
    wp = _square()
    assert round_corners(wp, 20) == 4
    path = build_bezier_path(wp)
    assert len(wp["nodes"]) == 8
    assert path.boundingRect() == QRectF(0, 0, 100, 100)
    c = 20 - 20 / math.sqrt(2)                                 # the arc at 45°
    assert not path.contains(QPointF(c - 1, c - 1))
    assert path.contains(QPointF(c + 1, c + 1))
    assert path.contains(QPointF(50, 50)) and path.contains(QPointF(1, 50))


def test_round_corners_keeps_open_ends_and_leaves_smooth_paths_alone():
    wp = {"nodes": [{"p": QPointF(x, y), "c1": QPointF(x, y), "c2": QPointF(x, y)}
                    for x, y in ((0, 0), (100, 0), (100, 100))], "closed": False}
    assert round_corners(wp, 10) == 1
    assert wp["nodes"][0]["p"] == QPointF(0, 0) and wp["nodes"][-1]["p"] == QPointF(100, 100)
    circle = QPainterPath()
    circle.addEllipse(QRectF(0, 0, 100, 100))
    assert round_corners(path_to_work_path(circle), 10) == 0


def test_round_corners_never_overlaps_on_short_edges():
    wp = _square(10)
    round_corners(wp, 500)
    pts = [n["p"] for n in wp["nodes"]]
    assert all(-1e-6 <= p.x() <= 10 + 1e-6 and -1e-6 <= p.y() <= 10 + 1e-6 for p in pts)
    assert build_bezier_path(wp).contains(QPointF(5, 5))


def test_round_corners_command_on_the_selected_shape(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(300, 300), "t")
    doc = w._document
    w._activate_tool("Pen")
    pen = w._canvas.active_tool
    opts = dict(w._canvas.tool_opts)
    _draw(pen, doc, TRIANGLE + ((50, 50),), opts)
    layer = doc.get_active_layer()
    before = clone_path(layer.path_nodes)
    w._on_opt_changed("pen_round_corners", 10)
    assert len(layer.path_nodes["nodes"]) == 6
    w._undo()
    assert len(w._document.get_active_layer().editable_path()["nodes"]) == len(before["nodes"])


def test_round_corners_command_without_corners_says_so(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    w._activate_tool("Pen")
    undo_before = len(w._history._undo_stack)
    w._on_opt_changed("pen_round_corners", 10)
    assert len(w._history._undo_stack) == undo_before
    assert w._status.currentMessage()


# ── options bar ──────────────────────────────────────────────────────────────

def test_pen_options_show_style_in_shape_mode_and_buttons_in_path_mode(main_window):
    w = main_window
    w._add_tab(Document(50, 50), "t")
    w._activate_tool("Pen")
    page = w._opts_bar.page_for("Pen")
    page.update_from_opts({"pen_mode": "shape"})
    assert page._btn_sel.isHidden() and not page._style.stroke_cb.isHidden()
    page.update_from_opts({"pen_mode": "path"})
    assert not page._btn_sel.isHidden() and page._style.stroke_cb.isHidden()


def test_style_options_live_edit_the_selected_pen_shape(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(300, 300), "t")
    doc = w._document
    w._activate_tool("Pen")
    _draw(w._canvas.active_tool, doc, TRIANGLE + ((50, 50),), dict(w._canvas.tool_opts))
    layer = doc.get_active_layer()
    w._on_opt_changed("shape_stroke_width", 9)
    assert layer.path_style["stroke_width"] == 9


def test_pen_cursor_badges(qapp):
    doc, pen, layer = _closed_triangle()
    pen.on_hover(QPoint(100, 50), doc, None, None, SHAPE)
    assert not pen.cursor().pixmap().isNull()
    pen.on_hover(QPoint(100, 50), doc, None, None, dict(SHAPE, _ctrl=True))
    assert pen.cursor().shape().name == "ArrowCursor"
