from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel,
                             QSlider, QSpinBox, QComboBox)
from PyQt6.QtCore import Qt
from .base_options import BaseOptions
from core.locale import tr

_MASK_VALUES  = ("round", "square", "scatter")

def _hslider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(value)
    s.setFixedWidth(120)
    return s


class BrushOptions(BaseOptions):
    def __init__(self, parent=None):
        super().__init__(parent)

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

        # Mask — index-based to stay locale-independent
        _MASK_KEYS = ("opts.mask.round", "opts.mask.square", "opts.mask.scatter")
        mask_combo = QComboBox()
        mask_combo.addItems([tr(k) for k in _MASK_KEYS])
        mask_combo.currentIndexChanged.connect(
            lambda i: self.option_changed.emit(
                "brush_mask", _MASK_VALUES[i] if 0 <= i < len(_MASK_VALUES) else "round"))

        self.layout.addWidget(self._lbl("opts.size"))
        self.layout.addWidget(self._brush_size_slider)
        self.layout.addWidget(self._brush_size_spin)
        self.layout.addWidget(self._lbl("opts.opacity"))
        self.layout.addWidget(self._brush_op_slider)
        self.layout.addWidget(self._brush_op_spin)
        self.layout.addWidget(self._lbl("opts.hardness"))
        self.layout.addWidget(hard_sl)
        self.layout.addWidget(hard_sp)
        self.layout.addWidget(self._lbl("opts.mask"))
        self.layout.addWidget(mask_combo)
        self.layout.addStretch()
