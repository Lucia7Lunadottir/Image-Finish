from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel,
                             QSlider, QSpinBox)
from PyQt6.QtCore import Qt
from .base_options import BaseOptions


def _hslider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(value)
    s.setFixedWidth(120)
    return s


class EffectOptions(BaseOptions):
    def __init__(self, effect_key: str, parent=None):
        super().__init__(parent)
        self.layout.setSpacing(14)

        sl_size = _hslider(4, 200, 20)
        sp_size = QSpinBox()
        sp_size.setRange(4, 200)
        sp_size.setValue(20)
        sl_size.valueChanged.connect(sp_size.setValue)
        sp_size.valueChanged.connect(sl_size.setValue)
        sp_size.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        sl_str = _hslider(1, 100, 50)
        sp_str = QSpinBox()
        sp_str.setRange(1, 100)
        sp_str.setValue(50)
        sp_str.setSuffix("%")
        sl_str.valueChanged.connect(sp_str.setValue)
        sp_str.valueChanged.connect(sl_str.setValue)
        sp_str.valueChanged.connect(
            lambda v: self.option_changed.emit("effect_strength", v / 100))

        self.layout.addWidget(self._lbl("opts.size"))
        self.layout.addWidget(sl_size)
        self.layout.addWidget(sp_size)
        self.layout.addWidget(self._lbl(effect_key))
        self.layout.addWidget(sl_str)
        self.layout.addWidget(sp_str)
        self.layout.addStretch()
