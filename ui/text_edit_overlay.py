from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPlainTextEdit


class _GhostTextEdit(QPlainTextEdit):
    """The actual keyboard/cursor/IME input surface. Its own glyphs are
    drawn faint (not hidden entirely, so the caret stays visually
    anchored) — the accurate, fully-styled text lives in the QLabel
    beneath it, see TextEditOverlay."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; "
            "border: 1px dashed rgba(122, 162, 247, 160); padding: 0px; }"
        )
        self.setContentsMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self._owner.cancel()
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._owner.commit()
            return
        super().keyPressEvent(ev)


class TextEditOverlay(QWidget):
    """The text-tool caret lives directly on the canvas instead of a
    separate panel.

    Two stacked children, both sized to exactly the rendered text's own
    bounding box (the same metrics `_render_text`/`_render_text_vertical`
    bake with) — never a fixed or manually resizable box:

    - `_preview` (QLabel, behind): shows the *actual* baked-pixel output —
      font, color, bold/italic/underline/strikeout, stroke and drop
      shadow — re-rendered through the exact same function used for the
      final commit, on every keystroke and every options-bar change. This
      is the real dynamic preview; nothing here is decorative.
    - `_input` (QPlainTextEdit, on top): captures keyboard/IME/cursor.
      Its own text is drawn faint so it doesn't double up visually with
      the accurate preview underneath, but its caret stays visible.

    Font/size/color/stroke/shadow all come live from the Text tool's
    options-bar controls (`opts_provider`) — there is no separate font UI
    here to feel like "yet another panel."
    """

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas

        self._preview = QLabel(self)
        self._preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._input = _GhostTextEdit(self)
        self._input.textChanged.connect(self.reposition)

        self._on_commit = None    # callable(text: str)
        self._on_cancel = None    # callable()
        self._doc_anchor = QPoint(0, 0)
        self._vertical = False
        self._opts_provider = None  # callable() -> dict, current live tool opts

        self.hide()

    # ------------------------------------------------------------ lifecycle
    def start(self, doc_anchor: QPoint, opts_provider, initial_text: str, on_commit, on_cancel, vertical: bool = False):
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._doc_anchor = QPoint(doc_anchor)
        self._opts_provider = opts_provider
        self._vertical = vertical

        self._input.blockSignals(True)
        self._input.setPlainText(initial_text)
        self._input.blockSignals(False)

        self.reposition()
        self.show()
        self.raise_()
        self._input.setFocus()
        cursor = self._input.textCursor()
        cursor.select(cursor.SelectionType.Document)
        self._input.setTextCursor(cursor)

        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def is_active(self) -> bool:
        return self._on_commit is not None or self._on_cancel is not None

    def commit(self):
        if self._on_commit is None:
            self.hide()
            return
        cb = self._on_commit
        text = self._input.toPlainText()
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
        self.hide()

    # Thin forwarding so callers (and tests) can treat this like a text field.
    def setPlainText(self, text: str):
        self._input.setPlainText(text)

    def toPlainText(self) -> str:
        return self._input.toPlainText()

    # --------------------------------------------------------------- events
    def _on_focus_changed(self, old, new):
        if new is None or not self.isAncestorOf(new):
            self.commit()

    # --------------------------------------------------------------- layout
    def reposition(self):
        if self._opts_provider is None:
            return
        from tools.text_tool import (_build_font, _render_text, _render_text_vertical,
                                     _text_bounding_rect, _text_bounding_rect_vertical)

        opts = self._opts_provider()
        text = self._input.toPlainText()
        zoom = max(0.05, self.canvas.zoom)

        td = {**opts, "text": text or " ", "x": self._doc_anchor.x(), "y": self._doc_anchor.y()}
        bounds_fn = _text_bounding_rect_vertical if self._vertical else _text_bounding_rect
        br = bounds_fn(td, padding=6) or QRect(self._doc_anchor.x(), self._doc_anchor.y(), 60, 40)

        # The real, fully-styled render (stroke/shadow/underline/etc. all
        # honored) — this is what actually gets baked on commit, drawn
        # here on every change so the preview is never stale or fake.
        img = QImage(max(1, br.width()), max(1, br.height()), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        if text:
            render = _render_text_vertical if self._vertical else _render_text
            render(img, self._doc_anchor.x() - br.left(), self._doc_anchor.y() - br.top(), text, opts)
        pix = QPixmap.fromImage(img)
        w = max(24, int(br.width() * zoom))
        h = max(24, int(br.height() * zoom))
        if zoom != 1.0:
            pix = pix.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(pix)

        # Faint ghost text in the input layer, just for cursor/IME feedback.
        f = _build_font(opts)
        f.setPointSizeF(max(4.0, f.pointSize() * zoom))
        self._input.blockSignals(True)
        self._input.setFont(f)
        self._input.blockSignals(False)
        pal = self._input.palette()
        base_color = opts.get("text_color")
        ghost = QColor(base_color) if isinstance(base_color, QColor) else QColor(0, 0, 0)
        ghost.setAlpha(70)
        pal.setColor(pal.ColorRole.Text, ghost)
        self._input.setPalette(pal)

        top_left = self.canvas.to_widget(QPoint(br.left(), br.top()))
        self.setGeometry(int(top_left.x()), int(top_left.y()), w, h)
        self._preview.setGeometry(0, 0, w, h)
        self._input.setGeometry(0, 0, w, h)
