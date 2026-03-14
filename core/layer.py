from PyQt6.QtGui import QImage, QColor
from PyQt6.QtCore import Qt, QPoint


class Layer:
    """Represents a single layer in the document."""

    BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay"]

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        self.name = name
        self.visible: bool = True
        self.locked: bool = False
        self.lock_alpha: bool = False
        self.mask: QImage | None = None
        self.mask_enabled: bool = True
        self.editing_mask: bool = False
        self.opacity: float = 1.0
        self.blend_mode: str = "Normal"
        self.offset: QPoint = QPoint(0, 0)

        # "raster" | "text" | "vector" | "adjustment" | "fill" | "smart_object"
        self.layer_type: str = "raster"

        self.image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        if fill_color:
            self.image.fill(fill_color)
        else:
            self.image.fill(Qt.GlobalColor.transparent)

        self.text_data: dict | None = None        # text layer params
        self.shape_data: dict | None = None       # vector layer params
        self.adjustment_data: dict | None = None  # adjustment layer params
        self.fill_data: dict | None = None        # fill layer params
        self.smart_data: dict | None = None       # smart object (stores original QImage)

    # ------------------------------------------------------------------
    def copy(self) -> "Layer":
        clone = Layer.__new__(Layer)
        clone.name = self.name
        clone.visible = self.visible
        clone.locked = self.locked
        clone.lock_alpha = getattr(self, "lock_alpha", False)
        if getattr(self, "mask", None) is not None:
            clone.mask = self.mask.copy()
        else:
            clone.mask = None
        clone.mask_enabled = getattr(self, "mask_enabled", True)
        clone.editing_mask = getattr(self, "editing_mask", False)
        clone.opacity = self.opacity
        clone.blend_mode = self.blend_mode
        clone.offset = QPoint(self.offset)
        clone.image = self.image.copy()
        clone.layer_type = getattr(self, "layer_type", "raster")
        td = getattr(self, "text_data", None)
        clone.text_data = dict(td) if td else None
        sd = getattr(self, "shape_data", None)
        clone.shape_data = dict(sd) if sd else None
        ad = getattr(self, "adjustment_data", None)
        clone.adjustment_data = dict(ad) if ad else None
        fd = getattr(self, "fill_data", None)
        clone.fill_data = dict(fd) if fd else None
        smd = getattr(self, "smart_data", None)
        if smd:
            clone.smart_data = {"original": smd["original"].copy()}
        else:
            clone.smart_data = None
        return clone

    def width(self) -> int:
        return self.image.width()

    def height(self) -> int:
        return self.image.height()

    def __repr__(self) -> str:
        return f"<Layer '{self.name}' {self.width()}x{self.height()} visible={self.visible}>"
