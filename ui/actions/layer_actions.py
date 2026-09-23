from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QPainter, QColor, QImage
from PyQt6.QtCore import Qt
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

    def _fit_text_layer(self, layer, text: str, opts: dict, doc_x: int, doc_y: int,
                        clip, vertical: bool) -> None:
        """Sizes `layer.image` tightly around the text's own bounding box
        and positions it via `layer.offset`, instead of always allocating
        a full document-sized image at absolute coordinates — the old
        approach silently, permanently clipped any glyph past the canvas
        edge (nothing past the fixed image bounds was ever rendered at
        all). The compositor already draws every layer at `layer.offset`
        (core/document.py, exercised by crop/move already), so a
        smaller-than-canvas layer is not a new concept here.

        `doc_x`/`doc_y` (and `text_data["x"]/["y"]`, which must keep this
        exact meaning — re-edit anchor recovery, hit-testing and
        move_tool.py all read them as document-space) stay document-space;
        only the actual pixel draw position and the selection clip shift
        by `-layer.offset` to land correctly inside the now-smaller image.
        """
        from core.text_layout import TextLayout
        stroke_w = int(opts.get("text_stroke_w", 0))
        shadow_pad = 0
        if opts.get("text_shadow", False):
            shadow_pad = max(abs(int(opts.get("text_shadow_dx", 3))),
                             abs(int(opts.get("text_shadow_dy", 3))))
        padding = 4 + stroke_w + shadow_pad

        layout = TextLayout(text, opts, vertical=vertical)
        bounds = layout.bounding_rect(doc_x, doc_y, padding=padding)

        layer.image = QImage(max(1, bounds.width()), max(1, bounds.height()),
                             QImage.Format.Format_ARGB32_Premultiplied)
        layer.image.fill(Qt.GlobalColor.transparent)
        layer.offset = bounds.topLeft()

        local_clip = clip.translated(-bounds.left(), -bounds.top()) if clip else None
        layout.draw(layer.image, doc_x - bounds.left(), doc_y - bounds.top(), local_clip)

    @require_document
    def _commit_text_edit(self, layer, text: str, font_opts: dict, doc_anchor, vertical: bool = False):
        """Bakes the CanvasWidget's on-canvas text editor result into a text
        layer's pixels and records one undo step. `layer` is None when the
        editor was creating a brand-new text layer."""
        from tools.text_tool import TextTool

        doc = self._document
        text = text.strip()
        if layer is None and not text:
            return

        idx = doc.layers.index(layer) if layer is not None and layer in doc.layers else None
        self._push_history(tr("history.edit_text") if layer is not None else tr("history.add_text"), idx)

        clip = doc.selection if (doc.selection and not doc.selection.isEmpty()) else None

        if layer is not None:
            if not text:
                doc.remove_layer(idx)
            else:
                td = layer.text_data
                self._fit_text_layer(layer, text, font_opts, td["x"], td["y"], clip, vertical)
                merged = {**td, "text": text, **TextTool._snap_opts(font_opts)}
                if vertical:
                    merged["vertical"] = True
                layer.text_data = merged
        else:
            from core.layer import TextLayer
            n = sum(1 for l in doc.layers if getattr(l, "text_data", None)) + 1
            new_layer = TextLayer(f"Text {n}", doc.width, doc.height)
            self._fit_text_layer(new_layer, text, font_opts, doc_anchor.x(), doc_anchor.y(),
                                 clip, vertical)
            new_layer.text_data = {"text": text, "x": doc_anchor.x(), "y": doc_anchor.y(),
                                   **TextTool._snap_opts(font_opts)}
            if vertical:
                new_layer.text_data["vertical"] = True
            doc.layers.append(new_layer)
            doc.active_layer_index = len(doc.layers) - 1

        self._canvas_refresh()
        self._refresh_layers()

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
                elif k == "_curve_points": d["points"] = v
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
        elif t == "curves":
            from ui.curves_dialog import CurvesDialog
            dlg = create_dlg(CurvesDialog)
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
            if dlg is None:
                return

            def on_finished(result):
                if result:
                    self._push_history(tr("history.edit_adj_layer"))
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
        if not layer or getattr(layer, "layer_type", "raster") == "smart_object":
            return
        self._push_history(tr("history.new_smart_object"))
        from core.layer import SmartObjectLayer
        layer = self._document.replace_layer(layer, layer.convert_to(SmartObjectLayer))
        layer.smart_data = {"original": layer.image.copy()}
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
        rendered = None
        if ltype == "fill":
            from core.document import _render_fill_layer
            rendered = _render_fill_layer(layer, self._document.width,
                                          self._document.height)
        from core.layer import RasterLayer
        layer = self._document.replace_layer(layer, layer.convert_to(RasterLayer))
        if ltype == "fill":
            layer.image = rendered
        elif ltype == "adjustment":
            layer.image.fill(0)
        self._refresh_layers()
        self._canvas_refresh()
