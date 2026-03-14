from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QMenu, QStatusBar, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QAction, QKeySequence, QColor, QPainterPath

from ui.canvas_widget    import CanvasWidget
from ui.toolbar          import ToolBar
from ui.tool_options_bar import ToolOptionsBar
from ui.layers_panel     import LayersPanel
from ui.color_panel      import ColorPanel

from ui.actions.file_actions       import FileActionsMixin
from ui.actions.edit_actions       import EditActionsMixin
from ui.actions.layer_actions      import LayerActionsMixin
from ui.actions.image_actions      import ImageActionsMixin
from ui.actions.adjustment_actions import AdjustmentActionsMixin
from ui.actions.filter_actions     import FilterActionsMixin

from core.document import Document
from core.history  import HistoryManager, HistoryState
from core.locale   import tr, available_languages, load as locale_load, current as locale_current


# ── Tool registry ──────────────────────────────────────────────────────────────
def _build_tool_registry(text_parent):
    from tools.brush_tool   import BrushTool, EraserTool
    from tools.fill_tool    import FillTool
    from tools.effect_tools import BlurTool, SharpenTool, SmudgeTool
    from tools.other_tools  import (SelectTool, MoveTool, EyedropperTool,
                                    EllipticalSelectTool,
                                    CropTool, TextTool, ShapesTool,
                                    VerticalTypeTool, HorizontalTypeMaskTool,
                                    VerticalTypeMaskTool,
                                    HandTool, ZoomTool, RotateViewTool,
                                    GradientTool, PerspectiveCropTool)
    from tools.lasso_tools import LassoTool, PolygonalLassoTool, MagneticLassoTool
    from tools.advanced_erasers import MagicEraserTool, BackgroundEraserTool
    from tools.magic_wand_tool import MagicWandTool

    text = TextTool();  text._parent_widget  = text_parent
    textv = VerticalTypeTool(); textv._parent_widget = text_parent
    texthm = HorizontalTypeMaskTool(); texthm._parent_widget = text_parent
    textvm = VerticalTypeMaskTool();   textvm._parent_widget = text_parent
    return {
        "Brush":      BrushTool(),
        "Eraser":           EraserTool(),
        "BackgroundEraser": BackgroundEraserTool(),
        "MagicEraser":      MagicEraserTool(),
        "Fill":       FillTool(),
        "Blur":       BlurTool(),
        "Sharpen":    SharpenTool(),
        "Smudge":     SmudgeTool(),
        "Select":     SelectTool(),
        "EllipseSelect": EllipticalSelectTool(),
        "Move":       MoveTool(),
        "Eyedropper": EyedropperTool(),
        "Crop":       CropTool(),
        "Perspective Crop": PerspectiveCropTool(),
        "Text":       text,
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
    }


# ── Main window ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow,
                 FileActionsMixin,
                 EditActionsMixin,
                 LayerActionsMixin,
                 ImageActionsMixin,
                 AdjustmentActionsMixin,
                 FilterActionsMixin):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("title.untitled"))

        self._document = Document(800, 600, QColor(255, 255, 255))
        self._history  = HistoryManager()
        self._tools    = _build_tool_registry(self)
        self._active_tool_name = "Brush"

        self._all_acts:  dict[str, QAction] = {}
        self._all_menus: dict[str, QMenu]   = {}
        self._lang_acts: dict[str, QAction] = {}

        self._build_ui()
        self._wire_signals()
        self._activate_tool("Brush")
        self._refresh_layers()
        self._push_history(tr("history.new_document"))

    # ================================================================== UI Build
    def _build_ui(self):
        from ui.styles import DARK_STYLE
        self.setStyleSheet(DARK_STYLE)
        self.resize(1300, 850)

        self._build_menu_bar()

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

        self._canvas = CanvasWidget()
        self._canvas.set_document(self._document)

        right = QWidget()
        right.setObjectName("panel")
        right.setFixedWidth(220)
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(0)

        self._color_panel  = ColorPanel()
        self._layers_panel = LayersPanel()
        right_v.addWidget(self._color_panel)
        right_v.addWidget(self._layers_panel, 1)

        body_h.addWidget(self._canvas, 1)
        body_h.addWidget(right)
        root_v.addWidget(body, 1)

    # ================================================================= Menu Bar
    def _build_menu_bar(self):
        mb = self.menuBar()

        # File
        file_m = self._menu(mb, "menu.file")
        self._act(file_m, "menu.new",        self._new_doc,    QKeySequence.StandardKey.New)
        self._act(file_m, "menu.open",       self._open_file,  QKeySequence.StandardKey.Open)
        file_m.addSeparator()
        self._act(file_m, "menu.save",       self._save,       QKeySequence.StandardKey.Save)
        self._act(file_m, "menu.save_as",    self._save_as,    QKeySequence("Ctrl+Shift+S"))
        self._act(file_m, "menu.export_png", self._export_png)
        file_m.addSeparator()
        self._act(file_m, "menu.quit",       self.close,       QKeySequence.StandardKey.Quit)

        # Edit
        edit_m = self._menu(mb, "menu.edit")
        self._undo_act = self._act(edit_m, "menu.undo", self._undo, QKeySequence.StandardKey.Undo)
        self._redo_act = self._act(edit_m, "menu.redo", self._redo, QKeySequence.StandardKey.Redo)
        edit_m.addSeparator()
        self._act(edit_m, "menu.cut",             self._cut,   QKeySequence.StandardKey.Cut)
        self._act(edit_m, "menu.copy",            self._copy,  QKeySequence.StandardKey.Copy)
        self._act(edit_m, "menu.paste_new_layer", self._paste, QKeySequence.StandardKey.Paste)
        edit_m.addSeparator()
        self._act(edit_m, "menu.clear_layer",  self._clear_layer, QKeySequence("Delete"))
        # Select
        select_m = self._menu(mb, "menu.select")
        self._act(select_m, "menu.select_all", self._select_all, QKeySequence.StandardKey.SelectAll) # Ctrl+A
        self._act(select_m, "menu.deselect",   self._deselect,   QKeySequence("Ctrl+D"))
        self._act(select_m, "menu.reselect",   self._reselect,   QKeySequence("Shift+Ctrl+D"))
        self._act(select_m, "menu.inverse",    self._inverse_selection, QKeySequence("Shift+Ctrl+I"))
        edit_m.addSeparator()
        self._act(edit_m, "menu.fill_fg", self._fill_fg, QKeySequence("Alt+Delete"))
        self._act(edit_m, "menu.fill_bg", self._fill_bg, QKeySequence("Ctrl+Delete"))

        # Image
        img_m  = self._menu(mb, "menu.image")
        adj_m  = self._menu(img_m, "menu.adjustments")
        self._act(adj_m, "menu.levels",              self._levels,              QKeySequence("Ctrl+L"))
        self._act(adj_m, "menu.brightness_contrast", self._brightness_contrast)
        self._act(adj_m, "menu.hue_saturation",      self._hue_saturation)
        self._act(adj_m, "menu.exposure",            self._exposure)
        self._act(adj_m, "menu.vibrance",            self._vibrance)
        adj_m.addSeparator()
        self._act(adj_m, "menu.black_white",         self._black_white)
        self._act(adj_m, "menu.posterize",           self._posterize)
        self._act(adj_m, "menu.threshold",           self._threshold)
        adj_m.addSeparator()
        self._act(adj_m, "menu.channel_mixer",       self._channel_mixer)
        self._act(adj_m, "menu.selective_color",     self._selective_color)
        self._act(adj_m, "menu.match_color",         self._match_color)
        adj_m.addSeparator()
        self._act(adj_m, "menu.shadows_highlights",  self._shadows_highlights)
        self._act(adj_m, "menu.replace_color",       self._replace_color)
        adj_m.addSeparator()
        self._act(adj_m, "menu.photo_filter",        self._photo_filter)
        self._act(adj_m, "menu.gradient_map",        self._gradient_map)
        self._act(adj_m, "menu.color_lookup",        self._color_lookup)
        self._act(adj_m, "menu.equalize",            self._equalize)
        adj_m.addSeparator()
        self._act(adj_m, "menu.hdr_toning",          self._hdr_toning)
        adj_m.addSeparator()
        self._act(adj_m, "menu.invert",              self._invert, QKeySequence("Ctrl+I"))
        img_m.addSeparator()
        self._act(img_m, "menu.flip_h",        self._flip_h)
        self._act(img_m, "menu.flip_v",        self._flip_v)
        img_m.addSeparator()
        self._act(img_m, "menu.image_size",    self._image_size,    QKeySequence("Ctrl+Alt+I"))
        self._act(img_m, "menu.resize_canvas", self._resize_canvas)
        img_m.addSeparator()
        self._act(img_m, "menu.trim",       self._trim)
        self._act(img_m, "menu.reveal_all", self._reveal_all)
        img_m.addSeparator()
        self._act(img_m, "menu.apply_crop",    self._apply_crop)
        self._act(img_m, "menu.apply_perspective_crop", self._apply_perspective_crop)
        img_m.addSeparator()
        self._act(img_m, "menu.flatten",       self._flatten)

        # Layer
        layer_m = self._menu(mb, "menu.layer")
        self._act(layer_m, "menu.new_layer",       self._add_layer,       QKeySequence("Ctrl+Shift+N"))
        self._act(layer_m, "menu.duplicate_layer", self._duplicate_layer, QKeySequence("Ctrl+J"))
        self._act(layer_m, "menu.delete_layer",    self._delete_layer)
        layer_m.addSeparator()

        adj_m = self._menu(layer_m, "menu.new_adj_layer")
        self._act(adj_m, "menu.new_adj_bc",     lambda: self._new_adj_layer("brightness_contrast"))
        self._act(adj_m, "menu.new_adj_hs",     lambda: self._new_adj_layer("hue_saturation"))
        self._act(adj_m, "menu.new_adj_invert", lambda: self._new_adj_layer("invert"))

        fill_m = self._menu(layer_m, "menu.new_fill_layer")
        self._act(fill_m, "menu.new_fill_solid",    lambda: self._new_fill_layer("solid"))
        self._act(fill_m, "menu.new_fill_gradient", lambda: self._new_fill_layer("gradient"))

        layer_m.addSeparator()
        self._act(layer_m, "menu.smart_object",   self._new_smart_object)
        self._act(layer_m, "menu.rasterize_layer", self._rasterize_layer)
        layer_m.addSeparator()
        self._act(layer_m, "menu.move_up",   self._layer_up,   QKeySequence("Ctrl+]"))
        self._act(layer_m, "menu.move_down", self._layer_down, QKeySequence("Ctrl+["))

        # Filter
        filter_m = self._menu(mb, "menu.filter")
        blur_m   = self._menu(filter_m, "menu.blur")
        self._act(blur_m, "menu.blur.average",  self._blur_average)
        self._act(blur_m, "menu.blur.blur",     self._blur_simple)
        self._act(blur_m, "menu.blur.more",     self._blur_more)
        blur_m.addSeparator()
        self._act(blur_m, "menu.blur.box",      self._box_blur)
        self._act(blur_m, "menu.blur.gaussian", self._gaussian_blur)
        self._act(blur_m, "menu.blur.motion",   self._motion_blur)
        self._act(blur_m, "menu.blur.radial",   self._radial_blur)
        self._act(blur_m, "menu.blur.smart",    self._smart_blur)
        self._act(blur_m, "menu.blur.surface",  self._surface_blur)
        self._act(blur_m, "menu.blur.shape",    self._shape_blur)
        self._act(blur_m, "menu.blur.lens",     self._lens_blur)

        # View
        view_m = self._menu(mb, "menu.view")
        self._act(view_m, "menu.zoom_in",    lambda: self._canvas.zoom_in(),    QKeySequence.StandardKey.ZoomIn)
        self._act(view_m, "menu.zoom_out",   lambda: self._canvas.zoom_out(),   QKeySequence.StandardKey.ZoomOut)
        self._act(view_m, "menu.fit_window", lambda: self._canvas.reset_zoom(), QKeySequence("Ctrl+0"))
        view_m.addSeparator()
        self._build_language_menu(view_m)

    def _act(self, menu: QMenu, key: str, slot, shortcut=None) -> QAction:
        act = QAction(tr(key), self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        self._all_acts[key] = act
        return act

    def _menu(self, parent, key: str) -> QMenu:
        m = parent.addMenu(tr(key))
        self._all_menus[key] = m
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

    def _set_language(self, code: str):
        if code == locale_current():
            return
        locale_load(code)
        self._apply_language()

    def _apply_language(self):
        for key, act in self._all_acts.items():
            act.setText(tr(key))
        for key, menu in self._all_menus.items():
            menu.setTitle(tr(key))
        cur = locale_current()
        for code, act in self._lang_acts.items():
            act.setChecked(code == cur)
        if hasattr(self, "_filepath") and self._filepath:
            self.setWindowTitle(tr("title.with_file", name=self._filepath.split("/")[-1]))
        else:
            self.setWindowTitle(tr("title.untitled"))
        self._toolbar.retranslate()
        self._opts_bar.retranslate()
        self._layers_panel.retranslate()
        self._color_panel.retranslate()
        self._refresh_layers()

    def _canvas_refresh(self):
        self._canvas._cache_dirty = True
        self._canvas.update()

    # ================================================================= Signals
    def _wire_signals(self):
        self._toolbar.tool_selected.connect(self._activate_tool)
        self._canvas.document_changed.connect(self._on_doc_changed)
        self._canvas.pixels_changed.connect(self._on_pixels_changed)
        self._canvas.color_picked.connect(self._color_panel.set_fg)
        self._color_panel.fg_changed.connect(self._on_fg_changed)
        self._color_panel.bg_changed.connect(self._on_bg_changed)
        self._opts_bar.option_changed.connect(self._on_opt_changed)
        self._opts_bar.apply_styles_requested.connect(self._apply_text_styles)
        self._opts_bar.apply_crop_requested.connect(self._on_apply_crop_requested)
        self._layers_panel.layer_selected.connect(self._on_layer_selected)
        self._layers_panel.layer_added.connect(self._add_layer)
        self._layers_panel.layer_duplicated.connect(self._duplicate_layer)
        self._layers_panel.layer_deleted.connect(self._delete_layer)
        self._layers_panel.layer_moved_up.connect(self._layer_up)
        self._layers_panel.layer_moved_down.connect(self._layer_down)
        self._layers_panel.layer_visibility.connect(self._on_layer_visibility)
        self._layers_panel.layer_opacity.connect(self._on_layer_opacity)
        if hasattr(self._layers_panel, "layer_alpha_locked"):
            self._layers_panel.layer_alpha_locked.connect(self._on_layer_alpha_locked)
        if hasattr(self._layers_panel, "layer_blend_mode"):
            self._layers_panel.layer_blend_mode.connect(self._on_layer_blend_mode)
        if hasattr(self._layers_panel, "layer_target_changed"):
            self._layers_panel.layer_target_changed.connect(self._on_layer_target_changed)
            if hasattr(self._layers_panel, "layer_mask_toggled"):
                self._layers_panel.layer_mask_toggled.connect(self._on_layer_mask_toggled)
            self._layers_panel.layer_add_mask.connect(self._add_mask)
            self._layers_panel.layer_delete_mask.connect(self._delete_mask)
            self._layers_panel.layer_apply_mask.connect(self._apply_mask)
        self._layers_panel.layer_merged_down.connect(self._merge_down)
        self._layers_panel.layer_flatten.connect(self._flatten)
        self._layers_panel.layer_edit.connect(self._on_edit_layer)
        self._layers_panel.layer_smart_object.connect(self._new_smart_object)
        self._layers_panel.layer_rasterize.connect(self._rasterize_layer)

    # ================================================================= Tools
    def _activate_tool(self, name: str):
        print(f"Activating tool: {name}")
        self._active_tool_name = name
        tool = self._tools.get(name)
        if not tool:
            return
        from tools.other_tools import EyedropperTool
        if isinstance(tool, EyedropperTool):
            tool.color_picked_callback = lambda c: (
                self._color_panel.set_fg(c),
                self._canvas.__setattr__("fg_color", c),
            )
        self._canvas.active_tool = tool
        self._canvas._update_cursor()
        self._opts_bar.switch_to(name)
        self._toolbar.set_active(name)

    # ================================================================= Events
    def _on_pixels_changed(self):
        self._update_status()

    def _on_doc_changed(self):
        self._refresh_layers()
        state = getattr(self._canvas, "_pre_stroke_state", None)
        if state:
            self._history.push(state)
            self._canvas._pre_stroke_state = None
        self._update_title()

    def _push_history(self, description: str):
        self._history.push(HistoryState(
            description=description,
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
            doc_width=self._document.width,
            doc_height=self._document.height,
            selection_snapshot=QPainterPath(self._document.selection) if self._document.selection else None,
        ))

    def _update_status(self, msg: str = ""):
        doc = self._document
        layer = doc.get_active_layer()
        layer_name = layer.name if layer else "—"
        z = int(self._canvas.zoom * 100)
        self._status.showMessage(
            tr("status.info", w=doc.width, h=doc.height, z=z, layer=layer_name)
            + (f"  |  {msg}" if msg else "")
        )

    def _update_title(self):
        self.setWindowTitle(tr("title.canvas", w=self._document.width, h=self._document.height))

    # ================================================================= Colour / Options
    def _on_fg_changed(self, c: QColor):
        self._canvas.fg_color = c

    def _on_bg_changed(self, c: QColor):
        self._canvas.bg_color = c

    def _on_opt_changed(self, key: str, value):
        if key == "reset_view_rotation":
            self._canvas.reset_rotation()
            return
        self._canvas.tool_opts[key] = value

    def _on_layer_blend_mode(self, mode: str):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "blend_mode", "SourceOver") != mode:
            layer.blend_mode = mode
            self._push_history(tr("history.layer_blend"))
            self._canvas_refresh()

    def _on_layer_alpha_locked(self, index: int, locked: bool):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "lock_alpha", False) != locked:
                layer.lock_alpha = locked
                self._push_history(tr("history.lock_alpha"))
                self._refresh_layers()

    def _on_layer_target_changed(self, index: int, target: str):
        if 0 <= index < len(self._document.layers):
            self._document.active_layer_index = index
            layer = self._document.layers[index]
            layer.editing_mask = (target == "mask")
            self._refresh_layers()

    def _on_layer_mask_toggled(self, index: int):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "mask", None) is not None:
                layer.mask_enabled = not getattr(layer, "mask_enabled", True)
                self._push_history(tr("history.toggle_mask"))
                self._refresh_layers()
                self._canvas_refresh()

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

    def _delete_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            layer.mask = None
            layer.editing_mask = False
            self._push_history(tr("history.delete_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    def _apply_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            self._document.apply_layer_mask(layer)
            self._push_history(tr("history.apply_mask"))
            self._refresh_layers()
            self._canvas_refresh()

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
        super().keyPressEvent(e)

    def _apply_text_styles(self):
        from tools.other_tools import _render_text, TextTool
        layer = self._document.get_active_layer()
        if not layer or not getattr(layer, "text_data", None):
            return
        self._push_history(tr("history.apply_text"))
        td   = layer.text_data
        opts = self._canvas.tool_opts
        layer.image.fill(Qt.GlobalColor.transparent)
        sel = self._document.selection
        _render_text(layer.image, td["x"], td["y"], td["text"], opts,
                     sel if (sel and not sel.isEmpty()) else None)
        layer.text_data = {**td, **TextTool._snap_opts(opts)}
        self._canvas_refresh()
        self._refresh_layers()
