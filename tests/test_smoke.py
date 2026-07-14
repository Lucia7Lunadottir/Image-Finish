"""App-level smoke tests: construction and menu fuzz with/without document."""

from core.document import Document


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
