"""tools/magic_wand_tool.py used a third QImage<->numpy bridging idiom
(`.bits()` + `.setsize()` + `np.frombuffer`) not caught by the earlier
`ctypes.memmove`/`from_address` audit — migrated to the same
core.pixel_buffer.qimage_argb_view as everything else. No prior test
coverage existed for this file at all.
"""
from PyQt6.QtCore import QPoint, QPointF
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from tools.magic_wand_tool import MagicWandTool, QuickSelectionTool, ObjectSelectionTool


def test_get_safe_layer_snapshot_is_isolated_copy(qapp):
    doc = Document(40, 30)
    layer = doc.layers[0]
    layer.image.fill(QColor(10, 20, 30, 255))

    tool = MagicWandTool()
    img, np_data = tool._get_safe_layer_snapshot(layer)

    assert np_data.shape[:2] == (30, 40)
    assert tuple(np_data[5, 5, :3]) == (10, 20, 30)

    # Mutating the layer afterward must not affect the already-taken snapshot.
    layer.image.fill(QColor(200, 200, 200, 255))
    assert tuple(np_data[5, 5, :3]) == (10, 20, 30)


def test_magic_wand_flood_fill_matches_contiguous_region(qapp):
    doc = Document(40, 30)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(0, 0, 20, 30, QColor(200, 50, 50, 255))
    p.fillRect(20, 0, 20, 30, QColor(10, 10, 200, 255))
    p.end()

    _, np_data = MagicWandTool()._get_safe_layer_snapshot(layer)
    mask = MagicWandTool._background_flood_fill(
        np_data=np_data, start_pos=(5, 15), target_color=(200, 50, 50),
        tolerance_pct=10, contiguous=True,
    )
    assert mask[15, 5] == True
    assert mask[15, 25] == False  # other color region excluded
    assert mask.sum() == 20 * 30  # whole left half matched


def test_convert_mask_to_path_encloses_masked_region(qapp):
    import numpy as np
    mask = np.zeros((30, 40), dtype=bool)
    mask[10:20, 10:20] = True

    tool = MagicWandTool()
    path = tool._convert_mask_to_path(mask, QPoint(0, 0))

    assert path.contains(QPointF(15, 15))
    assert not path.contains(QPointF(2, 2))


def test_quick_selection_brush_grows_live_mask(qapp):
    doc = Document(40, 30)
    layer = doc.layers[0]
    layer.image.fill(QColor(100, 100, 100, 255))

    tool = QuickSelectionTool()
    opts = {"brush_size": 10, "fill_tolerance": 20}
    tool.on_press(QPoint(20, 15), doc, QColor(), QColor(), opts)
    assert tool._live_mask is not None
    assert tool._live_mask[15, 20] == True

    preview = tool.stroke_preview()
    assert preview is not None
    img, offset, opacity = preview
    assert img.pixelColor(20, 15).alpha() > 0

    tool.on_release(QPoint(20, 15), doc, QColor(), QColor(), opts)
    assert doc.selection is not None and not doc.selection.isEmpty()


def test_object_selection_selects_bounding_box(qapp):
    doc = Document(40, 30)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer.image)
    p.fillRect(10, 5, 15, 15, QColor(80, 160, 40, 255))
    p.end()

    tool = ObjectSelectionTool()
    tool.on_press(QPoint(10, 5), doc, QColor(), QColor(), {})
    tool.on_move(QPoint(25, 20), doc, QColor(), QColor(), {})
    tool.on_release(QPoint(25, 20), doc, QColor(), QColor(), {})

    assert doc.selection is not None and not doc.selection.isEmpty()
