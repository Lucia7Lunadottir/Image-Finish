"""Non-destructive pixel adjustment dialogs: Brightness/Contrast, Hue/Saturation."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QDialogButtonBox, QStyle,
    QPushButton,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QMouseEvent

from core.app_logging import get_logger
from core.locale import tr
from ui.base_dialog import BaseDialog
from ui.preview_canvas_base import downscale_for_live_preview, start_full_res_worker

logger = get_logger("ui.adjustments_dialog")


# ── low-level pixel ops ──────────────────────────────────────────────────────

def _to_argb32(img: QImage) -> QImage:
    if img.format() == QImage.Format.Format_ARGB32:
        # Copy-on-write instance: as cheap as returning img itself, but the
        # in-place writes the apply_* functions do (via bits()) detach first.
        # Returning img directly let previews corrupt the caller's stored
        # original — e.g. Gaussian Blur could never *reduce* its radius.
        return QImage(img)
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def _in_place_arr(img: QImage):
    """Returns a writable numpy array mapped to the QImage's memory safely."""
    from core.pixel_buffer import qimage_argb_view
    return qimage_argb_view(img, writable=True)

def _const_arr(img: QImage):
    """Returns a read-only numpy array mapped to the QImage's memory safely."""
    from core.pixel_buffer import qimage_argb_view
    return qimage_argb_view(img, writable=False)


def _bits_ba(img: QImage):
    """Returns (buffer, array) for in-place pixel modification of QImage.
    Keep the returned buffer alive until _from_ba is called."""
    arr = _in_place_arr(img)
    return arr.base, arr[:, :img.width(), :]


def _from_ba(ba, img: QImage) -> QImage:
    """Finalize in-place edit and return premultiplied ARGB32 QImage.
    ba must be passed to prevent GC of the ctypes buffer before conversion."""
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

# Memory layout of Format_ARGB32 on little-endian x86:
#   4-channel axis indices:  0=B  1=G  2=R  3=A


def apply_brightness_contrast(src: QImage, brightness: int, contrast: int) -> QImage:
    """brightness / contrast each in [-100, 100].
    src may be ARGB32 or premultiplied — ARGB32 is handled without extra copy."""
    img = _to_argb32(src)
    cf  = (100.0 + contrast) / 100.0       # contrast factor
    bo  = brightness * 2.55                # [-100,100] → [-255,255]

    try:
        import numpy as np
        img = img.copy() # force detach
        arr = _in_place_arr(img)
        rgb = arr[:, :, :3].astype(np.float32)
        rgb = np.clip((rgb - 128.0) * cf + 128.0 + bo, 0, 255).astype(np.uint8)
        arr[:, :, :3] = rgb
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    except ImportError:
        for y in range(img.height()):
            for x in range(img.width()):
                px = img.pixel(x, y)
                a  = (px >> 24) & 0xFF
                r  = int(max(0, min(255, ((px >> 16 & 0xFF) - 128) * cf + 128 + bo)))
                g  = int(max(0, min(255, ((px >>  8 & 0xFF) - 128) * cf + 128 + bo)))
                b  = int(max(0, min(255, ((px & 0xFF)       - 128) * cf + 128 + bo)))
                img.setPixel(x, y, (a << 24) | (r << 16) | (g << 8) | b)
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def apply_hue_saturation(src: QImage, hue: int, saturation: int, lightness: int) -> QImage:
    """hue in [-180, 180], saturation / lightness in [-100, 100]."""
    img = _to_argb32(src)

    try:
        import numpy as np
        img = img.copy()
        arr = _in_place_arr(img)

        # BGRA layout: R=2, G=1, B=0
        B0 = arr[:, :, 0].astype(np.float32) / 255.0
        G0 = arr[:, :, 1].astype(np.float32) / 255.0
        R0 = arr[:, :, 2].astype(np.float32) / 255.0

        Cmax  = np.maximum(R0, np.maximum(G0, B0))
        Cmin  = np.minimum(R0, np.minimum(G0, B0))
        delta = Cmax - Cmin

        L     = (Cmax + Cmin) * 0.5
        denom = np.where(np.abs(2.0 * L - 1.0) < 0.9999,
                         1.0 - np.abs(2.0 * L - 1.0), 1e-9)
        S     = np.where(delta < 1e-9, 0.0, np.clip(delta / denom, 0.0, 1.0))

        H    = np.zeros_like(R0)
        mask = delta > 1e-9
        d    = delta[mask]
        Hm   = np.where(
            Cmax[mask] == R0[mask], ((G0[mask] - B0[mask]) / d) % 6.0,
            np.where(Cmax[mask] == G0[mask],
                     (B0[mask] - R0[mask]) / d + 2.0,
                     (R0[mask] - G0[mask]) / d + 4.0))
        H[mask] = Hm / 6.0

        H = (H + hue / 360.0) % 1.0
        S = np.clip(S + saturation / 100.0, 0.0, 1.0)
        L = np.clip(L + lightness  / 100.0, 0.0, 1.0)

        C  = (1.0 - np.abs(2.0 * L - 1.0)) * S
        H6 = H * 6.0
        X  = C * (1.0 - np.abs(H6 % 2.0 - 1.0))
        mv = L - C * 0.5
        Z  = np.zeros_like(H)

        R2 = np.zeros_like(H);  G2 = np.zeros_like(H);  B2 = np.zeros_like(H)
        for i, (rv, gv, bv) in enumerate(
                [(C, X, Z), (X, C, Z), (Z, C, X),
                 (Z, X, C), (X, Z, C), (C, Z, X)]):
            mi = (H6 >= i) & (H6 < i + 1)
            R2[mi] = rv[mi];  G2[mi] = gv[mi];  B2[mi] = bv[mi]

        arr[:, :, 2] = np.clip((R2 + mv) * 255, 0, 255).astype(np.uint8)
        arr[:, :, 1] = np.clip((G2 + mv) * 255, 0, 255).astype(np.uint8)
        arr[:, :, 0] = np.clip((B2 + mv) * 255, 0, 255).astype(np.uint8)
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    except ImportError:
        import colorsys
        for y in range(img.height()):
            for x in range(img.width()):
                px = img.pixel(x, y)
                a  = (px >> 24) & 0xFF
                r, g, b = (px >> 16 & 0xFF), (px >> 8 & 0xFF), (px & 0xFF)
                hv, lv, sv = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                hv = (hv + hue / 360.0) % 1.0
                sv = max(0.0, min(1.0, sv + saturation / 100.0))
                lv = max(0.0, min(1.0, lv + lightness  / 100.0))
                r2, g2, b2 = colorsys.hls_to_rgb(hv, lv, sv)
                img.setPixel(x, y, (a << 24) | (int(r2 * 255) << 16) |
                             (int(g2 * 255) << 8) | int(b2 * 255))
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def apply_invert(src: QImage) -> QImage:
    """Invert RGB channels; alpha is preserved."""
    img = _to_argb32(src)
    try:
        import numpy as np
        img = img.copy()
        arr = _in_place_arr(img)
        arr[:, :, :3] = 255 - arr[:, :, :3]
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    except ImportError:
        for y in range(img.height()):
            for x in range(img.width()):
                px = img.pixel(x, y)
                a  = (px >> 24) & 0xFF
                img.setPixel(x, y,
                    (a << 24) |
                    ((255 - (px >> 16 & 0xFF)) << 16) |
                    ((255 - (px >>  8 & 0xFF)) <<  8) |
                    (255 - (px & 0xFF)))
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


# ── slider that jumps to click position ──────────────────────────────────────

class _JumpSlider(QSlider):
    """Standard QSlider, but a click anywhere on the track moves the handle
    directly to that position instead of doing a page-step."""

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), self.width())
            self.setValue(val)
        super().mousePressEvent(event)


# ── reusable slider row ───────────────────────────────────────────────────────

class _SliderRow(QHBoxLayout):
    """Label + jump-slider + numeric value in one horizontal row."""

    def __init__(self, label: str, lo: int, hi: int, default: int = 0):
        super().__init__()
        self._default = default
        lbl = QLabel(label)
        lbl.setFixedWidth(90)

        self._slider = _JumpSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(lo, hi)
        self._slider.setValue(default)

        self._val_lbl = QLabel(str(default))
        self._val_lbl.setFixedWidth(40)
        self._val_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._slider.valueChanged.connect(lambda v: self._val_lbl.setText(str(v)))

        self.addWidget(lbl)
        self.addWidget(self._slider)
        self.addWidget(self._val_lbl)

    def value(self) -> int:
        return self._slider.value()

    def set_value(self, v: int):
        """Set value programmatically without triggering valueChanged."""
        self._slider.blockSignals(True)
        self._slider.setValue(v)
        self._slider.blockSignals(False)
        self._val_lbl.setText(str(v))

    def reset(self):
        self.set_value(self._default)

    @property
    def valueChanged(self):
        return self._slider.valueChanged


# ── base adjustment dialog ────────────────────────────────────────────────────

class _AdjustDialog(BaseDialog):
    """Modal dialog with real-time preview on the active layer.

    Optimisations:
    - _orig_argb32 is pre-converted once; apply_* functions skip the
      format-conversion step on every slider change.
    - A 40 ms debounce timer prevents pixel computation on every single
      valueChanged event while the user is dragging fast.
    - On images above the live-preview cap, _orig_argb32 is a downscaled
      proxy while the dialog is open (see ui.preview_canvas_base — same
      mechanism as the filter-preview dialogs); the true full-resolution
      source is restored and re-applied once in accept(). Subclasses that
      derive their own numpy state from _orig_argb32 in __init__ (rather
      than reading it fresh inside _apply_preview(), like HDRToningDialog
      does) must override _on_full_res_restored() to refresh that state —
      otherwise the final accept() pass silently reuses stale,
      wrong-resolution arrays.
    - Unlike the PreviewCanvasBase dialog family, this class paints
      directly onto the *document* layer (self._layer.image) and refreshes
      the *main* canvas — there is no isolated preview widget to quietly
      show a smaller proxy in. So every subclass's _apply_preview() write
      of a downscaled-proxy-sized image is caught and upscaled back to the
      full document size in _on_refresh_requested() (the method actually
      stored in self._canvas_refresh — see below) before the caller's
      real canvas_refresh runs. Without this, the layer would visibly
      shrink/pixelate on the real canvas while a slider is being dragged,
      not just show a lower-detail preview like the isolated dialogs do.
    """

    _DEBOUNCE_MS = 40

    def __init__(self, title: str, layer, canvas_refresh, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)

        self._layer               = layer
        self._canvas_refresh_real = canvas_refresh
        # Subclasses always call self._canvas_refresh() as the last step of
        # _apply_preview()/_reset()/_do_reset() — intercepting it here (not
        # just the debounce-timer path) catches every entry point, direct
        # or timer-driven, without editing a single subclass.
        self._canvas_refresh      = self._on_refresh_requested
        # True only while the final full-res _apply_preview() runs on a
        # background thread (see _run_final_apply_with_progress) — the
        # worker thread must not reach into the real, OpenGL-backed main
        # canvas, so the refresh is skipped there and done once, on the GUI
        # thread, when the worker signals completion.
        self._defer_gui_refresh   = False
        self._full_res_worker     = None
        self._full_res_progress   = None
        image                = layer.image
        self._original       = image.copy()
        full_argb32          = _to_argb32(self._original)
        self._orig_argb32_full = None
        downscaled = downscale_for_live_preview(full_argb32)
        if downscaled is not None:
            self._orig_argb32_full = full_argb32
            self._orig_argb32      = downscaled
        else:
            self._orig_argb32      = full_argb32

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._apply_preview)

        self._vbox = QVBoxLayout(self)
        self._btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        self._btns.accepted.connect(self.accept)
        self._btns.rejected.connect(self.reject)

    def _on_refresh_requested(self):
        """Stored as self._canvas_refresh — every subclass calls this
        expecting layer.image to already be at full document resolution.
        While _orig_argb32 is a downscaled live-preview proxy,
        _apply_preview() writes a proxy-sized image instead; upscale it
        back to the real layer size here, then run the real refresh."""
        if self._orig_argb32_full is not None:
            full_w, full_h = self._orig_argb32_full.width(), self._orig_argb32_full.height()
            img = self._layer.image
            if not img.isNull() and (img.width(), img.height()) != (full_w, full_h):
                self._layer.image = img.scaled(
                    full_w, full_h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
        if self._defer_gui_refresh:
            return
        self._canvas_refresh_real()

    def _add_row(self, row: _SliderRow):
        self._vbox.addLayout(row)
        row.valueChanged.connect(self._on_change)

    def _seal(self, reset_fn=None):
        self._vbox.addSpacing(4)
        if reset_fn is not None:
            reset_btn = QPushButton(tr("adj.reset"))
            reset_btn.clicked.connect(reset_fn)
            self._btns.addButton(reset_btn, QDialogButtonBox.ButtonRole.ResetRole)
        self._vbox.addWidget(self._btns)

    def _get_auto_data(self):
        # A dialog that knows its own data (adjustment_data()) is the
        # source of truth; scraping widget attributes by name is the legacy
        # fallback (it silently stored wrong keys for Gradient Map).
        if hasattr(self, "adjustment_data"):
            return self.adjustment_data()
        d = {}
        for k, v in self.__dict__.items():
            if k == "_lut": d["lut"] = v
            elif k == "_color": d["color"] = v
            elif k == "_shadows": d["shadows"] = v
            elif k == "_highlights": d["highlights"] = v
            elif hasattr(v, "value") and callable(v.value):
                try: d[k.lstrip('_')] = v.value()
                except TypeError: pass
            elif hasattr(v, "color") and callable(v.color):
                try: d[k.lstrip('_')] = v.color()
                except TypeError: pass
            elif hasattr(v, "isChecked") and callable(v.isChecked):
                try: d[k.lstrip('_')] = v.isChecked()
                except TypeError: pass
        
        d["type"] = getattr(self, "_adj_type", "unknown")
        if d["type"] in ("", "unknown"):
            n = self.__class__.__name__.lower()
            if "level" in n: d["type"] = "levels"
            elif "exposure" in n: d["type"] = "exposure"
            elif "vibrance" in n: d["type"] = "vibrance"
            elif "black" in n: d["type"] = "black_white"
            elif "poster" in n: d["type"] = "posterize"
            elif "thresh" in n: d["type"] = "threshold"
            elif "photo" in n: d["type"] = "photo_filter"
            elif "grad" in n: d["type"] = "gradient_map"
            elif "lookup" in n: d["type"] = "color_lookup"
            elif "hdr" in n: d["type"] = "hdr_toning"
            elif "brightness" in n: d["type"] = "brightness_contrast"
            elif "hue" in n: d["type"] = "hue_saturation"
        return d

    def _on_change(self):
        """Slider moved — (re)start debounce timer."""
        if getattr(self, "_is_adj_layer", False):
            self._layer.adjustment_data = self._get_auto_data()
        self._timer.start()

    def _apply_preview(self):
        raise NotImplementedError

    def _on_full_res_restored(self):
        """Hook for subclasses that cache numpy arrays derived from
        _orig_argb32 in __init__ instead of re-reading it inside
        _apply_preview(). Called once, right after _orig_argb32 is swapped
        back to full resolution, immediately before the final
        _apply_preview() — both run inside the background worker started
        by _run_final_apply_with_progress(), not directly in accept(), so
        this must stay GUI-free (numpy/QImage only, no widgets). No-op by
        default — only needed by dialogs like HDRToningDialog with a
        per-init derived-array cache."""
        pass

    def accept(self):
        self._timer.stop()
        if getattr(self, "_is_adj_layer", False):
            self._layer.adjustment_data = self._get_auto_data()
        if self._orig_argb32_full is not None:
            self._orig_argb32      = self._orig_argb32_full
            self._orig_argb32_full = None
            # Runs the real algorithm at full resolution — exactly what was
            # too slow to run on every slider tick in the first place — off
            # the GUI thread with a busy indicator, so the dialog stays
            # visibly alive instead of looking frozen; it closes itself
            # once the worker reports back (see the finished/error handlers
            # below), so we return here without calling super().accept()
            # yet. _on_full_res_restored() runs inside the worker too, not
            # here — for HDRToningDialog specifically it re-extracts numpy
            # arrays from the full 8K+ image, which alone can take seconds;
            # running it before the progress dialog is even shown would
            # reintroduce exactly the freeze this whole mechanism exists to
            # avoid.
            self._run_final_apply_with_progress()
            return
        super().accept()

    def _run_final_apply_with_progress(self):
        self._defer_gui_refresh = True

        def work():
            self._on_full_res_restored()
            self._apply_preview()

        def on_finished():
            self._defer_gui_refresh = False
            self._canvas_refresh_real()
            QDialog.accept(self)

        def on_error(trace: str):
            logger.error("Full-resolution adjustment commit failed:\n%s", trace)
            self._defer_gui_refresh = False
            # self.reject() (not QDialog.reject) so the normal is_adj_layer
            # vs. destructive-filter restoration below runs exactly as it
            # would for a manual Cancel click.
            self.reject()

        start_full_res_worker(self, work, on_finished, on_error)

    def reject(self):
        self._timer.stop()
        if getattr(self, "_is_adj_layer", False):
            self._layer.adjustment_data = self._orig_adj_data
        else:
            self._layer.image = self._original.copy()
        self._canvas_refresh()
        super().reject()


# ── concrete dialogs ──────────────────────────────────────────────────────────

class BrightnessContrastDialog(_AdjustDialog):
    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__(tr("adj.bc.title"), layer, canvas_refresh, parent)
        self._bright = _SliderRow(tr("adj.bc.brightness"), -100, 100)
        self._contr  = _SliderRow(tr("adj.bc.contrast"),   -100, 100)
        self._add_row(self._bright)
        self._add_row(self._contr)
        self._seal()

    def _apply_preview(self):
        self._layer.image = apply_brightness_contrast(
            self._orig_argb32, self._bright.value(), self._contr.value())
        self._canvas_refresh()


class HueSaturationDialog(_AdjustDialog):
    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__(tr("adj.hs.title"), layer, canvas_refresh, parent)
        self._hue  = _SliderRow(tr("adj.hs.hue"),        -180, 180)
        self._sat  = _SliderRow(tr("adj.hs.saturation"), -100, 100)
        self._lght = _SliderRow(tr("adj.hs.lightness"),  -100, 100)
        for row in (self._hue, self._sat, self._lght):
            self._add_row(row)
        self._seal()

    def _apply_preview(self):
        self._layer.image = apply_hue_saturation(
            self._orig_argb32,
            self._hue.value(), self._sat.value(), self._lght.value())
        self._canvas_refresh()
