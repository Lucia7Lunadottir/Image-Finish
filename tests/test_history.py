"""Undo history: byte budget, image dedup and copy-on-write snapshot safety."""

from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from core.history import HistoryManager, HistoryState


def _push(hm, doc, i):
    hm.push(HistoryState(description=f"s{i}",
                         layers_snapshot=doc.snapshot_layers(modified_index=0),
                         active_layer_index=0,
                         doc_width=doc.width, doc_height=doc.height))


def test_byte_budget_evicts_oldest(qapp):
    doc = Document(400, 300)  # one layer ≈ 480 KB
    hm = HistoryManager(max_states=40, max_bytes=3_000_000)
    for i in range(12):
        _push(hm, doc, i)
        p = QPainter(doc.layers[0].image)
        p.fillRect(i * 10, 0, 10, 10, QColor(10 + i * 20, 0, 0))
        p.end()
    assert len(hm._undo_stack) < 12
    assert hm.estimated_bytes() <= 3_000_000
    assert hm._undo_stack[0].description != "s0"


def test_shared_images_counted_once(qapp):
    doc = Document(200, 150)
    doc.add_layer()
    hm = HistoryManager(max_states=40, max_bytes=10**9)
    for i in range(5):
        _push(hm, doc, i)  # layer 1 shared across all snapshots (COW)
    single_layer = doc.layers[0].image.sizeInBytes()
    # 5 deep copies of layer 0 + 1 shared layer 1 (unchanged => same cacheKey)
    assert hm.estimated_bytes() <= single_layer * 7


def test_cow_snapshot_isolation(qapp):
    """In-place painting after a shared snapshot must not alter the snapshot."""
    doc = Document(400, 300)
    hm = HistoryManager(max_states=40, max_bytes=10**9)
    for i in range(4):
        _push(hm, doc, i)
        p = QPainter(doc.layers[0].image)
        p.fillRect(i * 10, 0, 10, 10, QColor(10 + i * 20, 0, 0))
        p.end()
    first = hm._undo_stack[0].layers_snapshot[0].image
    # Snapshot s0 was taken before any stroke: stroke 0 pixel must be absent.
    assert first.pixelColor(5, 5) != QColor(10, 0, 0)


def test_undo_redo_roundtrip(main_window):
    from core.document import Document as Doc
    main_window._add_tab(Doc(100, 80), "t")
    w = main_window
    w._document.layers[0].image.fill(QColor(1, 2, 3))
    w._push_history("fill", modified_index=0)
    w._document.layers[0].image.fill(QColor(200, 100, 50))
    w._undo()
    assert w._document.layers[0].image.pixelColor(5, 5) == QColor(1, 2, 3)
    w._redo()
    assert w._document.layers[0].image.pixelColor(5, 5) == QColor(200, 100, 50)
