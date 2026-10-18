from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSpinBox, QDial, QComboBox, QFileDialog, QCheckBox, QPushButton, QLabel
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
from .base_options import BaseOptions
from core.locale import tr
from ui.blend_mode_combo import BlendModeCombo
from ui.brush_widgets import SliderSpin, tip_icon, tip_library

class BrushOptions(BaseOptions):
    """Options panel for brush-based tools (Brush, Eraser, etc.)."""
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Brush tip ---
        self.layout.addWidget(self._lbl("opts.mask"))
        self._mask_combo = QComboBox()
        self._mask_combo.setIconSize(QSize(32, 32))
        self._mask_combo.activated.connect(self._on_mask_activated)
        self.layout.addWidget(self._mask_combo)
        tip_library().changed.connect(self._fill_tips)
        self._fill_tips()

        # --- Blend mode ---
        self.layout.addWidget(self._lbl("opts.blend_mode"))
        self._blend_combo = BlendModeCombo()
        self._blend_combo.activated.connect(lambda idx: self.option_changed.emit("brush_blend_mode", self._blend_combo.itemData(idx)))
        self.layout.addWidget(self._blend_combo)

        # --- Size / Opacity / Hardness ---
        self._size = SliderSpin(1, 500, 5000)
        self._size.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))
        self._size_dyn_cb = QCheckBox(tr("opts.dynamic"))
        self._size_dyn_cb.toggled.connect(lambda v: self.option_changed.emit("brush_size_dynamic", v))
        self._add_row("opts.size", self._size, self._size_dyn_cb)

        self._opacity = SliderSpin(1, 100, suffix="%")
        self._opacity.valueChanged.connect(lambda v: self.option_changed.emit("brush_opacity", v / 100.0))
        self._opacity_dyn_cb = QCheckBox(tr("opts.dynamic"))
        self._opacity_dyn_cb.toggled.connect(lambda v: self.option_changed.emit("brush_opacity_dynamic", v))
        self._add_row("opts.opacity", self._opacity, self._opacity_dyn_cb)

        self._hardness = SliderSpin(0, 100, suffix="%")
        self._hardness.valueChanged.connect(lambda v: self.option_changed.emit("brush_hardness", v / 100.0))
        self._add_row("opts.hardness", self._hardness)

        # --- Angle ---
        self.layout.addWidget(self._lbl("opts.angle"))
        angle_widget = QWidget()
        angle_layout = QHBoxLayout(angle_widget)
        angle_layout.setContentsMargins(0, 0, 0, 0)
        self._angle_dial = QDial()
        self._angle_dial.setRange(0, 359)
        self._angle_dial.setWrapping(True)
        self._angle_dial.setNotchesVisible(True)
        self._angle_dial.setFixedSize(50, 50)
        self._angle_spin = QSpinBox()
        self._angle_spin.setRange(0, 359)
        self._angle_spin.setSuffix("°")
        self._angle_dial.valueChanged.connect(self._angle_spin.setValue)
        self._angle_spin.valueChanged.connect(self._angle_dial.setValue)
        self._angle_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_angle", float(v)))
        angle_layout.addWidget(self._angle_dial)
        angle_layout.addWidget(self._angle_spin)
        
        self._angle_random_cb = QCheckBox(tr("opts.angle_random"))
        self._angle_random_cb.toggled.connect(lambda v: self.option_changed.emit("brush_angle_random", v))
        angle_layout.addWidget(self._angle_random_cb)
        
        self.layout.addWidget(angle_widget)

        # --- Symmetry ---
        sym_widget = QWidget()
        sym_layout = QHBoxLayout(sym_widget)
        sym_layout.setContentsMargins(0, 0, 0, 0)
        self._lbl_sym = QLabel(tr("opts.symmetry"))
        sym_layout.addWidget(self._lbl_sym)
        self._mirror_x_btn = QPushButton("X")
        self._mirror_x_btn.setCheckable(True)
        self._mirror_x_btn.setFixedWidth(30)
        self._mirror_x_btn.toggled.connect(lambda v: self.option_changed.emit("brush_mirror_x", v))
        sym_layout.addWidget(self._mirror_x_btn)
        self._mirror_y_btn = QPushButton("Y")
        self._mirror_y_btn.setCheckable(True)
        self._mirror_y_btn.setFixedWidth(30)
        self._mirror_y_btn.toggled.connect(lambda v: self.option_changed.emit("brush_mirror_y", v))
        sym_layout.addWidget(self._mirror_y_btn)
        
        self._cx_spin = QSpinBox()
        self._cx_spin.setRange(0, 100)
        self._cx_spin.setValue(50)
        self._cx_spin.setSuffix("%")
        self._cx_spin.setFixedWidth(66)
        self._cx_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_mirror_cx", v / 100.0))
        sym_layout.addWidget(self._cx_spin)
        
        self._cy_spin = QSpinBox()
        self._cy_spin.setRange(0, 100)
        self._cy_spin.setValue(50)
        self._cy_spin.setSuffix("%")
        self._cy_spin.setFixedWidth(66)
        self._cy_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_mirror_cy", v / 100.0))
        sym_layout.addWidget(self._cy_spin)
        
        self._sym_reset_btn = QPushButton("↺")
        self._sym_reset_btn.setFixedWidth(24)
        self._sym_reset_btn.clicked.connect(self._reset_symmetry)
        sym_layout.addWidget(self._sym_reset_btn)
        sym_layout.addStretch()
        self.layout.addWidget(sym_widget)

        self.layout.addStretch()

    def _add_row(self, label_key, *widgets):
        self.layout.addWidget(self._lbl(label_key))
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            lay.addWidget(w)
        self.layout.addWidget(row)

    def _fill_tips(self):
        """Tips from the shared library, then "Load…"."""
        lib = tip_library()
        current = self._mask_combo.currentData()
        self._mask_combo.blockSignals(True)
        self._mask_combo.clear()
        for tip in lib.tips():
            self._mask_combo.addItem(tip_icon(tip.value), lib.title(tip), tip.value)
        self._mask_combo.addItem(QIcon(), tr("opts.load"), "load_custom")
        idx = self._mask_combo.findData(current)
        self._mask_combo.setCurrentIndex(max(0, idx))
        self._mask_combo.blockSignals(False)

    def _on_mask_activated(self, idx):
        data = self._mask_combo.itemData(idx)
        if data == "load_custom":
            path, _ = QFileDialog.getOpenFileName(self, tr("opts.brush_select_image"), "", "Images (*.png *.jpg *.jpeg *.bmp)")
            data = tip_library().import_file(path) if path else "round"
            self._mask_combo.setCurrentIndex(max(0, self._mask_combo.findData(data)))
        self.option_changed.emit("brush_mask", data)

    def _reset_symmetry(self):
        self._cx_spin.setValue(50)
        self._cy_spin.setValue(50)

    def update_params(self, params: dict | None):
        if isinstance(params, dict):
            if "brush_mirror_cx" in params:
                self._cx_spin.blockSignals(True)
                self._cx_spin.setValue(int(params["brush_mirror_cx"] * 100))
                self._cx_spin.blockSignals(False)
            if "brush_mirror_cy" in params:
                self._cy_spin.blockSignals(True)
                self._cy_spin.setValue(int(params["brush_mirror_cy"] * 100))
                self._cy_spin.blockSignals(False)

    def update_from_opts(self, opts: dict):
        # Block signals to prevent triggering option_changed during update
        controls = [self._size_dyn_cb, self._opacity_dyn_cb,
                    self._angle_spin, self._angle_random_cb,
                    self._blend_combo, self._mirror_x_btn, self._mirror_y_btn,
                    self._cx_spin, self._cy_spin]
        for w in controls:
            w.blockSignals(True)

        self._size.setValue(opts.get("brush_size", 10))
        self._size_dyn_cb.setChecked(opts.get("brush_size_dynamic", False))
        self._opacity.setValue(round(opts.get("brush_opacity", 1.0) * 100))
        self._opacity_dyn_cb.setChecked(opts.get("brush_opacity_dynamic", False))
        self._hardness.setValue(round(opts.get("brush_hardness", 1.0) * 100))
        self._angle_spin.setValue(int(opts.get("brush_angle", 0.0)))
        self._angle_random_cb.setChecked(opts.get("brush_angle_random", False))
        self._mirror_x_btn.setChecked(bool(opts.get("brush_mirror_x", False)))
        self._mirror_y_btn.setChecked(bool(opts.get("brush_mirror_y", False)))
        self._cx_spin.setValue(int(opts.get("brush_mirror_cx", 0.5) * 100))
        self._cy_spin.setValue(int(opts.get("brush_mirror_cy", 0.5) * 100))

        blend = opts.get("brush_blend_mode", "SourceOver")
        idx_blend = self._blend_combo.findData(blend)
        if idx_blend >= 0:
            self._blend_combo.setCurrentIndex(idx_blend)

        mask_val = opts.get("brush_mask", "round")
        idx = self._mask_combo.findData(mask_val)
        if idx >= 0:
            self._mask_combo.blockSignals(True)
            self._mask_combo.setCurrentIndex(idx)
            self._mask_combo.blockSignals(False)

        for w in controls:
            w.blockSignals(False)

    def retranslate(self):
        self._fill_tips()

        self._blend_combo.retranslate()

        self._size_dyn_cb.setText(tr("opts.dynamic"))
        self._opacity_dyn_cb.setText(tr("opts.dynamic"))
        self._angle_random_cb.setText(tr("opts.angle_random"))
        self._lbl_sym.setText(tr("opts.symmetry"))
        self._cx_spin.setToolTip(tr("opts.sym_x"))
        self._cy_spin.setToolTip(tr("opts.sym_y"))
        self._sym_reset_btn.setToolTip(tr("opts.sym_reset"))
        if hasattr(super(), "retranslate"):
            super().retranslate()