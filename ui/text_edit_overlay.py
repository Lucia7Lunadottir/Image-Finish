from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QColor, QTextOption, QTextCursor, QTextBlockFormat, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QPlainTextEdit


class TextEditOverlay(QPlainTextEdit):
    """The text tool's on-canvas editor: one real, native QPlainTextEdit —
    not a second, separately re-rendered image standing in for the text.
    What you see while typing IS Qt's own text rendering, styled to match
    the layer being edited (font, size, color, bold/italic/underline/
    strikeout, alignment, tracking, leading) via `reposition()`, called
    live from `opts_provider()` on every keystroke and options-bar change.

    This replaces an earlier design (ghost QPlainTextEdit input stacked
    under a QLabel showing a from-scratch re-render of the styled text on
    every keystroke): it looked convincing in isolation but broke down in
    real use — an opaque background box that resisted several stylesheet
    fixes, a live-update path that only actually worked when some
    unrelated repaint happened to fire, and visible stale-pixel "ghosting"
    behind shrinking text. The C# sibling app's text editor is a single
    real TextBox bound directly to the layer's style properties with the
    document layer hidden underneath — this mirrors that, for the same
    reason: one genuine rendering can't disagree with itself.

    `CanvasWidget.begin_text_edit` sets the layer being edited to
    `visible = False` for the duration, so this widget is the only thing
    showing the text on screen — no second copy to go stale or ghost.

    Stroke and drop-shadow — style options no native Qt text widget can
    render — aren't shown while editing; they still apply correctly to
    the baked pixels on commit (see ui/actions/layer_actions.py's
    `_fit_text_layer`). The C# sibling doesn't have these effects on text
    layers at all, so this is an honest "not previewed live", not a
    regression from something that used to work there too.
    """

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        # An ID selector is more specific than ui/theme.py's app-wide
        # `QWidget { background-color: ...; font-size: ...; }` rule and
        # wins the stylesheet cascade — a bare `QPlainTextEdit { ... }`
        # type selector does NOT (verified experimentally: type-vs-type
        # cascade order made the global rule win for both this widget and
        # its internal viewport() in the previous design).
        self.setObjectName("textEditOverlayInput")
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContentsMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._rebuild_stylesheet(self.font().pointSizeF(), QColor(0, 0, 0), "Sans Serif")

        # Qt's own caret is a single-color line in the layer's own text
        # color — on the canvas (arbitrary image pixels underneath, unlike
        # a normal white-page text field) that can vanish outright, e.g.
        # black text over a dark photo. Disabled (`setCursorWidth(0)`) in
        # favor of a custom-painted one below: dark outline + bright
        # accent core, like this app's own marching-ants selection outline
        # — the same "must read against any background" problem, same
        # two-tone fix.
        self.setCursorWidth(0)
        self._caret_visible = True
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._toggle_caret)
        flash_time = QApplication.cursorFlashTime()
        self._caret_timer.start(flash_time // 2 if flash_time > 0 else 500)
        self.cursorPositionChanged.connect(self._reset_caret_blink)

        self.textChanged.connect(self.reposition)

        self._on_commit = None     # callable(text: str)
        self._on_cancel = None     # callable()
        self._doc_anchor = QPoint(0, 0)
        self._vertical = False
        self._opts_provider = None    # callable() -> dict, current live tool opts
        self._keep_alive_check = None  # callable(QWidget) -> bool, see start()

        self.hide()

    def _rebuild_stylesheet(self, pt_size: float, color: QColor, family: str):
        """Rebuilt on every font/color change: font-size, font-family AND
        color *must* all live in this ID-scoped stylesheet, not via
        setFont()/setPalette() alone — any active stylesheet makes Qt
        re-resolve the widget's effective font/palette from the cascade,
        silently discarding `setFont()`/`setPalette()` for any property
        the cascade also declares. ui/theme.py's app-wide `QWidget { ...
        font-family: ...; font-size: 13px; }` rule covers exactly these
        two font properties (not bold/italic/underline — those aren't set
        anywhere in the app-wide sheet, so setFont() alone works fine for
        them), and its own `color: ...` rule covers the third. Verified
        directly each time: `self.font().family()`/`.pointSizeF()` after
        `setFont()` and `self.palette().color(Text)` after `setPalette()`
        all kept reporting the theme's defaults, not what was just set,
        until the same property was ALSO declared here."""
        size = pt_size if pt_size > 0 else 12.0
        self.setStyleSheet(
            "QPlainTextEdit#textEditOverlayInput { background: transparent; "
            "border: 1px dashed rgba(122, 162, 247, 160); padding: 0px; "
            f"font-size: {size}pt; font-family: '{family}'; "
            f"color: {color.name(QColor.NameFormat.HexArgb)}; "
            "caret-color: #7aa2f7; }"
        )
        self.viewport().setStyleSheet("background: transparent;")

    # ------------------------------------------------------------ lifecycle
    def start(self, doc_anchor: QPoint, opts_provider, initial_text: str, on_commit, on_cancel,
             vertical: bool = False, keep_alive_check=None):
        """`keep_alive_check(widget) -> bool`: focus moving to a widget this
        returns True for does NOT commit/end the edit — used for the
        Character/Paragraph panels and the Text options toolbar, which
        restyle the in-progress edit live, not steal focus and silently
        bake it with the old settings. Anything else — switching tools,
        clicking the canvas, the window losing focus — still commits."""
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._doc_anchor = QPoint(doc_anchor)
        self._opts_provider = opts_provider
        self._vertical = vertical
        self._keep_alive_check = keep_alive_check

        self.blockSignals(True)
        self.setPlainText(initial_text)
        self.blockSignals(False)

        self.reposition()
        self.show()
        self.raise_()
        self.setFocus()
        # Not select-all: a selection renders through the Highlight/
        # HighlightedText palette roles, which `reposition()` below never
        # sets (only the plain Text role) — Qt's default selection colors
        # for those roles don't relate to the chosen text color at all, so
        # re-editing existing text would open showing an unrelated,
        # "inverted"-looking color until the first keystroke collapsed the
        # selection. Placing the caret at the end matches how real text
        # tools (Photoshop, GIMP) behave when you click into existing text
        # anyway — not a fixed-size select-all field.
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def is_active(self) -> bool:
        return self._on_commit is not None or self._on_cancel is not None

    def commit(self):
        if self._on_commit is None:
            self.hide()
            return
        cb = self._on_commit
        text = self.toPlainText()
        self._stop()
        cb(text)

    def cancel(self):
        cb = self._on_cancel
        self._stop()
        if cb is not None:
            cb()
        else:
            self.hide()

    def _stop(self):
        try:
            QApplication.instance().focusChanged.disconnect(self._on_focus_changed)
        except TypeError:
            pass
        self._on_commit = None
        self._on_cancel = None
        self._opts_provider = None
        self._keep_alive_check = None
        self.hide()

    # ----------------------------------------------------------------- caret
    def _toggle_caret(self):
        self._caret_visible = not self._caret_visible
        self.viewport().update()

    def _reset_caret_blink(self):
        # Solid immediately after moving/typing, same as any normal caret
        # — only starts blinking again once the user stops.
        self._caret_visible = True
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.hasFocus() or not self._caret_visible:
            return
        rect = self.cursorRect()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        outline = QPen(QColor(0, 0, 0, 220))
        outline.setWidth(4)
        painter.setPen(outline)
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        core = QPen(QColor(122, 162, 247))
        core.setWidth(2)
        painter.setPen(core)
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        painter.end()

    # --------------------------------------------------------------- events
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.cancel()
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit()
            return
        super().keyPressEvent(ev)

    def _on_focus_changed(self, old, new):
        if new is None:
            # A modal dialog taking the OS-level keyboard focus (e.g. the
            # Character panel's color picker) makes the *application*
            # focus widget go through None during the transition — that's
            # not the user abandoning the edit. Only commit here if there
            # ISN'T a legitimate style dialog currently up.
            modal = QApplication.activeModalWidget()
            if modal is not None and self._keep_alive_check is not None and self._keep_alive_check(modal):
                return
            self.commit()
            return
        if new is self:
            return
        if self._keep_alive_check is not None and self._keep_alive_check(new):
            return
        self.commit()

    # --------------------------------------------------------------- layout
    def reposition(self):
        if self._opts_provider is None:
            return
        from core.text_layout import TextLayout, _build_font

        opts = self._opts_provider()
        text = self.toPlainText()
        zoom = max(0.05, self.canvas.zoom)

        layout = TextLayout(text or " ", opts, vertical=self._vertical)
        br = layout.bounding_rect(self._doc_anchor.x(), self._doc_anchor.y(), padding=6)

        font = _build_font(opts)
        font.setPointSizeF(max(4.0, font.pointSizeF() * zoom))

        align_map = {
            "left":    Qt.AlignmentFlag.AlignLeft,
            "center":  Qt.AlignmentFlag.AlignHCenter,
            "right":   Qt.AlignmentFlag.AlignRight,
            "justify": Qt.AlignmentFlag.AlignJustify,
        }
        qalign = align_map.get(opts.get("text_align", "left"), Qt.AlignmentFlag.AlignLeft)
        leading = float(opts.get("text_leading", 1.0)) or 1.0
        color = opts.get("text_color")
        color = QColor(color) if isinstance(color, QColor) else QColor(0, 0, 0)

        # All of this mutates the document (font, per-block alignment and
        # line-height, palette) — block signals for the whole thing so
        # `textChanged` (connected to this very method) doesn't re-enter.
        self.blockSignals(True)
        self.setFont(font)
        self._rebuild_stylesheet(font.pointSizeF(), color, opts.get("font_family", "Sans Serif"))

        self.document().setDefaultTextOption(QTextOption(qalign))
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(leading * 100.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        fmt_cursor = self.textCursor()
        fmt_cursor.select(QTextCursor.SelectionType.Document)
        fmt_cursor.mergeBlockFormat(block_fmt)
        self.blockSignals(False)

        top_left = self.canvas.to_widget(QPoint(br.left(), br.top()))
        w = max(24, int(br.width() * zoom))
        h = max(24, int(br.height() * zoom))
        self.setGeometry(int(top_left.x()), int(top_left.y()), w, h)
