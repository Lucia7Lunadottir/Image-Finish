"""The Text tool used to always block on a modal QDialog. It now shows a
non-blocking in-place editor (TextEditOverlay) and commits when told to —
these tests drive that commit path directly, the way the overlay's own
focus-out / Escape / Ctrl+Enter handlers do internally.

Font/size/color come live from `canvas.tool_opts` (the same dict the Text
tool's options-bar writes to), not a snapshot passed at open time.
"""

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor

from core.document import Document


def test_new_text_commit_creates_text_layer(main_window):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    n_layers_before = len(doc.layers)

    w._canvas.tool_opts.update(font_family="Sans Serif", font_size=24, text_color=QColor(0, 0, 0))
    w._canvas.begin_text_edit(doc, None, "", QPoint(20, 30), vertical=False)
    assert w._canvas._text_overlay.is_active()

    w._canvas._text_overlay.setPlainText("Hello")
    w._canvas._text_overlay.commit()

    assert len(doc.layers) == n_layers_before + 1
    new_layer = doc.layers[-1]
    assert new_layer.layer_type == "text"
    assert new_layer.text_data["text"] == "Hello"
    assert new_layer.text_data["x"] == 20 and new_layer.text_data["y"] == 30
    assert w._history.can_undo()


def test_committing_empty_new_text_creates_nothing(main_window):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    n_layers_before = len(doc.layers)
    can_undo_before = w._history.can_undo()

    w._canvas.tool_opts.update(font_family="Sans Serif", font_size=24)
    w._canvas.begin_text_edit(doc, None, "", QPoint(5, 5), vertical=False)
    w._canvas._text_overlay.commit()  # never typed anything

    assert len(doc.layers) == n_layers_before
    assert w._history.can_undo() == can_undo_before


def test_reedit_existing_text_layer_updates_in_place(main_window):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document

    w._canvas.tool_opts.update(font_family="Sans Serif", font_size=24)
    w._canvas.begin_text_edit(doc, None, "", QPoint(10, 10), vertical=False)
    w._canvas._text_overlay.setPlainText("First")
    w._canvas._text_overlay.commit()

    layer = doc.layers[-1]
    n_layers = len(doc.layers)

    w._canvas.begin_text_edit(doc, layer, layer.text_data["text"],
                              QPoint(layer.text_data["x"], layer.text_data["y"]), vertical=False)
    w._canvas._text_overlay.setPlainText("Second")
    w._canvas._text_overlay.commit()

    assert len(doc.layers) == n_layers  # no extra layer created
    assert doc.layers[-1].text_data["text"] == "Second"


def test_clearing_text_on_reedit_removes_the_layer(main_window):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document

    w._canvas.tool_opts.update(font_family="Sans Serif", font_size=24)
    w._canvas.begin_text_edit(doc, None, "", QPoint(10, 10), vertical=False)
    w._canvas._text_overlay.setPlainText("Temp")
    w._canvas._text_overlay.commit()

    layer = doc.layers[-1]
    n_layers = len(doc.layers)

    w._canvas.begin_text_edit(doc, layer, "Temp",
                              QPoint(layer.text_data["x"], layer.text_data["y"]), vertical=False)
    w._canvas._text_overlay.setPlainText("")
    w._canvas._text_overlay.commit()

    assert len(doc.layers) == n_layers - 1
    assert layer not in doc.layers


def test_overlay_geometry_hugs_the_rendered_text_bounding_box(main_window):
    """Regression: the editor used to be a fixed-size floating panel you
    could visually mistake for a resizable box. It must now track the
    exact metrics `_render_text` will bake, growing/shrinking with the
    text instead of staying a fixed size."""
    w = main_window
    w._add_tab(Document(400, 300), "t")
    doc = w._document

    w._canvas.tool_opts.update(font_family="DejaVu Sans", font_size=20, text_color=QColor(0, 0, 0))
    w._canvas.begin_text_edit(doc, None, "", QPoint(30, 30), vertical=False)

    w._canvas._text_overlay.setPlainText("Hi")
    short_width = w._canvas._text_overlay.width()

    w._canvas._text_overlay.setPlainText("Hi there, much longer line")
    long_width = w._canvas._text_overlay.width()

    assert long_width > short_width
    w._canvas._text_overlay.cancel()
