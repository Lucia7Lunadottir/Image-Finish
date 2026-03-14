import os
import glob
import shutil
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QSpinBox, QDial, QComboBox, QFileDialog, QCheckBox
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QImage
from PyQt6.QtCore import Qt, QSize
from .base_options import BaseOptions
from core.locale import tr

class BrushOptions(BaseOptions):
    """Панель опций для инструментов с кистью (Кисть, Ластик и т.д.)."""
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Маска / Форма кисти ---
        self.layout.addWidget(self._lbl("opts.mask"))
        self._mask_combo = QComboBox()
        self._mask_combo.setIconSize(QSize(32, 32))
        self._mask_combo.addItem(self._get_icon("round"), tr("opts.mask.round"), "round")
        self._mask_combo.addItem(self._get_icon("square"), tr("opts.mask.square"), "square")
        self._mask_combo.addItem(self._get_icon("scatter"), tr("opts.mask.scatter"), "scatter")

        # Автозагрузка кистей из папки brushes
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        brushes_dir = os.path.join(base_dir, "brushes")
        if os.path.exists(brushes_dir):
            for ext in ('*.png', '*.jpg', '*.jpeg', '*.bmp'):
                for path in glob.glob(os.path.join(brushes_dir, ext)):
                    name = os.path.splitext(os.path.basename(path))[0]
                    self._mask_combo.addItem(self._get_icon(path), name, path)

        self._mask_combo.addItem(QIcon(), "Загрузить...", "load_custom")
        
        self._mask_combo.activated.connect(self._on_mask_activated)
        self.layout.addWidget(self._mask_combo)

        # --- Режим смешивания ---
        self.layout.addWidget(self._lbl("opts.blend_mode"))
        self._blend_combo = QComboBox()
        modes = [
            ("blend.normal", "SourceOver"), ("blend.multiply", "Multiply"),
            ("blend.screen", "Screen"), ("blend.overlay", "Overlay"),
            ("blend.darken", "Darken"), ("blend.lighten", "Lighten"),
            ("blend.color_dodge", "ColorDodge"), ("blend.color_burn", "ColorBurn"),
            ("blend.hard_light", "HardLight"), ("blend.soft_light", "SoftLight"),
            ("blend.difference", "Difference"), ("blend.exclusion", "Exclusion")
        ]
        for loc_key, val in modes:
            self._blend_combo.addItem(tr(loc_key), val)
        
        self._blend_combo.activated.connect(lambda idx: self.option_changed.emit("brush_blend_mode", self._blend_combo.itemData(idx)))
        self.layout.addWidget(self._blend_combo)

        # --- Размер ---
        self.layout.addWidget(self._lbl("opts.size"))
        size_widget = QWidget()
        size_layout = QHBoxLayout(size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(1, 500)
        self._size_slider.setFixedWidth(100)
        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 5000)
        self._size_slider.valueChanged.connect(self._on_size_slider_change)
        self._size_spin.valueChanged.connect(self._on_size_spin_change)
        size_layout.addWidget(self._size_slider)
        size_layout.addWidget(self._size_spin)
        self._size_dyn_cb = QCheckBox(tr("opts.dynamic"))
        self._size_dyn_cb.toggled.connect(lambda v: self.option_changed.emit("brush_size_dynamic", v))
        size_layout.addWidget(self._size_dyn_cb)
        self.layout.addWidget(size_widget)

        # --- Непрозрачность ---
        self.layout.addWidget(self._lbl("opts.opacity"))
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(1, 100)
        self._opacity_slider.setFixedWidth(100)
        self._opacity_spin = QSpinBox()
        self._opacity_spin.setRange(1, 100)
        self._opacity_spin.setSuffix("%")
        self._opacity_slider.valueChanged.connect(self._opacity_spin.setValue)
        self._opacity_spin.valueChanged.connect(self._opacity_slider.setValue)
        self._opacity_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_opacity", v / 100.0))
        opacity_layout.addWidget(self._opacity_slider)
        opacity_layout.addWidget(self._opacity_spin)
        self._opacity_dyn_cb = QCheckBox(tr("opts.dynamic"))
        self._opacity_dyn_cb.toggled.connect(lambda v: self.option_changed.emit("brush_opacity_dynamic", v))
        opacity_layout.addWidget(self._opacity_dyn_cb)
        self.layout.addWidget(opacity_widget)

        # --- Жёсткость ---
        self.layout.addWidget(self._lbl("opts.hardness"))
        hardness_widget = QWidget()
        hardness_layout = QHBoxLayout(hardness_widget)
        hardness_layout.setContentsMargins(0, 0, 0, 0)
        self._hardness_slider = QSlider(Qt.Orientation.Horizontal)
        self._hardness_slider.setRange(0, 100)
        self._hardness_slider.setFixedWidth(100)
        self._hardness_spin = QSpinBox()
        self._hardness_spin.setRange(0, 100)
        self._hardness_spin.setSuffix("%")
        self._hardness_slider.valueChanged.connect(self._hardness_spin.setValue)
        self._hardness_spin.valueChanged.connect(self._hardness_slider.setValue)
        self._hardness_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_hardness", v / 100.0))
        hardness_layout.addWidget(self._hardness_slider)
        hardness_layout.addWidget(self._hardness_spin)
        self.layout.addWidget(hardness_widget)

        # --- Угол ---
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

        self.layout.addStretch()

    def _on_size_slider_change(self, value):
        """Когда двигается слайдер, обновляем спинбокс и отправляем сигнал."""
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(value)
        self._size_spin.blockSignals(False)
        self.option_changed.emit("brush_size", value)

    def _on_size_spin_change(self, value):
        """Когда меняется спинбокс, обновляем слайдер и отправляем сигнал."""
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(value) # значение зажмётся в рамках слайдера
        self._size_slider.blockSignals(False)
        self.option_changed.emit("brush_size", value)

    def _get_icon(self, mask_val):
        size = 32
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.setPen(Qt.PenStyle.NoPen)
        
        if mask_val == "round":
            p.drawEllipse(4, 4, size-8, size-8)
        elif mask_val == "square":
            p.drawRect(4, 4, size-8, size-8)
        elif mask_val == "scatter":
            p.drawEllipse(8, 8, size-16, size-16)
            p.drawEllipse(4, 4, 4, 4)
            p.drawEllipse(20, 4, 6, 6)
            p.drawEllipse(6, 20, 5, 5)
            p.drawEllipse(22, 22, 3, 3)
        elif isinstance(mask_val, str) and os.path.exists(mask_val):
            p.end()
            img = QImage(mask_val)
            if not img.isNull():
                return QIcon(QPixmap.fromImage(img).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            return QIcon()
        p.end()
        return QIcon(pix)

    def _on_mask_activated(self, idx):
        data = self._mask_combo.itemData(idx)
        if data == "load_custom":
            path, _ = QFileDialog.getOpenFileName(self, "Выберите изображение для кисти", "", "Images (*.png *.jpg *.jpeg *.bmp)")
            if path:
                filename = os.path.basename(path)
                name = os.path.splitext(filename)[0]
                
                # Сохраняем копию в папку brushes для будущих запусков
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                brushes_dir = os.path.join(base_dir, "brushes")
                os.makedirs(brushes_dir, exist_ok=True)
                target_path = os.path.join(brushes_dir, filename)
                if path != target_path:
                    shutil.copy2(path, target_path)
                
                new_idx = self._mask_combo.count() - 1
                self._mask_combo.insertItem(new_idx, self._get_icon(target_path), name, target_path)
                self._mask_combo.setCurrentIndex(new_idx)
                self.option_changed.emit("brush_mask", target_path)
            else:
                self._mask_combo.setCurrentIndex(0)
                self.option_changed.emit("brush_mask", "round")
        else:
            self.option_changed.emit("brush_mask", data)

    def update_from_opts(self, opts: dict):
        # Блокируем сигналы, чтобы не вызывать option_changed при обновлении
        controls = [self._size_slider, self._size_spin, self._size_dyn_cb,
                    self._opacity_slider, self._opacity_spin, self._opacity_dyn_cb,
                    self._hardness_slider, self._hardness_spin, self._angle_spin, self._angle_random_cb,
                    self._blend_combo]
        for w in controls:
            w.blockSignals(True)

        size = opts.get("brush_size", 10)
        self._size_slider.setValue(size)
        self._size_spin.setValue(size)
        self._size_dyn_cb.setChecked(opts.get("brush_size_dynamic", False))
        self._opacity_spin.setValue(int(opts.get("brush_opacity", 1.0) * 100))
        self._opacity_dyn_cb.setChecked(opts.get("brush_opacity_dynamic", False))
        self._hardness_spin.setValue(int(opts.get("brush_hardness", 1.0) * 100))
        self._angle_spin.setValue(int(opts.get("brush_angle", 0.0)))
        self._angle_random_cb.setChecked(opts.get("brush_angle_random", False))

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
        self._mask_combo.setItemText(0, tr("opts.mask.round"))
        self._mask_combo.setItemText(1, tr("opts.mask.square"))
        self._mask_combo.setItemText(2, tr("opts.mask.scatter"))

        modes = [
            "blend.normal", "blend.multiply", "blend.screen", "blend.overlay",
            "blend.darken", "blend.lighten", "blend.color_dodge", "blend.color_burn",
            "blend.hard_light", "blend.soft_light", "blend.difference", "blend.exclusion"
        ]
        for i, loc_key in enumerate(modes):
            self._blend_combo.setItemText(i, tr(loc_key))

        self._size_dyn_cb.setText(tr("opts.dynamic"))
        self._opacity_dyn_cb.setText(tr("opts.dynamic"))
        self._angle_random_cb.setText(tr("opts.angle_random"))
        if hasattr(super(), "retranslate"):
            super().retranslate()