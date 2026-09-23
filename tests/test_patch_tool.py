"""tools/patch_tool.py had 13 hand-rolled ctypes/numpy QImage buffer
accesses across 4 tool classes (PatchTool, SpotHealingTool, RedEyeTool,
HealingBrushTool) and zero test coverage. Migrated the ARGB32-view ones to
core.pixel_buffer.qimage_argb_view (kept the few Format_Grayscale8 mask
bridges manual — different pixel format, not compatible) and, along the
way, removed two "read the full canvas into a scratch array, then
immediately overwrite every byte of it" dead reads (SpotHealingTool and
HealingBrushTool's on_release both built `new_img` by reading `layer.image`
into `out_arr` and then unconditionally overwriting `out_arr[:, :w, :]`
with the already-computed result — the initial read was pure waste).

These tests exercise each of the four classes' full press/move/release
flow end to end and check the result moved in the expected direction —
exact pixel values depend on brightness-matching + feathering math that
predates this refactor, so the assertions pin *direction*, not exact
output, matching what a numpy-shape/buffer-bridge migration should and
shouldn't change.
"""
from PyQt6.QtCore import QPoint, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath

from core.document import Document
from tools.patch_tool import PatchTool, SpotHealingTool, RedEyeTool, HealingBrushTool


def test_patch_tool_clones_from_dragged_source(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(0, 0, 50, 80, QColor(240, 240, 240, 255))   # clean source (left half)
    p.fillRect(50, 0, 50, 80, QColor(200, 30, 30, 255))    # blemish (right half)
    p.end()

    sel = QPainterPath()
    sel.addRect(QRectF(60, 30, 20, 20))
    doc.selection = sel

    tool = PatchTool()
    opts = {"patch_opacity": 1.0, "patch_diffusion": 5}
    tool.on_press(QPoint(65, 35), doc, QColor(), QColor(), opts)
    assert tool._mode == "drag"
    tool.on_move(QPoint(15, 35), doc, QColor(), QColor(), opts)  # drag onto the clean source
    tool.on_release(QPoint(15, 35), doc, QColor(), QColor(), opts)

    # Patch Tool brightness-matches the clone to the selection's own boundary
    # tone (so it blends into surrounding lighting/texture) — for a flat
    # blemish that pulls the result back toward the blemish's own color, so
    # don't assert it now looks like the raw source; assert a real change
    # happened inside the selection and nothing changed outside it.
    before = (200, 30, 30, 255)
    c = layer.image.pixelColor(70, 40)
    assert c.getRgb() != before
    assert c.green() > before[1]  # still pulled lighter/toward the source
    assert layer.image.pixelColor(90, 40).getRgb() == before  # outside selection: untouched


def test_spot_healing_removes_blemish(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 80, QColor(230, 230, 230, 255))  # clean background
    p.fillRect(40, 30, 10, 10, QColor(200, 20, 20, 255))   # small red blemish
    p.end()

    tool = SpotHealingTool()
    opts = {"brush_size": 14, "brush_opacity": 1.0}
    tool.on_press(QPoint(45, 35), doc, QColor(), QColor(), opts)
    tool.on_move(QPoint(46, 35), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(46, 35), doc, QColor(), QColor(), opts)

    c = layer.image.pixelColor(45, 35)
    assert c.getRgb() != (200, 20, 20, 255)  # blemish changed
    assert layer.image.pixelColor(5, 5).getRgb() == (230, 230, 230, 255)  # far away: untouched


def test_red_eye_desaturates_red_region(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 80, QColor(200, 200, 200, 255))
    p.fillRect(40, 30, 20, 20, QColor(220, 20, 20, 255))  # "red eye"
    p.end()

    tool = RedEyeTool()
    opts = {"red_eye_darken": 50}
    tool.on_press(QPoint(42, 32), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(58, 48), doc, QColor(), QColor(), opts)

    c = layer.image.pixelColor(50, 40)
    assert c.red() < 220
    assert abs(c.red() - c.green()) < 40  # no longer strongly red


def test_healing_brush_paints_from_sampled_source(qapp):
    doc = Document(100, 80)
    layer = doc.layers[0]
    p = QPainter(layer.image)
    p.fillRect(0, 0, 100, 80, QColor(230, 230, 230, 255))
    p.fillRect(10, 10, 10, 10, QColor(50, 120, 200, 255))   # clean sample source
    p.fillRect(60, 50, 10, 10, QColor(200, 40, 40, 255))    # blemish to paint over
    p.end()

    tool = HealingBrushTool()
    opts = {"brush_size": 12, "brush_opacity": 1.0}
    tool.on_press(QPoint(15, 15), doc, QColor(), QColor(), {**opts, "_alt": True})  # set source
    tool.on_press(QPoint(65, 55), doc, QColor(), QColor(), opts)                     # begin stroke
    tool.on_move(QPoint(66, 55), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(66, 55), doc, QColor(), QColor(), opts)

    c = layer.image.pixelColor(65, 55)
    assert c.getRgb() != (200, 40, 40, 255)  # blemish changed
    assert c.blue() > 40  # pulled toward the blue sample, away from pure red blemish
    assert layer.image.pixelColor(5, 5).getRgb() == (230, 230, 230, 255)  # far away: untouched
