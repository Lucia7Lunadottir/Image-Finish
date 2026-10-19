"""Photoshop adjustment layers and layer effects in .psd files.

  * Adjustment layers read into our adjustment layers and are written back
    as Photoshop's (core/psd_adjustments.py) — they used to be skipped.
  * Layer effects read into layer styles, with Fill opacity
    (core/psd_effects.py) — they used to be dropped.
  * Rendering fixes found by comparing with Photoshop's own renders
    (psd-tools' test corpus): Threshold overflowed for green > 111,
    Posterize and per-channel Levels differed, the Stroke style was about
    twice its size and outside-only, a layer with a mask and styles crashed.

The block layouts were checked on files saved by Photoshop; these tests pin
them without needing those files."""
import struct

import numpy as np
import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage

from core.adjustments.registry import apply_adjustment, get_kind
from core.document import Document
from core.layer import AdjustmentLayer, RasterLayer
from core.layer_styles import apply_layer_styles, stroke_coverage
from core.psd_adjustments import DescriptorWriter, codec_for_type, lab_to_qcolor, rgb_descriptor
from core.psd_effects import layer_styles_from_effects
from core.psd_export import PsdExporter
from core.psd_import import PsdImporter, _DescriptorReader
from core.pixel_buffer import gray_mask_image
from test_psd_import import _tag, layer, load, psd, rgba_at


def _norm(data: dict) -> dict:
    kind = get_kind(data["type"])
    out = kind.normalize(data)
    return {k: (v.name() if isinstance(v, QColor) else v) for k, v in out.items()}


SAMPLES = [
    {"type": "brightness_contrast", "brightness": -40, "contrast": 25},
    {"type": "levels", "black": 10, "gamma": 1.3, "white": 240, "out_min": 5, "out_max": 250,
     "channels": {"r": {"black": 20, "gamma": 0.8, "white": 255, "out_min": 0, "out_max": 255}}},
    {"type": "curves", "points": {"rgb": [(0, 0), (90, 120), (255, 255)], "b": [(0, 10), (255, 240)]}},
    {"type": "exposure", "exposure": 1.25, "offset": -0.0625, "gamma": 1.5},
    {"type": "vibrance", "vibrance": 30, "saturation": -12},
    {"type": "hue_saturation", "hue": -40, "saturation": 25, "lightness": -10},
    {"type": "invert"},
    {"type": "posterize", "levels": 6},
    {"type": "threshold", "threshold": 140},
    {"type": "black_white", "reds": 40, "yellows": 60, "greens": 40, "cyans": 60, "blues": 20,
     "magentas": 80},
    {"type": "photo_filter", "color": QColor(236, 138, 0), "density": 40, "preserve": False},
    {"type": "channel_mixer", "red": [80, 20, 0], "green": [0, 100, 0], "blue": [10, 0, 90],
     "monochrome": False},
    {"type": "selective_color", "ranges": {"Reds": [10, -20, 30, 0], "Blacks": [0, 0, 0, 15]}},
    {"type": "gradient_map", "gradient": None, "reverse": True,
     "shadows": QColor(20, 0, 60), "highlights": QColor(255, 220, 120)},
]


# ── codecs ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", SAMPLES, ids=lambda d: d["type"])
def test_every_codec_writes_what_it_reads(qapp, data):
    codec = codec_for_type(data["type"])
    blocks = dict(codec.write(get_kind(data["type"]).normalize(data)))
    back = {"type": data["type"], **codec.read(blocks, None)}
    if data["type"] == "gradient_map":                  # stored as a full gradient
        assert apply_adjustment(_ramp(), back) == apply_adjustment(_ramp(), data)
    else:
        assert _norm(back) == _norm(data)


def _ramp() -> QImage:
    img = QImage(256, 1, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(256):
        img.setPixelColor(x, 0, QColor(x, 255 - x, x // 2))
    return img


def test_brightness_prefers_photoshops_modern_values(qapp):
    codec = codec_for_type("brightness_contrast")
    legacy = struct.pack(">hhHBx", 5, 5, 127, 0)
    cged = DescriptorWriter.block("null", {"Brgh": ("long", -95), "Cntr": ("long", 150)})
    assert codec.read({b"brit": legacy}, None) == {"brightness": 5, "contrast": 5}
    assert codec.read({b"brit": legacy, b"CgEd": cged}, None) == {"brightness": -95, "contrast": 100}


def test_curves_points_are_stored_output_first(qapp):
    # Photoshop: bitmap 0b1001 = composite + blue; each point (output, input)
    data = struct.pack(">BHI", 0, 1, 0b1001)
    data += struct.pack(">H", 2) + struct.pack(">2H", 0, 0) + struct.pack(">2H", 200, 255)
    data += struct.pack(">H", 2) + struct.pack(">2H", 30, 0) + struct.pack(">2H", 255, 255)
    p = codec_for_type("curves").read({b"curv": data}, None)
    assert p == {"points": {"rgb": [(0, 0), (255, 200)], "b": [(0, 30), (255, 255)]}}


def test_photo_filter_lab_colour(qapp):
    # Photoshop's own file: Lab 67.06 / 32 / 120 (orange)
    data = bytes.fromhex("000200071a320c802ee000000000001901000000")
    p = codec_for_type("photo_filter").read({b"phfl": data}, None)
    c = p["color"]
    assert p["density"] == 25 and p["preserve"]
    assert c.red() > 200 and 100 < c.green() < 190 and c.blue() < 40
    assert lab_to_qcolor(100, 0, 0) == QColor(255, 255, 255)
    assert lab_to_qcolor(0, 0, 0) == QColor(0, 0, 0)


def test_descriptor_writer_reads_back(qapp):
    raw = DescriptorWriter.block("null", {"vibrance": ("long", -6), "useTint": ("bool", True),
                                          "Clr ": rgb_descriptor(QColor(1, 2, 3)),
                                          "Md  ": ("enum", ("BlnM", "Mltp"))})
    d = _DescriptorReader(raw[4:]).read()
    assert d["vibrance"] == -6 and d["useTint"] is True
    assert (d["Clr "]["Rd  "], d["Clr "]["Bl  "]) == (1, 3)
    assert d["Md  "] == ("BlnM", "Mltp")


# ── import / export ──────────────────────────────────────────────────────────

def test_adjustment_layer_is_imported_with_its_mask(qapp, tmp_path):
    mask = ((0, 0, 2, 1), 0, False, np.full((2, 1), 255, np.uint8))
    thrs = layer("Threshold 1", mask=mask, tags=_tag(b"thrs", struct.pack(">H2x", 140)))
    base = layer("bg", (0, 0, 2, 2), {0: np.full((2, 2), 200, np.uint8),
                                      1: np.full((2, 2), 200, np.uint8),
                                      2: np.full((2, 2), 200, np.uint8)})
    doc, importer = load(tmp_path, psd(2, 2, [base, thrs]))
    assert importer.skipped_layers == 0
    adj = doc.layers[1]
    assert isinstance(adj, AdjustmentLayer) and adj.name == "Threshold 1"
    assert adj.adjustment_data == {"type": "threshold", "threshold": 140}
    img = doc.get_composite()
    assert rgba_at(img, 0, 0)[:3] == (255, 255, 255)      # under the mask: thresholded
    assert rgba_at(img, 1, 0)[:3] == (200, 200, 200)      # masked out


def test_unknown_adjustment_is_still_skipped_and_counted(qapp, tmp_path):
    blnc = layer("Color Balance 1", tags=_tag(b"blnc", b"\0" * 20))
    _doc, importer = load(tmp_path, psd(1, 1, [blnc]))
    assert importer.skipped_layers == 1


@pytest.mark.parametrize("data", SAMPLES, ids=lambda d: d["type"])
def test_adjustment_layers_survive_a_psd_round_trip(qapp, tmp_path, data):
    doc = Document(4, 4)
    adj = doc.add_layer("Adj", layer_cls=AdjustmentLayer)
    adj.adjustment_data = dict(data)
    adj.opacity, adj.clipping = 0.5, True
    m = np.zeros((4, 4), np.float32)
    m[:, :2] = 1
    adj.mask = gray_mask_image(m)
    exporter = PsdExporter(doc)
    path = tmp_path / "a.psd"
    exporter.save(str(path))
    assert exporter.skipped == 0
    back = PsdImporter(str(path)).load()
    got = [l for l in back.layers if isinstance(l, AdjustmentLayer)]
    assert len(got) == 1
    g = got[0]
    assert g.name == "Adj" and g.clipping and abs(g.opacity - 0.5) < 0.01
    assert g.mask.pixelColor(0, 0).red() == 255 and g.mask.pixelColor(3, 0).red() == 0
    if data["type"] != "gradient_map":
        assert _norm(g.adjustment_data) == _norm(data)


def test_adjustment_without_photoshop_counterpart_is_skipped_on_export(qapp, tmp_path):
    doc = Document(4, 4)
    doc.add_layer("HDR", layer_cls=AdjustmentLayer).adjustment_data = {"type": "hdr_toning"}
    exporter = PsdExporter(doc)
    exporter.to_bytes()
    assert exporter.skipped == 1


# ── rendering fixes ──────────────────────────────────────────────────────────

def _one_pixel(color: QColor) -> QImage:
    img = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    img.setPixelColor(0, 0, color)
    return img


def test_threshold_of_a_bright_green_pixel(qapp):
    # luma(60, 200, 60) = 141; 587 * 200 overflowed 16 bits -> came out black
    out = apply_adjustment(_one_pixel(QColor(60, 200, 60)), {"type": "threshold", "threshold": 128})
    assert out.pixelColor(0, 0) == QColor(255, 255, 255)


@pytest.mark.parametrize("value, levels, expected", [(100, 3, 127), (170, 3, 127), (171, 3, 255),
                                                     (63, 4, 0), (64, 4, 85)])
def test_posterize_bands_like_photoshop(qapp, value, levels, expected):
    out = apply_adjustment(_one_pixel(QColor(value, value, value)), {"type": "posterize", "levels": levels})
    assert abs(out.pixelColor(0, 0).red() - expected) <= 1


def test_channel_levels_apply_before_the_composite(qapp):
    data = {"type": "levels", "black": 0, "gamma": 1.0, "white": 128, "out_min": 0, "out_max": 255,
            "channels": {"r": {"black": 0, "gamma": 1.0, "white": 255, "out_min": 0, "out_max": 128}}}
    out = apply_adjustment(_one_pixel(QColor(200, 200, 200)), data)
    # red: 200 -> 100 (channel) -> 199 (composite); the other way it'd be 128
    assert abs(out.pixelColor(0, 0).red() - 199) <= 1
    assert out.pixelColor(0, 0).green() == 255


def _square(size=40, inset=10) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    for y in range(inset, size - inset):
        for x in range(inset, size - inset):
            img.setPixelColor(x, y, QColor(0, 0, 255))
    return img


def _ring_width(position: str, size: float) -> int:
    alpha = np.zeros((40, 40), np.uint8)
    alpha[10:30, 10:30] = 255
    cov = stroke_coverage(alpha, size, position)
    row = cov[20]
    return int((row > 127).sum() // 2)


@pytest.mark.parametrize("position, size, width", [("outside", 3, 3), ("inside", 4, 4),
                                                    ("center", 4, 4), ("outside", 1, 1)])
def test_stroke_is_as_wide_as_its_size(position, size, width):
    assert _ring_width(position, size) == width


def test_outside_stroke_at_zero_fill_is_only_the_outline(qapp):
    styles = {"stroke": {"enabled": True, "size": 2, "color": QColor(255, 0, 0), "opacity": 100,
                         "position": "outside"}, "fill_opacity": 0}
    out, delta = apply_layer_styles(_square(), styles)
    at = lambda x, y: out.pixelColor(x - delta.x(), y - delta.y())
    assert at(20, 20).alpha() == 0                         # the fill is gone
    assert at(9, 20) == QColor(255, 0, 0)                   # the stroke stays


def test_layer_with_mask_and_styles_renders(qapp):
    """Crashed: the styles pad the image, the mask kept its size."""
    doc = Document(40, 40)
    lay = doc.layers[0]
    lay.image = _square()
    m = np.ones((40, 40), np.float32)
    m[:, 20:] = 0
    lay.mask = gray_mask_image(m)
    lay.layer_styles = {"drop_shadow": {"enabled": True, "distance": 3, "size": 2, "angle": 90,
                                        "color": QColor(0, 0, 0), "opacity": 75}}
    img = doc.get_composite()
    assert img.pixelColor(15, 20) == QColor(0, 0, 255)
    assert img.pixelColor(25, 20).alpha() == 0              # masked, shadow included


# ── layer effects ────────────────────────────────────────────────────────────

def _rgb(clr):
    return (int(clr.get("Rd  ", 0)), int(clr.get("Grn ", 0)), int(clr.get("Bl  ", 0)))


def test_effects_become_layer_styles(qapp):
    desc = {
        "masterFXSwitch": True,
        "dropShadowMulti": [{"enab": False}, {"enab": True, "Md  ": ("BlnM", "multiply"),
                                              "Clr ": {"_class": "RGBC", "Rd  ": 10.0, "Grn ": 20.0, "Bl  ": 30.0},
                                              "Opct": 35.0, "uglg": True, "lagl": 90.0, "Dstn": 18.0, "blur": 41.0}],
        "FrFX": {"enab": True, "Styl": ("FStl", "InsF"), "Md  ": ("BlnM", "Nrml"), "Opct": 100.0,
                 "Sz  ": 6.0, "Clr ": {"_class": "RGBC", "Rd  ": 255.0, "Grn ": 0.0, "Bl  ": 0.0}},
        "SoFi": {"enab": False, "Clr ": {"_class": "RGBC"}},
    }
    styles = layer_styles_from_effects(desc, 120, _rgb)
    assert set(styles) == {"drop_shadow", "stroke"}
    ds = styles["drop_shadow"]
    assert ds["color"] == QColor(10, 20, 30) and ds["blend_mode"] == "Multiply"
    assert (ds["angle"], ds["distance"], ds["size"], ds["opacity"]) == (120, 18, 41, 35)
    st = styles["stroke"]
    assert (st["position"], st["size"], st["color"]) == ("inside", 6, QColor(255, 0, 0))


def test_effects_switched_off_as_a_whole(qapp):
    desc = {"masterFXSwitch": False, "SoFi": {"enab": True, "Clr ": {"_class": "RGBC"}}}
    assert layer_styles_from_effects(desc, 120, _rgb) == {}


def test_fill_opacity_goes_to_the_styles_when_there_are_effects(qapp):
    class _Rec:
        name, visible, blend_key, section_blend_key = "L", True, b"norm", None
        opacity, fill_opacity = 255, 0
        effects = {"FrFX": {"enab": True, "Sz  ": 3.0, "Clr ": {"_class": "RGBC", "Rd  ": 255.0}}}

    class _Psd:
        global_angle = 120

        @staticmethod
        def descriptor_rgb(clr):
            return _rgb(clr)

    importer = PsdImporter("unused")
    importer._psd = _Psd()
    lay = RasterLayer("x", 4, 4)
    importer._copy_common(_Rec(), lay)
    assert lay.opacity == 1.0 and lay.layer_styles["fill_opacity"] == 0
    _Rec.effects = None
    plain = RasterLayer("y", 4, 4)
    importer._copy_common(_Rec(), plain)
    assert plain.opacity == 0.0 and not plain.layer_styles
