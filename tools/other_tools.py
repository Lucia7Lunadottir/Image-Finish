from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QImage, QPainterPath
from tools.base_tool import BaseTool


# ═══════════════════════════════════════════════ SelectTool
class SelectTool(BaseTool):
    """
    Прямоугольное выделение:

      • Drag вне выделения      → новое выделение
      • Shift+drag              → добавить к выделению (union)
      • Ctrl+drag               → вычесть из выделения (subtract)
      • Drag ВНУТРИ выделения   → переместить контур выделения (пиксели не трогаем)
    """
    name = "Select"
    icon = "⬜"
    shortcut = "M"

    def __init__(self):
        self._start:            QPoint       | None = None
        self._drag_end:         QPoint       | None = None
        self._mode:             str                 = "new"  # "new"|"add"|"sub"|"move"
        self._move_origin:      QPoint       | None = None
        self._move_origin_path: QPainterPath | None = None
        self._drag_base_path:   QPainterPath | None = None

    @staticmethod
    def _path_from_rect(r: QRect) -> QPainterPath:
        p = QPainterPath()
        p.addRect(QRectF(r))
        return p

    # ── press ─────────────────────────────────────────────────────────────────
    def on_press(self, pos, doc, fg, bg, opts):
        sel     = doc.selection
        shift   = bool(opts.get("_shift", False))
        ctrl    = bool(opts.get("_ctrl",  False))
        has_sel = sel and not sel.isEmpty()

        # Клик ВНУТРИ существующего выделения → двигаем контур
        if has_sel and sel.contains(QPointF(pos)):
            self._mode             = "move"
            self._move_origin      = pos
            self._move_origin_path = QPainterPath(sel)
            return

        # Drag вне выделения
        if shift and has_sel:
            self._mode           = "add"
            self._drag_base_path = QPainterPath(sel)
        elif ctrl and has_sel:
            self._mode           = "sub"
            self._drag_base_path = QPainterPath(sel)
        else:
            self._mode           = "new"
            self._drag_base_path = None
            doc.selection        = QPainterPath()
        self._start    = pos
        self._drag_end = pos

    # ── move ──────────────────────────────────────────────────────────────────
    def on_move(self, pos, doc, fg, bg, opts):
        if self._mode == "move" and self._move_origin and self._move_origin_path:
            delta = pos - self._move_origin
            doc.selection = self._move_origin_path.translated(delta.x(), delta.y())
            return

        if self._start:
            self._drag_end = pos
            drag_path = self._path_from_rect(QRect(self._start, pos).normalized())
            if self._mode == "add" and self._drag_base_path:
                doc.selection = self._drag_base_path.united(drag_path)
            elif self._mode == "sub" and self._drag_base_path:
                doc.selection = self._drag_base_path.subtracted(drag_path)
            else:
                doc.selection = drag_path

    # ── release ───────────────────────────────────────────────────────────────
    def on_release(self, pos, doc, fg, bg, opts):
        self._start = self._drag_end = None
        self._move_origin = self._move_origin_path = None
        self._drag_base_path = None
        self._mode = "new"

    def sub_drag_rect(self) -> QRect | None:
        """Прямоугольник вычитания во время Ctrl+drag, для отрисовки в canvas."""
        if self._mode == "sub" and self._start and self._drag_end:
            return QRect(self._start, self._drag_end).normalized()
        return None

    def needs_history_push(self) -> bool:
        return False  # SelectTool пиксели не меняет

    def cursor(self):
        return Qt.CursorShape.CrossCursor


# ═══════════════════════════════════════════════ MoveTool
class MoveTool(BaseTool):
    """
    Без выделения  → двигает весь активный слой.
    С выделением   → вырезает выделенные пиксели и тащит их (с превью).
    """
    name = "Move"
    icon = "✋"
    shortcut = "V"

    def __init__(self):
        self._last:         QPoint       | None = None
        self._floating:     QImage       | None = None
        self._floating_pos: QPoint       | None = None
        self._sel_origin:   QPainterPath | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        self._last = pos
        sel = doc.selection
        if not (sel and not sel.isEmpty()):
            return  # нет выделения — двигаем слой целиком

        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return

        br = sel.boundingRect().toRect()
        # Копируем выделенную область, маскируем по форме
        self._floating = layer.image.copy(br)
        local_sel = sel.translated(-br.x(), -br.y())
        full = QPainterPath()
        full.addRect(QRectF(self._floating.rect()))
        outside = full.subtracted(local_sel)
        mp = QPainter(self._floating)
        mp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        mp.setClipPath(outside)
        mp.fillRect(self._floating.rect(), QColor(0, 0, 0, 0))
        mp.end()

        # Вырезаем из слоя
        p = QPainter(layer.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setClipPath(sel)
        p.fillRect(br, QColor(0, 0, 0, 0))
        p.end()

        self._floating_pos = br.topLeft()
        self._sel_origin   = QPainterPath(sel)

    def on_move(self, pos, doc, fg, bg, opts):
        if not self._last:
            return
        delta = pos - self._last
        self._last = pos

        if self._floating is not None:
            # Двигаем floating + выделение
            self._floating_pos = self._floating_pos + delta
            doc.selection = self._sel_origin.translated(
                self._floating_pos.x() - self._sel_origin.boundingRect().x(),
                self._floating_pos.y() - self._sel_origin.boundingRect().y(),
            )
        else:
            layer = doc.get_active_layer()
            if layer:
                layer.offset = layer.offset + delta

    def on_release(self, pos, doc, fg, bg, opts):
        if self._floating is not None and self._floating_pos is not None:
            layer = doc.get_active_layer()
            if layer:
                p = QPainter(layer.image)
                p.drawImage(self._floating_pos, self._floating)
                p.end()
            self._floating     = None
            self._floating_pos = None
            self._sel_origin   = None
        self._last = None

    def floating_preview(self):
        if self._floating is not None and self._floating_pos is not None:
            return (self._floating, self._floating_pos)
        return None

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.SizeAllCursor


# ═══════════════════════════════════════════════ EyedropperTool
class EyedropperTool(BaseTool):
    name = "Eyedropper"
    icon = "💉"
    shortcut = "I"

    color_picked_callback = None

    def on_press(self, pos, doc, fg, bg, opts):
        composite = doc.get_composite()
        x, y = pos.x(), pos.y()
        if 0 <= x < composite.width() and 0 <= y < composite.height():
            picked = QColor(composite.pixel(x, y))
            picked.setAlpha(255)
            if callable(self.color_picked_callback):
                self.color_picked_callback(picked)

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor


# ═══════════════════════════════════════════════ CropTool
class CropTool(BaseTool):
    name = "Crop"
    icon = "✂️"
    shortcut = "C"

    def __init__(self):
        self._start: QPoint | None = None
        self.pending_rect: QRect | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        self._start = pos
        self.pending_rect = None

    def on_move(self, pos, doc, fg, bg, opts):
        if self._start:
            self.pending_rect = QRect(self._start, pos).normalized()

    def on_release(self, pos, doc, fg, bg, opts):
        if self._start:
            self.pending_rect = QRect(self._start, pos).normalized()
        self._start = None

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor


# ═══════════════════════════════════════════════ TextTool
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                             QDialogButtonBox, QLabel, QSizePolicy)
from PyQt6.QtGui import QFont, QFontMetrics, QBrush, QPen as _QPen, QPixmap


class _TextDialog(QDialog):
    """Диалог ввода многострочного текста с выбором шрифта и превью."""
    _PREVIEW_H = 80
    _PREVIEW_W = 480

    def __init__(self, initial_text: str = "", opts: dict = None,
                 layer_name: str = None, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QFontComboBox, QSpinBox, QPushButton, QHBoxLayout
        title = f"Редактировать: {layer_name}" if layer_name else "Новый текст"
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self._base_opts = dict(opts) if opts else {}   # локальная копия для превью

        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        # ── Строка шрифта ──────────────────────────────────────────────────
        font_row = QHBoxLayout()
        font_row.setSpacing(6)

        self._font_combo = QFontComboBox()
        self._font_combo.setFixedWidth(300)
        self._font_combo.setCurrentFont(
            QFont(self._base_opts.get("font_family", "Sans Serif")))

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

        # ── Превью ─────────────────────────────────────────────────────────
        self._preview = QLabel()
        self._preview.setFixedHeight(self._PREVIEW_H)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background:#ffffff; border:1px solid #45475a; border-radius:4px;")
        lo.addWidget(self._preview)

        # ── Редактор текста ────────────────────────────────────────────────
        self._edit = QPlainTextEdit(initial_text)
        self._edit.setPlaceholderText("Введите текст (Enter — новая строка)…")
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
        """Объединяет базовые opts с текущими значениями контролов диалога."""
        opts = dict(self._base_opts)
        opts["font_family"] = self._font_combo.currentFont().family()
        opts["font_size"]   = self._size_sp.value()
        opts["font_bold"]   = self._btn_b.isChecked()
        opts["font_italic"] = self._btn_i.isChecked()
        return opts

    def _update_preview(self, *_):
        text = self._edit.toPlainText() or "Предпросмотр"
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
        """Возвращает параметры шрифта, выбранные в диалоге."""
        return {
            "font_family": self._font_combo.currentFont().family(),
            "font_size":   self._size_sp.value(),
            "font_bold":   self._btn_b.isChecked(),
            "font_italic": self._btn_i.isChecked(),
        }


def _build_font(opts: dict) -> QFont:
    font = QFont(opts.get("font_family", "Sans Serif"),
                 int(opts.get("font_size", 24)))
    font.setBold(bool(opts.get("font_bold", False)))
    font.setItalic(bool(opts.get("font_italic", False)))
    font.setUnderline(bool(opts.get("font_underline", False)))
    font.setStrikeOut(bool(opts.get("font_strikeout", False)))
    return font


def _render_text(image, x: int, y: int, text: str, opts: dict, clip_path=None):
    """Рендерит текст на image начиная с (x, y) по настройкам opts."""
    font        = _build_font(opts)
    metrics     = QFontMetrics(font)
    line_h      = metrics.lineSpacing()
    lines       = text.split("\n")

    text_color   = opts.get("text_color",       QColor(0, 0, 0))
    stroke_w     = int(opts.get("text_stroke_w",   0))
    stroke_color = opts.get("text_stroke_color", QColor(0, 0, 0))
    shadow       = bool(opts.get("text_shadow",  False))
    shadow_color = opts.get("text_shadow_color", QColor(0, 0, 0, 160))
    sdx          = int(opts.get("text_shadow_dx", 3))
    sdy          = int(opts.get("text_shadow_dy", 3))

    def make_path(dx=0, dy=0) -> QPainterPath:
        path = QPainterPath()
        baseline = metrics.ascent()
        for i, line in enumerate(lines):
            if line:
                path.addText(x + dx, y + dy + baseline + i * line_h, font, line)
        return path

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if clip_path and not clip_path.isEmpty():
        painter.setClipPath(clip_path)

    if shadow:
        painter.fillPath(make_path(sdx, sdy), QBrush(shadow_color))

    main_path = make_path()
    if stroke_w > 0:
        pen = _QPen(stroke_color, stroke_w * 2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(main_path, pen)

    painter.fillPath(main_path, QBrush(text_color))
    painter.end()


class TextTool(BaseTool):
    """
    Клик на пустом месте    → диалог → новый слой с текстом.
    Клик при активном text-слое → диалог повторного редактирования.
    """
    name = "Text"
    icon = "T"
    shortcut = "T"

    needs_immediate_commit = True  # создаёт слой в on_press, не нужен on_release

    def __init__(self):
        self._parent_widget = None

    def on_press(self, pos, doc, fg, bg, opts):
        layer    = doc.get_active_layer()
        re_edit  = layer and getattr(layer, "text_data", None) is not None
        layer_name = layer.name if re_edit else None

        initial = layer.text_data.get("text", "") if re_edit else ""
        dlg     = _TextDialog(initial, opts, layer_name, self._parent_widget)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.get_text().strip()
        if not text:
            return

        # Применяем шрифт, выбранный прямо в диалоге
        opts.update(dlg.get_font_opts())

        if re_edit:
            # Перерисовываем существующий текстовый слой
            layer.image.fill(Qt.GlobalColor.transparent)
            td = layer.text_data
            _render_text(layer.image, td["x"], td["y"], text, opts,
                         doc.selection if (doc.selection and not doc.selection.isEmpty()) else None)
            layer.text_data = {**td, "text": text, **self._snap_opts(opts)}
        else:
            # Новый слой для текста
            from core.layer import Layer as _Layer
            n = sum(1 for l in doc.layers if l.text_data) + 1
            new_layer = _Layer(f"Text {n}", doc.width, doc.height)
            _render_text(new_layer.image, pos.x(), pos.y(), text, opts,
                         doc.selection if (doc.selection and not doc.selection.isEmpty()) else None)
            new_layer.text_data = {"text": text, "x": pos.x(), "y": pos.y(),
                                   **self._snap_opts(opts)}
            doc.layers.append(new_layer)
            doc.active_layer_index = len(doc.layers) - 1

    @staticmethod
    def _snap_opts(opts: dict) -> dict:
        """Сохраняем настройки текста в text_data слоя."""
        return {k: opts[k] for k in (
            "font_family", "font_size", "font_bold", "font_italic",
            "font_underline", "font_strikeout",
            "text_color", "text_stroke_w", "text_stroke_color",
            "text_shadow", "text_shadow_color", "text_shadow_dx", "text_shadow_dy",
        ) if k in opts}

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.IBeamCursor


# ═══════════════════════════════════════════════ ShapesTool
from PyQt6.QtGui import QPen, QBrush


class ShapesTool(BaseTool):
    name = "Shapes"
    icon = "🔷"
    shortcut = "U"

    def __init__(self):
        self._start: QPoint | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        self._start = pos

    def on_move(self, pos, doc, fg, bg, opts):
        pass

    def on_release(self, pos, doc, fg, bg, opts):
        if not self._start:
            return
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            self._start = None
            return

        rect  = QRect(self._start, pos).normalized()
        size  = int(opts.get("brush_size", 3))
        shape = opts.get("shape_type", "rect")

        painter = QPainter(layer.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if doc.selection and not doc.selection.isEmpty():
            painter.setClipPath(doc.selection)
        painter.setPen(QPen(fg, size))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        if shape == "ellipse":
            painter.drawEllipse(rect)
        else:
            painter.drawRect(rect)
        painter.end()
        self._start = None

    def cursor(self):
        return Qt.CursorShape.CrossCursor
