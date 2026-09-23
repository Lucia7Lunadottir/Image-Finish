from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import (QColor, QPainter, QImage, QPainterPath,
                         QFont, QFontMetrics, QBrush, QPen as _QPen, QPixmap)
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                             QDialogButtonBox, QLabel)
from tools.base_tool import BaseTool
from core.locale import tr
from core.text_layout import TextLayout, _build_font


# ── Font/layout helpers ──────────────────────────────────────────────────────
# All the actual per-line metrics/alignment/leading/tracking math lives in
# core.text_layout.TextLayout — one engine shared by rendering, bounding-box
# hit-testing and type-mask path generation, horizontal and vertical alike.
# These are thin, signature-compatible wrappers kept here since the rest of
# the app (ui/text_edit_overlay.py, ui/main_window.py, tools/move_tool.py,
# tools/other_tools.py) imports them from `tools.text_tool`.

def _text_bounding_rect(td: dict, padding: int = 4):
    """QRect bounding box of text from text_data (layer coordinates);
    `td["y"]` is the top of the block, not the first line's baseline."""
    text = td.get("text", "")
    if not text:
        return None
    x, y = int(td.get("x", 0)), int(td.get("y", 0))
    return TextLayout(text, td).bounding_rect(x, y, padding)


def _text_bounding_rect_vertical(td: dict, padding: int = 4):
    """Same as `_text_bounding_rect` but for the vertical column layout
    (one text line per column, one character per row)."""
    text = td.get("text", "")
    if not text:
        return None
    x, y = int(td.get("x", 0)), int(td.get("y", 0))
    return TextLayout(text, td, vertical=True).bounding_rect(x, y, padding)


def _render_text(image, x: int, y: int, text: str, opts: dict, clip_path=None, angle: float = 0.0):
    if angle and not opts.get("text_angle"):
        opts = {**opts, "text_angle": angle}
    TextLayout(text, opts).draw(image, x, y, clip_path)


def _render_text_vertical(image, x: int, y: int, text: str, opts: dict, clip_path=None):
    TextLayout(text, opts, vertical=True).draw(image, x, y, clip_path)


def _text_path_h(pos, text: str, opts: dict) -> QPainterPath:
    return TextLayout(text, opts).to_qpainter_path(pos.x(), pos.y())


def _text_path_v(pos, text: str, opts: dict) -> QPainterPath:
    return TextLayout(text, opts, vertical=True).to_qpainter_path(pos.x(), pos.y())


# ── Text dialog ────────────────────────────────────────────────────────────────

class _TextDialog(QDialog):
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

class TextTool(BaseTool):
    name = "Text"
    icon = "T"
    shortcut = "T"
    # The overlay commits asynchronously on its own schedule, not on this
    # mouse press — see needs_history_push().
    needs_immediate_commit = False

    def __init__(self):
        self._parent_widget = None

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        re_edit = False

        # Hit-test: find text layer under cursor by actual pixels
        from core.document import Document as _Document
        pos_pt = pos if isinstance(pos, QPoint) else pos.toPoint()
        for i in range(len(doc.layers) - 1, -1, -1):
            l = doc.layers[i]
            if not l.visible or l.locked: continue
            if getattr(l, "layer_type", "raster") != "text": continue
            if l.image.isNull(): continue
            br = _Document._nontransparent_bounds(l.image)
            if not br.isEmpty():
                check = br.adjusted(-4, -4, 4, 4).translated(l.offset)
                if check.contains(pos_pt):
                    doc.active_layer_index = i
                    layer = l
                    re_edit = True
                    break

        canvas = getattr(self._parent_widget, "_canvas", None)
        if canvas is None:
            return

        if re_edit:
            td = layer.text_data
            anchor = QPoint(int(td.get("x", 0)), int(td.get("y", 0)))
            canvas.begin_text_edit(doc, layer, td.get("text", ""), anchor, vertical=False)
        else:
            canvas.begin_text_edit(doc, None, "", pos_pt, vertical=False)

    @staticmethod
    def _snap_opts(opts: dict) -> dict:
        return {k: opts[k] for k in (
            "font_family", "font_size", "font_bold", "font_italic",
            "font_underline", "font_strikeout",
            "text_color", "text_stroke_w", "text_stroke_color",
            "text_shadow", "text_shadow_color", "text_shadow_dx", "text_shadow_dy",
            "text_angle", "text_align", "font_tracking", "text_leading",
        ) if k in opts}

    def needs_history_push(self) -> bool:
        # The on-canvas editor owns its own undo push on commit (see
        # MainWindow._commit_text_edit), since a typing session isn't
        # bounded by a single mouse press/release like a brush stroke.
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


class VerticalTypeTool(BaseTool):
    name = "TextV"
    icon = "Tv"
    shortcut = ""
    needs_immediate_commit = False

    def __init__(self):
        self._parent_widget = None

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        re_edit = False

        # Hit-test: find vertical text layer under cursor by actual pixels
        from core.document import Document as _Document
        pos_pt = pos if isinstance(pos, QPoint) else pos.toPoint()
        for i in range(len(doc.layers) - 1, -1, -1):
            l = doc.layers[i]
            if not l.visible or l.locked: continue
            if getattr(l, "layer_type", "raster") != "text": continue
            td = getattr(l, "text_data", None)
            if not td or not td.get("vertical", False): continue
            if l.image.isNull(): continue
            br = _Document._nontransparent_bounds(l.image)
            if not br.isEmpty():
                check = br.adjusted(-4, -4, 4, 4).translated(l.offset)
                if check.contains(pos_pt):
                    doc.active_layer_index = i
                    layer = l
                    re_edit = True
                    break

        canvas = getattr(self._parent_widget, "_canvas", None)
        if canvas is None:
            return

        if re_edit:
            td = layer.text_data
            anchor = QPoint(int(td.get("x", 0)), int(td.get("y", 0)))
            canvas.begin_text_edit(doc, layer, td.get("text", ""), anchor, vertical=True)
        else:
            canvas.begin_text_edit(doc, None, "", pos_pt, vertical=True)

    def needs_history_push(self):
        # See TextTool.needs_history_push — the on-canvas editor commits
        # its own undo state.
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


class HorizontalTypeMaskTool(BaseTool):
    name = "TextHMask"
    icon = "Tm"
    shortcut = ""
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
        doc.selection = _text_path_h(pos, text, opts)

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


class VerticalTypeMaskTool(BaseTool):
    name = "TextVMask"
    icon = "Vm"
    shortcut = ""
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
        doc.selection = _text_path_v(pos, text, opts)

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.IBeamCursor
