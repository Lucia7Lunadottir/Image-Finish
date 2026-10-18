"""ui/tool_options/overflow.py: options pages wider than the window move
their trailing controls into the "»" popup instead of running off-screen
(the Brush page alone needed ~2000 px)."""
from PyQt6.QtWidgets import QApplication, QLabel


def _bar(main_window, width, tool):
    w = main_window
    w.resize(width, 700)
    w.show()
    w._activate_tool(tool)
    QApplication.processEvents()
    bar = w._opts_bar
    bar._fit_current()
    QApplication.processEvents()
    return bar, bar._overflow._entries(bar.page_for(tool))


def test_narrow_window_overflows_and_wide_window_restores(main_window):
    bar, entries = _bar(main_window, 1000, "Brush")
    assert entries.overflowed and bar._overflow.button.isVisible()
    bar._overflow.fit(bar.page_for("Brush"), 5000)
    assert not entries.overflowed and not bar._overflow.button.isVisible()


def test_row_fits_in_the_available_width(main_window):
    bar, entries = _bar(main_window, 1000, "Brush")
    avail = bar._scroll.viewport().width()
    in_row = [u for u in entries.units() if u not in entries.overflowed]
    assert sum(u.width_hint() for u in in_row) <= avail


def test_labels_stay_with_their_controls(main_window):
    bar, entries = _bar(main_window, 900, "Brush")
    for unit in entries.units():
        labels = [i for i, w in enumerate(unit.widgets) if isinstance(w, QLabel) and w.objectName() == "optLabel"]
        assert labels in ([], [0])          # a label only ever leads its unit
        if labels:
            assert len(unit.widgets) > 1    # ...and never stands alone


def test_overflowed_controls_still_work(main_window):
    bar, entries = _bar(main_window, 900, "Brush")
    seen = []
    bar.option_changed.connect(lambda k, v: seen.append(k))
    unit = next(iter(entries.overflowed))
    from PyQt6.QtWidgets import QAbstractSpinBox
    spins = [c for w in unit.widgets for c in ([w] + w.findChildren(QAbstractSpinBox))
             if isinstance(c, QAbstractSpinBox)]
    assert spins
    spins[0].setValue(spins[0].value() + 1)
    assert seen


def test_shape_kind_change_refits(main_window):
    bar, entries = _bar(main_window, 1200, "Shapes")
    page = bar.page_for("Shapes")
    page._combo.setCurrentIndex(page._SHAPE_VALUES.index("rounded_rect"))   # shows 4 radius fields
    QApplication.processEvents()
    QApplication.processEvents()
    in_row = [u for u in entries.units() if u not in entries.overflowed]
    assert sum(u.width_hint() for u in in_row) <= bar._scroll.viewport().width()


def test_changing_an_option_with_no_document_open_is_kept_for_the_next_one(main_window):
    """Was a hard crash: _on_opt_changed dereferenced self._canvas (None on
    the Welcome screen) inside a slot, which PyQt6 turns into abort()."""
    from core.document import Document
    w = main_window
    assert w._canvas is None
    w._on_opt_changed("brush_size", 77)
    w._add_tab(Document(50, 50), "t")
    assert w._canvas.tool_opts["brush_size"] == 77
