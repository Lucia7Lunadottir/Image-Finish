"""Per-layer-kind behaviour as layer methods instead of `layer_type == "..."`
checks scattered over MoveTool, WarpTool, Align, snapping, Rasterize and
the panels (core/layer.py geometry queries, core/document.py tree queries).
"""
from PyQt6.QtCore import QPoint, QRect, QRectF
from PyQt6.QtGui import QColor, QImage

from core.document import Document
from core.layer import (AdjustmentLayer, ArtboardLayer, FillLayer, FrameLayer, GroupLayer,
                        RasterLayer, TextLayer)
from core.locale import tr


def _raster(doc, rect=QRect(10, 10, 20, 20), name="r"):
    layer = doc.add_layer(name=name)
    layer.image.fill(0)
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            layer.image.setPixelColor(x, y, QColor(200, 0, 0))
    return layer


def test_hit_test_per_kind(qapp):
    doc = Document(100, 80)
    r = _raster(doc)
    assert r.hit_test(QPoint(15, 15)) and not r.hit_test(QPoint(50, 50))
    art = ArtboardLayer("a", 100, 80)
    art.artboard_rect = QRect(40, 40, 30, 30)
    assert art.hit_test(QPoint(50, 50)) and not art.hit_test(QPoint(5, 5))
    assert not ArtboardLayer("a", 10, 10).hit_test(QPoint(1, 1))      # no rect yet
    assert not GroupLayer("g", 100, 80).hit_test(QPoint(15, 15))
    text = TextLayer("t", 100, 80)
    text.image.fill(0)
    text.image.setPixelColor(30, 30, QColor(0, 0, 0))
    assert text.hit_test(QPoint(33, 33))          # within the 4 px margin around glyphs
    assert not text.hit_test(QPoint(40, 40))


def test_snap_and_content_rects(qapp):
    doc = Document(100, 80)
    r = _raster(doc)
    r.offset = QPoint(5, 0)
    assert r.content_rect() == QRectF(15, 10, 20, 20) == r.snap_rect()
    art = ArtboardLayer("a", 100, 80)
    art.artboard_rect = QRect(1, 2, 30, 40)
    assert art.snap_rect() == QRectF(1, 2, 30, 40)
    assert art.content_rect().isEmpty()           # containers have no pixels of their own
    assert GroupLayer("g", 100, 80).content_rect().isEmpty()


def test_document_tree_queries(qapp):
    doc = Document(100, 80)
    art = doc.add_layer(name="art", layer_cls=ArtboardLayer)
    art.artboard_rect = QRect(0, 0, 50, 50)
    group = doc.add_layer(name="g", layer_cls=GroupLayer)
    group.parent_id = art.layer_id
    kid = doc.add_layer(name="k")
    kid.parent_id = group.layer_id
    loose = doc.add_layer(name="loose")
    loose.parent_id = None
    assert doc.layer_by_id(group.layer_id) is group
    assert doc.descendants(art) == [group, kid]
    assert doc.enclosing_artboard(kid) is art
    assert doc.enclosing_artboard(loose) is None
    assert doc.artboards() == [art]
    kid.parent_id = kid.layer_id                  # a cycle must not hang
    assert doc.enclosing_artboard(kid) is None


def test_auto_names_are_translated(qapp):
    doc = Document(10, 10)
    assert doc.next_layer_name(TextLayer, "layer.name.text") == f"{tr('layer.name.text')} 1"
    doc.add_layer(layer_cls=TextLayer)
    assert doc.next_layer_name(TextLayer, "layer.name.text").endswith(" 2")


def test_rasterized_image_per_kind(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    fill = doc.add_layer(name="f", layer_cls=FillLayer)
    fill.fill_data = {"type": "solid", "color": QColor(0, 0, 255)}
    doc.active_layer_index = doc.layers.index(fill)
    w._rasterize_layer()
    out = doc.get_active_layer()
    assert type(out) is RasterLayer and out.image.pixelColor(5, 5) == QColor(0, 0, 255)

    adj = doc.add_layer(name="a", layer_cls=AdjustmentLayer)
    adj.adjustment_data = {"type": "invert"}
    adj.image.fill(QColor(255, 0, 0))
    doc.active_layer_index = doc.layers.index(adj)
    w._rasterize_layer()
    out = doc.get_active_layer()
    assert type(out) is RasterLayer and out.image.pixelColor(5, 5).alpha() == 0


def test_undo_of_a_frame_move_restores_its_rect(main_window, mocked_dialogs):
    """The drag now moves the frame rect live (same hook as the numeric
    Transform panel); the history snapshot must still record the original
    rect — before, only artboards were special-cased there."""
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    frame = doc.layers[0].convert_to(FrameLayer)
    frame.frame_data = {"rect": QRectF(20, 20, 40, 30), "shape": "rect"}
    frame.image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    doc.layers[0] = frame
    doc.active_layer_index = 0
    w._activate_tool("Move")
    tool = w._tools["Move"]
    opts = {"_zoom": 1.0, "_ctrl": True}
    tool.on_press(QPoint(40, 35), doc, QColor(), QColor(), opts)
    tool.on_move(QPoint(55, 30), doc, QColor(), QColor(), opts)
    r = frame.frame_data["rect"]
    assert (round(r.x()), round(r.y())) == (35, 15)          # follows the drag live
    w._commit_move_transform()
    r = doc.layers[0].frame_data["rect"]
    assert (round(r.x()), round(r.y())) == (35, 15)
    w._undo()
    r = w._document.layers[0].frame_data["rect"]
    assert (round(r.x()), round(r.y()), round(r.width()), round(r.height())) == (20, 20, 40, 30)


def test_artboard_move_undo_still_restores_its_rect(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    art = doc.add_layer(name="art", layer_cls=ArtboardLayer)
    art.artboard_rect = QRect(20, 20, 60, 40)
    doc.active_layer_index = doc.layers.index(art)
    w._activate_tool("Move")
    tool = w._tools["Move"]
    opts = {"_zoom": 1.0, "_ctrl": True}
    tool.on_press(QPoint(50, 40), doc, QColor(), QColor(), opts)
    tool.on_move(QPoint(60, 40), doc, QColor(), QColor(), opts)
    w._commit_move_transform()
    w._undo()
    restored = next(l for l in w._document.layers if isinstance(l, ArtboardLayer))
    assert restored.artboard_rect == QRect(20, 20, 60, 40)


def test_undo_of_a_numeric_frame_transform_restores_its_rect(main_window, mocked_dialogs):
    """Was broken before: the Transform panel moved the frame rect live
    and the snapshot recorded the moved rect, so Undo kept it moved."""
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    frame = doc.layers[0].convert_to(FrameLayer)
    frame.frame_data = {"rect": QRectF(20, 20, 40, 30), "shape": "rect"}
    frame.image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    doc.layers[0] = frame
    doc.active_layer_index = 0
    w._activate_tool("Move")
    tool = w._tools["Move"]
    opts = {"_zoom": 1.0, "_ctrl": True}
    tool.on_press(QPoint(40, 35), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(40, 35), doc, QColor(), QColor(), opts)
    p = dict(tool.get_transform_params())
    p["x"] += 30
    tool.set_transform_params(doc, p)
    w._commit_move_transform()
    assert round(w._document.layers[0].frame_data["rect"].x()) == 50
    w._undo()
    assert round(w._document.layers[0].frame_data["rect"].x()) == 20
