from PyQt6.QtGui import QImage, QPainter, QColor, QPainterPath, QLinearGradient, QBrush
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint
from .layer import Layer


def _apply_layer_adjustment(image: QImage, layer) -> QImage:
    d = layer.adjustment_data or {}
    t = d.get("type", "")
    try:
        from ui.adjustments_dialog import (apply_brightness_contrast,
                                           apply_hue_saturation, apply_invert)
        if t == "brightness_contrast":
            return apply_brightness_contrast(image, d.get("brightness", 0), d.get("contrast", 0))
        if t == "hue_saturation":
            return apply_hue_saturation(image, d.get("hue", 0),
                                        d.get("saturation", 0), d.get("lightness", 0))
        if t == "invert":
            return apply_invert(image)
    except Exception:
        pass
    return image


def _render_fill_layer(layer, w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    d = layer.fill_data or {}
    p = QPainter(img)
    ft = d.get("type", "solid")
    if ft == "solid":
        p.fillRect(img.rect(), d.get("color", QColor(128, 128, 128)))
    elif ft == "gradient":
        c1 = d.get("color1", QColor(0, 0, 0))
        c2 = d.get("color2", QColor(255, 255, 255))
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.fillRect(img.rect(), QBrush(grad))
    p.end()
    return img


class Document:
    """
    Holds all layers, document size, and selection state.
    The single source of truth for image data.
    """

    def __init__(self, width: int = 800, height: int = 600, bg_color: QColor = None):
        self.width: int = width
        self.height: int = height
        self.layers: list[Layer] = []
        self.active_layer_index: int = 0
        self.selection: QPainterPath | None = None  # active selection (may be non-rectangular)

        # Create default background layer
        bg = bg_color if bg_color else QColor(255, 255, 255)
        self.add_layer(name="Background", fill_color=bg)

    # ------------------------------------------------------------------ Layers
    def add_layer(self, name: str = None, index: int = None,
                  fill_color: QColor = None) -> Layer:
        if name is None:
            name = f"Layer {len(self.layers) + 1}"
        layer = Layer(name, self.width, self.height, fill_color)
        if index is None:
            self.layers.append(layer)
            self.active_layer_index = len(self.layers) - 1
        else:
            self.layers.insert(index, layer)
            self.active_layer_index = index
        return layer

    def duplicate_layer(self, index: int) -> Layer:
        src = self.layers[index]
        clone = src.copy()
        clone.name = f"{src.name} copy"
        self.layers.insert(index + 1, clone)
        self.active_layer_index = index + 1
        return clone

    def remove_layer(self, index: int):
        if len(self.layers) <= 1:
            return  # always keep at least one layer
        self.layers.pop(index)
        self.active_layer_index = max(0, min(self.active_layer_index, len(self.layers) - 1))

    def move_layer(self, from_index: int, to_index: int):
        """Move layer up/down in the stack."""
        if from_index < 0 or from_index >= len(self.layers):
            return
        to_index = max(0, min(to_index, len(self.layers) - 1))
        layer = self.layers.pop(from_index)
        self.layers.insert(to_index, layer)
        self.active_layer_index = to_index

    def get_active_layer(self) -> Layer | None:
        if self.layers and 0 <= self.active_layer_index < len(self.layers):
            return self.layers[self.active_layer_index]
        return None

    # ---------------------------------------------------------------- Composite
    def get_composite(self) -> QImage:
        result = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)

        painter = QPainter(result)
        for layer in self.layers:  # bottom → top
            if not layer.visible:
                continue
            ltype = getattr(layer, "layer_type", "raster")

            if ltype == "adjustment":
                painter.end()
                result = _apply_layer_adjustment(result, layer)
                painter = QPainter(result)

            elif ltype == "fill":
                fill_img = _render_fill_layer(layer, self.width, self.height)
                painter.setOpacity(layer.opacity)
                painter.drawImage(layer.offset, fill_img)

            else:
                painter.setOpacity(layer.opacity)
                painter.drawImage(layer.offset, layer.image)

        if painter.isActive():
            painter.end()
        return result

    # ----------------------------------------------------------------- History
    def snapshot_layers(self) -> list[Layer]:
        return [layer.copy() for layer in self.layers]

    def restore_layers(self, snapshot: list[Layer]):
        self.layers = [layer.copy() for layer in snapshot]

    # ------------------------------------------------------------------- Crop
    def apply_crop(self, rect: QRect):
        if rect.isEmpty():
            return
        for layer in self.layers:
            new_img = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            p = QPainter(new_img)
            p.drawImage(0, 0, layer.image, rect.x(), rect.y(), rect.width(), rect.height())
            p.end()
            layer.image = new_img
            layer.offset = QPoint(0, 0)
        self.width = rect.width()
        self.height = rect.height()
        self.selection = None

    # ------------------------------------------------------------------ Flatten
    def flatten(self):
        composite = self.get_composite()
        self.layers.clear()
        bg = Layer("Background", self.width, self.height)
        bg.image = composite
        self.layers.append(bg)
        self.active_layer_index = 0

    def __repr__(self) -> str:
        return f"<Document {self.width}x{self.height} layers={len(self.layers)}>"
