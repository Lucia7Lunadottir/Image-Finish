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


def gray8_array(img: QImage) -> np.ndarray:
    """Independent `(height, width)` uint8 copy of a Format_Grayscale8 image
    (row padding stripped)."""
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width()].copy()


def coverage_mask(width: int, height: int, paint, antialias: bool = False) -> np.ndarray:
    """`(height, width)` uint8 coverage mask: 255 where `paint(painter)`
    draws, 0 elsewhere, antialiased in between.

    The one place that turns geometry into a numpy mask. `paint` should
    use `MASK_WHITE` — careful with `QColor(255)`: that's the *RGB integer*
    0x0000FF (blue), which lands on a grayscale image as 39, not 255. Five
    separate copies of this helper had exactly that bug (Modify > Smooth
    selected nothing, Select and Mask started at 15%, Patch blended at 15%)."""
    from PyQt6.QtGui import QPainter
    img = QImage(max(1, width), max(1, height), QImage.Format.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, antialias)
    paint(p)
    p.end()
    return gray8_array(img)


def path_mask(path, width: int, height: int, offset=None, antialias: bool = False) -> np.ndarray:
    """Coverage mask of a filled QPainterPath; `offset` (QPoint/QPointF) is
    subtracted, i.e. it's the mask's top-left in the path's coordinates."""
    def _paint(p):
        if offset is not None:
            p.translate(-offset.x(), -offset.y())
        p.fillPath(path, MASK_WHITE)
    return coverage_mask(width, height, _paint, antialias)


def stroke_mask(points, pen_width: float, width: int, height: int, offset=None) -> np.ndarray:
    """Coverage mask of a round-capped polyline (healing-brush strokes),
    antialiased; `offset` as in path_mask."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QPen, QPolygonF

    def _paint(p):
        p.setPen(QPen(MASK_WHITE, pen_width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        ox, oy = (offset.x(), offset.y()) if offset is not None else (0, 0)
        p.drawPolyline(QPolygonF([QPointF(pt.x() - ox, pt.y() - oy) for pt in points]))
    return coverage_mask(width, height, _paint, antialias=True)


from PyQt6.QtGui import QColor as _QColor  # noqa: E402
MASK_WHITE = _QColor(255, 255, 255)


def mask_to_path(mask: np.ndarray, offset=None):
    """Selection outline of a pixel mask — bool, 0..1 float or 0..255 uint8
    (non-bool masks are taken at 50%) — as a simplified QPainterPath,
    shifted by `offset` (the mask's top-left in document coordinates).
    The one implementation behind Magic Wand, Color Range, Calculations,
    Select Subject/Sky/Focus Area, Select and Mask and Quick Mask exit."""
    from PyQt6.QtGui import QBitmap, QPainterPath, QRegion
    if mask.dtype == bool:
        on = mask
    elif np.issubdtype(mask.dtype, np.floating):
        on = mask >= 0.5
    else:
        on = mask >= 128
    h, w = on.shape
    img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32)
    img.fill(0)
    qimage_argb_view(img, writable=True)[:h, :w, 3][on] = 255
    path = QPainterPath()
    path.addRegion(QRegion(QBitmap.fromImage(img.createAlphaMask())))
    path = path.simplified()
    if offset is not None:
        path.translate(offset.x(), offset.y())
    return path


def gray_mask_image(values: np.ndarray) -> QImage:
    """A layer-mask image from 0..1 coverage values (white = visible)."""
    h, w = values.shape
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    v = np.clip(values * 255.0 + 0.5, 0, 255).astype(np.uint8)
    arr = qimage_argb_view(img, writable=True)[:, :w, :]
    arr[..., 0] = arr[..., 1] = arr[..., 2] = v
    arr[..., 3] = 255
    return img
