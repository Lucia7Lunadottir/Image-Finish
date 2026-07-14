from core.locale import tr
from ui.document_controller import require_document


class FilterActionsMixin:
    def _blur_average(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_average
        self._push_history(tr("history.average"), modified_index=self._document.active_layer_index)
        layer.image = apply_average(layer.image)
        self._canvas_refresh()

    def _blur_simple(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_blur
        self._push_history(tr("history.blur"), modified_index=self._document.active_layer_index)
        layer.image = apply_blur(layer.image)
        self._canvas_refresh()

    def _blur_more(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import apply_blur_more
        self._push_history(tr("history.blur_more"), modified_index=self._document.active_layer_index)
        layer.image = apply_blur_more(layer.image)
        self._canvas_refresh()

    def _box_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import BoxBlurDialog
        self._push_history(tr("history.before_box_blur"), modified_index=self._document.active_layer_index)
        BoxBlurDialog(layer, self._canvas_refresh, self).exec()

    def _gaussian_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import GaussianBlurDialog
        self._push_history(tr("history.before_gaussian"), modified_index=self._document.active_layer_index)
        GaussianBlurDialog(layer, self._canvas_refresh, self).exec()

    def _motion_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.motion_blur import MotionBlurDialog
        self._push_history(tr("history.before_motion"), modified_index=self._document.active_layer_index)
        MotionBlurDialog(layer, self._canvas_refresh, self).exec()

    def _radial_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.radial_blur import RadialBlurDialog
        self._push_history(tr("history.before_radial"), modified_index=self._document.active_layer_index)
        RadialBlurDialog(layer, self._canvas_refresh, self).exec()

    def _smart_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import SmartBlurDialog
        self._push_history(tr("history.before_smart"), modified_index=self._document.active_layer_index)
        SmartBlurDialog(layer, self._canvas_refresh, self).exec()

    def _surface_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import SurfaceBlurDialog
        self._push_history(tr("history.before_surface"), modified_index=self._document.active_layer_index)
        SurfaceBlurDialog(layer, self._canvas_refresh, self).exec()

    def _shape_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import ShapeBlurDialog
        self._push_history(tr("history.before_shape"), modified_index=self._document.active_layer_index)
        ShapeBlurDialog(layer, self._canvas_refresh, self).exec()

    def _lens_blur(self):
        layer = self._document and self._document.get_active_layer()
        if not layer:
            return
        from core.filters.blur_filters import LensBlurDialog
        self._push_history(tr("history.before_lens"), modified_index=self._document.active_layer_index)
        LensBlurDialog(layer, self._canvas_refresh, self).exec()

    # ── Galleries (Blur/Specific/Render/Sharpen/Stylize/Other/Pixelate/Noise/Distort) ──

    @require_document
    def _open_blur_gallery(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr("menu.blur_gallery") + f" ({mode})", modified_index=self._document.active_layer_index)

        from ui.blur_gallery_dialog import BlurGalleryDialog
        dlg = BlurGalleryDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    def _blur_field(self): self._open_blur_gallery("field")
    def _blur_iris(self): self._open_blur_gallery("iris")
    def _blur_tilt_shift(self): self._open_blur_gallery("tilt_shift")
    def _blur_path(self): self._open_blur_gallery("path")
    def _blur_spin(self): self._open_blur_gallery("spin")

    @require_document
    def _open_specific_filter(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.filter.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.specific_filters_dialog import SpecificFiltersDialog
        dlg = SpecificFiltersDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_render(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.render.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.render_dialog import RenderDialog
        dlg = RenderDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_sharpen(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.sharpen.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.sharpen_dialog import SharpenDialog
        dlg = SharpenDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_stylize(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.stylize.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.stylize_dialog import StylizeDialog
        dlg = StylizeDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_other(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.other.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.other_filters_dialog import OtherFiltersDialog
        dlg = OtherFiltersDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_pixelate(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.pixelate.{mode}").replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.pixelate_dialog import PixelateDialog
        dlg = PixelateDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_noise(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        desc_key = "menu.noise.add"
        if mode == "despeckle": desc_key = "menu.noise.despeckle"
        elif mode == "dust_scratches": desc_key = "menu.noise.dust"
        elif mode == "median": desc_key = "menu.noise.median"
        elif mode == "reduce_noise": desc_key = "menu.noise.reduce"

        pre_state = self._make_history_state(tr(desc_key).replace('…', ''), modified_index=self._document.active_layer_index)

        from ui.noise_dialog import NoiseDialog
        if NoiseDialog(layer, mode, self._canvas_refresh, self).exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()

    @require_document
    def _open_distort(self, mode: str):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull() or getattr(layer, "layer_type", "raster") not in ("raster", "smart_object"):
            return

        pre_state = self._make_history_state(tr(f"menu.distort.{mode}"), modified_index=self._document.active_layer_index)

        from ui.distort_dialog import DistortDialog
        dlg = DistortDialog(layer, mode, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
            self._canvas_refresh()
            self._refresh_layers()
        else:
            self._canvas_refresh()
