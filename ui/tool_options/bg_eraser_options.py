from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QSpinBox
from PyQt6.QtCore import Qt
from .base_options import BaseOptions

class BackgroundEraserOptions(BaseOptions):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Блок размера кисти ---
        self.layout.addWidget(self._lbl("opts.size"))

        size_widget = QWidget()
        size_layout = QHBoxLayout(size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(1, 500)
        self._size_slider.setFixedWidth(100)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 500)

        # Синхронизируем ползунок и спинбокс друг с другом
        self._size_slider.valueChanged.connect(self._size_spin.setValue)
        self._size_spin.valueChanged.connect(self._size_slider.setValue)

        # Отправляем сигнал в ядро только при изменении спинбокса (он синхронен с ползунком)
        self._size_spin.valueChanged.connect(lambda v: self.option_changed.emit("brush_size", v))

        size_layout.addWidget(self._size_slider)
        size_layout.addWidget(self._size_spin)
        self.layout.addWidget(size_widget)


        # --- Блок чувствительности (Tolerance) ---
        self.layout.addWidget(self._lbl("opts.tolerance"))

        tol_widget = QWidget()
        tol_layout = QHBoxLayout(tol_widget)
        tol_layout.setContentsMargins(0, 0, 0, 0)

        self._tol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tol_slider.setRange(0, 100)
        self._tol_slider.setFixedWidth(100)

        self._tol_spin = QSpinBox()
        self._tol_spin.setRange(0, 100)
        self._tol_spin.setSuffix("%") # Добавим знак процента для красоты

        # Синхронизация
        self._tol_slider.valueChanged.connect(self._tol_spin.setValue)
        self._tol_spin.valueChanged.connect(self._tol_slider.setValue)

        # Отправляем сигнал
        self._tol_spin.valueChanged.connect(lambda v: self.option_changed.emit("fill_tolerance", v))

        tol_layout.addWidget(self._tol_slider)
        tol_layout.addWidget(self._tol_spin)
        self.layout.addWidget(tol_widget)

        self.layout.addStretch()

    def update_from_opts(self, opts: dict):
        # Достаточно обновить только спинбоксы, ползунки подтянутся автоматически
        self._size_spin.setValue(opts.get("brush_size", 20))
        self._tol_spin.setValue(opts.get("fill_tolerance", 20))
