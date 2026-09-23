"""Widget-construction helpers shared by every text-related options
surface (`ui/character_panel.py`, `ui/tool_options/text_options.py`), so a
B/I/U/S style-toggle button is built the same way once instead of once
per panel. Each panel still owns its own styling and decides what its
`option_changed` signal emits — this only builds the widget."""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtGui import QFont


def make_style_toggle_btn(label: str, font: QFont | None = None,
                          size: tuple[int, int] = (28, 28)) -> QPushButton:
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setFixedSize(*size)
    if font:
        btn.setFont(font)
    return btn
