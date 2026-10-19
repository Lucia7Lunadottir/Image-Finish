"""Photoshop adjustment layers <-> our adjustment layers
(core/adjustments/registry.py), for core/psd_import.py and core/psd_export.py.

One codec class per adjustment: the tagged block(s) Photoshop stores it in,
how they read into our parameters and how our parameters are written back.
Layouts follow Adobe's file format description and were checked against
files saved by Photoshop (psd-tools' test corpus).

What our adjustments can't express is dropped on import: per-range
Hue/Saturation edits and Colorize, Selective Color's Absolute method,
Channel Mixer constants. Kinds without a counterpart here (Color Balance,
Color Lookup, ...) are skipped by the importer, and ours without a
Photoshop counterpart (HDR Toning, Shadows/Highlights, ...) by the
exporter; both count them."""
from __future__ import annotations

import struct

from PyQt6.QtGui import QColor

from core.gradient_model import ColorStop, Gradient, OpacityStop


# ── descriptors (writing; reading is psd_import._DescriptorReader) ───────────

class DescriptorWriter:
    """A Photoshop action descriptor from a dict of (type, value) items:
    ("long", int), ("doub", float), ("bool", bool), ("UntF", (unit, float)),
    ("enum", (type, value)), ("TEXT", str), ("Objc", (class, items))."""

    @classmethod
    def block(cls, class_id: str, items: dict, version: int | None = 16) -> bytes:
        """A tagged block's content: descriptor version + descriptor."""
        head = struct.pack(">I", version) if version is not None else b""
        return head + cls.descriptor(class_id, items)

    @classmethod
    def descriptor(cls, class_id: str, items: dict) -> bytes:
        out = cls._unicode("") + cls._key(class_id) + struct.pack(">I", len(items))
        for key, (ostype, value) in items.items():
            out += cls._key(key) + ostype.encode("latin-1") + cls._value(ostype, value)
        return out

    @staticmethod
    def _unicode(text: str) -> bytes:
        units = (text + "\0").encode("utf-16-be")
        return struct.pack(">I", len(units) // 2) + units

    @staticmethod
    def _key(key: str) -> bytes:
        raw = key.encode("latin-1")
        if len(raw) == 4:
            return struct.pack(">I", 0) + raw
        return struct.pack(">I", len(raw)) + raw

    @classmethod
    def _value(cls, ostype: str, value) -> bytes:
        if ostype == "long":
            return struct.pack(">i", int(value))
        if ostype == "doub":
            return struct.pack(">d", float(value))
        if ostype == "bool":
            return struct.pack(">B", 1 if value else 0)
        if ostype == "UntF":
            unit, v = value
            return unit.encode("latin-1") + struct.pack(">d", float(v))
        if ostype == "enum":
            return cls._key(value[0]) + cls._key(value[1])
        if ostype == "TEXT":
            return cls._unicode(value)
        if ostype == "Objc":
            class_id, items = value
            return cls.descriptor(class_id, items)
        raise ValueError(f"descriptor type {ostype!r}")


def rgb_descriptor(c: QColor) -> tuple:
    return ("Objc", ("RGBC", {"Rd  ": ("doub", c.red()), "Grn ": ("doub", c.green()),
                              "Bl  ": ("doub", c.blue())}))


# ── codecs ───────────────────────────────────────────────────────────────────

class AdjustmentCodec:
    """`key`: the tagged block that marks a layer as this adjustment.
    `read(blocks, ctx)` gets every tagged block of the layer ({key: bytes})
    and returns our parameters (None if unreadable); `write(params)`
    returns the tagged blocks to store, [(key, bytes)]. `ctx` is the
    PsdFile being read (descriptor reading, colour conversion)."""
    key: bytes = b""
    type: str = ""

    def read(self, blocks: dict, ctx) -> dict | None:
        raise NotImplementedError

    def write(self, p: dict) -> list[tuple[bytes, bytes]]:
        raise NotImplementedError

    @staticmethod
    def _descriptor(data: bytes, offset: int = 4) -> dict:
        from core.psd_import import _DescriptorReader
        return _DescriptorReader(bytes(data[offset:])).read()


_CODECS: dict[bytes, AdjustmentCodec] = {}
_BY_TYPE: dict[str, AdjustmentCodec] = {}


def _register(cls):
    codec = cls()
    _CODECS[codec.key] = codec
    _BY_TYPE[codec.type] = codec
    return cls


def codec_for_blocks(blocks: dict) -> AdjustmentCodec | None:
    for key in blocks:
        if key in _CODECS:
            return _CODECS[key]
    return None


def codec_for_type(adj_type: str) -> AdjustmentCodec | None:
    return _BY_TYPE.get(adj_type)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@_register
class BrightnessContrastCodec(AdjustmentCodec):
    """'brit' holds the legacy values; Photoshop CS3+ keeps the real ones
    in a 'CgEd' descriptor next to it. Ours is the legacy (linear)
    algorithm, so it's written with "Use Legacy" on."""
    key, type = b"brit", "brightness_contrast"

    def read(self, blocks, ctx):
        if b"CgEd" in blocks:
            d = self._descriptor(blocks[b"CgEd"])
            b, c = d.get("Brgh", 0), d.get("Cntr", 0)
        else:
            b, c = struct.unpack_from(">hh", blocks[self.key], 0)
        return {"brightness": _clamp(int(b), -100, 100), "contrast": _clamp(int(c), -100, 100)}

    def write(self, p):
        b, c = int(p["brightness"]), int(p["contrast"])
        cged = DescriptorWriter.block("null", {
            "Vrsn": ("long", 1), "Brgh": ("long", b), "Cntr": ("long", c),
            "means": ("long", 127), "Lab ": ("bool", False), "useLegacy": ("bool", True),
            "Auto": ("bool", False)})
        return [(self.key, struct.pack(">hhHBx", b, c, 127, 0)), (b"CgEd", cged)]


_LEVEL_IDENTITY = (0, 255, 0, 255, 100)


@_register
class LevelsCodec(AdjustmentCodec):
    """29 records (composite, then each channel): input black / white,
    output black / white, gamma x 100."""
    key, type = b"levl", "levels"
    _CHANNELS = ("r", "g", "b")

    def read(self, blocks, ctx):
        data = blocks[self.key]
        recs = [struct.unpack_from(">5H", data, 2 + 10 * i) for i in range(4)
                if 2 + 10 * (i + 1) <= len(data)]
        if not recs:
            return None
        p = self._params(recs[0])
        channels = {name: self._params(r) for name, r in zip(self._CHANNELS, recs[1:])
                    if tuple(r) != _LEVEL_IDENTITY}
        if channels:
            p["channels"] = channels
        return p

    @staticmethod
    def _params(rec) -> dict:
        in_lo, in_hi, out_lo, out_hi, gamma = rec
        return {"black": int(in_lo), "white": int(max(in_hi, in_lo + 1)), "gamma": gamma / 100.0 or 1.0,
                "out_min": int(out_lo), "out_max": int(out_hi)}

    @staticmethod
    def _record(p: dict) -> bytes:
        return struct.pack(">5H", int(p["black"]), int(p["white"]), int(p["out_min"]),
                           int(p["out_max"]), int(round(_clamp(float(p["gamma"]), 0.1, 9.99) * 100)))

    def write(self, p):
        out = struct.pack(">H", 2) + self._record(p)
        channels = p.get("channels") or {}
        for name in self._CHANNELS:
            out += self._record(channels[name]) if name in channels else struct.pack(">5H", *_LEVEL_IDENTITY)
        out += struct.pack(">5H", *_LEVEL_IDENTITY) * (29 - 4)
        return [(self.key, out)]


@_register
class CurvesCodec(AdjustmentCodec):
    """Version 1: a bitmap of the curves present (bit 0 = composite, then
    R, G, B), each a point list stored as (output, input)."""
    key, type = b"curv", "curves"
    _CHANNELS = ("rgb", "r", "g", "b")

    def read(self, blocks, ctx):
        data = bytes(blocks[self.key])
        is_map, version, bitmap = struct.unpack_from(">BHI", data, 0)
        if is_map or version not in (1, 4):
            return None
        pos, points = 7, {}
        channels = [i for i in range(32) if bitmap & (1 << i)] if version == 1 else list(range(bitmap))
        for ch in channels:
            n = struct.unpack_from(">H", data, pos)[0]
            pts = [struct.unpack_from(">2H", data, pos + 2 + 4 * k) for k in range(n)]
            pos += 2 + 4 * n
            if ch < len(self._CHANNELS):
                points[self._CHANNELS[ch]] = sorted((int(x), int(y)) for y, x in pts)
        return {"points": points}

    def write(self, p):
        points = {k: v for k, v in (p.get("points") or {}).items() if k in self._CHANNELS and v}
        bitmap = 0
        body = b""
        extra = b""
        for i, name in enumerate(self._CHANNELS):
            if name not in points:
                continue
            bitmap |= 1 << i
            pts = sorted((int(x), int(y)) for x, y in points[name])
            rows = b"".join(struct.pack(">2H", y, x) for x, y in pts)
            body += struct.pack(">H", len(pts)) + rows
            extra += struct.pack(">2H", i, len(pts)) + rows
        n = bin(bitmap).count("1")
        data = struct.pack(">BHI", 0, 1, bitmap) + body + b"Crv " + struct.pack(">HI", 4, n) + extra
        return [(self.key, data)]


@_register
class ExposureCodec(AdjustmentCodec):
    key, type = b"expA", "exposure"

    def read(self, blocks, ctx):
        _v, exposure, offset, gamma = struct.unpack_from(">H3f", blocks[self.key], 0)
        return {"exposure": float(exposure), "offset": float(offset), "gamma": float(gamma) or 1.0}

    def write(self, p):
        return [(self.key, struct.pack(">H3f", 1, p["exposure"], p["offset"], p["gamma"]))]


@_register
class VibranceCodec(AdjustmentCodec):
    key, type = b"vibA", "vibrance"

    def read(self, blocks, ctx):
        d = self._descriptor(blocks[self.key])
        return {"vibrance": int(d.get("vibrance", 0)), "saturation": int(d.get("Strt", 0))}

    def write(self, p):
        return [(self.key, DescriptorWriter.block("null", {
            "vibrance": ("long", int(p["vibrance"])), "Strt": ("long", int(p["saturation"]))}))]


# Photoshop's default colour ranges for Hue/Saturation (reds .. magentas).
_HUE_RANGES = ((315, 345, 15, 45), (15, 45, 75, 105), (75, 105, 135, 165),
               (135, 165, 195, 225), (195, 225, 255, 285), (255, 285, 315, 345))


@_register
class HueSaturationCodec(AdjustmentCodec):
    """Master hue / saturation / lightness (the per-range edits and
    Colorize have no counterpart in ours)."""
    key, type = b"hue2", "hue_saturation"

    def read(self, blocks, ctx):
        data = blocks[self.key]
        hue, sat, light = struct.unpack_from(">3h", data, 10)
        return {"hue": int(hue), "saturation": int(sat), "lightness": int(light)}

    def write(self, p):
        out = struct.pack(">HBx", 2, 0) + struct.pack(">3h", 0, 25, 0)
        out += struct.pack(">3h", int(p["hue"]), int(p["saturation"]), int(p["lightness"]))
        for r in _HUE_RANGES:
            out += struct.pack(">4h", *r) + struct.pack(">3h", 0, 0, 0)
        return [(self.key, out)]


@_register
class InvertCodec(AdjustmentCodec):
    key, type = b"nvrt", "invert"

    def read(self, blocks, ctx):
        return {}

    def write(self, p):
        return [(self.key, b"")]


@_register
class PosterizeCodec(AdjustmentCodec):
    key, type = b"post", "posterize"

    def read(self, blocks, ctx):
        return {"levels": _clamp(struct.unpack_from(">H", blocks[self.key], 0)[0], 2, 255)}

    def write(self, p):
        return [(self.key, struct.pack(">H2x", int(p["levels"])))]


@_register
class ThresholdCodec(AdjustmentCodec):
    key, type = b"thrs", "threshold"

    def read(self, blocks, ctx):
        return {"threshold": _clamp(struct.unpack_from(">H", blocks[self.key], 0)[0], 1, 255)}

    def write(self, p):
        return [(self.key, struct.pack(">H2x", int(p["threshold"])))]


@_register
class BlackWhiteCodec(AdjustmentCodec):
    key, type = b"blwh", "black_white"
    _KEYS = (("reds", "Rd  "), ("yellows", "Yllw"), ("greens", "Grn "),
             ("cyans", "Cyn "), ("blues", "Bl  "), ("magentas", "Mgnt"))

    def read(self, blocks, ctx):
        d = self._descriptor(blocks[self.key])
        return {ours: int(d.get(theirs, 100)) for ours, theirs in self._KEYS}

    def write(self, p):
        items = {theirs: ("long", int(p[ours])) for ours, theirs in self._KEYS}
        items["useTint"] = ("bool", False)
        items["tintColor"] = rgb_descriptor(QColor(225, 211, 179))
        return [(self.key, DescriptorWriter.block("null", items))]


@_register
class PhotoFilterCodec(AdjustmentCodec):
    """Version 2: colour space (0 = RGB 0..65535, 7 = Lab: L x 100,
    a / b x 100 signed) + 4 components; version 3: XYZ, not documented —
    read as Photoshop's default warming colour."""
    key, type = b"phfl", "photo_filter"

    def read(self, blocks, ctx):
        data = bytes(blocks[self.key])
        version = struct.unpack_from(">H", data, 0)[0]
        color = QColor(236, 138, 0)
        if version == 3:
            pos = 2 + 12
        else:
            space = struct.unpack_from(">H", data, 2)[0]
            comps = struct.unpack_from(">4H", data, 4)
            color = self._color(space, comps, ctx) or color
            pos = 12
        density, preserve = struct.unpack_from(">IB", data, pos)
        return {"color": color, "density": _clamp(int(density), 1, 100), "preserve": bool(preserve)}

    @staticmethod
    def _color(space, comps, ctx) -> QColor | None:
        if space == 0:
            return QColor(*(round(c / 257) for c in comps[:3]))
        if space == 7:
            light = comps[0] / 100.0
            a, b = (struct.unpack(">h", struct.pack(">H", v))[0] / 100.0 for v in comps[1:3])
            return lab_to_qcolor(light, a, b)
        return None

    def write(self, p):
        c = p["color"]
        return [(self.key, struct.pack(">HH4HIB3x", 2, 0, c.red() * 257, c.green() * 257,
                                       c.blue() * 257, 0, int(p["density"]), 1 if p["preserve"] else 0))]


def lab_to_qcolor(light: float, a: float, b: float) -> QColor:
    """CIE Lab (D50, Photoshop's) -> sRGB."""
    fy = (light + 16.0) / 116.0
    fx, fz = fy + a / 500.0, fy - b / 200.0

    def f_inv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787
    x, y, z = 0.9642 * f_inv(fx), 1.0 * f_inv(fy), 0.8249 * f_inv(fz)
    # D50 XYZ -> linear sRGB (Bradford-adapted)
    r = 3.1338561 * x - 1.6168667 * y - 0.4906146 * z
    g = -0.9787684 * x + 1.9161415 * y + 0.0334540 * z
    bl = 0.0719453 * x - 0.2289914 * y + 1.4052427 * z

    def gamma(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return QColor(*(round(gamma(v) * 255) for v in (r, g, bl)))


@_register
class ChannelMixerCodec(AdjustmentCodec):
    """Per output channel: from R, G, B, (a 4th channel), constant — in %."""
    key, type = b"mixr", "channel_mixer"
    _ROWS = ("red", "green", "blue")

    def read(self, blocks, ctx):
        data = blocks[self.key]
        _v, mono = struct.unpack_from(">2H", data, 0)
        p = {"monochrome": bool(mono)}
        for i, name in enumerate(self._ROWS):
            if 4 + 10 * (i + 1) <= len(data):
                p[name] = list(struct.unpack_from(">3h", data, 4 + 10 * i))
        return p

    def write(self, p):
        out = struct.pack(">2H", 1, 1 if p["monochrome"] else 0)
        for name in self._ROWS:
            out += struct.pack(">5h", *(int(v) for v in p[name][:3]), 0, 0)
        out += struct.pack(">5h", 0, 0, 0, 100, 0)
        return [(self.key, out)]


@_register
class SelectiveColorCodec(AdjustmentCodec):
    """10 plates of (C, M, Y, K); plate 0 is unused, then reds .. blacks."""
    key, type = b"selc", "selective_color"

    def read(self, blocks, ctx):
        from core.adjustments.registry import SELECTIVE_COLOR_RANGES
        data = blocks[self.key]
        ranges = {name: list(struct.unpack_from(">4h", data, 4 + 8 * (i + 1)))
                  for i, name in enumerate(SELECTIVE_COLOR_RANGES)}
        return {"ranges": ranges}

    def write(self, p):
        from core.adjustments.registry import SELECTIVE_COLOR_RANGES
        out = struct.pack(">2H", 1, 0) + struct.pack(">4h", 0, 0, 0, 0)
        for name in SELECTIVE_COLOR_RANGES:
            out += struct.pack(">4h", *(int(v) for v in p["ranges"].get(name, [0, 0, 0, 0])[:4]))
        return [(self.key, out)]


@_register
class GradientMapCodec(AdjustmentCodec):
    """Binary gradient: colour stops (location 0..4096, midpoint %, RGB
    0..65535) and transparency stops; reverse flag."""
    key, type = b"grdm", "gradient_map"

    def read(self, blocks, ctx):
        data = bytes(blocks[self.key])
        version, reverse, _dither = struct.unpack_from(">H2B", data, 0)
        pos = 4 + (4 if version == 3 else 0)
        pos += 4 + 2 * struct.unpack_from(">I", data, pos)[0]          # name
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        raw = []
        for _ in range(n):
            loc, mid, mode = struct.unpack_from(">2IH", data, pos)
            r, g, b, _x = struct.unpack_from(">4H", data, pos + 10)
            raw.append((loc / 4096.0, mid / 100.0, QColor(round(r / 257), round(g / 257), round(b / 257))))
            pos += 20
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        alphas = []
        for _ in range(n):
            loc, mid, opacity = struct.unpack_from(">2IH", data, pos)
            alphas.append((loc / 4096.0, mid / 100.0, opacity / 255.0))
            pos += 10
        if not raw:
            return None
        g = Gradient(color_stops=self._stops(raw, ColorStop),
                     opacity_stops=self._stops(alphas, OpacityStop) or Gradient().opacity_stops)
        return {"gradient": g.to_dict(), "reverse": bool(reverse)}

    @staticmethod
    def _stops(raw, cls) -> list:
        """A PSD stop's midpoint is for the segment *ending* at it; ours is
        for the one starting at it."""
        raw = sorted(raw, key=lambda s: s[0])
        return [cls(loc, value, raw[i + 1][1] if i + 1 < len(raw) else 0.5)
                for i, (loc, _mid, value) in enumerate(raw)]

    def write(self, p):
        from core.adjustments.gradient_map import gradient_map_from_data
        g = gradient_map_from_data(p).sorted()
        name = "\0".encode("utf-16-be")
        out = struct.pack(">H2B", 1, 1 if p.get("reverse") else 0, 0)
        out += struct.pack(">I", 1) + name
        cs = g.color_stops
        out += struct.pack(">H", len(cs))
        for i, st in enumerate(cs):
            mid = cs[i - 1].midpoint if i else 0.5
            c = st.color
            out += struct.pack(">2IH4H2x", round(st.position * 4096), round(mid * 100), 0,
                               c.red() * 257, c.green() * 257, c.blue() * 257, 0)
        os_ = g.opacity_stops
        out += struct.pack(">H", len(os_))
        for i, st in enumerate(os_):
            mid = os_[i - 1].midpoint if i else 0.5
            out += struct.pack(">2IH", round(st.position * 4096), round(mid * 100),
                               round(st.opacity * 255))
        # expansion, interpolation, length, mode; random seed, show
        # transparency, use vector colour; roughness, colour model; min and
        # max colour — the values Photoshop writes for a solid gradient.
        out += struct.pack(">4H", 2, 4096, 32, 0) + struct.pack(">I2H", 0, 0, 1)
        out += struct.pack(">IH", 2048, 3)
        out += struct.pack(">4H", 0, 0, 0, 0) + struct.pack(">4H", 32768, 32768, 32768, 32768)
        out += b"\x00\x00"
        return [(self.key, out)]
