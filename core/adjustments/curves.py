"""Curves adjustment — per-channel tone curve via a monotone cubic spline
through user-placed control points, applied as an 8-bit LUT.

Channels compose the way Photoshop's Curves do: the "rgb" (master) curve
is applied to R/G/B first, then each channel's own curve refines it
further — so a master S-curve plus a per-channel tweak both take effect.
"""

from PyQt6.QtGui import QImage

from ui.adjustments_dialog import _to_argb32

IDENTITY_POINTS = [(0, 0), (255, 255)]


def spline_lut(points: list) -> list:
    """Build a 256-entry LUT from (x, y) control points (0..255 each).

    Uses a monotone cubic Hermite spline (Fritsch-Carlson): unlike a plain
    Catmull-Rom spline, it never overshoots past neighboring points' y
    values, so steep S-curves from closely-spaced points don't ring/band.
    """
    pts = sorted({p[0]: p for p in points}.values(), key=lambda p: p[0])
    if len(pts) < 2:
        return list(range(256))

    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    n = len(pts)

    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
         for i in range(n - 1)]

    m = [0.0] * n
    m[0] = d[0]
    m[-1] = d[-1]
    for i in range(1, n - 1):
        if d[i - 1] == 0.0 or d[i] == 0.0 or (d[i - 1] > 0) != (d[i] > 0):
            m[i] = 0.0
        else:
            m[i] = (d[i - 1] + d[i]) / 2.0

    for i in range(n - 1):
        if d[i] == 0.0:
            m[i] = 0.0
            m[i + 1] = 0.0
            continue
        a = m[i] / d[i]
        b = m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9.0:
            t = 3.0 / (s ** 0.5)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]

    lut = [0] * 256
    seg = 0
    for x in range(256):
        while seg < n - 2 and x > xs[seg + 1]:
            seg += 1
        x0, x1 = xs[seg], xs[seg + 1]
        if x <= xs[0]:
            y = ys[0]
        elif x >= xs[-1]:
            y = ys[-1]
        elif x1 == x0:
            y = ys[seg]
        else:
            h = x1 - x0
            t = (x - x0) / h
            t2, t3 = t * t, t * t * t
            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2
            y = h00 * ys[seg] + h10 * h * m[seg] + h01 * ys[seg + 1] + h11 * h * m[seg + 1]
        lut[x] = max(0, min(255, int(round(y))))
    return lut


def apply_curves(src: QImage, points: dict) -> QImage:
    """points: {"rgb": [...], "r": [...], "g": [...], "b": [...]}, each a
    list of (x, y) control points; missing/empty channels default to identity."""
    rgb_lut = spline_lut(points.get("rgb") or IDENTITY_POINTS)
    r_lut = spline_lut(points.get("r") or IDENTITY_POINTS)
    g_lut = spline_lut(points.get("g") or IDENTITY_POINTS)
    b_lut = spline_lut(points.get("b") or IDENTITY_POINTS)

    final_r = [r_lut[rgb_lut[i]] for i in range(256)]
    final_g = [g_lut[rgb_lut[i]] for i in range(256)]
    final_b = [b_lut[rgb_lut[i]] for i in range(256)]

    img = _to_argb32(src)
    try:
        import numpy as np
        img = img.copy()
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.width(), 4))
        arr[:, :, 2] = np.array(final_r, dtype=np.uint8)[arr[:, :, 2]]
        arr[:, :, 1] = np.array(final_g, dtype=np.uint8)[arr[:, :, 1]]
        arr[:, :, 0] = np.array(final_b, dtype=np.uint8)[arr[:, :, 0]]
        del arr
        del ptr
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    except ImportError:
        for y in range(img.height()):
            for x in range(img.width()):
                px = img.pixel(x, y)
                a = (px >> 24) & 0xFF
                r = final_r[(px >> 16) & 0xFF]
                g = final_g[(px >> 8) & 0xFF]
                b = final_b[px & 0xFF]
                img.setPixel(x, y, (a << 24) | (r << 16) | (g << 8) | b)
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
