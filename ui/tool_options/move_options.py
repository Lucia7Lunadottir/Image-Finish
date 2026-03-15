from PyQt6.QtWidgets import QPushButton, QLabel
from .base_options import BaseOptions
from core.locale import tr

class MoveOptions(BaseOptions):
    def __init__(self, hint_key="opts.move_hint", parent=None):
        super().__init__(parent)
        self._hint_key = hint_key
        self._hint_lbl = QLabel(tr(self._hint_key))
        self._hint_lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-weight: bold;")
        self.layout.addWidget(self._hint_lbl)
        
        self.layout.addSpacing(20)

        self._apply_btn = QPushButton("✔ " + tr("opts.apply"))
        self._apply_btn.setObjectName("smallBtn")
        self._apply_btn.clicked.connect(lambda: self.option_changed.emit("move_apply", True))
        self.layout.addWidget(self._apply_btn)

        self._cancel_btn = QPushButton("✖ " + tr("opts.cancel"))
        self._cancel_btn.setObjectName("smallBtn")
        self._cancel_btn.clicked.connect(lambda: self.option_changed.emit("move_cancel", True))
        self.layout.addWidget(self._cancel_btn)
        
        self.layout.addStretch()

    def retranslate(self):
        self._hint_lbl.setText(tr(self._hint_key))
        self._apply_btn.setText("✔ " + tr("opts.apply"))
        self._cancel_btn.setText("✖ " + tr("opts.cancel"))
        super().retranslate()