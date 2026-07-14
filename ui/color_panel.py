"""Photoshop-style Color panel: FG/BG swatch pair, saturation/value field,
hue ramp and an editable hex value. Full-dialog picking is still available
by double-clicking a swatch."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFrame, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen

from core.locale import tr
from ui import theme
from ui.hsv_picker import HueSaturationMap, HueSlider


class ColorSwatch(QFrame):
    clicked = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, color: QColor, size: int = 34, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def color(self) -> QColor:
        return self._color

    def set_color(self, c: QColor):
        self._color = QColor(c)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        tile = 6
        for tx in range(0, self.width(), tile):
            for ty in range(0, self.height(), tile):
                shade = QColor(200, 200, 200) if (tx // tile + ty // tile) % 2 == 0 else QColor(240, 240, 240)
                p.fillRect(tx, ty, tile, tile, shade)
        p.fillRect(self.rect(), self._color)
        p.setPen(QPen(QColor(60, 60, 80), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, _ev):
        self.clicked.emit()

    def mouseDoubleClickEvent(self, _ev):
        self.double_clicked.emit()


class ColorPanel(QWidget):
    fg_changed = pyqtSignal(QColor)
    bg_changed = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        self._fg = QColor(0, 0, 0)
        self._bg = QColor(255, 255, 255)
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self._title_lbl = QLabel(tr("panel.color"))
        self._title_lbl.setObjectName("panelTitle")
        layout.addWidget(self._title_lbl)

        row = QHBoxLayout()
        row.setSpacing(8)

        # ── FG/BG pair with swap/reset, like the toolbox chip in PS ────────
        pair_col = QVBoxLayout()
        pair_col.setSpacing(2)
        pair = QWidget()
        pair.setFixedSize(54, 54)
        self._bg_swatch = ColorSwatch(self._bg, size=32)
        self._fg_swatch = ColorSwatch(self._fg, size=32)
        self._bg_swatch.setParent(pair)
        self._fg_swatch.setParent(pair)
        self._bg_swatch.move(20, 20)
        self._fg_swatch.move(0, 0)
        self._fg_swatch.clicked.connect(self._activate_fg)
        self._bg_swatch.clicked.connect(self._activate_bg)
        self._fg_swatch.double_clicked.connect(self._pick_fg)
        self._bg_swatch.double_clicked.connect(self._pick_bg)
        pair_col.addWidget(pair)

        btns = QHBoxLayout()
        btns.setSpacing(2)
        self._swap_btn = QPushButton("⇄")
        self._swap_btn.setObjectName("smallBtn")
        self._swap_btn.setFixedSize(25, 20)
        self._swap_btn.setToolTip(tr("color.swap_tooltip"))
        self._swap_btn.clicked.connect(self._swap)
        self._reset_btn = QPushButton("↺")
        self._reset_btn.setObjectName("smallBtn")
        self._reset_btn.setFixedSize(25, 20)
        self._reset_btn.setToolTip(tr("color.reset_tooltip"))
        self._reset_btn.clicked.connect(self._reset)
        btns.addWidget(self._swap_btn)
        btns.addWidget(self._reset_btn)
        pair_col.addLayout(btns)
        pair_col.addStretch()
        row.addLayout(pair_col)

        # ── SV field ────────────────────────────────────────────────────────
        self._sv_map = HueSaturationMap()
        self._sv_map.setMinimumSize(110, 90)
        self._sv_map.sv_changed.connect(self._on_sv_changed)
        row.addWidget(self._sv_map, 1)
        layout.addLayout(row)

        # ── Hue ramp ────────────────────────────────────────────────────────
        self._hue_slider = HueSlider()
        self._hue_slider.hue_changed.connect(self._on_hue_changed)
        layout.addWidget(self._hue_slider)

        # ── Hex value ───────────────────────────────────────────────────────
        hex_row = QHBoxLayout()
        hex_row.setSpacing(4)
        hex_lbl = QLabel("#")
        theme.apply_style(hex_lbl, lambda: f"color: {theme.MUTED};")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setFixedHeight(22)
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_row.addWidget(hex_lbl)
        hex_row.addWidget(self._hex_edit, 1)
        layout.addLayout(hex_row)

        # Which swatch the SV field edits ("fg" | "bg"), like PS's active chip
        self._active_target = "fg"
        self._sync_widgets(self._fg)

    # ── public API (kept stable for MainWindow/tools) ───────────────────────
    def fg(self) -> QColor:
        return QColor(self._fg)

    def bg(self) -> QColor:
        return QColor(self._bg)

    def set_fg(self, c: QColor):
        self._fg = QColor(c)
        self._fg_swatch.set_color(c)
        if self._active_target == "fg":
            self._sync_widgets(c)

    def set_bg(self, c: QColor):
        self._bg = QColor(c)
        self._bg_swatch.set_color(c)
        if self._active_target == "bg":
            self._sync_widgets(c)

    def retranslate(self):
        self._title_lbl.setText(tr("panel.color"))
        self._swap_btn.setToolTip(tr("color.swap_tooltip"))
        self._reset_btn.setToolTip(tr("color.reset_tooltip"))

    # ── internals ────────────────────────────────────────────────────────────
    def _sync_widgets(self, c: QColor):
        """Push a color into the SV field / hue ramp / hex without feedback."""
        self._updating = True
        try:
            h, s, v, _a = c.getHsvF()
            if h < 0:  # achromatic: keep the current hue
                h = self._hue_slider._hue
            self._hue_slider.set_hue(h)
            self._sv_map.set_hue(h)
            self._sv_map.set_sv(s, v)
            self._hex_edit.setText(c.name()[1:].upper())
        finally:
            self._updating = False

    def _emit_active(self, c: QColor):
        if self._active_target == "fg":
            self._fg = QColor(c)
            self._fg_swatch.set_color(c)
            self.fg_changed.emit(QColor(c))
        else:
            self._bg = QColor(c)
            self._bg_swatch.set_color(c)
            self.bg_changed.emit(QColor(c))

    def _current_hsv_color(self) -> QColor:
        return QColor.fromHsvF(min(self._hue_slider._hue, 0.9999),
                               self._sv_map._sat, self._sv_map._val)

    def _on_sv_changed(self, _s: float, _v: float):
        if self._updating:
            return
        c = self._current_hsv_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._emit_active(c)

    def _on_hue_changed(self, h: float):
        if self._updating:
            return
        self._sv_map.set_hue(h)
        c = self._current_hsv_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._emit_active(c)

    def _on_hex_edited(self):
        if self._updating:
            return
        text = self._hex_edit.text().strip().lstrip("#")
        c = QColor("#" + text)
        if not c.isValid():
            active = self._fg if self._active_target == "fg" else self._bg
            self._hex_edit.setText(active.name()[1:].upper())
            return
        self._sync_widgets(c)
        self._emit_active(c)

    def _activate_fg(self):
        self._active_target = "fg"
        self._sync_widgets(self._fg)

    def _activate_bg(self):
        self._active_target = "bg"
        self._sync_widgets(self._bg)

    def _pick_fg(self):
        from .hsv_picker import ColorPickerDialog
        c = ColorPickerDialog.get_color(self._fg, self, tr("color.fg_title"))
        if c:
            self.set_fg(c)
            self.fg_changed.emit(QColor(c))

    def _pick_bg(self):
        from .hsv_picker import ColorPickerDialog
        c = ColorPickerDialog.get_color(self._bg, self, tr("color.bg_title"))
        if c:
            self.set_bg(c)
            self.bg_changed.emit(QColor(c))

    def _swap(self):
        fg, bg = QColor(self._bg), QColor(self._fg)
        self._fg, self._bg = fg, bg
        self._fg_swatch.set_color(fg)
        self._bg_swatch.set_color(bg)
        self._sync_widgets(fg if self._active_target == "fg" else bg)
        self.fg_changed.emit(QColor(fg))
        self.bg_changed.emit(QColor(bg))

    def _reset(self):
        self._fg = QColor(0, 0, 0)
        self._bg = QColor(255, 255, 255)
        self._fg_swatch.set_color(self._fg)
        self._bg_swatch.set_color(self._bg)
        self._sync_widgets(self._fg if self._active_target == "fg" else self._bg)
        self.fg_changed.emit(QColor(self._fg))
        self.bg_changed.emit(QColor(self._bg))
