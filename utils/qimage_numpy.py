"""Lifetime-safe numpy views over QImage pixel data.

The historical pattern `(ctypes.c_uint8 * n).from_address(int(ptr))` gives
numpy a raw address with no ownership: if the QImage is garbage-collected
or detaches while the array is alive, access is undefined behavior.
These helpers pin the QImage to the returned array instead.
"""

import numpy as np
from PyQt6.QtGui import QImage


class _QImageArray(np.ndarray):
    """ndarray subclass that keeps its source QImage alive."""
    _qimage = None

    def __array_finalize__(self, obj):
        if obj is not None:
            self._qimage = getattr(obj, "_qimage", None)


def view_argb(img: QImage, writable: bool = True) -> np.ndarray:
    """View a 32-bit QImage as (height, stride/4, 4) uint8 BGRA.

    Slice to `[:, :img.width()]` when the image has row padding.
    `writable=True` uses bits(), which detaches shared pixel data first —
    required before in-place edits so copy-on-write snapshots stay intact.
    The QImage is kept alive for the lifetime of the returned array.
    """
    ptr = img.bits() if writable else img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    if not writable:
        arr = arr.copy()  # const view escaping scope must not dangle
        return arr
    out = arr.view(_QImageArray)
    out._qimage = img
    return out


def copy_argb(img: QImage) -> np.ndarray:
    """Independent (height, width, 4) uint8 copy of a 32-bit QImage."""
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    return arr[:, :img.width()].copy()
