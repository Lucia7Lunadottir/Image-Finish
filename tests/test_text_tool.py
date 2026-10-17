"""Type-mask tools (HorizontalTypeMaskTool/VerticalTypeMaskTool): prompt
for text, set doc.selection to its outline. The editing type tools
(TextTool/VerticalTypeTool) are covered by tests/test_text_editing.py.
"""
from types import SimpleNamespace

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from core.layer import TextLayer
from tools.text_tool import (
    TextTool, VerticalTypeTool, HorizontalTypeMaskTool, VerticalTypeMaskTool,
)


def _opaque_text_layer(name, x, y, w=20, h=20, vertical=False, offset=QPoint(0, 0)):
    layer = TextLayer(name, 100, 100)
    layer.offset = offset
    p = QPainter(layer.image)
    p.fillRect(x, y, w, h, QColor(0, 0, 0, 255))
    p.end()
    layer.text_data = {"text": name, "x": x, "y": y, "font_size": 24,
                        "vertical": vertical}
    return layer


def _fake_canvas():
    calls = []
    canvas = SimpleNamespace()
    canvas.begin_text_edit = lambda doc, layer, text, anchor, vertical=False: \
        calls.append((doc, layer, text, anchor, vertical))
    canvas._calls = calls
    return canvas


def _with_canvas(tool, canvas):
    tool._parent_widget = SimpleNamespace(_canvas=canvas)
    return tool


def test_horizontal_type_mask_tool_sets_selection_from_dialog_text(qapp, monkeypatch):
    import tools.text_tool as tt

    class _StubDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return tt.QDialog.DialogCode.Accepted
        def get_text(self): return "Hi"
        def get_font_opts(self): return {"font_size": 30}

    monkeypatch.setattr(tt, "_TextDialog", _StubDialog)
    recorded = {}
    def fake_path_h(pos, text, opts):
        recorded["args"] = (pos, text, opts)
        return "H-PATH"
    monkeypatch.setattr(tt, "_text_path_h", fake_path_h)

    doc = Document(100, 100)
    tool = _with_canvas(HorizontalTypeMaskTool(), _fake_canvas())
    opts = {"font_size": 24}
    tool.on_press(QPoint(5, 5), doc, QColor("black"), QColor("white"), opts)

    assert doc.selection == "H-PATH"
    pos, text, used_opts = recorded["args"]
    assert text == "Hi"
    assert used_opts["font_size"] == 30  # dialog's font opts merged in


def test_vertical_type_mask_tool_uses_vertical_path_fn(qapp, monkeypatch):
    import tools.text_tool as tt

    class _StubDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return tt.QDialog.DialogCode.Accepted
        def get_text(self): return "Hi"
        def get_font_opts(self): return {}

    monkeypatch.setattr(tt, "_TextDialog", _StubDialog)
    monkeypatch.setattr(tt, "_text_path_h", lambda *a, **k: "H-PATH")
    monkeypatch.setattr(tt, "_text_path_v", lambda *a, **k: "V-PATH")

    doc = Document(100, 100)
    tool = _with_canvas(VerticalTypeMaskTool(), _fake_canvas())
    tool.on_press(QPoint(5, 5), doc, QColor("black"), QColor("white"), {})

    assert doc.selection == "V-PATH"


def test_type_mask_tool_cancelled_dialog_does_not_set_selection(qapp, monkeypatch):
    import tools.text_tool as tt

    class _StubDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return tt.QDialog.DialogCode.Rejected
        def get_text(self): return "Hi"
        def get_font_opts(self): return {}

    monkeypatch.setattr(tt, "_TextDialog", _StubDialog)

    doc = Document(100, 100)
    tool = _with_canvas(HorizontalTypeMaskTool(), _fake_canvas())
    tool.on_press(QPoint(5, 5), doc, QColor("black"), QColor("white"), {})

    assert doc.selection is None
