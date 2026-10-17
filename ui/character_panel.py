from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QDoubleSpinBox, QSlider,
                             QFrame, QFontComboBox, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap, QPainter
from core.locale import tr

from ui import theme
from ui.text_style_widgets import make_style_toggle_btn

def LABEL_STYLE():
    return (f"color:{theme.SUBTEXT};font-size:11px;background:transparent;")
def SPIN_STYLE():
    return (
    f"QSpinBox,QDoubleSpinBox{{background:{theme.SURFACE0};color:{theme.TEXT};border:none;"
                  "padding:2px 4px;border-radius:3px;}"
                  "QSpinBox::up-button,QSpinBox::down-button,"
                  "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{width:14px;}"
    )
def TOGGLE_BTN_STYLE():
    return (
    f"QPushButton{{background:{theme.SURFACE0};color:{theme.TEXT};border:none;padding:4px 8px;"
                        "border-radius:4px;font-weight:bold;}"
                        f"QPushButton:checked{{background:{theme.ACCENT};color:{theme.BASE};}}"
                        f"QPushButton:hover{{background:{theme.SURFACE1};}}"
    )
def HEADER_STYLE():
    return (
    f"color:{theme.MUTED};font-size:10px;font-weight:bold;letter-spacing:1px;"
                    "background:transparent;padding:8px 0 4px 0;"
    )
def SLIDER_STYLE():
    return (
    f"QSlider::groove:horizontal{{height:4px;background:{theme.SURFACE0};border-radius:2px;}}"
                    f"QSlider::handle:horizontal{{background:{theme.ACCENT_LIGHT};width:12px;height:12px;margin:-4px 0;border-radius:6px;}}"
                    f"QSlider::sub-page:horizontal{{background:{theme.ACCENT};border-radius:2px;}}"
    )


def _make_sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    theme.apply_style(f, lambda: f"color:{theme.SURFACE0};background:{theme.SURFACE0};max-height:1px;margin:4px 0;")
    return f


class CharacterPanel(QWidget):
    option_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)

        # ---------- Section header ----------
        self._header_lbl = QLabel("CHARACTER")
        theme.apply_style(self._header_lbl, HEADER_STYLE)
        layout.addWidget(self._header_lbl)
        layout.addWidget(_make_sep())

        # ---------- Font family ----------
        self._font_family_lbl = QLabel("Font:")
        theme.apply_style(self._font_family_lbl, LABEL_STYLE)
        layout.addWidget(self._font_family_lbl)

        self._font_combo = QFontComboBox()
        self._font_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._font_combo.currentFontChanged.connect(
            lambda f: self.option_changed.emit("font_family", f.family())
        )
        layout.addWidget(self._font_combo)

        # ---------- Size ----------
        size_row = QWidget()
        size_lo = QHBoxLayout(size_row)
        size_lo.setContentsMargins(0, 0, 0, 0)
        size_lo.setSpacing(6)

        self._size_lbl = QLabel("Size:")
        theme.apply_style(self._size_lbl, LABEL_STYLE)
        size_lo.addWidget(self._size_lbl)

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(1, 1296)
        self._size_spin.setDecimals(1)
        self._size_spin.setValue(24)
        self._size_spin.setSuffix(" pt")
        theme.apply_style(self._size_spin, SPIN_STYLE)
        self._size_spin.setFixedWidth(72)
        self._size_spin.valueChanged.connect(lambda v: self.option_changed.emit("font_size", v))
        size_lo.addWidget(self._size_spin)
        size_lo.addStretch()
        layout.addWidget(size_row)

        layout.addWidget(_make_sep())

        # ---------- B / I / U toggle row ----------
        style_row = QWidget()
        style_lo = QHBoxLayout(style_row)
        style_lo.setContentsMargins(0, 0, 0, 0)
        style_lo.setSpacing(4)

        bold_font = QFont(); bold_font.setBold(True)
        ital_font = QFont(); ital_font.setItalic(True)
        under_font = QFont(); under_font.setUnderline(True)
        strike_font = QFont(); strike_font.setStrikeOut(True)

        self._btn_bold = make_style_toggle_btn("B", bold_font)
        self._btn_italic = make_style_toggle_btn("I", ital_font)
        self._btn_underline = make_style_toggle_btn("U", under_font)
        self._btn_strikeout = make_style_toggle_btn("S", strike_font)

        for btn, key in ((self._btn_bold, "font_bold"),
                        (self._btn_italic, "font_italic"),
                        (self._btn_underline, "font_underline"),
                        (self._btn_strikeout, "font_strikeout")):
            theme.apply_style(btn, TOGGLE_BTN_STYLE)
            btn.toggled.connect(lambda v, k=key: self.option_changed.emit(k, v))
            style_lo.addWidget(btn)

        # Color button
        self._current_color = QColor(0, 0, 0)
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(36, 28)
        self._color_btn.setToolTip(tr("char.color_tip"))
        self._color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()
        style_lo.addWidget(self._color_btn)
        style_lo.addStretch()

        layout.addWidget(style_row)
        layout.addWidget(_make_sep())

        # ---------- Tracking ----------
        tracking_lbl_row = QWidget()
        tracking_lbl_lo = QHBoxLayout(tracking_lbl_row)
        tracking_lbl_lo.setContentsMargins(0, 0, 0, 0)
        tracking_lbl_lo.setSpacing(6)

        self._tracking_lbl = QLabel("Tracking:")
        theme.apply_style(self._tracking_lbl, LABEL_STYLE)
        tracking_lbl_lo.addWidget(self._tracking_lbl)

        self._tracking_spin = QSpinBox()
        self._tracking_spin.setRange(-500, 500)
        self._tracking_spin.setValue(0)
        theme.apply_style(self._tracking_spin, SPIN_STYLE)
        self._tracking_spin.setFixedWidth(64)
        tracking_lbl_lo.addWidget(self._tracking_spin)
        tracking_lbl_lo.addStretch()
        layout.addWidget(tracking_lbl_row)

        self._tracking_slider = QSlider(Qt.Orientation.Horizontal)
        self._tracking_slider.setRange(-500, 500)
        self._tracking_slider.setValue(0)
        theme.apply_style(self._tracking_slider, SLIDER_STYLE)

        # Connect tracking widgets bidirectionally
        self._tracking_slider.valueChanged.connect(self._on_tracking_slider)
        self._tracking_spin.valueChanged.connect(self._on_tracking_spin)

        layout.addWidget(self._tracking_slider)

        layout.addWidget(_make_sep())

        # ---------- Leading ----------
        leading_row = QWidget()
        leading_lo = QHBoxLayout(leading_row)
        leading_lo.setContentsMargins(0, 0, 0, 0)
        leading_lo.setSpacing(6)

        self._leading_lbl = QLabel("Leading:")
        theme.apply_style(self._leading_lbl, LABEL_STYLE)
        leading_lo.addWidget(self._leading_lbl)

        self._leading_spin = QDoubleSpinBox()
        self._leading_spin.setRange(0.5, 5.0)
        self._leading_spin.setSingleStep(0.1)
        self._leading_spin.setValue(1.0)
        self._leading_spin.setDecimals(2)
        theme.apply_style(self._leading_spin, SPIN_STYLE)
        self._leading_spin.setFixedWidth(72)
        self._leading_spin.valueChanged.connect(lambda v: self.option_changed.emit("text_leading", v))
        leading_lo.addWidget(self._leading_spin)
        leading_lo.addStretch()
        layout.addWidget(leading_row)

        layout.addWidget(_make_sep())

        # ---------- Baseline shift + caps ----------
        extra_row = QWidget()
        extra_lo = QHBoxLayout(extra_row)
        extra_lo.setContentsMargins(0, 0, 0, 0)
        extra_lo.setSpacing(6)
        self._baseline_lbl = QLabel(tr("char.baseline"))
        theme.apply_style(self._baseline_lbl, LABEL_STYLE)
        extra_lo.addWidget(self._baseline_lbl)
        self._baseline_spin = QDoubleSpinBox()
        self._baseline_spin.setRange(-500, 500)
        self._baseline_spin.setDecimals(1)
        self._baseline_spin.setSuffix(" pt")
        theme.apply_style(self._baseline_spin, SPIN_STYLE)
        self._baseline_spin.setFixedWidth(80)
        self._baseline_spin.valueChanged.connect(lambda v: self.option_changed.emit("font_baseline_shift", v))
        extra_lo.addWidget(self._baseline_spin)
        extra_lo.addStretch()
        layout.addWidget(extra_row)

        caps_row = QWidget()
        caps_lo = QHBoxLayout(caps_row)
        caps_lo.setContentsMargins(0, 0, 0, 0)
        caps_lo.setSpacing(6)
        self._caps_lbl = QLabel(tr("char.caps"))
        theme.apply_style(self._caps_lbl, LABEL_STYLE)
        caps_lo.addWidget(self._caps_lbl)
        from PyQt6.QtWidgets import QComboBox
        self._caps_combo = QComboBox()
        for key in ("normal", "all", "small"):
            self._caps_combo.addItem(tr(f"char.caps.{key}"), key)
        self._caps_combo.currentIndexChanged.connect(
            lambda _i: self.option_changed.emit("font_caps", self._caps_combo.currentData()))
        caps_lo.addWidget(self._caps_combo, 1)
        layout.addWidget(caps_row)

        layout.addStretch(1)
        self.retranslate()

    # ---------------------------------------------------------------- Tracking sync

    def _on_tracking_slider(self, value: int):
        self._tracking_spin.blockSignals(True)
        self._tracking_spin.setValue(value)
        self._tracking_spin.blockSignals(False)
        self.option_changed.emit("font_tracking", value)

    def _on_tracking_spin(self, value: int):
        self._tracking_slider.blockSignals(True)
        self._tracking_slider.setValue(value)
        self._tracking_slider.blockSignals(False)
        self.option_changed.emit("font_tracking", value)

    # ---------------------------------------------------------------- Color

    def _pick_color(self):
        from ui.hsv_picker import ColorPickerDialog
        color = ColorPickerDialog.get_color(self._current_color, self, tr("char.color_tip"))
        if color is not None and color.isValid():
            self._current_color = QColor(color)
            self._update_color_btn()
            self.option_changed.emit("text_color", QColor(color))

    def _update_color_btn(self):
        pix = QPixmap(20, 20)
        pix.fill(self._current_color)
        p = QPainter(pix)
        p.setPen(QColor(80, 80, 80))
        p.drawRect(0, 0, 19, 19)
        p.end()
        from PyQt6.QtGui import QIcon
        self._color_btn.setIcon(QIcon(pix))
        self._color_btn.setStyleSheet(
            f"QPushButton{{background:{self._current_color.name()};border:1px solid #555;"
            f"border-radius:3px;padding:0;}}"
            f"QPushButton:hover{{border:1px solid #a6adc8;}}"
        )

    # ---------------------------------------------------------------- Public

    def refresh(self, canvas):
        if canvas is None:
            return
        opts = getattr(canvas, "tool_opts", {})

        self._font_combo.blockSignals(True)
        family = opts.get("font_family", "Sans Serif")
        font = QFont(family)
        self._font_combo.setCurrentFont(font)
        self._font_combo.blockSignals(False)

        self._size_spin.blockSignals(True)
        self._size_spin.setValue(float(opts.get("font_size", 24)))
        self._size_spin.blockSignals(False)

        self._baseline_spin.blockSignals(True)
        self._baseline_spin.setValue(float(opts.get("font_baseline_shift", 0.0)))
        self._baseline_spin.blockSignals(False)

        self._caps_combo.blockSignals(True)
        idx = self._caps_combo.findData(opts.get("font_caps", "normal"))
        self._caps_combo.setCurrentIndex(max(0, idx))
        self._caps_combo.blockSignals(False)

        for btn, key in ((self._btn_bold, "font_bold"),
                        (self._btn_italic, "font_italic"),
                        (self._btn_underline, "font_underline"),
                        (self._btn_strikeout, "font_strikeout")):
            btn.blockSignals(True)
            btn.setChecked(bool(opts.get(key, False)))
            btn.blockSignals(False)

        color = opts.get("text_color", QColor(0, 0, 0))
        if isinstance(color, str):
            color = QColor(color)
        if isinstance(color, QColor) and color.isValid():
            self._current_color = color
            self._update_color_btn()

        tracking = int(opts.get("font_tracking", 0))
        self._tracking_spin.blockSignals(True)
        self._tracking_slider.blockSignals(True)
        self._tracking_spin.setValue(tracking)
        self._tracking_slider.setValue(tracking)
        self._tracking_spin.blockSignals(False)
        self._tracking_slider.blockSignals(False)

        self._leading_spin.blockSignals(True)
        self._leading_spin.setValue(float(opts.get("text_leading", 1.0)))
        self._leading_spin.blockSignals(False)

    def retranslate(self):
        self._header_lbl.setText(tr("char.title"))
        self._font_family_lbl.setText(tr("char.family"))
        self._size_lbl.setText(tr("char.size"))
        self._tracking_lbl.setText(tr("char.tracking"))
        self._leading_lbl.setText(tr("char.leading"))
        self._baseline_lbl.setText(tr("char.baseline"))
        self._caps_lbl.setText(tr("char.caps"))
        self._color_btn.setToolTip(tr("char.color_tip"))
        for i, key in enumerate(("normal", "all", "small")):
            self._caps_combo.setItemText(i, tr(f"char.caps.{key}"))
