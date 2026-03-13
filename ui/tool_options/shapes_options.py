from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel,
                             QSlider, QSpinBox, QComboBox, QCheckBox)
from PyQt6.QtCore import Qt
from .base_options import BaseOptions
from core.locale import tr


def _hslider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(value)
    s.setFixedWidth(120)
    return s


class ShapesOptions(BaseOptions):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout.setSpacing(14)
        
        _SHAPE_VALUES = ("rect", "ellipse", "triangle", "polygon", "line", "star", "arrow", "cross")
        _SHAPE_KEYS = (
            "opts.shape.rect", "opts.shape.ellipse", "opts.shape.triangle",
            "opts.shape.polygon", "opts.shape.line", "opts.shape.star",
            "opts.shape.arrow", "opts.shape.cross",
        )
        combo = QComboBox()
        combo.addItems([tr(k) for k in _SHAPE_KEYS])

        sides_lbl = self._lbl("opts.shape.sides")
        sides_sp = QSpinBox()
        sides_sp.setRange(3, 20)
        sides_sp.setValue(6)
        sides_sp.setFixedWidth(44)
        sides_sp.valueChanged.connect(lambda v: self.option_changed.emit("shape_sides", v))
        sides_lbl.setVisible(False)
        sides_sp.setVisible(False)

        angle_lbl = self._lbl("opts.shape.angle")
        angle_sp = QSpinBox()
        angle_sp.setRange(0, 359)
        angle_sp.setValue(0)
        angle_sp.setFixedWidth(50)
        angle_sp.setSuffix("°")
        angle_sp.setWrapping(True)
        angle_sp.valueChanged.connect(lambda v: self.option_changed.emit("shape_angle", v))

        def _on_shape_change(i):
            shape = _SHAPE_VALUES[i] if 0 <= i < len(_SHAPE_VALUES) else "rect"
            self.option_changed.emit("shape_type", shape)
            sides_lbl.setVisible(shape == "polygon")
            sides_sp.setVisible(shape == "polygon")
            angle_lbl.setVisible(shape != "line")
            angle_sp.setVisible(shape != "line")

        combo.currentIndexChanged.connect(_on_shape_change)

        sl = _hslider(1, 50, 2)
        sp = QSpinBox()
        sp.setRange(1, 50)
        sp.setValue(2)
        sl.valueChanged.connect(sp.setValue)
        sp.valueChanged.connect(sl.setValue)
        sp.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        fill_cb = QCheckBox(tr("opts.shape.fill"))
        fill_cb.setChecked(False)
        fill_cb.toggled.connect(lambda v: self.option_changed.emit("shape_fill", v))

        self.layout.addWidget(self._lbl("opts.shape"))
        self.layout.addWidget(combo)
        self.layout.addWidget(sides_lbl)
        self.layout.addWidget(sides_sp)
        self.layout.addWidget(angle_lbl)
        self.layout.addWidget(angle_sp)
        self.layout.addWidget(fill_cb)
        self.layout.addWidget(self._lbl("opts.stroke"))
        self.layout.addWidget(sl)
        self.layout.addWidget(sp)
        self.layout.addStretch()
