from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QPainter, QColor
from core.locale import tr
from ui.document_controller import require_document


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
        is_adj = getattr(layer, "layer_type", "raster") == "adjustment"
        if is_adj:
            _saved_adj = layer.adjustment_data
            layer.adjustment_data = {"type": t}
            target_img = self._document.get_composite()
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
                    if getattr(self._real, "layer_type", "raster") != "adjustment":
                        self._real.image = value
                elif name == "adjustment_data":
                    self._real.adjustment_data = value
                else:
                    setattr(self._real, name, value)

        proxy = LayerProxy(layer, target_img)
        dlg_ref = [None]

        def scrape_data():
            d = {"type": t}
            dlg = dlg_ref[0]
            if not dlg: return d
            for k, v in dlg.__dict__.items():
                if k == "_lut": d["lut"] = v
                elif hasattr(v, "value") and callable(v.value):
                    try: d[k.lstrip('_')] = v.value()
                    except TypeError: pass
                elif hasattr(v, "color") and callable(v.color):
                    try: d[k.lstrip('_')] = v.color()
                    except TypeError: pass
                elif hasattr(v, "isChecked") and callable(v.isChecked):
                    try: d[k.lstrip('_')] = v.isChecked()
                    except TypeError: pass
            return d

        def wrapped_refresh():
            if is_adj:
                layer.adjustment_data = scrape_data()
            self._canvas_refresh()

        import inspect
        def create_dlg(DialogClass):
            sig = inspect.signature(DialogClass.__init__)
            params = [p for p in sig.parameters.values() if p.name != 'self']
            if len(params) >= 3 and params[1].name in ("canvas_refresh", "cb"):
                return DialogClass(proxy, wrapped_refresh, self)
            else:
                dlg_inst = DialogClass(target_img, self)
                dlg_inst._canvas_refresh = wrapped_refresh
                return dlg_inst

        if t == "levels":
            from ui.levels_dialog import LevelsDialog
            dlg = create_dlg(LevelsDialog)
        elif t == "exposure":
            from ui.more_adjustments import ExposureDialog
            dlg = create_dlg(ExposureDialog)
        elif t == "vibrance":
            from ui.more_adjustments import VibranceDialog
            dlg = create_dlg(VibranceDialog)
        elif t == "black_white":
            from ui.more_adjustments import BlackWhiteDialog
            dlg = create_dlg(BlackWhiteDialog)
        elif t == "posterize":
            from ui.more_adjustments import PosterizeDialog
            dlg = create_dlg(PosterizeDialog)
        elif t == "threshold":
            from ui.more_adjustments import ThresholdDialog
            dlg = create_dlg(ThresholdDialog)
        elif t == "photo_filter":
            from ui.more_adjustments import PhotoFilterDialog
            dlg = create_dlg(PhotoFilterDialog)
        elif t == "gradient_map":
            from ui.more_adjustments import GradientMapDialog
            dlg = create_dlg(GradientMapDialog)
        elif t == "color_lookup":
            from core.adjustments.color_lookup import ColorLookupDialog
            dlg = create_dlg(ColorLookupDialog)
        elif t == "hdr_toning":
            from core.adjustments.hdr_toning import HDRToningDialog
            dlg = create_dlg(HDRToningDialog)
        else:
            from ui.adjustment_layer_dialog import AdjustmentLayerDialog
            return AdjustmentLayerDialog(layer, self._canvas_refresh, self)

        dlg_ref[0] = dlg
        if is_adj:
            dlg._is_adj_layer = True
            dlg._layer = layer
            import copy
            dlg._orig_adj_data = copy.deepcopy(layer.adjustment_data) if layer.adjustment_data else {}
            dlg._adj_type = t

            layer.adjustment_data = scrape_data()

            dlg.accepted.connect(lambda: setattr(layer, "adjustment_data", scrape_data()))
            def on_reject():
                layer.adjustment_data = dlg._orig_adj_data
                self._canvas_refresh()
            dlg.rejected.connect(on_reject)

        return dlg

    def _new_adj_layer(self, adj_type: str = "brightness_contrast"):
        if not self._document: return
        idx = self._document.active_layer_index
        self._push_history(tr("history.new_adj_layer"))  # snapshot BEFORE adding
        layer = self._document.add_layer(tr("layer.name.adjustment"), idx + 1)
        layer.layer_type = "adjustment"
        layer.adjustment_data = {"type": adj_type}

        dlg = self._get_adj_dialog(layer, adj_type)
        if dlg and dlg.exec():
            self._refresh_layers()
        else:
            self._history.undo()  # discard the snapshot we just pushed
            self._document.layers.remove(layer)
            self._document.active_layer_index = idx
            self._canvas_refresh()
            self._refresh_layers()

    # ── Fill layers ───────────────────────────────────────────────────────

    @require_document
    def _new_fill_layer(self, fill_type: str = "solid"):
        from ui.fill_layer_dialog import FillLayerDialog
        from core.layer import Layer
        init = {"type": fill_type, "color": QColor(128, 128, 128)}
        dlg = FillLayerDialog(init, self)
        if not dlg.exec():
            return
        self._push_history(tr("history.new_fill_layer"))
        data = dlg.result_data()
        layer = Layer(tr("layer.name.fill"), self._document.width, self._document.height)
        layer.layer_type = "fill"
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
        ltype = getattr(layer, "layer_type", "raster")
        if ltype == "fill":
            from ui.fill_layer_dialog import FillLayerDialog
            dlg = FillLayerDialog(layer, self._canvas_refresh, self)
            if dlg.exec():
                self._push_history(tr("history.edit_fill_layer"))
                self._refresh_layers()
            else:
                self._canvas_refresh()
        elif ltype == "adjustment":
            t = (layer.adjustment_data or {}).get("type", "")
            dlg = self._get_adj_dialog(layer, t)
            if dlg and dlg.exec():
                self._push_history(tr("history.edit_adj_layer"))
                self._refresh_layers()
            else:
                self._canvas_refresh()

    # ── Smart objects ─────────────────────────────────────────────────────

    @require_document
    def _new_smart_object(self):
        layer = self._document.get_active_layer()
        if not layer or getattr(layer, "layer_type", "raster") == "smart_object":
            return
        self._push_history(tr("history.new_smart_object"))
        layer.layer_type = "smart_object"
        if not hasattr(layer, "smart_data") or layer.smart_data is None:
            layer.smart_data = {}
        layer.smart_data["original"] = layer.image.copy()
        self._refresh_layers()
        self._canvas_refresh()

    @require_document
    def _clear_smart_filters(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "layer_type", "raster") == "smart_object":
            if hasattr(layer, "smart_data") and layer.smart_data and "original" in layer.smart_data:
                self._push_history(tr("history.clear_smart_filters"))
                layer.image = layer.smart_data["original"].copy()
                self._canvas_refresh()
                self._refresh_layers()

    @require_document
    def _rasterize_layer(self):
        layer = self._document.get_active_layer()
        if not layer or layer.layer_type == "raster":
            return
        self._push_history(tr("history.rasterize_layer"))
        ltype = layer.layer_type
        if ltype == "fill":
            from core.document import _render_fill_layer
            layer.image = _render_fill_layer(layer, self._document.width,
                                             self._document.height)
        elif ltype == "adjustment":
            layer.image.fill(0)
        layer.layer_type = "raster"
        layer.adjustment_data = None
        layer.fill_data = None
        layer.shape_data = None
        layer.text_data = None
        layer.smart_data = None
        self._refresh_layers()
        self._canvas_refresh()
