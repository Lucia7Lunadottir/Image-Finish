"""On-canvas text editing for the Text tools.

Replaces the old TextEditOverlay (a native QPlainTextEdit laid over the
canvas). That approach could never show what the layer will really look
like — no stroke, no shadow, horizontal-only, one style for the whole
layer, Qt's own text rendering instead of the layer's. Here the text you
edit IS the layer: every keystroke edits the layer's TextData and the
layer renders itself; this module only adds what an editor needs on top —
caret, selection, the paragraph-text frame with its handles, and input.

Pieces:
- `TextInputProxy`: an invisible focus widget on the canvas that receives
  keys and input-method (IME) events and claims shortcut keys while
  typing, so typing "B" inserts a B instead of switching to the Brush.
- `TextEditSession`: the editing state (TextData, caret, selection, the
  in-session undo stack) and every operation on it. Mouse input arrives
  from the Text tool (tools/text_tool.py); painting is called from the
  canvas paint loop.

Responsiveness: while typing, the layer is hidden from the document
composite and painted by the session at screen resolution (cheap — no
recomposite per keystroke). Once typing pauses, the layer goes back into
the composite so it's shown in its real place in the layer stack.

History: one document undo step per editing session, pushed lazily right
before the first change; Cancel (Esc) restores the original and removes
that step again.
"""
import re
from dataclasses import replace

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPolygonF, QTransform
from PyQt6.QtWidgets import QApplication, QWidget

from core.locale import tr
from core.text_engine import layout_text, paint_text, text_transform
from core.text_model import (CHAR_OPTION_KEYS, EFFECT_OPTION_KEYS, PARAGRAPH_OPTION_KEYS,
                             TextData, _coerce)

_FAST_MODE_IDLE_MS = 300
_HANDLE_PX = 8
_ACCENT = QColor(122, 162, 247)
_HANDLE_NAMES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
_WORD = re.compile(r"\w", re.UNICODE)


class TextInputProxy(QWidget):
    """Keyboard + IME receiver for the editing session (see module doc)."""

    def __init__(self, canvas, session: "TextEditSession"):
        super().__init__(canvas)
        self._session = session
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.resize(1, 1)
        self.hide()

    def event(self, ev):
        if ev.type() == QEvent.Type.ShortcutOverride and self._session.claims_key(ev):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        # Never let a key fall through to the canvas while typing: its
        # handlers would start the Alt-eyedropper (AltGr on many keyboard
        # layouts), Space-panning, zoom keys... Real shortcuts (Ctrl+S, ...)
        # aren't affected — Qt fires those before the key press arrives.
        self._session.key_press(ev)
        ev.accept()

    def keyReleaseEvent(self, ev):
        ev.accept()

    def inputMethodEvent(self, ev):
        self._session.input_method(ev)
        ev.accept()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return QRectF(self._session.caret_widget_rect().translated(-self.pos().x(), -self.pos().y()))
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        return super().inputMethodQuery(query)

    def paintEvent(self, ev):
        pass


class TextEditSession(QObject):
    """See module docstring. `canvas` is the CanvasWidget; the main window
    (canvas.window()) supplies history and panel refreshes."""

    style_changed = pyqtSignal()      # caret/selection style changed -> sync panels
    finished = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.proxy = TextInputProxy(canvas, self)
        self._reset_state()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._leave_fast_mode)
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._toggle_caret)
        self._caret_on = True
        self._click_count = 0
        self._last_click = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)

    def _reset_state(self):
        self.doc = None
        self.layer = None           # TextLayer once materialized
        self.data: TextData | None = None
        self._original = None       # text_data dict of an existing layer, for Cancel
        self._is_new = False
        self._history_state = None
        self.cursor = 0
        self.anchor = 0
        self._pending = None        # CharStyle for the next typed text at a bare caret
        self._x_hint = None
        self._undo = []
        self._redo = []
        self._typing_run = False
        self._preedit = ""
        self._layout = None
        self._layout_for = None
        self._dragging = False
        self._resizing = None
        self._fast = False

    # ── lifecycle ───────────────────────────────────────────────────
    def is_active(self) -> bool:
        return self.data is not None

    def start(self, doc, layer=None, data: TextData | None = None, cursor_at: QPointF | None = None):
        """Edit `layer` (an existing TextLayer) or start new text from
        `data` (not added to the document until the first keystroke)."""
        if self.is_active():
            self.commit()
        self.doc = doc
        if layer is not None:
            self.layer = layer
            self._original = layer.text_data
            self.data = layer.data()
            self._is_new = False
        else:
            self.data = data
            self._is_new = True
        self.cursor = self.anchor = len(self.data.text)
        if cursor_at is not None:
            self.cursor = self.anchor = self.hit_doc(cursor_at)
        self.proxy.show()
        self.proxy.setFocus()
        self._blink.start(max(250, QApplication.cursorFlashTime() // 2 or 500))
        self._after_move()

    def commit(self):
        if not self.is_active():
            return
        layer, doc, data = self.layer, self.doc, self.data
        self._end_ui()
        if layer is not None and layer in doc.layers:
            if not data.text.strip():
                # Empty text isn't a layer (Photoshop discards it too).
                doc.remove_layer(doc.layers.index(layer))
            else:
                layer.set_data(data)
                layer._live_edit_hidden = False
                layer.rebake_thumbnail()
        self._finish()

    def cancel(self):
        if not self.is_active():
            return
        layer, doc = self.layer, self.doc
        self._end_ui()
        if layer is not None and layer in doc.layers:
            if self._is_new:
                doc.layers.remove(layer)
                doc.active_layer_index = max(0, min(doc.active_layer_index, len(doc.layers) - 1))
            else:
                layer.text_data = self._original
                layer._live_edit_hidden = False
                layer.rebake_thumbnail()
            win = self.canvas.window()
            history = getattr(win, "_history", None)
            if history is not None and self._history_state is not None and hasattr(history, "discard"):
                history.discard(self._history_state)
        self._finish()

    def _end_ui(self):
        self._idle.stop()
        self._blink.stop()
        self.proxy.hide()
        self.proxy.clearFocus()

    def _finish(self):
        if self.doc is not None:
            self.doc.invalidate_composite()
        self._reset_state()
        win = self.canvas.window()
        self.canvas.invalidate_cache()
        if hasattr(win, "_refresh_layers"):
            win._refresh_layers()
        self.canvas.document_changed.emit()
        self.finished.emit()
        self.canvas.update()

    # ── model change plumbing ───────────────────────────────────────
    def layout(self):
        shown = self._display_data()
        key = (id(shown), shown.text, tuple(shown.runs), tuple(shown.paragraphs), shown.effects,
               shown.box, shown.vertical, shown.x, shown.y, shown.angle)
        if self._layout_for != key:
            self._layout = layout_text(shown)
            self._layout_for = key
        return self._layout

    def _display_data(self) -> TextData:
        if not self._preedit:
            return self.data
        shown = self.data.copy()
        a, b = self._sel()
        if a != b:
            shown.delete(a, b)
        shown.insert(a, self._preedit, self._insert_style())
        return shown

    def _snapshot(self, kind: str = "edit"):
        """Push an in-session undo step (consecutive typing coalesces)."""
        if kind == "type" and self._typing_run:
            return
        self._undo.append((self.data.to_dict(), self.cursor, self.anchor))
        self._redo.clear()
        self._typing_run = kind == "type"

    def _ensure_materialized(self):
        """Right before the first change: the document undo step, and for
        new text the layer itself."""
        if self._history_state is not None:
            return
        win = self.canvas.window()
        if hasattr(win, "_make_history_state") and getattr(win, "_history", None) is not None:
            desc = tr("history.add_text") if self._is_new else tr("history.edit_text")
            idx = None if self._is_new else (self.doc.layers.index(self.layer) if self.layer in self.doc.layers else None)
            self._history_state = win._make_history_state(desc, idx)
            win._history.push(self._history_state)
        else:
            self._history_state = object()   # no window (tests): still mark as started
        if self.layer is None:
            from core.layer import TextLayer
            self.layer = TextLayer(self.doc.next_layer_name(TextLayer, "layer.name.text"),
                                   self.doc.width, self.doc.height)
            self.layer.set_data(self.data)
            self.doc.layers.append(self.layer)
            self.doc.active_layer_index = len(self.doc.layers) - 1
            if hasattr(win, "_refresh_layers"):
                win._refresh_layers()

    def _changed(self):
        self._ensure_materialized()
        self.layer.set_data(self.data)
        self.doc.invalidate_composite()
        self._enter_fast_mode()
        self._after_move()

    def _enter_fast_mode(self):
        if self.layer is None:
            return
        if not self._fast:
            self._fast = True
            self.layer._live_edit_hidden = True
            self.canvas.invalidate_cache()
        self._idle.start(_FAST_MODE_IDLE_MS)
        self.canvas.update()

    def _leave_fast_mode(self):
        if self.layer is None or self._preedit:
            return
        self._fast = False
        self.layer._live_edit_hidden = False
        self.layer.rebake_thumbnail()
        self.doc.invalidate_composite()
        self.canvas.invalidate_cache()
        win = self.canvas.window()
        panel = getattr(win, "_layers_panel", None)
        if panel is not None and hasattr(panel, "refresh_active_thumbnail"):
            panel.refresh_active_thumbnail(self.doc)

    def _after_move(self):
        self._caret_on = True
        self.canvas.update()
        self._place_proxy()
        self.style_changed.emit()

    # ── geometry ────────────────────────────────────────────────────
    def transform(self) -> QTransform:
        return text_transform(self.data)

    def view_transform(self) -> QTransform:
        c = self.canvas
        return QTransform(c.zoom, 0, 0, c.zoom, c._pan.x(), c._pan.y())

    def _to_local(self, doc_pt) -> QPointF:
        inv, _ = self.transform().inverted()
        return inv.map(QPointF(doc_pt))

    def hit_doc(self, doc_pt) -> int:
        return self.layout().hit(self._to_local(doc_pt))

    def contains_doc_point(self, doc_pt, tolerance_px: float = 6.0) -> bool:
        tol = tolerance_px / max(0.01, self.canvas.zoom)
        lay = self.layout()
        r = lay.bounds().united(lay.ink_bounds()).adjusted(-tol, -tol, tol, tol)
        return r.contains(self._to_local(doc_pt))

    def caret_widget_rect(self) -> QRect:
        line = self.layout().caret_line(self._caret_display_pos())
        m = self.transform() * self.view_transform()
        poly = m.map(QPolygonF([line.p1(), line.p2()]))
        return poly.boundingRect().toAlignedRect().adjusted(-1, -1, 1, 1)

    def _caret_display_pos(self) -> int:
        return min(self._sel()) + len(self._preedit) if self._preedit else self.cursor

    def _place_proxy(self):
        if self.is_active():
            r = self.caret_widget_rect()
            self.proxy.move(r.topLeft())
            QGuiApplication.inputMethod().update(Qt.InputMethodQuery.ImCursorRectangle)

    # ── selection helpers ───────────────────────────────────────────
    def _sel(self):
        return min(self.cursor, self.anchor), max(self.cursor, self.anchor)

    def has_selection(self) -> bool:
        return self.cursor != self.anchor

    def selected_text(self) -> str:
        a, b = self._sel()
        return self.data.text[a:b]

    def _set_cursor(self, pos: int, extend: bool, keep_hint: bool = False):
        pos = max(0, min(len(self.data.text), pos))
        self.cursor = pos
        if not extend:
            self.anchor = pos
        if not keep_hint:
            self._x_hint = None
        self._pending = None
        self._typing_run = False
        self._after_move()

    def select_all(self):
        self.anchor, self.cursor = 0, len(self.data.text)
        self._after_move()

    def _word_bounds(self, pos: int):
        t = self.data.text
        a = b = max(0, min(pos, len(t)))
        while a > 0 and _WORD.match(t[a - 1]):
            a -= 1
        while b < len(t) and _WORD.match(t[b]):
            b += 1
        if a == b and b < len(t):
            b += 1
        return a, b

    def _word_left(self, pos: int) -> int:
        t = self.data.text
        while pos > 0 and not _WORD.match(t[pos - 1]):
            pos -= 1
        while pos > 0 and _WORD.match(t[pos - 1]):
            pos -= 1
        return pos

    def _word_right(self, pos: int) -> int:
        t = self.data.text
        while pos < len(t) and _WORD.match(t[pos]):
            pos += 1
        while pos < len(t) and not _WORD.match(t[pos]):
            pos += 1
        return pos

    # ── editing ─────────────────────────────────────────────────────
    def _insert_style(self):
        if self._pending is not None:
            return self._pending
        a, _ = self._sel()
        return self.data.style_at(a)

    def insert_text(self, s: str):
        if not s:
            return
        self._snapshot("type" if len(s) == 1 and s != "\n" else "edit")
        style = self._insert_style()
        a, b = self._sel()
        if a != b:
            self.data.delete(a, b)
        self.data.insert(a, s, style)
        self.cursor = self.anchor = a + len(s)
        self._pending = None
        self._x_hint = None
        self._changed()

    def delete_selection(self) -> bool:
        a, b = self._sel()
        if a == b:
            return False
        self._snapshot()
        self.data.delete(a, b)
        self.cursor = self.anchor = a
        self._changed()
        return True

    def backspace(self, word: bool = False):
        if self.delete_selection() or self.cursor == 0:
            return
        start = self._word_left(self.cursor) if word else self.cursor - 1
        self._snapshot()
        self.data.delete(start, self.cursor)
        self.cursor = self.anchor = start
        self._changed()

    def delete_forward(self, word: bool = False):
        if self.delete_selection() or self.cursor >= len(self.data.text):
            return
        end = self._word_right(self.cursor) if word else self.cursor + 1
        self._snapshot()
        self.data.delete(self.cursor, end)
        self._changed()

    def undo(self):
        if not self._undo:
            return
        self._redo.append((self.data.to_dict(), self.cursor, self.anchor))
        state, self.cursor, self.anchor = self._undo.pop()
        self.data = TextData.from_dict(state)
        self._typing_run = False
        self._changed()

    def redo(self):
        if not self._redo:
            return
        self._undo.append((self.data.to_dict(), self.cursor, self.anchor))
        state, self.cursor, self.anchor = self._redo.pop()
        self.data = TextData.from_dict(state)
        self._typing_run = False
        self._changed()

    def copy(self):
        if self.has_selection():
            QApplication.clipboard().setText(self.selected_text())

    def cut(self):
        self.copy()
        self.delete_selection()

    def paste(self):
        text = QApplication.clipboard().text()
        if text:
            self.insert_text(text.replace("\r\n", "\n").replace("\r", "\n"))

    # ── styling (panels / options bar) ──────────────────────────────
    def apply_option(self, key: str, value) -> bool:
        """Character options apply to the selection (or to what's typed
        next at a bare caret); paragraph options and effects to the whole
        layer — Photoshop's rules."""
        if key in CHAR_OPTION_KEYS:
            f = CHAR_OPTION_KEYS[key]
            v = _coerce(f, value)
            a, b = self._sel()
            if a != b:
                self._snapshot()
                self.data.restyle(a, b, **{f: v})
                self._changed()
            elif not self.data.text:
                self.data.restyle_all(**{f: v})
                self._changed()
            else:
                self._pending = replace(self._insert_style(), **{f: v})
                self._after_move()
            return True
        if key in PARAGRAPH_OPTION_KEYS:   # the caret's / selection's paragraphs
            self._snapshot()
            f = PARAGRAPH_OPTION_KEYS[key]
            a, b = self._sel()
            self.data.restyle_paragraphs(a, b, **{f: _coerce(f, value)})
            self._changed()
            return True
        if key in EFFECT_OPTION_KEYS:
            self._snapshot()
            f = EFFECT_OPTION_KEYS[key]
            self.data.effects = replace(self.data.effects, **{f: _coerce(f, value)})
            self._changed()
            return True
        if key == "text_vertical":
            self._snapshot()
            self.data.vertical = bool(value)
            self._changed()
            return True
        return False

    def options_at_cursor(self) -> dict:
        a, b = self._sel()
        opts = self.data.options_at(a, b)
        if self._pending is not None and a == b:
            for key, f in CHAR_OPTION_KEYS.items():
                opts[key] = getattr(self._pending, f)
            opts["text_color"] = QColor(self._pending.color)
        opts["text_vertical"] = self.data.vertical
        return opts

    def _toggle_style(self, field: str):
        current = self.options_at_cursor()
        key = next(k for k, f in CHAR_OPTION_KEYS.items() if f == field)
        self.apply_option(key, not current[key])

    # ── keyboard ────────────────────────────────────────────────────
    _EDIT_KEYS = {Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                  Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
                  Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Tab}
    _CTRL_KEYS = {Qt.Key.Key_A, Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V, Qt.Key.Key_Z,
                  Qt.Key.Key_Y, Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U}

    def claims_key(self, ev) -> bool:
        if not self.is_active():
            return False
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ev.key() in self._EDIT_KEYS:
            return True
        if ctrl:
            return ev.key() in self._CTRL_KEYS
        return bool(ev.text()) and ev.text().isprintable()

    def key_press(self, ev) -> bool:
        if not self.is_active():
            return False
        key, mods = ev.key(), ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        vertical = self.data.vertical
        K = Qt.Key

        if key == K.Key_Escape:
            self.cancel()
        elif key == K.Key_Enter and (mods & Qt.KeyboardModifier.KeypadModifier) or \
                key in (K.Key_Return, K.Key_Enter) and ctrl:
            self.commit()
        elif key in (K.Key_Return, K.Key_Enter):
            self.insert_text("\n")
        elif key == K.Key_Backspace:
            self.backspace(word=ctrl)
        elif key == K.Key_Delete:
            self.delete_forward(word=ctrl)
        elif key in (K.Key_Left, K.Key_Right, K.Key_Up, K.Key_Down):
            self._arrow(key, ctrl, shift, vertical)
        elif key == K.Key_Home:
            self._set_cursor(0 if ctrl else self.layout().line_range(self.cursor)[0], shift)
        elif key == K.Key_End:
            self._set_cursor(len(self.data.text) if ctrl else self.layout().line_range(self.cursor)[1], shift)
        elif ctrl and key == K.Key_A:
            self.select_all()
        elif ctrl and key == K.Key_C:
            self.copy()
        elif ctrl and key == K.Key_X:
            self.cut()
        elif ctrl and key == K.Key_V:
            self.paste()
        elif ctrl and key == K.Key_Z:
            self.redo() if shift else self.undo()
        elif ctrl and key == K.Key_Y:
            self.redo()
        elif ctrl and key == K.Key_B:
            self._toggle_style("bold")
        elif ctrl and key == K.Key_I:
            self._toggle_style("italic")
        elif ctrl and key == K.Key_U:
            self._toggle_style("underline")
        elif key == K.Key_Tab:
            self.insert_text("\t")
        elif ev.text() and ev.text().isprintable() and not ctrl:
            self.insert_text(ev.text())
        else:
            return False
        return True

    def _arrow(self, key, ctrl, shift, vertical):
        K = Qt.Key
        along_back, along_fwd = (K.Key_Up, K.Key_Down) if vertical else (K.Key_Left, K.Key_Right)
        if key in (along_back, along_fwd):
            back = key == along_back
            if not shift and self.has_selection():
                a, b = self._sel()
                self._set_cursor(a if back else b, False)
                return
            if ctrl:
                pos = self._word_left(self.cursor) if back else self._word_right(self.cursor)
            else:
                pos = self.cursor - 1 if back else self.cursor + 1
            self._set_cursor(pos, shift)
            return
        # across lines: down = next line (horizontal); left = next column (vertical)
        step = 1 if key in ((K.Key_Left,) if vertical else (K.Key_Down,)) else -1
        pos, self._x_hint = self.layout().move_line(self.cursor, step, self._x_hint)
        self._set_cursor(pos, shift, keep_hint=True)

    # ── input method ────────────────────────────────────────────────
    def input_method(self, ev):
        commit = ev.commitString()
        self._preedit = ev.preeditString()
        if commit:
            self.insert_text(commit)
        if self._preedit:
            self._ensure_materialized()
            self._enter_fast_mode()
        else:
            self._idle.start(_FAST_MODE_IDLE_MS)
        self._after_move()

    # ── mouse (from the Text tool) ──────────────────────────────────
    def handle_at(self, doc_pt) -> str | None:
        if not self.data or not self.data.box:
            return None
        m = self.transform() * self.view_transform()
        wp = self.view_transform().map(QPointF(doc_pt))
        for name, local in self._handle_points().items():
            hp = m.map(local)
            if abs(hp.x() - wp.x()) <= _HANDLE_PX and abs(hp.y() - wp.y()) <= _HANDLE_PX:
                return name
        return None

    def _handle_points(self) -> dict:
        w, h = self.data.box
        xs = {"l": 0, "c": w / 2, "r": w}
        ys = {"t": 0, "m": h / 2, "b": h}
        return {"tl": QPointF(xs["l"], ys["t"]), "t": QPointF(xs["c"], ys["t"]), "tr": QPointF(xs["r"], ys["t"]),
                "r": QPointF(xs["r"], ys["m"]), "br": QPointF(xs["r"], ys["b"]), "b": QPointF(xs["c"], ys["b"]),
                "bl": QPointF(xs["l"], ys["b"]), "l": QPointF(xs["l"], ys["m"])}

    def mouse_press(self, doc_pt, shift: bool = False):
        handle = self.handle_at(doc_pt)
        if handle:
            self._snapshot()
            self._resizing = (handle, QRectF(0, 0, *self.data.box), self.transform())
            return
        now_pt = QPointF(doc_pt)
        if (self._click_timer.isActive() and self._last_click is not None
                and abs(self._last_click.x() - now_pt.x()) * self.canvas.zoom < 5
                and abs(self._last_click.y() - now_pt.y()) * self.canvas.zoom < 5):
            self._click_count += 1
        else:
            self._click_count = 1
        self._last_click = now_pt
        self._click_timer.start(QApplication.doubleClickInterval())

        pos = self.hit_doc(doc_pt)
        if self._click_count == 2:
            a, b = self._word_bounds(pos)
            self.anchor, self.cursor = a, b
            self._after_move()
        elif self._click_count >= 3:
            a, b = self.layout().line_range(pos)
            self.anchor, self.cursor = a, b
            self._after_move()
        else:
            self._set_cursor(pos, shift)
            self._dragging = True
        self.proxy.setFocus()

    def mouse_move(self, doc_pt):
        if self._resizing:
            self._resize_box(doc_pt)
        elif self._dragging:
            self._set_cursor(self.hit_doc(doc_pt), True)

    def mouse_release(self, doc_pt):
        self._dragging = False
        if self._resizing:
            self._resizing = None
            self._leave_fast_mode()
        self.proxy.setFocus()

    def _resize_box(self, doc_pt):
        name, orig, t = self._resizing
        inv, _ = t.inverted()
        p = inv.map(QPointF(doc_pt))
        r = QRectF(orig)
        if "l" in name: r.setLeft(min(p.x(), r.right() - 10))
        if "r" in name: r.setRight(max(p.x(), r.left() + 10))
        if name in ("t", "tl", "tr"): r.setTop(min(p.y(), r.bottom() - 10))
        if name in ("b", "bl", "br"): r.setBottom(max(p.y(), r.top() + 10))
        origin = t.map(r.topLeft())
        self.data.x, self.data.y = origin.x(), origin.y()
        self.data.box = (r.width(), r.height())
        self._changed()

    # ── painting (canvas paint loop, widget coordinates) ────────────
    def _toggle_caret(self):
        self._caret_on = not self._caret_on
        self.canvas.update()

    def paint(self, painter: QPainter):
        if not self.is_active():
            return
        lay = self.layout()
        m = self.transform() * self.view_transform()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._fast or self.layer is None or self.layer._live_edit_hidden:
            painter.setTransform(m)
            if self.layer is not None:
                painter.setOpacity(self.layer.opacity)
            paint_text(painter, self._display_data(), lay)
            painter.setOpacity(1.0)

        painter.setTransform(QTransform())
        # frame
        frame = m.map(QPolygonF(lay.bounds()))
        pen = QPen(QColor(0, 0, 0, 160), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(frame)
        pen = QPen(_ACCENT, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPolygon(frame)
        if self.data.box:
            painter.setPen(QPen(QColor(20, 20, 30), 1))
            painter.setBrush(_ACCENT)
            for p in self._handle_points().values():
                hp = m.map(p)
                painter.drawRect(QRectF(hp.x() - _HANDLE_PX / 2, hp.y() - _HANDLE_PX / 2, _HANDLE_PX, _HANDLE_PX))

        # selection
        a, b = self._sel()
        if a != b:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 90))
            for r in lay.selection_rects(a, b):
                painter.drawPolygon(m.map(QPolygonF(r)))

        # IME pre-edit underline
        if self._preedit:
            start = a
            painter.setPen(QPen(_ACCENT, 2))
            for r in lay.selection_rects(start, start + len(self._preedit)):
                poly = m.map(QPolygonF(r))
                painter.drawLine(poly[3], poly[2])

        # caret: dark outline + bright core, readable on any background
        if self._caret_on and not self.has_selection():
            line = lay.caret_line(self._caret_display_pos())
            p1, p2 = m.map(line.p1()), m.map(line.p2())
            painter.setPen(QPen(QColor(0, 0, 0, 220), 4))
            painter.drawLine(p1, p2)
            painter.setPen(QPen(_ACCENT, 2))
            painter.drawLine(p1, p2)
        painter.restore()
