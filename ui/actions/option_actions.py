"""The options bar: tool options, its command buttons, foreground/background colour (moved out of MainWindow)."""

from PyQt6.QtGui import QColor
from PyQt6.QtGui import QPainterPath
from core.locale import tr


class OptionActionsMixin:
    # Options-bar keys that are commands (buttons), not tool options: one
    # method each instead of a chain of `if key == ...` in _on_opt_changed.
    _OPTION_COMMANDS = {
        "text_edit_cancel":    "_opt_cmd_text_edit_cancel",
        "align_layer":         "_align_layer",
        "reset_view_rotation": "_opt_cmd_reset_view_rotation",
        "transform_params":    "_opt_cmd_transform_params",
        "sampler_clear":       "_opt_cmd_sampler_clear",
        "ruler_clear":         "_opt_cmd_ruler_clear",
        "clear_slices":        "_opt_cmd_clear_slices",
        "move_apply":          "_opt_cmd_move_apply",
        "move_cancel":         "_opt_cmd_move_cancel",
        "pen_action":          "_opt_cmd_pen_action",
    }

    def _opt_cmd_text_edit_cancel(self, _value):
        self._cancel_text_edit()

    def _opt_cmd_reset_view_rotation(self, _value):
        self._canvas.reset_rotation()

    def _opt_cmd_transform_params(self, params):
        tool = self._canvas.active_tool
        if hasattr(tool, "set_transform_params"):
            tool.set_transform_params(self._document, params)
            self._canvas_refresh()

    def _opt_cmd_sampler_clear(self, _value):
        tool = self._tools.get("ColorSampler")
        if tool:
            tool.markers.clear()
        self._canvas_refresh()

    def _opt_cmd_ruler_clear(self, _value):
        tool = self._tools.get("Ruler")
        if tool:
            tool.clear()
        self._canvas_refresh()

    def _opt_cmd_clear_slices(self, _value):
        if hasattr(self._document, "slices"):
            self._document.slices.clear()
            self._canvas_refresh()

    def _opt_cmd_move_apply(self, _value):
        self._commit_transforms()

    def _opt_cmd_move_cancel(self, _value):
        self._cancel_transform()

    def _opt_cmd_pen_action(self, action_name):
        tool = self._canvas.active_tool
        if not hasattr(tool, "perform_action"):
            return
        result = tool.perform_action(self._document, action_name, self._canvas.fg_color)
        if result:
            action, path = result
            if action == "selection":
                self._push_history(tr("history.make_selection"))
                self._document.selection = path
            elif action == "shape":
                self._push_history(tr("history.new_vector_shape"))
                self._new_shape_layer_from_path(path)
        self._refresh_layers()
        self._canvas_refresh()

    def _new_shape_layer_from_path(self, path):
        from core.layer import VectorLayer
        doc = self._document
        layer = doc.add_layer(doc.next_layer_name(VectorLayer, "layer.name.path"),
                              doc.active_layer_index + 1, layer_cls=VectorLayer)
        layer.vector_mask = QPainterPath(path)
        layer.vector_mask_enabled = True
        # Live geometry, not a one-time raster bake: render_into fills
        # `vector_mask` fresh on every render, so the path stays exact
        # instead of degrading like a pixel bake would under scale/rotate.
        layer.path_style = {"fill_color": QColor(self._canvas.fg_color),
                            "stroke_color": None, "stroke_width": 0.0}
        layer.rebake_thumbnail()

    def _on_opt_changed(self, key: str, value):
        command = self._OPTION_COMMANDS.get(key)
        if command is not None:
            getattr(self, command)(value)
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
        # Same for the brush settings: options bar, Brushes panel and the
        # right-click brush picker all edit them.
        for page_tool in ("Text", "Brush"):
            page = self._opts_bar.page_for(page_tool) if hasattr(self, "_opts_bar") else None
            if page is not None and hasattr(page, "update_from_opts"):
                page.update_from_opts(canvas.tool_opts)
        if hasattr(self, "_brushes_panel"):
            self._brushes_panel.refresh(canvas)
        # tool_opts is stored above, but nothing here ever asked the canvas
        # to actually repaint — the live text-edit preview (which reads
        # tool_opts fresh every paintGL() frame) only looked live before
        # because *something else* happened to trigger a repaint shortly
        # after. Explicitly: an option change must be visible immediately,
        # not just eventually.
        canvas.update()

    # ================================================================= Colour / Options
    def _on_fg_changed(self, c: QColor):
        if not hasattr(self, "_doc_tabs"): return
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).fg_color = c

    def _on_bg_changed(self, c: QColor):
        if not hasattr(self, "_doc_tabs"): return
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).bg_color = c
