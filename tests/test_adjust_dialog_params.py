"""The _AdjustDialog family renders from a parameter dict, not from widgets.

Bugs this pins down:
- the final full-resolution pass runs on a worker thread, yet most dialogs
  read their sliders inside _apply_preview;
- filter "Reset" showed the *unfiltered* layer although the defaults are
  not a no-op (Gaussian 1.0 px...), so Reset + OK gave an unblurred small
  image but a blurred large one;
- nothing was previewed when a dialog opened, so OK straight away left a
  small image untouched while a large one got the default effect;
- HDR Toning's Reset moved the sliders but never re-rendered.
"""
import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage

from core.layer import RasterLayer


def _img():
    img = QImage(12, 8, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(12):
        for y in range(8):
            img.setPixelColor(x, y, QColor(20 * x % 256, 30 * y % 256, (255 - 20 * x) % 256))
    return img


def _same(a: QImage, b: QImage) -> bool:
    a = a.convertToFormat(QImage.Format.Format_ARGB32)
    b = b.convertToFormat(QImage.Format.Format_ARGB32)
    return a.size() == b.size() and all(
        a.pixel(x, y) == b.pixel(x, y) for x in range(a.width()) for y in range(a.height()))


def _layer():
    layer = RasterLayer("r", 12, 8)
    layer.image = _img()
    return layer


def _filters():
    from core.filters.blur_filters import (GaussianBlurDialog, BoxBlurDialog, SurfaceBlurDialog,
                                           SmartBlurDialog, ShapeBlurDialog, LensBlurDialog)
    from core.filters.motion_blur import MotionBlurDialog
    from core.filters.radial_blur import RadialBlurDialog
    return [GaussianBlurDialog, BoxBlurDialog, SurfaceBlurDialog, SmartBlurDialog,
            ShapeBlurDialog, LensBlurDialog, MotionBlurDialog, RadialBlurDialog]


def _dialogs():
    from core.adjustments.hdr_toning import HDRToningDialog
    from core.adjustments.photo_filter import PhotoFilterDialog
    from core.adjustments.gradient_map import GradientMapDialog
    return _filters() + [HDRToningDialog, PhotoFilterDialog, GradientMapDialog]


def _nudge(dlg):
    """Move every bound slider/combo away from its default."""
    from PyQt6.QtWidgets import QComboBox, QCheckBox
    for w in dlg._bindings.values():
        if isinstance(w, QComboBox):
            w.setCurrentIndex(w.count() - 1)
        elif isinstance(w, QCheckBox):
            w.setChecked(not w.isChecked())
        elif hasattr(w, "_slider"):
            s = w._slider
            s.setValue(s.minimum() + (s.maximum() - s.minimum()) // 3)


@pytest.mark.parametrize("cls", _dialogs(), ids=lambda c: c.__name__)
def test_preview_is_the_render_of_the_params(qapp, cls):
    layer = _layer()
    dlg = cls(layer, lambda: None)
    _nudge(dlg)
    dlg._apply_preview()
    assert _same(layer.image, dlg._render(_img(), dlg._params()))
    dlg.reject()


@pytest.mark.parametrize("cls", _dialogs(), ids=lambda c: c.__name__)
def test_reset_shows_the_defaults_not_the_original(qapp, cls):
    layer = _layer()
    dlg = cls(layer, lambda: None)
    defaults = dlg._params()
    _nudge(dlg)
    dlg._apply_preview()
    dlg._reset_to_defaults()
    assert dlg._params() == defaults
    assert _same(layer.image, dlg._render(_img(), defaults))
    dlg.reject()


@pytest.mark.parametrize("cls", _dialogs(), ids=lambda c: c.__name__)
def test_render_uses_frozen_params_not_widgets(qapp, cls):
    layer = _layer()
    dlg = cls(layer, lambda: None)
    _nudge(dlg)
    frozen = dlg.adjustment_data()
    dlg._frozen_data = frozen
    dlg._reset_to_defaults()                 # widgets change after freezing...
    dlg._apply_preview()                     # ...the final pass ignores them
    assert _same(layer.image, dlg._render(_img(), dlg._normalize(frozen)))


def test_ok_right_after_opening_applies_the_defaults(qapp):
    from core.adjustments.photo_filter import PhotoFilterDialog
    from core.adjustments.registry import apply_adjustment, get_kind
    layer = _layer()
    dlg = PhotoFilterDialog(layer, lambda: None)
    assert dlg._timer.isActive()             # first preview is scheduled on open
    dlg.accept()                             # before the debounce fired
    expected = apply_adjustment(_img(), {"type": "photo_filter", **get_kind("photo_filter").defaults()})
    assert _same(layer.image, expected)


def test_cancel_restores_the_original(qapp):
    from core.filters.blur_filters import GaussianBlurDialog
    layer = _layer()
    dlg = GaussianBlurDialog(layer, lambda: None)
    dlg._apply_preview()
    dlg.reject()
    assert _same(layer.image, _img())


def test_gaussian_radius_is_in_pixels(qapp):
    from core.filters.blur_filters import GaussianBlurDialog, apply_gaussian_blur
    layer = _layer()
    dlg = GaussianBlurDialog(layer, lambda: None)
    dlg._radius.set_value(2.5)
    assert dlg._params()["radius"] == pytest.approx(2.5)
    dlg._apply_preview()
    assert _same(layer.image, apply_gaussian_blur(_img(), 2.5))


def test_hdr_cached_render_matches_the_registry(qapp):
    from core.adjustments.hdr_toning import HDRToningDialog
    from core.adjustments.registry import apply_adjustment
    layer = _layer()
    dlg = HDRToningDialog(layer, lambda: None)
    dlg._radius.set_value(3)
    dlg._strength.set_value(70)
    dlg._apply_preview()
    expected = apply_adjustment(_img(), dlg.adjustment_data())
    a = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
    b = expected.convertToFormat(QImage.Format.Format_ARGB32)
    # cached vs standalone path: same formula, allow 1-level rounding
    diff = max(abs(((a.pixel(x, y) >> s) & 255) - ((b.pixel(x, y) >> s) & 255))
               for x in range(12) for y in range(8) for s in (0, 8, 16))
    assert diff <= 1


@pytest.mark.parametrize("mode", ["Spin", "Zoom"])
def test_radial_blur_both_modes_run(qapp, mode):
    from core.filters.radial_blur import apply_radial_blur
    out = apply_radial_blur(_img(), mode, 30)
    assert out.size() == _img().size() and not _same(out, _img())


def test_pixel_distances_scale_with_the_preview_proxy(qapp, monkeypatch):
    """A large image is previewed on a downscaled copy: the blur radius has
    to shrink with it, or the preview blurs several times stronger than OK
    will. The final full-resolution pass gets the real radius."""
    from core.filters.blur_filters import GaussianBlurDialog
    big = RasterLayer("big", 3200, 40)
    big.image.fill(QColor(90, 120, 30))
    dlg = GaussianBlurDialog(big, lambda: None)
    seen = []
    monkeypatch.setattr(dlg, "_render", lambda src, p: (seen.append((src.width(), p["radius"])), src)[1])
    dlg._radius.set_value(4.0)
    dlg._apply_preview()
    assert seen[-1] == (1600, pytest.approx(2.0))
    dlg._frozen_data = dlg.adjustment_data()
    dlg._orig_argb32 = dlg._orig_argb32_full          # what accept() swaps in
    dlg._orig_argb32_full = None
    dlg._apply_preview()
    assert seen[-1] == (3200, pytest.approx(4.0))


# ── Levels / Curves on the shared base ─────────────────────────────────────
# They used to paint into the QImage they were given, had no live-preview
# proxy (every tick re-ran on the full 8K image), and OK inside the
# debounce window kept the previous preview.

def test_levels_preview_ok_and_cancel(qapp):
    from ui.levels_dialog import LevelsDialog, apply_levels
    layer = _layer()
    dlg = LevelsDialog(layer, lambda: None)
    dlg._black_sp.setValue(30)                 # debounce pending
    dlg._white_sp.setValue(200)
    dlg.accept()
    assert _same(layer.image, apply_levels(_img(), 30, 1.0, 200, 0, 255))

    layer = _layer()
    dlg = LevelsDialog(layer, lambda: None)
    dlg._gamma_sp.setValue(2.0)
    dlg._apply_preview()
    assert not _same(layer.image, _img())
    dlg.reject()
    assert _same(layer.image, _img())


def test_levels_auto_previews(qapp):
    from ui.levels_dialog import LevelsDialog, apply_levels
    layer = _layer()
    dlg = LevelsDialog(layer, lambda: None)
    dlg._auto()
    dlg._apply_preview()
    p = dlg._params()
    assert _same(layer.image, apply_levels(_img(), p["black"], p["gamma"], p["white"], 0, 255))


def test_levels_uses_the_live_preview_proxy_on_large_images(qapp):
    from ui.levels_dialog import LevelsDialog
    big = RasterLayer("big", 3200, 40)
    dlg = LevelsDialog(big, lambda: None)
    assert dlg._orig_argb32.width() == 1600 and dlg._orig_argb32_full.width() == 3200
    dlg.reject()


def test_curves_eyedropper_samples_full_res_in_layer_coordinates(qapp):
    from ui.curves_dialog import CurvesDialog
    big = RasterLayer("big", 3200, 40)
    big.image.fill(QColor(0, 0, 0))
    big.image.setPixelColor(2001, 10, QColor(200, 200, 200))
    big.offset = QPoint(100, 0)
    dlg = CurvesDialog(big, lambda: None)
    dlg._picking = "white"
    dlg._sample_point(2101, 10)               # document point over that pixel
    pts = dlg.adjustment_data()["points"]["rgb"]
    assert (200, 255) in [tuple(p) for p in pts]
    dlg.reject()
