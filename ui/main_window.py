from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QMenu, QStatusBar, QFileDialog, QMessageBox, QTabWidget,
                             QStackedWidget)
from PyQt6.QtCore import Qt, QRectF, QRect, QPoint, QPointF
from PyQt6.QtGui import QAction, QColor, QPainterPath

from ui.canvas_widget       import CanvasWidget
from ui.document_controller import DocumentController, require_document
from ui.toolbar          import ToolBar
from ui.tool_options_bar import ToolOptionsBar

from ui.actions.file_actions       import FileActionsMixin
from ui.actions.edit_actions       import EditActionsMixin
from ui.actions.layer_actions      import LayerActionsMixin
from ui.actions.image_actions      import ImageActionsMixin
from ui.actions.adjustment_actions import AdjustmentActionsMixin
from ui.actions.filter_actions     import FilterActionsMixin
from ui.actions.panel_actions      import PanelActionsMixin
from ui.actions.shape_actions      import ShapeActionsMixin
from ui.actions.text_actions       import TextActionsMixin

from core.app_logging import get_logger
from core.document import Document
from core.history  import HistoryState
from core.locale   import tr, available_languages, load as locale_load, current as locale_current

logger = get_logger("main_window")


# ── Tool registry ──────────────────────────────────────────────────────────────
def _build_tool_registry(text_parent):
    from tools.brush_tool   import (BrushTool, EraserTool, CloneStampTool, PatternStampTool,
                                    PencilTool, ColorReplacementTool, MixerBrushTool, HistoryBrushTool)
    from tools.fill_tool    import FillTool
    from tools.effect_tools import BlurTool, SharpenTool, SmudgeTool, DodgeTool, BurnTool, SpongeTool
    from tools.other_tools  import (SelectTool, MoveTool, EyedropperTool,
                                    EllipticalSelectTool,
                                    CropTool, TextTool, ShapesTool,
                                    VerticalTypeTool, HorizontalTypeMaskTool,
                                    VerticalTypeMaskTool,
                                    HandTool, ZoomTool, RotateViewTool,
                                    GradientTool, PerspectiveCropTool)
    from tools.lasso_tools import LassoTool, PolygonalLassoTool, MagneticLassoTool
    from tools.measure_tools import ColorSamplerTool, RulerTool
    from tools.advanced_erasers import MagicEraserTool, BackgroundEraserTool
    from tools.magic_wand_tool import MagicWandTool, QuickSelectionTool, ObjectSelectionTool
    from tools.artboard_tool import ArtboardTool
    from tools.warp_tool import WarpTool
    from tools.puppet_warp_tool import PuppetWarpTool
    from tools.perspective_warp_tool import PerspectiveWarpTool
    from tools.slice_tool import SliceTool
    from tools.patch_tool import PatchTool, SpotHealingTool, HealingBrushTool, RedEyeTool
    from tools.pen_tool import (PenTool, FreeformPenTool, CurvaturePenTool, 
                                AddAnchorPointTool, DeleteAnchorPointTool, ConvertPointTool,
                                PathSelectionTool, DirectSelectionTool)
    from tools.frame_tool import FrameTool

    text = TextTool();  text._parent_widget  = text_parent
    textv = VerticalTypeTool(); textv._parent_widget = text_parent
    texthm = HorizontalTypeMaskTool(); texthm._parent_widget = text_parent
    textvm = VerticalTypeMaskTool();   textvm._parent_widget = text_parent
    return {
        "Brush":      BrushTool(),
        "Eraser":           EraserTool(),
        "BackgroundEraser": BackgroundEraserTool(),
        "MagicEraser":      MagicEraserTool(),
        "CloneStamp":       CloneStampTool(),
        "PatternStamp":     PatternStampTool(),
        "Pencil":           PencilTool(),
        "ColorReplacement": ColorReplacementTool(),
        "MixerBrush":       MixerBrushTool(),
        "HistoryBrush":     HistoryBrushTool(),
        "Fill":       FillTool(),
        "Blur":       BlurTool(),
        "Sharpen":    SharpenTool(),
        "Smudge":     SmudgeTool(),
        "Dodge":      DodgeTool(),
        "Burn":       BurnTool(),
        "Sponge":     SpongeTool(),
        "Select":     SelectTool(),
        "EllipseSelect": EllipticalSelectTool(),
        "Move":       MoveTool(),
        "Warp":       WarpTool(),
        "PuppetWarp": PuppetWarpTool(),
        "PerspectiveWarp": PerspectiveWarpTool(),
        "Artboard":   ArtboardTool(),
        "Eyedropper": EyedropperTool(),
        "ColorSampler": ColorSamplerTool(),
        "Ruler":      RulerTool(),
        "Crop":       CropTool(),
        "Perspective Crop": PerspectiveCropTool(),
        "Slice":      SliceTool(),
        "SpotHealing":SpotHealingTool(),
        "HealingBrush":HealingBrushTool(),
        "Patch":      PatchTool(),
        "RedEye":     RedEyeTool(),
        "Text":       text,
        "Pen":        PenTool(),
        "FreeformPen":FreeformPenTool(),
        "CurvaturePen":CurvaturePenTool(),
        "AddAnchor":  AddAnchorPointTool(),
        "DeleteAnchor":DeleteAnchorPointTool(),
        "ConvertPoint":ConvertPointTool(),
        "PathSelection":PathSelectionTool(),
        "DirectSelection":DirectSelectionTool(),
        "Frame":      FrameTool(),
        "TextV":      textv,
        "TextHMask":  texthm,
        "TextVMask":  textvm,
        "Shapes":     ShapesTool(),
        "Gradient":   GradientTool(),
        "Hand":       HandTool(),
        "Zoom":       ZoomTool(),
        "RotateView": RotateViewTool(),
        "Lasso":          LassoTool(),
        "PolygonalLasso": PolygonalLassoTool(),
        "MagneticLasso":  MagneticLassoTool(),
        "MagicWand": MagicWandTool(),
        "QuickSelection": QuickSelectionTool(),
        "ObjectSelection": ObjectSelectionTool(),
    }


# ── Main window ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow,
                 FileActionsMixin,
                 EditActionsMixin,
                 LayerActionsMixin,
                 ImageActionsMixin,
                 AdjustmentActionsMixin,
                 FilterActionsMixin,
                 PanelActionsMixin,
                 ShapeActionsMixin,
                 TextActionsMixin):

    @property
    def _canvas(self) -> CanvasWidget:
        if hasattr(self, "_doc_controller"):
            return self._doc_controller.canvas()
        return None

    @property
    def _document(self):
        if hasattr(self, "_doc_controller"):
            return self._doc_controller.document()
        return None

    @_document.setter
    def _document(self, val): pass

    @property
    def _history(self):
        if hasattr(self, "_doc_controller"):
            return self._doc_controller.history()
        return None

    @_history.setter
    def _history(self, val): pass

    @property
    def _filepath(self):
        c = self._canvas
        return getattr(c, "filepath", None) if c else None

    @_filepath.setter
    def _filepath(self, path):
        c = self._canvas
        if c:
            c.filepath = path
            self._update_title()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("title.untitled", mode="RGB/8"))

        self._recent_files = []
        self._load_recent_files()

        self.setAcceptDrops(True)
        self._tools    = _build_tool_registry(self)
        self._active_tool_name = "Brush"

        self._all_acts:  list[tuple[str, QAction]] = []
        self._all_menus: list[tuple[str, QMenu]]   = []
        self._lang_acts: dict[str, QAction] = {}

        self._build_ui()

        from ui import workspace
        workspace.restore(self)

        from tools.base_tool import AbstractAsyncTool
        for tool in self._tools.values():
            if isinstance(tool, AbstractAsyncTool):
                tool.set_liveness_check(self._doc_controller.is_alive)

        self._welcome_panel.refresh_recent(self._recent_files)

        self._wire_signals()
        self._activate_tool("Brush")

    # ================================================================== UI Build
    def _build_ui(self):
        from ui.styles import DARK_STYLE
        self.setStyleSheet(DARK_STYLE)
        self.resize(1300, 850)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(tr("status.ready"))

        self._opts_bar = ToolOptionsBar()

        central = QWidget()
        self.setCentralWidget(central)
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)
        root_v.addWidget(self._opts_bar)

        body = QWidget()
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(0, 0, 0, 0)
        body_h.setSpacing(0)

        self._toolbar = ToolBar()
        body_h.addWidget(self._toolbar)

        self._doc_tabs = QTabWidget()
        self._doc_tabs.setTabsClosable(True)
        self._doc_tabs.setMovable(True)
        self._doc_tabs.tabCloseRequested.connect(self._close_tab)
        self._doc_tabs.currentChanged.connect(self._on_tab_changed)
        self._doc_tabs.setObjectName("docTabs")
        self._doc_controller = DocumentController(self._doc_tabs, parent=self)

        from ui.panel_manager import PanelManager
        self._panel_manager = PanelManager(self)
        self._build_menu_bar()

        # Connect panel signals
        self._history_panel.jump_requested.connect(self._history_jump)
        self._navigator_panel.zoom_changed.connect(self._on_nav_zoom)
        self._swatches_panel.fg_color_selected.connect(self._color_panel.set_fg)
        self._swatches_panel.bg_color_selected.connect(self._color_panel.set_bg)
        self._swatches_panel.add_swatch_requested.connect(
            lambda: self._swatches_panel.add_swatch(self._color_panel._fg))
        self._character_panel.option_changed.connect(self._on_opt_changed)
        self._paragraph_panel.option_changed.connect(self._on_opt_changed)
        self._glyphs_panel.char_inserted.connect(self._on_glyph_inserted)
        self._actions_panel.action_requested.connect(self._on_action_requested)
        self._tool_presets_panel.save_requested.connect(self._on_preset_save_requested)
        self._tool_presets_panel.preset_selected.connect(self._on_preset_selected)
        self._brushes_panel.brush_selected.connect(self._on_brush_selected)
        self._paths_panel.make_selection_requested.connect(self._path_make_selection)
        self._paths_panel.fill_path_requested.connect(self._path_fill)
        self._paths_panel.stroke_path_requested.connect(self._path_stroke)
        self._paths_panel.delete_path_requested.connect(self._path_delete)
        self._paths_panel.new_path_requested.connect(self._path_new)
        self._paths_panel.rename_path_requested.connect(self._path_rename)
        self._properties_panel.transform_changed.connect(self._on_transform_changed)
        self._properties_panel.align_requested.connect(self._do_align_layer)

        from ui.welcome_panel import WelcomePanel
        self._welcome_panel = WelcomePanel()
        self._center_stack = QStackedWidget()
        self._center_stack.addWidget(self._welcome_panel)  # index 0
        self._center_stack.addWidget(self._doc_tabs)        # index 1
        self._center_stack.setCurrentIndex(0)

        self._welcome_panel.new_requested.connect(self._new_doc)
        self._welcome_panel.open_requested.connect(self._open_file)
        self._welcome_panel.open_path_requested.connect(self._open_file_path)

        body_h.addWidget(self._center_stack, 1)
        root_v.addWidget(body, 1)

    # ================================================================= Menu Bar
    def _build_menu_bar(self):
        from ui.menu_builder import build_menu_bar
        build_menu_bar(self)

    def _reset_workspace(self):
        self._panel_manager.apply_default_layout()

    def _act(self, menu: QMenu, key: str, slot, shortcut=None) -> QAction:
        act = QAction(tr(key), self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        self._all_acts.append((key, act))
        return act

    def _menu(self, parent, key: str) -> QMenu:
        m = parent.addMenu(tr(key))
        self._all_menus.append((key, m))
        return m

    # ── Language ───────────────────────────────────────────────────────────────
    def _build_language_menu(self, parent_menu: QMenu):
        lang_m = self._menu(parent_menu, "menu.language")
        cur = locale_current()
        for code, name in available_languages():
            act = QAction(name, self, checkable=True)
            act.setChecked(code == cur)
            act.triggered.connect(lambda checked, c=code: self._set_language(c))
            lang_m.addAction(act)
            self._lang_acts[code] = act

    def _build_theme_menu(self, parent_menu):
        from ui import theme
        theme_m = self._menu(parent_menu, "menu.theme")
        self._theme_acts = {}
        for name, key in (("dark", "menu.theme_dark"),
                          ("light", "menu.theme_light"),
                          ("custom", "menu.theme_custom")):
            act = QAction(tr(key), self)
            act.setCheckable(True)
            act.setChecked(theme.current_theme() == name)
            act.triggered.connect(lambda checked, n=name: self._set_theme(n))
            theme_m.addAction(act)
            self._all_acts.append((key, act))
            self._theme_acts[name] = act
        theme_m.addSeparator()
        self._act(theme_m, "menu.theme_configure", self._configure_custom_theme)

    def _set_theme(self, name: str):
        from ui import theme
        if name == theme.current_theme():
            self._theme_acts[name].setChecked(True)
            return
        theme.set_theme(name)
        theme.save_theme(name)
        self._apply_theme_live()

    def _configure_custom_theme(self):
        """One main color drives the whole palette (surfaces take its hue,
        accents are the color itself), on a dark or light lightness base."""
        from ui import theme
        from PyQt6.QtWidgets import QColorDialog, QMessageBox
        from PyQt6.QtCore import QSettings
        s = QSettings("ImageFinish", "ImageFinish")
        start = QColor(str(s.value("theme_custom_color", "#7c3aed")))
        color = QColorDialog.getColor(start, self, tr("dlg.theme_main_color"))
        if not color.isValid():
            return
        base = "dark"
        reply = QMessageBox.question(
            self, tr("menu.theme"), tr("dlg.theme_base_question"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            base = "light"
        s.setValue("theme_custom_color", color.name())
        s.setValue("theme_custom_base", base)
        theme.set_theme("custom")
        theme.save_theme("custom")
        self._apply_theme_live()

    def _apply_theme_live(self):
        from ui import theme
        for n, act in self._theme_acts.items():
            act.setChecked(n == theme.current_theme())
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_stylesheet())
        self.setStyleSheet(theme.build_stylesheet())
        theme.repolish_all()
        self._toolbar.retheme()
        self._refresh_layers()
        self._refresh_secondary_panels()
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).update()
        self._status.showMessage(tr("status.theme_applied"), 4000)

    def _set_language(self, code: str):
        if code == locale_current():
            return
        locale_load(code)
        self._apply_language()

    def _apply_language(self):
        for key, act in self._all_acts:
            act.setText(tr(key))
        for key, menu in self._all_menus:
            menu.setTitle(tr(key))
        cur = locale_current()
        for code, act in self._lang_acts.items():
            act.setChecked(code == cur)
        self._update_mode_menu()
        self._update_recent_menu()
        self._toolbar.retranslate()
        self._opts_bar.retranslate()
        self._layers_panel.retranslate()
        self._color_panel.retranslate()
        self._channels_panel.retranslate()
        self._panel_manager.retranslate()
        for panel in (self._history_panel, self._navigator_panel, self._info_panel,
                      self._histogram_panel, self._brushes_panel, self._swatches_panel,
                      self._paths_panel, self._properties_panel, self._actions_panel,
                      self._tool_presets_panel, self._character_panel,
                      self._paragraph_panel, self._glyphs_panel):
            if hasattr(panel, "retranslate"):
                panel.retranslate()
        if hasattr(self, "_welcome_panel"):
            self._welcome_panel.retranslate()
        self._refresh_layers()

    def _canvas_refresh(self):
        if self._canvas:
            self._canvas._cache_dirty = True
            if self._document:
                self._document.invalidate_composite()
            self._canvas.update()
            # Undo/redo (and anything else routing through here) can swap
            # every Layer object wholesale — re-sync the live shape items
            # so they don't keep editing objects the document dropped.
            if hasattr(self._canvas, "_shape_overlay"):
                self._canvas._shape_overlay.refresh_items()

    # ================================================================= Signals
    def _wire_signals(self):
        self._toolbar.tool_selected.connect(self._activate_tool)
        self._color_panel.fg_changed.connect(self._on_fg_changed)
        self._color_panel.bg_changed.connect(self._on_bg_changed)
        self._opts_bar.option_changed.connect(self._on_opt_changed)
        self._opts_bar.apply_styles_requested.connect(self._apply_text_styles)
        self._opts_bar.apply_crop_requested.connect(self._on_apply_crop_requested)
        self._layers_panel.layer_selected.connect(self._on_layer_selected_wrap)
        self._layers_panel.layer_added.connect(self._add_layer)
        self._layers_panel.layer_duplicated.connect(self._duplicate_layer)
        self._layers_panel.layer_deleted.connect(self._delete_layer)
        self._layers_panel.layer_renamed.connect(self._rename_layer)
        self._layers_panel.layer_expanded_toggled.connect(self._on_layer_expanded_toggled)
        self._layers_panel.layer_moved.connect(self._move_layer_exact)
        self._layers_panel.layer_moved_up.connect(self._layer_up)
        self._layers_panel.layer_moved_down.connect(self._layer_down)
        self._layers_panel.layer_visibility.connect(self._on_layer_visibility)
        self._layers_panel.layer_opacity.connect(self._on_layer_opacity)
        if hasattr(self._layers_panel, "layer_lock_changed"):
            self._layers_panel.layer_lock_changed.connect(self._on_layer_lock_changed)
        if hasattr(self._layers_panel, "layer_grouped"):
            self._layers_panel.layer_grouped.connect(self._group_layer)
            self._layers_panel.layer_linked.connect(self._link_layer)
        if hasattr(self._layers_panel, "layer_blend_mode"):
            self._layers_panel.layer_blend_mode.connect(self._on_layer_blend_mode)
        if hasattr(self._layers_panel, "layer_target_changed"):
            self._layers_panel.layer_target_changed.connect(self._on_layer_target_changed)
            if hasattr(self._layers_panel, "layer_mask_toggled"):
                self._layers_panel.layer_mask_toggled.connect(self._on_layer_mask_toggled)
            self._layers_panel.layer_add_mask.connect(self._add_mask)
            self._layers_panel.layer_delete_mask.connect(self._delete_mask)
            self._layers_panel.layer_apply_mask.connect(self._apply_mask)
            if hasattr(self._layers_panel, "layer_invert_mask"):
                self._layers_panel.layer_invert_mask.connect(self._invert_mask)
        if hasattr(self._layers_panel, "layer_add_vector_mask"):
            self._layers_panel.layer_add_vector_mask.connect(self._add_vector_mask)
            self._layers_panel.layer_delete_vector_mask.connect(self._delete_vector_mask)
            self._layers_panel.layer_vmask_toggled.connect(self._on_layer_vmask_toggled)
        if hasattr(self._layers_panel, "layer_clipping_toggled"):
            self._layers_panel.layer_clipping_toggled.connect(self._on_layer_clipping_toggled)
        self._layers_panel.layer_merged_down.connect(self._merge_down)
        self._layers_panel.layer_flatten.connect(self._flatten)
        self._layers_panel.layer_edit.connect(self._on_edit_layer)
        self._layers_panel.layer_smart_object.connect(self._new_smart_object)
        self._layers_panel.layer_rasterize.connect(self._rasterize_layer)
        if hasattr(self._layers_panel, "layer_export_png"):
            self._layers_panel.layer_export_png.connect(self._export_layer_png)
        self._layers_panel.layer_styles_requested.connect(self._open_layer_styles)
        if hasattr(self._layers_panel, "layer_clear_smart_filters"):
            self._layers_panel.layer_clear_smart_filters.connect(self._clear_smart_filters)
        self._channels_panel.channel_changed.connect(self._on_channel_changed)
        self._channels_panel.save_requested.connect(self._save_selection)
        self._channels_panel.load_requested.connect(self._load_selection_btn)
        self._channels_panel.delete_requested.connect(self._delete_alpha_channel)

    def _add_tab(self, doc, title, filepath=None):
        canvas = CanvasWidget()
        canvas.set_document(doc)
        from core.history import HistoryManager
        canvas.history = HistoryManager()
        doc.history = canvas.history
        canvas.filepath = filepath
        if hasattr(self, "_doc_tabs") and self._doc_tabs.count() > 0:
            fc = self._doc_tabs.widget(0)
            canvas.tool_opts = dict(fc.tool_opts)
            canvas.fg_color = fc.fg_color
            canvas.bg_color = fc.bg_color
        else:
            cp = getattr(self, "_color_panel", None)
            canvas.fg_color = getattr(cp, "_fg", QColor(0, 0, 0))
            canvas.bg_color = getattr(cp, "_bg", QColor(255, 255, 255))
            canvas.tool_opts.update(getattr(self, "_session_tool_opts", {}))
        canvas.is_modified = False
        canvas.document_changed.connect(self._on_doc_changed)
        canvas.pixels_changed.connect(self._on_pixels_changed)
        canvas.pixels_changed.connect(lambda: setattr(canvas, "is_modified", True))
        canvas.view_changed.connect(self._update_status)
        canvas.color_picked.connect(self._color_panel.set_fg)
        canvas.tool_state_changed.connect(self._opts_bar.update_tool_state)
        if hasattr(self, "_info_panel"):
            canvas.cursor_info.connect(self._info_panel.update_info)
        tool = self._tools.get(self._active_tool_name)
        canvas.active_tool = tool
        self._connect_text_session(canvas)
        idx = self._doc_tabs.addTab(canvas, title)
        self._doc_tabs.setCurrentIndex(idx)
        if hasattr(self, "_center_stack"):
            self._center_stack.setCurrentIndex(1)
        # The Welcome screen's recent-file thumbnails set PointingHandCursor
        # on themselves; swapping them out for the canvas at the same screen
        # position doesn't happen via a mouse move, so nothing tells Qt (and
        # the Wayland compositor underneath it) to re-poll which widget is
        # now under the pointer — the thumbnail's hand cursor visually stays
        # put. Just calling canvas.setCursor() isn't enough to fix that: Qt
        # only forwards a cursor change to the platform for the widget it
        # currently considers "entered", and that bookkeeping is normally
        # only updated by a real mouse-move reaching the window. Posting a
        # synthetic MouseMove at the pointer's actual current position forces
        # Qt to re-run its own hit-testing and hand the canvas its hover/
        # cursor state for real, instead of just poking canvas's cursor
        # property from the outside. Deferred via singleShot so it runs once
        # the stack-switch above has actually been applied.
        canvas._update_cursor()

        def _resync_cursor():
            from PyQt6.QtCore import QEvent
            from PyQt6.QtGui import QMouseEvent, QCursor
            from PyQt6.QtWidgets import QApplication
            gpos = QCursor.pos()
            lpos = canvas.mapFromGlobal(gpos)
            ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(lpos), QPointF(gpos),
                              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(canvas, ev)
            canvas._update_cursor()
        from PyQt6.QtCore import QTimer
        # A one-shot timer owned by the canvas (PyQt6 has no context-object
        # singleShot overload): if the canvas is destroyed first — tab
        # closed before the next tick — the timer dies with it. A bare
        # singleShot lambda would run against a deleted widget, and an
        # exception in a queued slot makes PyQt6 abort() the whole process.
        resync_timer = QTimer(canvas)
        resync_timer.setSingleShot(True)
        resync_timer.timeout.connect(_resync_cursor)
        resync_timer.timeout.connect(resync_timer.deleteLater)
        resync_timer.start(0)
        # Sync tool options bar with canvas defaults
        page = self._opts_bar._pages.get(self._active_tool_name)
        if page and hasattr(page, "update_from_opts"):
            page.update_from_opts(canvas.tool_opts)
        return canvas

    def _close_tab(self, index: int):
        canvas = self._doc_tabs.widget(index)
        self._commit_text_edit_if_active(canvas)
        if getattr(canvas, "is_modified", False):
            title = self._doc_tabs.tabText(index)
            reply = QMessageBox.question(
                self, tr("dlg.unsaved_title"),
                tr("dlg.unsaved_msg", name=title),
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._doc_tabs.setCurrentIndex(index)
                self._save()
        self._doc_tabs.removeTab(index)
        canvas.deleteLater()
        if self._doc_tabs.count() == 0:
            self._welcome_panel.refresh_recent(self._recent_files)
            self._center_stack.setCurrentIndex(0)

    def closeEvent(self, event):
        for i in range(self._doc_tabs.count()):
            canvas = self._doc_tabs.widget(i)
            if getattr(canvas, "is_modified", False):
                title = self._doc_tabs.tabText(i)
                reply = QMessageBox.question(
                    self, tr("dlg.unsaved_title"),
                    tr("dlg.unsaved_msg", name=title),
                    QMessageBox.StandardButton.Save |
                    QMessageBox.StandardButton.Discard |
                    QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if reply == QMessageBox.StandardButton.Save:
                    self._doc_tabs.setCurrentIndex(i)
                    self._save()
        from ui import workspace
        workspace.save(self)
        # Drain background workers (histogram/navigator): a QRunnable still
        # running at interpreter teardown crashes the process on exit.
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(3000)
        event.accept()

    def _on_tab_changed(self, index: int):
        if index < 0: return
        current = self._doc_tabs.widget(index)
        for i in range(self._doc_tabs.count()):
            other = self._doc_tabs.widget(i)
            if other is not current:
                self._commit_text_edit_if_active(other)
        self._refresh_layers()
        self._update_mode_menu()
        self._update_title()
        self._canvas_refresh()
        self._sync_view_actions()
        if self._canvas and self._canvas.active_tool:
            self._canvas._emit_tool_state()
        self._refresh_secondary_panels()
        if hasattr(self, "_brushes_panel"):
            self._brushes_panel.refresh(self._canvas)

    def _sync_view_actions(self):
        """Sync View menu action checked states with the current document/canvas."""
        doc = self._document
        canvas = self._canvas
        if doc:
            self._act_guides.setChecked(getattr(doc, "show_guides", True))
            self._act_grid.setChecked(getattr(doc, "show_grid", False))
            self._act_slices.setChecked(getattr(doc, "show_slices", True))
            snap = getattr(doc, "snap_enabled", True)
            self._act_snap.setChecked(snap)
            self._act_snap_guides.setChecked(getattr(doc, "snap_to_guides", True))
            self._act_snap_guides.setEnabled(snap)
            self._act_snap_grid.setChecked(getattr(doc, "snap_to_grid", False))
            self._act_snap_grid.setEnabled(snap)
            self._act_snap_bounds.setChecked(getattr(doc, "snap_to_bounds", True))
            self._act_snap_bounds.setEnabled(snap)
            self._act_snap_layers.setChecked(getattr(doc, "snap_to_layers", True))
            self._act_snap_layers.setEnabled(snap)
        if canvas:
            self._act_rulers.setChecked(getattr(canvas, "show_rulers", False))

    # ================================================================= Tools
    def _commit_move_transform(self):
        for t_name in ["Move", "Warp", "PuppetWarp", "PerspectiveWarp"]:
            tool = self._tools.get(t_name)
            if tool and getattr(tool, "is_transforming", False):
                # Temporarily restore original layer and selection state for a clean snapshot
                layer = self._document.get_active_layer()
                tmp_img, tmp_off, tmp_sel = None, None, None
                kind_geometry = False
                tmp_kids = []
                if layer and hasattr(tool, "_layer_backup") and tool._layer_backup is not None:
                    for kid_data in getattr(tool, "_linked_children", []):
                        kid = kid_data["layer"]
                        tmp_kids.append((kid, QPoint(kid.offset)))
                        kid.offset = kid_data["backup_offset"]
                        
                    tmp_img = layer.image
                    tmp_off = layer.offset
                    tmp_sel = self._document.selection
                    # Per-kind geometry the drag/Transform panel already
                    # moved live (artboard rect, frame rect): back to the
                    # original for the snapshot, re-applied right after.
                    kind_geometry = t_name == "Move" and getattr(tool, "_original_rect", None) is not None
                    if kind_geometry:
                        layer.move_tool_cancel_extra(tool._original_rect)
                    layer.image = tool._layer_backup
                    layer.offset = tool._offset_backup
                    if getattr(tool, "_sel_origin", None):
                        self._document.selection = tool._sel_origin

                pre_state = self._make_history_state(tr("tool.warp") if t_name == "Warp" else tr("tool.move"))
                
                # Restore the "cut" version back for the final compositing
                if layer and tmp_img is not None:
                    layer.image = tmp_img
                    layer.offset = tmp_off
                    self._document.selection = tmp_sel
                    if kind_geometry:
                        layer.move_tool_set_params_extra(tool._total_transform, tool._original_rect)
                        
                for kid, old_off in tmp_kids:
                    kid.offset = old_off

                old_w, old_h = self._document.width, self._document.height
                tool.apply_transform(self._document)
                self._history.push(pre_state)
                if self._document.width != old_w or self._document.height != old_h:
                    self._canvas.reset_zoom()
                self._canvas_refresh()

    def _activate_tool(self, name: str):
        if self._active_tool_name in ("Move", "Warp") and name != self._active_tool_name:
            self._commit_move_transform()

        if name != self._active_tool_name and hasattr(self, "_doc_tabs"):
            # Tool buttons deliberately don't take keyboard focus (so
            # shortcuts keep hitting the canvas), so switching tools never
            # fires QApplication.focusChanged — TextEditOverlay's whole
            # commit mechanism is focus-based, so it never even heard the
            # editor should close. Left open, the still-hidden layer
            # (begin_text_edit sets layer.visible = False for the
            # duration) stayed invisible forever the moment the user did
            # anything else, e.g. selecting a different layer — "the text
            # vanishes but the layer is still there". Ask directly instead
            # of waiting for a focus signal that was never coming.
            self._commit_text_edit_if_active(self._doc_tabs.currentWidget())

        logger.debug("Activating tool: %s", name)
        self._active_tool_name = name
        tool = self._tools.get(name)
        if not tool:
            return
        from tools.other_tools import EyedropperTool
        if isinstance(tool, EyedropperTool):
            tool.color_picked_callback = lambda c: (
                self._color_panel.set_fg(c),
                self._on_fg_changed(c),
            )
        for i in range(self._doc_tabs.count()):
            c = self._doc_tabs.widget(i)
            c.active_tool = tool
            c._update_cursor()
        self._opts_bar.switch_to(name)
        self._toolbar.set_active(name)
        if hasattr(self, "_doc_tabs") and self._doc_tabs.count() > 0:
            canvas = self._doc_tabs.currentWidget()
            if canvas and hasattr(canvas, "tool_opts"):
                page = self._opts_bar._pages.get(name)
                if page and hasattr(page, "update_from_opts"):
                    page.update_from_opts(canvas.tool_opts)
        self._opts_bar.update_tool_state(None)

    def _on_layer_selected_wrap(self, index: int):
        self._commit_move_transform()
        self._commit_text_edit_if_active()
        if hasattr(self, "_on_layer_selected"):
            self._on_layer_selected(index)
        if self._document and 0 <= index < len(self._document.layers):
            self._sync_shape_options_from_layer(self._document.layers[index])
            self._sync_text_options_from_layer(self._document.layers[index])

    @require_document
    def _open_layer_styles(self, index: int):
        layer = self._doc_controller.layer_at(index)
        if layer is None or layer.is_container:
            return
        from ui.layer_style_dialog import LayerStyleDialog
        dlg = LayerStyleDialog(layer, self._canvas_refresh, self)
        if dlg.exec():
            self._push_history("Layer Styles")
            self._refresh_layers()
        else:
            dlg.reject()

    @require_document
    def _rename_layer(self, index: int, new_name: str):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if layer.name != new_name:
                layer.name = new_name

    @require_document
    def _on_layer_expanded_toggled(self, index: int, expanded: bool):
        if 0 <= index < len(self._document.layers):
            self._document.layers[index].expanded = expanded
            self._refresh_layers()

    @require_document
    def _move_layer_exact(self, from_index: int, to_index: int):
        if 0 <= from_index < len(self._document.layers) and 0 <= to_index < len(self._document.layers):
            layer = self._document.layers[from_index]
            self._document.move_layer(from_index, to_index)
            
            if to_index < len(self._document.layers) - 1:
                layer_above_in_ui = self._document.layers[to_index + 1]
                if layer_above_in_ui.is_container:
                    layer.parent_id = getattr(layer_above_in_ui, "layer_id", None)
                else:
                    layer.parent_id = getattr(layer_above_in_ui, "parent_id", None)
            else:
                layer.parent_id = None
                
            self._push_history(tr("history.layer_moved"))
            self._refresh_layers()
            self._canvas_refresh()

    def _on_channel_changed(self, ch: str):
        if not self._canvas:
            return
        self._canvas.view_channel = ch
        self._canvas_refresh()

    @require_document
    def _save_selection(self):
        sel = self._document.selection
        if not sel or sel.isEmpty():
            return
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, tr("menu.save_selection"), tr("dlg.define_name"))
        if ok and name:
            self._push_history(tr("history.save_selection"))
            if not hasattr(self._document, "alpha_channels"):
                self._document.alpha_channels = []
            self._document.alpha_channels.append({"name": name, "path": QPainterPath(sel)})
            self._channels_panel.refresh(self._document)

    @require_document
    def _load_selection(self):
        if not hasattr(self._document, "alpha_channels") or not self._document.alpha_channels:
            return
        from PyQt6.QtWidgets import QInputDialog
        names = [ch["name"] for ch in self._document.alpha_channels]
        name, ok = QInputDialog.getItem(self, tr("menu.load_selection"), "Channel:", names, 0, False)
        if ok and name:
            for ch in self._document.alpha_channels:
                if ch["name"] == name:
                    self._document.selection = QPainterPath(ch["path"])
                    self._push_history(tr("history.load_selection"))
                    self._canvas_refresh()
                    break

    @require_document
    def _load_selection_btn(self, idx):
        if hasattr(self._document, "alpha_channels") and 0 <= idx < len(self._document.alpha_channels):
            self._document.selection = QPainterPath(self._document.alpha_channels[idx]["path"])
            self._push_history(tr("history.load_selection"))
            self._canvas_refresh()

    @require_document
    def _delete_alpha_channel(self, idx):
        if hasattr(self._document, "alpha_channels") and 0 <= idx < len(self._document.alpha_channels):
            self._push_history(tr("history.delete_layer"))
            self._document.alpha_channels.pop(idx)
            self._channels_panel.refresh(self._document)
            if self._canvas.view_channel == f"alpha_{idx}":
                self._canvas.view_channel = "RGB"
                self._canvas_refresh()
            elif self._canvas.view_channel.startswith("alpha_"):
                cur_idx = int(self._canvas.view_channel.split("_")[1])
                if cur_idx > idx:
                    self._canvas.view_channel = f"alpha_{cur_idx - 1}"

    def _refresh_layers(self):
        super()._refresh_layers()
        if hasattr(self, "_channels_panel") and self._document:
            self._channels_panel.refresh(self._document)

    # ================================================================= Events
    @require_document
    def _toggle_rulers(self):
        self._canvas.show_rulers = self._act_rulers.isChecked(); self._canvas.update()
    def _toggle_guides(self):
        if hasattr(self._document, "show_guides"): self._document.show_guides = self._act_guides.isChecked(); self._canvas.update()
    def _toggle_grid(self):
        if hasattr(self._document, "show_grid"): self._document.show_grid = self._act_grid.isChecked(); self._canvas.update()
    def _toggle_slices(self):
        if hasattr(self._document, "show_slices"): self._document.show_slices = self._act_slices.isChecked(); self._canvas.update()
    def _toggle_snap(self):
        enabled = self._act_snap.isChecked()
        self._act_snap_guides.setEnabled(enabled); self._act_snap_grid.setEnabled(enabled)
        self._act_snap_bounds.setEnabled(enabled); self._act_snap_layers.setEnabled(enabled)
        if hasattr(self._document, "snap_enabled"): self._document.snap_enabled = enabled
    def _toggle_snap_guides(self):
        if hasattr(self._document, "snap_to_guides"): self._document.snap_to_guides = self._act_snap_guides.isChecked()
    def _toggle_snap_grid(self):
        if hasattr(self._document, "snap_to_grid"): self._document.snap_to_grid = self._act_snap_grid.isChecked()
    def _toggle_snap_bounds(self):
        if hasattr(self._document, "snap_to_bounds"): self._document.snap_to_bounds = self._act_snap_bounds.isChecked()
    def _toggle_snap_layers(self):
        if hasattr(self._document, "snap_to_layers"): self._document.snap_to_layers = self._act_snap_layers.isChecked()
    
    @require_document
    def _clear_guides(self):
        if hasattr(self._document, "guides_v"): self._document.guides_v.clear()
        if hasattr(self._document, "guides_h"): self._document.guides_h.clear()
        self._canvas.update()

    def _on_pixels_changed(self):
        # Skip updating heavy panels (histogram, navigator) on every
        # mouse move — they call get_composite() and kill FPS.
        # Panels will update in _on_doc_changed() when the stroke ends.
        self._update_status()

    def _on_doc_changed(self):
        if self._canvas is None:
            return
        state = getattr(self._canvas, "_pre_stroke_state", None)
        if state and self._history:
            self._history.push(state)
            self._canvas._pre_stroke_state = None
            if state.doc_width != self._document.width or state.doc_height != self._document.height:
                self._canvas.reset_zoom()
        self._update_title()
        from PyQt6.QtCore import QTimer
        # Delay panel refresh to avoid blocking the GUI right after stroke
        QTimer.singleShot(50, self._deferred_panel_refresh)

    def _deferred_panel_refresh(self):
        if self._document:
            # document_changed fires both for "pixels changed on the layer
            # that was already there" (the common case — a cheap thumbnail
            # refresh is enough) and "a layer got added/removed" (a tool
            # created a new layer directly, e.g. ShapesTool/PenTool's
            # mid-mouse-event layer creation — nothing else ever asked the
            # panel to rebuild its rows). One row per document layer always
            # holds regardless of collapsed-group hiding, so a row-count
            # mismatch is exactly "the layer list itself changed" — rebuild
            # properly in that case instead of silently updating a
            # thumbnail for a layer that has no row at all yet.
            if self._layers_panel._list.count() != len(self._document.layers):
                self._refresh_layers()
            else:
                self._layers_panel.refresh_active_thumbnail(self._document)
        self._refresh_secondary_panels()

    def _refresh_secondary_panels(self):
        canvas = self._canvas
        if hasattr(self, "_history_panel"):
            self._history_panel.refresh(canvas)
        if hasattr(self, "_navigator_panel"):
            self._navigator_panel.refresh(canvas)
        if hasattr(self, "_histogram_panel"):
            self._histogram_panel.refresh(canvas)
        if hasattr(self, "_properties_panel"):
            self._properties_panel.refresh(canvas)
        if hasattr(self, "_paths_panel"):
            self._paths_panel.refresh(canvas)
        if hasattr(self, "_character_panel"):
            self._character_panel.refresh(canvas)
        if hasattr(self, "_paragraph_panel"):
            self._paragraph_panel.refresh(canvas)

    @require_document
    def _undo(self):
        session = self._text_session()
        if session is not None and session.is_active():
            # Undo while typing undoes typing (Photoshop does the same).
            session.undo()
            return
        tool = self._canvas.active_tool
        if hasattr(tool, "is_transforming") and tool.is_transforming:
            tool.cancel_transform(self._document)
            self._canvas_refresh()
            self._opts_bar.update_tool_state(None)
            return
        super()._undo()

    @require_document
    def _redo(self):
        session = self._text_session()
        if session is not None and session.is_active():
            # Undo while typing undoes typing (Photoshop does the same).
            session.redo()
            return
        tool = self._canvas.active_tool
        if hasattr(tool, "is_transforming") and tool.is_transforming:
            tool.cancel_transform(self._document)
            self._canvas_refresh()
            self._opts_bar.update_tool_state(None)
            return
        super()._redo()

    def _make_history_state(self, description: str, modified_index: int | None = None) -> HistoryState:
        """Snapshot the current document. Pass `modified_index` when the
        operation touches a single layer: unmodified layers then share
        their QImage with the live document, which keeps undo memory flat."""
        from core.history import clone_work_path
        return HistoryState(
            description=description,
            layers_snapshot=self._document.snapshot_layers(modified_index=modified_index),
            active_layer_index=self._document.active_layer_index,
            doc_width=self._document.width,
            doc_height=self._document.height,
            selection_snapshot=QPainterPath(self._document.selection) if self._document.selection else None,
            work_path_snapshot=clone_work_path(getattr(self._document, "work_path", None)),
            alpha_channels_snapshot=list(getattr(self._document, "alpha_channels", [])),
            color_mode_snapshot=getattr(self._document, "color_mode", "RGB"),
            bit_depth_snapshot=getattr(self._document, "bit_depth", 8)
        )

    def _push_history(self, description: str, modified_index: int | None = None):
        if not self._document or not self._history:
            return
        self._history.push(self._make_history_state(description, modified_index))

    def _update_status(self, msg: str = ""):
        if not self._document: return
        doc = self._document
        layer = doc.get_active_layer()
        layer_name = layer.name if layer else "—"
        z = int(self._canvas.zoom * 100)
        self._status.showMessage(
            tr("status.info", w=doc.width, h=doc.height, z=z, layer=layer_name)
            + (f"  |  {msg}" if msg else "")
        )

    def _update_title(self):
        if not self._document: return
        mode = getattr(self._document, "color_mode", "RGB")
        depth = getattr(self._document, "bit_depth", 8)
        mode_str = f"{mode}/{depth}"
        fp = self._filepath
        if fp:
            self._add_recent_file(fp)
            name = fp.split("/")[-1]
            self.setWindowTitle(tr("title.with_file", name=name, mode=mode_str))
            if hasattr(self, "_doc_tabs") and self._doc_tabs.currentIndex() >= 0:
                self._doc_tabs.setTabText(self._doc_tabs.currentIndex(), name)
        else:
            self.setWindowTitle(tr("title.canvas", w=self._document.width, h=self._document.height, mode=mode_str))
            if hasattr(self, "_doc_tabs") and self._doc_tabs.currentIndex() >= 0:
                self._doc_tabs.setTabText(self._doc_tabs.currentIndex(), tr("title.untitled", mode=mode_str))
            
    def _update_mode_menu(self):
        if not hasattr(self, "_act_mode_rgb"): return
        if not self._document: return
        mode = getattr(self._document, "color_mode", "RGB")
        depth = getattr(self._document, "bit_depth", 8)
        self._act_mode_bitmap.setChecked(mode == "Bitmap")
        self._act_mode_gray.setChecked(mode == "Grayscale")
        self._act_mode_duo.setChecked(mode == "Duotone")
        self._act_mode_idx.setChecked(mode == "Indexed")
        self._act_mode_rgb.setChecked(mode == "RGB")
        self._act_mode_cmyk.setChecked(mode == "CMYK")
        self._act_mode_lab.setChecked(mode == "Lab")
        
        self._act_depth_8.setChecked(depth == 8)
        self._act_depth_16.setChecked(depth == 16)
        self._act_depth_32.setChecked(depth == 32)
        self._update_title()

    def _align_layer(self, alignment: str):
        doc = self._document
        layer = doc.get_active_layer()
        from core.layer import ArtboardLayer
        if not layer or layer.locked or isinstance(layer, ArtboardLayer):
            return

        linked = [layer]
        if layer.is_container:          # a group aligns as one block
            linked.extend(doc.descendants(layer))
            
        link_id = getattr(layer, "link_id", None)
        if link_id:
            for l in doc.layers:
                if getattr(l, "link_id", None) == link_id and l not in linked:
                    linked.append(l)
                    
        src_rect = QRectF()
        for l in linked:
            r = l.content_rect()
            if not r.isEmpty():
                src_rect = src_rect.united(r)
                
        if src_rect.isEmpty(): return
        
        target_rect = None
        if doc.selection and not doc.selection.isEmpty(): target_rect = doc.selection.boundingRect()
        else:
            artboard = doc.enclosing_artboard(layer)
            target_rect = QRectF(artboard.artboard_rect) if artboard else QRectF(0, 0, doc.width, doc.height)
                
        dx, dy = 0, 0
        if alignment == "left": dx = target_rect.left() - src_rect.left()
        elif alignment == "center_h": dx = target_rect.center().x() - src_rect.center().x()
        elif alignment == "right": dx = target_rect.right() - src_rect.right()
        elif alignment == "top": dy = target_rect.top() - src_rect.top()
        elif alignment == "center_v": dy = target_rect.center().y() - src_rect.center().y()
        elif alignment == "bottom": dy = target_rect.bottom() - src_rect.bottom()
        
        if dx == 0 and dy == 0: return
        self._push_history(tr("history.layer_moved"))
        for l in linked: l.offset = l.offset + QPoint(int(dx), int(dy))
        self._canvas_refresh()

    @require_document
    def _apply_image(self):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull(): return
        
        pre_state = self._make_history_state(tr("history.apply_image"), modified_index=self._document.active_layer_index)
        
        from ui.calculations_dialog import ApplyImageDialog
        dlg = ApplyImageDialog(self._document, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
        else:
            dlg.cancel()

    def _calculations(self):
        if not self._document or not self._document.layers: return
        from ui.calculations_dialog import CalculationsDialog
        dlg = CalculationsDialog(self._document, self._canvas_refresh, self)
        if dlg.exec():
            self._push_history(tr("history.calculations"))
            dlg.apply_result(self)

    # ================================================================= Colour / Options
    def _on_fg_changed(self, c: QColor):
        if not hasattr(self, "_doc_tabs"): return
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).fg_color = c

    def _on_bg_changed(self, c: QColor):
        if not hasattr(self, "_doc_tabs"): return
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).bg_color = c

    def _on_opt_changed(self, key: str, value):
        if key == "text_edit_cancel":
            self._cancel_text_edit()
            return
        if key == "align_layer":
            self._align_layer(value)
            return
        if key == "reset_view_rotation":
            self._canvas.reset_rotation()
            return
        if key == "transform_params":
            tool = self._canvas.active_tool
            if hasattr(tool, "set_transform_params"):
                tool.set_transform_params(self._document, value)
                self._canvas_refresh()
            return
        if key == "sampler_clear":
            tool = self._tools.get("ColorSampler")
            if tool: tool.markers.clear()
            self._canvas_refresh()
            return
        if key == "ruler_clear":
            tool = self._tools.get("Ruler")
            if tool: tool.clear()
            self._canvas_refresh()
            return
        if key == "clear_slices":
            if hasattr(self._document, "slices"):
                self._document.slices.clear()
                self._canvas_refresh()
            return
        if key == "move_apply":
            self._commit_move_transform()
            return
        if key == "move_cancel":
            tool = self._canvas.active_tool
            if hasattr(tool, "is_transforming") and tool.is_transforming:
                tool.cancel_transform(self._document)
                self._canvas_refresh()
                self._opts_bar.update_tool_state(None)
            return
        if key == "pen_action":
            tool = self._canvas.active_tool
            if hasattr(tool, "perform_action"):
                result = tool.perform_action(self._document, value, self._canvas.fg_color)
                if result:
                    action, path = result
                    if action == "selection":
                        self._push_history(tr("history.quick_mask"))
                        self._document.selection = path
                    elif action == "shape":
                        self._push_history("New Vector Shape")
                        from core.layer import VectorLayer
                        new_layer = self._document.add_layer(
                            self._document.next_layer_name(VectorLayer, "layer.name.path"),
                            self._document.active_layer_index + 1, layer_cls=VectorLayer)
                        new_layer.vector_mask = QPainterPath(path)
                        new_layer.vector_mask_enabled = True
                        # Live geometry, not a one-time raster bake: render_into
                        # fills `vector_mask` fresh on every render, so the
                        # path stays exact instead of degrading like a pixel
                        # bake would under future scale/rotate.
                        new_layer.path_style = {
                            "fill_color": QColor(self._canvas.fg_color),
                            "stroke_color": None,
                            "stroke_width": 0.0,
                        }
                        new_layer.rebake_thumbnail()
                self._refresh_layers()
                self._canvas_refresh()
            return
        # Live-edits the active layer's existing shape, if there is one —
        # falls through regardless so tool_opts still updates below (the
        # next brand-new shape drawn should also pick up this value).
        if self._document:
            self._apply_shape_option_live(key, value)
            self._apply_text_option_live(key, value)
        # Also remembered window-wide: with no document open (Welcome
        # screen) there's no canvas to hold it, and the next opened document
        # should still start with what the user just picked.
        if not hasattr(self, "_session_tool_opts"):
            self._session_tool_opts = {}
        self._session_tool_opts[key] = value
        if not hasattr(self, "_doc_tabs"): return
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).tool_opts[key] = value
        canvas = self._canvas
        if canvas is None:
            return
        # Every text-option control (toolbar and dock alike) funnels
        # through here — refresh both so whichever one the user *didn't*
        # just touch reflects the same state instead of silently drifting
        # (this was the toolbar-vs-Character-panel desync bug).
        if hasattr(self, "_character_panel"):
            self._character_panel.refresh(self._canvas)
        if hasattr(self, "_paragraph_panel"):
            self._paragraph_panel.refresh(self._canvas)
        text_page = self._opts_bar._pages.get("Text") if hasattr(self, "_opts_bar") else None
        if text_page is not None and hasattr(text_page, "update_from_opts"):
            text_page.update_from_opts(canvas.tool_opts)
        # tool_opts is stored above, but nothing here ever asked the canvas
        # to actually repaint — the live text-edit preview (which reads
        # tool_opts fresh every paintGL() frame) only looked live before
        # because *something else* happened to trigger a repaint shortly
        # after. Explicitly: an option change must be visible immediately,
        # not just eventually.
        canvas.update()

    @require_document
    def _on_layer_blend_mode(self, mode: str):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "blend_mode", "SourceOver") != mode:
            layer.blend_mode = mode
            self._push_history(tr("history.layer_blend"))
            self._canvas_refresh()

    @require_document
    def _on_layer_lock_changed(self, lock_type: str, locked: bool):
        layer = self._document.get_active_layer()
        if layer:
            if lock_type == "alpha": layer.lock_alpha = locked
            elif lock_type == "pixels": layer.lock_pixels = locked
            elif lock_type == "position": layer.lock_position = locked
            elif lock_type == "artboard": layer.lock_artboard = locked
            elif lock_type == "all": layer.locked = locked
            self._push_history(tr("history.lock_changed"))
            self._refresh_layers()

    @require_document
    def _group_layer(self):
        idx = self._document.active_layer_index
        from core.layer import GroupLayer
        group = self._document.add_layer(tr("layer.name.group"), idx + 1, layer_cls=GroupLayer)
        layer = self._document.layers[idx]
        layer.parent_id = group.layer_id
        self._push_history(tr("history.new_group"))
        self._refresh_layers()
        
    @require_document
    def _link_layer(self):
        idx = self._document.active_layer_index
        if idx > 0:
            l1 = self._document.layers[idx]
            l2 = self._document.layers[idx - 1]
            import uuid
            new_link = l2.link_id if l2.link_id else str(uuid.uuid4())
            if l1.link_id == new_link: l1.link_id = None
            else: l1.link_id = new_link
            self._push_history(tr("history.link_layers"))
            self._refresh_layers()

    @require_document
    def _on_layer_target_changed(self, index: int, target: str):
        if 0 <= index < len(self._document.layers):
            self._document.active_layer_index = index
            layer = self._document.layers[index]
            layer.editing_mask = (target == "mask")
            self._refresh_layers()

    @require_document
    def _on_layer_mask_toggled(self, index: int):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "mask", None) is not None:
                layer.mask_enabled = not getattr(layer, "mask_enabled", True)
                self._push_history(tr("history.toggle_mask"))
                self._refresh_layers()
                self._canvas_refresh()

    @require_document
    def _add_vector_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "vector_mask", None) is None:
            if self._document.selection and not self._document.selection.isEmpty():
                layer.vector_mask = QPainterPath(self._document.selection)
            else:
                path = QPainterPath()
                path.addRect(QRectF(0, 0, self._document.width, self._document.height))
                layer.vector_mask = path
            layer.vector_mask_enabled = True
            self._push_history(tr("history.add_vector_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _delete_vector_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "vector_mask", None) is not None:
            layer.vector_mask = None
            self._push_history(tr("history.delete_vector_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _on_layer_vmask_toggled(self, index: int):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "vector_mask", None) is not None:
                layer.vector_mask_enabled = not getattr(layer, "vector_mask_enabled", True)
                self._push_history(tr("history.toggle_vector_mask"))
                self._refresh_layers()
                self._canvas_refresh()
                
    def _toggle_clipping_mask(self):
        if self._document and self._document.get_active_layer():
            self._on_layer_clipping_toggled(self._document.active_layer_index)
            
    @require_document
    def _on_layer_clipping_toggled(self, index: int):
        if 0 < index < len(self._document.layers): # Cannot apply to the bottom layer
            layer = self._document.layers[index]
            self._push_history(tr("history.clipping_mask"))
            layer.clipping = not getattr(layer, "clipping", False)
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _add_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is None:
            from PyQt6.QtGui import QImage, QColor
            layer.mask = QImage(layer.width(), layer.height(), QImage.Format.Format_ARGB32_Premultiplied)
            layer.mask.fill(QColor(255, 255, 255))
            layer.editing_mask = True
            self._push_history(tr("history.add_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _delete_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            layer.mask = None
            layer.editing_mask = False
            self._push_history(tr("history.delete_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _apply_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            self._document.apply_layer_mask(layer)
            self._push_history(tr("history.apply_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _invert_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            layer.mask.invertPixels()
            self._push_history(tr("history.invert_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _invert(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None:
            self._invert_mask()
        elif hasattr(super(), "_invert"):
            super()._invert()

    def _toggle_quick_mask(self):
        if not self._document: return
        
        pre_state = self._make_history_state(tr("history.quick_mask"))
        
        if getattr(self._document, "quick_mask_layer", None) is not None:
            # Exit Quick Mask mode
            qm = self._document.quick_mask_layer.image
            from core.pixel_buffer import qimage_argb_view

            arr = qimage_argb_view(qm, writable=True)[:, :self._document.width, :]
            
            gray = 0.299*arr[..., 2] + 0.587*arr[..., 1] + 0.114*arr[..., 0]
            mask_val = (255 - gray) * (arr[..., 3] / 255.0)
            
            from core.pixel_buffer import mask_to_path
            self._document.selection = mask_to_path(mask_val < 128)
            self._document.quick_mask_layer = None
            
            if hasattr(self, "_qm_old_fg"):
                self._color_panel.set_fg(self._qm_old_fg)
                self._canvas.fg_color = self._qm_old_fg
                self._color_panel.set_bg(self._qm_old_bg)
                self._canvas.bg_color = self._qm_old_bg
        else:
            # Enter Quick Mask mode
            from core.layer import RasterLayer
            from PyQt6.QtGui import QPainter

            layer = RasterLayer("Quick Mask", self._document.width, self._document.height)
            layer.is_quick_mask = True
            
            sel = self._document.selection
            if sel and not sel.isEmpty():
                layer.image.fill(QColor(0, 0, 0))
                p = QPainter(layer.image)
                p.setClipPath(sel)
                p.fillRect(layer.image.rect(), QColor(255, 255, 255))
                p.end()
            else:
                layer.image.fill(QColor(255, 255, 255))
            
            self._document.quick_mask_layer = layer
            
            self._qm_old_fg = self._canvas.fg_color
            self._qm_old_bg = self._canvas.bg_color
            self._color_panel.set_fg(QColor(0, 0, 0))
            self._canvas.fg_color = QColor(0, 0, 0)
            self._color_panel.set_bg(QColor(255, 255, 255))
            self._canvas.bg_color = QColor(255, 255, 255)
            
        self._history.push(pre_state)
        self._canvas_refresh()
        self._refresh_layers()

    # _get_adj_dialog / _new_adj_layer / _on_edit_layer / _new_smart_object /
    # _clear_smart_filters now live in ui/actions/layer_actions.py
    # (LayerActionsMixin) — they used to be redefined here too, silently
    # shadowing the mixin's (different, stale) versions via MRO.

    @require_document
    def _export_slices(self):
        from core.serialization import save_image_atomic, SerializationError
        slices = getattr(self._document, "slices", [])
        if not slices:
            QMessageBox.information(self, "ImageFinish", tr("err.no_slices"))
            return
        dir_path = QFileDialog.getExistingDirectory(self, tr("dlg.export_slices"))
        if not dir_path: return
        comp = self._document.get_composite(respect_live_hidden=False)
        count = 0
        for i, r in enumerate(slices):
            c = r.intersected(comp.rect())
            if not c.isEmpty():
                try:
                    save_image_atomic(comp.copy(c), f"{dir_path}/slice_{i+1}.png")
                    count += 1
                except (SerializationError, OSError) as e:
                    QMessageBox.critical(self, tr("err.title.save_error"),
                                         tr("err.could_not_save", path=f"slice_{i+1}.png") + f"\n{e}")
                    return
        self._status.showMessage(tr("status.slices_exported", count=count))

    @require_document
    def _export_layer_png(self):
        from core.serialization import save_image_atomic, SerializationError
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull(): return
        path, _ = QFileDialog.getSaveFileName(self, tr("menu.export_layer_png"), f"{layer.name}.png", "PNG (*.png)")
        if path:
            try:
                save_image_atomic(layer.image, path)
            except (SerializationError, OSError) as e:
                QMessageBox.critical(self, tr("err.title.save_error"),
                                     tr("err.could_not_save", path=path) + f"\n{e}")
                return
            self._status.showMessage(tr("status.saved", path=path))

    def _get_define_image(self):
        doc = self._document
        comp = doc.get_composite(respect_live_hidden=False)
        if doc.selection and not doc.selection.isEmpty():
            br = doc.selection.boundingRect().toRect().intersected(comp.rect())
            if not br.isEmpty(): return comp.copy(br)
        return comp.copy()

    @require_document
    def _define_brush(self):
        from PyQt6.QtWidgets import QInputDialog
        import os
        import numpy as np
        from PyQt6.QtGui import QImage, QPainter
        img = self._get_define_image()
        name, ok = QInputDialog.getText(self, tr("dlg.define_brush_title"), tr("dlg.define_name"))
        if not ok or not name.strip(): return
        name = name.strip()
        w, h = img.width(), img.height()
        side = max(w, h)
        sq_img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        sq_img.fill(0)
        p = QPainter(sq_img)
        p.drawImage((side - w) // 2, (side - h) // 2, img)
        p.end()
        sq_img = sq_img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        from core.pixel_buffer import qimage_argb_view
        arr = qimage_argb_view(sq_img, writable=False)[:, :side, :]
        luma = (arr[..., 2]*0.299 + arr[..., 1]*0.587 + arr[..., 0]*0.114)
        orig_alpha = arr[..., 3] / 255.0
        brush_img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        brush_img.fill(0)
        b_arr = qimage_argb_view(brush_img, writable=True)[:, :side, :]
        b_arr[..., 3] = ((255 - luma) * orig_alpha).astype(np.uint8)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_dir = os.path.join(base_dir, "brushes")
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}.png")
        brush_img.save(path)
        brush_page = self._opts_bar._pages.get("Brush")
        if hasattr(brush_page, "add_custom_brush"): brush_page.add_custom_brush(path, name)

    @require_document
    def _define_pattern(self):
        from PyQt6.QtWidgets import QInputDialog
        import os
        img = self._get_define_image()
        name, ok = QInputDialog.getText(self, tr("dlg.define_pattern_title"), tr("dlg.define_name"))
        if not ok or not name.strip(): return
        name = name.strip()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_dir = os.path.join(base_dir, "patterns")
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}.png")
        img.save(path)
        pat_page = self._opts_bar._pages.get("PatternStamp")
        if hasattr(pat_page, "add_custom_pattern"): pat_page.add_custom_pattern(path, name)

    @require_document
    def _define_shape(self):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        import os, json
        doc = self._document
        if not doc.selection or doc.selection.isEmpty():
            QMessageBox.warning(self, tr("err.title.error"), tr("err.no_selection_shape"))
            return
        name, ok = QInputDialog.getText(self, tr("dlg.define_shape_title"), tr("dlg.define_name"))
        if not ok or not name.strip(): return
        name = name.strip()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_dir = os.path.join(base_dir, "shapes")
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}.json")
        data = [{"type": int(e.type.value) if hasattr(e.type, 'value') else int(e.type), "x": e.x, "y": e.y} for i in range(doc.selection.elementCount()) for e in [doc.selection.elementAt(i)]]
        with open(path, "w") as f: json.dump(data, f)
        shapes_page = self._opts_bar._pages.get("Shapes")
        if hasattr(shapes_page, "add_custom_shape"): shapes_page.add_custom_shape(path, name)

    def _on_apply_crop_requested(self):
        if self._active_tool_name == "Crop":
            self._apply_crop()
        elif self._active_tool_name == "Perspective Crop":
            self._apply_perspective_crop()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Return or e.key() == Qt.Key.Key_Enter:
            if self._active_tool_name == "Crop":
                self._apply_crop()
            elif self._active_tool_name == "Perspective Crop":
                self._apply_perspective_crop()
            elif self._active_tool_name in ("Move", "Warp", "PuppetWarp", "PerspectiveWarp"):
                self._commit_move_transform()
        elif e.key() == Qt.Key.Key_Escape:
            if self._active_tool_name in ("Move", "Warp", "PuppetWarp", "PerspectiveWarp"):
                tool = self._canvas.active_tool
                if hasattr(tool, "is_transforming") and tool.is_transforming:
                    tool.cancel_transform(self._document)
                    self._canvas_refresh()
        super().keyPressEvent(e)
        
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)
            
    def dropEvent(self, ev):
        shift_pressed = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            if not path: continue
            if shift_pressed and self._document:
                from PyQt6.QtGui import QImage
                import os
                img = QImage(path)
                if not img.isNull():
                    self._push_history(tr("history.add_layer"))
                    img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                    name = os.path.basename(path)
                    idx = self._document.active_layer_index
                    layer = self._document.add_layer(name, idx + 1)
                    layer.image = img
                    layer.offset = QPoint((self._document.width - img.width()) // 2, (self._document.height - img.height()) // 2)
                    self._refresh_layers()
                    self._canvas_refresh()
                else:
                    self._open_file_path(path)
            else:
                self._open_file_path(path)

    # Filter galleries (Blur/Specific/Render/Sharpen/Stylize/Other/Pixelate/
    # Noise/Distort) moved to ui/actions/filter_actions.py (FilterActionsMixin).

    # Recent Files: moved to ui/actions/file_actions.py (FileActionsMixin) —
    # _load_recent_files/_save_recent_files/_add_recent_file/_remove_recent_file/
    # _update_recent_menu/_clear_recent/_open_recent.

    # Panel handlers (history/navigator/glyph/properties/tool-presets panels,
    # pen-tool work path) moved to ui/actions/panel_actions.py (PanelActionsMixin).
