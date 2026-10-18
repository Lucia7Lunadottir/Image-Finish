"""Edit > Stroke… — Photoshop's Stroke dialog: width, colour, location,
blend mode, opacity, preserve transparency (core/selection_stroke.py
does the painting)."""
from dataclasses import dataclass, field

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QRadioButton, QVBoxLayout)

from core.locale import tr
from core.selection_stroke import LOCATIONS
from ui.base_dialog import BaseDialog
from ui.blend_mode_combo import BlendModeCombo
from ui.brush_widgets import SliderSpin
from ui.color_panel import ColorSwatch


@dataclass
class StrokeSettings:
    width: int = 3
    color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    location: str = "center"
    blend_mode: str = "SourceOver"
    opacity: int = 100
    preserve_transparency: bool = False


class StrokeDialog(BaseDialog):

    def __init__(self, settings: StrokeSettings, parent=None):
        super().__init__(parent, "dlg.stroke.title")
        lay = QVBoxLayout(self)

        stroke_box = QGroupBox(tr("dlg.stroke.stroke"))
        grid = QGridLayout(stroke_box)
        self._width = SliderSpin(1, 250, suffix=" px", slider_width=160)
        self._width.setValue(settings.width)
        grid.addWidget(QLabel(tr("dlg.stroke.width")), 0, 0)
        grid.addWidget(self._width, 0, 1)
        self._swatch = ColorSwatch(QColor(settings.color), 26)
        self._swatch.clicked.connect(self._pick_color)
        grid.addWidget(QLabel(tr("dlg.stroke.color")), 1, 0)
        grid.addWidget(self._swatch, 1, 1)
        lay.addWidget(stroke_box)

        loc_box = QGroupBox(tr("dlg.stroke.location"))
        loc_lay = QHBoxLayout(loc_box)
        self._locations = QButtonGroup(self)
        for i, loc in enumerate(LOCATIONS):
            rb = QRadioButton(tr(f"dlg.stroke.{loc}"))
            rb.setChecked(loc == settings.location)
            self._locations.addButton(rb, i)
            loc_lay.addWidget(rb)
        lay.addWidget(loc_box)

        blend_box = QGroupBox(tr("dlg.stroke.blending"))
        bgrid = QGridLayout(blend_box)
        self._mode = BlendModeCombo()
        self._mode.setCurrentIndex(max(0, self._mode.findData(settings.blend_mode)))
        bgrid.addWidget(QLabel(tr("opts.blend_mode")), 0, 0)
        bgrid.addWidget(self._mode, 0, 1)
        self._opacity = SliderSpin(1, 100, suffix="%", slider_width=160)
        self._opacity.setValue(settings.opacity)
        bgrid.addWidget(QLabel(tr("opts.opacity")), 1, 0)
        bgrid.addWidget(self._opacity, 1, 1)
        self._preserve = QCheckBox(tr("dlg.stroke.preserve_transparency"))
        self._preserve.setChecked(settings.preserve_transparency)
        bgrid.addWidget(self._preserve, 2, 0, 1, 2)
        lay.addWidget(blend_box)

        self.add_button_box(lay)

    def _pick_color(self):
        c = QColorDialog.getColor(self._swatch.color(), self, tr("dlg.stroke.color"))
        if c.isValid():
            self._swatch.set_color(c)

    def settings(self) -> StrokeSettings:
        return StrokeSettings(
            width=self._width.value(),
            color=QColor(self._swatch.color()),
            location=LOCATIONS[max(0, self._locations.checkedId())],
            blend_mode=self._mode.currentData() or "SourceOver",
            opacity=self._opacity.value(),
            preserve_transparency=self._preserve.isChecked(),
        )
