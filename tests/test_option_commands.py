"""MainWindow._on_opt_changed: option-bar *commands* go to one method each
(_OPTION_COMMANDS) and are never stored as tool options."""
from core.document import Document


def test_every_option_command_has_its_method():
    from ui.main_window import MainWindow
    for key, method in MainWindow._OPTION_COMMANDS.items():
        assert callable(getattr(MainWindow, method, None)), (key, method)


def test_a_command_is_dispatched_not_stored(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    ruler = w._tools["Ruler"]
    cleared = []
    ruler.clear = lambda: cleared.append(1)
    w._on_opt_changed("ruler_clear", True)
    assert cleared
    assert "ruler_clear" not in w._canvas.tool_opts


def test_an_option_is_stored_on_every_canvas(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(20, 20), "a")
    w._add_tab(Document(20, 20), "b")
    w._on_opt_changed("brush_size", 33)
    for i in range(w._doc_tabs.count()):
        assert w._doc_tabs.widget(i).tool_opts["brush_size"] == 33
