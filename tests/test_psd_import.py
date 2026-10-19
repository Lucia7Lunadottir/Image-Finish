"""core/psd_import.py — the Photoshop .psd/.psb reader.

The PSD files here are built byte by byte by the small writer below, so the
tests need no PSD library (the app has none either) and each one pins one
part of the format."""
import struct

import numpy as np
import pytest
from PyQt6.QtGui import QColorSpace, QImage

from core.layer import GroupLayer, RasterLayer
from core.psd_import import PsdFormatError, PsdImporter


# ── a minimal PSD writer ─────────────────────────────────────────────────────

def _packbits_row(row: bytes) -> bytes:
    """PackBits: repeat runs for a uniform row, literal runs otherwise."""
    out = bytearray()
    if len(set(row)) == 1:
        for i in range(0, len(row), 128):
            n = min(128, len(row) - i)
            out += bytes([257 - n if n > 1 else 0, row[0]])
    else:
        for i in range(0, len(row), 128):
            chunk = row[i:i + 128]
            out += bytes([len(chunk) - 1]) + chunk
    return bytes(out)


def _channel(plane: np.ndarray, compression: int, psb: bool) -> bytes:
    """One channel's data: compression word + payload."""
    raw = plane.astype(">u2").tobytes() if plane.dtype == np.uint16 else plane.astype(np.uint8).tobytes()
    if compression == 0:
        return struct.pack(">H", 0) + raw
    h = plane.shape[0]
    row_len = len(raw) // h
    rows = [_packbits_row(raw[i * row_len:(i + 1) * row_len]) for i in range(h)]
    counts = b"".join(struct.pack(">I" if psb else ">H", len(r)) for r in rows)
    return struct.pack(">H", 1) + counts + b"".join(rows)


def _tag(key: bytes, data: bytes) -> bytes:
    data += b"\0" * (len(data) % 2)
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def _unicode_name(name: str) -> bytes:
    return _tag(b"luni", struct.pack(">I", len(name)) + name.encode("utf-16-be"))


def _section(kind: int, blend: bytes | None = None) -> bytes:
    data = struct.pack(">I", kind)
    if blend:
        data += b"8BIM" + blend
    return _tag(b"lsct", data)


def layer(name, rect=(0, 0, 0, 0), planes=None, *, blend=b"norm", opacity=255,
          clipping=False, hidden=False, mask=None, tags=b"", compression=0):
    """planes: {channel id: 2-D array} covering `rect` (top, left, bottom, right).
    mask: (rect, default colour, disabled, 2-D array)."""
    return dict(name=name, rect=rect, planes=planes or {}, blend=blend, opacity=opacity,
                clipping=clipping, hidden=hidden, mask=mask, tags=tags, compression=compression)


def group_start():
    return layer("</Layer group>", tags=_section(3))


def group_end(name, *, closed=False, blend=b"pass", **kw):
    return layer(name, tags=_section(2 if closed else 1, blend) + _unicode_name(name), **kw)


def _record(lay: dict, psb: bool) -> tuple[bytes, bytes]:
    t, l, b, r = lay["rect"]
    planes = dict(lay["planes"])
    if lay["mask"] is not None:
        planes[-2] = lay["mask"][3]
    datas = {cid: _channel(p, lay["compression"], psb) for cid, p in planes.items()}
    head = struct.pack(">4iH", t, l, b, r, len(datas))
    for cid, d in datas.items():
        head += struct.pack(">h", cid) + struct.pack(">Q" if psb else ">I", len(d))
    head += b"8BIM" + lay["blend"] + struct.pack(">BBBB", lay["opacity"], int(lay["clipping"]),
                                                  0x02 if lay["hidden"] else 0, 0)
    extra = b""
    if lay["mask"] is not None:
        (mt, ml, mb, mr), default, disabled, _ = lay["mask"]
        extra += struct.pack(">I4iBB2x", 20, mt, ml, mb, mr, default, 0x02 if disabled else 0)
    else:
        extra += struct.pack(">I", 0)
    extra += struct.pack(">I", 0)                                    # blending ranges
    name = lay["name"].encode("latin-1", "replace")[:255]
    pascal = bytes([len(name)]) + name
    extra += pascal + b"\0" * ((4 - len(pascal) % 4) % 4)
    extra += lay["tags"]
    return head + struct.pack(">I", len(extra)) + extra, b"".join(datas.values())


def psd(width, height, layers=(), *, channels=3, depth=8, mode=3, version=1,
        merged=None, icc=None, layers_in_block=False) -> bytes:
    """A whole file. `merged`: list of 2-D planes for the flattened image."""
    psb = version == 2
    out = b"8BPS" + struct.pack(">H6xHIIHH", version, channels, height, width, depth, mode)
    out += struct.pack(">I", 0)                                      # colour mode data
    resources = b""
    if icc:
        resources = b"8BIM" + struct.pack(">H", 1039) + b"\0\0" + struct.pack(">I", len(icc)) + icc
        resources += b"\0" * (len(icc) % 2)
    out += struct.pack(">I", len(resources)) + resources

    records, data = b"", b""
    for lay in layers:
        rec, d = _record(lay, psb)
        records += rec
        data += d
    info = struct.pack(">h", len(layers)) + records + data if layers else b""
    length = struct.pack(">Q" if psb else ">I", len(info))
    if layers_in_block:
        section = struct.pack(">Q" if psb else ">I", 0) + struct.pack(">I", 0)
        section += b"8BIM" + b"Lr16" + (struct.pack(">Q", len(info)) if psb else struct.pack(">I", len(info))) + info
    else:
        section = length + info + struct.pack(">I", 0)              # + global mask info
    out += struct.pack(">Q" if psb else ">I", len(section)) + section

    planes = merged or [np.zeros((height, width), np.uint8)] * channels
    out += struct.pack(">H", 0) + b"".join(
        p.astype(">u2").tobytes() if depth == 16 else p.astype(np.uint8).tobytes() for p in planes)
    return out


def solid(h, w, value, dtype=np.uint8):
    return np.full((h, w), value, dtype)


def rgb_planes(h, w, r, g, b, a=None):
    p = {0: solid(h, w, r), 1: solid(h, w, g), 2: solid(h, w, b)}
    if a is not None:
        p[-1] = solid(h, w, a)
    return p


# ── descriptors (fill layer settings) ────────────────────────────────────────

def _key(k: str) -> bytes:
    kb = k.encode("latin-1")
    return struct.pack(">I", 0) + kb if len(kb) == 4 else struct.pack(">I", len(kb)) + kb


def _value(v) -> bytes:
    kind = v[0]
    if kind == "doub":
        return b"doub" + struct.pack(">d", v[1])
    if kind == "UntF":
        return b"UntF" + v[1] + struct.pack(">d", v[2])
    if kind == "long":
        return b"long" + struct.pack(">i", v[1])
    if kind == "bool":
        return b"bool" + bytes([int(v[1])])
    if kind == "enum":
        return b"enum" + _key(v[1]) + _key(v[2])
    if kind == "Objc":
        return b"Objc" + descriptor(v[1], v[2])
    if kind == "VlLs":
        return b"VlLs" + struct.pack(">I", len(v[1])) + b"".join(_value(x) for x in v[1])
    raise ValueError(kind)


def descriptor(cls: str, items: dict) -> bytes:
    out = struct.pack(">I", 0) + _key(cls) + struct.pack(">I", len(items))
    for k, v in items.items():
        out += _key(k) + _value(v)
    return out


def rgb_color(r, g, b):
    return ("Objc", "RGBC", {"Rd  ": ("doub", r), "Grn ": ("doub", g), "Bl  ": ("doub", b)})


def solid_fill_tag(r, g, b) -> bytes:
    return _tag(b"SoCo", struct.pack(">I", 16) + descriptor("null", {"Clr ": rgb_color(r, g, b)}))


def gradient_fill_tag(c0, c1, *, angle=0.0, kind="Lnr ", method=None) -> bytes:
    def stop(c, loc):
        return ("Objc", "Clrt", {"Clr ": rgb_color(*c), "Type": ("enum", "Clry", "UsrS"),
                                 "Lctn": ("long", loc), "Mdpn": ("long", 50)})
    grad = {"GrdF": ("enum", "GrdF", "CstS"), "Intr": ("doub", 4096.0),
            "Clrs": ("VlLs", [stop(c0, 0), stop(c1, 4096)]),
            "Trns": ("VlLs", [("Objc", "TrnS", {"Opct": ("UntF", b"#Prc", 100.0),
                                                "Lctn": ("long", loc), "Mdpn": ("long", 50)})
                              for loc in (0, 4096)])}
    items = {"Angl": ("UntF", b"#Ang", angle), "Type": ("enum", "GrdT", kind),
             "Grad": ("Objc", "Grdn", grad)}
    if method:
        items["gradientsInterpolationMethod"] = ("enum", "gradientInterpolationMethodType", method)
    return _tag(b"GdFl", struct.pack(">I", 16) + descriptor("null", items))


def vector_rect_tag(width, height, rect, *, closed=True) -> bytes:
    """A vector mask: one rectangle subpath (top, left, bottom, right in px)."""
    t, l, b, r = rect

    def fixed(v, size):
        return int(round(v / size * 0x1000000))
    data = struct.pack(">II", 3, 0)
    data += struct.pack(">HH22x", 8, 0)                              # initial fill rule
    data += struct.pack(">HHh20x", 0 if closed else 3, 4, 1)         # subpath length, union
    for y, x in ((t, l), (t, r), (b, r), (b, l)):
        pt = struct.pack(">ii", fixed(y, height), fixed(x, width))
        data += struct.pack(">H", 1 if closed else 4) + pt * 3
    return _tag(b"vmsk", data)


# ── helpers ──────────────────────────────────────────────────────────────────

def load(tmp_path, data: bytes, name="t.psd"):
    path = tmp_path / name
    path.write_bytes(data)
    importer = PsdImporter(str(path))
    return importer.load(), importer


def rgba_at(img: QImage, x, y):
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue(), c.alpha()


# ── tests ────────────────────────────────────────────────────────────────────

def test_layers_keep_psd_stack_order_bottom_to_top(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(8, 8, [
        layer("bottom", (0, 0, 8, 8), rgb_planes(8, 8, 255, 0, 0)),
        layer("top", (2, 2, 4, 4), rgb_planes(2, 2, 0, 0, 255)),
    ]))
    assert [l.name for l in doc.layers] == ["bottom", "top"]
    assert doc.active_layer_index == 1
    assert rgba_at(doc.layers[0].image, 0, 0) == (255, 0, 0, 255)
    top = doc.layers[1].image
    assert rgba_at(top, 2, 2) == (0, 0, 255, 255)
    assert rgba_at(top, 0, 0)[3] == 0          # outside its rect: transparent


def test_groups_keep_their_children_and_nesting(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(4, 4, [
        layer("background", (0, 0, 4, 4), rgb_planes(4, 4, 9, 9, 9)),
        group_start(),
        layer("inner child", (0, 0, 1, 1), rgb_planes(1, 1, 1, 2, 3)),
        group_start(),
        layer("deep child", (0, 0, 1, 1), rgb_planes(1, 1, 4, 5, 6)),
        group_end("Inner", closed=True),
        group_end("Outer", opacity=128, hidden=True),
    ]))
    names = [l.name for l in doc.layers]
    assert names == ["background", "inner child", "deep child", "Inner", "Outer"]
    by_name = {l.name: l for l in doc.layers}
    outer, inner = by_name["Outer"], by_name["Inner"]
    assert isinstance(outer, GroupLayer) and isinstance(inner, GroupLayer)
    assert by_name["background"].parent_id is None
    assert outer.parent_id is None
    assert by_name["inner child"].parent_id == outer.layer_id
    assert inner.parent_id == outer.layer_id
    assert by_name["deep child"].parent_id == inner.layer_id
    assert outer.expanded and not inner.expanded
    assert not outer.visible and outer.opacity == pytest.approx(128 / 255)
    assert outer.blend_mode == "SourceOver"    # Pass Through opens as Normal


def test_group_without_closing_record_is_kept(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(2, 2, [
        group_start(),
        layer("orphan", (0, 0, 1, 1), rgb_planes(1, 1, 1, 1, 1)),
    ]))
    orphan, group = doc.layers
    assert isinstance(group, GroupLayer)
    assert orphan.parent_id == group.layer_id


def test_visibility_opacity_blend_and_clipping(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(2, 2, [
        layer("base", (0, 0, 2, 2), rgb_planes(2, 2, 10, 10, 10)),
        layer("clipped", (0, 0, 2, 2), rgb_planes(2, 2, 20, 20, 20), blend=b"mul ",
              opacity=128, clipping=True, hidden=True,
              tags=_tag(b"iOpa", bytes([128]))),
        layer("unknown blend", (0, 0, 2, 2), rgb_planes(2, 2, 30, 30, 30), blend=b"lbrn"),
    ]))
    base, clipped, unknown = doc.layers
    assert base.visible and not base.clipping
    assert not clipped.visible and clipped.clipping
    assert clipped.blend_mode == "Multiply"
    # opacity x fill opacity (no layer effects are imported)
    assert clipped.opacity == pytest.approx((128 / 255) ** 2)
    assert unknown.blend_mode == "SourceOver"


@pytest.mark.parametrize("key, expected", [
    (b"scrn", "Screen"), (b"over", "Overlay"), (b"dark", "Darken"), (b"lite", "Lighten"),
    (b"div ", "ColorDodge"), (b"idiv", "ColorBurn"), (b"hLit", "HardLight"),
    (b"sLit", "SoftLight"), (b"diff", "Difference"), (b"smud", "Exclusion"),
])
def test_blend_mode_keys(qapp, tmp_path, key, expected):
    doc, _ = load(tmp_path, psd(1, 1, [layer("l", (0, 0, 1, 1), rgb_planes(1, 1, 0, 0, 0), blend=key)]))
    assert doc.layers[0].blend_mode == expected


def test_unicode_name_wins_over_pascal_name(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(1, 1, [
        layer("Layer 1", (0, 0, 1, 1), rgb_planes(1, 1, 0, 0, 0), tags=_unicode_name("Фон ✨")),
    ]))
    assert doc.layers[0].name == "Фон ✨"


def test_alpha_channel_and_layer_mask(qapp, tmp_path):
    mask_data = np.array([[0, 255], [128, 255]], np.uint8)
    doc, _ = load(tmp_path, psd(4, 4, [
        layer("masked", (0, 0, 4, 4), rgb_planes(4, 4, 200, 100, 50, a=128),
              mask=((1, 1, 3, 3), 255, False, mask_data)),
        layer("mask off", (0, 0, 4, 4), rgb_planes(4, 4, 1, 1, 1),
              mask=((0, 0, 1, 1), 0, True, np.zeros((1, 1), np.uint8))),
    ]))
    masked, off = doc.layers
    assert rgba_at(masked.image, 0, 0)[3] == 128
    m = masked.mask
    assert m.pixelColor(0, 0).green() == 255       # outside the mask rect: default colour
    assert m.pixelColor(1, 1).green() == 0
    assert m.pixelColor(1, 2).green() == 128
    assert m.pixelColor(2, 1).green() == 255
    assert masked.mask_enabled
    assert off.mask is not None and not off.mask_enabled
    assert off.mask.pixelColor(3, 3).green() == 0


def test_rle_compressed_channels(qapp, tmp_path):
    gradient = np.tile(np.arange(0, 200, 10, dtype=np.uint8), (3, 1))   # literal runs
    doc, _ = load(tmp_path, psd(20, 3, [
        layer("rle", (0, 0, 3, 20), {0: gradient, 1: solid(3, 20, 7), 2: solid(3, 20, 9)},
              compression=1),
    ]))
    img = doc.layers[0].image
    assert [rgba_at(img, x, 1)[0] for x in (0, 5, 19)] == [0, 50, 190]
    assert rgba_at(img, 4, 2)[1:3] == (7, 9)


def test_psb_large_document_format(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(3, 2, [
        layer("psb layer", (0, 0, 2, 3), rgb_planes(2, 3, 11, 22, 33), compression=1),
    ], version=2), name="t.psb")
    assert rgba_at(doc.layers[0].image, 2, 1) == (11, 22, 33, 255)


def test_16_bit_layers_from_lr16_block(qapp, tmp_path):
    planes = {0: solid(2, 2, 65535, np.uint16), 1: solid(2, 2, 32768, np.uint16),
              2: solid(2, 2, 0, np.uint16)}
    doc, _ = load(tmp_path, psd(2, 2, [layer("deep", (0, 0, 2, 2), planes)],
                                depth=16, layers_in_block=True))
    assert doc.layers[0].name == "deep"
    assert rgba_at(doc.layers[0].image, 1, 1) == (255, 128, 0, 255)


def test_flat_file_opens_merged_image(qapp, tmp_path):
    merged = [solid(2, 3, 40), solid(2, 3, 50), solid(2, 3, 60)]
    doc, _ = load(tmp_path, psd(3, 2, merged=merged))
    assert len(doc.layers) == 1 and isinstance(doc.layers[0], RasterLayer)
    assert rgba_at(doc.layers[0].image, 2, 1) == (40, 50, 60, 255)


def test_only_adjustment_layers_falls_back_to_merged_and_counts_them(qapp, tmp_path):
    curves = layer("Curves 1", tags=_tag(b"curv", b"\0" * 8))
    merged = [solid(1, 1, 1), solid(1, 1, 2), solid(1, 1, 3)]
    doc, importer = load(tmp_path, psd(1, 1, [curves], merged=merged))
    assert importer.skipped_layers == 1
    assert rgba_at(doc.layers[0].image, 0, 0) == (1, 2, 3, 255)


def test_grayscale_and_cmyk_without_profile(qapp, tmp_path):
    gray, _ = load(tmp_path, psd(1, 1, [layer("g", (0, 0, 1, 1), {0: solid(1, 1, 77)})],
                                 channels=1, mode=1), name="g.psd")
    assert rgba_at(gray.layers[0].image, 0, 0) == (77, 77, 77, 255)
    # PSD stores CMYK inverted: 255 = no ink. Here: no C, full M, no Y, no K.
    cmyk_planes = {0: solid(1, 1, 255), 1: solid(1, 1, 0), 2: solid(1, 1, 255), 3: solid(1, 1, 255)}
    cmyk, _ = load(tmp_path, psd(1, 1, [layer("c", (0, 0, 1, 1), cmyk_planes)],
                                 channels=4, mode=4), name="c.psd")
    assert rgba_at(cmyk.layers[0].image, 0, 0) == (255, 0, 255, 255)


def test_embedded_icc_profile_is_applied(qapp, tmp_path):
    icc = bytes(QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb).iccProfile())
    doc, _ = load(tmp_path, psd(1, 1, [layer("a", (0, 0, 1, 1), rgb_planes(1, 1, 0, 128, 0))],
                                icc=icc))
    expected = QImage(1, 1, QImage.Format.Format_RGB888)
    expected.fill(0)
    expected.setPixelColor(0, 0, expected.pixelColor(0, 0).fromRgb(0, 128, 0))
    expected.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb))
    expected = expected.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    got = rgba_at(doc.layers[0].image, 0, 0)
    assert got[:3] == rgba_at(expected, 0, 0)[:3]
    assert got[:3] != (0, 128, 0)


def test_solid_fill_shape_without_pixels_is_painted_from_its_vector_mask(qapp, tmp_path):
    tags = solid_fill_tag(0, 128, 255) + vector_rect_tag(10, 10, (2, 2, 8, 8))
    doc, importer = load(tmp_path, psd(10, 10, [layer("Rectangle 1", tags=tags)]))
    assert importer.skipped_layers == 0
    img = doc.layers[0].image
    assert rgba_at(img, 5, 5) == (0, 128, 255, 255)
    assert rgba_at(img, 0, 0)[3] == 0
    assert rgba_at(img, 9, 5)[3] == 0
    assert doc.layers[0].vector_mask is None     # already painted into the pixels


def test_open_vector_path_is_filled_as_if_closed(qapp, tmp_path):
    tags = solid_fill_tag(255, 0, 0) + vector_rect_tag(10, 10, (2, 2, 8, 8), closed=False)
    doc, _ = load(tmp_path, psd(10, 10, [layer("Shape", tags=tags)]))
    assert rgba_at(doc.layers[0].image, 5, 5) == (255, 0, 0, 255)


def test_colour_fill_without_mask_covers_the_canvas(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(3, 3, [layer("Color Fill 1", (0, 0, 3, 3), tags=solid_fill_tag(1, 2, 3))]))
    assert rgba_at(doc.layers[0].image, 2, 2) == (1, 2, 3, 255)


def test_vector_mask_on_a_pixel_layer_is_kept_as_vector_mask(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(10, 10, [
        layer("photo", (0, 0, 10, 10), rgb_planes(10, 10, 9, 9, 9), tags=vector_rect_tag(10, 10, (0, 0, 5, 5))),
    ]))
    vm = doc.layers[0].vector_mask
    assert vm is not None and vm.boundingRect().width() == pytest.approx(5, abs=0.01)
    assert rgba_at(doc.layers[0].image, 8, 8) == (9, 9, 9, 255)   # pixels untouched


def test_linear_gradient_fill(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(101, 3, [layer("Gradient Fill 1", (0, 0, 3, 101),
                                              tags=gradient_fill_tag((0, 0, 0), (255, 255, 255)))]))
    img = doc.layers[0].image
    left, mid, right = (rgba_at(img, x, 1)[0] for x in (0, 50, 100))
    assert left < 5 and right > 250
    assert abs(mid - 128) <= 3


def test_linear_light_gradient_interpolation(qapp, tmp_path):
    classic, _ = load(tmp_path, psd(101, 1, [layer("g", tags=gradient_fill_tag((0, 0, 0), (255, 255, 255)))]),
                      name="a.psd")
    linear, _ = load(tmp_path, psd(101, 1, [layer("g", tags=gradient_fill_tag(
        (0, 0, 0), (255, 255, 255), method="Lnr "))]), name="b.psd")
    # half way in linear light is ~188 in sRGB, not 128
    assert abs(rgba_at(linear.layers[0].image, 50, 0)[0] - 188) <= 3
    assert rgba_at(classic.layers[0].image, 50, 0)[0] < 135


def test_gradient_angle_90_runs_bottom_to_top(qapp, tmp_path):
    doc, _ = load(tmp_path, psd(3, 101, [layer("g", tags=gradient_fill_tag((0, 0, 0), (255, 255, 255), angle=90.0))]))
    img = doc.layers[0].image
    assert rgba_at(img, 1, 100)[0] < 5 and rgba_at(img, 1, 0)[0] > 250


def test_pattern_fill_without_pixels_is_skipped_and_counted(qapp, tmp_path):
    doc, importer = load(tmp_path, psd(2, 2, [
        layer("bg", (0, 0, 2, 2), rgb_planes(2, 2, 5, 5, 5)),
        layer("Pattern Fill 1", tags=_tag(b"PtFl", b"\0" * 8)),
    ]))
    assert [l.name for l in doc.layers] == ["bg"]
    assert importer.skipped_layers == 1


def test_not_a_psd_raises(qapp, tmp_path):
    with pytest.raises(PsdFormatError):
        load(tmp_path, b"\x89PNG\r\n\x1a\n" + b"\0" * 40)


def test_truncated_layer_section_falls_back_to_merged(qapp, tmp_path):
    data = psd(2, 2, [layer("l", (0, 0, 2, 2), rgb_planes(2, 2, 1, 1, 1))],
               merged=[solid(2, 2, 7)] * 3)
    head = data[:26 + 4 + 4]
    section_len = struct.unpack(">I", data[34:38])[0]
    broken_section = struct.pack(">I", 0xFFFF) + b"\0" * 6   # layer info claims more than exists
    rest = data[38 + section_len:]
    doc, _ = load(tmp_path, head + struct.pack(">I", len(broken_section)) + broken_section + rest)
    assert rgba_at(doc.layers[0].image, 1, 1) == (7, 7, 7, 255)


# ── main window ──────────────────────────────────────────────────────────────

def test_open_psd_in_main_window_and_save_writes_psd(main_window, mocked_dialogs, tmp_path):
    """Ctrl+S on an opened PSD writes the PSD back (with its layers), as
    in Photoshop — it used to be import-only (Save As .imfn)."""
    path = tmp_path / "art.psd"
    path.write_bytes(psd(4, 4, [layer("only", (0, 0, 4, 4), rgb_planes(4, 4, 1, 2, 3)),
                                layer("second", (0, 0, 2, 2), rgb_planes(2, 2, 9, 9, 9))]))
    main_window._open_file_path(str(path))
    assert [l.name for l in main_window._document.layers] == ["only", "second"]
    main_window._document.layers[1].name = "renamed"
    main_window._save()
    doc, _ = load(tmp_path, path.read_bytes(), name="again.psd")
    assert [l.name for l in doc.layers] == ["only", "renamed"]
