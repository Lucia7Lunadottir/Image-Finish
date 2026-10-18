from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal

from core.locale import tr
from ui.brush_widgets import BrushTipGrid


class BrushesPanel(QWidget):
    """Every brush tip (ui/brush_widgets.py library); clicking one emits
    brush_selected(tip value)."""

    brush_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._title = QLabel(tr("panel.brushes"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        self._grid = BrushTipGrid(columns=3, thumb=64)
        self._grid.tip_selected.connect(self.brush_selected)
        layout.addWidget(self._grid, 1)

    def refresh(self, canvas):
        """Highlight the tip the canvas currently uses."""
        opts = getattr(canvas, "tool_opts", None) or {}
        self._grid.set_current(opts.get("brush_mask", "round"))

    def retranslate(self):
        self._title.setText(tr("panel.brushes"))
