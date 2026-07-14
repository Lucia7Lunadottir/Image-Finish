"""Construction and layout of all side panels as dockable widgets.

Single responsibility: build the 16 panels, wrap them in PanelDock and
arrange the Photoshop-like default workspace on the main window. The
panels themselves are still exposed as `window._layers_panel` etc. so the
existing signal wiring in MainWindow keeps working unchanged.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget

from core.app_logging import get_logger
from ui.panel_dock import PanelDock

logger = get_logger("panel_manager")

_RIGHT = Qt.DockWidgetArea.RightDockWidgetArea


class PanelManager:
    # (tr key, window attribute); construction order == Window-menu order
    PANEL_DEFS = [
        ("panel.color",        "_color_panel"),
        ("panel.swatches_tab", "_swatches_panel"),
        ("panel.properties",   "_properties_panel"),
        ("panel.navigator",    "_navigator_panel"),
        ("panel.histogram",    "_histogram_panel"),
        ("panel.info",         "_info_panel"),
        ("panel.history",      "_history_panel"),
        ("panel.actions",      "_actions_panel"),
        ("panel.layers",       "_layers_panel"),
        ("panel.channels",     "_channels_panel"),
        ("panel.paths",        "_paths_panel"),
        ("panel.brushes",      "_brushes_panel"),
        ("panel.tool_presets", "_tool_presets_panel"),
        ("panel.character",    "_character_panel"),
        ("panel.paragraph",    "_paragraph_panel"),
        ("panel.glyphs",       "_glyphs_panel"),
    ]

    # Hidden until enabled from the Window menu (matches Photoshop defaults)
    HIDDEN_BY_DEFAULT = {
        "panel.brushes", "panel.tool_presets",
        "panel.character", "panel.paragraph", "panel.glyphs",
    }

    def __init__(self, window):
        self._window = window
        self.docks: dict[str, PanelDock] = {}
        self._build_panels(window)
        self._build_docks(window)
        self.apply_default_layout()

    # ── construction ─────────────────────────────────────────────────────
    def _build_panels(self, w):
        from ui.color_panel        import ColorPanel
        from ui.layers_panel       import LayersPanel
        from ui.channels_panel     import ChannelsPanel
        from ui.history_panel      import HistoryPanel
        from ui.navigator_panel    import NavigatorPanel
        from ui.info_panel         import InfoPanel
        from ui.histogram_panel    import HistogramPanel
        from ui.brushes_panel      import BrushesPanel
        from ui.swatches_panel     import SwatchesPanel
        from ui.paths_panel        import PathsPanel
        from ui.properties_panel   import PropertiesPanel
        from ui.actions_panel      import ActionsPanel
        from ui.tool_presets_panel import ToolPresetsPanel
        from ui.character_panel    import CharacterPanel
        from ui.paragraph_panel    import ParagraphPanel
        from ui.glyphs_panel       import GlyphsPanel

        w._color_panel        = ColorPanel()
        w._layers_panel       = LayersPanel()
        w._channels_panel     = ChannelsPanel()
        w._history_panel      = HistoryPanel()
        w._navigator_panel    = NavigatorPanel()
        w._info_panel         = InfoPanel()
        w._histogram_panel    = HistogramPanel()
        w._brushes_panel      = BrushesPanel()
        w._swatches_panel     = SwatchesPanel()
        w._paths_panel        = PathsPanel()
        w._properties_panel   = PropertiesPanel()
        w._actions_panel      = ActionsPanel()
        w._tool_presets_panel = ToolPresetsPanel()
        w._character_panel    = CharacterPanel()
        w._paragraph_panel    = ParagraphPanel()
        w._glyphs_panel       = GlyphsPanel()

        w._layers_panel._title_lbl.hide()

    def _build_docks(self, w):
        from PyQt6.QtWidgets import QMainWindow
        w.setDockNestingEnabled(True)
        w.setDockOptions(w.dockOptions() | QMainWindow.DockOption.GroupedDragging)
        w.setTabPosition(_RIGHT, QTabWidget.TabPosition.North)
        for key, attr in self.PANEL_DEFS:
            panel = getattr(w, attr)
            # The dock tab now carries the caption — internal headers are noise
            for attr_name in ("_title_lbl", "_title"):
                title_lbl = getattr(panel, attr_name, None)
                if title_lbl is not None and hasattr(title_lbl, "hide"):
                    title_lbl.hide()
            self.docks[key] = PanelDock(key, self._shrinkable(panel), w)

    @staticmethod
    def _shrinkable(panel):
        """Wrap a panel in a frameless scroll area so the dock column can be
        narrowed below the panel's natural minimum (content scrolls)."""
        from PyQt6.QtWidgets import QScrollArea
        area = QScrollArea()
        area.setWidget(panel)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setMinimumWidth(120)
        area.viewport().setAutoFillBackground(False)
        return area

    # ── layout ───────────────────────────────────────────────────────────
    def apply_default_layout(self):
        """Photoshop-like default: color on top, properties/navigation in
        the middle, layers at the bottom; extras hidden."""
        w = self._window
        d = self.docks

        for dock in d.values():
            w.removeDockWidget(dock)

        top    = d["panel.color"]
        middle = d["panel.properties"]
        bottom = d["panel.layers"]

        w.addDockWidget(_RIGHT, top)
        w.addDockWidget(_RIGHT, middle)
        w.addDockWidget(_RIGHT, bottom)
        w.splitDockWidget(top, middle, Qt.Orientation.Vertical)
        w.splitDockWidget(middle, bottom, Qt.Orientation.Vertical)

        for key in ("panel.swatches_tab",):
            w.tabifyDockWidget(top, d[key])
        for key in ("panel.navigator", "panel.histogram", "panel.info",
                    "panel.history", "panel.actions"):
            w.tabifyDockWidget(middle, d[key])
        for key in ("panel.channels", "panel.paths", "panel.brushes",
                    "panel.tool_presets", "panel.character",
                    "panel.paragraph", "panel.glyphs"):
            w.tabifyDockWidget(bottom, d[key])

        for key, dock in d.items():
            dock.setFloating(False)
            dock.setVisible(key not in self.HIDDEN_BY_DEFAULT)

        # Bring the primary tab of each group to the front
        top.raise_(); middle.raise_(); bottom.raise_()

        try:
            w.resizeDocks([top, middle, bottom], [140, 260, 320], Qt.Orientation.Vertical)
            w.resizeDocks([top], [300], Qt.Orientation.Horizontal)
        except Exception:
            logger.debug("resizeDocks failed", exc_info=True)

    # ── services for MainWindow ──────────────────────────────────────────
    def toggle_actions(self):
        """(tr_key, QAction) pairs for the Window menu. Action text follows
        the dock title automatically, including on language switches."""
        return [(key, self.docks[key].toggleViewAction())
                for key, _attr in self.PANEL_DEFS]

    def retranslate(self):
        for dock in self.docks.values():
            dock.retranslate()
