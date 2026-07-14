from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.locale import tr

from ui import theme

def LABEL_STYLE():
    return (f"color:{theme.SUBTEXT};font-size:11px;")
def VALUE_STYLE():
    return (f"color:{theme.TEXT};font-size:11px;")
def DARK():
    return (f"background:{theme.BASE};")


class InfoPanel(QWidget):
    """
    Displays colour information (RGBA) and cursor position (X, Y)
    for the pixel under the cursor.

    Call update_info(x, y, color) whenever the mouse moves over the canvas.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        # Title
        self._title = QLabel(self._title_text())
        self._title.setObjectName("panelTitle")
        main_layout.addWidget(self._title)

        # Grid layout for colour swatch + RGBA + XY
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        # Colour swatch — row 0, spans two columns of labels
        self._swatch = QLabel()
        self._swatch.setFixedSize(20, 20)
        theme.apply_style(self._swatch, lambda: f"background:{theme.BASE};border:1px solid {theme.SURFACE1};")
        grid.addWidget(self._swatch, 0, 0, 1, 1, Qt.AlignmentFlag.AlignTop)

        # Placeholder to keep swatch on same row
        grid.addWidget(QLabel(""), 0, 1)

        # R
        r_lbl = QLabel("R:")
        theme.apply_style(r_lbl, LABEL_STYLE)
        grid.addWidget(r_lbl, 1, 0)
        self._r_val = QLabel("—")
        theme.apply_style(self._r_val, VALUE_STYLE)
        grid.addWidget(self._r_val, 1, 1)

        # G
        g_lbl = QLabel("G:")
        theme.apply_style(g_lbl, LABEL_STYLE)
        grid.addWidget(g_lbl, 2, 0)
        self._g_val = QLabel("—")
        theme.apply_style(self._g_val, VALUE_STYLE)
        grid.addWidget(self._g_val, 2, 1)

        # B
        b_lbl = QLabel("B:")
        theme.apply_style(b_lbl, LABEL_STYLE)
        grid.addWidget(b_lbl, 3, 0)
        self._b_val = QLabel("—")
        theme.apply_style(self._b_val, VALUE_STYLE)
        grid.addWidget(self._b_val, 3, 1)

        # A
        a_lbl = QLabel("A:")
        theme.apply_style(a_lbl, LABEL_STYLE)
        grid.addWidget(a_lbl, 4, 0)
        self._a_val = QLabel("—")
        theme.apply_style(self._a_val, VALUE_STYLE)
        grid.addWidget(self._a_val, 4, 1)

        # Separator row (empty)
        grid.addWidget(QLabel(""), 5, 0)

        # X
        self._x_lbl = QLabel("X:")
        theme.apply_style(self._x_lbl, LABEL_STYLE)
        grid.addWidget(self._x_lbl, 6, 0)
        self._x_val = QLabel("—")
        theme.apply_style(self._x_val, VALUE_STYLE)
        grid.addWidget(self._x_val, 6, 1)

        # Y
        self._y_lbl = QLabel("Y:")
        theme.apply_style(self._y_lbl, LABEL_STYLE)
        grid.addWidget(self._y_lbl, 7, 0)
        self._y_val = QLabel("—")
        theme.apply_style(self._y_val, VALUE_STYLE)
        grid.addWidget(self._y_val, 7, 1)

        grid.setColumnStretch(1, 1)
        main_layout.addWidget(grid_widget)
        main_layout.addStretch()

    # ----------------------------------------------------------------- public

    def update_info(self, x: int, y: int, color: QColor):
        """Update all displayed values for the given pixel position and colour."""
        self._x_val.setText(str(x))
        self._y_val.setText(str(y))
        self._r_val.setText(str(color.red()))
        self._g_val.setText(str(color.green()))
        self._b_val.setText(str(color.blue()))
        self._a_val.setText(str(color.alpha()))
        # Swatch: show the opaque version so it is always visible
        swatch_color = QColor(color.red(), color.green(), color.blue())
        self._swatch.setStyleSheet(
            f"background:{swatch_color.name()};border:1px solid #45475a;"
        )

    def retranslate(self):
        """Update translatable strings (title only)."""
        self._title.setText(self._title_text())

    # ----------------------------------------------------------------- private

    def _title_text(self) -> str:
        val = tr("panel.info")
        return val if val != "panel.info" else "Info"
