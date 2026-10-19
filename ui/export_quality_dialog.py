"""Quality for lossy formats (JPEG, WebP, AVIF, JPEG XL, HEIF, JPEG 2000),
asked on Save As like Photoshop's JPEG Options, remembered per format and
reused by Ctrl+S."""
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QVBoxLayout

from core.locale import tr
from ui.adjustments_dialog import _SliderRow
from ui.base_dialog import BaseDialog

DEFAULT_QUALITY = 90


def remembered_quality(fmt) -> int:
    value = QSettings("ImageFinish", "Export").value(f"quality/{fmt.key}", DEFAULT_QUALITY)
    try:
        return max(1, min(100, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_QUALITY


def remember_quality(fmt, quality: int) -> None:
    QSettings("ImageFinish", "Export").setValue(f"quality/{fmt.key}", int(quality))


class ExportQualityDialog(BaseDialog):
    def __init__(self, fmt, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.export_quality_title", format=fmt.label))
        lay = QVBoxLayout(self)
        self._quality = _SliderRow(tr("dlg.export_quality"), 1, 100, remembered_quality(fmt))
        lay.addLayout(self._quality)
        self.add_button_box(lay)

    def quality(self) -> int:
        return self._quality.value()


def ask_quality(fmt, parent=None) -> int | None:
    """The chosen quality (and remembered), or None when cancelled."""
    dlg = ExportQualityDialog(fmt, parent)
    if not dlg.exec():
        return None
    remember_quality(fmt, dlg.quality())
    return dlg.quality()
