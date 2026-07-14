"""App-level smoke tests: construction and menu fuzz with/without document."""

from PyQt6.QtGui import QColor

from core.document import Document
from core.layer import Layer


def test_main_window_constructs(main_window):
    assert main_window._document is None
    assert main_window._canvas is None


def test_all_menu_actions_no_document(main_window, mocked_dialogs):
    """Every menu action must survive being triggered with no open tab."""
    failures = []
    for name, act in list(main_window._all_acts):
        try:
            act.trigger()
        except Exception as e:  # noqa: BLE001 — the point is "no exception at all"
            failures.append((name, repr(e)))
    assert not failures, failures


def test_all_menu_actions_with_document(main_window, mocked_dialogs):
    main_window._add_tab(Document(120, 90), "t")
    failures = []
    for name, act in list(main_window._all_acts):
        try:
            act.trigger()
        except Exception as e:  # noqa: BLE001
            failures.append((name, repr(e)))
    assert not failures, failures


def test_edit_layer_fill_and_adjustment(main_window, mocked_dialogs):
    """_on_edit_layer lives in LayerActionsMixin now (it used to be shadowed
    by an identically-named, out-of-sync method on MainWindow) — exercise
    both branches directly since neither is reachable via menu fuzzing."""
    w = main_window
    w._add_tab(Document(60, 50), "t")

    fill_layer = Layer("Fill", 60, 50)
    fill_layer.layer_type = "fill"
    fill_layer.fill_data = {"type": "solid", "color": QColor(128, 128, 128)}
    w._document.layers.append(fill_layer)
    w._document.active_layer_index = len(w._document.layers) - 1
    w._on_edit_layer()  # must not raise

    adj_layer = Layer("Adj", 60, 50)
    adj_layer.layer_type = "adjustment"
    adj_layer.adjustment_data = {"type": "invert"}
    w._document.layers.append(adj_layer)
    w._document.active_layer_index = len(w._document.layers) - 1
    w._on_edit_layer()  # must not raise


def test_basic_layer_workflow(main_window):
    main_window._add_tab(Document(100, 80), "t")
    w = main_window
    w._add_layer()
    assert len(w._document.layers) == 2
    w._on_layer_selected(1)
    assert w._document.active_layer_index == 1
    w._on_layer_selected(99)  # out of range must be a no-op, not a crash
    assert w._document.active_layer_index == 1
    w._undo()
    assert len(w._document.layers) == 1
    w._redo()
    assert len(w._document.layers) == 2
