from PyQt6.QtWidgets import QComboBox

from core.blend_modes import BLEND_MODES
from core.locale import tr


class BlendModeCombo(QComboBox):
    """Combo of core.blend_modes.BLEND_MODES; item data = stored value."""

    def __init__(self, parent=None):
        super().__init__(parent)
        for value, key in BLEND_MODES:
            self.addItem(tr(key), value)

    def value(self) -> str:
        return self.currentData()

    def set_value(self, value: str):
        idx = self.findData(value)
        if idx >= 0:
            self.setCurrentIndex(idx)

    def retranslate(self):
        for i, (_, key) in enumerate(BLEND_MODES):
            self.setItemText(i, tr(key))
