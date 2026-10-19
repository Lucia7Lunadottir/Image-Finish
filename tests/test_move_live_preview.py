"""Dragging text or a shape with the Move tool shows exactly what letting
go will: the layer composites as moved through the normal pipeline —
with its layer styles (the old preview painted only the bare content on
top of the canvas, so a stroke or shadow vanished mid-drag), in its place
in the layer stack — and the zoomed canvas may stay sharp mid-drag."""
import pytest
from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtGui import QColor, QTransform

from core.document import Document
from core.layer import TextLayer, VectorLayer
from tools.move_tool import MoveTool

ZOOM = 4.0


def _text_doc(styles=True):
    doc = Document(200, 120)
    layer = doc.add_layer(name="T", layer_cls=TextLayer)
    layer.text_data = {"text": "Hg", "x": 40, "y": 40, "font_size": 36, "color": "#ff000000"}
    if styles:
        layer.layer_styles = {"stroke": {"enabled": True, "size": 3, "color": QColor(0, 0, 255)}}
    layer.rebake_thumbnail()
    return doc, layer


def _view(doc):
    return doc.render_view(QTransform().scale(ZOOM, ZOOM), QSize(800, 480))


def _start_drag(doc):
    tool = MoveTool()
    opts = {"_zoom": ZOOM}
    tool.on_press(QPoint(60, 55), doc, QColor(), QColor(), opts)
    tool.on_move(QPoint(70, 60), doc, QColor(), QColor(), opts)
    return tool


@pytest.mark.parametrize("styles", [False, True])
def test_mid_drag_frame_is_the_committed_frame(qapp, styles):
    doc, _ = _text_doc(styles)
    tool = _start_drag(doc)
    during = _view(doc)
    tool.on_release(QPoint(70, 60), doc, QColor(), QColor(), {"_zoom": ZOOM})
    tool.apply_transform(doc)
    assert during == _view(doc)
    assert tool.floating_preview() is None


def test_layer_style_is_visible_mid_drag(qapp):
    doc, layer = _text_doc()
    _start_drag(doc)
    img = doc.get_composite()
    blue = [(x, y) for x in range(doc.width) for y in range(doc.height)
            if img.pixelColor(x, y) == QColor(0, 0, 255)]
    assert blue
    assert min(x for x, _ in blue) > 40            # the stroke moved with the text


def test_dragged_shape_stays_under_the_layer_above(qapp):
    doc = Document(100, 100)
    shape = doc.add_layer(name="S", layer_cls=VectorLayer)
    shape.shape_data = {"shape": "rect", "rect": (10, 10, 30, 30), "fill": True,
                        "fill_color": "#ffff0000", "size": 0, "sides": 6, "angle": 0}
    shape.rebake_thumbnail()
    cover = doc.add_layer(name="cover")
    cover.image.fill(QColor(0, 255, 0))
    doc.active_layer_index = doc.layers.index(shape)
    tool = MoveTool()
    tool.on_press(QPoint(20, 20), doc, QColor(), QColor(), {})
    tool.on_move(QPoint(40, 40), doc, QColor(), QColor(), {})
    assert doc.get_composite().pixelColor(45, 45) == QColor(0, 255, 0)


def test_ground_truth_render_sees_the_layer_where_it_still_is(qapp):
    doc, layer = _text_doc(styles=False)
    before = doc.get_composite(respect_live_hidden=False)
    _start_drag(doc)
    assert doc.get_composite(respect_live_hidden=False) == before


def test_cancel_puts_the_layer_back(qapp):
    doc, layer = _text_doc()
    before = _view(doc)
    tool = _start_drag(doc)
    tool.cancel_transform(doc)
    assert layer._move_preview_source is None and not layer._live_edit_hidden
    assert _view(doc) == before


def test_move_of_live_content_may_stay_sharp_mid_drag(qapp):
    doc, _ = _text_doc()
    tool = _start_drag(doc)
    assert tool.sharp_while_dragging()
    pixels = Document(50, 50)
    tool2 = MoveTool()
    tool2.on_press(QPoint(10, 10), pixels, QColor(), QColor(), {})
    tool2.on_move(QPoint(20, 20), pixels, QColor(), QColor(), {})
    assert not tool2.sharp_while_dragging()


def test_hires_renders_mid_drag_only_for_sharp_drags_within_budget(main_window, mocked_dialogs):
    from ui.canvas_hires import HiresView
    main_window._add_tab(Document(50, 50), "t")
    canvas = main_window._canvas
    hires = HiresView(canvas)

    class _Tool:
        def __init__(self, sharp):
            self.sharp = sharp

        def sharp_while_dragging(self):
            return self.sharp

    canvas._active_tool = _Tool(True)
    hires.render_ms = 10
    assert hires._may_render_now(True)
    hires.render_ms = 200                           # too slow: wait for the release
    assert not hires._may_render_now(True)
    canvas._active_tool = _Tool(False)              # a brush stroke
    hires.render_ms = 1
    assert not hires._may_render_now(True)
    assert hires._may_render_now(False)
