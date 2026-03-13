from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton)
from PyQt6.QtCore import pyqtSignal
from .base_options import BaseOptions
from core.locale import tr


class PerspectiveCropOptions(BaseOptions):
    apply_crop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout.addWidget(self._lbl("opts.crop_hint"))
        apply_btn = QPushButton(tr("menu.apply_perspective_crop"))
        apply_btn.setObjectName("smallBtn")
        apply_btn.setFixedHeight(26)
        apply_btn.clicked.connect(self.apply_crop_requested.emit)
        self.layout.addWidget(apply_btn)
        self.layout.addStretch()
