"""Filter previews must never mutate the caller's source image.

Regression: _to_argb32 used to return the input object itself for ARGB32
images, so blur previews corrupted the dialog's stored original — lowering
the Gaussian Blur radius after raising it had no visible effect.
"""

import hashlib

from PyQt6.QtGui import QColor, QImage, QPainter

from core.filters.blur_filters import apply_gaussian_blur


def _digest(img):
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return hashlib.md5(bytes(ptr)).hexdigest()


def _sample(fmt):
    img = QImage(200, 150, fmt)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(60, 40, 80, 60, QColor(200, 30, 30))
    p.end()
    return img


def test_gaussian_blur_does_not_mutate_source(qapp):
    for fmt in (QImage.Format.Format_ARGB32,
                QImage.Format.Format_ARGB32_Premultiplied):
        src = _sample(fmt)
        before = _digest(src)
        apply_gaussian_blur(src, 40.0)
        assert _digest(src) == before, f"source mutated for {fmt}"


def test_gaussian_blur_radius_can_decrease(qapp):
    """Simulates the dialog: big radius preview, then small radius preview
    from the same stored original must equal a direct small-radius blur."""
    src = _sample(QImage.Format.Format_ARGB32)
    apply_gaussian_blur(src, 60.0)          # big preview
    small_after_big = apply_gaussian_blur(src, 2.0)
    direct_small = apply_gaussian_blur(_sample(QImage.Format.Format_ARGB32), 2.0)
    assert _digest(small_after_big) == _digest(direct_small)
