from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, Qt

from core.locale import tr


class ToolBar(QWidget):
    """
    Vertical toolbar on the left side.
    Emits tool_selected(tool_name) when a button is clicked.
    """

    tool_selected = pyqtSignal(str)

    # (internal_name, icon, shortcut, tr_key)
    _TOOLS = [
        ("Move",       "✋",  "V", "tool.move"),
        ("Brush",      "🖌️", "B", "tool.brush"),
        ("Eraser",     "🧹",  "E", "tool.eraser"),
        ("Fill",       "🪣",  "G", "tool.fill"),
        ("Blur",       "💧",  "R", "tool.blur"),
        ("Sharpen",    "🔺",  "Y", "tool.sharpen"),
        ("Smudge",     "👆",  "W", "tool.smudge"),
        ("Select",     "⬜",  "M", "tool.select"),
        ("Shapes",     "🔷",  "U", "tool.shapes"),
        ("Text",       "T",   "T", "tool.text"),
        ("TextV",      "Tv",  "",  "tool.text_v"),
        ("TextHMask",  "Tm",  "",  "tool.text_h_mask"),
        ("TextVMask",  "Vm",  "",  "tool.text_v_mask"),
        ("Eyedropper", "💉",  "I", "tool.eyedropper"),
        ("Crop",       "✂️",  "C", "tool.crop"),
        ("Hand",       "🖐",  "H", "tool.hand"),
        ("Zoom",       "🔍",  "Z", "tool.zoom"),
        ("RotateView", "🔄",  "",  "tool.rotate_view"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setFixedWidth(54)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._buttons: dict[str, QPushButton] = {}

        for name, icon, shortcut, key in self._TOOLS:
            btn = QPushButton(icon)
            btn.setObjectName("toolBtn")
            btn.setToolTip(self._make_tip(key, shortcut))
            btn.setCheckable(False)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, n=name: self._on_click(n))
            layout.addWidget(btn)
            self._buttons[name] = btn

        layout.addStretch()

        self.set_active("Brush")

    @staticmethod
    def _make_tip(key: str, shortcut: str) -> str:
        label = tr(key)
        return f"{label}  [{shortcut}]" if shortcut else label

    def retranslate(self):
        """Update all button tooltips to the current locale."""
        for name, _icon, shortcut, key in self._TOOLS:
            btn = self._buttons.get(name)
            if btn:
                btn.setToolTip(self._make_tip(key, shortcut))

    def set_active(self, tool_name: str):
        for name, btn in self._buttons.items():
            btn.setProperty("active", name == tool_name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_click(self, name: str):
        self.set_active(name)
        self.tool_selected.emit(name)
