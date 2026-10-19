"""Photoshop .psd / .psb export — the counterpart of core/psd_import.py,
written straight from the file format (no PSD library).

What goes into the file, per layer:
  * pixels — what the layer looks like by itself (content, layer styles
    and vector mask applied; opacity, blend mode, mask and clipping are
    stored as PSD layer properties, as Photoshop keeps them);
  * name (Pascal + Unicode), visibility, opacity, blend mode, clipping,
    the layer mask;
  * groups as Photoshop's section dividers (open/closed, pass-through).

Text, shapes, Pen paths and fill layers are written as their rendered
pixels (Photoshop's own text/shape data isn't documented well enough to
write); adjustment layers have no pixels and are skipped. `PsdExporter`
counts both so the UI can say so. The merged image (the composite) is
written too, so viewers that don't read layers still show the picture.

8-bit RGB with alpha; RLE (PackBits) compression; PSB above 30000 px."""
from __future__ import annotations

import struct

import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColorSpace, QImage, QPainter, QTransform

from core.layer import AdjustmentLayer, Layer, LiveRenderedLayer
from core.pixel_buffer import qimage_argb_view

_PSD_MAX = 30000

# stored blend-mode values (core/blend_modes.py) -> PSD keys
_BLEND_KEYS = {
    "SourceOver": b"norm", "Normal": b"norm",
    "Multiply": b"mul ", "Screen": b"scrn", "Overlay": b"over",
    "Darken": b"dark", "Lighten": b"lite", "ColorDodge": b"div ", "ColorBurn": b"idiv",
    "HardLight": b"hLit", "SoftLight": b"sLit", "Difference": b"diff", "Exclusion": b"smud",
}

# Section divider types
_OPEN_FOLDER, _CLOSED_FOLDER, _BOUNDING_DIVIDER = 1, 2, 3


# ── channel encoding ─────────────────────────────────────────────────────────

class _RleEncoder:
    """PackBits per row. Uniform rows (empty areas — most of a layer the
    size of the canvas) become repeat runs; other rows literal runs. That
    keeps the encoder numpy-fast; the files stay valid PackBits that every
    PSD reader takes."""

    def __init__(self, psb: bool):
        self._count_fmt = ">I" if psb else ">H"

    def encode(self, plane: np.ndarray) -> bytes:
        """Compression word + row byte counts + rows."""
        h, w = plane.shape
        if h == 0 or w == 0:
            return struct.pack(">H", 0)
        uniform = (plane == plane[:, :1]).all(axis=1)
        rows = []
        for y in range(h):
            row = plane[y]
            if uniform[y]:
                v = bytes((int(row[0]),))
                full, rest = divmod(w, 128)
                out = (bytes((129,)) + v) * full            # 257 - 128 = 129: 128 copies
                if rest == 1:
                    out += b"\x00" + v
                elif rest:
                    out += bytes((257 - rest,)) + v
            else:
                data = row.tobytes()
                out = b"".join(bytes((len(data[i:i + 128]) - 1,)) + data[i:i + 128]
                               for i in range(0, w, 128))
            rows.append(out)
        counts = b"".join(struct.pack(self._count_fmt, len(r)) for r in rows)
        return struct.pack(">H", 1) + counts + b"".join(rows)


def _rgba_planes(img: QImage) -> list[np.ndarray]:
    """R, G, B, A (straight alpha) planes of a QImage."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8)
    arr = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    return [np.ascontiguousarray(arr[..., i]) for i in range(4)]


# ── what each layer contributes ──────────────────────────────────────────────

class _LayerPixels:
    """A layer's own look (content + styles + vector mask; no opacity,
    blend, mask or clipping), rendered through the document's normal
    render_into chain so it matches the canvas exactly."""

    @staticmethod
    def render(doc, layer: Layer) -> tuple[QImage | None, QRect]:
        from core.render_context import CompositeContext
        probe = layer.copy(deep_image=False)
        probe.visible = True
        probe.opacity = 1.0
        probe.blend_mode = "SourceOver"
        probe.clipping = False
        probe.mask_enabled = False
        result = QImage(doc.width, doc.height, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(0)
        painter = QPainter(result)
        painter.setTransform(QTransform())
        ctx = CompositeContext(document=doc, result=result, painter=painter, children_map={})
        ctx.view_transform = QTransform()
        doc._render_layer_list([probe], None, ctx)
        if ctx.painter.isActive():
            ctx.painter.end()
        bounds = doc._nontransparent_bounds(result)
        if bounds.isEmpty():
            return None, QRect()
        return result.copy(bounds), bounds


# ── the writer ───────────────────────────────────────────────────────────────

class PsdExporter:
    """Writes one Document to a .psd (or .psb, when bigger than PSD allows)."""

    def __init__(self, doc):
        self._doc = doc
        self.psb = doc.width > _PSD_MAX or doc.height > _PSD_MAX
        self._rle = _RleEncoder(self.psb)
        self.rasterized = 0          # text / shape / fill layers written as pixels
        self.skipped = 0             # adjustment layers (no pixels to write)

    # ── public ──────────────────────────────────────────────────────
    def to_bytes(self) -> bytes:
        doc = self._doc
        out = bytearray()
        out += b"8BPS" + struct.pack(">H6xHIIHH", 2 if self.psb else 1, 4,
                                     doc.height, doc.width, 8, 3)
        out += struct.pack(">I", 0)                        # colour mode data
        out += self._image_resources()
        out += self._layer_and_mask_section()
        out += self._merged_image()
        return bytes(out)

    def save(self, path: str) -> None:
        from core.serialization import _atomic_write
        data = self.to_bytes()

        def _write(tmp_path):
            with open(tmp_path, "wb") as f:
                f.write(data)
        _atomic_write(path, _write)

    # ── sections ────────────────────────────────────────────────────
    def _len(self, n: int) -> bytes:
        return struct.pack(">Q" if self.psb else ">I", n)

    @staticmethod
    def _image_resources() -> bytes:
        icc = bytes(QColorSpace(QColorSpace.NamedColorSpace.SRgb).iccProfile())
        block = b"8BIM" + struct.pack(">H", 1039) + b"\x00\x00" + struct.pack(">I", len(icc)) + icc
        if len(icc) % 2:
            block += b"\x00"
        return struct.pack(">I", len(block)) + block

    def _layer_and_mask_section(self) -> bytes:
        entries = self._entries()
        if not entries:
            info = b""
        else:
            records, channel_data = b"", b""
            for e in entries:
                rec, data = self._record(e)
                records += rec
                channel_data += data
            # Negative count: the merged image's alpha is transparency.
            info = struct.pack(">h", -len(entries)) + records + channel_data
            if len(info) % 2:
                info += b"\x00"
        section = self._len(len(info)) + info + struct.pack(">I", 0)   # + global mask info
        return self._len(len(section)) + section

    def _merged_image(self) -> bytes:
        planes = _rgba_planes(self._doc.get_composite(respect_live_hidden=False))
        rows_counts, rows_data = b"", b""
        for plane in planes:
            enc = self._rle.encode(plane)
            n = self._doc.height * (4 if self.psb else 2)
            rows_counts += enc[2:2 + n]
            rows_data += enc[2 + n:]
        return struct.pack(">H", 1) + rows_counts + rows_data

    # ── layers ──────────────────────────────────────────────────────
    def _entries(self) -> list[dict]:
        """Layer records bottom-to-top, groups as divider + children + group."""
        doc = self._doc
        children: dict = {}
        for layer in doc.layers:
            children.setdefault(getattr(layer, "parent_id", None), []).append(layer)
        out: list[dict] = []

        def walk(parent_id):
            for layer in children.get(parent_id, []):
                if layer.is_container:
                    out.append({"divider": True})
                    walk(layer.layer_id)
                    out.append({"group": layer})
                elif isinstance(layer, AdjustmentLayer):
                    self.skipped += 1
                else:
                    if isinstance(layer, LiveRenderedLayer) or getattr(layer, "SETTINGS_LAYER", False):
                        self.rasterized += 1
                    out.append({"layer": layer})
        walk(None)
        return out

    def _record(self, e: dict) -> tuple[bytes, bytes]:
        if e.get("divider"):
            return self._layer_record("</Layer group>", QRect(), {}, None, 255, False, True,
                                      b"norm", self._section(_BOUNDING_DIVIDER))
        if "group" in e:
            g = e["group"]
            kind = _OPEN_FOLDER if getattr(g, "expanded", True) else _CLOSED_FOLDER
            return self._layer_record(g.name, QRect(), {}, None, self._opacity(g), False, g.visible,
                                      b"pass", self._section(kind, b"pass"))
        layer = e["layer"]
        img, rect = _LayerPixels.render(self._doc, layer)
        channels = {}
        if img is not None:
            r, g, b, a = _rgba_planes(img)
            channels = {-1: a, 0: r, 1: g, 2: b}
        mask = self._mask(layer)
        return self._layer_record(layer.name, rect, channels, mask, self._opacity(layer),
                                  bool(getattr(layer, "clipping", False)), layer.visible,
                                  _BLEND_KEYS.get(getattr(layer, "blend_mode", "SourceOver"), b"norm"), b"")

    @staticmethod
    def _opacity(layer) -> int:
        return max(0, min(255, int(round(float(getattr(layer, "opacity", 1.0)) * 255))))

    @staticmethod
    def _mask(layer):
        """(rect, default colour, disabled, plane) or None. Masks of
        canvas-covering layers reveal outside themselves; a pixel layer's
        mask covers its own image."""
        mask = getattr(layer, "mask", None)
        if mask is None:
            return None
        from core.layer import _CanvasCoveringLayer
        off = layer.offset if not isinstance(layer, _CanvasCoveringLayer) else layer.offset * 0
        plane = _rgba_planes(mask)[1]                    # grey: any colour channel
        rect = QRect(off.x(), off.y(), mask.width(), mask.height())
        default = 255 if isinstance(layer, _CanvasCoveringLayer) else 0
        return rect, default, not getattr(layer, "mask_enabled", True), plane

    def _section(self, kind: int, blend: bytes | None = None) -> bytes:
        data = struct.pack(">I", kind)
        if blend:
            data += b"8BIM" + blend
        return self._tag(b"lsct", data)

    @staticmethod
    def _tag(key: bytes, data: bytes) -> bytes:
        if len(data) % 2:
            data += b"\x00"
        return b"8BIM" + key + struct.pack(">I", len(data)) + data

    def _layer_record(self, name: str, rect: QRect, channels: dict, mask, opacity: int,
                      clipping: bool, visible: bool, blend: bytes, extra_tags: bytes) -> tuple[bytes, bytes]:
        if mask is not None:
            channels = dict(channels)
            channels[-2] = mask[3]
        data = {cid: self._rle.encode(plane) for cid, plane in channels.items()}
        if not data:                 # every layer needs its colour channels, even empty
            data = {cid: struct.pack(">H", 0) for cid in (-1, 0, 1, 2)}
        top, left = (rect.y(), rect.x()) if not rect.isEmpty() else (0, 0)
        bottom, right = (rect.y() + rect.height(), rect.x() + rect.width()) if not rect.isEmpty() else (0, 0)
        head = struct.pack(">4iH", top, left, bottom, right, len(data))
        for cid, d in data.items():
            head += struct.pack(">h", cid) + self._len(len(d))
        flags = 0 if visible else 0x02
        head += b"8BIM" + blend + struct.pack(">BBBB", opacity, 1 if clipping else 0, flags, 0)

        extra = b""
        if mask is not None:
            mrect, default, disabled, _plane = mask
            extra += struct.pack(">I4iBB2x", 20, mrect.y(), mrect.x(), mrect.y() + mrect.height(),
                                 mrect.x() + mrect.width(), default, 0x02 if disabled else 0)
        else:
            extra += struct.pack(">I", 0)
        extra += struct.pack(">I", 0)                                     # blending ranges
        pascal = name.encode("mac_roman", "replace")[:255]
        pascal = bytes((len(pascal),)) + pascal
        extra += pascal + b"\x00" * ((4 - len(pascal) % 4) % 4)
        units = name.encode("utf-16-be")
        extra += self._tag(b"luni", struct.pack(">I", len(units) // 2) + units)
        extra += extra_tags
        head += struct.pack(">I", len(extra)) + extra
        return head, b"".join(data.values())
