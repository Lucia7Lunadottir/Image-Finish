
from core.locale import tr
from core.text_model import CHAR_OPTION_KEYS, EFFECT_OPTION_KEYS, PARAGRAPH_OPTION_KEYS, _coerce

_TEXT_KEYS = set(CHAR_OPTION_KEYS) | set(PARAGRAPH_OPTION_KEYS) | set(EFFECT_OPTION_KEYS) | {"text_vertical"}


class TextActionsMixin:
    """Glue between the text editor (ui/text_edit_session.py), the Text
    options bar, the Character/Paragraph panels and the document.

    Option changes go:
    - into the open editing session if there is one (selection-aware —
      see TextEditSession.apply_option);
    - otherwise, with a Text tool active and a text layer selected, onto
      that whole layer (one undo step per burst, like shape edits);
    - and always into tool_opts, the defaults for the next new text."""

    # ── session access ──────────────────────────────────────────────
    def _text_session(self, canvas=None):
        canvas = canvas or getattr(self, "_canvas", None)
        return getattr(canvas, "_text_session", None) if canvas is not None else None

    def _commit_text_edit_if_active(self, canvas=None) -> bool:
        """Anything that needs the document in a settled state (tool
        switch, layer selection, undo, save, closing a tab) commits an
        open text edit first."""
        session = self._text_session(canvas)
        if session is not None and session.is_active():
            session.commit()
            return True
        return False

    def _cancel_text_edit(self):
        session = self._text_session()
        if session is not None and session.is_active():
            session.cancel()

    def _apply_text_styles(self):
        """The options bar's ✓ button: commit the edit in progress."""
        self._commit_text_edit_if_active()

    # ── options ─────────────────────────────────────────────────────
    def _is_text_tool_active(self) -> bool:
        from tools.text_tool import _BaseTypeTool
        canvas = getattr(self, "_canvas", None)
        return canvas is not None and isinstance(canvas.active_tool, _BaseTypeTool)

    def _apply_text_option_live(self, key: str, value) -> bool:
        if key not in _TEXT_KEYS:
            return False
        session = self._text_session()
        if session is not None and session.is_active():
            session.apply_option(key, value)
            self._refocus_text_editor()
            return True
        if not self._is_text_tool_active() or self._document is None:
            return False
        layer = self._document.get_active_layer()
        if getattr(layer, "layer_type", "") != "text" or not layer.has_live_content():
            return False
        data = layer.data()
        from dataclasses import replace
        if key in CHAR_OPTION_KEYS:
            f = CHAR_OPTION_KEYS[key]
            data.restyle_all(**{f: _coerce(f, value)})
        elif key in PARAGRAPH_OPTION_KEYS:
            f = PARAGRAPH_OPTION_KEYS[key]
            data.restyle_all_paragraphs(**{f: _coerce(f, value)})
        elif key in EFFECT_OPTION_KEYS:
            f = EFFECT_OPTION_KEYS[key]
            data.effects = replace(data.effects, **{f: _coerce(f, value)})
        else:
            data.vertical = bool(value)
        if data.to_dict() == layer.text_data:
            return True
        self._open_shape_edit_history_session(layer, key, tr("history.edit_text"))   # same burst-coalescing undo
        layer.set_data(data)
        layer.rebake_thumbnail()
        self._canvas_refresh()
        return True

    def _refocus_text_editor(self):
        """After clicking a button/color/combo in a panel, typing should go
        back into the text — but not while the user is typing a number
        into a spin box or a font name into a combo."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit

        def _refocus():
            session = self._text_session()
            if session is None or not session.is_active():
                return
            w = QApplication.focusWidget()
            if isinstance(w, (QAbstractSpinBox, QLineEdit)) or (isinstance(w, QComboBox) and w.isEditable()):
                return
            if QApplication.activeModalWidget() is not None:
                return
            session.proxy.setFocus()
        QTimer.singleShot(0, _refocus)

    # ── panels <- text ──────────────────────────────────────────────
    def _sync_text_panels(self, opts: dict):
        canvas = getattr(self, "_canvas", None)
        if canvas is None:
            return
        canvas.tool_opts.update(opts)
        page = self._opts_bar._pages.get("Text") if hasattr(self, "_opts_bar") else None
        if page is not None and hasattr(page, "update_from_opts"):
            page.update_from_opts(canvas.tool_opts)
        if hasattr(page, "set_editing"):
            session = self._text_session()
            page.set_editing(bool(session and session.is_active()))
        for name in ("_character_panel", "_paragraph_panel"):
            panel = getattr(self, name, None)
            if panel is not None:
                panel.refresh(canvas)

    def _on_text_session_style_changed(self):
        session = self._text_session()
        if session is not None and session.is_active():
            self._sync_text_panels(session.options_at_cursor())

    def _on_text_session_finished(self):
        page = self._opts_bar._pages.get("Text") if hasattr(self, "_opts_bar") else None
        if page is not None and hasattr(page, "set_editing"):
            page.set_editing(False)
        self._refresh_layers()

    def _sync_text_options_from_layer(self, layer):
        if not self._is_text_tool_active():
            return
        if getattr(layer, "layer_type", "") != "text" or not layer.has_live_content():
            return
        data = layer.data()
        opts = data.options_at(0, len(data.text))
        opts["text_vertical"] = data.vertical
        self._sync_text_panels(opts)

    def _connect_text_session(self, canvas):
        session = self._text_session(canvas)
        if session is None:
            return
        session.style_changed.connect(self._on_text_session_style_changed)
        session.finished.connect(self._on_text_session_finished)
