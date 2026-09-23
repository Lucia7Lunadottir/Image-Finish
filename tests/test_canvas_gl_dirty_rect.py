"""Regression test for a real bug she hit live: after a single brush
stroke, Ctrl+Z left visible leftovers of the stroke on screen until a
click forced a redraw.

Root cause: BrushTool.get_dirty_rect() deliberately survives past its own
on_release (so CanvasWidget.mouseReleaseEvent's eager recompute can blit
just the stroke's rect into the cache instead of a full recompute). But
undo/redo goes through EditActionsMixin._undo -> _canvas_refresh(), which
invalidates Document's composite cache directly, without going through the
tool at all. The next paint's CanvasWidget._recompute_composite() then read
the tool's still-stale dirty rect, passed it straight to
`_last_composite_dirty_rect`, and CanvasWidget's paint routine forwarded
that to GLCompositor.draw(dirty_rect=...) — telling the GPU layer "only
this small rect changed" while Document.get_composite() had actually done
a full recompute (the doc-level cache was already None). GLCompositor
would then glTexSubImage2D only that stale sub-rect, leaving whatever the
GPU texture held outside it un-refreshed — the leftover shapes she saw.

ui/gl_compositor.py's own comment already documented the intended
invariant ("a resize, a channel-view swap, undo/redo... all go through the
full-image path instead") — this test pins that CanvasWidget actually
upholds it.
"""
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor

from core.document import Document
from ui.canvas_widget import CanvasWidget
from tools.brush_tool import BrushTool

OPTS = {"brush_size": 20, "brush_hardness": 1.0, "brush_opacity": 1.0,
        "brush_mask": "round", "brush_blend_mode": "SourceOver"}


def _make_canvas_with_finished_stroke(qapp):
    doc = Document(100, 80)
    doc.get_composite()  # warm the cache, like the first real paint would

    canvas = CanvasWidget()
    canvas.set_document(doc)
    canvas.active_tool = BrushTool()
    canvas.tool_opts = dict(OPTS)
    canvas.fg_color = QColor(0, 0, 0)
    canvas.bg_color = QColor(255, 255, 255)

    tool = canvas.active_tool
    tool.on_press(QPoint(30, 30), doc, canvas.fg_color, canvas.bg_color, canvas.tool_opts)
    tool.on_move(QPoint(50, 40), doc, canvas.fg_color, canvas.bg_color, canvas.tool_opts)
    tool.on_release(QPoint(50, 40), doc, canvas.fg_color, canvas.bg_color, canvas.tool_opts)
    canvas._recompute_composite()  # mirrors mouseReleaseEvent's eager recompute
    return doc, canvas


def test_stroke_dirty_rect_is_partial_right_after_release(qapp):
    """Sanity check on the optimization itself: a normal just-finished
    stroke DOES still get the cheap partial-blit path."""
    doc, canvas = _make_canvas_with_finished_stroke(qapp)
    assert canvas._last_composite_dirty_rect is not None
    assert canvas.active_tool.get_dirty_rect() == canvas._last_composite_dirty_rect


def test_external_invalidate_without_new_press_forces_full_gl_reupload(qapp):
    """The actual bug: something other than the tool (undo, in this case)
    invalidates the document's composite cache while the tool's own dirty
    rect is still sitting there from the last stroke. The next recompute
    must report `None` (full re-upload), not the stale rect, even though
    the tool never got a fresh on_press to reset it."""
    doc, canvas = _make_canvas_with_finished_stroke(qapp)
    assert canvas.active_tool.get_dirty_rect() is not None  # still stale, by design

    # Simulate EditActionsMixin._undo() -> _canvas_refresh()'s invalidation,
    # without a new on_press in between.
    doc.invalidate_composite()
    canvas._cache_dirty = True
    canvas._recompute_composite()

    assert canvas._last_composite_dirty_rect is None
