from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (QColor, QPainter, QImage, QPainterPath, QPen as _QPen, QPixmap,
                         QFont, QFontMetricsF)
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                             QDialogButtonBox, QLabel)
from tools.base_tool import BaseTool
from core.locale import tr
from core.text_model import TextData
from core.layer import TextLayer
from core.text_engine import (layout_device, paint_text, qfont, text_transform,
                              text_outline_in_document, PT_TO_PX)
from ui.base_dialog import BaseDialog


# ── Compatibility helpers ────────────────────────────────────────────────────
# Older call sites (type-mask tools, the text dialog preview, other_tools
# re-exports) work with a flat options dict + anchor. They go through the
# same engine as text layers (core/text_engine.py).

def _data_from_opts(text: str, opts: dict, x: float, y: float, vertical: bool = False) -> TextData:
    data = TextData.from_options(opts, x, y, vertical=vertical)
    data.angle = float(opts.get("text_angle", 0.0) or 0.0)
    data.insert(0, text)
    return data


def _build_font(opts: dict) -> QFont:
    return qfont(TextData.from_options(opts, 0, 0).runs[0][1])


def _render_text(image, x: int, y: int, text: str, opts: dict, clip_path=None, angle: float = 0.0):
    data = _data_from_opts(text, {**opts, "text_angle": angle or opts.get("text_angle", 0.0)}, x, y)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if clip_path is not None and not clip_path.isEmpty():
        p.setClipPath(clip_path)
    p.setTransform(text_transform(data))
    paint_text(p, data)
    p.end()


def _render_text_vertical(image, x: int, y: int, text: str, opts: dict, clip_path=None):
    data = _data_from_opts(text, opts, x, y, vertical=True)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if clip_path is not None and not clip_path.isEmpty():
        p.setClipPath(clip_path)
    p.setTransform(text_transform(data))
    paint_text(p, data)
    p.end()


def _text_path_h(pos, text: str, opts: dict) -> QPainterPath:
    return text_outline_in_document(_data_from_opts(text, opts, pos.x(), pos.y()))


def _text_path_v(pos, text: str, opts: dict) -> QPainterPath:
    return text_outline_in_document(_data_from_opts(text, opts, pos.x(), pos.y(), vertical=True))


# ── Text dialog ────────────────────────────────────────────────────────────────

class _TextDialog(BaseDialog):
    _PREVIEW_H = 80
    _PREVIEW_W = 480

    def __init__(self, initial_text: str = "", opts: dict = None,
                 layer_name: str = None, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QFontComboBox, QSpinBox, QPushButton, QHBoxLayout
        title = tr("text_dlg.edit_title", name=layer_name) if layer_name else tr("text_dlg.new_title")
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self._base_opts = dict(opts) if opts else {}

        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        font_row = QHBoxLayout()
        font_row.setSpacing(6)

        self._font_combo = QFontComboBox()
        self._font_combo.setFixedWidth(300)
        self._font_combo.setCurrentFont(QFont(self._base_opts.get("font_family", "Sans Serif")))

        self._size_sp = QSpinBox()
        self._size_sp.setRange(4, 500)
        self._size_sp.setValue(int(self._base_opts.get("font_size", 24)))
        self._size_sp.setFixedWidth(60)
        self._size_sp.setSuffix(" pt")

        bold_f = QFont(); bold_f.setBold(True)
        ital_f = QFont(); ital_f.setItalic(True)

        self._btn_b = QPushButton("B")
        self._btn_b.setFont(bold_f)
        self._btn_b.setCheckable(True)
        self._btn_b.setChecked(bool(self._base_opts.get("font_bold", False)))
        self._btn_b.setFixedSize(28, 28)

        self._btn_i = QPushButton("I")
        self._btn_i.setFont(ital_f)
        self._btn_i.setCheckable(True)
        self._btn_i.setChecked(bool(self._base_opts.get("font_italic", False)))
        self._btn_i.setFixedSize(28, 28)

        font_row.addWidget(self._font_combo)
        font_row.addWidget(self._size_sp)
        font_row.addWidget(self._btn_b)
        font_row.addWidget(self._btn_i)
        font_row.addStretch()
        lo.addLayout(font_row)

        self._preview = QLabel()
        self._preview.setFixedHeight(self._PREVIEW_H)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background:#ffffff; border:1px solid #45475a; border-radius:4px;")
        lo.addWidget(self._preview)

        self._edit = QPlainTextEdit(initial_text)
        self._edit.setPlaceholderText(tr("text_dlg.placeholder"))
        lo.addWidget(self._edit, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

        self._font_combo.currentFontChanged.connect(self._update_preview)
        self._size_sp.valueChanged.connect(self._update_preview)
        self._btn_b.toggled.connect(self._update_preview)
        self._btn_i.toggled.connect(self._update_preview)
        self._edit.textChanged.connect(self._update_preview)

        self._update_preview()
        self._edit.setFocus()

    def _current_opts(self) -> dict:
        opts = dict(self._base_opts)
        opts["font_family"] = self._font_combo.currentFont().family()
        opts["font_size"]   = self._size_sp.value()
        opts["font_bold"]   = self._btn_b.isChecked()
        opts["font_italic"] = self._btn_i.isChecked()
        return opts

    def _update_preview(self, *_):
        text = self._edit.toPlainText() or tr("text_dlg.preview")
        w, h = self._PREVIEW_W, self._PREVIEW_H - 2
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(255, 255, 255))
        cur_opts = self._current_opts()
        cur_opts["font_size"] = min(cur_opts["font_size"], h - 16)
        _render_text(img, 8, 8, text, cur_opts)
        self._preview.setPixmap(QPixmap.fromImage(img))

    def get_text(self) -> str:
        return self._edit.toPlainText()

    def get_font_opts(self) -> dict:
        return {
            "font_family": self._font_combo.currentFont().family(),
            "font_size":   self._size_sp.value(),
            "font_bold":   self._btn_b.isChecked(),
            "font_italic": self._btn_i.isChecked(),
        }


# ── Text tools ─────────────────────────────────────────────────────────────────

class _BaseTypeTool(BaseTool):
    """Type tools, Photoshop-style:

    - click on existing text: edit it (caret where you clicked; drag
      selects, double-click a word, triple-click a line);
    - click on empty canvas: new point text, baseline at the click;
    - drag on empty canvas: new paragraph text in that box (wraps);
    - while editing, click outside the text commits it.

    Editing itself is ui/text_edit_session.py; this class only routes the
    mouse. `_VERTICAL` picks the orientation of *new* text — existing text
    keeps its own orientation whichever type tool edits it."""

    _VERTICAL = False
    needs_immediate_commit = False

    def __init__(self):
        self._parent_widget = None
        self._mode = None          # None | "session" | "create"
        self._drag_start = None
        self._drag_end = None

    def _session(self):
        canvas = getattr(self._parent_widget, "_canvas", None)
        return getattr(canvas, "_text_session", None) if canvas is not None else None

    @staticmethod
    def _text_layer_at(doc, pt: QPointF):
        for i in range(len(doc.layers) - 1, -1, -1):
            l = doc.layers[i]
            if not l.visible or l.locked or not isinstance(l, TextLayer):
                continue
            if l.has_live_content() and l.contains_doc_point(pt):
                return i, l
        return None, None

    def on_press(self, pos, doc, fg, bg, opts):
        session = self._session()
        if session is None:
            return
        pt = QPointF(pos)
        shift = bool(opts.get("_shift", False))
        self._mode = None
        if session.is_active():
            if session.handle_at(pt) or session.contains_doc_point(pt):
                session.mouse_press(pt, shift)
                self._mode = "session"
                return
            session.commit()
            # Clicking another text layer goes straight into editing it;
            # any other click outside just commits (Photoshop).
            idx, layer = self._text_layer_at(doc, pt)
            if layer is not None:
                self._edit_layer(session, doc, idx, layer, pt)
            return
        idx, layer = self._text_layer_at(doc, pt)
        if layer is not None:
            self._edit_layer(session, doc, idx, layer, pt)
            return
        self._mode = "create"
        self._drag_start = self._drag_end = pt

    def _edit_layer(self, session, doc, idx, layer, pt):
        doc.active_layer_index = idx
        session.start(doc, layer)
        session.mouse_press(pt)
        self._mode = "session"

    def on_move(self, pos, doc, fg, bg, opts):
        if self._mode == "session":
            session = self._session()
            if session is not None and session.is_active():
                session.mouse_move(QPointF(pos))
        elif self._mode == "create":
            self._drag_end = QPointF(pos)

    def on_release(self, pos, doc, fg, bg, opts):
        session = self._session()
        mode, self._mode = self._mode, None
        if session is None:
            return
        if mode == "session":
            if session.is_active():
                session.mouse_release(QPointF(pos))
            return
        if mode != "create":
            return
        end = QPointF(pos)
        rect = QRectF(self._drag_start, end).normalized()
        self._drag_start = self._drag_end = None
        zoom = float(opts.get("_zoom", 1.0) or 1.0)
        if rect.width() * zoom > 8 and rect.height() * zoom > 8:
            data = TextData.from_options(opts, rect.x(), rect.y(), vertical=self._VERTICAL,
                                         box=(rect.width(), rect.height()))
        else:
            data = TextData.from_options(opts, 0, 0, vertical=self._VERTICAL)
            data.x, data.y = self._point_origin(data, end)
        session.start(doc, None, data)

    @staticmethod
    def _point_origin(data: TextData, click: QPointF):
        """Point text: the click is the first baseline (horizontal) or the
        top center of the first column (vertical)."""
        style = data.runs[0][1]
        if data.vertical:
            return click.x() - style.size * PT_TO_PX * data.paragraphs[0].leading / 2, click.y()
        ascent = QFontMetricsF(qfont(style), layout_device()).ascent()
        return click.x(), click.y() - ascent

    def preview_text_box(self):
        if self._mode == "create" and self._drag_start is not None and self._drag_end is not None:
            return QRectF(self._drag_start, self._drag_end).normalized()
        return None

    def draw_overlays(self, painter, pw, doc):
        r = self.preview_text_box()
        if r is None or r.width() < 1 or r.height() < 1:
            return
        pen = _QPen(QColor(122, 162, 247), pw, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

    def needs_history_push(self) -> bool:
        # The editing session pushes its own single undo step.
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


class TextTool(_BaseTypeTool):
    name = "Text"
    icon = "T"
    shortcut = "T"
    _VERTICAL = False


class VerticalTypeTool(_BaseTypeTool):
    name = "TextV"
    icon = "Tv"
    shortcut = ""
    _VERTICAL = True


class _BaseTypeMaskTool(BaseTool):
    """Shared behaviour for HorizontalTypeMaskTool/VerticalTypeMaskTool:
    prompt for text via _TextDialog, then set doc.selection to the resulting
    type-outline path. _VERTICAL picks _text_path_h vs. _text_path_v."""

    _VERTICAL = False
    needs_immediate_commit = True

    def __init__(self):
        self._parent_widget = None

    def on_press(self, pos, doc, fg, bg, opts):
        dlg = _TextDialog("", opts, None, self._parent_widget)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.get_text().strip()
        if not text:
            return
        opts.update(dlg.get_font_opts())
        path_fn = _text_path_v if self._VERTICAL else _text_path_h
        doc.selection = path_fn(pos, text, opts)

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


class HorizontalTypeMaskTool(_BaseTypeMaskTool):
    name = "TextHMask"
    icon = "Tm"
    shortcut = ""
    _VERTICAL = False


class VerticalTypeMaskTool(_BaseTypeMaskTool):
    name = "TextVMask"
    icon = "Vm"
    shortcut = ""
    _VERTICAL = True
