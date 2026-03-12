"""Non-destructive pixel adjustment dialogs: Brightness/Contrast, Hue/Saturation."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QDialogButtonBox, QStyle,
    QPushButton,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QMouseEvent


# ── low-level pixel ops ──────────────────────────────────────────────────────

def _to_argb32(img: QImage) -> QImage:
    if img.format() == QImage.Format.Format_ARGB32:
        return img                          # no-op: skip allocation + copy
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def _bits_ba(img: QImage):
    """Return (bytearray, numpy_array_HW4) sharing the same memory."""
    import numpy as np
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    ba  = bytearray(ptr)                    # one writable copy of pixel data
    arr = np.frombuffer(ba, dtype=np.uint8).reshape(
        (img.height(), img.width(), 4))
    return ba, arr


def _from_ba(ba: bytearray, ref: QImage) -> QImage:
    """Wrap a modified bytearray as a premultiplied QImage.
    convertToFormat() always allocates a new buffer, so ba can be freed after."""
    tmp = QImage(ba, ref.width(), ref.height(),
                 ref.bytesPerLine(), QImage.Format.Format_ARGB32)
    return tmp.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


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
        ba, arr = _bits_ba(img)
        rgb = arr[:, :, :3].astype(np.float32)
        rgb = np.clip((rgb - 128.0) * cf + 128.0 + bo, 0, 255).astype(np.uint8)
        arr[:, :, :3] = rgb
        return _from_ba(ba, img)
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
        ba, arr = _bits_ba(img)

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
        return _from_ba(ba, img)

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
        ba, arr = _bits_ba(img)
        arr[:, :, :3] = 255 - arr[:, :, :3]
        return _from_ba(ba, img)
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

class _AdjustDialog(QDialog):
    """Modal dialog with real-time preview on the active layer.

    Optimisations:
    - _orig_argb32 is pre-converted once; apply_* functions skip the
      format-conversion step on every slider change.
    - A 40 ms debounce timer prevents pixel computation on every single
      valueChanged event while the user is dragging fast.
    """

    _DEBOUNCE_MS = 40

    def __init__(self, title: str, layer, canvas_refresh, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)

        self._layer          = layer
        self._original       = layer.image.copy()           # premul, for restore
        self._orig_argb32    = _to_argb32(self._original)  # ARGB32, for fast apply
        self._canvas_refresh = canvas_refresh

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

    def _add_row(self, row: _SliderRow):
        self._vbox.addLayout(row)
        row.valueChanged.connect(self._on_change)

    def _seal(self, reset_fn=None):
        self._vbox.addSpacing(4)
        if reset_fn is not None:
            reset_btn = QPushButton("Reset")
            reset_btn.clicked.connect(reset_fn)
            self._btns.addButton(reset_btn, QDialogButtonBox.ButtonRole.ResetRole)
        self._vbox.addWidget(self._btns)

    def _on_change(self):
        """Slider moved — (re)start debounce timer."""
        self._timer.start()

    def _apply_preview(self):
        raise NotImplementedError

    def reject(self):
        self._timer.stop()
        self._layer.image = self._original.copy()
        self._canvas_refresh()
        super().reject()


# ── concrete dialogs ──────────────────────────────────────────────────────────

class BrightnessContrastDialog(_AdjustDialog):
    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__("Brightness / Contrast", layer, canvas_refresh, parent)
        self._bright = _SliderRow("Brightness:", -100, 100)
        self._contr  = _SliderRow("Contrast:",   -100, 100)
        self._add_row(self._bright)
        self._add_row(self._contr)
        self._seal()

    def _apply_preview(self):
        self._layer.image = apply_brightness_contrast(
            self._orig_argb32, self._bright.value(), self._contr.value())
        self._canvas_refresh()


class HueSaturationDialog(_AdjustDialog):
    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__("Hue / Saturation", layer, canvas_refresh, parent)
        self._hue  = _SliderRow("Hue:",        -180, 180)
        self._sat  = _SliderRow("Saturation:", -100, 100)
        self._lght = _SliderRow("Lightness:",  -100, 100)
        for row in (self._hue, self._sat, self._lght):
            self._add_row(row)
        self._seal()

    def _apply_preview(self):
        self._layer.image = apply_hue_saturation(
            self._orig_argb32,
            self._hue.value(), self._sat.value(), self._lght.value())
        self._canvas_refresh()
