"""Brush tips: the built-in shapes and the image tips in brushes/, and
the stamp a tip makes at a given size and hardness.

Everything that shows or paints a tip — the brush tools, the brush
outline on the canvas, the options bar list, the Brushes panel and the
right-click brush picker — gets it from here, so a tip looks and paints
the same everywhere.

A tip value is a string: one of `BUILTIN_TIPS`, or the path of an image.
"""
import glob
import math
import os
import random
import shutil
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QRadialGradient

BUILTIN_TIPS = ("round", "square", "scatter")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
BRUSHES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brushes")


@dataclass(frozen=True)
class BrushTip:
    value: str           # what goes into tool_opts["brush_mask"]
    title_key: str | None  # translation key for built-ins
    name: str            # file name for image tips

    @property
    def is_builtin(self) -> bool:
        return self.value in BUILTIN_TIPS


def available_tips() -> list[BrushTip]:
    """Built-in shapes first, then every image in brushes/ by name."""
    tips = [BrushTip(v, f"opts.mask.{v}", v) for v in BUILTIN_TIPS]
    if os.path.isdir(BRUSHES_DIR):
        files = [p for p in glob.glob(os.path.join(BRUSHES_DIR, "*"))
                 if p.lower().endswith(_IMAGE_EXTS)]
        for path in sorted(files, key=lambda p: os.path.basename(p).lower()):
            tips.append(BrushTip(path, None, os.path.splitext(os.path.basename(path))[0]))
    return tips


def import_tip_file(path: str) -> str:
    """Copy an image into brushes/ (kept for later sessions); its tip value."""
    os.makedirs(BRUSHES_DIR, exist_ok=True)
    target = os.path.join(BRUSHES_DIR, os.path.basename(path))
    if os.path.abspath(path) != os.path.abspath(target):
        shutil.copy2(path, target)
    return target


def save_tip_image(name: str, img: QImage) -> str:
    """Store a new tip image (Edit > Define Brush) under `name`."""
    os.makedirs(BRUSHES_DIR, exist_ok=True)
    path = os.path.join(BRUSHES_DIR, f"{name}.png")
    img.save(path)
    return path


def tip_stamp(size: int, hardness: float, tip) -> QImage:
    """The tip's alpha stamp, size × size (colour comes at painting time).
    Image tips: their alpha, or inverted luminance for opaque images (dark
    = paint), stretched to the square."""
    image = tip if isinstance(tip, QImage) else None
    if image is None and isinstance(tip, str) and tip not in BUILTIN_TIPS:
        image = QImage(tip)
    if image is None or image.isNull():
        return _generated_stamp(size, hardness, tip if tip in BUILTIN_TIPS else "round")
    stamp = image.scaled(max(1, size), max(1, size), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    if not stamp.hasAlphaChannel():
        from core.pixel_buffer import qimage_argb_view
        stamp = stamp.convertToFormat(QImage.Format.Format_ARGB32)
        arr = qimage_argb_view(stamp, writable=True)
        luma = (arr[..., 2] * 0.299 + arr[..., 1] * 0.587 + arr[..., 0] * 0.114).astype(np.uint8)
        arr[..., 3] = 255 - luma
        arr[..., 0:3] = 0
    return stamp


def _generated_stamp(size: int, hardness: float, mask: str) -> QImage:
    """
    Returns a QImage (size x size ARGB32) brush stamp.
    Alpha channel defines the shape: 255 = full paint, 0 = empty.

    mask:
      round   - circular with softness based on hardness
      square  - square
      scatter - circular with noise at edges
    """
    s = max(2, size)
    img = QImage(s, s, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, r = s / 2, s / 2, s / 2 - 0.5

    if mask == "square":
        margin = int(s * (1 - hardness) * 0.3)
        inner = QRect(margin, margin, s - 2 * margin, s - 2 * margin)
        p.fillRect(img.rect(), Qt.GlobalColor.transparent)
        p.setBrush(QBrush(QColor(0, 0, 0, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(inner, margin * 0.5, margin * 0.5)

    elif mask == "scatter":
        # Base: soft circle, edges: random splashes
        grad = QRadialGradient(cx, cy, r)
        inner_stop = max(0.0, min(1.0, hardness))
        grad.setColorAt(0,          QColor(0, 0, 0, 255))
        grad.setColorAt(inner_stop, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0,        QColor(0, 0, 0, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        # Add random splatter outside
        p.setBrush(QBrush(QColor(0, 0, 0, 180)))
        rng = random.Random(size)   # deterministic seed
        for _ in range(int(s * 0.4)):
            angle = rng.uniform(0, 2 * math.pi)
            dist  = rng.uniform(r * 0.6, r * 1.3)
            sx = cx + math.cos(angle) * dist
            sy = cy + math.sin(angle) * dist
            dr = rng.uniform(0.5, max(1, s * 0.04))
            p.drawEllipse(QPointF(sx, sy), dr, dr)

    else:  # round (default)
        grad = QRadialGradient(cx, cy, r)
        inner_stop = max(0.0, min(0.99, hardness))

        # Common start for all round brushes
        grad.setColorAt(0, QColor(0, 0, 0, 255))
        grad.setColorAt(inner_stop, QColor(0, 0, 0, 255))

        # Smoother, quadratic falloff for soft brushes feels more natural
        if inner_stop < 0.1:  # Apply to very soft brushes (hardness < 10%)
            # Approximation of y=(1-x)^2 curve from inner_stop to 1.0
            span = 1.0 - inner_stop
            if span > 0:
                # y = (1 - (x-is)/span)^2. We start from t=0.25
                for i in range(1, 5):
                    t = i / 4.0
                    x = inner_stop + t * span
                    y = (1.0 - t)**2
                    grad.setColorAt(x, QColor(0, 0, 0, int(255 * y)))
            else:  # this case is inner_stop >= 1, but for safety
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:  # Original linear falloff for harder brushes
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))

        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

    p.end()
    return img
