"""The file formats ImageFinish saves to, and how each one is written.

Three writers: the native .imfn (layers, live text/shapes), Photoshop
.psd/.psb (core/psd_export.py: layers as pixels) and every flat image
format Qt can encode (Qt's own plugins, qt6-imageformats, kimageformats).
`available_formats()` lists only what this installation can really write,
so the Save dialog never offers a format that would then fail."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageFormat:
    key: str                     # Qt writer name for "qt" formats
    label: str                   # shown in the file dialog
    extensions: tuple            # first one is the default
    writer: str = "qt"           # "imfn" | "psd" | "qt"
    alpha: bool = True           # keeps transparency (else flattened on white)
    lossy: bool = False          # has a quality setting
    max_size: int | None = None  # largest side the format allows
    square_sizes: tuple = ()     # only these square sizes (Apple icons)

    @property
    def filter(self) -> str:
        return f"{self.label} ({' '.join('*.' + e for e in self.extensions)})"

    @property
    def default_extension(self) -> str:
        return self.extensions[0]


FORMATS: tuple[ImageFormat, ...] = (
    ImageFormat("imfn", "ImageFinish", ("imfn",), writer="imfn"),
    ImageFormat("psd", "Photoshop", ("psd", "psb"), writer="psd"),
    ImageFormat("png", "PNG", ("png",)),
    ImageFormat("jpeg", "JPEG", ("jpg", "jpeg", "jfif"), alpha=False, lossy=True),
    ImageFormat("webp", "WebP", ("webp",), lossy=True),
    ImageFormat("avif", "AVIF", ("avif",), lossy=True),
    ImageFormat("jxl", "JPEG XL", ("jxl",), lossy=True),
    ImageFormat("heif", "HEIF", ("heic", "heif"), lossy=True),
    ImageFormat("jp2", "JPEG 2000", ("jp2", "j2k"), lossy=True),
    ImageFormat("tiff", "TIFF", ("tif", "tiff")),
    ImageFormat("bmp", "BMP", ("bmp",), alpha=False),
    ImageFormat("tga", "Targa", ("tga",)),
    ImageFormat("qoi", "QOI", ("qoi",)),
    ImageFormat("exr", "OpenEXR", ("exr",)),
    ImageFormat("dds", "DirectDraw Surface", ("dds",)),
    ImageFormat("ico", "Windows Icon", ("ico",), max_size=256),
    ImageFormat("cur", "Windows Cursor", ("cur",), max_size=256),
    ImageFormat("icns", "Apple Icon", ("icns",), square_sizes=(16, 32, 64, 128, 256, 512, 1024)),
    ImageFormat("sgi", "SGI", ("sgi", "rgb", "rgba")),
    ImageFormat("pcx", "PCX", ("pcx",), alpha=False),
    ImageFormat("ppm", "PPM", ("ppm",), alpha=False),
    ImageFormat("pgm", "PGM", ("pgm",), alpha=False),
    ImageFormat("pbm", "PBM", ("pbm",), alpha=False),
    ImageFormat("xpm", "XPM", ("xpm",)),
    ImageFormat("xbm", "XBM", ("xbm",), alpha=False),
    ImageFormat("wbmp", "WBMP", ("wbmp",), alpha=False),
)


def _qt_writable() -> set[str]:
    from PyQt6.QtGui import QImageWriter
    return {bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()}


def available_formats() -> list[ImageFormat]:
    """Formats this installation can write, in the Save dialog's order."""
    qt = _qt_writable()
    return [f for f in FORMATS if f.writer != "qt" or f.key in qt]


def format_for_path(path: str) -> ImageFormat | None:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    for f in available_formats():
        if ext in f.extensions:
            return f
    return None


def format_for_filter(selected_filter: str) -> ImageFormat | None:
    for f in available_formats():
        if f.filter == selected_filter:
            return f
    return None


def save_filter() -> str:
    return ";;".join(f.filter for f in available_formats())


def readable_extensions() -> list[str]:
    """Every extension the app can open: .imfn, .psd/.psb and whatever Qt reads."""
    from PyQt6.QtGui import QImageReader
    exts = ["imfn", "psd", "psb"]
    for f in QImageReader.supportedImageFormats():
        e = bytes(f).decode().lower()
        if e not in exts:
            exts.append(e)
    return exts


def open_filter(all_supported: str, all_files: str, images_only: bool = False) -> str:
    """"All supported (…)", the main formats one by one, "All files"."""
    exts = readable_extensions()
    if images_only:
        exts = [e for e in exts if e not in ("imfn", "psd", "psb")]
    parts = [f"{all_supported} ({' '.join('*.' + e for e in exts)})"]
    for f in available_formats():
        if images_only and f.writer != "qt":
            continue
        parts.append(f.filter)
    parts.append(f"{all_files} (*)")
    return ";;".join(parts)


def prepare_flat_image(img, fmt: ImageFormat):
    """The composite as `fmt` can hold it: flattened on white when the
    format has no transparency (as Photoshop's JPEG export does — Qt would
    otherwise turn transparent pixels black), scaled down to the format's
    size limit (icons)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    if not fmt.alpha:
        flat = QImage(img.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor(255, 255, 255))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    if fmt.max_size and max(img.width(), img.height()) > fmt.max_size:
        img = img.scaled(fmt.max_size, fmt.max_size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    if fmt.square_sizes:
        # The largest allowed square the picture fills, picture centred.
        side = max(img.width(), img.height())
        fits = [s for s in fmt.square_sizes if s <= side] or [fmt.square_sizes[0]]
        size = fits[-1]
        scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        square = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        square.fill(Qt.GlobalColor.transparent)
        p = QPainter(square)
        p.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        p.end()
        img = square
    return img


def write_flat_image(img, path: str, fmt: ImageFormat, quality: int = -1) -> None:
    """Encode through Qt's writer for `fmt`, atomically (a failed write
    never leaves a half-written file in place of the old one)."""
    from PyQt6.QtGui import QImageWriter
    from core.serialization import SerializationError, _atomic_write
    if img.isNull():
        raise SerializationError("Nothing to save: image is empty")
    img = prepare_flat_image(img, fmt)

    def _write(tmp_path):
        writer = QImageWriter(tmp_path, fmt.key.encode())
        if fmt.lossy and quality >= 0:
            writer.setQuality(int(quality))
        if not writer.write(img):
            raise SerializationError(f"Could not encode image as {fmt.label}: {writer.errorString()}")
    _atomic_write(path, _write)
