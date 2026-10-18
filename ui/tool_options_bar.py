from PyQt6.QtWidgets import QWidget, QHBoxLayout, QStackedWidget, QScrollArea, QSizePolicy, QToolButton
from PyQt6.QtCore import pyqtSignal, Qt

from .tool_options.overflow import OptionsOverflow

class ToolOptionsBar(QWidget):
    option_changed = pyqtSignal(str, object)
    apply_styles_requested = pyqtSignal()
    apply_crop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolOptionsBar")
        self.setMinimumHeight(46)
        self.setMaximumHeight(64)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Too-wide pages overflow into the "»" popup (OptionsOverflow)
        # instead of scrolling off-screen.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        c_layout = QHBoxLayout(self._container)
        c_layout.setContentsMargins(10, 0, 10, 0)
        c_layout.setSpacing(0)

        self._stack = QStackedWidget()
        c_layout.addWidget(self._stack, 1)
        
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)
        overflow_btn = QToolButton()
        outer.addWidget(overflow_btn)
        self._overflow = OptionsOverflow(overflow_btn, self)

        self._pages: dict[str, QWidget] = {}
        self._build_pages()

    def _build_pages(self):
        from ui.tool_catalog import TOOLS
        widgets = {}   # OptionsPage -> its one widget
        for spec in TOOLS.values():
            if spec.options not in widgets:
                widgets[spec.options] = spec.options.make()
            self._pages[spec.name] = widgets[spec.options]

        for page in widgets.values():
            page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            self._stack.addWidget(page)
            if hasattr(page, "option_changed"):
                page.option_changed.connect(self.option_changed)
            if hasattr(page, "apply_styles_requested"):
                page.apply_styles_requested.connect(self.apply_styles_requested)
            if hasattr(page, "apply_crop_requested"):
                page.apply_crop_requested.connect(self.apply_crop_requested)

    def page_for(self, tool_name: str):
        """The options page shown for a tool (shared between some tools)."""
        return self._pages.get(tool_name)

    def switch_to(self, tool_name: str):
        page = self._pages.get(tool_name)
        if page:
            current = self._stack.currentWidget()
            if current and current != page:
                current.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            self._stack.setCurrentWidget(page)
            self._fit_current()

    def _fit_current(self):
        page = self._stack.currentWidget()
        if page is not None:
            self._overflow.fit(page, self._scroll.viewport().width() - 20)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_current()

    def update_tool_state(self, state: object):
        current = self._stack.currentWidget()
        if hasattr(current, "update_params"):
            current.update_params(state)

    def retranslate(self):
        # Use set to avoid updating the same panel (e.g. BrushOptions) multiple times
        for page in set(self._pages.values()):
            if hasattr(page, "retranslate"):
                page.retranslate()
