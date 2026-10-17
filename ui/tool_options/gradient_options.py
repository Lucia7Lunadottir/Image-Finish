from PyQt6.QtWidgets import QSpinBox, QComboBox, QCheckBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from .base_options import BaseOptions
from core.locale import tr
from core.gradient_model import Gradient, GRADIENT_STYLES
from ui.gradient_editor import GradientPreviewWidget, GradientEditorDialog
from ui.blend_mode_combo import BlendModeCombo
from ui.adjustments_dialog import _JumpSlider


class GradientOptions(BaseOptions):
    """Gradient tool options, as in Photoshop: the gradient (swatch ->
    full editor), style (linear/radial/angle/reflected/diamond), blend
    mode, opacity, reverse. The style is laid out along the drag — see
    core/gradient_model.py::Gradient.brush_for_drag."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout.setSpacing(10)
        emit = self.option_changed.emit

        self._gradient = None          # None = foreground -> background
        self._swatch = GradientPreviewWidget()
        self._swatch.setToolTip(tr("opts.gradient.edit_tip"))
        self._swatch.clicked.connect(self._edit_gradient)

        self._style = QComboBox()
        for st in GRADIENT_STYLES:
            self._style.addItem(tr(f"gradient_editor.style.{st}"), st)
        self._style.currentIndexChanged.connect(lambda _i: emit("gradient_type", self._style.currentData()))

        self._mode = BlendModeCombo()
        self._mode.currentIndexChanged.connect(lambda _i: emit("gradient_mode", self._mode.value()))

        self._opacity_sl = _JumpSlider(Qt.Orientation.Horizontal)
        self._opacity_sl.setRange(1, 100)
        self._opacity_sl.setValue(100)
        self._opacity_sl.setFixedWidth(110)
        self._opacity_sp = QSpinBox()
        self._opacity_sp.setRange(1, 100)
        self._opacity_sp.setValue(100)
        self._opacity_sp.setSuffix("%")
        self._opacity_sl.valueChanged.connect(self._opacity_sp.setValue)
        self._opacity_sp.valueChanged.connect(self._opacity_sl.setValue)
        self._opacity_sp.valueChanged.connect(lambda v: emit("gradient_opacity", v))

        self._reverse = QCheckBox(tr("opts.gradient.reverse"))
        self._reverse.toggled.connect(lambda v: emit("gradient_reverse", v))

        for w in (self._swatch, self._lbl("opts.gradient.type"), self._style,
                  self._lbl("opts.blend_mode"), self._mode,
                  self._lbl("opts.opacity"), self._opacity_sl, self._opacity_sp, self._reverse):
            self.layout.addWidget(w)
        self.layout.addStretch()

    def _colors(self):
        canvas = getattr(self.window(), "_canvas", None)
        return (QColor(getattr(canvas, "fg_color", QColor(0, 0, 0))),
                QColor(getattr(canvas, "bg_color", QColor(255, 255, 255))))

    def _current(self) -> Gradient:
        return self._gradient.copy() if self._gradient else Gradient.two_color(*self._colors())

    def _edit_gradient(self):
        fg, bg = self._colors()
        dlg = GradientEditorDialog(self._current(), fg, bg, self)
        if dlg.exec():
            self._gradient = dlg.result_gradient()
            self._swatch.set_gradient(self._gradient)
            self.option_changed.emit("gradient", self._gradient.to_dict())

    def update_from_opts(self, opts: dict):
        if opts.get("gradient"):
            self._gradient = Gradient.from_dict(opts["gradient"])
        self._swatch.set_gradient(self._current())
        for w, setter, key, default in (
                (self._style, lambda v: self._style.setCurrentIndex(max(0, self._style.findData(v))),
                 "gradient_type", "linear"),
                (self._mode, self._mode.set_value, "gradient_mode", "SourceOver"),
                (self._opacity_sp, self._opacity_sp.setValue, "gradient_opacity", 100),
                (self._reverse, self._reverse.setChecked, "gradient_reverse", False)):
            w.blockSignals(True)
            setter(opts.get(key, default))
            w.blockSignals(False)
        self._opacity_sl.blockSignals(True)
        self._opacity_sl.setValue(self._opacity_sp.value())
        self._opacity_sl.blockSignals(False)

    def retranslate(self):
        super().retranslate()
        for i, st in enumerate(GRADIENT_STYLES):
            self._style.setItemText(i, tr(f"gradient_editor.style.{st}"))
        self._mode.retranslate()
        self._reverse.setText(tr("opts.gradient.reverse"))
        self._swatch.setToolTip(tr("opts.gradient.edit_tip"))
