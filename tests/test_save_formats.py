"""Saving: the format registry (core/image_formats.py), flat exports through
Qt's writers, the quality option, and Photoshop export (core/psd_export.py)
read back by our own PSD reader."""
import struct

import numpy as np
import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QImageReader
from PyQt6.QtWidgets import QFileDialog

from core.document import Document
from core.image_formats import (FORMATS, available_formats, format_for_filter, format_for_path,
                                prepare_flat_image, save_filter, write_flat_image)
from core.layer import AdjustmentLayer, GroupLayer, RasterLayer, TextLayer
from core.psd_export import PsdExporter, _RleEncoder
from core.psd_import import PsdImporter, _unpack_bits


def _rgba(w=40, h=30):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    for x in range(10, 30):
        for y in range(5, 20):
            img.setPixelColor(x, y, QColor(200, 40, 40))
    return img


# ── registry ─────────────────────────────────────────────────────────────────

def test_registry_lists_only_what_qt_can_write(qapp):
    keys = [f.key for f in available_formats()]
    assert keys[:3] == ["imfn", "psd", "png"]
    from PyQt6.QtGui import QImageWriter
    qt = {bytes(f).decode() for f in QImageWriter.supportedImageFormats()}
    assert all(f.writer != "qt" or f.key in qt for f in available_formats())
    assert len(available_formats()) >= 6


def test_format_lookup_by_extension_and_filter(qapp):
    assert format_for_path("a.JPG").key == "jpeg" and format_for_path("a.jfif").key == "jpeg"
    assert format_for_path("a.psb").key == "psd"
    assert format_for_path("a.unknown") is None and format_for_path("noext") is None
    png = format_for_path("x.png")
    assert format_for_filter(png.filter) is png
    assert png.filter in save_filter()


def test_formats_without_alpha_are_flattened_on_white(qapp):
    jpeg = next(f for f in FORMATS if f.key == "jpeg")
    flat = prepare_flat_image(_rgba(), jpeg)
    assert flat.pixelColor(0, 0) == QColor(255, 255, 255)
    assert flat.pixelColor(15, 10) == QColor(200, 40, 40)


def test_icons_are_scaled_to_the_format_limit(qapp):
    ico = next(f for f in FORMATS if f.key == "ico")
    assert max(prepare_flat_image(_rgba(600, 300), ico).width(), 0) == 256


@pytest.mark.parametrize("fmt", [f for f in FORMATS if f.writer == "qt"], ids=lambda f: f.key)
def test_every_available_flat_format_writes_a_readable_file(qapp, tmp_path, fmt):
    if fmt not in available_formats():
        pytest.skip(f"no Qt writer for {fmt.key} here")
    path = str(tmp_path / f"out.{fmt.default_extension}")
    write_flat_image(_rgba(), path, fmt, 90 if fmt.lossy else -1)
    reader = QImageReader(path)
    if not reader.canRead():
        pytest.skip(f"no Qt reader for {fmt.key} here")
    img = reader.read()
    assert not img.isNull(), reader.errorString()
    expected = (32, 32) if fmt.square_sizes else (40, 30)          # icns: a standard square
    assert (img.width(), img.height()) == expected


def test_png_keeps_transparency_and_jpeg_turns_it_white(qapp, tmp_path):
    png, jpeg = format_for_path("a.png"), format_for_path("a.jpg")
    write_flat_image(_rgba(), str(tmp_path / "a.png"), png)
    write_flat_image(_rgba(), str(tmp_path / "a.jpg"), jpeg, 95)
    assert QImage(str(tmp_path / "a.png")).pixelColor(0, 0).alpha() == 0
    c = QImage(str(tmp_path / "a.jpg")).pixelColor(0, 0)
    assert min(c.red(), c.green(), c.blue()) > 245


def test_quality_changes_the_file(qapp, tmp_path):
    jpeg = format_for_path("a.jpg")
    noisy = QImage(200, 200, QImage.Format.Format_RGB32)
    rng = np.random.default_rng(0)
    for y in range(0, 200, 2):
        for x in range(0, 200, 2):
            noisy.setPixel(x, y, int(rng.integers(0, 0xFFFFFF)))
    write_flat_image(noisy, str(tmp_path / "lo.jpg"), jpeg, 10)
    write_flat_image(noisy, str(tmp_path / "hi.jpg"), jpeg, 95)
    assert (tmp_path / "lo.jpg").stat().st_size < (tmp_path / "hi.jpg").stat().st_size


# ── Save As in the window ────────────────────────────────────────────────────

def _doc(w):
    w._add_tab(Document(40, 30), "t")
    w._document.layers[0].image.fill(QColor(10, 200, 10))
    return w._document


def test_save_as_adds_the_extension_of_the_chosen_format(main_window, mocked_dialogs, tmp_path, monkeypatch):
    w = main_window
    _doc(w)
    webp = format_for_path("x.webp")
    target = str(tmp_path / "picture")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, webp.filter)))
    import ui.export_quality_dialog as q
    monkeypatch.setattr(q, "ask_quality", lambda fmt, parent=None: 80)
    w._save_as()
    assert (tmp_path / "picture.webp").exists()
    assert w._filepath.endswith("picture.webp")


def test_cancelling_the_quality_dialog_saves_nothing(main_window, mocked_dialogs, tmp_path, monkeypatch):
    w = main_window
    _doc(w)
    target = str(tmp_path / "x.jpg")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    import ui.export_quality_dialog as q
    monkeypatch.setattr(q, "ask_quality", lambda fmt, parent=None: None)
    w._save_as()
    assert not (tmp_path / "x.jpg").exists()


def test_save_psd_reports_rasterized_and_skipped_layers(main_window, mocked_dialogs, tmp_path):
    w = main_window
    doc = _doc(w)
    t = doc.add_layer(name="T", layer_cls=TextLayer)
    t.text_data = {"text": "Hi", "x": 2, "y": 2, "font_size": 14}
    a = doc.add_layer(name="A", layer_cls=AdjustmentLayer)
    a.adjustment_data = {"type": "invert"}              # Photoshop has it: written
    h = doc.add_layer(name="H", layer_cls=AdjustmentLayer)
    h.adjustment_data = {"type": "hdr_toning"}          # it hasn't: skipped
    path = str(tmp_path / "x.psd")
    w._do_save(path)
    msg = w._status.currentMessage()
    assert "1" in msg and "PSD" in msg
    names = [l.name for l in PsdImporter(path).load().layers]
    assert names == ["Background", "T", "A"]


# ── PSD export ───────────────────────────────────────────────────────────────

def test_rle_encoder_round_trips(qapp):
    rng = np.random.default_rng(1)
    plane = rng.integers(0, 256, (6, 300), dtype=np.uint8)
    plane[2] = 7                                             # uniform row
    plane[4, :] = 0
    enc = _RleEncoder(psb=False).encode(plane)
    assert struct.unpack(">H", enc[:2])[0] == 1
    raw = _unpack_bits(memoryview(enc[2 + 6 * 2:]), plane.size)
    assert np.frombuffer(raw, np.uint8).reshape(plane.shape).tolist() == plane.tolist()


def _layered_doc():
    doc = Document(80, 60)
    doc.layers[0].image.fill(QColor(250, 250, 250))
    red = doc.add_layer("Красный ✨")
    red.image.fill(0)
    for x in range(10, 40):
        for y in range(10, 40):
            red.image.setPixelColor(x, y, QColor(220, 20, 20))
    red.opacity, red.blend_mode, red.clipping = 0.5, "Screen", False
    mask = QImage(80, 60, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(255, 255, 255))
    for y in range(60):
        for x in range(0, 20):
            mask.setPixelColor(x, y, QColor(0, 0, 0))
    red.mask = mask
    hidden = doc.add_layer("hidden")
    hidden.visible = False
    group = doc.add_layer("Group", layer_cls=GroupLayer)
    inner = doc.add_layer("inner")
    inner.image.fill(QColor(0, 0, 255, 128))
    inner.parent_id = group.layer_id
    inner.clipping = True
    doc.layers.remove(group)
    doc.layers.append(group)                                  # group above its child
    group.expanded = False
    return doc


def test_psd_export_round_trip(qapp, tmp_path):
    doc = _layered_doc()
    path = str(tmp_path / "out.psd")
    PsdExporter(doc).save(path)
    back = PsdImporter(path).load()
    names = [l.name for l in back.layers]
    assert names == ["Background", "Красный ✨", "hidden", "inner", "Group"]
    by = {l.name: l for l in back.layers}
    assert by["Красный ✨"].blend_mode == "Screen" and abs(by["Красный ✨"].opacity - 0.5) < 0.01
    assert by["Красный ✨"].mask.pixelColor(5, 5).green() == 0
    assert not by["hidden"].visible
    assert isinstance(by["Group"], GroupLayer) and not by["Group"].expanded
    assert by["inner"].parent_id == by["Group"].layer_id and by["inner"].clipping
    ours = np.frombuffer(doc.get_composite().constBits().asstring(80 * 60 * 4), np.uint8)
    theirs = np.frombuffer(back.get_composite().constBits().asstring(80 * 60 * 4), np.uint8)
    assert np.abs(ours.astype(int) - theirs.astype(int)).max() <= 2


def test_psd_merged_image_is_what_viewers_show(qapp, tmp_path):
    doc = _layered_doc()
    path = str(tmp_path / "m.psd")
    PsdExporter(doc).save(path)
    reader = QImageReader(path)
    if not reader.canRead():
        pytest.skip("no Qt PSD reader (kimageformats) here")
    merged = reader.read().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    comp = doc.get_composite()
    for x, y in ((30, 30), (5, 5), (70, 50)):
        assert merged.pixelColor(x, y) == comp.pixelColor(x, y)


def test_big_documents_become_psb(qapp, tmp_path):
    doc = Document(30001, 2)
    doc.layers[0].image.fill(QColor(1, 2, 3))
    exp = PsdExporter(doc)
    data = exp.to_bytes()
    assert exp.psb and struct.unpack(">H", data[4:6])[0] == 2
    path = tmp_path / "big.psb"
    path.write_bytes(data)
    back = PsdImporter(str(path)).load()
    assert back.width == 30001 and back.layers[0].image.pixelColor(30000, 1) == QColor(1, 2, 3)
