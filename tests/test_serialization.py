"""Round-trip, legacy-load, validation and atomicity of the .imfn formats."""

import gzip
import os
import pickle

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtCore import QRectF, QPointF

from core.document import Document
from core.layer import RasterLayer, GroupLayer, FillLayer, VectorLayer
from core.serialization import (SerializationError, load_document,
                                save_document)


def _rich_document():
    doc = Document(64, 48)
    doc.layers[0].image.fill(QColor(255, 0, 0))
    group = GroupLayer("Group", 64, 48)
    doc.layers.append(group)
    child = RasterLayer("Child", 64, 48)
    child.parent_id = group.layer_id
    child.image.fill(QColor(0, 255, 0, 128))
    child.opacity = 0.7
    child.blend_mode = "Multiply"
    child.layer_styles = {"drop_shadow": {"enabled": True,
                                          "color": QColor(10, 20, 30),
                                          "opacity": 75}}
    child.mask = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
    child.mask.fill(QColor(255, 255, 255))
    doc.layers.append(child)
    fill = FillLayer("Fill", 64, 48)
    fill.fill_data = {"type": "solid", "color": QColor(1, 2, 3)}
    doc.layers.append(fill)
    from PyQt6.QtGui import QPainterPath
    vector = VectorLayer("Path", 64, 48)
    vpath = QPainterPath()
    vpath.addEllipse(10, 10, 20, 20)
    vector.vector_mask = vpath
    vector.path_style = {"fill_color": QColor(9, 8, 7), "stroke_color": None, "stroke_width": 0.0}
    doc.layers.append(vector)
    doc.saved_paths = [{
        "name": "Path 1",
        "closed": True,
        "nodes": [
            {"p": QPointF(1, 2), "c1": QPointF(1, 2), "c2": QPointF(3, 4)},
            {"p": QPointF(5, 6), "c1": QPointF(5, 6), "c2": QPointF(5, 6)},
        ],
    }]
    return doc


def test_v2_roundtrip(qapp, tmp_path):
    doc = _rich_document()
    path = str(tmp_path / "doc.imfn")
    save_document(doc, path)

    doc2, legacy = load_document(path)
    assert not legacy
    assert len(doc2.layers) == 5
    assert doc2.layers[2].parent_id == doc2.layers[1].layer_id
    assert doc2.layers[2].opacity == pytest.approx(0.7)
    assert doc2.layers[2].blend_mode == "Multiply"
    color = doc2.layers[2].layer_styles["drop_shadow"]["color"]
    assert isinstance(color, QColor) and color.red() == 10 and color.blue() == 30
    assert isinstance(doc2.layers[3].fill_data["color"], QColor)
    assert doc2.layers[2].mask is not None
    assert doc2.layers[0].image.pixelColor(5, 5) == QColor(255, 0, 0)
    vec = doc2.layers[4]
    assert isinstance(vec.path_style["fill_color"], QColor)
    assert vec.path_style["fill_color"].getRgb()[:3] == (9, 8, 7)
    assert vec.vector_mask is not None and not vec.vector_mask.isEmpty()
    assert vec.vector_mask.contains(QRectF(15, 15, 5, 5))
    assert len(doc2.saved_paths) == 1
    sp = doc2.saved_paths[0]
    assert sp["name"] == "Path 1" and sp["closed"] is True
    assert isinstance(sp["nodes"][0]["p"], QPointF)
    assert sp["nodes"][1]["p"].x() == 5 and sp["nodes"][1]["p"].y() == 6


def test_legacy_pickle_loads_and_converts(qapp, tmp_path):
    path = str(tmp_path / "legacy.imfn")
    data = {"width": 32, "height": 20, "color_mode": "RGB", "bit_depth": 8,
            "layers": [RasterLayer("L1", 32, 20).to_dict()]}
    with gzip.open(path, "wb") as f:
        pickle.dump(data, f)

    doc, legacy = load_document(path)
    assert legacy and doc.width == 32

    save_document(doc, path)
    doc2, legacy2 = load_document(path)
    assert not legacy2


def test_failed_save_keeps_original(qapp, tmp_path):
    doc = _rich_document()
    path = str(tmp_path / "doc.imfn")
    save_document(doc, path)
    original = open(path, "rb").read()

    broken = Document(16, 16)
    broken.layers[0].to_dict = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(Exception):
        save_document(broken, path)

    assert open(path, "rb").read() == original
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".imfn-save-")]


def test_corrupted_file_raises_serialization_error(qapp, tmp_path):
    path = str(tmp_path / "bad.imfn")
    with open(path, "wb") as f:
        f.write(b"PK\x03\x04this is not really a zip")
    with pytest.raises(SerializationError):
        load_document(path)


def test_unknown_format_raises(qapp, tmp_path):
    path = str(tmp_path / "noise.imfn")
    with open(path, "wb") as f:
        f.write(b"just some text")
    with pytest.raises(SerializationError):
        load_document(path)
