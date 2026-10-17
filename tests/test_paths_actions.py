"""MainWindow._path_* handlers (ui/actions/panel_actions.py), generalized
to act on whichever Paths panel row is selected — the ephemeral work path
or a named entry in doc.saved_paths — instead of always assuming "work".
"""
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor

from core.document import Document


def _wp(*points, closed=False):
    return {"nodes": [{"p": QPointF(*pt), "c1": QPointF(*pt), "c2": QPointF(*pt)}
                      for pt in points],
            "closed": closed}


def _select_row(w, row):
    w._paths_panel.refresh(w._canvas)
    w._paths_panel._list.setCurrentRow(row)


def test_new_path_promotes_work_path_and_clears_it(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    doc.work_path = _wp((1, 1), (2, 2), closed=True)

    w._path_new()

    assert doc.work_path == {"nodes": [], "closed": False}
    assert len(doc.saved_paths) == 1
    saved = doc.saved_paths[0]
    assert saved["name"]  # auto-named, non-empty
    assert saved["closed"] is True
    assert len(saved["nodes"]) == 2
    assert saved["nodes"][0]["p"] == QPointF(1, 1)


def test_new_path_does_nothing_when_work_path_empty(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document

    w._path_new()

    assert doc.saved_paths == []


def test_new_path_auto_names_sequentially(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document

    doc.work_path = _wp((0, 0))
    w._path_new()
    doc.work_path = _wp((1, 1))
    w._path_new()

    assert len(doc.saved_paths) == 2
    assert doc.saved_paths[0]["name"] != doc.saved_paths[1]["name"]


def test_path_rename_updates_saved_path_name(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    doc.saved_paths = [{"name": "Old", "nodes": [], "closed": False}]

    w._path_rename(0, "New Name")

    assert doc.saved_paths[0]["name"] == "New Name"


def test_delete_removes_selected_saved_path_not_others(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    doc.saved_paths = [{"name": "A", "nodes": [], "closed": False},
                       {"name": "B", "nodes": [], "closed": False}]

    _select_row(w, 1)  # "B"
    w._path_delete()

    assert len(doc.saved_paths) == 1
    assert doc.saved_paths[0]["name"] == "A"


def test_delete_work_path_clears_it_not_saved_paths(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    doc.work_path = _wp((0, 0))
    doc.saved_paths = [{"name": "A", "nodes": [], "closed": False}]

    _select_row(w, 0)  # "Work Path" row (always first when present)
    w._path_delete()

    assert doc.work_path == {"nodes": [], "closed": False}
    assert len(doc.saved_paths) == 1


def test_make_selection_uses_saved_path_geometry(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    doc.saved_paths = [{"name": "A", "closed": True,
                        "nodes": [{"p": QPointF(5, 5), "c1": QPointF(5, 5), "c2": QPointF(5, 5)},
                                 {"p": QPointF(20, 5), "c1": QPointF(20, 5), "c2": QPointF(20, 5)},
                                 {"p": QPointF(20, 20), "c1": QPointF(20, 20), "c2": QPointF(20, 20)}]}]

    _select_row(w, 0)
    w._path_make_selection()

    assert doc.selection is not None
    assert not doc.selection.isEmpty()
    assert doc.selection.contains(QPointF(15, 10))  # inside the triangle-ish path


def test_fill_path_paints_into_active_layer(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    w._canvas.fg_color = QColor(255, 0, 0, 255)
    doc.saved_paths = [{"name": "A", "closed": True,
                        "nodes": [{"p": QPointF(2, 2), "c1": QPointF(2, 2), "c2": QPointF(2, 2)},
                                 {"p": QPointF(30, 2), "c1": QPointF(30, 2), "c2": QPointF(30, 2)},
                                 {"p": QPointF(30, 30), "c1": QPointF(30, 30), "c2": QPointF(30, 30)},
                                 {"p": QPointF(2, 30), "c1": QPointF(2, 30), "c2": QPointF(2, 30)}]}]

    _select_row(w, 0)
    w._path_fill()

    layer = doc.get_active_layer()
    assert layer.image.pixelColor(15, 15) == QColor(255, 0, 0, 255)


def test_operations_no_op_when_nothing_selected(main_window):
    w = main_window
    w._add_tab(Document(40, 40), "t")
    doc = w._document
    # No work path, no saved paths -> panel has only the placeholder row.
    w._paths_panel.refresh(w._canvas)

    w._path_make_selection()
    w._path_fill()
    w._path_stroke()
    w._path_delete()

    assert doc.selection is None
