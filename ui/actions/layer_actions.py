from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QPainter, QColor
from core.locale import tr
from ui.document_controller import require_document


# Adjustment-layer type -> its live-preview dialog ("module:Class", imported
# on first use). Types not listed open the generic AdjustmentLayerDialog.
_ADJUSTMENT_LAYER_DIALOGS = {
    "levels":       "ui.levels_dialog:LevelsDialog",
    "curves":       "ui.curves_dialog:CurvesDialog",
    "exposure":     "core.adjustments.exposure:ExposureDialog",
    "vibrance":     "core.adjustments.vibrance:VibranceDialog",
    "black_white":  "core.adjustments.black_white:BlackWhiteDialog",
    "posterize":    "core.adjustments.posterize:PosterizeDialog",
    "threshold":    "core.adjustments.threshold:ThresholdDialog",
    "channel_mixer":   "core.adjustments.channel_mixer:ChannelMixerDialog",
    "selective_color": "core.adjustments.selective_color:SelectiveColorDialog",
    "photo_filter": "core.adjustments.photo_filter:PhotoFilterDialog",
    "gradient_map": "core.adjustments.gradient_map:GradientMapDialog",
    "color_lookup": "core.adjustments.color_lookup:ColorLookupDialog",
    "hdr_toning":   "core.adjustments.hdr_toning:HDRToningDialog",
}


def _adjustment_dialog_class(adj_type: str):
    spec = _ADJUSTMENT_LAYER_DIALOGS.get(adj_type)
    if spec is None:
        return None
    import importlib
    module, cls = spec.split(":")
    return getattr(importlib.import_module(module), cls)


class LayerActionsMixin:
    def _refresh_layers(self):
        if not self._document:
            return
        self._layers_panel.refresh(self._document)
        self._update_status()

    @require_document
    def _on_layer_selected(self, index: int):
        if not self._doc_controller.set_active_layer_index(index):
            return
        self._refresh_layers()

    @require_document
    def _on_layer_visibility(self, index: int, visible: bool):
        layer = self._doc_controller.layer_at(index)
        if layer is None:
            return
        layer.visible = visible
        self._canvas_refresh()

    @require_document
    def _on_layer_opacity(self, index: int, opacity: float):
        layer = self._doc_controller.layer_at(index)
        if layer is None:
            return
        layer.opacity = opacity
        self._canvas_refresh()
        self._refresh_layers()

    @require_document
    def _add_layer(self):
        self._push_history(tr("history.add_layer"))
        self._document.add_layer()
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _duplicate_layer(self):
        self._push_history(tr("history.duplicate_layer"))
        self._document.duplicate_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _delete_layer(self):
        if len(self._document.layers) <= 1:
            QMessageBox.warning(self, tr("err.title.delete_layer"), tr("err.delete_last_layer"))
            return
        self._push_history(tr("history.delete_layer"))
        self._document.remove_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _layer_up(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_up"))
        self._document.move_layer(i, i + 1)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _layer_down(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_down"))
        self._document.move_layer(i, i - 1)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _merge_down(self):
        i = self._document.active_layer_index
        if i == 0:
            return
        bottom = self._doc_controller.layer_at(i - 1)
        top    = self._doc_controller.layer_at(i)
        if bottom is None or top is None:
            return
        self._push_history(tr("history.merge_down"))
        p = QPainter(bottom.image)
        p.setOpacity(top.opacity)
        p.drawImage(top.offset, top.image)
        p.end()
        self._document.remove_layer(i)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _combine_shapes(self, op: str):
        """Layer > Combine Shapes (Photoshop): merges the active vector
        layer's geometry into the vector layer directly below it with a
        path operation — unite, subtract front, intersect, exclude. The
        lower layer keeps its fill/stroke and becomes a path layer."""
        from core.layer import VectorLayer
        doc = self._document
        top = doc.get_active_layer()
        siblings = [l for l in doc.layers if getattr(l, "parent_id", None) == getattr(top, "parent_id", None)]
        pos = siblings.index(top) if top in siblings else -1
        bottom = siblings[pos - 1] if pos > 0 else None
        if not (isinstance(top, VectorLayer) and top.has_vector_geometry()
                and isinstance(bottom, VectorLayer) and bottom.has_vector_geometry()):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, tr("menu.combine_shapes"), tr("msg.combine_shapes_need_two"))
            return
        self._push_history(tr("history.combine_shapes"))
        bottom.combine_with(top.vector_outline(), op)
        doc.remove_layer(doc.layers.index(top))
        doc.active_layer_index = doc.layers.index(bottom)
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _flatten(self):
        self._push_history(tr("history.flatten"))
        self._document.flatten()
        self._refresh_layers()
        self._canvas_refresh()

    # ── Adjustment layers ─────────────────────────────────────────────────
    #
    # Per-type adjustment dialogs (levels, exposure, HDR toning, ...) need a
    # live preview against the composite, so layer creation/editing and
    # dialog selection are handled together by _get_adj_dialog/_new_adj_layer
    # below rather than through the generic AdjustmentLayerDialog.

    def _get_adj_dialog(self, layer, t):
        from core.layer import AdjustmentLayer
        is_adj = isinstance(layer, AdjustmentLayer)
        if is_adj:
            _saved_adj = layer.adjustment_data
            layer.adjustment_data = {"type": t}
            target_img = self._document.get_composite(respect_live_hidden=False)
            layer.adjustment_data = _saved_adj
        else:
            target_img = layer.image

        class LayerProxy:
            def __init__(self, real, img):
                self.__dict__["_real"] = real
                self.__dict__["image"] = img
            def __getattr__(self, name):
                return getattr(self._real, name)
            def __setattr__(self, name, value):
                if name == "image":
                    self.__dict__["image"] = value
                    if not isinstance(self._real, AdjustmentLayer):
                        self._real.image = value
                elif name == "adjustment_data":
                    self._real.adjustment_data = value
                else:
                    setattr(self._real, name, value)

        proxy = LayerProxy(layer, target_img)
        dlg_ref = [None]

        def layer_data():
            """The dialog's own parameters (adjustment_data(), backed by
            core/adjustments/registry.py) — never guessed from widget
            attribute names, which is how layers used to lose or garble
            their settings."""
            dlg = dlg_ref[0]
            if dlg is None or not hasattr(dlg, "adjustment_data"):
                return {"type": t}
            d = dlg.adjustment_data()
            d["type"] = t
            return d

        def wrapped_refresh():
            if is_adj:
                layer.adjustment_data = layer_data()
            self._canvas_refresh()

        dialog_cls = _adjustment_dialog_class(t)
        if dialog_cls is None:
            from ui.adjustment_layer_dialog import AdjustmentLayerDialog
            return AdjustmentLayerDialog(layer, self._canvas_refresh, self)
        from ui.adjustments_dialog import build_adjustment_dialog
        dlg = build_adjustment_dialog(dialog_cls, proxy, wrapped_refresh, self)

        dlg_ref[0] = dlg
        if is_adj:
            dlg._is_adj_layer = True
            dlg._layer = layer
            import copy
            dlg._orig_adj_data = copy.deepcopy(layer.adjustment_data) if layer.adjustment_data else {}
            dlg._adj_type = t

            if hasattr(dlg, "load_adjustment_data") and len(dlg._orig_adj_data) > 1:
                # Re-opening an existing adjustment layer starts from its
                # saved settings, not the dialog's defaults.
                dlg.load_adjustment_data(dlg._orig_adj_data)
            layer.adjustment_data = layer_data()

            dlg.accepted.connect(lambda: setattr(layer, "adjustment_data", layer_data()))
            def on_reject():
                layer.adjustment_data = dlg._orig_adj_data
                self._canvas_refresh()
            dlg.rejected.connect(on_reject)

        return dlg

    def _new_adj_layer(self, adj_type: str = "brightness_contrast"):
        if not self._document: return
        from core.layer import AdjustmentLayer
        idx = self._document.active_layer_index
        self._push_history(tr("history.new_adj_layer"))  # snapshot BEFORE adding
        layer = self._document.add_layer(tr("layer.name.adjustment"), idx + 1, layer_cls=AdjustmentLayer)
        layer.adjustment_data = {"type": adj_type}

        dlg = self._get_adj_dialog(layer, adj_type)
        if dlg is None:
            return

        def on_finished(result):
            if result:
                self._refresh_layers()
            else:
                self._history.undo()  # discard the snapshot we just pushed
                self._document.layers.remove(layer)
                self._document.active_layer_index = idx
                self._canvas_refresh()
                self._refresh_layers()

        # See AdjustmentActionsMixin._show_adj_dialog: dialogs needing real
        # canvas clicks (Curves' eyedroppers) can't be shown via .exec(),
        # which forces modal blocking regardless of setModal().
        if getattr(dlg, "NON_BLOCKING", False):
            dlg.setModal(False)
            dlg.finished.connect(on_finished)
            dlg.show()
        else:
            on_finished(dlg.exec())

    # ── Fill layers ───────────────────────────────────────────────────────

    @require_document
    def _new_fill_layer(self, fill_type: str = "solid"):
        from ui.fill_layer_dialog import FillLayerDialog
        from core.layer import FillLayer
        init = {"type": fill_type, "color": QColor(128, 128, 128)}
        dlg = FillLayerDialog(init, self)
        if not dlg.exec():
            return
        self._push_history(tr("history.new_fill_layer"))
        data = dlg.result_data()
        layer = FillLayer(tr("layer.name.fill"), self._document.width, self._document.height)
        layer.fill_data = data
        i = self._document.active_layer_index + 1
        self._document.layers.insert(i, layer)
        self._document.active_layer_index = i
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _on_edit_layer(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from core.layer import AdjustmentLayer, FillLayer
        # Both dialogs preview on the layer itself, so the undo snapshot is
        # taken *before* they open (taken after OK it already held the new
        # settings, and Undo changed nothing).
        index = self._document.active_layer_index
        if isinstance(layer, FillLayer):
            from ui.fill_layer_dialog import FillLayerDialog
            pre_state = self._make_history_state(tr("history.edit_fill_layer"), modified_index=index)
            dlg = FillLayerDialog(layer, self._canvas_refresh, self)
            if dlg.exec():
                self._history.push(pre_state)
                self._refresh_layers()
            else:
                self._canvas_refresh()
        elif isinstance(layer, AdjustmentLayer):
            t = (layer.adjustment_data or {}).get("type", "")
            pre_state = self._make_history_state(tr("history.edit_adj_layer"), modified_index=index)
            dlg = self._get_adj_dialog(layer, t)
            if dlg is None:
                return

            def on_finished(result):
                if result:
                    self._history.push(pre_state)
                    self._refresh_layers()
                else:
                    self._canvas_refresh()

            if getattr(dlg, "NON_BLOCKING", False):
                dlg.setModal(False)
                dlg.finished.connect(on_finished)
                dlg.show()
            else:
                on_finished(dlg.exec())

    # ── Smart objects ─────────────────────────────────────────────────────

    @require_document
    def _new_smart_object(self):
        layer = self._document.get_active_layer()
        from core.layer import SmartObjectLayer
        if not layer or isinstance(layer, SmartObjectLayer):
            return
        self._push_history(tr("history.new_smart_object"))
        layer = self._document.replace_layer(layer, layer.convert_to(SmartObjectLayer))
        layer.smart_data = {"original": layer.image.copy()}
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _clear_smart_filters(self):
        layer = self._document.get_active_layer()
        from core.layer import SmartObjectLayer
        if isinstance(layer, SmartObjectLayer):
            if layer.smart_data and "original" in layer.smart_data:
                self._push_history(tr("history.clear_smart_filters"))
                layer.image = layer.smart_data["original"].copy()
                self._canvas_refresh()
                self._refresh_layers()

    @require_document
    def _rasterize_layer(self):
        from core.layer import RasterLayer
        layer = self._document.get_active_layer()
        if not layer or type(layer) is RasterLayer:
            return
        self._push_history(tr("history.rasterize_layer"))
        pixels = layer.rasterized_image(self._document)
        layer = self._document.replace_layer(layer, layer.convert_to(RasterLayer))
        if pixels is not None:
            layer.image = pixels
        self._refresh_layers()
        self._canvas_refresh()
