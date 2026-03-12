from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QSplitter, QMenuBar, QMenu, QStatusBar,
                             QFileDialog, QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QAction, QKeySequence, QColor, QImageReader, QImageWriter, QPainter, QPainterPath

from ui.canvas_widget    import CanvasWidget
from ui.toolbar          import ToolBar
from ui.tool_options_bar import ToolOptionsBar
from ui.layers_panel     import LayersPanel
from ui.color_panel      import ColorPanel

from core.document  import Document
from core.history   import HistoryManager, HistoryState
from core.locale    import tr, available_languages, load as locale_load, current as locale_current


# ── Tool registry ─────────────────────────────────────────────────────────────
def _build_tool_registry(text_parent):
    from tools.brush_tool   import BrushTool
    from tools.eraser_tool  import EraserTool
    from tools.fill_tool    import FillTool
    from tools.effect_tools import BlurTool, SharpenTool, SmudgeTool
    from tools.other_tools  import (SelectTool, MoveTool, EyedropperTool,
                                    CropTool, TextTool, ShapesTool,
                                    VerticalTypeTool, HorizontalTypeMaskTool,
                                    VerticalTypeMaskTool)
    text = TextTool()
    text._parent_widget = text_parent
    textv = VerticalTypeTool()
    textv._parent_widget = text_parent
    texthm = HorizontalTypeMaskTool()
    texthm._parent_widget = text_parent
    textvm = VerticalTypeMaskTool()
    textvm._parent_widget = text_parent

    return {
        "Brush":      BrushTool(),
        "Eraser":     EraserTool(),
        "Fill":       FillTool(),
        "Blur":       BlurTool(),
        "Sharpen":    SharpenTool(),
        "Smudge":     SmudgeTool(),
        "Select":     SelectTool(),
        "Move":       MoveTool(),
        "Eyedropper": EyedropperTool(),
        "Crop":       CropTool(),
        "Text":       text,
        "TextV":      textv,
        "TextHMask":  texthm,
        "TextVMask":  textvm,
        "Shapes":     ShapesTool(),
    }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("title.untitled"))

        self._document = Document(800, 600, QColor(255, 255, 255))
        self._history  = HistoryManager()
        self._tools    = _build_tool_registry(self)
        self._active_tool_name = "Brush"

        # Locale tracking
        self._all_acts:  dict[str, QAction] = {}
        self._all_menus: dict[str, QMenu]   = {}
        self._lang_acts: dict[str, QAction] = {}

        self._build_ui()
        self._wire_signals()
        self._activate_tool("Brush")
        self._refresh_layers()

        # Initial history snapshot
        self._push_history(tr("history.new_document"))

    # ================================================================== UI Build
    def _build_ui(self):
        from ui.styles import DARK_STYLE
        self.setStyleSheet(DARK_STYLE)
        self.resize(1300, 850)

        # ── Menu bar ──────────────────────────────────────────────────────
        self._build_menu_bar()

        # ── Status bar ────────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(tr("status.ready"))

        # ── Tool options bar (top, below menu) ────────────────────────────
        self._opts_bar = ToolOptionsBar()

        # ── Central area ─────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)
        root_v.addWidget(self._opts_bar)

        # Main horizontal: toolbar | canvas | right panels
        body = QWidget()
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(0, 0, 0, 0)
        body_h.setSpacing(0)

        # Left toolbar
        self._toolbar = ToolBar()
        body_h.addWidget(self._toolbar)

        # Canvas (takes remaining space)
        self._canvas = CanvasWidget()
        self._canvas.set_document(self._document)

        # Right panel: color + layers stacked vertically
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

        # ── File ──────────────────────────────────────────────────────────
        file_m = self._menu(mb, "menu.file")
        self._act(file_m, "menu.new",        self._new_doc,    QKeySequence.StandardKey.New)
        self._act(file_m, "menu.open",       self._open_file,  QKeySequence.StandardKey.Open)
        file_m.addSeparator()
        self._act(file_m, "menu.save",       self._save,       QKeySequence.StandardKey.Save)
        self._act(file_m, "menu.save_as",    self._save_as,    QKeySequence("Ctrl+Shift+S"))
        self._act(file_m, "menu.export_png", self._export_png)
        file_m.addSeparator()
        self._act(file_m, "menu.quit",       self.close,       QKeySequence.StandardKey.Quit)

        # ── Edit ──────────────────────────────────────────────────────────
        edit_m = self._menu(mb, "menu.edit")
        self._undo_act = self._act(edit_m, "menu.undo", self._undo, QKeySequence.StandardKey.Undo)
        self._redo_act = self._act(edit_m, "menu.redo", self._redo, QKeySequence.StandardKey.Redo)
        edit_m.addSeparator()
        self._act(edit_m, "menu.cut",             self._cut,   QKeySequence.StandardKey.Cut)
        self._act(edit_m, "menu.copy",            self._copy,  QKeySequence.StandardKey.Copy)
        self._act(edit_m, "menu.paste_new_layer", self._paste, QKeySequence.StandardKey.Paste)
        edit_m.addSeparator()
        self._act(edit_m, "menu.clear_layer",  self._clear_layer, QKeySequence("Delete"))
        self._act(edit_m, "menu.deselect",     self._deselect,    QKeySequence("Ctrl+D"))
        self._act(edit_m, "menu.select_all",   self._select_all,  QKeySequence.StandardKey.SelectAll)
        edit_m.addSeparator()
        self._act(edit_m, "menu.fill_fg", self._fill_fg, QKeySequence("Alt+Delete"))
        self._act(edit_m, "menu.fill_bg", self._fill_bg, QKeySequence("Ctrl+Delete"))

        # ── Image ─────────────────────────────────────────────────────────
        img_m = self._menu(mb, "menu.image")

        adj_m = self._menu(img_m, "menu.adjustments")
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
        self._act(img_m, "menu.resize_canvas", self._resize_canvas)
        img_m.addSeparator()
        self._act(img_m, "menu.apply_crop",    self._apply_crop, QKeySequence("Return"))
        img_m.addSeparator()
        self._act(img_m, "menu.flatten",       self._flatten)

        # ── Layer ─────────────────────────────────────────────────────────
        layer_m = self._menu(mb, "menu.layer")
        self._act(layer_m, "menu.new_layer",       self._add_layer,       QKeySequence("Ctrl+Shift+N"))
        self._act(layer_m, "menu.duplicate_layer", self._duplicate_layer, QKeySequence("Ctrl+J"))
        self._act(layer_m, "menu.delete_layer",    self._delete_layer)
        layer_m.addSeparator()
        self._act(layer_m, "menu.move_up",   self._layer_up,   QKeySequence("Ctrl+]"))
        self._act(layer_m, "menu.move_down", self._layer_down, QKeySequence("Ctrl+["))

        # ── Filter ────────────────────────────────────────────────────────
        filter_m = self._menu(mb, "menu.filter")
        blur_m = self._menu(filter_m, "menu.blur")
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

        # ── View ──────────────────────────────────────────────────────────
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
        """Add a (sub)menu to parent (QMenuBar or QMenu) and register for live updates."""
        m = parent.addMenu(tr(key))
        self._all_menus[key] = m
        return m

    # ── Language menu ─────────────────────────────────────────────────────────
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
        """Update all menu labels and UI strings to current locale (live switch)."""
        for key, act in self._all_acts.items():
            act.setText(tr(key))
        for key, menu in self._all_menus.items():
            menu.setTitle(tr(key))
        # Update language checkmarks
        cur = locale_current()
        for code, act in self._lang_acts.items():
            act.setChecked(code == cur)
        # Update window title
        if hasattr(self, "_filepath") and self._filepath:
            self.setWindowTitle(tr("title.with_file", name=self._filepath.split("/")[-1]))
        else:
            self.setWindowTitle(tr("title.untitled"))
        # Update toolbar, options bar, and right panels
        self._toolbar.retranslate()
        self._opts_bar.retranslate()
        self._layers_panel.retranslate()
        self._color_panel.retranslate()
        # Rebuild layer items (picks up new tooltip strings) + refresh status bar
        self._refresh_layers()

    def _canvas_refresh(self):
        """Инвалидировать кэш холста и перерисовать."""
        self._canvas._cache_dirty = True
        self._canvas.update()

    # ================================================================ Signals
    def _wire_signals(self):
        # Toolbar
        self._toolbar.tool_selected.connect(self._activate_tool)

        # Canvas
        self._canvas.document_changed.connect(self._on_doc_changed)
        self._canvas.pixels_changed.connect(self._on_pixels_changed)
        self._canvas.color_picked.connect(self._color_panel.set_fg)

        # Color panel
        self._color_panel.fg_changed.connect(self._on_fg_changed)
        self._color_panel.bg_changed.connect(self._on_bg_changed)

        # Tool options
        self._opts_bar.option_changed.connect(self._on_opt_changed)
        self._opts_bar.apply_styles_requested.connect(self._apply_text_styles)

        # Layers panel
        self._layers_panel.layer_selected.connect(self._on_layer_selected)
        self._layers_panel.layer_added.connect(self._add_layer)
        self._layers_panel.layer_duplicated.connect(self._duplicate_layer)
        self._layers_panel.layer_deleted.connect(self._delete_layer)
        self._layers_panel.layer_moved_up.connect(self._layer_up)
        self._layers_panel.layer_moved_down.connect(self._layer_down)
        self._layers_panel.layer_visibility.connect(self._on_layer_visibility)
        self._layers_panel.layer_opacity.connect(self._on_layer_opacity)
        self._layers_panel.layer_merged_down.connect(self._merge_down)
        self._layers_panel.layer_flatten.connect(self._flatten)

    # ================================================================ Tool activation
    def _activate_tool(self, name: str):
        self._active_tool_name = name
        tool = self._tools.get(name)
        if not tool:
            return

        # Wire eyedropper callback
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

    # ================================================================ Document events
    def _on_pixels_changed(self):
        """Вызывается на каждое движение кисти — только обновляем статус."""
        self._update_status()

    def _on_doc_changed(self):
        """Вызывается один раз после завершения мазка или любой структурной операции."""
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

    # ================================================================ Colour
    def _on_fg_changed(self, c: QColor):
        self._canvas.fg_color = c

    def _on_bg_changed(self, c: QColor):
        self._canvas.bg_color = c

    # ================================================================ Options
    def _on_opt_changed(self, key: str, value):
        self._canvas.tool_opts[key] = value

    def _apply_text_styles(self):
        """Перерисовать активный текстовый слой с текущими настройками стиля."""
        from tools.other_tools import _render_text, TextTool
        from PyQt6.QtCore import Qt
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

    # ================================================================ Layer ops
    def _refresh_layers(self):
        self._layers_panel.refresh(self._document)
        self._update_status()

    def _on_layer_selected(self, index: int):
        self._document.active_layer_index = index
        self._refresh_layers()

    def _on_layer_visibility(self, index: int, visible: bool):
        self._document.layers[index].visible = visible
        self._canvas_refresh()

    def _on_layer_opacity(self, index: int, opacity: float):
        self._document.layers[index].opacity = opacity
        self._canvas_refresh()
        self._refresh_layers()

    def _add_layer(self):
        self._push_history(tr("history.add_layer"))
        self._document.add_layer()
        self._refresh_layers()
        self._canvas_refresh()

    def _duplicate_layer(self):
        self._push_history(tr("history.duplicate_layer"))
        self._document.duplicate_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    def _delete_layer(self):
        if len(self._document.layers) <= 1:
            QMessageBox.warning(self, tr("err.title.delete_layer"), tr("err.delete_last_layer"))
            return
        self._push_history(tr("history.delete_layer"))
        self._document.remove_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    def _layer_up(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_up"))
        self._document.move_layer(i, i + 1)
        self._refresh_layers()
        self._canvas_refresh()

    def _layer_down(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_down"))
        self._document.move_layer(i, i - 1)
        self._refresh_layers()
        self._canvas_refresh()

    def _merge_down(self):
        i = self._document.active_layer_index
        if i == 0:
            return
        self._push_history(tr("history.merge_down"))
        from PyQt6.QtGui import QPainter
        bottom = self._document.layers[i - 1]
        top    = self._document.layers[i]
        p = QPainter(bottom.image)
        p.setOpacity(top.opacity)
        p.drawImage(top.offset, top.image)
        p.end()
        self._document.remove_layer(i)
        self._refresh_layers()
        self._canvas_refresh()

    def _flatten(self):
        self._push_history(tr("history.flatten"))
        self._document.flatten()
        self._refresh_layers()
        self._canvas_refresh()

    # ================================================================ Edit ops
    def _undo(self):
        state = self._history.undo()
        if not state:
            return
        # Save current state to redo
        self._history.save_for_redo(HistoryState(
            description="redo",
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
        ))
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._refresh_layers()
        self._canvas_refresh()
        self._status.showMessage(tr("status.undo", desc=state.description))

    def _redo(self):
        state = self._history.redo()
        if not state:
            return
        self._push_history("undo")
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._refresh_layers()
        self._canvas_refresh()

    def _clear_layer(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.clear_layer"))
        layer.image.fill(Qt.GlobalColor.transparent)
        self._canvas_refresh()

    def _deselect(self):
        self._document.selection = None
        self._canvas_refresh()

    def _select_all(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self._document.width, self._document.height))
        self._document.selection = p
        self._canvas_refresh()

    def _cut(self):
        self._copy()
        layer = self._document.get_active_layer()
        if not layer:
            return
        sel = self._document.selection
        if sel and not sel.isEmpty():
            self._push_history(tr("history.cut"))
            p = QPainter(layer.image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setClipPath(sel)
            p.fillRect(sel.boundingRect().toRect(), QColor(0, 0, 0, 0))
            p.end()
            self._canvas_refresh()

    def _copy(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        sel = self._document.selection
        if sel and not sel.isEmpty():
            self._clipboard = layer.image.copy(sel.boundingRect().toRect())
        else:
            self._clipboard = layer.image.copy()

    def _paste(self):
        if not hasattr(self, "_clipboard") or self._clipboard is None:
            return
        self._push_history(tr("history.paste"))
        from core.layer import Layer
        from PyQt6.QtCore import QPoint
        new_layer = Layer(f"Pasted {len(self._document.layers)+1}",
                          self._document.width, self._document.height)
        # Вставляем по центру холста
        cx = (self._document.width  - self._clipboard.width())  // 2
        cy = (self._document.height - self._clipboard.height()) // 2
        p = QPainter(new_layer.image)
        p.drawImage(QPoint(cx, cy), self._clipboard)
        p.end()
        self._document.layers.append(new_layer)
        self._document.active_layer_index = len(self._document.layers) - 1
        self._refresh_layers()
        self._canvas_refresh()

    def _fill_fg(self):
        self._fill_with(self._canvas.fg_color)

    def _fill_bg(self):
        self._fill_with(self._canvas.bg_color)

    def _fill_with(self, color: QColor):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.fill"))
        from PyQt6.QtGui import QPainter
        p = QPainter(layer.image)
        sel = self._document.selection
        if sel and not sel.isEmpty():
            p.setClipPath(sel)
            p.fillRect(sel.boundingRect().toRect(), color)
            p.setClipping(False)
        else:
            p.fillRect(layer.image.rect(), color)
        p.end()
        self._canvas_refresh()

    # ================================================================ Adjustments
    def _levels(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.levels_dialog import LevelsDialog
        self._push_history(tr("history.before_levels"))
        LevelsDialog(layer, self._canvas_refresh, self).exec()

    def _brightness_contrast(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.adjustments_dialog import BrightnessContrastDialog
        self._push_history(tr("history.before_bc"))
        dlg = BrightnessContrastDialog(layer, self._canvas_refresh, self)
        dlg.exec()

    def _hue_saturation(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.adjustments_dialog import HueSaturationDialog
        self._push_history(tr("history.before_hs"))
        dlg = HueSaturationDialog(layer, self._canvas_refresh, self)
        dlg.exec()

    def _invert(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.adjustments_dialog import apply_invert
        self._push_history(tr("history.invert"))
        layer.image = apply_invert(layer.image)
        self._canvas_refresh()

    def _exposure(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ExposureDialog
        self._push_history(tr("history.before_exposure"))
        ExposureDialog(layer, self._canvas_refresh, self).exec()

    def _vibrance(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import VibranceDialog
        self._push_history(tr("history.before_vibrance"))
        VibranceDialog(layer, self._canvas_refresh, self).exec()

    def _black_white(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import BlackWhiteDialog
        self._push_history(tr("history.before_bw"))
        BlackWhiteDialog(layer, self._canvas_refresh, self).exec()

    def _posterize(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import PosterizeDialog
        self._push_history(tr("history.before_posterize"))
        PosterizeDialog(layer, self._canvas_refresh, self).exec()

    def _threshold(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ThresholdDialog
        self._push_history(tr("history.before_threshold"))
        ThresholdDialog(layer, self._canvas_refresh, self).exec()

    def _channel_mixer(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ChannelMixerDialog
        self._push_history(tr("history.before_mixer"))
        ChannelMixerDialog(layer, self._canvas_refresh, self).exec()

    def _selective_color(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import SelectiveColorDialog
        self._push_history(tr("history.before_sel_color"))
        SelectiveColorDialog(layer, self._canvas_refresh, self).exec()

    def _match_color(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import MatchColorDialog
        active_idx = self._document.active_layer_index
        sources = [
            (lyr.name, lyr.image)
            for i, lyr in enumerate(self._document.layers)
            if i != active_idx
        ]
        self._push_history(tr("history.before_match_color"))
        MatchColorDialog(layer, sources, self._canvas_refresh, self).exec()

    def _shadows_highlights(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ShadowsHighlightsDialog
        self._push_history(tr("history.before_shadows_hl"))
        ShadowsHighlightsDialog(layer, self._canvas_refresh, self).exec()

    def _replace_color(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ReplaceColorDialog
        self._push_history(tr("history.before_replace"))
        ReplaceColorDialog(layer, self._canvas_refresh, self).exec()

    def _photo_filter(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import PhotoFilterDialog
        self._push_history(tr("history.before_photo_filter"))
        PhotoFilterDialog(layer, self._canvas_refresh, self).exec()

    def _gradient_map(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import GradientMapDialog
        self._push_history(tr("history.before_gradient"))
        GradientMapDialog(layer, self._canvas_refresh, self).exec()

    def _color_lookup(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import ColorLookupDialog
        self._push_history(tr("history.before_lookup"))
        ColorLookupDialog(layer, self._canvas_refresh, self).exec()

    def _equalize(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.more_adjustments import apply_equalize
        self._push_history(tr("history.equalize"))
        layer.image = apply_equalize(layer.image)
        self._canvas_refresh()

    def _hdr_toning(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.adjustments.hdr_toning import HDRToningDialog
        self._push_history(tr("history.before_hdr"))
        HDRToningDialog(layer, self._canvas_refresh, self).exec()

    # ================================================================ Filters
    def _blur_average(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_average
        self._push_history(tr("history.average"))
        layer.image = apply_average(layer.image)
        self._canvas_refresh()

    def _blur_simple(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_blur
        self._push_history(tr("history.blur"))
        layer.image = apply_blur(layer.image)
        self._canvas_refresh()

    def _blur_more(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_blur_more
        self._push_history(tr("history.blur_more"))
        layer.image = apply_blur_more(layer.image)
        self._canvas_refresh()

    def _box_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import BoxBlurDialog
        self._push_history(tr("history.before_box_blur"))
        BoxBlurDialog(layer, self._canvas_refresh, self).exec()

    def _gaussian_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import GaussianBlurDialog
        self._push_history(tr("history.before_gaussian"))
        GaussianBlurDialog(layer, self._canvas_refresh, self).exec()

    def _motion_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.motion_blur import MotionBlurDialog
        self._push_history(tr("history.before_motion"))
        MotionBlurDialog(layer, self._canvas_refresh, self).exec()

    def _radial_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.radial_blur import RadialBlurDialog
        self._push_history(tr("history.before_radial"))
        RadialBlurDialog(layer, self._canvas_refresh, self).exec()

    def _smart_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import SmartBlurDialog
        self._push_history(tr("history.before_smart"))
        SmartBlurDialog(layer, self._canvas_refresh, self).exec()

    def _surface_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import SurfaceBlurDialog
        self._push_history(tr("history.before_surface"))
        SurfaceBlurDialog(layer, self._canvas_refresh, self).exec()

    def _shape_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import ShapeBlurDialog
        self._push_history(tr("history.before_shape"))
        ShapeBlurDialog(layer, self._canvas_refresh, self).exec()

    def _lens_blur(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import LensBlurDialog
        self._push_history(tr("history.before_lens"))
        LensBlurDialog(layer, self._canvas_refresh, self).exec()

    # ================================================================ Image ops
    def _flip_h(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.flip_h"))
        layer.image = layer.image.mirrored(horizontal=True, vertical=False)
        self._canvas_refresh()

    def _flip_v(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.flip_v"))
        layer.image = layer.image.mirrored(horizontal=False, vertical=True)
        self._canvas_refresh()

    def _resize_canvas(self):
        from utils.new_document_dialog import NewDocumentDialog
        dlg = NewDocumentDialog(self)
        dlg.setWindowTitle(tr("dlg.resize_canvas"))
        dlg._width_spin.setValue(self._document.width)
        dlg._height_spin.setValue(self._document.height)
        if dlg.exec():
            self._push_history(tr("history.resize_canvas"))
            from PyQt6.QtGui import QPainter, QImage
            new_w, new_h = dlg.get_width(), dlg.get_height()
            for layer in self._document.layers:
                new_img = QImage(new_w, new_h, QImage.Format.Format_ARGB32_Premultiplied)
                new_img.fill(Qt.GlobalColor.transparent)
                p = QPainter(new_img)
                p.drawImage(0, 0, layer.image)
                p.end()
                layer.image = new_img
            self._document.width  = new_w
            self._document.height = new_h
            self._canvas_refresh()
            self._canvas.reset_zoom()
            self._refresh_layers()

    def _apply_crop(self):
        from tools.other_tools import CropTool
        tool = self._tools.get("Crop")
        if isinstance(tool, CropTool) and tool.pending_rect:
            self._push_history(tr("history.crop"))
            self._document.apply_crop(tool.pending_rect)
            tool.pending_rect = None
            self._canvas_refresh()
            self._canvas.reset_zoom()
            self._refresh_layers()

    # ================================================================ File ops
    def _new_doc(self):
        from utils.new_document_dialog import NewDocumentDialog
        dlg = NewDocumentDialog(self)
        if dlg.exec():
            self._document = Document(dlg.get_width(), dlg.get_height(), dlg.get_bg_color())
            self._history.clear()
            self._canvas.set_document(self._document)
            self._refresh_layers()
            self._push_history(tr("history.new_document"))
            self._update_title()
            self._filepath = None

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg.open_image"), "",
            tr("dlg.open_filter"))
        if not path:
            return
        from PyQt6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            QMessageBox.critical(self, tr("err.title.error"), tr("err.could_not_open", path=path))
            return
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self._document = Document.__new__(Document)
        self._document.width  = img.width()
        self._document.height = img.height()
        self._document.selection = None
        from core.layer import Layer
        layer = Layer.__new__(Layer)
        layer.name = "Background"
        layer.visible = True
        layer.locked  = False
        layer.opacity = 1.0
        layer.blend_mode = "Normal"
        layer.text_data  = None
        from PyQt6.QtCore import QPoint
        layer.offset = QPoint(0, 0)
        layer.image  = img
        self._document.layers = [layer]
        self._document.active_layer_index = 0

        self._history.clear()
        self._canvas.set_document(self._document)
        self._filepath = path
        self._refresh_layers()
        self.setWindowTitle(tr("title.with_file", name=path.split("/")[-1]))

    def _save(self):
        if hasattr(self, "_filepath") and self._filepath:
            self._do_save(self._filepath)
        else:
            self._save_as()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.save_as"), "untitled.png",
            tr("dlg.save_filter"))
        if path:
            self._filepath = path
            self._do_save(path)

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.export_png"), "export.png", "PNG (*.png)")
        if path:
            self._do_save(path, flatten=True)

    def _do_save(self, path: str, flatten: bool = False):
        if flatten:
            img = self._document.get_composite()
        else:
            layer = self._document.get_active_layer()
            img = layer.image if layer else self._document.get_composite()
        ok = img.save(path)
        if ok:
            self._status.showMessage(tr("status.saved", path=path))
        else:
            QMessageBox.critical(self, tr("err.title.save_error"), tr("err.could_not_save", path=path))
