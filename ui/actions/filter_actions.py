from core.locale import tr


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
