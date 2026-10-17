from core.locale import tr
from ui.actions.pixel_target import pixel_layer_for_edit
from ui.document_controller import require_document


class FilterActionsMixin:
    def _blur_average(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import apply_average
        self._push_history(tr("history.average"), modified_index=self._document.active_layer_index)
        layer.image = apply_average(layer.image)
        self._canvas_refresh()

    def _blur_simple(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import apply_blur
        self._push_history(tr("history.blur"), modified_index=self._document.active_layer_index)
        layer.image = apply_blur(layer.image)
        self._canvas_refresh()

    def _blur_more(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import apply_blur_more
        self._push_history(tr("history.blur_more"), modified_index=self._document.active_layer_index)
        layer.image = apply_blur_more(layer.image)
        self._canvas_refresh()

    def _box_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import BoxBlurDialog
        self._push_history(tr("history.before_box_blur"), modified_index=self._document.active_layer_index)
        BoxBlurDialog(layer, self._canvas_refresh, self).exec()

    def _gaussian_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import GaussianBlurDialog
        self._push_history(tr("history.before_gaussian"), modified_index=self._document.active_layer_index)
        GaussianBlurDialog(layer, self._canvas_refresh, self).exec()

    def _motion_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.motion_blur import MotionBlurDialog
        self._push_history(tr("history.before_motion"), modified_index=self._document.active_layer_index)
        MotionBlurDialog(layer, self._canvas_refresh, self).exec()

    def _radial_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.radial_blur import RadialBlurDialog
        self._push_history(tr("history.before_radial"), modified_index=self._document.active_layer_index)
        RadialBlurDialog(layer, self._canvas_refresh, self).exec()

    def _smart_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import SmartBlurDialog
        self._push_history(tr("history.before_smart"), modified_index=self._document.active_layer_index)
        SmartBlurDialog(layer, self._canvas_refresh, self).exec()

    def _surface_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import SurfaceBlurDialog
        self._push_history(tr("history.before_surface"), modified_index=self._document.active_layer_index)
        SurfaceBlurDialog(layer, self._canvas_refresh, self).exec()

    def _shape_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import ShapeBlurDialog
        self._push_history(tr("history.before_shape"), modified_index=self._document.active_layer_index)
        ShapeBlurDialog(layer, self._canvas_refresh, self).exec()

    def _lens_blur(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from core.filters.blur_filters import LensBlurDialog
        self._push_history(tr("history.before_lens"), modified_index=self._document.active_layer_index)
        LensBlurDialog(layer, self._canvas_refresh, self).exec()

    # ── Galleries (Blur/Specific/Render/Sharpen/Stylize/Other/Pixelate/Noise/Distort) ──
    # All ui/filter_gallery.py dialogs: one flow, the history step named
    # after the filter itself.

    @require_document
    def _run_filter_gallery(self, dialog_cls, mode: str):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        title = tr(dialog_cls.MODES[mode].title_key).replace('…', '')
        pre_state = self._make_history_state(title, modified_index=self._document.active_layer_index)
        if dialog_cls(layer, mode, self._canvas_refresh, self).exec():
            self._history.push(pre_state)
            self._refresh_layers()
        self._canvas_refresh()

    def _open_blur_gallery(self, mode: str):
        from ui.blur_gallery_dialog import BlurGalleryDialog
        self._run_filter_gallery(BlurGalleryDialog, mode)

    def _blur_field(self): self._open_blur_gallery("field")
    def _blur_iris(self): self._open_blur_gallery("iris")
    def _blur_tilt_shift(self): self._open_blur_gallery("tilt_shift")
    def _blur_path(self): self._open_blur_gallery("path")
    def _blur_spin(self): self._open_blur_gallery("spin")

    def _open_specific_filter(self, mode: str):
        from ui.specific_filters_dialog import SpecificFiltersDialog
        self._run_filter_gallery(SpecificFiltersDialog, mode)

    def _open_render(self, mode: str):
        from ui.render_dialog import RenderDialog
        self._run_filter_gallery(RenderDialog, mode)

    def _open_sharpen(self, mode: str):
        from ui.sharpen_dialog import SharpenDialog
        self._run_filter_gallery(SharpenDialog, mode)

    def _open_stylize(self, mode: str):
        from ui.stylize_dialog import StylizeDialog
        self._run_filter_gallery(StylizeDialog, mode)

    def _open_other(self, mode: str):
        from ui.other_filters_dialog import OtherFiltersDialog
        self._run_filter_gallery(OtherFiltersDialog, mode)

    def _open_pixelate(self, mode: str):
        from ui.pixelate_dialog import PixelateDialog
        self._run_filter_gallery(PixelateDialog, mode)

    def _open_noise(self, mode: str):
        from ui.noise_dialog import NoiseDialog
        self._run_filter_gallery(NoiseDialog, mode)

    def _open_distort(self, mode: str):
        from ui.distort_dialog import DistortDialog
        self._run_filter_gallery(DistortDialog, mode)
