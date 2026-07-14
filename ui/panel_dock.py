"""Dockable wrapper for side panels (Photoshop-style)."""

from PyQt6.QtWidgets import QDockWidget, QWidget
from PyQt6.QtCore import Qt

from core.locale import tr


class PanelDock(QDockWidget):
    """QDockWidget with the conventions every panel dock needs:
    a stable objectName (required for QMainWindow.saveState) and a
    tr()-key-based title that survives language switches.

    Photoshop-style chrome: while docked the title bar is hidden (the tab
    carries the caption and the drag handle); when floated the normal
    title bar comes back so the window can be moved and closed."""

    def __init__(self, key: str, widget, parent=None):
        super().__init__(parent)
        self._tr_key = key
        # objectName must be stable across versions/languages for saveState.
        self.setObjectName("dock_" + key.replace(".", "_"))
        self.setWidget(widget)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self._no_title = QWidget(self)
        self._no_title.setFixedHeight(0)
        self.topLevelChanged.connect(self._on_top_level_changed)
        self._on_top_level_changed(False)
        self.retranslate()

    def _on_top_level_changed(self, floating: bool):
        self.setTitleBarWidget(None if floating else self._no_title)

    def retranslate(self):
        self.setWindowTitle(tr(self._tr_key))
