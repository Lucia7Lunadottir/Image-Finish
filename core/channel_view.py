"""One channel of the composite shown as greyscale (Channels panel: R, G,
B, the CMYK inks, or a saved alpha channel). Was inline in the canvas
paint routine."""
import numpy as np
from PyQt6.QtGui import QImage

from core.pixel_buffer import path_mask, qimage_argb_view


def channel_view(composite: QImage, channel: str, alpha_channels=()) -> QImage:
    """`channel`: "R" "G" "B", "C" "M" "Y" "K", or "alpha_<index>" into
    `alpha_channels` (dicts with a "path"). A colour channel keeps the
    composite's transparency; an alpha channel is shown opaque."""
    w, h = composite.width(), composite.height()
    arr = qimage_argb_view(composite, writable=False)[:, :w]
    if channel.startswith("alpha_"):
        idx = int(channel.split("_")[1])
        if 0 <= idx < len(alpha_channels):
            gray = path_mask(alpha_channels[idx]["path"], w, h)
        else:
            gray = np.zeros((h, w), dtype=np.uint8)
    else:
        gray = np.clip(_channel_values(arr, channel), 0, 255).astype(np.uint8)

    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = gray
    out[..., 1] = gray
    out[..., 2] = gray
    out[..., 3] = 255 if channel.startswith("alpha_") else arr[..., 3]
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    qimage_argb_view(img, writable=True)[:, :w, :] = out
    return img


def _channel_values(arr: np.ndarray, channel: str) -> np.ndarray:
    B = arr[..., 0].astype(np.float32)
    G = arr[..., 1].astype(np.float32)
    R = arr[..., 2].astype(np.float32)
    if channel == "R":
        return R
    if channel == "G":
        return G
    if channel == "B":
        return B
    C, M, Y = 1.0 - R / 255.0, 1.0 - G / 255.0, 1.0 - B / 255.0
    K = np.minimum(C, np.minimum(M, Y))
    if channel == "K":
        return K * 255.0
    ink = {"C": C, "M": M, "Y": Y}[channel]
    safe_K = np.where(K >= 0.999, 1.0, 1.0 - K)
    return np.where(K >= 0.999, 0.0, (ink - K) / safe_K) * 255.0
