"""Photoshop .psd / .psb import, read directly from the file format.

No third-party PSD library: python-psd-tools exists only in the AUR, and
the package is meant to install from the official repositories alone.

Two halves:
  * PsdFile  — parses the binary file into plain records (header, layer
    records, channel data) and decodes channels to 8-bit arrays.
  * PsdImporter — turns those records into a Document of RasterLayers and
    GroupLayers.

PSD stores layers bottom-to-top, the same order as `Document.layers`. A
group is written as a "bounding section divider" record below its children
and the group's own record above them — the same place GroupLayer sits in
our list (above its children, see LayerActionsMixin._group_layer).

Pixel, type, shape and smart-object layers come in as their stored pixels.
Colour and gradient fill layers that Photoshop saved without pixels are
painted from their settings and vector mask. Adjustment layers become our
adjustment layers (core/psd_adjustments.py); kinds we don't have, pattern
fills and noise gradients without pixels are skipped (and counted). Layer
effects become layer styles (core/psd_effects.py), with the layer's Fill
opacity."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QColorSpace, QImage, QPainter, QPainterPath

from core.app_logging import get_logger
from core.document import Document
from core.layer import AdjustmentLayer, GroupLayer, Layer, RasterLayer
from core.locale import tr
from core.pixel_buffer import gray_mask_image, path_mask

logger = get_logger("psd_import")


class PsdFormatError(ValueError):
    """The file isn't a PSD/PSB this reader understands."""


# ── binary cursor ────────────────────────────────────────────────────────────

class _Reader:
    """Big-endian cursor over the whole file. `psb` switches the fields
    that are 8 bytes wide in the large-document format."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.psb = False

    def _unpack(self, fmt: str, size: int):
        if self.pos + size > len(self.data):
            raise PsdFormatError("unexpected end of file")
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def u8(self) -> int:  return self._unpack(">B", 1)
    def u16(self) -> int: return self._unpack(">H", 2)
    def i16(self) -> int: return self._unpack(">h", 2)
    def u32(self) -> int: return self._unpack(">I", 4)
    def i32(self) -> int: return self._unpack(">i", 4)
    def u64(self) -> int: return self._unpack(">Q", 8)

    def length(self) -> int:
        """A section length: 4 bytes in PSD, 8 in PSB."""
        return self.u64() if self.psb else self.u32()

    def take(self, n: int) -> memoryview:
        if n < 0 or self.pos + n > len(self.data):
            raise PsdFormatError("unexpected end of file")
        view = memoryview(self.data)[self.pos:self.pos + n]
        self.pos += n
        return view

    def skip(self, n: int) -> None:
        self.take(n)


# Tagged blocks whose length field is 8 bytes in PSB.
_PSB_LONG_KEYS = {b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn",
                  b"Alph", b"FMsk", b"lnk2", b"FEid", b"FXid", b"PxSD", b"lnkE",
                  b"extd", b"lnkD", b"lnk3", b"cinf"}
_TAG_SIGNATURES = (b"8BIM", b"8B64")


def _iter_tagged_blocks(r: _Reader, end: int):
    """Yield (key, data) for "additional layer information" blocks up to
    `end`. Writers pad blocks differently (even / 4-byte), so instead of
    trusting one rule, skip forward to the next signature."""
    while r.pos + 12 <= end:
        sig = bytes(r.data[r.pos:r.pos + 4])
        if sig not in _TAG_SIGNATURES:
            r.pos += 1
            continue
        r.pos += 4
        key = bytes(r.take(4))
        size = r.u64() if (r.psb and key in _PSB_LONG_KEYS) else r.u32()
        size = min(size, end - r.pos)
        yield key, r.take(size)
    r.pos = end


# ── action descriptors ───────────────────────────────────────────────────────

class _DescriptorReader:
    """Photoshop "action descriptor" structures, read into plain dicts.
    Only the value types fill-layer settings use; anything else raises
    PsdFormatError, and the caller treats the setting as unreadable."""

    def __init__(self, data: bytes):
        self._r = _Reader(data)

    def read(self) -> dict:
        r = self._r
        r.skip(r.u32() * 2)                 # descriptor name (UTF-16)
        result = {"_class": self._key()}
        for _ in range(r.u32()):
            key = self._key()
            result[key] = self._value(bytes(r.take(4)))
        return result

    def _key(self) -> str:
        r = self._r
        n = r.u32()
        return bytes(r.take(n or 4)).decode("latin-1")

    def _text(self) -> str:
        r = self._r
        return bytes(r.take(r.u32() * 2)).decode("utf-16-be", "replace").rstrip("\0")

    def _value(self, ostype: bytes):
        r = self._r
        if ostype in (b"Objc", b"GlbO"):
            return self.read()
        if ostype == b"VlLs":
            return [self._value(bytes(r.take(4))) for _ in range(r.u32())]
        if ostype == b"doub":
            return r._unpack(">d", 8)
        if ostype == b"UntF":
            r.skip(4)                        # unit: degrees / percent / pixels
            return r._unpack(">d", 8)
        if ostype == b"long":
            return r.i32()
        if ostype == b"comp":
            return r._unpack(">q", 8)
        if ostype == b"bool":
            return r.u8() != 0
        if ostype == b"TEXT":
            return self._text()
        if ostype == b"enum":
            return (self._key(), self._key())
        if ostype in (b"type", b"GlbC"):
            self._text()
            return self._key()
        if ostype in (b"alis", b"tdta"):
            return bytes(r.take(r.u32()))
        raise PsdFormatError(f"unsupported descriptor value type {ostype!r}")


def _descriptor_color(desc: dict) -> QColor | None:
    """QColor of a descriptor colour object ('Clr ')."""
    cls = desc.get("_class")
    if cls == "RGBC":
        if "redFloat" in desc:
            return QColor.fromRgbF(*(min(1.0, max(0.0, desc[k])) for k in
                                     ("redFloat", "greenFloat", "blueFloat")))
        return QColor(*(int(round(min(255.0, max(0.0, desc.get(k, 0.0))))) for k in
                        ("Rd  ", "Grn ", "Bl  ")))
    if cls == "Grsc":
        v = 1.0 - desc.get("Gry ", 0.0) / 100.0
        return QColor.fromRgbF(v, v, v)
    if cls == "CMYC":
        return QColor.fromCmykF(*(desc.get(k, 0.0) / 100.0 for k in
                                  ("Cyn ", "Mgnt", "Ylw ", "Blck")))
    if cls == "HSBC":
        return QColor.fromHsvF((desc.get("H   ", 0.0) % 360.0) / 360.0,
                               desc.get("Strt", 0.0) / 100.0, desc.get("Brgh", 0.0) / 100.0)
    if cls == "LbCl":
        lab = [np.array([[desc.get("Lmnc", 0.0) * 255.0 / 100.0]]),
               np.array([[desc.get("A   ", 0.0) + 128.0]]),
               np.array([[desc.get("B   ", 0.0) + 128.0]])]
        r, g, b = _LabMode().to_rgb(lab)[0, 0]
        return QColor(int(r), int(g), int(b))
    return None


# ── fill layers ──────────────────────────────────────────────────────────────

class _Fill:
    """Content of a fill layer ('SoCo' / 'GdFl') that Photoshop didn't
    store as pixels, painted over the canvas or inside `shape`."""
    align = True        # a gradient spans the shape's bounds, else the canvas

    def paint(self, width: int, height: int, shape: QPainterPath | None) -> QImage:
        raise NotImplementedError


class _SolidFill(_Fill):
    def __init__(self, rgb: tuple):
        self._color = QColor(*rgb)

    def paint(self, width, height, shape):
        img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        if shape is None:
            img.fill(self._color)
            return img
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(shape, self._color)
        p.end()
        return img


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_OKLAB_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                      [0.2119034982, 0.6806995451, 0.1073969566],
                      [0.0883024619, 0.2817188376, 0.6299787005]], np.float32)
_OKLAB_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                      [1.9779984951, -2.4285922050, 0.4505937099],
                      [0.0259040371, 0.7827717662, -0.8086757660]], np.float32)


def _srgb_to_oklab(c: np.ndarray) -> np.ndarray:
    lms = _srgb_to_linear(c) @ _OKLAB_M1.T
    return np.cbrt(lms) @ _OKLAB_M2.T


def _oklab_to_srgb(c: np.ndarray) -> np.ndarray:
    lms = (c @ np.linalg.inv(_OKLAB_M2).T) ** 3
    return _linear_to_srgb(lms @ np.linalg.inv(_OKLAB_M1).T)


class _GradientFill(_Fill):
    """Linear / radial / angle / reflected / diamond gradient with colour
    and transparency stops (and their midpoints), angle, scale, offset,
    reverse and the interpolation method (Classic = in sRGB, Linear = in
    linear light, Perceptual = in Oklab). The ramp spans `box` (the
    shape's bounds, or the canvas).

    Geometry was checked against the pixels Photoshop stores for gradient
    shape layers: linear and angle gradients match within a few levels;
    radial / reflected / diamond ones came out consistently ~10% longer
    in Photoshop than the box-based length, hence _ROUND_SPAN."""

    _KINDS = {"Lnr ", "Rdl ", "Angl", "Rflc", "Dmnd"}
    _ROUND_SPAN = 1.1

    def __init__(self, desc: dict, resolve_color):
        kind = desc.get("Type")
        self.kind = kind[1] if isinstance(kind, tuple) else "Lnr "
        if self.kind not in self._KINDS:
            raise PsdFormatError(f"unsupported gradient type {self.kind!r}")
        self.angle = float(desc.get("Angl", 0.0))
        self.scale = float(desc.get("Scl ", 100.0)) / 100.0 or 1.0
        self.reverse = bool(desc.get("Rvrs", False))
        self.align = bool(desc.get("Algn", True))
        ofst = desc.get("Ofst") if isinstance(desc.get("Ofst"), dict) else {}
        self.offset = (float(ofst.get("Hrzn", 0.0)), float(ofst.get("Vrtc", 0.0)))
        method = desc.get("gradientsInterpolationMethod")
        self.method = method[1] if isinstance(method, tuple) else "Gcls"

        grad = desc.get("Grad")
        if not isinstance(grad, dict):
            raise PsdFormatError("gradient fill without a gradient")
        form = grad.get("GrdF")
        if isinstance(form, tuple) and form[1] != "CstS":
            raise PsdFormatError("noise gradients aren't supported")
        self.colors = self._stops(grad.get("Clrs", []),
                                  lambda st: self._stop_color(st, resolve_color))
        self.alphas = self._stops(grad.get("Trns", []),
                                  lambda st: (float(st.get("Opct", 100.0)) / 100.0,))
        if not self.colors:
            raise PsdFormatError("gradient without colour stops")
        if not self.alphas:
            self.alphas = [(0.0, 0.5, np.array([1.0])), (1.0, 0.5, np.array([1.0]))]

    @staticmethod
    def _stop_color(stop: dict, resolve_color) -> tuple:
        clr = stop.get("Clr ")
        if isinstance(clr, dict):
            rgb = resolve_color(clr)
            if rgb is not None:
                return tuple(c / 255.0 for c in rgb)
        kind = stop.get("Type")
        # Foreground / background stops carry no colour: Photoshop's defaults.
        return (1.0, 1.0, 1.0) if isinstance(kind, tuple) and kind[1] == "BckC" else (0.0, 0.0, 0.0)

    @staticmethod
    def _stops(items: list, value) -> list:
        """[(location 0..1, midpoint 0..1, value array)], sorted."""
        out = []
        for st in items:
            if isinstance(st, dict):
                out.append((min(1.0, max(0.0, st.get("Lctn", 0) / 4096.0)),
                            min(0.99, max(0.01, st.get("Mdpn", 50) / 100.0)),
                            np.array(value(st), np.float32)))
        out.sort(key=lambda t: t[0])
        return out

    @staticmethod
    def _interpolate(stops: list, z: np.ndarray) -> np.ndarray:
        """Values at positions `z`; the midpoint of the stop pair is where
        the blend is half way."""
        vals = np.empty(z.shape + stops[0][2].shape, np.float32)
        vals[...] = stops[0][2]
        for (l0, _, v0), (l1, mid, v1) in zip(stops, stops[1:]):
            if l1 <= l0:
                vals[z >= l1] = v1
                continue
            sel = z >= l0
            t = np.clip((z[sel] - l0) / (l1 - l0), 0.0, 1.0)
            t = np.power(t, np.log(0.5) / np.log(mid))
            vals[sel] = v0 + (v1 - v0) * t[..., None]
        vals[z >= stops[-1][0]] = stops[-1][2]
        return vals

    def _interpolate_colors(self, z: np.ndarray) -> np.ndarray:
        if self.method == "Lnr ":
            to_space, from_space = _srgb_to_linear, _linear_to_srgb
        elif self.method == "Perc":
            to_space, from_space = _srgb_to_oklab, _oklab_to_srgb
        else:
            return self._interpolate(self.colors, z)
        stops = [(loc, mid, to_space(v.astype(np.float32))) for loc, mid, v in self.colors]
        return np.clip(from_space(self._interpolate(stops, z)), 0.0, 1.0).astype(np.float32)

    def paint(self, width, height, shape):
        box = QRectF(0, 0, width, height)
        if shape is not None and not shape.isEmpty() and self.align:
            box = shape.boundingRect()
        rgba = self.render(width, height, box)
        if shape is not None:
            rgba[..., 3] *= path_mask(shape, width, height, antialias=True).astype(np.float32) / 255.0
        return _rgba_to_qimage(np.clip(rgba * 255.0 + 0.5, 0, 255).astype(np.uint8))

    def render(self, width: int, height: int, box: QRectF) -> np.ndarray:
        """(h, w, 4) float RGBA in 0..1 for the whole canvas, the ramp laid
        out across `box`."""
        bw, bh = max(box.width(), 1.0), max(box.height(), 1.0)
        r = self.angle % 90.0
        span = self.scale * ((90.0 - r) / 90.0 * bw + r / 90.0 * bh)
        if self.kind in ("Rdl ", "Rflc", "Dmnd"):
            span *= self._ROUND_SPAN
        cx = box.x() + bw / 2 + self.offset[0] / 100.0 * bw
        cy = box.y() + bh / 2 + self.offset[1] / 100.0 * bh
        X = (np.arange(width, dtype=np.float32) + 0.5 - cx) * (2.0 / span)
        Y = (np.arange(height, dtype=np.float32) + 0.5 - cy) * (2.0 / span)
        X, Y = np.meshgrid(X, Y)
        th = np.radians(self.angle % 360.0)
        along = np.cos(th) * X - np.sin(th) * Y
        if self.kind == "Lnr ":
            z = 0.5 * (along + 1.0)
        elif self.kind == "Rdl ":
            z = np.hypot(X, Y)
        elif self.kind == "Angl":
            z = ((np.degrees(np.arctan2(Y, X)) + self.angle) % 360.0) / 360.0
        elif self.kind == "Rflc":
            z = np.abs(along)
        else:                                            # diamond
            z = np.abs(along) + np.abs(np.sin(th) * X + np.cos(th) * Y)
        z = np.clip(z, 0.0, 1.0)
        if self.reverse:
            z = 1.0 - z
        rgb = self._interpolate_colors(z)
        alpha = self._interpolate(self.alphas, z)
        return np.concatenate([rgb, alpha], axis=2)


# ── vector masks ─────────────────────────────────────────────────────────────

# Path record selectors
_PATH_CLOSED_LEN, _PATH_CLOSED_KNOTS = 0, (1, 2)
_PATH_OPEN_LEN, _PATH_OPEN_KNOTS = 3, (4, 5)
_PATH_INITIAL_FILL = 8

# Shape operations of a path component (-1 = part of the previous one)
_OP_EXCLUDE, _OP_UNION, _OP_SUBTRACT, _OP_INTERSECT, _OP_MERGED = 0, 1, 2, 3, -1


@dataclass
class _VectorMask:
    path: QPainterPath
    disabled: bool


class _VectorMaskReader:
    """'vmsk' / 'vsms' block -> a QPainterPath in document pixels.

    Each knot is three (y, x) points — preceding control, anchor, leaving
    control — as 8.24 fixed point relative to the canvas size. Components
    combine in order by their shape operation; the first component's
    subtract/intersect starts from a fully covered canvas."""

    def __init__(self, width: int, height: int):
        self._w, self._h = width, height

    def read(self, block: memoryview) -> _VectorMask | None:
        if len(block) < 8:
            return None
        flags = struct.unpack_from(">I", block, 4)[0]
        components: list[tuple[int, QPainterPath]] = []
        initial_fill = False
        knots: list = []
        remaining, closed, op = 0, False, _OP_UNION
        for pos in range(8, len(block) - 25, 26):
            selector = struct.unpack_from(">H", block, pos)[0]
            if selector in (_PATH_CLOSED_LEN, _PATH_OPEN_LEN):
                remaining, op = struct.unpack_from(">Hh", block, pos + 2)
                closed = selector == _PATH_CLOSED_LEN
                knots = []
                if remaining == 0:
                    continue
            elif selector in _PATH_CLOSED_KNOTS + _PATH_OPEN_KNOTS and remaining:
                knots.append(self._points(block, pos + 2))
                remaining -= 1
                if remaining == 0:      # open paths fill as if closed straight
                    sub = self._subpath(knots, closed)
                    if op == _OP_MERGED and components:
                        components[-1][1].addPath(sub)
                    else:
                        components.append((op, sub))
            elif selector == _PATH_INITIAL_FILL:
                initial_fill = struct.unpack_from(">H", block, pos + 2)[0] != 0

        canvas = QPainterPath()
        canvas.addRect(QRectF(0, 0, self._w, self._h))
        path = QPainterPath(canvas) if initial_fill and not components else QPainterPath()
        for i, (op, sub) in enumerate(components):
            if i == 0 and op in (_OP_SUBTRACT, _OP_INTERSECT):
                path = QPainterPath(canvas)
            if op == _OP_EXCLUDE:
                path = path.united(sub).subtracted(path.intersected(sub))
            elif op == _OP_SUBTRACT:
                path = path.subtracted(sub)
            elif op == _OP_INTERSECT:
                path = path.intersected(sub)
            else:
                path = path.united(sub)
        if flags & 0x01:                                  # inverted
            path = canvas.subtracted(path)
        return _VectorMask(path, disabled=bool(flags & 0x04))

    def _points(self, block: memoryview, pos: int) -> list:
        vals = struct.unpack_from(">6i", block, pos)
        return [QPointF(vals[i + 1] / 0x1000000 * self._w, vals[i] / 0x1000000 * self._h)
                for i in (0, 2, 4)]

    @staticmethod
    def _subpath(knots: list, closed: bool) -> QPainterPath:
        """Bezier through the knots ([preceding, anchor, leaving]). An open
        subpath is closed with a straight line, the way its fill is drawn."""
        p = QPainterPath()
        p.setFillRule(Qt.FillRule.WindingFill)
        p.moveTo(knots[0][1])
        for a, b in zip(knots, knots[1:] + (knots[:1] if closed else [])):
            p.cubicTo(a[2], b[0], b[1])
        p.closeSubpath()
        return p


# ── records ──────────────────────────────────────────────────────────────────

# Section divider types ('lsct' / 'lsdk').
_SECTION_OPEN, _SECTION_CLOSED, _SECTION_BOUNDARY = 1, 2, 3

# Keys of adjustment and fill layers. Such a layer is skipped only when it
# has no pixels: shape layers are fill layers too ('SoCo' + vector mask),
# and Photoshop stores their rendered pixels.
_FILL_KEYS = {b"SoCo", b"GdFl", b"PtFl"}
_ADJUSTMENT_KEYS = {b"SoCo", b"GdFl", b"PtFl", b"brit", b"levl", b"curv", b"expA",
                    b"vibA", b"hue ", b"hue2", b"blnc", b"blwh", b"phfl", b"mixr",
                    b"clrL", b"nvrt", b"post", b"thrs", b"grdm", b"selc"}


@dataclass
class _Rect:
    top: int = 0
    left: int = 0
    bottom: int = 0
    right: int = 0

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass
class _MaskInfo:
    rect: _Rect
    default_color: int
    disabled: bool


@dataclass
class PsdLayerRecord:
    name: str
    rect: _Rect
    blend_key: bytes
    opacity: int
    fill_opacity: int
    clipping: bool
    visible: bool
    section: int = 0                  # 0 = ordinary layer, else _SECTION_*
    section_blend_key: bytes | None = None
    is_adjustment: bool = False
    mask: _MaskInfo | None = None
    vector_mask: _VectorMask | None = None
    fill_key: bytes | None = None     # b"SoCo" / b"GdFl" / b"PtFl"
    fill: _Fill | None = None         # solid colour / gradient we can paint
    adjustment_blocks: dict = field(default_factory=dict)   # key -> bytes (core/psd_adjustments.py)
    effects: dict | None = None       # the layer effects descriptor ('lfx2' / 'lmfx')
    channel_ids: list = field(default_factory=list)
    channel_lengths: list = field(default_factory=list)
    channel_data: dict = field(default_factory=dict)   # id -> memoryview


# ── channel decoding ─────────────────────────────────────────────────────────

def _unpack_bits(src: memoryview, expected: int) -> bytes:
    """PackBits (RLE) decode, until `expected` bytes are produced."""
    src = bytes(src)
    out = bytearray()
    i, n = 0, len(src)
    while i < n and len(out) < expected:
        c = src[i]
        i += 1
        if c < 128:
            out += src[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += src[i:i + 1] * (257 - c)
            i += 1
    if len(out) < expected:
        out += bytes(expected - len(out))
    return bytes(out[:expected])


class _ChannelDecoder:
    """Decodes one channel's bytes to a (height, width) uint8 array.
    Colour channels at 32 bits are linear light and get the sRGB curve;
    alpha and masks don't."""

    def __init__(self, depth: int, psb: bool):
        if depth not in (1, 8, 16, 32):
            raise PsdFormatError(f"unsupported bit depth: {depth}")
        self.depth = depth
        self.psb = psb

    def row_bytes(self, width: int) -> int:
        return (width * self.depth + 7) // 8

    def decode(self, data: memoryview, width: int, height: int, linear: bool) -> np.ndarray:
        if width <= 0 or height <= 0:
            return np.zeros((max(height, 0), max(width, 0)), np.uint8)
        if len(data) < 2:
            return np.zeros((height, width), np.uint8)
        compression = struct.unpack_from(">H", data, 0)[0]
        raw = self.decompress(compression, data[2:], width, height)
        return self.to_uint8(raw, width, height, linear)

    def decompress(self, compression: int, body: memoryview, width: int, height: int) -> bytes:
        size = self.row_bytes(width) * height
        if compression == 0:
            raw = bytes(body[:size])
        elif compression == 1:
            counts = height * (4 if self.psb else 2)
            raw = _unpack_bits(body[counts:], size)
        elif compression in (2, 3):
            try:
                raw = zlib.decompress(bytes(body))
            except zlib.error as e:
                raise PsdFormatError(f"broken ZIP channel data: {e}") from e
            if compression == 3:
                raw = self._undo_prediction(raw[:size].ljust(size, b"\0"), width, height)
        else:
            raise PsdFormatError(f"unknown compression: {compression}")
        return raw[:size].ljust(size, b"\0")

    def _undo_prediction(self, raw: bytes, width: int, height: int) -> bytes:
        if self.depth == 8:
            a = np.frombuffer(raw, np.uint8).reshape(height, width)
            return np.cumsum(a, axis=1, dtype=np.uint8).tobytes()
        if self.depth == 16:
            a = np.frombuffer(raw, ">u2").reshape(height, width).astype(np.uint16)
            return np.cumsum(a, axis=1, dtype=np.uint16).astype(">u2").tobytes()
        if self.depth == 32:
            # Byte-wise delta over each row, whose bytes are stored as four
            # planes (all 1st bytes of the row, then all 2nd bytes, ...).
            a = np.frombuffer(raw, np.uint8).reshape(height, width * 4)
            a = np.cumsum(a, axis=1, dtype=np.uint8)
            return a.reshape(height, 4, width).transpose(0, 2, 1).tobytes()
        raise PsdFormatError("ZIP prediction on 1-bit data")

    def to_uint8(self, raw: bytes, width: int, height: int, linear: bool) -> np.ndarray:
        if self.depth == 8:
            return np.frombuffer(raw, np.uint8).reshape(height, width).copy()
        if self.depth == 16:
            a = np.frombuffer(raw, ">u2").reshape(height, width).astype(np.uint32)
            return ((a * 255 + 32767) // 65535).astype(np.uint8)
        if self.depth == 32:
            a = np.clip(np.frombuffer(raw, ">f4").reshape(height, width), 0.0, 1.0)
            if linear:
                a = np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)
            return np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
        # 1-bit bitmap: 1 = black
        bits = np.unpackbits(np.frombuffer(raw, np.uint8).reshape(height, -1), axis=1)[:, :width]
        return np.where(bits == 1, 0, 255).astype(np.uint8)


# ── colour modes ─────────────────────────────────────────────────────────────

class _ColorMode:
    """Turns a mode's colour channels into (h, w, 3) uint8 RGB."""
    channel_ids: tuple = ()
    linear_channels = True
    icc_model = None            # QColorSpace.ColorModel an ICC profile must have

    def to_rgb(self, channels: list) -> np.ndarray:
        raise NotImplementedError

    def icc_source(self, channels: list) -> QImage | None:
        """The channels as a QImage an ICC profile can be attached to."""
        return None


class _RgbMode(_ColorMode):
    channel_ids = (0, 1, 2)
    icc_model = QColorSpace.ColorModel.Rgb

    def to_rgb(self, channels):
        return np.dstack(channels)

    def icc_source(self, channels):
        return _array_qimage(np.dstack(channels), QImage.Format.Format_RGB888)


class _GrayMode(_ColorMode):
    channel_ids = (0,)
    icc_model = QColorSpace.ColorModel.Gray

    def to_rgb(self, channels):
        return np.dstack([channels[0]] * 3)

    def icc_source(self, channels):
        return _array_qimage(channels[0], QImage.Format.Format_Grayscale8)


class _CmykMode(_ColorMode):
    """PSD stores CMYK inverted (255 = no ink). Without a profile this is
    the naive conversion; with one, Qt converts the ink values."""
    channel_ids = (0, 1, 2, 3)
    icc_model = QColorSpace.ColorModel.Cmyk

    def to_rgb(self, channels):
        c, m, y, k = (ch.astype(np.uint16) for ch in channels)
        return np.dstack([(c * k + 127) // 255, (m * k + 127) // 255,
                          (y * k + 127) // 255]).astype(np.uint8)

    def icc_source(self, channels):
        ink = 255 - np.dstack(channels)
        return _array_qimage(ink, QImage.Format.Format_CMYK8888)


def _array_qimage(a: np.ndarray, fmt: QImage.Format) -> QImage:
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    return QImage(a.data, w, h, a.strides[0], fmt).copy()


class _IccConverter:
    """Colour channels -> sRGB through the document's embedded ICC profile.
    Falls back to the mode's plain conversion when there's no usable
    profile for the mode (or the data is 32-bit linear light)."""

    def __init__(self, icc: bytes | None, mode: _ColorMode, depth: int):
        self._mode = mode
        self._cs = None
        if icc and depth != 32 and mode.icc_model is not None:
            cs = QColorSpace.fromIccProfile(icc)
            if cs.isValid() and cs.colorModel() == mode.icc_model:
                self._cs = cs
            else:
                logger.info("PSD ICC profile not usable for this mode; converting without it")
        self._srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)

    def to_rgb(self, channels: list) -> np.ndarray:
        if self._cs is not None:
            src = self._mode.icc_source(channels)
            if src is not None:
                src.setColorSpace(self._cs)
                out = src.convertedToColorSpace(self._srgb, QImage.Format.Format_RGB888)
                if not out.isNull():
                    h, w = out.height(), out.width()
                    buf = np.frombuffer(out.constBits().asstring(out.sizeInBytes()), np.uint8)
                    return buf.reshape(h, out.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()
        return self._mode.to_rgb(channels)


class _LabMode(_ColorMode):
    channel_ids = (0, 1, 2)
    linear_channels = False

    def to_rgb(self, channels):
        L = channels[0].astype(np.float32) * (100.0 / 255.0)
        a = channels[1].astype(np.float32) - 128.0
        b = channels[2].astype(np.float32) - 128.0
        fy = (L + 16.0) / 116.0
        fx, fz = fy + a / 500.0, fy - b / 200.0

        def finv(t):
            return np.where(t > 6 / 29, t ** 3, 3 * (6 / 29) ** 2 * (t - 4 / 29))
        x, y, z = 0.95047 * finv(fx), finv(fy), 1.08883 * finv(fz)   # D65
        r = 3.2406 * x - 1.5372 * y - 0.4986 * z
        g = -0.9689 * x + 1.8758 * y + 0.0415 * z
        bl = 0.0557 * x - 0.2040 * y + 1.0570 * z
        rgb = np.clip(np.dstack([r, g, bl]), 0.0, 1.0)
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
        return np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


class _IndexedMode(_ColorMode):
    """Indexed and bitmap images have no layers — only the merged image."""
    channel_ids = (0,)

    def __init__(self, palette: bytes):
        pal = np.frombuffer(palette[:768].ljust(768, b"\0"), np.uint8)
        self._lut = pal.reshape(3, 256).T

    def to_rgb(self, channels):
        return self._lut[channels[0]]


# PSD colour mode numbers
_MODE_BITMAP, _MODE_GRAY, _MODE_INDEXED, _MODE_RGB = 0, 1, 2, 3
_MODE_CMYK, _MODE_MULTICHANNEL, _MODE_DUOTONE, _MODE_LAB = 4, 7, 8, 9


def _color_mode_for(mode: int, color_data: bytes) -> _ColorMode:
    if mode == _MODE_RGB:
        return _RgbMode()
    if mode in (_MODE_GRAY, _MODE_DUOTONE, _MODE_BITMAP, _MODE_MULTICHANNEL):
        # duotone: its grayscale base, no ink curves; multichannel: channel 0
        return _GrayMode()
    if mode == _MODE_CMYK:
        return _CmykMode()
    if mode == _MODE_LAB:
        return _LabMode()
    if mode == _MODE_INDEXED:
        return _IndexedMode(color_data)
    raise PsdFormatError(f"unsupported color mode: {mode}")


# ── the file ─────────────────────────────────────────────────────────────────

class PsdFile:
    """A parsed .psd/.psb: header fields, layer records with their raw
    channel data, and access to the merged image."""

    def __init__(self, data: bytes):
        r = _Reader(data)
        if bytes(r.take(4)) != b"8BPS":
            raise PsdFormatError("not a Photoshop file")
        version = r.u16()
        if version not in (1, 2):
            raise PsdFormatError(f"unsupported PSD version: {version}")
        r.psb = version == 2
        r.skip(6)
        self.channel_count = r.u16()
        self.height = r.u32()
        self.width = r.u32()
        self.depth = r.u16()
        self.mode = r.u16()
        if self.width <= 0 or self.height <= 0:
            raise PsdFormatError("empty canvas")

        color_data = bytes(r.take(r.u32()))
        resources_len = r.u32()
        resources = self._read_resources(r, r.pos + resources_len)
        icc = resources.get(1039)
        # Global light angle (resource 1037), which effects may follow.
        self.global_angle = (struct.unpack(">i", resources[1037][:4])[0]
                             if len(resources.get(1037, b"")) >= 4 else 120)
        self.color_mode = _color_mode_for(self.mode, color_data)
        self.colors = _IccConverter(icc, self.color_mode, self.depth)
        self.decoder = _ChannelDecoder(self.depth, r.psb)
        self._r = r

        self.layers: list[PsdLayerRecord] = []
        self.merged_has_alpha = False
        section_len = r.length()
        section_end = r.pos + section_len
        try:
            self._read_layer_and_mask_section(section_end)
        except PsdFormatError:
            logger.exception("PSD layer section unreadable; using the merged image")
            self.layers = []
        r.pos = section_end
        self._merged_offset = section_end

    _RESOURCES = (1037, 1039)          # global angle, ICC profile

    @classmethod
    def _read_resources(cls, r: _Reader, end: int) -> dict:
        """The image resources we use, {id: bytes}. Leaves the cursor at
        `end`."""
        found = {}
        try:
            while r.pos + 12 <= end:
                if bytes(r.take(4)) != b"8BIM":
                    break
                res_id = r.u16()
                name_len = r.u8()
                r.skip(name_len + (1 + name_len) % 2)     # Pascal name, even-padded
                size = r.u32()
                data = r.take(min(size, end - r.pos))
                if size % 2 and r.pos < end:
                    r.skip(1)
                if res_id in cls._RESOURCES:
                    found[res_id] = bytes(data)
        except PsdFormatError:
            logger.warning("PSD image resources unreadable")
        r.pos = end
        return found

    # ---------------------------------------------------------------- layers
    def _read_layer_and_mask_section(self, end: int) -> None:
        r = self._r
        if r.pos >= end:
            return
        info_len = r.length()
        info_end = r.pos + info_len
        if info_len:
            self._read_layer_info(info_end)
        r.pos = info_end
        if r.pos + 4 <= end:
            r.skip(min(r.u32(), end - r.pos))          # global layer mask info
        # 16/32-bit documents keep the layer info in a tagged block instead.
        for key, block in _iter_tagged_blocks(r, end):
            if key in (b"Lr16", b"Lr32", b"Layr") and not self.layers:
                sub = _Reader(bytes(block))
                sub.psb = r.psb
                self._read_layer_info(len(block), sub)

    def _read_layer_info(self, end: int, r: _Reader | None = None) -> None:
        r = r or self._r
        count = r.i16()
        if count < 0:                 # negative: merged image has transparency
            count = -count
            self.merged_has_alpha = True
        records = [self._read_record(r) for _ in range(count)]
        for rec in records:
            for cid, size in zip(rec.channel_ids, rec.channel_lengths):
                rec.channel_data[cid] = r.take(min(size, max(0, end - r.pos)))
        self.layers = records

    def _read_record(self, r: _Reader) -> PsdLayerRecord:
        rect = _Rect(r.i32(), r.i32(), r.i32(), r.i32())
        n_channels = r.u16()
        ids, lengths = [], []
        for _ in range(n_channels):
            ids.append(r.i16())
            lengths.append(r.length())
        if bytes(r.take(4)) != b"8BIM":
            raise PsdFormatError("bad layer record signature")
        blend_key = bytes(r.take(4))
        opacity = r.u8()
        clipping = r.u8() != 0
        flags = r.u8()
        r.skip(1)
        extra_end = r.u32()
        extra_end += r.pos

        mask = self._read_mask_data(r)
        r.skip(r.u32())                              # blending ranges
        name_len = r.u8()
        name = bytes(r.take(name_len)).decode("latin-1", "replace")
        r.skip((4 - (1 + name_len) % 4) % 4)

        rec = PsdLayerRecord(name=name, rect=rect, blend_key=blend_key,
                             opacity=opacity, fill_opacity=255, clipping=clipping,
                             visible=not (flags & 0x02), mask=mask,
                             channel_ids=ids, channel_lengths=lengths)
        for key, block in _iter_tagged_blocks(r, extra_end):
            self._apply_tagged_block(rec, key, block)
        return rec

    @staticmethod
    def _read_mask_data(r: _Reader) -> _MaskInfo | None:
        size = r.u32()
        end = r.pos + size
        mask = None
        if size >= 18:
            rect = _Rect(r.i32(), r.i32(), r.i32(), r.i32())
            default_color = r.u8()
            flags = r.u8()
            mask = _MaskInfo(rect, default_color, disabled=bool(flags & 0x02))
        r.pos = end
        return mask

    def _apply_tagged_block(self, rec: PsdLayerRecord, key: bytes, block: memoryview) -> None:
        if key == b"luni" and len(block) >= 4:
            n = struct.unpack_from(">I", block, 0)[0]
            rec.name = bytes(block[4:4 + 2 * n]).decode("utf-16-be", "replace").rstrip("\0")
        elif key in (b"lsct", b"lsdk") and len(block) >= 4:
            rec.section = struct.unpack_from(">I", block, 0)[0]
            if len(block) >= 12:
                rec.section_blend_key = bytes(block[8:12])
        elif key == b"iOpa" and len(block) >= 1:
            rec.fill_opacity = block[0]
        elif key in (b"vmsk", b"vsms"):
            rec.vector_mask = _VectorMaskReader(self.width, self.height).read(block)
        elif key in (b"lfx2", b"lmfx") and len(block) > 8:
            # 'lmfx' (several effects of a kind) wins over 'lfx2'.
            if key == b"lmfx" or rec.effects is None:
                try:
                    rec.effects = _DescriptorReader(bytes(block[8:])).read()
                except PsdFormatError as e:
                    logger.warning("Effects of PSD layer %r not imported: %s", rec.name, e)
        elif key == b"CgEd":
            rec.adjustment_blocks[key] = bytes(block)
        elif key in _ADJUSTMENT_KEYS:
            rec.is_adjustment = True
            rec.adjustment_blocks[key] = bytes(block)
            if key in _FILL_KEYS:
                rec.fill_key = key
                rec.fill = self._read_fill(key, block, rec.name)

    def _read_fill(self, key: bytes, block: memoryview, name: str) -> _Fill | None:
        """'SoCo' / 'GdFl' settings (version + descriptor), or None for
        pattern fills and anything unreadable."""
        if key not in (b"SoCo", b"GdFl") or len(block) <= 4:
            return None
        try:
            desc = _DescriptorReader(bytes(block[4:])).read()
            if key == b"SoCo":
                clr = desc.get("Clr ")
                rgb = self.descriptor_rgb(clr) if isinstance(clr, dict) else None
                return _SolidFill(rgb) if rgb is not None else None
            return _GradientFill(desc, self.descriptor_rgb)
        except PsdFormatError as e:
            logger.warning("Fill of PSD layer %r not imported: %s", name, e)
            return None

    def descriptor_rgb(self, clr: dict) -> tuple | None:
        """sRGB of a descriptor colour. CMYK / gray colours of a CMYK / gray
        document go through its ICC profile, like its pixels."""
        cls = clr.get("_class")
        channels = None
        if cls == "CMYC" and isinstance(self.color_mode, _CmykMode):
            channels = [np.array([[255.0 - clr.get(k, 0.0) * 2.55]]).round().astype(np.uint8)
                        for k in ("Cyn ", "Mgnt", "Ylw ", "Blck")]
        elif cls == "Grsc" and type(self.color_mode) is _GrayMode:
            channels = [np.array([[255.0 - clr.get("Gry ", 0.0) * 2.55]]).round().astype(np.uint8)]
        if channels is not None:
            return tuple(int(v) for v in self.colors.to_rgb(channels)[0, 0])
        color = _descriptor_color(clr)
        return (color.red(), color.green(), color.blue()) if color is not None else None

    # ----------------------------------------------------------- pixel data
    @staticmethod
    def has_pixels(rec: PsdLayerRecord) -> bool:
        """Fill layers often have a rect but no channel data at all."""
        return (rec.rect.width > 0 and rec.rect.height > 0 and
                any(cid >= 0 and len(data) > 2 for cid, data in rec.channel_data.items()))

    def _layer_planes(self, rec: PsdLayerRecord) -> tuple[np.ndarray, np.ndarray]:
        """(h, w, 3) RGB and (h, w) alpha of the layer's own rect."""
        w, h = rec.rect.width, rec.rect.height
        mode = self.color_mode
        colour = [self.decoder.decode(rec.channel_data.get(cid, memoryview(b"")), w, h,
                                      mode.linear_channels)
                  for cid in mode.channel_ids]
        if -1 in rec.channel_data:
            alpha = self.decoder.decode(rec.channel_data[-1], w, h, linear=False)
        else:
            alpha = np.full((h, w), 255, np.uint8)
        return self.colors.to_rgb(colour), alpha

    def layer_rgba(self, rec: PsdLayerRecord) -> np.ndarray | None:
        """(h, w, 4) straight-alpha RGBA of the layer's own rect."""
        if not self.has_pixels(rec):
            return None
        rgb, alpha = self._layer_planes(rec)
        return np.dstack([rgb, alpha])

    def paste_layer(self, rec: PsdLayerRecord, canvas: np.ndarray) -> bool:
        """Write the layer's pixels into a document-size (H, W, 4) RGBA
        array, without building a full RGBA copy of the rect first (these
        are tens of MB per layer). False when the layer has no pixels."""
        if not self.has_pixels(rec):
            return False
        rgb, alpha = self._layer_planes(rec)
        _paste(canvas[..., :3], rgb, rec.rect.left, rec.rect.top)
        _paste(canvas[..., 3], alpha, rec.rect.left, rec.rect.top)
        return True

    def layer_mask(self, rec: PsdLayerRecord) -> np.ndarray | None:
        """Document-size 0..1 mask values, or None when the layer has none.
        Outside its own rect a PSD mask is its default colour."""
        m = rec.mask
        if m is None:
            return None
        values = np.full((self.height, self.width), m.default_color / 255.0, np.float32)
        mw, mh = m.rect.width, m.rect.height
        if -2 in rec.channel_data and mw and mh:
            src = self.decoder.decode(rec.channel_data[-2], mw, mh, linear=False)
            _paste(values, src.astype(np.float32) / 255.0, m.rect.left, m.rect.top)
        return values

    def merged_rgba(self) -> np.ndarray:
        """The flattened image stored after the layer section."""
        r = self._r
        r.pos = self._merged_offset
        w, h = self.width, self.height
        compression = r.u16()
        body = r.data[r.pos:]
        dec = self.decoder
        plane = dec.row_bytes(w) * h
        n = self.channel_count
        if compression == 1:
            count_size = 4 if r.psb else 2
            counts = np.frombuffer(bytes(body[:n * h * count_size]),
                                   ">u4" if count_size == 4 else ">u2").astype(np.int64)
            per_channel = counts.reshape(n, h).sum(axis=1)
            offset = n * h * count_size
            raws = []
            for i in range(n):
                size = int(per_channel[i])
                raws.append(_unpack_bits(memoryview(body)[offset:offset + size], plane))
                offset += size
        elif compression == 0:
            raws = [bytes(body[i * plane:(i + 1) * plane]).ljust(plane, b"\0") for i in range(n)]
        else:
            all_raw = dec.decompress(compression, memoryview(body), w, h * n)
            raws = [all_raw[i * plane:(i + 1) * plane] for i in range(n)]

        mode = self.color_mode
        colour = [dec.to_uint8(raws[i], w, h, mode.linear_channels) if i < n
                  else np.zeros((h, w), np.uint8)
                  for i in range(len(mode.channel_ids))]
        alpha_index = len(mode.channel_ids)
        if self.merged_has_alpha and alpha_index < n:
            alpha = dec.to_uint8(raws[alpha_index], w, h, linear=False)
        else:
            alpha = np.full((h, w), 255, np.uint8)
        return np.dstack([self.colors.to_rgb(colour), alpha])


def _paste(dst: np.ndarray, src: np.ndarray, left: int, top: int) -> None:
    """Copy `src` into `dst` at (left, top), clipped to `dst`."""
    h, w = dst.shape[:2]
    sh, sw = src.shape[:2]
    x1, y1 = max(0, left), max(0, top)
    x2, y2 = min(w, left + sw), min(h, top + sh)
    if x1 < x2 and y1 < y2:
        dst[y1:y2, x1:x2] = src[y1 - top:y2 - top, x1 - left:x2 - left]


# ── PSD -> Document ──────────────────────────────────────────────────────────

# PSD blend keys -> stored values from core.blend_modes. Anything else
# (Pass Through, Linear Burn, Hue, Color, ...) has no QPainter equivalent
# and opens as Normal.
_BLEND_MODES = {
    b"mul ": "Multiply",
    b"scrn": "Screen",
    b"over": "Overlay",
    b"dark": "Darken",
    b"lite": "Lighten",
    b"div ": "ColorDodge",
    b"idiv": "ColorBurn",
    b"hLit": "HardLight",
    b"sLit": "SoftLight",
    b"diff": "Difference",
    b"smud": "Exclusion",
}


class PsdImporter:
    """Builds a Document from one .psd/.psb file."""

    def __init__(self, path: str):
        self._path = path
        self._psd: PsdFile | None = None
        self._doc: Document | None = None
        self.skipped_layers = 0     # unsupported adjustment / pattern / noise-gradient layers

    def load(self) -> Document:
        with open(self._path, "rb") as f:
            self._psd = PsdFile(f.read())
        psd = self._psd
        self._doc = Document(psd.width, psd.height)
        self._doc.layers = []                # no default Background layer
        if psd.layers:
            self._add_layers(psd.layers)
        if not self._doc.layers:
            self._add_merged()
        self._doc.active_layer_index = len(self._doc.layers) - 1
        return self._doc

    def _add_layers(self, records: list) -> None:
        open_groups: list[GroupLayer] = []
        for rec in records:
            parent_id = open_groups[-1].layer_id if open_groups else None
            if rec.section == _SECTION_BOUNDARY:
                group = GroupLayer("", self._doc.width, self._doc.height)
                group.parent_id = parent_id
                open_groups.append(group)
            elif rec.section in (_SECTION_OPEN, _SECTION_CLOSED):
                if open_groups:
                    group = open_groups.pop()
                else:                       # no divider below: empty group
                    group = GroupLayer("", self._doc.width, self._doc.height)
                    group.parent_id = parent_id
                self._copy_common(rec, group)
                group.expanded = rec.section == _SECTION_OPEN
                self._doc.layers.append(group)
            elif rec.is_adjustment and not self._has_content(rec):
                if not self._add_adjustment_layer(rec, parent_id):
                    self.skipped_layers += 1
            else:
                self._add_pixel_layer(rec, parent_id)
        # A file missing a group's closing record: keep the group anyway.
        while open_groups:
            group = open_groups.pop()
            group.name = group.name or tr("layer.name.group")
            self._doc.layers.append(group)

    def _has_content(self, rec: PsdLayerRecord) -> bool:
        """Stored pixels, or a colour / gradient fill we can paint ourselves.
        Adjustment layers have neither; pattern fills without stored pixels
        aren't rendered."""
        return self._psd.has_pixels(rec) or rec.fill is not None

    def _add_pixel_layer(self, rec: PsdLayerRecord, parent_id: str | None) -> None:
        w, h = self._doc.width, self._doc.height
        layer = RasterLayer(rec.name, w, h)
        layer.parent_id = parent_id
        vm = rec.vector_mask
        canvas = np.zeros((h, w, 4), np.uint8)
        if self._psd.paste_layer(rec, canvas):
            layer.image = _rgba_to_qimage(canvas)
            # A fill/shape layer's stored pixels already are the shape;
            # on any other layer the vector mask is applied on top.
            if vm is not None and rec.fill_key is None:
                layer.vector_mask = vm.path
                layer.vector_mask_enabled = not vm.disabled
        elif rec.fill is not None:
            shape = vm.path if vm is not None and not vm.disabled else None
            layer.image = rec.fill.paint(w, h, shape)
        self._copy_common(rec, layer)
        layer.clipping = rec.clipping
        mask = self._psd.layer_mask(rec)
        if mask is not None:
            layer.mask = gray_mask_image(mask)
            layer.mask_enabled = not rec.mask.disabled
        self._doc.layers.append(layer)

    def _add_adjustment_layer(self, rec: PsdLayerRecord, parent_id: str | None) -> bool:
        """Our adjustment layer for a Photoshop one; False if we have no
        such adjustment or can't read its settings."""
        from core.psd_adjustments import codec_for_blocks
        codec = codec_for_blocks(rec.adjustment_blocks)
        if codec is None:
            return False
        try:
            params = codec.read(rec.adjustment_blocks, self._psd)
        except (struct.error, PsdFormatError, IndexError, ValueError) as e:
            logger.warning("Adjustment layer %r not imported: %s", rec.name, e)
            params = None
        if params is None:
            return False
        layer = AdjustmentLayer(rec.name, self._doc.width, self._doc.height)
        layer.parent_id = parent_id
        layer.adjustment_data = {"type": codec.type, **params}
        self._copy_common(rec, layer)
        layer.clipping = rec.clipping
        vm = rec.vector_mask
        if vm is not None:
            layer.vector_mask = vm.path
            layer.vector_mask_enabled = not vm.disabled
        mask = self._psd.layer_mask(rec)
        if mask is not None:
            layer.mask = gray_mask_image(mask)
            layer.mask_enabled = not rec.mask.disabled
        self._doc.layers.append(layer)
        return True

    def _add_merged(self) -> None:
        layer = RasterLayer("Background", self._doc.width, self._doc.height)
        layer.image = _rgba_to_qimage(self._psd.merged_rgba())
        self._doc.layers.append(layer)

    def _copy_common(self, rec: PsdLayerRecord, layer: Layer) -> None:
        layer.name = rec.name
        layer.visible = rec.visible
        key = rec.section_blend_key or rec.blend_key
        layer.blend_mode = _BLEND_MODES.get(key, "SourceOver")
        styles = {}
        if rec.effects is not None and not layer.is_container:
            from core.psd_effects import layer_styles_from_effects
            styles = layer_styles_from_effects(rec.effects, self._psd.global_angle,
                                               self._psd.descriptor_rgb)
        if styles:
            # Fill opacity fades the layer's pixels, not its effects.
            layer.opacity = rec.opacity / 255.0
            if rec.fill_opacity < 255:
                styles["fill_opacity"] = rec.fill_opacity / 2.55
            layer.layer_styles = styles
        else:
            # Without effects, fill opacity acts like opacity.
            layer.opacity = (rec.opacity / 255.0) * (rec.fill_opacity / 255.0)


def _rgba_to_qimage(rgba: np.ndarray) -> QImage:
    h, w = rgba.shape[:2]
    rgba = np.ascontiguousarray(rgba)
    img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
