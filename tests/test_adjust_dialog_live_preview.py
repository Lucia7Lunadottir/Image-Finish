"""_AdjustDialog (base for 17 adjustment/filter dialogs in
core/adjustments/* and core/filters/{motion_blur,radial_blur,blur_filters}.py)
re-ran its full _apply_preview() on the whole image on every debounced
slider tick, same bottleneck already fixed for the PreviewCanvasBase
family (see tests/test_preview_canvas_base.py) — on an 8K+ source this
made every adjustment dialog feel like it hung while dragging a slider.

Unlike PreviewCanvasBase, these dialogs paint directly onto the *document*
layer (self._layer.image), which is shown on the main canvas at real
document scale — so unlike the isolated preview-dialog canvases, a
downscaled proxy can't just stay in place after the dialog closes; the
true full-resolution source must be recomputed once in accept().

These tests cover: the downscale/restore mechanism in the shared base
class, the one real outlier that needed its own touch (HDRToningDialog
caches numpy arrays derived from _orig_argb32 once in __init__ instead of
re-reading it per tick — restoring full res without invalidating that
cache would silently keep the final accept() image at the wrong
resolution), and a real crash bug found while auditing this family
(ColorLookupDialog referenced a never-assigned self._image whenever used
as a destructive filter — see core/adjustments/color_lookup.py).
"""
import numpy as np
import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QDialog

from core.layer import RasterLayer
from ui.adjustments_dialog import BrightnessContrastDialog
from ui.preview_canvas_base import _MAX_LIVE_PREVIEW_DIM
from core.adjustments.hdr_toning import HDRToningDialog
from core.adjustments.color_lookup import ColorLookupDialog


def _wait_for_dialog_finished(dlg, timeout_ms=5000):
    """accept() on a downscaled dialog now dispatches the final full-res
    pass to a QThreadPool worker and returns immediately — the dialog only
    actually closes (self._full_res_worker reset to None, QDialog.finished
    emitted) once that worker reports back on the GUI thread. Tests must
    pump the event loop for that to happen, same as the real modal
    dlg.exec() call site does."""
    if dlg._full_res_worker is None:
        return  # accept()/reject() already completed synchronously
    loop = QEventLoop()
    dlg.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert dlg._full_res_worker is None, "worker never reported back within timeout"


def _layer_with_gradient(w, h):
    layer = RasterLayer("L", w, h)
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(w):
        img.setPixelColor(x, 0, QColor(x % 256, 128, 200, 255))
    for y in range(1, h):
        for x in range(w):
            img.setPixelColor(x, y, img.pixelColor(x, 0))
    layer.image = img
    return layer


@pytest.fixture()
def big_layer():
    # Long edge well above _MAX_LIVE_PREVIEW_DIM (1600).
    return _layer_with_gradient(2400, 20)


@pytest.fixture()
def small_layer():
    return _layer_with_gradient(200, 20)


def test_large_image_downscaled_for_interactive_preview(qapp, big_layer):
    dlg = BrightnessContrastDialog(big_layer, lambda: None)
    assert dlg._orig_argb32_full is not None
    assert max(dlg._orig_argb32.width(), dlg._orig_argb32.height()) == _MAX_LIVE_PREVIEW_DIM
    assert dlg._orig_argb32_full.width() == 2400


def test_small_image_not_downscaled(qapp, small_layer):
    dlg = BrightnessContrastDialog(small_layer, lambda: None)
    assert dlg._orig_argb32_full is None
    assert dlg._orig_argb32.width() == 200


def test_accept_runs_full_res_pass_off_the_gui_thread(qapp, big_layer):
    """The final full-res commit is exactly the computation that was too
    slow to run on every slider tick — accept() must not block the caller
    (dispatches to QThreadPool and returns immediately, showing a busy
    progress dialog) instead of freezing the whole app until it's done."""
    dlg = BrightnessContrastDialog(big_layer, lambda: None)
    dlg._bright.set_value(40)
    dlg.accept()
    assert dlg._full_res_worker is not None       # dispatched, not run inline
    assert dlg._full_res_progress is not None
    assert dlg._full_res_progress.isVisible()
    assert dlg.result() == 0                      # dialog hasn't actually closed yet
    _wait_for_dialog_finished(dlg)
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_canvas_refresh_callback_still_fires(qapp, big_layer):
    """self._canvas_refresh is intercepted (to upscale the layer image
    back to full document size first) — the caller-supplied refresh
    callback must still actually run, or the canvas would never repaint."""
    calls = []
    dlg = BrightnessContrastDialog(big_layer, lambda: calls.append(1))
    dlg._bright.set_value(40)
    dlg._apply_preview()
    assert calls == [1]
    dlg.accept()
    _wait_for_dialog_finished(dlg)
    assert calls == [1, 1]


def test_interactive_tick_keeps_real_canvas_at_full_document_size(qapp, big_layer):
    """This dialog paints straight onto the document layer shown on the
    *main* canvas (unlike the isolated PreviewCanvasBase dialogs, which
    have their own preview widget to quietly show a smaller proxy in) —
    so even while _orig_argb32 is a downscaled proxy for speed,
    self._layer.image must stay at the real document resolution on every
    tick, or the layer would visibly shrink/pixelate on the canvas while
    a slider is being dragged, not just lose some detail."""
    dlg = BrightnessContrastDialog(big_layer, lambda: None)
    dlg._bright.set_value(40)
    dlg._apply_preview()  # simulate a debounced tick while dragging
    assert dlg._orig_argb32.width() == _MAX_LIVE_PREVIEW_DIM  # proxy used internally
    assert big_layer.image.width() == 2400   # but the visible layer stays full-size
    assert big_layer.image.height() == 20


def test_accept_restores_full_resolution_output(qapp, big_layer):
    dlg = BrightnessContrastDialog(big_layer, lambda: None)
    dlg._bright.set_value(40)
    dlg._apply_preview()

    dlg.accept()
    _wait_for_dialog_finished(dlg)
    assert big_layer.image.width() == 2400
    assert big_layer.image.height() == 20


def test_interactive_and_final_pixels_agree_within_resample_error(qapp, big_layer):
    """The downscaled-preview pass and the final full-res pass run the same
    brightness/contrast math on different-resolution source data — they
    should agree closely, not just "some image came out"."""
    dlg = BrightnessContrastDialog(big_layer, lambda: None)
    dlg._bright.set_value(-30)
    dlg._contr.set_value(20)
    dlg.accept()
    _wait_for_dialog_finished(dlg)
    final = big_layer.image
    # A flat-per-row gradient: pixel (100, 5) should be close to the
    # brightness/contrast-adjusted value of the original at that column.
    from ui.adjustments_dialog import apply_brightness_contrast, _to_argb32
    expected = apply_brightness_contrast(_to_argb32(dlg._original), -30, 20)
    c1 = final.pixelColor(100, 5)
    c2 = expected.pixelColor(100, 5)
    assert abs(c1.red() - c2.red()) <= 2
    assert abs(c1.green() - c2.green()) <= 2
    assert abs(c1.blue() - c2.blue()) <= 2


def test_hdr_toning_cache_invalidated_on_full_res_restore(qapp, big_layer):
    """Without _on_full_res_restored(), accept() would swap _orig_argb32
    back to full res but leave _orig_f/_orig_bgr/_orig_alpha (and the
    radius-keyed blur cache) at the old downscaled shape — the final
    _apply_preview() then tries to write a small result_u8 into a
    full-size output array and raises a numpy broadcast error."""
    dlg = HDRToningDialog(big_layer, lambda: None)
    dlg._radius._slider.setValue(80)
    dlg._apply_preview()
    assert dlg._orig_f.shape[1] == _MAX_LIVE_PREVIEW_DIM

    dlg.accept()
    _wait_for_dialog_finished(dlg)  # must not raise inside the worker
    assert big_layer.image.width() == 2400
    assert dlg._orig_f.shape[1] == 2400
    # accept()'s own _apply_preview() pass rebuilds the cache at the
    # now-correct (full) resolution, keyed by the same radius.
    assert dlg._blur_radius == 80
    assert dlg._blur_cache.shape[1] == 2400


def test_hdr_toning_small_image_skips_restore_hook_safely(qapp, small_layer):
    dlg = HDRToningDialog(small_layer, lambda: None)
    dlg._radius._slider.setValue(80)
    dlg._apply_preview()
    dlg.accept()  # no downscale happened — hook must be a no-op, not raise
    assert small_layer.image.width() == 200


def _tiny_identity_lut():
    # 2x2x2 LUT that maps every input to itself (identity).
    pts = []
    for b in range(2):
        for g in range(2):
            for r in range(2):
                pts.append([float(r), float(g), float(b)])
    return {"size": 2, "is_3d": True, "data": pts,
            "domain_min": [0.0, 0.0, 0.0], "domain_max": [1.0, 1.0, 1.0]}


def test_color_lookup_destructive_mode_does_not_crash(qapp, small_layer):
    """Regression: _apply_preview() used to do QPainter(self._image) with
    self._image never assigned anywhere in the class — an AttributeError
    raised from inside the debounce-timer slot, which aborts the whole
    process in this PyQt6 build (see core/app_logging.install_excepthook).
    _is_adj_layer defaults to False here, exactly like the real
    'Image > Adjustments > Color Lookup...' menu path."""
    dlg = ColorLookupDialog(small_layer, lambda: None)
    assert getattr(dlg, "_is_adj_layer", False) is False

    dlg._apply_preview()  # no LUT loaded yet — must not raise
    assert small_layer.image.width() == 200

    dlg._lut = _tiny_identity_lut()
    dlg._apply_preview()  # must not raise, and must actually write pixels
    assert small_layer.image.width() == 200
    c = small_layer.image.pixelColor(10, 0)
    assert c.red() == 10 % 256
