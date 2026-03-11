from PyQt6.QtGui import QImage, QColor
from PyQt6.QtCore import Qt, QPoint


class Layer:
    """Represents a single layer in the document."""

    BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay"]

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        self.name = name
        self.visible: bool = True
        self.locked: bool = False
        self.opacity: float = 1.0
        self.blend_mode: str = "Normal"
        self.offset: QPoint = QPoint(0, 0)

        self.image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        if fill_color:
            self.image.fill(fill_color)
        else:
            self.image.fill(Qt.GlobalColor.transparent)

        self.text_data: dict | None = None  # хранит параметры текста для повторного редактирования

    # ------------------------------------------------------------------
    def copy(self) -> "Layer":
        clone = Layer.__new__(Layer)
        clone.name = self.name
        clone.visible = self.visible
        clone.locked = self.locked
        clone.opacity = self.opacity
        clone.blend_mode = self.blend_mode
        clone.offset = QPoint(self.offset)
        clone.image = self.image.copy()
        td = getattr(self, "text_data", None)
        clone.text_data = dict(td) if td else None
        return clone

    def width(self) -> int:
        return self.image.width()

    def height(self) -> int:
        return self.image.height()

    def __repr__(self) -> str:
        return f"<Layer '{self.name}' {self.width()}x{self.height()} visible={self.visible}>"
