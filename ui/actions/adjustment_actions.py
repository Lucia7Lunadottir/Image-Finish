from core.locale import tr


class AdjustmentActionsMixin:
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
        BrightnessContrastDialog(layer, self._canvas_refresh, self).exec()

    def _hue_saturation(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        from ui.adjustments_dialog import HueSaturationDialog
        self._push_history(tr("history.before_hs"))
        HueSaturationDialog(layer, self._canvas_refresh, self).exec()

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
