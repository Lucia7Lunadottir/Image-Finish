from PyQt6.QtWidgets import (QLabel,
                             QSpinBox, QDoubleSpinBox, QPushButton, QFontComboBox, QFrame)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QFont
from .base_options import BaseOptions
from core.locale import tr

from ui import theme
from ui.text_style_widgets import make_style_toggle_btn


class TextOptions(BaseOptions):
    apply_styles_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout.setSpacing(4)

        font_combo = self._font_combo = QFontComboBox()
        font_combo.setFixedWidth(250)
        font_combo.setCurrentFont(QFont("Sans Serif"))
        font_combo.currentFontChanged.connect(
            lambda f: self.option_changed.emit("font_family", f.family()))

        size_sp = self._size_sp = QDoubleSpinBox()
        size_sp.setRange(1, 1296)
        size_sp.setDecimals(1)
        size_sp.setValue(24)
        size_sp.setSuffix(" pt")
        size_sp.setFixedWidth(84)
        size_sp.valueChanged.connect(lambda v: self.option_changed.emit("font_size", v))

        bold_f = QFont(); bold_f.setBold(True)
        ital_f = QFont(); ital_f.setItalic(True)
        unde_f = QFont(); unde_f.setUnderline(True)
        stri_f = QFont(); stri_f.setStrikeOut(True)

        btn_b = self._btn_b = self._style_btn("B", "font_bold",      bold_f)
        btn_i = self._btn_i = self._style_btn("I", "font_italic",    ital_f)
        btn_u = self._btn_u = self._style_btn("U", "font_underline", unde_f)
        btn_s = self._btn_s = self._style_btn("S", "font_strikeout", stri_f)

        clr_text = self._clr_text = self._color_btn(QColor(0, 0, 0), "text_color")

        stroke_sp = self._stroke_sp = QSpinBox()
        stroke_sp.setRange(0, 50)
        stroke_sp.setValue(0)
        stroke_sp.setFixedWidth(44)
        stroke_sp.valueChanged.connect(lambda v: self.option_changed.emit("text_stroke_w", v))

        clr_stroke = self._clr_stroke = self._color_btn(QColor(0, 0, 0), "text_stroke_color")

        btn_shadow = self._btn_shadow = QPushButton(tr("opts.shadow"))
        btn_shadow.setObjectName("styleToggleBtn")
        btn_shadow.setCheckable(True)
        btn_shadow.setFixedHeight(26)
        btn_shadow.toggled.connect(lambda v: self.option_changed.emit("text_shadow", v))

        sdx = self._sdx = QSpinBox(); sdx.setRange(-50, 50); sdx.setValue(3); sdx.setFixedWidth(44)
        sdx.valueChanged.connect(lambda v: self.option_changed.emit("text_shadow_dx", v))

        sdy = self._sdy = QSpinBox(); sdy.setRange(-50, 50); sdy.setValue(3); sdy.setFixedWidth(44)
        sdy.valueChanged.connect(lambda v: self.option_changed.emit("text_shadow_dy", v))

        clr_shadow = self._clr_shadow = self._color_btn(QColor(0, 0, 0, 160), "text_shadow_color")

        # Orientation of new text — or, with a text layer selected / being
        # edited, of that text (Photoshop's "toggle text orientation").
        self._orient_btn = QPushButton("⇅")
        self._orient_btn.setObjectName("styleToggleBtn")
        self._orient_btn.setCheckable(True)
        self._orient_btn.setFixedSize(30, 26)
        self._orient_btn.setToolTip(tr("opts.text.vertical_tip"))
        self._orient_btn.toggled.connect(lambda v: self.option_changed.emit("text_vertical", v))

        # Commit / cancel the edit in progress (shown only while editing).
        self._commit_btn = QPushButton("✓")
        self._commit_btn.setObjectName("smallBtn")
        self._commit_btn.setFixedSize(30, 26)
        self._commit_btn.setToolTip(tr("opts.text.commit_tip"))
        self._commit_btn.clicked.connect(self.apply_styles_requested.emit)
        self._cancel_btn = QPushButton("✗")
        self._cancel_btn.setObjectName("smallBtn")
        self._cancel_btn.setFixedSize(30, 26)
        self._cancel_btn.setToolTip(tr("opts.text.cancel_tip"))
        self._cancel_btn.clicked.connect(lambda: self.option_changed.emit("text_edit_cancel", True))
        self.set_editing(False)

        stroke_lbl = QLabel(tr("opts.stroke_abbr"))
        theme.apply_style(stroke_lbl, lambda: f"color: {theme.SUBTEXT}; font-size: 12px;")

        self.layout.addWidget(font_combo)
        self.layout.addWidget(size_sp)
        self.layout.addWidget(self._sep())
        self.layout.addWidget(btn_b)
        self.layout.addWidget(btn_i)
        self.layout.addWidget(btn_u)
        self.layout.addWidget(btn_s)
        self.layout.addWidget(clr_text)
        self.layout.addWidget(self._sep())
        self.layout.addWidget(stroke_lbl)
        self.layout.addWidget(stroke_sp)
        self.layout.addWidget(clr_stroke)
        self.layout.addWidget(self._sep())
        self.layout.addWidget(btn_shadow)
        self.layout.addWidget(sdx)
        self.layout.addWidget(sdy)
        self.layout.addWidget(clr_shadow)
        self.layout.addWidget(self._sep())
        self.layout.addWidget(self._orient_btn)
        self.layout.addStretch()
        self.layout.addWidget(self._commit_btn)
        self.layout.addWidget(self._cancel_btn)

    def set_editing(self, editing: bool):
        self._commit_btn.setVisible(editing)
        self._cancel_btn.setVisible(editing)

    def update_from_opts(self, opts: dict):
        """Matches the update_from_opts(opts) convention every other
        options page already uses (brush_options.py etc.) — this bar can
        also *set* every one of these options, but until now had no way
        to reflect a change made anywhere else (Character panel, a
        reopened text layer): the toolbar-vs-dock desync bug."""
        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentFont(QFont(opts.get("font_family", "Sans Serif")))
        self._font_combo.blockSignals(False)

        self._size_sp.blockSignals(True)
        self._size_sp.setValue(float(opts.get("font_size", 24)))
        self._size_sp.blockSignals(False)

        self._orient_btn.blockSignals(True)
        self._orient_btn.setChecked(bool(opts.get("text_vertical", False)))
        self._orient_btn.blockSignals(False)

        for btn, key in ((self._btn_b, "font_bold"), (self._btn_i, "font_italic"),
                        (self._btn_u, "font_underline"), (self._btn_s, "font_strikeout")):
            btn.blockSignals(True)
            btn.setChecked(bool(opts.get(key, False)))
            btn.blockSignals(False)

        for btn, key, default in ((self._clr_text, "text_color", QColor(0, 0, 0)),
                                  (self._clr_stroke, "text_stroke_color", QColor(0, 0, 0)),
                                  (self._clr_shadow, "text_shadow_color", QColor(0, 0, 0, 160))):
            c = opts.get(key, default)
            if isinstance(c, str):
                c = QColor(c)
            if isinstance(c, QColor) and c.isValid():
                btn._color = QColor(c)
                btn.setStyleSheet(
                    f"background:{c.name()}; border:1px solid #555; border-radius:3px;")

        self._stroke_sp.blockSignals(True)
        self._stroke_sp.setValue(int(opts.get("text_stroke_w", 0)))
        self._stroke_sp.blockSignals(False)

        self._btn_shadow.blockSignals(True)
        self._btn_shadow.setChecked(bool(opts.get("text_shadow", False)))
        self._btn_shadow.blockSignals(False)

        self._sdx.blockSignals(True)
        self._sdx.setValue(int(opts.get("text_shadow_dx", 3)))
        self._sdx.blockSignals(False)

        self._sdy.blockSignals(True)
        self._sdy.setValue(int(opts.get("text_shadow_dy", 3)))
        self._sdy.blockSignals(False)

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        return f

    def _style_btn(self, label: str, key: str, font: QFont | None = None) -> QPushButton:
        btn = make_style_toggle_btn(label, font, size=(26, 26))
        btn.setObjectName("styleToggleBtn")
        btn.toggled.connect(lambda checked: self.option_changed.emit(key, checked))
        return btn

    def _color_btn(self, color: QColor, key: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(26, 26)

        def _set_color(c: QColor):
            btn._color = QColor(c)
            btn.setStyleSheet(
                f"background:{c.name()}; border:1px solid #555; border-radius:3px;")
            self.option_changed.emit(key, QColor(c))

        _set_color(color)
        btn.clicked.connect(lambda: self._pick_color(btn, _set_color))
        return btn

    def _pick_color(self, btn, callback):
        from ui.hsv_picker import ColorPickerDialog
        c = ColorPickerDialog.get_color(getattr(btn, "_color", QColor(0, 0, 0)), btn, tr("adj.choose_color"))
        if c is not None and c.isValid():
            callback(c)
