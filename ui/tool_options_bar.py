from PyQt6.QtWidgets import QWidget, QHBoxLayout, QStackedWidget
from PyQt6.QtCore import pyqtSignal

from .tool_options.brush_options import BrushOptions
from .tool_options.eraser_options import EraserOptions
from .tool_options.fill_options import FillOptions
from .tool_options.gradient_options import GradientOptions
from .tool_options.select_options import SelectOptions
from .tool_options.shapes_options import ShapesOptions
from .tool_options.text_options import TextOptions
from .tool_options.crop_options import CropOptions
from .tool_options.perspective_crop_options import PerspectiveCropOptions
from .tool_options.effect_options import EffectOptions
from .tool_options.rotate_view_options import RotateViewOptions
from .tool_options.empty_options import EmptyOptions


class ToolOptionsBar(QWidget):
    option_changed = pyqtSignal(str, object)
    apply_styles_requested = pyqtSignal()
    apply_crop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolOptionsBar")
        self.setFixedHeight(42)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 0, 10, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        self._pages: dict[str, QWidget] = {}
        self._build_pages()

    def _build_pages(self):
        self._pages["Brush"] = BrushOptions()
        self._pages["Eraser"] = EraserOptions()
        self._pages["Fill"] = FillOptions()
        self._pages["Gradient"] = GradientOptions()
        self._pages["Select"] = SelectOptions()
        self._pages["EllipseSelect"] = self._pages["Select"]
        self._pages["Shapes"] = ShapesOptions()
        self._pages["Text"] = TextOptions()
        self._pages["TextV"] = self._pages["Text"]
        self._pages["TextHMask"] = self._pages["Text"]
        self._pages["TextVMask"] = self._pages["Text"]
        self._pages["Move"] = EmptyOptions("tool.move")
        self._pages["Eyedropper"] = EmptyOptions("tool.eyedropper")
        self._pages["Crop"] = CropOptions()
        self._pages["Perspective Crop"] = PerspectiveCropOptions()
        self._pages["Blur"] = EffectOptions("opts.effect.blur")
        self._pages["Sharpen"] = EffectOptions("opts.effect.sharpen")
        self._pages["Smudge"] = EffectOptions("opts.effect.smudge")
        self._pages["Hand"] = EmptyOptions("opts.hand_hint")
        self._pages["Zoom"] = EmptyOptions("opts.zoom_hint")
        self._pages["RotateView"] = RotateViewOptions()
        self._pages["Lasso"] = self._pages["Select"]
        self._pages["PolygonalLasso"] = self._pages["Select"]
        self._pages["MagneticLasso"] = self._pages["Select"]

        for name, page in self._pages.items():
            self._stack.addWidget(page)
            if hasattr(page, "option_changed"):
                page.option_changed.connect(self.option_changed)
            if hasattr(page, "apply_styles_requested"):
                page.apply_styles_requested.connect(self.apply_styles_requested)
            if hasattr(page, "apply_crop_requested"):
                page.apply_crop_requested.connect(self.apply_crop_requested)

    def switch_to(self, tool_name: str):
        page = self._pages.get(tool_name)
        if page:
            self._stack.setCurrentWidget(page)
