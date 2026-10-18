"""The Text tool, end to end: on-canvas editing session
(ui/text_edit_session.py), text model (core/text_model.py), layout/render
engine (core/text_engine.py) and the TextLayer that renders live from it.

Replaces tests/test_text_edit_overlay.py, which covered the old
QPlainTextEdit overlay this design removed."""
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QInputMethodEvent, QKeyEvent, QTransform

from core.document import Document
from core.layer import TextLayer
from core.text_model import CharStyle, TextData
from core.text_engine import layout_text, qfont, layout_device


# ── helpers ────────────────────────────────────────────────────────────────

def _setup(w, size=(300, 200)):
    w._add_tab(Document(*size), "t")
    w._activate_tool("Text")
    return w._document, w._canvas, w._canvas._text_session


def _opts(w, **over):
    o = dict(w._canvas.tool_opts)
    o.update({"_zoom": 1.0, "_shift": False})
    o.update(over)
    return o


def _click(w, x, y, **opts):
    tool = w._canvas.active_tool
    o = _opts(w, **opts)
    tool.on_press(QPoint(x, y), w._document, QColor(0, 0, 0), QColor(255, 255, 255), o)
    tool.on_release(QPoint(x, y), w._document, QColor(0, 0, 0), QColor(255, 255, 255), o)


def _drag(w, x0, y0, x1, y1):
    tool = w._canvas.active_tool
    o = _opts(w)
    tool.on_press(QPoint(x0, y0), w._document, QColor(0, 0, 0), QColor(255, 255, 255), o)
    tool.on_move(QPoint(x1, y1), w._document, QColor(0, 0, 0), QColor(255, 255, 255), o)
    tool.on_release(QPoint(x1, y1), w._document, QColor(0, 0, 0), QColor(255, 255, 255), o)


def _key(session, key, text="", mods=Qt.KeyboardModifier.NoModifier):
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(session.proxy, QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def _type(session, s):
    for ch in s:
        if ch == "\n":
            _key(session, Qt.Key.Key_Return, "\r")
        else:
            _key(session, 0, ch)


def _text_layers(doc):
    return [l for l in doc.layers if isinstance(l, TextLayer)]


# ── creating and committing ───────────────────────────────────────────────

def test_click_type_commit_creates_one_layer_and_one_undo_step(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    undo_before = len(w._history._undo_stack)
    _click(w, 40, 60)
    assert session.is_active() and not _text_layers(doc)     # nothing until you type
    _type(session, "Hello")
    layer = _text_layers(doc)[0]
    assert layer.text_data["text"] == "Hello"
    _key(session, Qt.Key.Key_Return, "\r", Qt.KeyboardModifier.ControlModifier)   # Ctrl+Enter commits
    assert not session.is_active()
    assert len(w._history._undo_stack) == undo_before + 1
    w._undo()
    assert not _text_layers(w._document)


def test_point_text_baseline_sits_at_the_click(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 40, 100)
    _type(session, "x")
    data = _text_layers(doc)[0].data()
    ascent = __import__("PyQt6.QtGui", fromlist=["QFontMetricsF"]).QFontMetricsF(
        qfont(data.runs[0][1]), layout_device()).ascent()
    assert abs(data.y + ascent - 100) < 0.5 and data.x == 40


def test_commit_without_typing_adds_nothing(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    n = len(doc.layers)
    _click(w, 40, 60)
    session.commit()
    assert len(doc.layers) == n


def test_escape_cancels_new_text_and_leaves_no_undo_step(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    undo_before = len(w._history._undo_stack)
    _click(w, 40, 60)
    _type(session, "Gone")
    _key(session, Qt.Key.Key_Escape)
    assert not _text_layers(doc)
    assert len(w._history._undo_stack) == undo_before


def test_click_on_existing_text_edits_it_and_escape_restores_original(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 40, 60)
    _type(session, "Original")
    session.commit()
    layer = _text_layers(doc)[0]
    original = dict(layer.text_data)

    frame = layer.frame_polygon().boundingRect()
    _click(w, int(frame.center().x()), int(frame.center().y()))
    assert session.is_active() and session.layer is layer
    _type(session, "XYZ")
    assert layer.text_data["text"] != original["text"]
    _key(session, Qt.Key.Key_Escape)
    assert layer.text_data == original


def test_deleting_all_text_and_committing_removes_the_layer(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 40, 60)
    _type(session, "Bye")
    session.commit()
    layer = _text_layers(doc)[0]
    frame = layer.frame_polygon().boundingRect()
    _click(w, int(frame.center().x()), int(frame.center().y()))
    _key(session, Qt.Key.Key_A, "a", Qt.KeyboardModifier.ControlModifier)
    _key(session, Qt.Key.Key_Backspace)
    session.commit()
    assert layer not in doc.layers


def test_clicking_outside_commits(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "Hi")
    _click(w, 250, 180)
    assert not session.is_active()
    assert _text_layers(doc)[0].text_data["text"] == "Hi"


def test_tool_switch_and_layer_selection_commit(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "A")
    w._activate_tool("Brush")
    assert not session.is_active()
    w._activate_tool("Text")
    _click(w, 20, 120)
    _type(session, "B")
    w._on_layer_selected_wrap(0)
    assert not session.is_active()
    assert sorted(l.text_data["text"] for l in _text_layers(doc)) == ["A", "B"]


# ── keyboard editing ──────────────────────────────────────────────────────

def test_navigation_and_deletion_keys(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "one two\nthree")
    _key(session, Qt.Key.Key_Home)
    assert session.cursor == len("one two\n")
    _key(session, Qt.Key.Key_Up)
    assert session.cursor <= len("one two")
    _key(session, Qt.Key.Key_End, "", Qt.KeyboardModifier.ControlModifier)
    assert session.cursor == len(session.data.text)
    _key(session, Qt.Key.Key_Backspace, "", Qt.KeyboardModifier.ControlModifier)   # word
    assert session.data.text == "one two\n"
    _key(session, Qt.Key.Key_Home, "", Qt.KeyboardModifier.ControlModifier)
    _key(session, Qt.Key.Key_Delete)
    assert session.data.text == "ne two\n"


def test_shift_arrows_select_and_typing_replaces_selection(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "abcdef")
    for _ in range(3):
        _key(session, Qt.Key.Key_Left, "", Qt.KeyboardModifier.ShiftModifier)
    assert session.selected_text() == "def"
    _type(session, "X")
    assert session.data.text == "abcX"


def test_in_session_undo_redo_and_typing_coalesces(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "word")
    _key(session, Qt.Key.Key_Backspace)
    _key(session, Qt.Key.Key_Z, "", Qt.KeyboardModifier.ControlModifier)
    assert session.data.text == "word"
    _key(session, Qt.Key.Key_Z, "", Qt.KeyboardModifier.ControlModifier)
    assert session.data.text == ""          # all of the typing was one step
    _key(session, Qt.Key.Key_Z, "", Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert session.data.text == "word"


def test_proxy_claims_letter_shortcuts_while_typing(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b")
    assert session.claims_key(ev)
    session.commit()
    assert not session.claims_key(ev)


def test_clipboard_cut_paste(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "cut me")
    _key(session, Qt.Key.Key_A, "", Qt.KeyboardModifier.ControlModifier)
    _key(session, Qt.Key.Key_X, "", Qt.KeyboardModifier.ControlModifier)
    assert session.data.text == ""
    _key(session, Qt.Key.Key_V, "", Qt.KeyboardModifier.ControlModifier)
    _key(session, Qt.Key.Key_V, "", Qt.KeyboardModifier.ControlModifier)
    assert session.data.text == "cut mecut me"


def test_input_method_commit_and_preedit(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(session.proxy, QInputMethodEvent("にほ", []))
    assert session.data.text == "" and session._preedit == "にほ"
    assert "にほ" in session._display_data().text
    ev = QInputMethodEvent("", [])
    ev.setCommitString("日本")
    QApplication.sendEvent(session.proxy, ev)
    assert session.data.text == "日本" and session._preedit == ""


# ── styling ───────────────────────────────────────────────────────────────

def test_options_apply_to_selection_only(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "Hello world")
    session.anchor, session.cursor = 6, 11
    w._on_opt_changed("font_bold", True)
    w._on_opt_changed("text_color", QColor(255, 0, 0))
    data = session.data
    assert not data.style_at(3).bold and data.style_at(8).bold
    assert QColor(data.style_at(8).color).red() == 255 and QColor(data.style_at(3).color).red() == 0


def test_option_at_bare_caret_styles_what_you_type_next(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "ab")
    w._on_opt_changed("font_size", 48)
    _type(session, "C")
    assert session.data.style_at(2).size != 48 and session.data.style_at(3).size == 48


def test_ctrl_b_toggles_bold_on_selection(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "bold")
    _key(session, Qt.Key.Key_A, "", Qt.KeyboardModifier.ControlModifier)
    _key(session, Qt.Key.Key_B, "", Qt.KeyboardModifier.ControlModifier)
    assert session.data.style_at(2).bold


def test_panels_follow_the_caret(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "plain bold")
    session.anchor, session.cursor = 6, 10
    w._on_opt_changed("font_bold", True)
    session._set_cursor(8, False)
    page = w._opts_bar.page_for("Text")
    assert page._btn_b.isChecked()
    session._set_cursor(2, False)
    assert not page._btn_b.isChecked()


def test_options_without_editing_apply_to_the_selected_text_layer(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "Whole")
    session.commit()
    layer = _text_layers(doc)[0]
    w._on_opt_changed("font_italic", True)
    w._on_opt_changed("text_align", "center")
    data = layer.data()
    assert data.style_at(1).italic and data.style_at(5).italic
    assert data.paragraph.align == "center"


def test_paragraph_indents_and_spacing_move_lines(main_window):
    data = TextData(text="one\ntwo", runs=[(7, CharStyle())])
    base = layout_text(data)
    from dataclasses import replace
    data.restyle_all_paragraphs(indent_left=10, space_before=20)
    moved = layout_text(data)
    assert moved.lines[0].dx > base.lines[0].dx
    assert moved.lines[1].top > base.lines[1].top + 20


# ── paragraph text box ────────────────────────────────────────────────────

def test_drag_creates_wrapping_paragraph_text_and_handles_resize_it(main_window):
    w = main_window
    doc, canvas, session = _setup(w, (400, 300))
    _drag(w, 20, 20, 140, 200)
    assert session.data.box == (120, 180)
    _type(session, "several words that will not fit on one line")
    lay = session.layout()
    assert len(lay.lines) > 1
    assert all(l.qline.naturalTextWidth() <= 120.5 for l in lay.lines)
    lines_before = len(lay.lines)
    br = session.transform().map(QPointF(120, 180))
    assert session.handle_at(br) == "br"
    session.mouse_press(br)
    session.mouse_move(QPointF(370, 200))
    session.mouse_release(QPointF(370, 200))
    assert session.data.box[0] > 300
    assert len(session.layout().lines) < lines_before


# ── vertical text ─────────────────────────────────────────────────────────

def test_vertical_text_tool_and_arrow_keys_follow_columns(main_window):
    w = main_window
    w._add_tab(Document(300, 300), "t")
    w._activate_tool("TextV")
    session = w._canvas._text_session
    _click(w, 150, 30)
    assert session.data.vertical
    _type(session, "abc\ndef")
    _key(session, Qt.Key.Key_Up)                      # back along the column
    assert session.cursor == len("abc\nde")
    _key(session, Qt.Key.Key_Right)                   # previous column (to the right)
    assert session.cursor <= len("abc")


# ── rendering ─────────────────────────────────────────────────────────────

def _text_doc(text="Sharp", **style):
    doc = Document(200, 100)
    doc.layers[0].image.fill(QColor(0, 0, 0, 0))
    layer = TextLayer("t", 200, 100)
    data = TextData(text=text, runs=[(len(text), CharStyle(size=36, **style))], x=10, y=10)
    layer.set_data(data)
    layer.rebake_thumbnail()
    doc.layers.append(layer)
    return doc, layer


def test_text_is_sharp_in_the_zoomed_view():
    doc, layer = _text_doc("O")
    scale = 8
    view = doc.render_view(QTransform.fromScale(scale, scale), QSize(200 * scale, 100 * scale))
    magnified = doc.get_composite().scaled(200 * scale, 100 * scale)
    b = layer.content_bounds()
    y = int((b.top() + b.height() / 2) * scale)
    def partial(img):
        return sum(1 for x in range(int(b.left() * scale), int(b.center().x() * scale))
                   if 0 < img.pixelColor(x, y).alpha() < 255)
    assert partial(view) <= 4
    assert partial(magnified) >= scale


def test_text_respects_layer_order():
    doc, layer = _text_doc("M")
    cover = doc.add_layer(name="cover")
    cover.image.fill(QColor("#00ff00"))
    c = layer.content_bounds().center()
    assert doc.get_composite().pixelColor(int(c.x()), int(c.y())).getRgb()[:3] == (0, 255, 0)


def test_stroke_and_shadow_render():
    doc, layer = _text_doc("I")
    data = layer.data()
    from dataclasses import replace
    data.effects = replace(data.effects, stroke_width=4, stroke_color="#ff0000ff",
                           shadow=True, shadow_dx=10, shadow_dy=0, shadow_color="#ffff0000")
    layer.set_data(data)
    comp = doc.get_composite()
    ink = layer.text_layout().ink_bounds().translated(10, 10)
    cy = int(ink.center().y())
    row = [comp.pixelColor(x, cy) for x in range(200)]
    first = next(x for x, c in enumerate(row) if c.alpha() > 200)
    first_black = next(x for x, c in enumerate(row) if c.alpha() > 200 and c.blue() < 60 and c.red() < 60)
    assert row[first].blue() > 150                    # outermost ink is the stroke color
    assert first_black - first >= 3                   # ~4px of stroke before the glyph fill
    last = max(x for x, c in enumerate(row) if c.alpha() > 200)
    assert row[last].red() > 150                      # shadow sticks out to the right


def test_legacy_text_data_still_renders_and_moves_scale_font_size():
    from PyQt6.QtGui import QTransform as T
    layer = TextLayer("old", 200, 100)
    layer.text_data = {"text": "Hi", "x": 30, "y": 40, "font_size": 24,
                       "text_color": QColor(255, 0, 0), "text_stroke_w": 2}
    assert layer.has_live_content()
    data = layer.data()
    assert data.runs[0][1].size == 24 and data.effects.stroke_width == 2
    layer.move_tool_apply_extra(Document(200, 100), T().translate(5, 0).scale(2, 2), QRectF(), layer.image)
    moved = layer.data()
    assert moved.runs[0][1].size == 48
    assert moved.x == 65   # (30 * 2) + 5


def test_text_roundtrips_through_save(tmp_path):
    from core.serialization import save_document, load_document
    doc, layer = _text_doc("Saved")
    data = layer.data()
    data.restyle(0, 2, bold=True, color="#ff00ff00")
    data.box = (150, 60)
    layer.set_data(data)
    path = str(tmp_path / "t.imfn")
    save_document(doc, path)
    doc2, _ = load_document(path)
    l2 = [l for l in doc2.layers if isinstance(l, TextLayer)][0]
    d2 = l2.data()
    assert d2.text == "Saved" and d2.style_at(1).bold and not d2.style_at(4).bold
    assert d2.box == (150, 60)


def test_rasterize_keeps_the_text_pixels(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 60)
    _type(session, "Raster")
    session.commit()
    layer = _text_layers(doc)[0]
    before = doc.get_composite().copy()
    doc.active_layer_index = doc.layers.index(layer)
    w._rasterize_layer()
    after = w._document.get_composite()
    diff = sum(1 for x in range(0, 300, 3) for y in range(0, 200, 3)
               if before.pixelColor(x, y) != after.pixelColor(x, y))
    assert diff < 5


def test_paragraph_settings_are_per_paragraph(main_window):
    w = main_window
    doc, canvas, session = _setup(w)
    _click(w, 20, 40)
    _type(session, "first\nsecond\nthird")
    session._set_cursor(len("first\nsec"), False)       # caret in the 2nd paragraph
    w._on_opt_changed("text_align", "right")
    paras = session.data.paragraphs
    assert [p.align for p in paras] == ["left", "right", "left"]
    session.anchor, session.cursor = 0, len(session.data.text)
    w._on_opt_changed("para_space_before", 12)
    assert all(p.space_before == 12 for p in session.data.paragraphs)
    page = w._opts_bar.page_for("Text")
    session._set_cursor(len("first\nsec"), False)
    assert w._canvas.tool_opts["text_align"] == "right"     # panels follow the caret's paragraph


def test_splitting_and_merging_paragraphs_keeps_their_styles():
    from core.text_model import TextData, CharStyle
    data = TextData(text="ab\ncd", runs=[(5, CharStyle())])
    data.restyle_paragraphs(4, 4, align="center")
    assert [p.align for p in data.paragraphs] == ["left", "center"]
    data.insert(4, "\nX")                                # split the 2nd paragraph
    assert [p.align for p in data.paragraphs] == ["left", "center", "center"]
    data.delete(1, 4)                                     # merge 1st with the rest of 2nd
    assert [p.align for p in data.paragraphs] == ["left", "center"]
    assert TextData.from_dict(data.to_dict()).paragraphs == data.paragraphs


def test_first_version_layer_wide_paragraph_still_loads():
    from core.text_model import TextData
    old = {"version": 2, "text": "a\nb", "runs": [[3, {}]], "paragraph": {"align": "center"}}
    assert [p.align for p in TextData.from_dict(old).paragraphs] == ["center", "center"]
