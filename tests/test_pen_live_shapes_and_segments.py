"""Pen tools on live Shapes-tool shapes, segment dragging, and tool overlays
that keep their screen size at any zoom.

  * Editing the points of a rect / ellipse / line drawn by the Shapes tool
    turns it into a regular path layer, as in Photoshop; moving it whole
    with Path Selection keeps it live.
  * Direct Selection (and the Pen with Ctrl) drags segments, not only
    anchors and handles.
  * Overlays get one screen pixel as `pw`, hit distances are screen px."""
import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter

from core.document import Document
from core.layer import VectorLayer
from core.path_model import bezier_point, path_offset
from tools.pen_tool import (AddAnchorPointTool, DirectSelectionTool, PathSelectionTool, PenTool,
                            _is_smooth)

FG, BG = QColor(0, 0, 0), QColor(255, 255, 255)


def _node(x, y, c1=None, c2=None):
    p = QPointF(x, y)
    return {"p": p, "c1": QPointF(*c1) if c1 else QPointF(p), "c2": QPointF(*c2) if c2 else QPointF(p)}


def _live(doc, shape="rect", rect=(40, 40, 60, 40), **extra):
    layer = doc.add_layer(name="S", layer_cls=VectorLayer)
    x, y, w, h = rect
    layer.shape_data = {"shape": shape, "rect": rect, "start": (x, y), "end": (x + w, y + h),
                        "fill": True, "fill_color": "#ffff0000", "stroke_color": "#ff0000ff",
                        "size": 4, "sides": 6, "angle": 0, **extra}
    layer.rebake_thumbnail()
    return layer


def _drag(tool, doc, a, b, opts=None):
    opts = opts or {}
    tool.on_press(QPoint(*a), doc, FG, BG, opts)
    tool.on_move(QPoint(*b), doc, FG, BG, opts)
    tool.on_release(QPoint(*b), doc, FG, BG, opts)


@pytest.fixture()
def doc(qapp):
    return Document(200, 200)


# ── live shapes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("shape, count, closed", [
    ("rect", 4, True), ("ellipse", 4, True), ("triangle", 3, True), ("line", 2, False)])
def test_live_shape_outline_as_nodes(doc, shape, count, closed):
    layer = _live(doc, shape)
    wp = layer.live_shape_nodes()
    assert len(wp["nodes"]) == count and wp["closed"] is closed and not wp["subpaths"]


def test_live_shape_nodes_follow_the_layer_offset(doc):
    layer = _live(doc)
    layer.offset = QPoint(10, 5)
    assert layer.live_shape_nodes()["nodes"][0]["p"] == QPointF(50, 45)


def test_direct_selection_turns_a_live_rect_into_a_path(doc):
    layer = _live(doc)
    _drag(DirectSelectionTool(), doc, (40, 40), (20, 30))
    assert layer.shape_data is None and layer._is_path_layer()
    assert layer.vector_mask.boundingRect() == QRectF(20, 30, 80, 50)
    assert layer.path_style["fill_color"] == QColor(255, 0, 0)
    assert layer.path_style["stroke_color"] == QColor(0, 0, 255)
    assert layer.path_style["stroke_width"] == 4
    assert layer.image.pixelColor(70, 60) == QColor(255, 0, 0)       # thumbnail rebaked


def test_conversion_happens_on_the_first_move_of_the_drag(doc):
    layer = _live(doc)
    tool = DirectSelectionTool()
    tool.on_press(QPoint(100, 80), doc, FG, BG, {})
    assert layer.is_live_shape()                     # just grabbing a point changes nothing
    tool.on_move(QPoint(120, 90), doc, FG, BG, {})
    assert not layer.is_live_shape()
    assert layer.vector_mask.boundingRect().bottomRight() == QPointF(120, 90)
    tool.on_move(QPoint(130, 95), doc, FG, BG, {})   # the drag continues on the path layer
    assert layer.vector_mask.boundingRect().bottomRight() == QPointF(130, 95)


def test_path_selection_moves_a_live_shape_and_keeps_it_live(doc):
    layer = _live(doc, "ellipse")
    tool = PathSelectionTool()
    tool.on_press(QPoint(70, 60), doc, FG, BG, {})
    tool.on_move(QPoint(80, 65), doc, FG, BG, {})
    assert tuple(layer.shape_data["rect"]) == (50, 45, 60, 40)
    tool.on_move(QPoint(90, 70), doc, FG, BG, {})       # from the original, not cumulative
    tool.on_release(QPoint(90, 70), doc, FG, BG, {})
    assert layer.is_live_shape() and layer.shape_data["shape"] == "ellipse"
    assert tuple(layer.shape_data["rect"]) == (60, 50, 60, 40)


def test_click_without_editing_keeps_the_shape_live(doc):
    layer = _live(doc)
    _drag(DirectSelectionTool(), doc, (150, 150), (160, 160))   # nowhere near it
    assert layer.is_live_shape()


def test_add_anchor_on_a_live_rect(doc):
    layer = _live(doc)
    AddAnchorPointTool().on_press(QPoint(70, 40), doc, FG, BG, {})
    assert not layer.is_live_shape()
    assert len(layer.path_nodes["nodes"]) == 5


def test_pen_ctrl_edits_a_live_ellipse(doc):
    layer = _live(doc, "ellipse")
    top = layer.live_shape_nodes()["nodes"]
    p = min(top, key=lambda n: n["p"].y())["p"]
    _drag(PenTool(), doc, (round(p.x()), round(p.y())), (round(p.x()), 10),
          {"_ctrl": True, "pen_mode": "shape"})
    assert not layer.is_live_shape()
    assert layer.vector_mask.boundingRect().top() == pytest.approx(10, abs=0.5)


def test_pen_click_beside_a_live_shape_starts_a_new_one(doc):
    layer = _live(doc)
    opts = {"pen_mode": "shape", "pen_auto_add_delete": True}
    PenTool().on_press(QPoint(150, 150), doc, FG, BG, opts)
    assert layer.is_live_shape()
    assert doc.get_active_layer() is not layer


def test_pen_auto_delete_on_a_live_rect_corner(doc):
    layer = _live(doc)
    opts = {"pen_mode": "shape", "pen_auto_add_delete": True}
    PenTool().on_press(QPoint(100, 40), doc, FG, BG, opts)
    assert doc.get_active_layer() is layer and len(layer.path_nodes["nodes"]) == 3


def test_enter_does_not_convert_a_live_line(doc):
    layer = _live(doc, "line")
    tool = PenTool()
    tool._opts = {"pen_mode": "shape"}
    assert tool.finish_path(doc) is False
    assert layer.is_live_shape()


def test_converted_line_stays_an_open_stroke(doc):
    layer = _live(doc, "line", rect=(20, 100, 160, 0), stroke_cap="butt")
    _drag(DirectSelectionTool(), doc, (180, 100), (180, 40))
    assert layer.path_style["open_stroke"] and layer.path_style["fill_color"] is None
    img = doc.get_composite()
    # No closing segment / fill between the ends: the area above the
    # middle of the (now slanted) line stays empty.
    assert img.pixelColor(100, 60).alpha() == 0 or img.pixelColor(100, 60) == QColor(255, 255, 255)
    assert layer.vector_mask.boundingRect().top() == pytest.approx(40)


def test_converted_shape_survives_clone(doc):
    layer = _live(doc)
    _drag(DirectSelectionTool(), doc, (40, 40), (20, 30))
    clone = layer.copy()
    assert clone._path_nodes_valid() and len(clone.path_nodes["nodes"]) == 4


def test_path_offset():
    a = {"nodes": [_node(0, 0), _node(10, 0), _node(10, 10)], "closed": True}
    moved = {"nodes": [_node(5, 3), _node(15, 3), _node(15, 13)], "closed": True}
    edited = {"nodes": [_node(5, 3), _node(15, 3), _node(16, 13)], "closed": True}
    assert path_offset(a, a) == (0, 0)
    assert path_offset(a, moved) == (5, 3)
    assert path_offset(a, edited) is None


# ── segment drag ─────────────────────────────────────────────────────────────

def test_dragging_a_straight_segment_moves_both_anchors(qapp):
    doc = Document(200, 200)
    doc.work_path = {"nodes": [_node(20, 20), _node(100, 20), _node(100, 100)], "closed": False}
    _drag(DirectSelectionTool(), doc, (60, 20), (60, 35))
    n = doc.work_path["nodes"]
    assert (n[0]["p"], n[1]["p"], n[2]["p"]) == (QPointF(20, 35), QPointF(100, 35), QPointF(100, 100))


@pytest.mark.parametrize("modifier", [{}, {"_ctrl": True}])
def test_dragging_a_curve_segment_makes_it_pass_through_the_cursor(qapp, modifier):
    doc = Document(300, 300)
    doc.work_path = {"nodes": [_node(20, 100, c2=(60, 60)), _node(180, 100, c1=(140, 60))],
                     "closed": False}
    n0, n1 = doc.work_path["nodes"]
    grab = bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], 0.3)
    tool = DirectSelectionTool() if not modifier else PenTool()
    a = (round(grab.x()), round(grab.y()))
    tool.on_press(QPoint(*a), doc, FG, BG, modifier)
    t = (tool._delegate if modifier else tool)._seg_t
    target = QPointF(a[0] + 10, a[1] - 30)
    tool.on_move(target.toPoint(), doc, FG, BG, modifier)
    n0, n1 = doc.work_path["nodes"]
    assert n0["p"] == QPointF(20, 100) and n1["p"] == QPointF(180, 100)   # anchors stay
    q = bezier_point(n0["p"], n0["c2"], n1["c1"], n1["p"], t)
    expected = QPointF(grab.x() + (target.x() - a[0]), grab.y() + (target.y() - a[1]))
    assert math.hypot(q.x() - expected.x(), q.y() - expected.y()) < 1e-6


def test_segment_drag_keeps_smooth_ends_smooth(qapp):
    doc = Document(300, 300)
    doc.work_path = {"nodes": [_node(20, 100), _node(100, 100, c1=(70, 70), c2=(130, 130)),
                               _node(180, 100)], "closed": False}
    nodes = doc.work_path["nodes"]
    grab = bezier_point(nodes[0]["p"], nodes[0]["c2"], nodes[1]["c1"], nodes[1]["p"], 0.6)
    _drag(DirectSelectionTool(), doc, (round(grab.x()), round(grab.y())),
          (round(grab.x()) - 10, round(grab.y()) - 25))
    assert _is_smooth(nodes[1])


def test_anchor_and_handle_hits_win_over_the_segment(qapp):
    doc = Document(200, 200)
    doc.work_path = {"nodes": [_node(20, 20), _node(100, 20)], "closed": False}
    tool = DirectSelectionTool()
    tool.on_press(QPoint(22, 20), doc, FG, BG, {})
    assert tool.drag_target == (0, "p")


# ── overlays and hit distances at any zoom ───────────────────────────────────

def test_canvas_gives_overlays_one_screen_pixel(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(100, 100), "t")
    canvas = w._canvas
    seen = []

    class _Probe:
        name = "Probe"
        pointer_inside = True

        def draw_overlays(self, painter, pw, doc):
            seen.append(pw)

    canvas.zoom = 8.0
    canvas._active_tool = _Probe()
    img = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    canvas._paint_tool_overlays(p)
    p.end()
    assert seen == [1 / 8]


def _line_thickness_on_screen(tool, zoom):
    img = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.scale(zoom, zoom)
    tool.draw_overlays(p, 1.0 / zoom, Document(100, 100))
    p.end()
    # a column through the rect's top edge (y = 10 in the document)
    return sum(1 for y in range(400) if img.pixelColor(int(30 * zoom), y).alpha() > 200
               and y < 20 * zoom)


@pytest.mark.parametrize("tool_name", ["frame", "slice"])
def test_rubber_band_lines_keep_their_screen_width(qapp, tool_name):
    if tool_name == "frame":
        from tools.frame_tool import FrameTool as Tool
    else:
        from tools.slice_tool import SliceTool as Tool
    tool = Tool()
    tool._start, tool._end = QPoint(10, 10), QPoint(40, 40)
    if tool_name == "frame":
        tool._shape = "rect"
    assert _line_thickness_on_screen(tool, 8.0) <= _line_thickness_on_screen(tool, 1.0) + 1


@pytest.mark.parametrize("zoom, grabs", [(1.0, True), (8.0, False), (0.25, True)])
def test_perspective_crop_corner_hit_is_in_screen_pixels(qapp, zoom, grabs):
    from tools.perspective_crop_tool import PerspectiveCropTool
    tool = PerspectiveCropTool()
    tool.points = [QPoint(10, 10), QPoint(100, 10), QPoint(100, 100), QPoint(10, 100)]
    tool.pending_quad = object()
    # 8 document px away: 8 screen px at 100 %, 64 at 800 %, 2 at 25 %
    tool.on_press(QPoint(18, 10), Document(200, 200), FG, BG, {"_zoom": zoom})
    assert (tool._dragged_point_index == 0) is grabs


@pytest.mark.parametrize("zoom, removes", [(1.0, True), (4.0, False)])
def test_color_sampler_alt_removal_is_in_screen_pixels(qapp, zoom, removes):
    from tools.measure_tools import ColorSamplerTool
    tool = ColorSamplerTool()
    tool.markers = [QPoint(50, 50)]
    tool.on_press(QPoint(56, 50), Document(100, 100), FG, BG, {"_alt": True, "_zoom": zoom})
    assert (not tool.markers) is removes


# ── the "turn into a path?" question ─────────────────────────────────────────

@pytest.mark.parametrize("tool, pos, opts, asks", [
    (DirectSelectionTool, (40, 40), {}, True),          # an anchor
    (DirectSelectionTool, (70, 40), {}, True),          # a segment
    (DirectSelectionTool, (150, 150), {}, False),       # nowhere
    (PathSelectionTool, (70, 60), {}, False),           # moving it whole keeps it live
    (AddAnchorPointTool, (70, 40), {}, True),
    (AddAnchorPointTool, (70, 60), {}, False),
    (PenTool, (40, 40), {"pen_mode": "shape", "pen_auto_add_delete": True}, True),
    (PenTool, (150, 150), {"pen_mode": "shape"}, False),                         # a new shape
    (PenTool, (150, 150), {"pen_mode": "shape", "shape_path_op": "unite"}, True),
    (PenTool, (40, 40), {"pen_mode": "shape", "_ctrl": True}, True),
])
def test_which_presses_would_turn_a_live_shape_into_a_path(doc, tool, pos, opts, asks):
    layer = _live(doc)
    assert (tool().live_shape_edit_at(QPoint(*pos), doc, opts) is layer) is asks
    assert layer.is_live_shape()                        # asking changes nothing


def test_pen_near_a_live_line_end_does_not_continue_it(doc):
    layer = _live(doc, "line", rect=(20, 100, 160, 0))
    tool = PenTool()
    assert tool.live_shape_edit_at(QPoint(180, 100), doc, {"pen_mode": "shape",
                                                           "pen_auto_add_delete": False}) is None


def _mouse(kind, pos):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent
    button = Qt.MouseButton.LeftButton
    buttons = button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    return QMouseEvent(kind, QPointF(*pos), QPointF(*pos), button, buttons,
                       Qt.KeyboardModifier.NoModifier)


@pytest.fixture()
def canvas_with_shape(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(200, 200), "t")
    layer = _live(w._document)
    c = w._canvas
    c.resize(400, 400)
    c.zoom, c._pan = 1.0, QPointF(0, 0)
    w._activate_tool("AddAnchor")
    return w, c, layer


def _click(c, pos):
    from PyQt6.QtCore import QEvent
    c.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos))
    c.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos))


def test_refusing_the_question_leaves_the_shape_alone(canvas_with_shape, monkeypatch):
    import ui.actions.live_shape_prompt as prompt
    w, c, layer = canvas_with_shape
    asked = []
    monkeypatch.setattr(prompt, "confirm_live_shape_conversion",
                        lambda parent, l: asked.append(l) or False)
    _click(c, (70, 40))
    assert asked == [layer] and layer.is_live_shape()


def test_accepting_converts_and_one_undo_brings_the_shape_back(canvas_with_shape, monkeypatch):
    import ui.actions.live_shape_prompt as prompt
    w, c, layer = canvas_with_shape
    monkeypatch.setattr(prompt, "confirm_live_shape_conversion", lambda parent, l: True)
    _click(c, (70, 40))
    edited = w._document.get_active_layer()
    assert not edited.is_live_shape() and len(edited.path_nodes["nodes"]) == 5
    w._undo()
    assert w._document.get_active_layer().is_live_shape()


def test_dont_ask_again_is_remembered(qapp, monkeypatch):
    import ui.actions.live_shape_prompt as prompt
    from PyQt6.QtWidgets import QMessageBox
    store = {}

    class _Settings:
        def value(self, key, default=None, type=None):
            return store.get(key, default)

        def setValue(self, key, value):
            store[key] = value

    monkeypatch.setattr(prompt, "_settings", lambda: _Settings())
    shown = []

    def fake_exec(box):
        shown.append(box.text())
        box.checkBox().setChecked(True)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    layer = VectorLayer("Прямоугольник 1", 10, 10)
    assert prompt.confirm_live_shape_conversion(None, layer)
    assert prompt.confirm_live_shape_conversion(None, layer)
    assert len(shown) == 1 and "Прямоугольник 1" in shown[0]
