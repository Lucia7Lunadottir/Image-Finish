"""ui/actions/pixel_target.py — the gate in front of every pixel command.

Filters and Image > Adjustments used to edit whatever the active layer's
`image` was: on text/shape/fill layers only an invisible baked copy (no
change on the canvas, but an undo step), on adjustment layers an unused
image."""
import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox

from core.document import Document
from core.layer import AdjustmentLayer, TextLayer


def _doc_with(w, layer_cls, **attrs):
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.add_layer(name="L", layer_cls=layer_cls)
    for k, v in attrs.items():
        setattr(layer, k, v)
    doc.active_layer_index = doc.layers.index(layer)
    return doc, layer


def _answer(monkeypatch, button):
    asked = []
    def question(*a, **k):
        asked.append(a)
        return button
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


@pytest.mark.parametrize("command", ["_gaussian_blur", "_brightness_contrast", "_invert",
                                     "_open_noise", "_match_color"])
def test_adjustment_layer_is_refused_without_an_undo_step(main_window, mocked_dialogs, command):
    w = main_window
    doc, layer = _doc_with(w, AdjustmentLayer, adjustment_data={"type": "invert"})
    before = len(w._history._undo_stack)
    fn = getattr(w, command)
    fn("add_noise") if command == "_open_noise" else fn()
    assert len(w._history._undo_stack) == before
    assert doc.layers[doc.active_layer_index] is layer
    assert w._status.currentMessage()


def test_text_layer_cancel_keeps_it_text(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with(w, TextLayer, text_data={"text": "hi", "x": 2, "y": 2, "font_size": 12})
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    w._gaussian_blur()
    assert asked
    assert doc.get_active_layer() is layer and layer.layer_type == "text"


def test_text_layer_ok_rasterizes_then_runs(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with(w, TextLayer, text_data={"text": "hi", "x": 2, "y": 2, "font_size": 12})
    _answer(monkeypatch, QMessageBox.StandardButton.Ok)
    w._invert()
    active = doc.get_active_layer()
    assert active.layer_type == "raster" and active.name == "L"


def test_raster_layer_goes_straight_through(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.get_active_layer()
    layer.image.fill(QColor(10, 20, 30))
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    w._invert()
    assert not asked
    assert doc.get_active_layer().image.pixelColor(0, 0) == QColor(245, 235, 225)


# ── canvas tools ───────────────────────────────────────────────────────────
# The canvas used to refuse a hard-coded list of tool names on text/smart
# objects only; a brush stroke on a shape, fill or adjustment layer went
# into the invisible baked image (and onto the undo stack).

def test_every_pixel_tool_declares_its_op(main_window):
    painting = {"Brush", "Eraser", "BackgroundEraser", "MagicEraser", "CloneStamp", "PatternStamp",
                "Pencil", "ColorReplacement", "MixerBrush", "HistoryBrush", "Fill", "Blur",
                "Sharpen", "Smudge", "Dodge", "Burn", "Sponge", "Gradient", "Patch",
                "SpotHealing", "HealingBrush", "RedEye"}
    warps = {"Warp", "PuppetWarp", "PerspectiveWarp"}
    for name, tool in main_window._tools.items():
        want = "paint" if name in painting else "transform" if name in warps else None
        assert getattr(tool, "PIXEL_OP", None) == want, name


def _press(w, tool_name, doc_pt=QPoint(10, 10)):
    from PyQt6.QtCore import QPointF, QEvent, Qt
    from PyQt6.QtGui import QMouseEvent
    canvas = w._canvas
    canvas.active_tool = w._tools[tool_name]
    pos = canvas.to_widget(doc_pt)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos), QPointF(pos),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(ev)
    return canvas


def test_brush_on_fill_layer_asks_and_cancel_changes_nothing(main_window, mocked_dialogs, monkeypatch):
    from core.layer import FillLayer
    w = main_window
    doc, layer = _doc_with(w, FillLayer, fill_data={"type": "solid", "color": QColor(0, 0, 255)})
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    before = layer.image.copy()
    _press(w, "Brush")
    assert asked and layer.image == before and doc.get_active_layer() is layer


def test_brush_on_shape_ok_rasterizes(main_window, mocked_dialogs, monkeypatch):
    from core.layer import VectorLayer
    w = main_window
    doc, layer = _doc_with(w, VectorLayer, shape_data={
        "shape": "rect", "rect": (0, 0, 20, 20), "fg": "#00ff00", "bg": "#00ff00",
        "fill": True, "size": 0, "sides": 6, "angle": 0})
    _answer(monkeypatch, QMessageBox.StandardButton.Ok)
    _press(w, "Brush")
    assert doc.get_active_layer().layer_type == "raster"


def test_brush_on_adjustment_layer_refused_but_its_mask_is_paintable(main_window, mocked_dialogs, monkeypatch):
    from PyQt6.QtGui import QImage
    from ui.actions.pixel_target import pixel_layer_for_edit
    w = main_window
    doc, layer = _doc_with(w, AdjustmentLayer, adjustment_data={"type": "invert"})
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Ok)
    assert pixel_layer_for_edit(w, "paint") is None and not asked
    layer.mask = QImage(20, 20, QImage.Format.Format_Grayscale8)
    layer.mask.fill(255)
    layer.editing_mask = True
    assert pixel_layer_for_edit(w, "paint") is layer


def test_smart_object_takes_filters_but_paint_needs_rasterizing(qapp):
    from core.layer import SmartObjectLayer
    so = SmartObjectLayer("s", 2, 2)
    assert so.pixel_access_for("filter") == "direct"
    assert so.pixel_access_for("transform") == "direct"
    assert so.pixel_access_for("paint") == "rasterize"


def test_cursor_traits_are_declared_on_the_tool_classes(main_window):
    """Were name sets in canvas_widget (_BRUSH_TOOLS, _SELECTION_TOOLS)."""
    brush = {"Brush", "Eraser", "BackgroundEraser", "Blur", "Sharpen", "Smudge", "CloneStamp",
             "PatternStamp", "Pencil", "ColorReplacement", "MixerBrush", "SpotHealing",
             "HealingBrush", "HistoryBrush", "Dodge", "Burn", "Sponge", "QuickSelection"}
    selection = {"Select", "EllipseSelect", "Lasso", "PolygonalLasso", "MagneticLasso",
                 "MagicWand", "ObjectSelection"}
    for name, tool in main_window._tools.items():
        assert tool.BRUSH_CURSOR == (name in brush), name
        assert tool.SELECTION_CURSOR == (name in selection), name


def test_stroke_history_step_uses_the_translated_tool_name(main_window, mocked_dialogs):
    from core.locale import tr
    w = main_window
    w._add_tab(Document(40, 40), "t")
    canvas = _press(w, "Brush")
    assert canvas._pre_stroke_state.description == tr("tool.brush")


def test_alt_and_cursor_quirks_are_declared_on_the_tool_classes(main_window):
    """Were tool-name checks in canvas_widget (_ALT_EYEDROPPER_TOOLS,
    'BackgroundEraser', 'CloneStamp')."""
    alt_eyedropper = {"Brush", "Pencil", "ColorReplacement", "MixerBrush", "PatternStamp"}
    for name, tool in main_window._tools.items():
        assert tool.ALT_EYEDROPPER == (name in alt_eyedropper), name
        assert tool.ALT_PICKS_SOURCE == (name == "CloneStamp"), name
        assert tool.PLAIN_BRUSH_CURSOR == (name == "BackgroundEraser"), name


@pytest.mark.parametrize("tool_name,opts", [
    ("Brush", {"brush_size": 30, "brush_hardness": 0.5}),
    ("Brush", {"brush_size": 30, "brush_mask": "square", "brush_angle": 30}),
    ("Brush", {"brush_size": 30, "brush_mask": "scatter"}),
    ("Brush", {"brush_size": 30, "brush_mirror_x": True, "brush_mirror_y": True}),
    ("CloneStamp", {"brush_size": 30, "_alt": True}),
    ("BackgroundEraser", {"brush_size": 30, "brush_mask": "square"}),
])
def test_brush_cursor_overlay_paints(qapp, tool_name, opts):
    import logging
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QImage, QPainter
    from ui.canvas_cursors import BrushCursorOverlay
    from ui.main_window import _build_tool_registry
    tool = _build_tool_registry(None)[tool_name]
    img = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    failures = []
    handler = logging.Handler()
    handler.emit = lambda r: failures.append(r)
    logging.getLogger("canvas").addHandler(handler)
    try:
        BrushCursorOverlay().paint(p, tool=tool, opts=opts, zoom=1.0, mouse=QPointF(60, 60),
                                   to_doc=lambda q: QPoint(int(q.x()), int(q.y())),
                                   to_widget=lambda q: QPointF(q), doc_size=(200, 200))
    finally:
        logging.getLogger("canvas").removeHandler(handler)
        p.end()
    assert not failures
    assert any(img.pixelColor(x, y).alpha() for x in range(200) for y in range(200))
