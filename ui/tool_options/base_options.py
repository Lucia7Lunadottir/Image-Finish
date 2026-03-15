from PyQt6.QtWidgets import QWidget, QHBoxLayout
from PyQt6.QtCore import pyqtSignal


class BaseOptions(QWidget):
    option_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)

    def _lbl(self, key: str):
        from core.locale import tr
        from PyQt6.QtWidgets import QLabel
        lbl = QLabel(tr(key))
        lbl.setObjectName("optLabel")
        return lbl

    def retranslate(self):
        pass
