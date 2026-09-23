"""Real bug she hit live: after drawing a shape (ShapesTool or Pen Tool),
the new vector layer never showed up in the layers panel. Root cause:
CanvasWidget.document_changed fires for two very different situations —
"pixels changed on a layer already shown" (want the cheap
refresh_active_thumbnail path) and "a layer was added/removed" (a tool
creating a layer directly during a mouse event, not through an explicit
menu action that calls _refresh_layers() itself) — but
MainWindow._deferred_panel_refresh always took the cheap path regardless,
so a newly-added layer had no row at all until something else happened to
trigger a full rebuild.
"""
from core.document import Document
from core.layer import VectorLayer


def test_deferred_refresh_rebuilds_panel_when_layer_count_changed(main_window):
    doc = Document(60, 40)
    main_window._add_tab(doc, "test")
    main_window._refresh_layers()
    assert main_window._layers_panel._list.count() == 1

    # Simulate a tool adding a layer directly (ShapesTool/PenTool's
    # mouseReleaseEvent path) without calling _refresh_layers() itself —
    # only the generic document_changed -> _on_doc_changed signal fires.
    doc.add_layer(name="Shape 1", layer_cls=VectorLayer)
    assert len(doc.layers) == 2

    main_window._deferred_panel_refresh()

    assert main_window._layers_panel._list.count() == 2


def test_deferred_refresh_stays_cheap_when_layer_count_unchanged(main_window):
    """Contrast case: a normal brush stroke (pixels changed, no new layer)
    must NOT force a full list rebuild every time — that's the whole point
    of the thumbnail-only fast path this bug's fix must not regress."""
    doc = Document(60, 40)
    main_window._add_tab(doc, "test")
    main_window._refresh_layers()
    row_widget_before = main_window._layers_panel._list.itemWidget(main_window._layers_panel._list.item(0))

    main_window._deferred_panel_refresh()

    assert main_window._layers_panel._list.count() == 1
    row_widget_after = main_window._layers_panel._list.itemWidget(main_window._layers_panel._list.item(0))
    assert row_widget_before is row_widget_after  # same widget instance -> no rebuild happened
