from core.locale import tr
from ui.actions.pixel_target import pixel_layer_for_edit


class AdjustmentActionsMixin:
    def _show_adj_dialog(self, DialogClass, history_desc: str):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        self._push_history(tr(history_desc), modified_index=self._document.active_layer_index)
        from ui.adjustments_dialog import build_adjustment_dialog
        dlg = build_adjustment_dialog(DialogClass, layer, self._canvas_refresh, self)
        # Dialogs that need real clicks on the main canvas (e.g. Curves'
        # eyedroppers) opt out of modal .exec(): QDialog.exec() forces
        # Qt::WA_ShowModal regardless of setModal(), which blocks input to
        # every other window in the app — including the canvas behind it.
        if getattr(DialogClass, "NON_BLOCKING", False):
            dlg.setModal(False)
            dlg.show()
        else:
            dlg.exec()

    def _levels(self):
        from ui.levels_dialog import LevelsDialog
        self._show_adj_dialog(LevelsDialog, "history.before_levels")

    def _curves(self):
        from ui.curves_dialog import CurvesDialog
        self._show_adj_dialog(CurvesDialog, "history.before_curves")

    def _brightness_contrast(self):
        from ui.adjustments_dialog import BrightnessContrastDialog
        self._show_adj_dialog(BrightnessContrastDialog, "history.before_bc")

    def _hue_saturation(self):
        from ui.adjustments_dialog import HueSaturationDialog
        self._show_adj_dialog(HueSaturationDialog, "history.before_hs")

    def _invert(self):
        active = self._document and self._document.get_active_layer()
        if active is not None and getattr(active, "editing_mask", False) and active.mask is not None:
            self._invert_mask()          # Ctrl+I while editing a mask inverts the mask
            return
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from ui.adjustments_dialog import apply_invert
        self._push_history(tr("history.invert"), modified_index=self._document.active_layer_index)
        layer.image = apply_invert(layer.image)
        self._canvas_refresh()

    def _exposure(self):
        from ui.more_adjustments import ExposureDialog
        self._show_adj_dialog(ExposureDialog, "history.before_exposure")

    def _vibrance(self):
        from ui.more_adjustments import VibranceDialog
        self._show_adj_dialog(VibranceDialog, "history.before_vibrance")

    def _black_white(self):
        from ui.more_adjustments import BlackWhiteDialog
        self._show_adj_dialog(BlackWhiteDialog, "history.before_bw")

    def _posterize(self):
        from ui.more_adjustments import PosterizeDialog
        self._show_adj_dialog(PosterizeDialog, "history.before_posterize")

    def _threshold(self):
        from ui.more_adjustments import ThresholdDialog
        self._show_adj_dialog(ThresholdDialog, "history.before_threshold")

    def _channel_mixer(self):
        from ui.more_adjustments import ChannelMixerDialog
        self._show_adj_dialog(ChannelMixerDialog, "history.before_mixer")

    def _selective_color(self):
        from ui.more_adjustments import SelectiveColorDialog
        self._show_adj_dialog(SelectiveColorDialog, "history.before_sel_color")

    def _match_color(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from ui.more_adjustments import MatchColorDialog
        # Any layer that looks like something can be a colour source (fill
        # and shape layers as rendered) — not adjustment layers or groups.
        doc = self._document
        sources = []
        for lyr in doc.layers:
            if lyr is layer or lyr.pixel_access == "none":
                continue
            img = lyr.content_image(doc)
            if img is not None and not img.isNull():
                sources.append((lyr.name, img))
        self._push_history(tr("history.before_match_color"), modified_index=self._document.active_layer_index)
        MatchColorDialog(layer, sources, self._canvas_refresh, self).exec()

    def _shadows_highlights(self):
        from ui.more_adjustments import ShadowsHighlightsDialog
        self._show_adj_dialog(ShadowsHighlightsDialog, "history.before_shadows_hl")

    def _replace_color(self):
        from ui.more_adjustments import ReplaceColorDialog
        self._show_adj_dialog(ReplaceColorDialog, "history.before_replace")

    def _photo_filter(self):
        from ui.more_adjustments import PhotoFilterDialog
        self._show_adj_dialog(PhotoFilterDialog, "history.before_photo_filter")

    def _gradient_map(self):
        from ui.more_adjustments import GradientMapDialog
        self._show_adj_dialog(GradientMapDialog, "history.before_gradient")

    def _color_lookup(self):
        from ui.more_adjustments import ColorLookupDialog
        self._show_adj_dialog(ColorLookupDialog, "history.before_lookup")

    def _equalize(self):
        layer = pixel_layer_for_edit(self)
        if layer is None:
            return
        from ui.more_adjustments import apply_equalize
        self._push_history(tr("history.equalize"), modified_index=self._document.active_layer_index)
        layer.image = apply_equalize(layer.image)
        self._canvas_refresh()

    def _hdr_toning(self):
        from core.adjustments.hdr_toning import HDRToningDialog
        self._show_adj_dialog(HDRToningDialog, "history.before_hdr")
