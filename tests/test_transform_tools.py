"""Move / Warp / Puppet Warp / Perspective Warp on one TransformTool base
(tools/transform_base.py), and the window committing them through it
instead of reaching into each tool's private fields."""
import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from tools.move_tool import MoveTool
from tools.transform_base import TransformTool

WARPS = ["Warp", "PuppetWarp", "PerspectiveWarp"]
OPTS = {"_zoom": 1.0}


def _paint(layer, rect):
    layer.image.fill(0)
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            layer.image.setPixelColor(x, y, QColor(200, 0, 0))


def _start(w, name, at=QPoint(15, 15)):
    w._activate_tool(name)
    tool = w._tools[name]
    tool.on_press(at, w._document, QColor(), QColor(), OPTS)
    tool.on_release(at, w._document, QColor(), QColor(), OPTS)
    assert tool.is_transforming
    return tool


@pytest.mark.parametrize("name", ["Move"] + WARPS)
def test_switching_tool_commits_the_transform(main_window, mocked_dialogs, name):
    """Puppet/Perspective Warp were left open on a tool switch: the layer
    stayed swapped for its 1x1 transparent stand-in (content gone)."""
    w = main_window
    w._add_tab(Document(100, 80), "t")
    _paint(w._document.layers[0], QRect(10, 10, 20, 20))
    tool = _start(w, name)
    w._activate_tool("Brush")
    assert not tool.is_transforming
    assert w._document.layers[0].image.width() >= 20
    assert w._history.undo_description() == _title(name)


def _title(name):
    from ui.tool_catalog import tool_title
    return tool_title(name)


@pytest.mark.parametrize("name", WARPS)
def test_undo_after_warp_restores_layer(main_window, mocked_dialogs, name):
    w = main_window
    w._add_tab(Document(100, 80), "t")
    _paint(w._document.layers[0], QRect(10, 10, 20, 20))
    _start(w, name)
    w._commit_transforms()
    assert w._history.undo_description() == _title(name)
    w._undo()
    layer = w._document.layers[0]
    assert layer.image.size().width() == 100
    assert layer.image.pixelColor(15, 15).red() == 200


@pytest.mark.parametrize("name", ["Move"] + WARPS)
def test_escape_cancels_any_transform(main_window, mocked_dialogs, name):
    w = main_window
    w._add_tab(Document(100, 80), "t")
    _paint(w._document.layers[0], QRect(10, 10, 20, 20))
    tool = _start(w, name)
    assert w._cancel_transform()
    assert not tool.is_transforming
    assert w._document.layers[0].image.width() == 100
    assert not w._cancel_transform()          # nothing open any more


def test_commit_goes_to_the_documents_own_history(main_window, mocked_dialogs):
    """A transform started in one tab, committed while another tab is
    current, lands in its own document's history."""
    w = main_window
    w._add_tab(Document(100, 80), "a")
    first = w._doc_tabs.currentWidget()
    _paint(first.document.layers[0], QRect(10, 10, 20, 20))
    tool = _start(w, "PuppetWarp")
    w._add_tab(Document(50, 50), "b")
    second = w._doc_tabs.currentWidget()
    w._commit_transforms()
    assert not tool.is_transforming
    assert first.history.undo_description() == _title("PuppetWarp")
    assert not second.history.can_undo()


def test_move_floating_selection_on_offset_layer_stays_in_place(qapp):
    """The cut piece was pasted back at its document position used as a
    layer-local one — shifted by the layer's offset."""
    doc = Document(100, 80)
    layer = doc.layers[0]
    _paint(layer, QRect(10, 10, 20, 20))
    layer.offset = QPoint(30, 20)                 # pixels at doc (40..59, 30..49)
    sel = QPainterPath()
    sel.addRect(40, 30, 20, 20)
    doc.selection = sel
    tool = MoveTool()
    opts = {"_zoom": 1.0, "_ctrl": True}
    tool.on_press(QPoint(45, 35), doc, None, None, opts)
    tool.on_move(QPoint(46, 35), doc, None, None, opts)
    tool.on_release(QPoint(46, 35), doc, None, None, opts)
    tool.apply_transform(doc)
    assert layer.image.pixelColor(11, 10).alpha() == 255      # moved 1 px right
    assert layer.image.pixelColor(41, 30).alpha() == 0


def test_original_state_is_restored_after_snapshot(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    _paint(layer, QRect(10, 10, 20, 20))
    tool = MoveTool()
    tool.on_press(QPoint(15, 15), doc, None, None, OPTS)
    live = layer.image
    with tool.original_state(doc):
        assert layer.image.size().width() == 100
        assert layer.image.pixelColor(15, 15).red() == 200
    assert layer.image is live
    tool.cancel_transform(doc)


def test_failed_start_does_not_leave_layer_hidden(qapp):
    """A selection outside the layer aborts the start — Move used to leave
    the layer's live-edit-hidden flag on (invisible shape/text layer)."""
    doc = Document(100, 80)
    layer = doc.layers[0]
    layer.offset = QPoint(0, 0)
    sel = QPainterPath()
    sel.addRect(500, 500, 10, 10)
    doc.selection = sel
    tool = MoveTool()
    tool.on_press(QPoint(505, 505), doc, None, None, OPTS)
    assert not tool.is_transforming
    assert not layer._live_edit_hidden


def test_every_transform_tool_is_a_transform_tool(main_window):
    names = {n for n, t in main_window._tools.items() if isinstance(t, TransformTool)}
    assert names == {"Move", *WARPS}


def test_catalog_drives_toolbar_options_and_instances(main_window):
    from ui.tool_catalog import TOOLS
    w = main_window
    assert set(w._tools) == set(TOOLS)
    for name, tool in w._tools.items():
        assert tool.name == name
        assert w._opts_bar.page_for(name) is not None
        assert name in w._toolbar._buttons or name in w._toolbar._tool_to_group
    # One widget per OptionsPage: all brush-like tools share the Brush page.
    assert w._opts_bar.page_for("Pencil") is w._opts_bar.page_for("Brush")
    assert w._opts_bar.page_for("Warp") is not w._opts_bar.page_for("Move")
