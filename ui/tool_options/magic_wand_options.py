from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QSpinBox, QCheckBox
from PyQt6.QtCore import Qt
from .base_options import BaseOptions

class MagicWandOptions(BaseOptions):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Блок чувствительности (Tolerance) ---
        self.layout.addWidget(self._lbl("opts.tolerance"))

        tol_widget = QWidget()
        tol_layout = QHBoxLayout(tol_widget)
        tol_layout.setContentsMargins(0, 0, 0, 0)

        self._tol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tol_slider.setRange(0, 100)
        self._tol_slider.setFixedWidth(80)

        self._tol_spin = QSpinBox()
        self._tol_spin.setRange(0, 100)
        self._tol_spin.setSuffix("%")

        self._tol_slider.valueChanged.connect(self._tol_spin.setValue)
        self._tol_spin.valueChanged.connect(self._tol_slider.setValue)
        self._tol_spin.valueChanged.connect(lambda v: self.option_changed.emit("fill_tolerance", v))

        tol_layout.addWidget(self._tol_slider)
        tol_layout.addWidget(self._tol_spin)
        self.layout.addWidget(tol_widget)

        # --- Галочки (Чекбоксы) ---
        self._aa_cb = QCheckBox("Сглаживание")
        self._aa_cb.setChecked(True)
        self._aa_cb.toggled.connect(lambda v: self.option_changed.emit("anti_alias", v))
        self.layout.addWidget(self._aa_cb)

        self._contig_cb = QCheckBox("Прилегающий")
        self._contig_cb.setChecked(True)
        self._contig_cb.toggled.connect(lambda v: self.option_changed.emit("contiguous", v))
        self.layout.addWidget(self._contig_cb)

        self._sample_cb = QCheckBox("Со всех слоёв")
        self._sample_cb.setChecked(False)
        self._sample_cb.toggled.connect(lambda v: self.option_changed.emit("sample_all", v))
        self.layout.addWidget(self._sample_cb)

        self.layout.addStretch()

    def update_from_opts(self, opts: dict):
        self._tol_spin.setValue(opts.get("fill_tolerance", 32))
        self._aa_cb.setChecked(opts.get("anti_alias", True))
        self._contig_cb.setChecked(opts.get("contiguous", True))
        self._sample_cb.setChecked(opts.get("sample_all", False))
