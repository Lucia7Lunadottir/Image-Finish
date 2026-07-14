"""Document serialization: the versioned .imfn v2 format and legacy loading.

Design (SOLID):
- `DocumentSerializer` is the abstract interface; the rest of the app only
  calls the `load_document` / `save_document` facades.
- `ImfnZipSerializer` — current format, version 2: a ZIP container with
  `manifest.json` (metadata, JSON-safe) and one PNG entry per layer image.
- `LegacyPickleSerializer` — the old gzip+pickle format, read-only, kept so
  existing user files continue to open.

All writes are atomic: temp file in the target directory + os.replace.
"""

import gzip
import json
import os
import pickle
import tempfile
import zipfile
from abc import ABC, abstractmethod

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QColor, QImage

from core.app_logging import get_logger

logger = get_logger("serialization")

FORMAT_VERSION = 2
_MANIFEST_NAME = "manifest.json"


class SerializationError(Exception):
    """User-facing load/save failure; message is safe to show in a dialog."""


# ── Qt value <-> JSON-safe encoding ──────────────────────────────────────────

def encode_qt(obj):
    """Recursively convert Qt value objects inside plain containers to
    JSON-safe tagged dicts. Tuples become lists (JSON has no tuples)."""
    if isinstance(obj, QColor):
        return {"__qt__": "QColor", "v": obj.name(QColor.NameFormat.HexArgb)}
    if isinstance(obj, QPoint):
        return {"__qt__": "QPoint", "v": [obj.x(), obj.y()]}
    if isinstance(obj, QPointF):
        return {"__qt__": "QPointF", "v": [obj.x(), obj.y()]}
    if isinstance(obj, QRect):
        return {"__qt__": "QRect", "v": [obj.x(), obj.y(), obj.width(), obj.height()]}
    if isinstance(obj, QRectF):
        return {"__qt__": "QRectF", "v": [obj.x(), obj.y(), obj.width(), obj.height()]}
    if isinstance(obj, dict):
        return {k: encode_qt(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [encode_qt(v) for v in obj]
    if isinstance(obj, bytes):
        # Binary blobs do not belong in the manifest.
        raise SerializationError("Unexpected binary data in layer metadata")
    return obj


def decode_qt(obj):
    if isinstance(obj, dict):
        tag = obj.get("__qt__")
        if tag is None:
            return {k: decode_qt(v) for k, v in obj.items()}
        v = obj.get("v")
        if tag == "QColor":
            return QColor(v)
        if tag == "QPoint":
            return QPoint(int(v[0]), int(v[1]))
        if tag == "QPointF":
            return QPointF(v[0], v[1])
        if tag == "QRect":
            return QRect(int(v[0]), int(v[1]), int(v[2]), int(v[3]))
        if tag == "QRectF":
            return QRectF(v[0], v[1], v[2], v[3])
        logger.warning("Unknown Qt tag in manifest: %r", tag)
        return None
    if isinstance(obj, list):
        return [decode_qt(v) for v in obj]
    return obj


# ── Interface ────────────────────────────────────────────────────────────────

class DocumentSerializer(ABC):
    @abstractmethod
    def can_load(self, path: str) -> bool:
        """Cheap sniff (magic bytes), no full parse."""

    @abstractmethod
    def load(self, path: str):
        """Return a Document. Raises SerializationError on invalid input."""

    def save(self, doc, path: str) -> None:
        raise SerializationError("This format is read-only")


def _read_magic(path: str, n: int = 4) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError as e:
        raise SerializationError(f"Cannot read file: {e}") from e


def _atomic_write(path: str, write_fn) -> None:
    """Call write_fn(tmp_path), then atomically move tmp over path."""
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".imfn-save-", dir=dir_)
    os.close(fd)
    try:
        write_fn(tmp)
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── .imfn v2: ZIP(manifest.json + PNG layers) ───────────────────────────────

class ImfnZipSerializer(DocumentSerializer):
    MAGIC = b"PK\x03\x04"

    def can_load(self, path: str) -> bool:
        return _read_magic(path).startswith(self.MAGIC)

    def save(self, doc, path: str) -> None:
        layers_meta = []
        blobs = []  # (zip_name, bytes)
        for i, layer in enumerate(doc.layers):
            d = layer.to_dict()
            img_bytes = d.pop("image", None)
            mask_bytes = d.pop("mask", None)
            smart_bytes = d.pop("smart_data_original", None)
            if img_bytes:
                name = f"layers/{i:03d}.png"
                blobs.append((name, img_bytes))
                d["image"] = name
            else:
                d["image"] = None
            if mask_bytes:
                name = f"layers/{i:03d}.mask.png"
                blobs.append((name, mask_bytes))
                d["mask"] = name
            else:
                d["mask"] = None
            if smart_bytes:
                name = f"layers/{i:03d}.smart.png"
                blobs.append((name, smart_bytes))
                d["smart_data_original"] = name
            layers_meta.append(encode_qt(d))

        manifest = {
            "format": "imfn",
            "version": FORMAT_VERSION,
            "width": doc.width,
            "height": doc.height,
            "color_mode": getattr(doc, "color_mode", "RGB"),
            "bit_depth": getattr(doc, "bit_depth", 8),
            "active_layer_index": getattr(doc, "active_layer_index", 0),
            "layers": layers_meta,
        }
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=1)

        def _write(tmp_path):
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(_MANIFEST_NAME, manifest_json)
                for name, data in blobs:
                    # PNG is already compressed — store as-is.
                    zf.writestr(name, data, zipfile.ZIP_STORED)

        _atomic_write(path, _write)
        logger.info("Saved %s (v%d, %d layers)", path, FORMAT_VERSION, len(doc.layers))

    def load(self, path: str):
        from core.document import Document
        from core.layer import Layer
        try:
            zf = zipfile.ZipFile(path, "r")
        except (zipfile.BadZipFile, OSError) as e:
            raise SerializationError(f"Not a valid ImageFinish file: {e}") from e

        with zf:
            try:
                manifest = json.loads(zf.read(_MANIFEST_NAME).decode("utf-8"))
            except KeyError:
                raise SerializationError("Missing manifest.json — file is corrupted")
            except (ValueError, UnicodeDecodeError) as e:
                raise SerializationError(f"Corrupted manifest: {e}") from e

            if manifest.get("format") != "imfn":
                raise SerializationError("Not an ImageFinish document")
            version = manifest.get("version", 0)
            if not isinstance(version, int) or version > FORMAT_VERSION:
                raise SerializationError(
                    f"File format version {version} is newer than this "
                    f"application supports ({FORMAT_VERSION})")
            for key in ("width", "height", "layers"):
                if key not in manifest:
                    raise SerializationError(f"Corrupted manifest: missing {key!r}")
            w, h = int(manifest["width"]), int(manifest["height"])
            if w <= 0 or h <= 0:
                raise SerializationError(f"Invalid document size {w}x{h}")

            def read_blob(name):
                if not name:
                    return None
                try:
                    return zf.read(name)
                except KeyError:
                    raise SerializationError(f"Missing image data: {name}")

            doc = Document(w, h)
            doc.color_mode = manifest.get("color_mode", "RGB")
            doc.bit_depth = manifest.get("bit_depth", 8)
            layers = []
            for meta in manifest["layers"]:
                d = decode_qt(meta)
                d["image"] = read_blob(d.get("image"))
                d["mask"] = read_blob(d.get("mask"))
                if d.get("smart_data_original"):
                    d["smart_data_original"] = read_blob(d["smart_data_original"])
                layer = Layer.from_dict(d, w, h)
                if d["image"] and layer.image.isNull():
                    raise SerializationError(
                        f"Layer {d.get('name', '?')!r} image data is corrupted")
                layers.append(layer)
            if layers:
                doc.layers = layers
            idx = manifest.get("active_layer_index", 0)
            doc.active_layer_index = max(0, min(int(idx), len(doc.layers) - 1))
            return doc


# ── legacy v1: gzip + pickle (read-only) ─────────────────────────────────────

class LegacyPickleSerializer(DocumentSerializer):
    MAGIC = b"\x1f\x8b"

    def can_load(self, path: str) -> bool:
        return _read_magic(path).startswith(self.MAGIC)

    def load(self, path: str):
        from core.document import Document
        from core.layer import Layer
        try:
            with gzip.open(path, "rb") as f:
                data = pickle.load(f)
        except Exception as e:
            raise SerializationError(f"Cannot read legacy file: {e}") from e
        if not isinstance(data, dict) or "width" not in data or "height" not in data:
            raise SerializationError("Legacy file has unexpected structure")
        doc = Document(data["width"], data["height"])
        doc.color_mode = data.get("color_mode", "RGB")
        doc.bit_depth = data.get("bit_depth", 8)
        layers = [Layer.from_dict(ld, doc.width, doc.height)
                  for ld in data.get("layers", [])]
        if layers:
            doc.layers = layers
        doc.active_layer_index = len(doc.layers) - 1
        logger.info("Loaded legacy .imfn (v1 pickle): %s", path)
        return doc


# ── Facades ──────────────────────────────────────────────────────────────────

_SERIALIZERS: list[DocumentSerializer] = [
    ImfnZipSerializer(),
    LegacyPickleSerializer(),
]


def load_document(path: str):
    """Load a document, auto-detecting the format by magic bytes.
    Returns (document, was_legacy_format)."""
    for ser in _SERIALIZERS:
        if ser.can_load(path):
            return ser.load(path), isinstance(ser, LegacyPickleSerializer)
    raise SerializationError("Unknown file format — not an ImageFinish document")


def save_document(doc, path: str) -> None:
    """Save in the current format (v2), atomically."""
    ImfnZipSerializer().save(doc, path)


def save_image_atomic(img: QImage, path: str) -> None:
    """Atomic QImage export; format derived from the target extension."""
    ext = os.path.splitext(path)[1].lstrip(".").upper() or "PNG"
    if ext == "JPG":
        ext = "JPEG"

    def _write(tmp_path):
        if img.isNull():
            raise SerializationError("Nothing to save: image is empty")
        if not img.save(tmp_path, ext):
            raise SerializationError(f"Could not encode image as {ext}")

    _atomic_write(path, _write)
