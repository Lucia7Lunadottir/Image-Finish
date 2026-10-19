"""Warp Text: core/text_warp.py, its place in the text model / layout, the
Layer > Warp Text… command and the on-canvas editor showing the plain text."""
import pytest
from PyQt6.QtCore import QPoint, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document
from core.layer import TextLayer
from core.text_engine import layout_text, text_outline_in_document
from core.text_model import TextData
from core.text_warp import STYLE_KEYS, WARP_STYLES, TextWarp


def _data(text="Equestria", warp=None):
    d = TextData.from_dict({"text": text, "x": 20, "y": 30, "font_size": 40})
    if warp is not None:
        d.warp = warp
    return d


# ── the warp itself ──────────────────────────────────────────────────────────

def test_warp_is_active_only_with_a_style_that_does_something():
    assert not TextWarp().is_active()
    assert not TextWarp(style="arc", bend=0).is_active()
    assert TextWarp(style="arc", bend=30).is_active()
    assert TextWarp(style="flag", bend=0, hdist=20).is_active()


def test_warp_dict_round_trip_and_bad_values():
    w = TextWarp(style="wave", horizontal=False, bend=-40, hdist=10, vdist=-5)
    assert TextWarp.from_dict(w.to_dict()) == w
    bad = TextWarp.from_dict({"style": "nonsense", "bend": 900, "hdist": "x"})
    assert bad.style == "none" and bad.bend == 100 and bad.hdist == 0


@pytest.mark.parametrize("style", list(WARP_STYLES))
def test_every_style_changes_the_text_and_keeps_it_whole(qapp, style):
    plain = layout_text(_data()).outline()
    warped = layout_text(_data(warp=TextWarp(style=style, bend=60))).outline()
    assert warped.boundingRect() != plain.boundingRect() or warped != plain
    # Same glyph count, nothing thrown far away.
    assert warped.toSubpathPolygons().__len__() == plain.toSubpathPolygons().__len__()
    b, p = warped.boundingRect(), plain.boundingRect()
    assert b.width() < p.width() * 2 and b.height() < p.width()


def test_arc_bends_the_ends_down_and_negative_bend_up(qapp):
    frame = QRectF(0, 0, 200, 40)
    up = TextWarp(style="arc", bend=50)
    down = TextWarp(style="arc", bend=-50)
    left = QPointF(0, 20)
    assert up.map_point(left, frame).y() > 20           # ends drop: an arch shape
    assert down.map_point(left, frame).y() < 20
    centre = QPointF(100, 20)
    assert up.map_point(centre, frame) == centre


def test_vertical_orientation_warps_across_the_other_axis():
    frame = QRectF(0, 0, 200, 40)
    h = TextWarp(style="flag", bend=60)
    v = TextWarp(style="flag", bend=60, horizontal=False)
    p = QPointF(50, 30)
    assert h.map_point(p, frame).x() == pytest.approx(50)    # horizontal: moves up/down
    assert v.map_point(p, frame).y() == pytest.approx(30)    # vertical: moves sideways


def test_map_path_stays_curved_and_closed(qapp):
    path = QPainterPath()
    path.addRect(QRectF(10, 10, 100, 20))
    out = TextWarp(style="arc", bend=50).map_path(path, QRectF(0, 0, 120, 40))
    types = {out.elementAt(i).type for i in range(out.elementCount())}
    assert QPainterPath.ElementType.CurveToElement in types          # not a polyline
    poly = out.toSubpathPolygons()
    assert len(poly) == 1 and poly[0].isClosed()


# ── model / layout ───────────────────────────────────────────────────────────

def test_text_data_keeps_the_warp():
    d = _data(warp=TextWarp(style="bulge", bend=35))
    back = TextData.from_dict(d.to_dict())
    assert back.warp == d.warp
    assert TextData.from_dict(_data().to_dict()).warp == TextWarp()
    assert _data().to_dict()["warp"] is None                        # nothing written when off
    assert d.copy().warp == d.warp


def test_layout_can_ignore_the_warp(qapp):
    d = _data(warp=TextWarp(style="arc", bend=80))
    assert layout_text(d, warped=False).outline() == layout_text(_data()).outline()
    assert layout_text(d).outline() != layout_text(_data()).outline()


def test_warped_text_layer_bounds_outline_and_hit(qapp):
    layer = TextLayer("T", 400, 200)
    layer.set_data(_data(warp=TextWarp(style="arc", bend=90)))
    plain = TextLayer("P", 400, 200)
    plain.set_data(_data())
    assert layer.content_bounds().height() > plain.content_bounds().height()
    outline = text_outline_in_document(layer.data())
    assert outline.boundingRect().height() > text_outline_in_document(plain.data()).boundingRect().height()
    # The far end of the arc is clickable.
    end = outline.boundingRect().bottomRight() - QPointF(2, 2)
    assert layer.contains_doc_point(end, tolerance=6)


def test_warped_text_survives_save_and_load(qapp, tmp_path):
    from core.serialization import load_document, save_document
    doc = Document(300, 150)
    layer = doc.add_layer(name="T", layer_cls=TextLayer)
    layer.set_data(_data(warp=TextWarp(style="wave", bend=-30, vdist=12)))
    path = str(tmp_path / "w.imfn")
    save_document(doc, path)
    loaded, _ = load_document(path)
    t = [l for l in loaded.layers if isinstance(l, TextLayer)][0]
    assert t.data().warp == TextWarp(style="wave", bend=-30, vdist=12)


# ── the command ──────────────────────────────────────────────────────────────

def _doc_with_text(w):
    w._add_tab(Document(300, 150), "t")
    doc = w._document
    layer = doc.add_layer(name="T", layer_cls=TextLayer)
    layer.set_data(_data())
    doc.active_layer_index = doc.layers.index(layer)
    return doc, layer


def _fake_dialog(monkeypatch, warp, accept=True):
    import ui.warp_text_dialog as mod

    class Fake:
        def __init__(self, initial, on_change, parent=None):
            self._on_change = on_change
            on_change(warp)                       # the user moves a slider: live preview

        def exec(self):
            return accept

        def warp(self):
            return warp
    monkeypatch.setattr(mod, "WarpTextDialog", Fake)


def test_warp_command_applies_with_one_undo_step(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with_text(w)
    _fake_dialog(monkeypatch, TextWarp(style="arch", bend=40))
    before = len(w._history._undo_stack)
    w._warp_text()
    assert layer.data().warp == TextWarp(style="arch", bend=40)
    assert len(w._history._undo_stack) == before + 1
    w._undo()
    assert w._document.get_active_layer().data().warp == TextWarp()


def test_warp_command_cancel_restores_the_text(main_window, mocked_dialogs, monkeypatch):
    w = main_window
    doc, layer = _doc_with_text(w)
    before = layer.text_data
    _fake_dialog(monkeypatch, TextWarp(style="arch", bend=40), accept=False)
    w._warp_text()
    assert layer.text_data == before


def test_warp_command_needs_a_text_layer(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(50, 50), "t")
    w._warp_text()
    assert w._status.currentMessage()


def test_editor_shows_the_plain_text(main_window, mocked_dialogs):
    """Editing a warped text works on the unwarped layout, so the caret and
    the selection sit on the glyphs being typed."""
    w = main_window
    doc, layer = _doc_with_text(w)
    layer.set_data(_data(warp=TextWarp(style="arc", bend=90)))
    w._activate_tool("Text")
    session = w._canvas._text_session
    session.start(doc, layer)
    assert session.layout().outline() == layout_text(_data()).outline()
    session.commit()
    assert w._document.get_active_layer().data().warp == TextWarp(style="arc", bend=90)


def test_dialog_reports_its_values(qapp):
    from ui.warp_text_dialog import WarpTextDialog
    seen = []
    dlg = WarpTextDialog(TextWarp(style="flag", bend=20), seen.append)
    dlg._bend.valueChanged.emit(dlg._bend.value())
    assert dlg.warp() == TextWarp(style="flag", bend=20)
    dlg._style.setCurrentIndex(STYLE_KEYS.index("twist"))
    assert seen[-1].style == "twist"
