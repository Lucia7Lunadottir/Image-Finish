"""PuppetWarpTool/PerspectiveWarpTool/WarpTool each had their own copy of
`if getattr(layer, "layer_type", "raster") in ("artboard", "group"): return`
(identical one-liner in all three files) — replaced with the already-tested
`Layer._is_container` flag. These tests pin that the guard still no-ops on
containers and still starts a transform on a plain layer.
"""
from PyQt6.QtCore import QPoint

from core.document import Document
from core.layer import ArtboardLayer, GroupLayer
from tools.puppet_warp_tool import PuppetWarpTool
from tools.perspective_warp_tool import PerspectiveWarpTool
from tools.warp_tool import WarpTool

OPTS = {"_zoom": 1.0}


def _make_container_doc(cls):
    doc = Document(100, 80)
    layer = doc.layers[0].convert_to(cls)
    doc.layers[0] = layer
    return doc


def test_puppet_warp_skips_containers(qapp):
    for cls in (ArtboardLayer, GroupLayer):
        doc = _make_container_doc(cls)
        tool = PuppetWarpTool()
        tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
        assert tool.is_transforming is False

    doc = Document(100, 80)
    tool = PuppetWarpTool()
    tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
    assert tool.is_transforming is True


def test_perspective_warp_skips_containers(qapp):
    for cls in (ArtboardLayer, GroupLayer):
        doc = _make_container_doc(cls)
        tool = PerspectiveWarpTool()
        tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
        assert tool.is_transforming is False

    doc = Document(100, 80)
    tool = PerspectiveWarpTool()
    tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
    assert tool.is_transforming is True


def test_warp_tool_skips_containers(qapp):
    for cls in (ArtboardLayer, GroupLayer):
        doc = _make_container_doc(cls)
        tool = WarpTool()
        tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
        assert tool.is_transforming is False

    doc = Document(100, 80)
    tool = WarpTool()
    tool.on_press(QPoint(50, 40), doc, None, None, OPTS)
    assert tool.is_transforming is True
