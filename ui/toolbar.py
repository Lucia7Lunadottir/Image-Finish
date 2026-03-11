from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, Qt


class ToolBar(QWidget):
    """
    Vertical toolbar on the left side.
    Emits tool_selected(tool_name) when a button is clicked.
    """

    tool_selected = pyqtSignal(str)

    _TOOLS = [
        ("Move",        "✋", "V"),
        ("Brush",       "🖌️", "B"),
        ("Eraser",      "🧹", "E"),
        ("Fill",        "🪣", "G"),
        ("Blur",        "💧", "R"),
        ("Sharpen",     "🔺", "Y"),
        ("Smudge",      "👆", "W"),
        ("Select",      "⬜", "M"),
        ("Shapes",      "🔷", "U"),
        ("Text",        "T",  "T"),
        ("Eyedropper",  "💉", "I"),
        ("Crop",        "✂️", "C"),
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

        for name, icon, shortcut in self._TOOLS:
            btn = QPushButton(icon)
            btn.setObjectName("toolBtn")
            btn.setToolTip(f"{name}  [{shortcut}]")
            btn.setCheckable(False)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, n=name: self._on_click(n))
            layout.addWidget(btn)
            self._buttons[name] = btn

        layout.addStretch()

        # Select "Move" by default
        self.set_active("Brush")

    def set_active(self, tool_name: str):
        for name, btn in self._buttons.items():
            btn.setProperty("active", name == tool_name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_click(self, name: str):
        self.set_active(name)
        self.tool_selected.emit(name)
