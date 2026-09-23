"""tools/effect_tools.py (Blur/Sharpen/Smudge/Dodge/Burn/Sponge) had zero
test coverage despite being one of the few tool files that was already
well-architected before this session's refactor pass (Template Method via
BrushEffectTool._compute_effect + _SoftMaskMixin/_EffectStrokeMixin) — no
duplication was found to remove, so this audit's contribution is
characterization tests for the six brush effects plus the shared
lock_pixels/lock_alpha guards in BrushEffectTool._apply.
"""
import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from tools.effect_tools import (
    BlurTool, SharpenTool, SmudgeTool, DodgeTool, BurnTool, SpongeTool,
)


def _stroke(tool, doc, pos, opts, fg=QColor(0, 0, 0), bg=QColor(255, 255, 255)):
    tool.on_press(pos, doc, fg, bg, opts)
    tool.on_release(pos, doc, fg, bg, opts)


def _checker_doc(w=100, h=100):
    doc = Document(w, h)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(0, 0, w // 2, h, QColor(20, 20, 20, 255))
    p.fillRect(w // 2, 0, w // 2, h, QColor(235, 235, 235, 255))
    p.end()
    return doc, layer


def test_blur_softens_a_sharp_edge():
    doc, layer = _checker_doc()
    before = layer.image.copy()
    tool = BlurTool()
    opts = {"brush_size": 40, "brush_hardness": 1.0, "effect_strength": 1.0}
    _stroke(tool, doc, QPoint(50, 50), opts)  # centered on the seam

    # right at the seam, contrast between neighboring pixels must drop
    def row_variance(img, y):
        vals = [QColor(img.pixel(x, y)).red() for x in range(35, 66)]
        return np.var(vals)

    assert row_variance(layer.image, 50) < row_variance(before, 50)
    # far from the brush, nothing should have changed
    assert layer.image.pixelColor(5, 5) == before.pixelColor(5, 5)


def test_sharpen_increases_contrast_on_soft_edge():
    doc, layer = _checker_doc()
    # pre-blur the seam so sharpen has something to sharpen
    blur = BlurTool()
    _stroke(blur, doc, QPoint(50, 50), {"brush_size": 60, "brush_hardness": 1.0, "effect_strength": 1.0})
    softened = layer.image.copy()

    sharpen = SharpenTool()
    _stroke(sharpen, doc, QPoint(50, 50), {"brush_size": 40, "brush_hardness": 1.0, "effect_strength": 1.0})

    def gradient_energy(img, y):
        vals = [QColor(img.pixel(x, y)).red() for x in range(44, 57)]
        return sum((b - a) ** 2 for a, b in zip(vals, vals[1:]))

    assert gradient_energy(layer.image, 50) > gradient_energy(softened, 50)


def test_smudge_drags_color_in_stroke_direction():
    doc, layer = _checker_doc()
    tool = SmudgeTool()
    opts = {"brush_size": 24, "brush_hardness": 1.0, "effect_strength": 1.0}
    # start on the dark side, drag into the light side
    tool.on_press(QPoint(30, 50), doc, QColor(0, 0, 0), QColor(255, 255, 255), opts)
    tool.on_move(QPoint(70, 50), doc, QColor(0, 0, 0), QColor(255, 255, 255), opts)
    tool.on_release(QPoint(70, 50), doc, QColor(0, 0, 0), QColor(255, 255, 255), opts)

    # a point on the light side, near where the drag ended, should have darkened
    after = layer.image.pixelColor(68, 50).red()
    assert after < 235


def test_dodge_brightens_and_burn_darkens():
    doc, layer = _checker_doc()
    mid = QColor(120, 120, 120, 255)
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 100, mid)
    p.end()

    dodge = DodgeTool()
    _stroke(dodge, doc, QPoint(50, 50), {"brush_size": 30, "effect_strength": 1.0})
    assert layer.image.pixelColor(50, 50).red() > mid.red()

    doc2, layer2 = _checker_doc()
    p = QPainter(layer2.image)
    p.fillRect(0, 0, 100, 100, mid)
    p.end()
    burn = BurnTool()
    _stroke(burn, doc2, QPoint(50, 50), {"brush_size": 30, "effect_strength": 1.0})
    assert layer2.image.pixelColor(50, 50).red() < mid.red()


def test_sponge_desaturate_and_saturate():
    doc, layer = _checker_doc()
    sat = QColor(200, 40, 40, 255)  # strongly saturated red
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 100, sat)
    p.end()

    def saturation(c):
        mx, mn = max(c.red(), c.green(), c.blue()), min(c.red(), c.green(), c.blue())
        return mx - mn

    desat_tool = SpongeTool()
    _stroke(desat_tool, doc, QPoint(50, 50), {"brush_size": 30, "effect_strength": 1.0, "sponge_mode": "desaturate"})
    assert saturation(layer.image.pixelColor(50, 50)) < saturation(sat)

    doc2, layer2 = _checker_doc()
    p = QPainter(layer2.image)
    p.fillRect(0, 0, 100, 100, sat)
    p.end()
    sat_tool = SpongeTool()
    _stroke(sat_tool, doc2, QPoint(50, 50), {"brush_size": 30, "effect_strength": 1.0, "sponge_mode": "saturate"})
    assert saturation(layer2.image.pixelColor(50, 50)) > saturation(sat)


def test_lock_pixels_blocks_effect():
    doc, layer = _checker_doc()
    layer.lock_pixels = True
    before = layer.image.copy()
    tool = BlurTool()
    _stroke(tool, doc, QPoint(50, 50), {"brush_size": 40, "effect_strength": 1.0})
    assert layer.image.pixelColor(50, 50) == before.pixelColor(50, 50)


def test_lock_alpha_preserves_original_alpha():
    doc, layer = _checker_doc()
    # punch a translucent hole so the effect actually touches alpha
    p = QPainter(layer.image)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(45, 45, 10, 10, QColor(0, 0, 0, 0))
    p.end()
    layer.lock_alpha = True
    before_alpha = layer.image.pixelColor(48, 48).alpha()

    tool = BlurTool()
    _stroke(tool, doc, QPoint(50, 50), {"brush_size": 40, "effect_strength": 1.0})
    assert layer.image.pixelColor(48, 48).alpha() == before_alpha
