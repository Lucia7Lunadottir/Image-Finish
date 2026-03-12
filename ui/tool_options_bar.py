from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel,
                             QSlider, QSpinBox, QComboBox, QStackedWidget,
                             QPushButton, QFontComboBox, QColorDialog, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("optLabel")
    return lbl


def _hslider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(value)
    s.setFixedWidth(120)
    return s


class ToolOptionsBar(QWidget):
    """
    Context-sensitive options bar displayed below the menu bar.
    Each tool has its own panel shown via a QStackedWidget.
    """

    option_changed        = pyqtSignal(str, object)  # (key, value)
    apply_styles_requested = pyqtSignal()            # re-render active text layer

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolOptionsBar")
        self.setFixedHeight(42)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 0, 10, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)   # stretch=1 → занимает всю ширину бара

        self._pages: dict[str, QWidget] = {}
        self._size_spins: dict[str, QSpinBox] = {}
        self._build_pages()

    # ---------------------------------------------------------------- Build
    def _build_pages(self):
        self._add_brush_page()
        self._add_eraser_page()
        self._add_fill_page()
        self._add_select_page()
        self._add_shapes_page()
        self._add_text_page()
        self._add_empty_page("Move")
        self._add_empty_page("Eyedropper")
        self._add_crop_page()
        self._add_effect_page("Blur",    "Blur")
        self._add_effect_page("Sharpen", "Sharpen")
        self._add_effect_page("Smudge",  "Smudge")

    def _row(self, *widgets) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(10)
        for ww in widgets:
            lo.addWidget(ww)
        return w

    def _add_brush_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(10)

        # Size
        self._brush_size_slider = _hslider(1, 500, 10)
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 500)
        self._brush_size_spin.setValue(10)
        self._brush_size_slider.valueChanged.connect(self._brush_size_spin.setValue)
        self._brush_size_spin.valueChanged.connect(self._brush_size_slider.setValue)
        self._brush_size_spin.valueChanged.connect(
            lambda v: self.option_changed.emit("brush_size", v))

        # Opacity
        self._brush_op_slider = _hslider(1, 100, 100)
        self._brush_op_spin = QSpinBox()
        self._brush_op_spin.setRange(1, 100)
        self._brush_op_spin.setValue(100)
        self._brush_op_spin.setSuffix("%")
        self._brush_op_slider.valueChanged.connect(self._brush_op_spin.setValue)
        self._brush_op_spin.valueChanged.connect(self._brush_op_slider.setValue)
        self._brush_op_spin.valueChanged.connect(
            lambda v: self.option_changed.emit("brush_opacity", v / 100))

        # Hardness
        hard_sl = _hslider(0, 100, 100)
        hard_sp = QSpinBox()
        hard_sp.setRange(0, 100)
        hard_sp.setValue(100)
        hard_sp.setSuffix("%")
        hard_sl.valueChanged.connect(hard_sp.setValue)
        hard_sp.valueChanged.connect(hard_sl.setValue)
        hard_sp.valueChanged.connect(
            lambda v: self.option_changed.emit("brush_hardness", v / 100))

        # Mask
        mask_combo = QComboBox()
        mask_combo.addItems(["Round", "Square", "Scatter"])
        mask_combo.currentTextChanged.connect(
            lambda t: self.option_changed.emit("brush_mask", t.lower()))

        lo.addWidget(_label("Size:"))
        lo.addWidget(self._brush_size_slider)
        lo.addWidget(self._brush_size_spin)
        lo.addWidget(_label("Opacity:"))
        lo.addWidget(self._brush_op_slider)
        lo.addWidget(self._brush_op_spin)
        lo.addWidget(_label("Hard:"))
        lo.addWidget(hard_sl)
        lo.addWidget(hard_sp)
        lo.addWidget(_label("Mask:"))
        lo.addWidget(mask_combo)
        lo.addStretch()

        self._size_spins["Brush"] = self._brush_size_spin
        self._stack.addWidget(page)
        self._pages["Brush"] = page

    def _add_eraser_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(14)

        sl = _hslider(1, 200, 20)
        sp = QSpinBox()
        sp.setRange(1, 200)
        sp.setValue(20)
        sl.valueChanged.connect(sp.setValue)
        sp.valueChanged.connect(sl.setValue)
        sp.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        lo.addWidget(_label("Size:"))
        lo.addWidget(sl)
        lo.addWidget(sp)
        lo.addStretch()

        self._size_spins["Eraser"] = sp
        self._stack.addWidget(page)
        self._pages["Eraser"] = page

    def _add_fill_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(14)

        sl = _hslider(0, 255, 32)
        sp = QSpinBox()
        sp.setRange(0, 255)
        sp.setValue(32)
        sl.valueChanged.connect(sp.setValue)
        sp.valueChanged.connect(sl.setValue)
        sp.valueChanged.connect(lambda v: self.option_changed.emit("fill_tolerance", v))

        lo.addWidget(_label("Tolerance:"))
        lo.addWidget(sl)
        lo.addWidget(sp)
        lo.addStretch()

        self._stack.addWidget(page)
        self._pages["Fill"] = page

    def _add_select_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(_label("Rectangular Marquee  —  drag to select"))
        lo.addStretch()
        self._stack.addWidget(page)
        self._pages["Select"] = page

    def _add_shapes_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(14)

        combo = QComboBox()
        combo.addItems(["Rectangle", "Ellipse"])
        combo.currentTextChanged.connect(
            lambda t: self.option_changed.emit("shape_type",
                                               "rect" if t == "Rectangle" else "ellipse"))

        sl = _hslider(1, 50, 2)
        sp = QSpinBox()
        sp.setRange(1, 50)
        sp.setValue(2)
        sl.valueChanged.connect(sp.setValue)
        sp.valueChanged.connect(sl.setValue)
        sp.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        lo.addWidget(_label("Shape:"))
        lo.addWidget(combo)
        lo.addWidget(_label("Stroke:"))
        lo.addWidget(sl)
        lo.addWidget(sp)
        lo.addStretch()

        self._stack.addWidget(page)
        self._pages["Shapes"] = page

    # ── вспомогательные методы для text page ─────────────────────────────────
    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        return f

    def _style_btn(self, label: str, key: str, font: QFont | None = None) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName("styleToggleBtn")
        btn.setCheckable(True)
        btn.setFixedSize(26, 26)
        if font:
            btn.setFont(font)
        btn.toggled.connect(lambda checked: self.option_changed.emit(key, checked))
        return btn

    def _color_btn(self, color: QColor, key: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(26, 26)
        btn.setToolTip(key)

        def _set_color(c: QColor):
            btn.setStyleSheet(
                f"background:{c.name()}; border:1px solid #555; border-radius:3px;")
            self.option_changed.emit(key, QColor(c))

        _set_color(color)
        btn.clicked.connect(lambda: self._pick_color(btn, key, _set_color))
        return btn

    def _pick_color(self, btn, key, callback):
        c = QColorDialog.getColor(options=QColorDialog.ColorDialogOption.ShowAlphaChannel,
                                   parent=btn)
        if c.isValid():
            callback(c)

    def _add_text_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)

        # ── Шрифт ──────────────────────────────────────────────────────────
        font_combo = QFontComboBox()
        font_combo.setFixedWidth(250)
        font_combo.setCurrentFont(QFont("Sans Serif"))
        font_combo.currentFontChanged.connect(
            lambda f: self.option_changed.emit("font_family", f.family()))

        size_sp = QSpinBox()
        size_sp.setRange(4, 500)
        size_sp.setValue(24)
        size_sp.setFixedWidth(52)
        size_sp.valueChanged.connect(lambda v: self.option_changed.emit("font_size", v))

        # ── Стили ──────────────────────────────────────────────────────────
        bold_f = QFont(); bold_f.setBold(True)
        ital_f = QFont(); ital_f.setItalic(True)
        unde_f = QFont(); unde_f.setUnderline(True)
        stri_f = QFont(); stri_f.setStrikeOut(True)

        btn_b = self._style_btn("B",  "font_bold",      bold_f)
        btn_i = self._style_btn("I",  "font_italic",    ital_f)
        btn_u = self._style_btn("U",  "font_underline", unde_f)
        btn_s = self._style_btn("S",  "font_strikeout", stri_f)

        # ── Цвет текста ────────────────────────────────────────────────────
        clr_text = self._color_btn(QColor(0, 0, 0), "text_color")
        clr_text.setToolTip("Цвет текста")

        # ── Обводка ────────────────────────────────────────────────────────
        stroke_sp = QSpinBox()
        stroke_sp.setRange(0, 50)
        stroke_sp.setValue(0)
        stroke_sp.setFixedWidth(44)
        stroke_sp.setToolTip("Ширина обводки (0 = нет)")
        stroke_sp.valueChanged.connect(lambda v: self.option_changed.emit("text_stroke_w", v))

        clr_stroke = self._color_btn(QColor(0, 0, 0), "text_stroke_color")
        clr_stroke.setToolTip("Цвет обводки")

        # ── Тень ───────────────────────────────────────────────────────────
        btn_shadow = QPushButton("Тень")
        btn_shadow.setObjectName("styleToggleBtn")
        btn_shadow.setCheckable(True)
        btn_shadow.setFixedHeight(26)
        btn_shadow.toggled.connect(lambda v: self.option_changed.emit("text_shadow", v))

        sdx = QSpinBox(); sdx.setRange(-50, 50); sdx.setValue(3); sdx.setFixedWidth(44)
        sdx.setToolTip("Тень X"); sdx.valueChanged.connect(
            lambda v: self.option_changed.emit("text_shadow_dx", v))
        sdy = QSpinBox(); sdy.setRange(-50, 50); sdy.setValue(3); sdy.setFixedWidth(44)
        sdy.setToolTip("Тень Y"); sdy.valueChanged.connect(
            lambda v: self.option_changed.emit("text_shadow_dy", v))

        clr_shadow = self._color_btn(QColor(0, 0, 0, 160), "text_shadow_color")
        clr_shadow.setToolTip("Цвет тени")

        # ── Сборка ─────────────────────────────────────────────────────────
        lo.addWidget(font_combo)
        lo.addWidget(size_sp)
        lo.addWidget(self._sep())
        lo.addWidget(btn_b)
        lo.addWidget(btn_i)
        lo.addWidget(btn_u)
        lo.addWidget(btn_s)
        lo.addWidget(clr_text)
        lo.addWidget(self._sep())
        stroke_lbl = QLabel("Обв:")
        stroke_lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
        lo.addWidget(stroke_lbl)
        lo.addWidget(stroke_sp)
        lo.addWidget(clr_stroke)
        lo.addWidget(self._sep())
        lo.addWidget(btn_shadow)
        lo.addWidget(sdx)
        lo.addWidget(sdy)
        lo.addWidget(clr_shadow)
        lo.addWidget(self._sep())

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("smallBtn")
        apply_btn.setFixedHeight(26)
        apply_btn.setToolTip("Применить текущие стили к активному текстовому слою")
        apply_btn.clicked.connect(self.apply_styles_requested.emit)
        lo.addWidget(apply_btn)

        lo.addStretch()

        self._stack.addWidget(page)
        self._pages["Text"] = page

    def _add_empty_page(self, name: str):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(_label(name))
        lo.addStretch()
        self._stack.addWidget(page)
        self._pages[name] = page

    def _add_crop_page(self):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(_label("Drag to select crop area — then press Enter / click Apply Crop"))
        lo.addStretch()
        self._stack.addWidget(page)
        self._pages["Crop"] = page

    def _add_effect_page(self, tool_name: str, label_text: str):
        page = QWidget()
        lo = QHBoxLayout(page)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(14)

        # Размер кисти
        sl_size = _hslider(4, 200, 20)
        sp_size = QSpinBox()
        sp_size.setRange(4, 200)
        sp_size.setValue(20)
        sl_size.valueChanged.connect(sp_size.setValue)
        sp_size.valueChanged.connect(sl_size.setValue)
        sp_size.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        # Сила эффекта
        sl_str = _hslider(1, 100, 50)
        sp_str = QSpinBox()
        sp_str.setRange(1, 100)
        sp_str.setValue(50)
        sp_str.setSuffix("%")
        sl_str.valueChanged.connect(sp_str.setValue)
        sp_str.valueChanged.connect(sl_str.setValue)
        sp_str.valueChanged.connect(
            lambda v: self.option_changed.emit("effect_strength", v / 100))

        lo.addWidget(_label("Size:"))
        lo.addWidget(sl_size)
        lo.addWidget(sp_size)
        lo.addWidget(_label(f"{label_text}:"))
        lo.addWidget(sl_str)
        lo.addWidget(sp_str)
        lo.addStretch()

        self._size_spins[tool_name] = sp_size
        self._stack.addWidget(page)
        self._pages[tool_name] = page

    # ---------------------------------------------------------------- Public
    def switch_to(self, tool_name: str):
        page = self._pages.get(tool_name)
        if page:
            self._stack.setCurrentWidget(page)
            sp = self._size_spins.get(tool_name)
            if sp:
                self.option_changed.emit("brush_size", sp.value())
