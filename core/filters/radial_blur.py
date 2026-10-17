"""core/filters/radial_blur.py — Radial Blur filter + dialog (Spin / Zoom)."""

import math

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QComboBox
from PyQt6.QtGui import QImage

from core.locale import tr
from ui.adjustments_dialog import _AdjustDialog, _SliderRow, _to_argb32, _from_ba, _bits_ba


# ── bilinear sampler ──────────────────────────────────────────────────────────

def _bilinear_sample_all(all_chs, rows, cols, h, w):
    """Bilinear interpolation for all channels at once.
    all_chs: (C, H, W) float32  →  returns (H, W, C) float32."""
    import numpy as np
    r0 = np.clip(np.floor(rows).astype(np.int32), 0, h - 1)
    c0 = np.clip(np.floor(cols).astype(np.int32), 0, w - 1)
    r1 = np.clip(r0 + 1, 0, h - 1)
    c1 = np.clip(c0 + 1, 0, w - 1)
    dr = (rows - np.floor(rows))[np.newaxis, :, :]   # (1, H, W)
    dc = (cols - np.floor(cols))[np.newaxis, :, :]   # (1, H, W)
    # all_chs[:, r0, c0] → (C, H, W) via advanced indexing
    top    = all_chs[:, r0, c0] * (1 - dc) + all_chs[:, r0, c1] * dc
    bottom = all_chs[:, r1, c0] * (1 - dc) + all_chs[:, r1, c1] * dc
    return (top * (1 - dr) + bottom * dr).transpose(1, 2, 0)  # (H, W, C)


# ── core algorithms ───────────────────────────────────────────────────────────

def _apply_spin_np(arr, amount: int):
    """Rotational blur around image center. amount 1–100 → 0.4°–40° arc."""
    import numpy as np
    h, w = arr.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    n   = max(4, amount // 8 + 4)                       # 4..16 samples
    max_rad = amount * 0.4 * (math.pi / 180.0)          # degrees → radians
    thetas  = np.linspace(-max_rad, max_rad, n)

    y_g, x_g = np.mgrid[0:h, 0:w]
    rx = x_g.astype(np.float32) - cx
    ry = y_g.astype(np.float32) - cy
    all_chs = np.stack([arr[:, :, c].astype(np.float32) for c in range(4)])  # (4,H,W) once

    acc = np.zeros((h, w, 4), dtype=np.float32)
    for theta in thetas:
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        sx = np.clip(cos_t * rx - sin_t * ry + cx, 0, w - 1)
        sy = np.clip(sin_t * rx + cos_t * ry + cy, 0, h - 1)
        acc += _bilinear_sample_all(all_chs, sy, sx, h, w)

    return np.clip(acc / n, 0, 255).astype(np.uint8)


def _apply_zoom_np(arr, amount: int):
    """Zoom (radial) blur from center outward. amount 1–100 → 0.5%–50% scale."""
    import numpy as np
    h, w = arr.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    n         = max(4, amount // 8 + 4)
    max_scale = amount / 100.0 * 0.5                    # 0–50 % pull toward center

    y_g, x_g = np.mgrid[0:h, 0:w]
    rx = x_g.astype(np.float32) - cx
    ry = y_g.astype(np.float32) - cy
    # All four channels, like Spin: the caller writes back a (H, W, 4) array
    # (with 3 here, every Zoom blur raised a broadcast ValueError).
    all_chs = np.stack([arr[:, :, c].astype(np.float32) for c in range(4)])  # (4,H,W) once

    t_vals = np.linspace(1.0 - max_scale, 1.0, n)

    acc = np.zeros((h, w, 4), dtype=np.float32)
    for t in t_vals:
        sx = np.clip(t * rx + cx, 0, w - 1)
        sy = np.clip(t * ry + cy, 0, h - 1)
        acc += _bilinear_sample_all(all_chs, sy, sx, h, w)

    return np.clip(acc / n, 0, 255).astype(np.uint8)


# ── public apply function ─────────────────────────────────────────────────────

def apply_radial_blur(src: QImage, mode: str, amount: int) -> QImage:
    """Radial blur. mode: 'Spin' | 'Zoom', amount: 1–100. Alpha preserved."""
    if amount < 1:
        return src.copy()
    img = _to_argb32(src)

    try:
        import numpy as np
        ba, arr = _bits_ba(img)

        blurred = _apply_spin_np(arr, amount) if mode == "Spin" else _apply_zoom_np(arr, amount)
        arr[:, :, :4] = blurred
        return _from_ba(ba, img)

    except ImportError:
        # No numpy — return unchanged (motion too slow for realtime fallback)
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


_RADIAL_MODES = ("Spin", "Zoom")
_RADIAL_MODE_KEYS = ("flt.radial.spin", "flt.radial.zoom")


# ── dialog ────────────────────────────────────────────────────────────────────

class RadialBlurDialog(_AdjustDialog):
    """Radial Blur dialog: Type (Spin/Zoom) + Amount 1–100, live preview."""

    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__(tr("flt.radial.title"), layer, canvas_refresh, parent)

        # Type row (ComboBox, not a slider)
        type_row = QHBoxLayout()
        lbl = QLabel(tr("flt.radial.type"))
        lbl.setFixedWidth(90)
        self._type_combo = self._bind("mode", QComboBox())
        for mode, key in zip(_RADIAL_MODES, _RADIAL_MODE_KEYS):
            self._type_combo.addItem(tr(key), mode)
        self._type_combo.currentIndexChanged.connect(self._on_change)
        type_row.addWidget(lbl)
        type_row.addWidget(self._type_combo, 1)
        self._vbox.addLayout(type_row)

        self._amount = self._bind("amount", _SliderRow(tr("flt.amount"), 1, 100, 10))
        self._add_row(self._amount)
        self._seal(reset_fn=self._reset_to_defaults)

    def _render(self, src, p):
        return apply_radial_blur(src, p["mode"] or _RADIAL_MODES[0], p["amount"])
