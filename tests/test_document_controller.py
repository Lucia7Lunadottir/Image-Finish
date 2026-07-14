"""DocumentController guards: bounds, liveness, no-document tolerance."""

from core.document import Document


def test_layer_at_bounds(main_window):
    ctrl = main_window._doc_controller
    assert ctrl.layer_at(0) is None  # no document at all
    main_window._add_tab(Document(50, 40), "t")
    assert ctrl.layer_at(0) is not None
    assert ctrl.layer_at(5) is None
    assert ctrl.layer_at(-1) is None
    assert ctrl.layer_at("nope") is None


def test_set_active_layer_index_clamps(main_window):
    ctrl = main_window._doc_controller
    assert ctrl.set_active_layer_index(0) is False  # no document
    main_window._add_tab(Document(50, 40), "t")
    assert ctrl.set_active_layer_index(0) is True
    assert ctrl.set_active_layer_index(3) is False
    assert main_window._document.active_layer_index == 0


def test_is_alive_after_tab_close(main_window):
    ctrl = main_window._doc_controller
    doc = Document(50, 40)
    assert ctrl.is_alive(doc) is False
    main_window._add_tab(doc, "t")
    assert ctrl.is_alive(doc) is True
    main_window._doc_tabs.removeTab(0)
    assert ctrl.is_alive(doc) is False
    assert ctrl.is_alive(None) is False
