"""Paths panel v1: the panel used to show only a single ephemeral "Work
Path" row with no way to keep more than one path around. Added:
Document.saved_paths (named, permanent entries), "New Path" (promotes the
current work path into one), inline rename, and Make Selection/Fill/
Stroke/Delete generalized to act on whichever row — work path or saved —
is selected, instead of only ever assuming "work".
"""
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor

from core.document import Document
from ui.paths_panel import PathsPanel


def _wp(*points, closed=False):
    return {"nodes": [{"p": QPointF(*pt), "c1": QPointF(*pt), "c2": QPointF(*pt)}
                      for pt in points],
            "closed": closed}


class _FakeCanvas:
    def __init__(self, document):
        self.document = document


def test_refresh_shows_placeholder_when_nothing_to_show(qapp):
    panel = PathsPanel()
    panel.refresh(_FakeCanvas(Document(10, 10)))
    assert panel._list.count() == 1
    assert panel._selected_kind() == (None, None)


def test_refresh_lists_work_path_and_saved_paths(qapp):
    doc = Document(10, 10)
    doc.work_path = _wp((1, 1), (2, 2))
    doc.saved_paths = [
        {"name": "Path 1", "nodes": [], "closed": False},
        {"name": "Path 2", "nodes": [], "closed": False},
    ]
    panel = PathsPanel()
    panel.refresh(_FakeCanvas(doc))

    assert panel._list.count() == 3
    assert panel._list.item(0).data(Qt.ItemDataRole.UserRole) == ("work", None)
    assert panel._list.item(1).text() == "Path 1"
    assert panel._list.item(1).data(Qt.ItemDataRole.UserRole) == ("saved", 0)
    assert panel._list.item(2).text() == "Path 2"
    assert panel._list.item(2).data(Qt.ItemDataRole.UserRole) == ("saved", 1)


def test_new_path_button_enabled_only_with_work_path(qapp):
    doc = Document(10, 10)
    panel = PathsPanel()
    panel.refresh(_FakeCanvas(doc))
    assert not panel._btn_new.isEnabled()

    doc.work_path = _wp((0, 0))
    panel.refresh(_FakeCanvas(doc))
    assert panel._btn_new.isEnabled()


def test_selection_preserved_across_refresh_for_saved_path(qapp):
    doc = Document(10, 10)
    doc.saved_paths = [{"name": "A", "nodes": [], "closed": False},
                       {"name": "B", "nodes": [], "closed": False}]
    panel = PathsPanel()
    panel.refresh(_FakeCanvas(doc))
    panel._list.setCurrentRow(1)  # select "B"
    assert panel._selected_kind() == ("saved", 1)

    panel.refresh(_FakeCanvas(doc))  # e.g. after an unrelated canvas refresh
    assert panel._selected_kind() == ("saved", 1)
    assert panel._list.currentItem().text() == "B"


def test_rename_via_item_changed_emits_signal_with_correct_index(qapp):
    doc = Document(10, 10)
    doc.saved_paths = [{"name": "A", "nodes": [], "closed": False},
                       {"name": "B", "nodes": [], "closed": False}]
    panel = PathsPanel()
    panel.refresh(_FakeCanvas(doc))

    received = []
    panel.rename_path_requested.connect(lambda idx, name: received.append((idx, name)))

    item = panel._list.item(1)  # "B"
    item.setText("Renamed")

    assert received == [(1, "Renamed")]


def test_refresh_does_not_spuriously_fire_rename(qapp):
    """Populating the list (addItem/setText during refresh()) must not be
    mistaken for a user-driven rename — itemChanged fires during
    population too, not just on real edits."""
    doc = Document(10, 10)
    doc.saved_paths = [{"name": "A", "nodes": [], "closed": False}]
    panel = PathsPanel()

    received = []
    panel.rename_path_requested.connect(lambda idx, name: received.append((idx, name)))
    panel.refresh(_FakeCanvas(doc))
    panel.refresh(_FakeCanvas(doc))

    assert received == []
