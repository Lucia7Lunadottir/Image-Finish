"""ui/filter_gallery.py — the shared frame of the nine filter galleries.

Pins: pixel-distance parameters follow the live-preview proxy (a 10 px blur
on an 8K image used to preview as a 50 px one); the final full-resolution
pass renders the parameters frozen at OK, not the widgets; random filters
(clouds...) show the pattern that will be applied; OK inside the debounce
window applies the current settings; captions are translated."""
import numpy as np
import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QLabel

from core.layer import RasterLayer
from core.locale import tr


def _layer(w=40, h=30):
    layer = RasterLayer("r", w, h)
    for x in range(w):
        for y in range(h):
            layer.image.setPixelColor(x, y, QColor((x * 9) % 256, (y * 13) % 256, 90))
    return layer


def _arr(img):
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    ptr = img.constBits(); ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


def _galleries():
    from ui.noise_dialog import NoiseDialog
    from ui.stylize_dialog import StylizeDialog
    from ui.sharpen_dialog import SharpenDialog
    from ui.pixelate_dialog import PixelateDialog
    from ui.other_filters_dialog import OtherFiltersDialog
    from ui.distort_dialog import DistortDialog
    from ui.render_dialog import RenderDialog
    from ui.blur_gallery_dialog import BlurGalleryDialog
    from ui.specific_filters_dialog import SpecificFiltersDialog
    return (NoiseDialog, StylizeDialog, SharpenDialog, PixelateDialog, OtherFiltersDialog,
            DistortDialog, RenderDialog, BlurGalleryDialog, SpecificFiltersDialog)


def test_every_menu_mode_exists_and_opens(qapp):
    import re
    menu = open("ui/menu_builder.py").read()
    entry = {"_open_noise": "NoiseDialog", "_open_stylize": "StylizeDialog", "_open_sharpen": "SharpenDialog",
             "_open_pixelate": "PixelateDialog", "_open_other": "OtherFiltersDialog",
             "_open_distort": "DistortDialog", "_open_render": "RenderDialog",
             "_open_specific_filter": "SpecificFiltersDialog"}
    by_name = {c.__name__: c for c in _galleries()}
    found = re.findall(r'win\.(_open_\w+)\("(\w+)"\)', menu)
    found += [("_open_blur_gallery", m) for m in ("field", "iris", "tilt_shift", "path", "spin")]
    entry["_open_blur_gallery"] = "BlurGalleryDialog"
    assert len(found) >= 55
    for fn, mode in found:
        cls = by_name[entry[fn]]
        assert mode in cls.MODES, (fn, mode)
        dlg = cls(_layer(), mode, lambda: None)
        assert dlg.preview_img.size() == dlg.orig_img.size()
        assert "menu." not in dlg.windowTitle(), dlg.windowTitle()     # title translated
        dlg.reject()


def test_no_params_caption_is_translated(qapp):
    from ui.sharpen_dialog import SharpenDialog
    dlg = SharpenDialog(_layer(), "sharpen", lambda: None)
    texts = [l.text() for l in dlg.findChildren(QLabel)]
    assert tr("filter.no_params") in texts


def test_spatial_params_follow_the_preview_proxy(qapp):
    from ui.pixelate_dialog import PixelateDialog
    dlg = PixelateDialog(_layer(3200, 40), "mosaic", lambda: None)
    ctx = dlg._context()
    assert ctx.scale == pytest.approx(0.5)
    assert dlg._render_params({"size": 10}, ctx.scale) == {"size": 5}
    assert dlg._render_params({"size": 10}, 1.0) == {"size": 10}
    dlg.reject()


def test_final_pass_uses_params_frozen_at_ok(qapp, monkeypatch):
    import ui.preview_canvas_base as pcb
    from ui.pixelate_dialog import PixelateDialog, Mosaic
    captured = {}
    monkeypatch.setattr(pcb, "start_full_res_worker",
                        lambda dialog, work, done, err: captured.update(work=work, done=done))
    layer = _layer(3200, 40)
    full_src = _arr(layer.image)
    dlg = PixelateDialog(layer, "mosaic", lambda: None)
    dlg._controls["size"].setValue(12)
    dlg.accept()
    dlg._controls["size"].setValue(150)       # moved after OK: must not matter
    captured["work"]()
    captured["done"]()
    from ui.filter_gallery import FilterContext
    expected = Mosaic().apply(full_src, {"size": 12}, FilterContext())
    assert np.array_equal(_arr(layer.image)[..., :3], expected[..., :3])


def test_ok_inside_the_debounce_window_applies_current_settings(qapp):
    from ui.other_filters_dialog import OtherFiltersDialog, HighPass
    from ui.filter_gallery import FilterContext
    layer = _layer()
    src = _arr(layer.image)
    dlg = OtherFiltersDialog(layer, "high_pass", lambda: None)
    dlg._controls["radius"].setValue(3)          # debounce timer now pending
    assert dlg._timer.isActive()
    dlg.accept()
    expected = HighPass().apply(src, {"radius": 3}, FilterContext())
    assert np.array_equal(_arr(layer.image), expected)


@pytest.mark.parametrize("mode", ["clouds", "diff_clouds", "fibers", "wood"])
def test_random_render_filters_apply_what_they_preview(qapp, mode):
    from ui.render_dialog import RenderDialog
    layer = _layer()
    dlg = RenderDialog(layer, mode, lambda: None)
    shown = _arr(dlg.preview_img)
    dlg._apply_effect()                          # a re-render (slider tick) keeps the pattern
    assert np.array_equal(_arr(dlg.preview_img), shown)
    dlg.accept()
    assert np.array_equal(_arr(layer.image), shown)


def test_liquify_stroke_and_undo(qapp):
    from ui.specific_filters_dialog import SpecificFiltersDialog
    layer = _layer()
    dlg = SpecificFiltersDialog(layer, "liquify", lambda: None)
    before = _arr(dlg.preview_img)
    liq = dlg.filter
    liq.push_undo()
    assert liq.warp(20, 15, 28, 15, dlg._params())
    dlg._apply_effect()
    assert not np.array_equal(_arr(dlg.preview_img), before)
    dlg._liquify_undo()
    dlg._apply_effect()
    assert np.array_equal(_arr(dlg.preview_img), before)
    dlg.reject()
