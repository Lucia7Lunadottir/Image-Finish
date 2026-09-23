"""ui.preview_canvas_base.run_full_res_commit() — the fix for a real,
user-reported freeze: opening a filter dialog (Stylize > Crystallize, in
the report) on a large image and clicking OK made the whole window manager
flag the app as "not responding" with no visible progress at all.

Every one of the 9 PreviewCanvasBase-family filter dialogs (Noise,
Stylize, Sharpen, Pixelate, Other Filters, Blur Gallery, Distort, Render,
Specific Filters) used to call restore_full_res_before_accept() +
self._apply_effect() synchronously, right inside accept() — i.e. exactly
the full-resolution recompute the live-preview downscale exists to avoid
running on every slider tick, blocking the GUI thread for however long
that takes. This mirrors the fix already applied to the separate
_AdjustDialog family (see tests/test_adjust_dialog_live_preview.py) but
had to be a free function, not a base-class method, since these 9 dialogs
are plain QDialog subclasses with no shared accept()-owning base class.
"""
import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QDialog

from ui.preview_canvas_base import (
    run_full_res_commit, downscale_for_live_preview, _MAX_LIVE_PREVIEW_DIM,
)


def _wait_for_dialog_finished(dlg, timeout_ms=5000):
    # run_full_res_commit only ever creates _full_res_worker on the dialog
    # when it actually dispatches to a background thread — a dialog whose
    # image was never downscaled finishes accept() synchronously and never
    # gets the attribute at all.
    if getattr(dlg, "_full_res_worker", None) is None:
        return
    loop = QEventLoop()
    dlg.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert dlg._full_res_worker is None, "worker never reported back within timeout"


class _FakeLayer:
    def __init__(self, image):
        self.image = image


class _FakeCanvas:
    """Stands in for the real PreviewCanvasBase-derived canvas: only
    .update() matters here (the one GUI call every _apply_effect() makes)."""
    def __init__(self):
        self.update_calls = 0

    def update(self):
        self.update_calls += 1


class _StubFilterDialog(QDialog):
    """Minimal stand-in for the 9 real filter dialogs: same attribute
    shape (.layer, .canvas, .orig_img/.orig_img_full/.orig_arr,
    .preview_img) and the same accept() shape they all share."""

    def __init__(self, w, h, downscale=True):
        super().__init__()
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(10, 20, 30, 255))
        self.layer = _FakeLayer(QImage(img))
        self.canvas = _FakeCanvas()
        self.orig_img = img
        self.preview_img = img.copy()
        self.orig_img_full = None
        if downscale:
            small = downscale_for_live_preview(img)
            if small is not None:
                self.orig_img_full = img
                self.orig_img = small
                self.preview_img = small.copy()
        from core.pixel_buffer import qimage_argb_view
        self.orig_arr = qimage_argb_view(self.orig_img, writable=False)[
            :, :self.orig_img.width(), :].copy()
        self.apply_calls = 0

    def _apply_effect(self):
        self.apply_calls += 1
        # Every real dialog's _apply_effect ends with exactly this call.
        self.canvas.update()
        self.preview_img = self.orig_img.copy()

    def accept(self):
        if run_full_res_commit(self, self._apply_effect):
            self.layer.image = self.preview_img
            super().accept()


def test_no_downscale_runs_synchronously_like_before(qapp):
    dlg = _StubFilterDialog(200, 20, downscale=False)
    dlg.accept()
    assert getattr(dlg, "_full_res_worker", None) is None  # never dispatched
    assert dlg.result() == QDialog.DialogCode.Accepted
    # Never downscaled means every interactive tick already ran at full
    # resolution — accept() must NOT re-run _apply_effect() a redundant
    # extra time, exactly like the original (pre-progress-bar) accept().
    assert dlg.apply_calls == 0


def test_downscaled_accept_dispatches_worker_and_does_not_block(qapp):
    dlg = _StubFilterDialog(2400, 20, downscale=True)
    assert dlg.orig_img_full is not None
    assert dlg.orig_img.width() == _MAX_LIVE_PREVIEW_DIM

    dlg.accept()
    assert dlg._full_res_worker is not None       # dispatched to a background thread
    assert dlg._full_res_progress is not None
    assert dlg._full_res_progress.isVisible()
    assert dlg.result() == 0                      # dialog has not actually closed yet
    # canvas.update() is suppressed while the worker runs (would be a
    # cross-thread widget call otherwise) — the shadow is a plain instance
    # attribute, so its presence proves the real bound method was replaced.
    assert "update" in dlg.canvas.__dict__

    _wait_for_dialog_finished(dlg)
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.orig_img.width() == 2400           # restored to full res before the pass
    assert dlg.layer.image.width() == 2400
    # update() stays suppressed for the entire threaded pass, and the
    # dialog closes immediately on success — there's nothing left to
    # repaint, so it's correct that update() never actually ran for real.
    assert dlg.canvas.update_calls == 0
    assert dlg._full_res_progress is None


def test_progress_bar_stays_static_indeterminate(qapp):
    """A prior attempt drove the bar with a QTimer stepping setValue()
    0..100..0 to force a visible animation (the app's global stylesheet
    silently kills the native busy/marquee animation for indeterminate
    QProgressDialogs — see [[image-finish-global-qss-breaks-native-behavior]]).
    Live-tested and reverted: QProgressDialog.setValue() re-triggers its
    own internal show()/layout machinery on every call (active because
    setMinimumDuration(0) keeps it "always eligible to reshow"); at a 25
    Hz tick rate a real window manager treated each one as the window
    being remapped, repeatedly stealing focus — reported live as "the
    window keeps recreating itself". The static indeterminate bar (range
    0,0, no periodic setValue()) doesn't visually animate under this app's
    stylesheet, but doesn't fight the window manager either — accepted as
    the better trade-off. This guards against silently reintroducing the
    determinate+timer pattern."""
    import time

    dlg = _StubFilterDialog(2400, 20, downscale=True)
    dlg._apply_effect = lambda: time.sleep(0.2)

    dlg.accept()
    progress = dlg._full_res_progress
    assert progress is not None
    assert (progress.minimum(), progress.maximum()) == (0, 0)

    _wait_for_dialog_finished(dlg)


def test_error_in_worker_reverts_and_rejects(qapp):
    dlg = _StubFilterDialog(2400, 20, downscale=True)

    def boom():
        raise RuntimeError("synthetic failure")
    dlg._apply_effect = boom

    dlg.accept()
    assert dlg._full_res_worker is not None
    _wait_for_dialog_finished(dlg)

    assert dlg.result() == QDialog.DialogCode.Rejected
    assert dlg._full_res_progress is None
    # canvas.update was restored even though the worker raised.
    assert dlg.canvas.update_calls == 0
    dlg.canvas.update()
    assert dlg.canvas.update_calls == 1


def test_pre_apply_runs_synchronously_before_the_threaded_pass(qapp):
    """blur_gallery_dialog.py's use case: invalidate a resolution-keyed
    cache right after the restore, before the worker starts."""
    dlg = _StubFilterDialog(2400, 20, downscale=True)
    dlg.cache_reset_calls = 0

    def reset_cache():
        dlg.cache_reset_calls += 1

    assert run_full_res_commit(dlg, dlg._apply_effect, pre_apply=reset_cache) is False
    assert dlg.cache_reset_calls == 1   # ran immediately, not deferred to the worker
    _wait_for_dialog_finished(dlg)


def test_crystallize_dialog_on_large_image_does_not_block_accept(qapp, monkeypatch):
    """Direct regression test for the reported bug: Filter > Stylize >
    Crystallize on a large image, click OK — the dialog used to run
    scipy's distance_transform_edt synchronously in accept() with no
    feedback at all. Uses a real PixelateDialog/mode="crystallize"."""
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    from core.document import Document
    from ui.pixelate_dialog import PixelateDialog

    w, h = 2000, 1700
    doc = Document(w, h)
    layer = doc.layers[0]
    layer.image.fill(QColor(90, 100, 110, 255))

    dlg = PixelateDialog(layer, "crystallize", lambda: None)
    assert dlg.orig_img_full is not None  # confirms this image size actually downscales

    dlg.accept()
    assert dlg._full_res_worker is not None   # dispatched, not run inline on the GUI thread
    _wait_for_dialog_finished(dlg, timeout_ms=20000)

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert layer.image.width() == w
    assert layer.image.height() == h
