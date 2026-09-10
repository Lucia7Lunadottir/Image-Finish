"""Photoshop-style 'hold Alt = temporary eyedropper' while a paint tool is active."""

from PyQt6.QtCore import Qt, QEvent, QPoint
from PyQt6.QtGui import QColor, QKeyEvent

from core.document import Document


def _alt_press(canvas):
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier))


def _alt_release(canvas):
    canvas.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier))


def test_alt_swaps_brush_to_eyedropper_and_back(main_window):
    w = main_window
    w._add_tab(Document(60, 50), "t")
    w._activate_tool("Brush")
    canvas = w._canvas
    brush = canvas.active_tool
    assert brush.name == "Brush"

    _alt_press(canvas)
    assert canvas.active_tool.name == "Eyedropper"
    # The system cursor must stay exactly as it was for the brush (blank,
    # replaced by the painted circle guide) rather than switching to a real
    # CrossCursor and back — some window managers only redraw the cursor
    # icon on the next mouse-originated event, so a shape change driven
    # purely by a key event can visually stick around after Alt is released.
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas._show_brush_cursor is True

    _alt_release(canvas)
    assert canvas.active_tool is brush
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas._show_brush_cursor is True


def test_alt_click_while_held_updates_foreground_color(main_window):
    w = main_window
    w._add_tab(Document(60, 50), "t")
    w._activate_tool("Brush")
    canvas = w._canvas
    layer = w._document.get_active_layer()
    marker = QColor(90, 200, 40)
    layer.image.fill(marker)
    w._document.invalidate_composite()

    _alt_press(canvas)
    canvas.active_tool.on_press(QPoint(10, 10), w._document, canvas.fg_color, canvas.bg_color, canvas.tool_opts)
    _alt_release(canvas)

    assert canvas.fg_color.red() == marker.red()
    assert canvas.fg_color.green() == marker.green()
    assert canvas.fg_color.blue() == marker.blue()


def test_alt_does_not_hijack_clone_stamp_source_picking(main_window):
    """CloneStamp already uses Alt to set its clone source point — the
    temporary eyedropper must not steal Alt away from it."""
    w = main_window
    w._add_tab(Document(60, 50), "t")
    w._activate_tool("CloneStamp")
    canvas = w._canvas
    clone = canvas.active_tool
    assert clone.name == "CloneStamp"

    _alt_press(canvas)
    assert canvas.active_tool is clone

    _alt_release(canvas)
    assert canvas.active_tool is clone


def test_fresh_canvas_widget_starts_with_blank_cursor(qapp):
    """Brush is always the first tool applied to any newly opened document,
    so a brand-new CanvasWidget should already look like it, cursor-wise,
    from construction — before _add_tab ever gets a chance to react."""
    from ui.canvas_widget import CanvasWidget

    canvas = CanvasWidget()
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas._show_brush_cursor is True


def test_opening_a_tab_sets_the_canvas_cursor_immediately(main_window):
    """Regression: the Welcome screen's recent-file thumbnails set
    PointingHandCursor on themselves. Swapping them out for the opened
    document's canvas at the same screen position doesn't happen via an
    actual mouse move, so nothing tells Qt to re-poll which widget is under
    the pointer — the stale hand cursor kept showing until the next real
    mouse move. _add_tab must set the canvas's own cursor immediately."""
    w = main_window
    w._add_tab(Document(60, 50), "t")
    canvas = w._canvas
    assert canvas.active_tool.name == "Brush"
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas._show_brush_cursor is True


def test_opening_a_tab_resync_cursor_survives_event_loop(main_window):
    """The cursor fix also posts a synthetic mouse-move on the next event
    loop tick (deferred via QTimer.singleShot) to force Qt to re-run its own
    hit-testing for the widget now under the pointer. Make sure that actually
    firing doesn't raise and leaves the cursor in the correct state."""
    from PyQt6.QtWidgets import QApplication

    w = main_window
    w._add_tab(Document(60, 50), "t")
    canvas = w._canvas

    QApplication.processEvents()
    QApplication.processEvents()

    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas._show_brush_cursor is True


def test_alt_does_not_swap_mid_stroke(main_window):
    w = main_window
    w._add_tab(Document(60, 50), "t")
    w._activate_tool("Brush")
    canvas = w._canvas
    brush = canvas.active_tool

    canvas._stroke_in_progress = True
    _alt_press(canvas)
    assert canvas.active_tool is brush
    canvas._stroke_in_progress = False
