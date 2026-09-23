"""Zero-copy QImage <-> numpy bridging, shared by core/ (composite render)
and tools/ (pixel-level editing).

Operates on whatever ARGB32(-Premultiplied) format the QImage is already
in — no forced conversion, no copy. This is deliberately not the same as
tools/tool_utils.py's older `_qimage_to_np`/`_np_to_qimage`, which force
`convertToFormat(Format_ARGB32)` (non-premultiplied) and always copy: most
layer images in this app are `Format_ARGB32_Premultiplied`, and silently
round-tripping through straight alpha loses precision at anti-aliased
edges. Use this module whenever the QImage in hand is already premultiplied
ARGB32 and you just need numpy access to its existing bytes; keep using
`tool_utils`'s copy-based helpers only where a genuine format conversion
(to non-premultiplied) or an isolated scratch copy is actually wanted.
"""
import ctypes
import numpy as np
from PyQt6.QtGui import QImage


def qimage_argb_view(img: QImage, writable: bool = False) -> np.ndarray:
    """`(height, bytesPerLine()//4, 4)` uint8 view onto `img`'s own pixel
    buffer — no copy, no format conversion. `writable=True` uses `bits()`
    (detaches the QImage so mutations through the array are safe);
    `writable=False` uses `constBits()` (read-only, no detach)."""
    ptr = img.bits() if writable else img.constBits()
    buf = (ctypes.c_uint8 * img.sizeInBytes()).from_address(int(ptr))
    return np.ndarray((img.height(), img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=buf)


def ensure_owned_copy(img: QImage) -> QImage:
    """Copy `img` once and tag it `is_copy`, so later code in the same
    pass can mutate it in place without re-copying an image that's already
    a private scratch buffer."""
    if getattr(img, "is_copy", False):
        return img
    img = img.copy()
    img.is_copy = True
    return img


def shift_pixels_edge(arr: np.ndarray, w: int, h: int, dx: int, dy: int, edge_mode: str) -> np.ndarray:
    """Shift a pixel array by `(dx, dy)`, matching the layer-style Offset
    effect's three edge behaviors (`wrap`/`repeat`/`transparent`). `w`/`h`
    are the *logical* image dimensions (may be smaller than `arr`'s column
    count if the QImage row stride pads beyond `width()`) — shared by the
    layer-style Offset effect and the same shift applied to an in-progress
    brush stroke preview, so the two stay pixel-identical."""
    if edge_mode == "wrap":
        return np.roll(np.roll(arr, dy, axis=0), dx, axis=1)
    if edge_mode == "repeat":
        Y, X = np.ogrid[:h, :w]
        Y = np.clip(Y - dy, 0, h - 1)
        X = np.clip(X - dx, 0, w - 1)
        return arr[Y, X]
    # transparent
    res = np.zeros_like(arr)
    y1_src, y2_src = max(0, -dy), min(h, h - dy)
    x1_src, x2_src = max(0, -dx), min(w, w - dx)
    y1_dst, y2_dst = max(0, dy), min(h, h + dy)
    x1_dst, x2_dst = max(0, dx), min(w, w + dx)
    if y1_src < y2_src and x1_src < x2_src:
        res[y1_dst:y2_dst, x1_dst:x2_dst] = arr[y1_src:y2_src, x1_src:x2_src]
    return res
