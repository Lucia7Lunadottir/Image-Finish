"""
tool_utils.py — общие утилиты для инструментов, работающих с пикселями.

Функции для работы с numpy/QImage: маски кисти, блюр, конвертация форматов.
Импортируются из effect_tools, fill_tool, advanced_erasers и т.д.
"""

from PyQt6.QtGui import QImage
from PyQt6.QtCore import QRect

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ── Геометрия ─────────────────────────────────────────────────────────────────

def _clamp_rect(rect: QRect, w: int, h: int) -> QRect:
    """Обрезает QRect по границам изображения."""
    x1 = max(0, rect.left())
    y1 = max(0, rect.top())
    x2 = min(w, rect.right() + 1)
    y2 = min(h, rect.bottom() + 1)
    return QRect(x1, y1, x2 - x1, y2 - y1)


# ── Конвертация QImage ↔ numpy ────────────────────────────────────────────────

def _qimage_to_np(img: QImage):
    """QImage ARGB32 → numpy (H, W, 4) uint8. Каналы: BGRA."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    import ctypes
    arr = np.empty((h, img.bytesPerLine() // 4, 4), dtype=np.uint8)
    ctypes.memmove(arr.ctypes.data, int(img.constBits()), img.sizeInBytes())
    return arr[:, :w, :]


def _np_to_qimage(arr) -> QImage:
    """numpy (H, W, 4) uint8 → QImage ARGB32."""
    h, w = arr.shape[:2]
    import ctypes
    arr_c = np.ascontiguousarray(arr)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    ctypes.memmove(int(img.bits()), arr_c.ctypes.data, min(img.sizeInBytes(), arr_c.nbytes))
    return img


# ── Маски кисти ───────────────────────────────────────────────────────────────

def _circle_mask(src_rect: QRect, cx: int, cy: int, r: int):
    """Бинарная маска круга (H, W, 1) float32: 1.0 внутри, 0.0 снаружи."""
    pw, ph = src_rect.width(), src_rect.height()
    xs = np.arange(pw) + src_rect.left() - cx
    ys = np.arange(ph) + src_rect.top()  - cy
    xx, yy = np.meshgrid(xs, ys)
    return (xx**2 + yy**2 <= r**2).astype(np.float32)[:, :, np.newaxis]


def _soft_circle_mask(src_rect: QRect, cx: int, cy: int, r: int):
    """Мягкая радиальная маска (H, W, 1) float32 [0.0–1.0], smoothstep.
    Всегда мягкая — не зависит от hardness. Используется Dodge/Burn/Sponge."""
    pw, ph = src_rect.width(), src_rect.height()
    xs = np.arange(pw) + src_rect.left() - cx
    ys = np.arange(ph) + src_rect.top()  - cy
    xx, yy = np.meshgrid(xs, ys)
    dist = np.sqrt(xx**2 + yy**2)
    mask = np.clip(1.0 - dist / max(1, r), 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)   # smoothstep
    return mask[:, :, np.newaxis].astype(np.float32)


def _brush_mask(src_rect: QRect, cx: int, cy: int, r: int, hardness: float = 1.0):
    """Маска кисти с контролем жёсткости (H, W, 1) float32.
    hardness=1.0 → жёсткий бинарный край; hardness=0.0 → smoothstep от центра."""
    pw, ph = src_rect.width(), src_rect.height()
    xs = np.arange(pw) + src_rect.left() - cx
    ys = np.arange(ph) + src_rect.top()  - cy
    xx, yy = np.meshgrid(xs, ys)
    dist   = np.sqrt(xx**2 + yy**2)
    r_f    = float(max(1, r))
    h      = float(np.clip(hardness, 0.0, 1.0))
    inner_r = r_f * h
    fade    = r_f - inner_r
    if fade < 1e-3:
        mask = (dist <= r_f).astype(np.float32)
    else:
        t    = np.clip((dist - inner_r) / fade, 0.0, 1.0)
        mask = (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)   # smoothstep
        mask[dist > r_f] = 0.0
    return mask[:, :, np.newaxis].astype(np.float32)


# ── Размытие ──────────────────────────────────────────────────────────────────

def _box_blur_rgb(arr3: "np.ndarray", radius: int) -> "np.ndarray":
    """Быстрый separable box blur для float32 массива с произвольным числом каналов.
    Используется для premultiplied RGB (или alpha) перед/после размытия."""
    from numpy import pad, cumsum
    r = max(1, radius)
    padded = pad(arr3, ((0, 0), (r, r), (0, 0)), mode='edge')
    cs     = cumsum(padded, axis=1)
    bh     = (cs[:, 2*r:, :] - cs[:, :-2*r, :]) / (2 * r)
    padded2 = pad(bh, ((r, r), (0, 0), (0, 0)), mode='edge')
    cs2    = cumsum(padded2, axis=0)
    return (cs2[2*r:, :, :] - cs2[:-2*r, :, :]) / (2 * r)


def _box_blur_np(arr, radius: int):
    """Box blur для 4-канального BGRA через premultiplied alpha.
    Используется в SharpenTool (_sharpen_np)."""
    from numpy import pad, cumsum
    r     = max(1, radius)
    arr_f = arr.astype(np.float32)
    alpha = arr_f[..., 3:4] / 255.0
    premult = arr_f.copy()
    premult[..., :3] *= alpha
    padded  = pad(premult, ((0, 0), (r, r), (0, 0)), mode='edge')
    cs      = cumsum(padded, axis=1)
    bh      = (cs[:, 2*r:, :] - cs[:, :-2*r, :]) / (2 * r)
    padded2 = pad(bh, ((r, r), (0, 0), (0, 0)), mode='edge')
    cs2     = cumsum(padded2, axis=0)
    blurred = (cs2[2*r:, :, :] - cs2[:-2*r, :, :]) / (2 * r)
    blurred_alpha = blurred[..., 3:4]
    safe    = np.maximum(blurred_alpha, 1e-6)
    result  = blurred.copy()
    result[..., :3] = np.where(blurred_alpha > 0.5,
                               blurred[..., :3] * 255.0 / safe,
                               0.0)
    return result.clip(0, 255).astype(np.uint8)


def _sharpen_np(arr, strength: float = 1.0):
    """Unsharp mask: result = orig + strength*(orig − blurred)."""
    blurred = _box_blur_np(arr, 2)
    detail  = arr.astype(np.float32) - blurred.astype(np.float32)
    return (arr.astype(np.float32) + strength * detail).clip(0, 255).astype(np.uint8)


# ── Qt fallback (без numpy) ───────────────────────────────────────────────────

def fast_box_blur_np(arr, radius: int):
    """Быстрый separable box blur для предпросмотра в диалогах.
    Принимает (H, W, C) uint8, возвращает uint8 того же размера.
    Не зависит от порядка каналов — не содержит логики premultiplied alpha."""
    import numpy as np
    r = int(radius)
    if r <= 0:
        return arr.copy()
    h, w, c = arr.shape
    r = min(r, max(1, min(h, w) // 2))

    pad_h  = np.pad(arr, ((0, 0), (r, r), (0, 0)), mode='edge').astype(np.int32)
    cs_h   = np.cumsum(pad_h, axis=1)
    res_h  = np.empty_like(arr, dtype=np.int32)
    res_h[:, 0, :]  = cs_h[:, 2*r, :]
    if w > 1:
        res_h[:, 1:, :] = cs_h[:, 2*r+1:, :] - cs_h[:, :-2*r-1, :]
    res_h //= (2*r + 1)

    pad_v  = np.pad(res_h, ((r, r), (0, 0), (0, 0)), mode='edge')
    cs_v   = np.cumsum(pad_v, axis=0)
    res_v  = np.empty_like(res_h)
    res_v[0, :, :]  = cs_v[2*r, :, :]
    if h > 1:
        res_v[1:, :, :] = cs_v[2*r+1:, :, :] - cs_v[:-2*r-1, :, :]
    res_v //= (2*r + 1)

    return res_v.astype(np.uint8)


def _apply_qt_blur(image: QImage, cx: int, cy: int, radius: int, passes: int = 2):
    """Box blur круговой области через QImage.pixel (медленно, fallback)."""
    from PyQt6.QtGui import QColor
    rect = _clamp_rect(QRect(cx - radius, cy - radius, 2*radius, 2*radius),
                       image.width(), image.height())
    if rect.isEmpty():
        return
    for _ in range(passes):
        for y in range(rect.top(), rect.bottom()):
            for x in range(rect.left(), rect.right()):
                rs = gs = bs = als = n = 0
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        nx_, ny_ = x + dx, y + dy
                        if 0 <= nx_ < image.width() and 0 <= ny_ < image.height():
                            c = QColor(image.pixel(nx_, ny_))
                            rs += c.red(); gs += c.green()
                            bs += c.blue(); als += c.alpha()
                            n += 1
                if n:
                    image.setPixel(x, y, QColor(rs//n, gs//n, bs//n, als//n).rgba())
