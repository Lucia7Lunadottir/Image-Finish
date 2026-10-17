"""Shared pan/zoom/checkerboard preview widget for filter & adjustment
dialogs (Noise, Stylize, Sharpen, Pixelate, Other Filters, Specific
Filters/Liquify, Blur Gallery, Distort, Render, Select and Mask).

These dialogs all show ``dialog.preview_img`` inside a zoomable/pannable
checkerboard canvas; they used to each carry their own copy of this
~50-line QWidget. PreviewCanvasBase is the single implementation;
subclasses only add whatever mode-specific interaction they need via the
hooks below.
"""
import math
import traceback

from PyQt6.QtWidgets import QWidget, QDialog, QProgressDialog
from PyQt6.QtCore import Qt, QPointF, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QColor, QPixmap, QBrush

from core.app_logging import get_logger
from core.locale import tr
from ui import theme

logger = get_logger("ui.preview_canvas_base")


# --- live-preview downscaling ---------------------------------------------
#
# Every dialog in this family re-runs its full _apply_effect() on the whole
# image on every debounced slider tick (~60ms after the user stops moving
# it). At full resolution that's fine up to a few megapixels, but on an 8K-
# 16K photo it makes every single filter feel like it's hanging while
# dragging a slider — the algorithm itself may be fast, but "fast" times a
# few hundred megapixels, on every tick, on a laptop CPU, isn't. The fix
# isn't per-algorithm: run _apply_effect() against a capped-resolution proxy
# while the user is interacting, and pay for one full-resolution pass only
# once, when the dialog is actually accepted.

_MAX_LIVE_PREVIEW_DIM = 1600


def downscale_for_live_preview(img: QImage, max_dim: int = _MAX_LIVE_PREVIEW_DIM):
    """Returns a smaller QImage for interactive preview, or None if img is
    already within max_dim on its long edge (nothing to do)."""
    if max(img.width(), img.height()) <= max_dim:
        return None
    scale = max_dim / max(img.width(), img.height())
    new_w = max(1, round(img.width() * scale))
    new_h = max(1, round(img.height() * scale))
    return img.scaled(new_w, new_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)


def init_live_preview_arrays(dialog, layer, max_dim: int = _MAX_LIVE_PREVIEW_DIM):
    """Sets dialog.orig_img/.preview_img/.orig_arr, downscaled for
    interactive editing when the source exceeds max_dim. dialog.orig_arr_full
    holds the true full-resolution QImage when downscaling happened (None
    otherwise) — call restore_full_res_before_accept() in accept() before
    the final _apply_effect() pass."""
    from core.pixel_buffer import qimage_argb_view
    dialog.orig_img = layer.image.copy()
    dialog.preview_img = dialog.orig_img.copy()
    dialog.orig_img_full = None
    downscaled = downscale_for_live_preview(dialog.orig_img, max_dim)
    if downscaled is not None:
        dialog.orig_img_full = dialog.orig_img
        dialog.orig_img = downscaled
        dialog.preview_img = downscaled.copy()
    dialog.orig_arr = qimage_argb_view(dialog.orig_img, writable=False)[:, :dialog.orig_img.width(), :].copy()


def restore_full_res_before_accept(dialog, scale_attrs=()) -> bool:
    """Call at the start of accept(). Returns True if a full-resolution
    re-run of _apply_effect() is now needed (i.e. the dialog had been
    running on a downscaled proxy). scale_attrs lists numeric attribute
    names (e.g. "cx", "cy") that were set/dragged in downscaled-image
    coordinates and must be rescaled to match the restored full image —
    used by dialogs with a draggable center point (Blur Gallery, Distort,
    Render)."""
    if dialog.orig_img_full is None:
        return False
    old_w = dialog.orig_img.width()
    dialog.orig_img = dialog.orig_img_full
    dialog.orig_img_full = None
    scale = dialog.orig_img.width() / old_w
    for attr in scale_attrs:
        setattr(dialog, attr, getattr(dialog, attr) * scale)
    from core.pixel_buffer import qimage_argb_view
    dialog.orig_arr = qimage_argb_view(dialog.orig_img, writable=False)[:, :dialog.orig_img.width(), :].copy()
    return True


# --- background worker for the one-shot full-resolution commit ------------
#
# restore_full_res_before_accept() above only swaps the *source* array back
# to full resolution — the caller still has to re-run its (possibly slow)
# _apply_effect()/_apply_preview() once at that resolution, synchronously,
# in accept(). On an 8K+ image that single pass is exactly the computation
# the live-preview downscale exists to avoid running on every slider tick,
# and can itself take seconds to tens of seconds — long enough for the
# window manager to flag the whole app as "not responding" with zero
# visual feedback. run_full_res_commit() below runs it off the GUI thread
# with a busy progress dialog instead. Same QRunnable+signals shape already
# used elsewhere in this codebase (ui/histogram_panel.py, ui/welcome_panel.py,
# ui/navigator_panel.py, tools/base_tool.py::GenericToolWorker) — a
# dedicated small pair here because none of those carry a payload this call
# site needs.

class _FullResApplySignals(QObject):
    finished = pyqtSignal()
    error    = pyqtSignal(str)


class _FullResApplyWorker(QRunnable):
    """Runs a given zero-arg callable off the GUI thread. The callable must
    be GUI-free — pure numpy/QImage pixel work only, no widget or OpenGL
    canvas touching (see run_full_res_commit's canvas.update() suppression
    below for how callers that can't guarantee this stay safe anyway)."""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.signals = _FullResApplySignals()

    def run(self):
        try:
            self._fn()
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        else:
            self.signals.finished.emit()


def start_full_res_worker(dialog, work_fn, on_finished, on_error):
    """Shared plumbing behind both accept()-time full-res commit paths in
    this codebase (_AdjustDialog._run_final_apply_with_progress and
    run_full_res_commit below): show a busy QProgressDialog on *dialog*,
    run work_fn() on QThreadPool, and call on_finished()/on_error(trace)
    back on the GUI thread once it reports in. dialog._full_res_worker/
    _full_res_progress are always cleaned up first, in both outcomes, so
    callers only ever need to handle their own domain-specific "what does
    success/failure mean here" logic (canvas repaint suppression,
    accept()/reject(), layer restoration, ...) — never the QProgressDialog
    or QThreadPool wiring itself, which is identical in both callers.

    Left in Qt's built-in indeterminate mode (range 0,0): tried driving it
    with a QTimer stepping setValue() 0..100..0 instead, on the theory that
    the app's global QApplication-level stylesheet (ui.theme) switches
    every widget — this one included — to Qt's CSS-based style engine,
    which doesn't animate the native busy/marquee indicator at all
    (indeterminate mode just paints one static frame under a stylesheet).
    That "fix" made things actively worse, live-tested: QProgressDialog's
    setValue() internally re-triggers its own show()/layout logic on every
    call (Qt's own _q_forceShow machinery, active because
    setMinimumDuration(0) means "always eligible to (re)show") — at a 40ms
    tick that's ~25 calls/second, and on a real window manager each one
    re-mapped/re-focused the dialog, i.e. exactly what looked like "the
    window keeps recreating itself and stealing focus". Reverted: the
    static indeterminate bar doesn't visually animate under this app's
    stylesheet, but it doesn't fight the window manager either, which
    matters more. See [[image-finish-2026-09-session]] for the full
    back-and-forth if this needs revisiting."""
    progress = QProgressDialog(tr("adj.applying_full_res"), "", 0, 0, dialog)
    progress.setWindowTitle(dialog.windowTitle())
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()
    dialog._full_res_progress = progress  # keep alive

    worker = _FullResApplyWorker(work_fn)
    dialog._full_res_worker = worker  # keep alive until it reports back

    def _cleanup():
        progress.close()
        dialog._full_res_progress = None
        dialog._full_res_worker   = None

    def _finished():
        _cleanup()
        on_finished()

    def _error(trace: str):
        _cleanup()
        on_error(trace)

    worker.signals.finished.connect(_finished)
    worker.signals.error.connect(_error)
    QThreadPool.globalInstance().start(worker)


def run_full_res_commit(dialog, apply_fn, scale_attrs=(), pre_apply=None) -> bool:
    """Shared accept()-time full-res commit for the PreviewCanvasBase filter
    dialogs (Noise, Stylize, Sharpen, Pixelate, Other Filters, Blur Gallery,
    Distort, Render, Specific Filters).

    If the dialog had never been downscaled (small source image), this is a
    no-op and returns True immediately — the caller's accept() should
    proceed synchronously exactly as before. Otherwise it restores full
    resolution, then re-runs apply_fn() (the dialog's own _apply_effect) off
    the GUI thread behind a busy QProgressDialog, and closes the dialog
    itself once done — returns False, meaning the caller must return from
    accept() without calling super().accept() (this function does that once
    the worker reports back).

    pre_apply, if given, runs synchronously on the GUI thread right after
    the resolution restore and before the threaded apply_fn() — for state
    that must be invalidated at the new resolution but is cheap enough not
    to need its own thread (e.g. blur_gallery_dialog's blurred_cache, keyed
    by radius but shaped for the downscaled proxy).

    apply_fn ends by calling dialog.canvas.update() to repaint the preview
    (true of every dialog in this family) — a real widget/paint call, not
    safe to run on a worker thread. It's suppressed for the duration here
    (the canvas doesn't need to repaint since the dialog is about to close
    either way) rather than requiring every dialog to change _apply_effect.
    """
    if not restore_full_res_before_accept(dialog, scale_attrs):
        return True
    if pre_apply is not None:
        pre_apply()

    real_update = dialog.canvas.update
    dialog.canvas.update = lambda: None

    def on_finished():
        dialog.canvas.update = real_update
        dialog.layer.image = dialog.preview_img
        QDialog.accept(dialog)

    def on_error(trace: str):
        logger.error("Full-resolution filter commit failed:\n%s", trace)
        dialog.canvas.update = real_update
        QDialog.reject(dialog)

    start_full_res_worker(dialog, apply_fn, on_finished, on_error)
    return False


class PreviewCanvasBase(QWidget):
    def __init__(self, dialog=None):
        super().__init__()
        self.dialog = dialog
        self.setMouseTracking(True)
        self.zoom = 1.0
        self._pan = QPointF(0, 0)
        self._panning = False
        self._pan_last = None
        self._space = False
        self._checker = self._build_checker()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @staticmethod
    def _build_checker(tile: int = 16) -> QPixmap:
        pix = QPixmap(tile * 2, tile * 2)
        p = QPainter(pix)
        p.fillRect(0, 0, tile, tile, QColor(180, 180, 180))
        p.fillRect(tile, 0, tile, tile, QColor(220, 220, 220))
        p.fillRect(0, tile, tile, tile, QColor(220, 220, 220))
        p.fillRect(tile, tile, tile, tile, QColor(180, 180, 180))
        p.end()
        return pix

    # --- hooks for subclasses -------------------------------------------------

    def _get_preview_image(self):
        return getattr(self.dialog, "preview_img", None)

    def _wants_checkerboard(self) -> bool:
        return True

    def _image_clip_rect(self, w, h):
        """Optional QRect (in widget space) to clip drawing to. None = no clip."""
        return None

    def _paint_overlay_in_image_space(self, painter, w, h):
        """Called after drawImage, while the pan/zoom transform is still active."""
        pass

    def _paint_overlay_in_screen_space(self, painter):
        """Called after the pan/zoom transform has been restored (widget-space)."""
        pass

    def _idle_cursor(self):
        return Qt.CursorShape.ArrowCursor

    def _is_pan_trigger(self, ev) -> bool:
        return ev.button() == Qt.MouseButton.MiddleButton or (self._space and ev.button() == Qt.MouseButton.LeftButton)

    # --- shared implementation -------------------------------------------------

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.CRUST))
        img = self._get_preview_image()
        if not img:
            p.end()
            return

        w, h = img.width(), img.height()

        p.save()
        clip = self._image_clip_rect(w, h)
        if clip is not None:
            p.setClipRect(clip)
        p.translate(self._pan)
        p.scale(self.zoom, self.zoom)

        if self._wants_checkerboard():
            p.fillRect(0, 0, w, h, QBrush(self._checker))

        p.drawImage(0, 0, img)
        self._paint_overlay_in_image_space(p, w, h)
        p.restore()

        self._paint_overlay_in_screen_space(p)
        p.end()

    def _maybe_start_pan(self, ev) -> bool:
        """Starts panning if ev triggers it. Returns True if consumed.

        NOT a Qt virtual override itself (see mousePressEvent below) —
        mousePressEvent/mouseMoveEvent are void in C++, and PyQt6 raises
        "TypeError: invalid result from X.mousePressEvent()" if a Python
        override that is the *actual* dispatch target (i.e. a subclass
        that doesn't itself override the method, like `class Y(Base):
        pass`) returns anything but None. Keeping the bool here and
        having mousePressEvent/mouseMoveEvent call it without returning
        keeps every subclass safe regardless of whether it overrides."""
        if self._is_pan_trigger(ev):
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        return False

    def _maybe_continue_pan(self, ev) -> bool:
        """Returns True if consumed as panning. See _maybe_start_pan."""
        if self._panning and self._pan_last is not None:
            self._pan += (ev.position() - self._pan_last)
            self._pan_last = ev.position()
            self.update()
            return True
        return False

    def mousePressEvent(self, ev):
        self._maybe_start_pan(ev)

    def mouseMoveEvent(self, ev):
        self._maybe_continue_pan(ev)

    def mouseReleaseEvent(self, ev):
        self._panning = False
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._space else self._idle_cursor())

    def wheelEvent(self, ev):
        factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = max(0.05, min(32.0, self.zoom * factor))
        scale = new_zoom / self.zoom
        pivot = ev.position()
        self._pan = QPointF(pivot.x() - (pivot.x() - self._pan.x()) * scale, pivot.y() - (pivot.y() - self._pan.y()) * scale)
        self.zoom = new_zoom
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self.setCursor(self._idle_cursor())


class DragCenterMixin:
    """Shared 'drag a draggable center point (dialog.cx/cy)' interaction,
    used by dialogs whose overlay includes a center marker the user can
    grab and reposition (Blur Gallery, Distort, Render)."""

    _center_hit_radius = 20  # screen px at zoom=1; override per dialog

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._dragging_center = False

    def _center_active(self) -> bool:
        """Whether dialog.mode currently allows grabbing the center handle."""
        return True

    def mousePressEvent(self, ev):
        if self._maybe_start_pan(ev):
            return
        if ev.button() == Qt.MouseButton.LeftButton and self._center_active():
            pos = ev.position()
            img_x = (pos.x() - self._pan.x()) / self.zoom
            img_y = (pos.y() - self._pan.y()) / self.zoom
            if math.hypot(img_x - self.dialog.cx, img_y - self.dialog.cy) < (self._center_hit_radius / self.zoom):
                self._dragging_center = True

    def mouseMoveEvent(self, ev):
        if self._maybe_continue_pan(ev):
            return
        if self._dragging_center:
            pos = ev.position()
            self.dialog.cx = (pos.x() - self._pan.x()) / self.zoom
            self.dialog.cy = (pos.y() - self._pan.y()) / self.zoom
            self.update()
            self.dialog._trigger_update()

    def mouseReleaseEvent(self, ev):
        self._dragging_center = False
        super().mouseReleaseEvent(ev)
