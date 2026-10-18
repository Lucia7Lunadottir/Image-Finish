"""Brush controls shared by the options bar (ui/tool_options/brush_options.py),
the Brushes panel and the right-click brush picker — one implementation
of each, so they behave the same and stay in step.

- `tip_library()`: the tips (core/brush_tips.py) plus a `changed` signal,
  so a tip loaded or defined anywhere shows up in every list at once.
- `SliderSpin`: the options bar's slider + number field.
- `BrushTipGrid`: clickable tip thumbnails.
- `BrushTipPreview`: the stamp the current settings paint.
"""
from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                             QSpinBox, QWidget)

from core import brush_tips
from core.locale import tr
from ui import theme
from ui.adjustments_dialog import _JumpSlider


# ── tip library ──────────────────────────────────────────────────────────────
class _TipLibrary(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._tips = None

    def tips(self) -> list:
        if self._tips is None:
            self._tips = brush_tips.available_tips()
        return self._tips

    def title(self, tip) -> str:
        return tr(tip.title_key) if tip.title_key else tip.name

    def import_file(self, path: str) -> str:
        value = brush_tips.import_tip_file(path)
        self.reload()
        return value

    def add_image(self, name: str, img: QImage) -> str:
        value = brush_tips.save_tip_image(name, img)
        self.reload()
        return value

    def reload(self):
        self._tips = None
        self.changed.emit()


_LIBRARY = None


def tip_library() -> _TipLibrary:
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _TipLibrary()
    return _LIBRARY


def tip_pixmap(value, size: int, hardness: float = 1.0, color: QColor | None = None) -> QPixmap:
    """The tip as it paints, tinted (theme text colour by default)."""
    stamp = brush_tips.tip_stamp(size, hardness, value).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(stamp)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(stamp.rect(), color or QColor(theme.TEXT))
    p.end()
    return QPixmap.fromImage(stamp)


def tip_icon(value, size: int = 32) -> QIcon:
    return QIcon(tip_pixmap(value, size - 4))


# ── slider + number ──────────────────────────────────────────────────────────
class SliderSpin(QWidget):
    """A jump-to-click slider with a number field next to it. The field may
    go past the slider's range (brush size up to 5000 px on a 1–500
    slider); the slider then just stays at its end."""

    valueChanged = pyqtSignal(int)

    def __init__(self, lo: int, slider_hi: int, spin_hi: int | None = None, suffix: str = "",
                 slider_width: int = 100, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, slider_hi)
        self.slider.setFixedWidth(slider_width)
        self.spin = QSpinBox()
        self.spin.setRange(lo, spin_hi if spin_hi is not None else slider_hi)
        self.spin.setSuffix(suffix)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        lay.addWidget(self.slider)
        lay.addWidget(self.spin)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, value: int):
        """Set without emitting (syncing from the options)."""
        for w in (self.slider, self.spin):
            w.blockSignals(True)
        self.spin.setValue(int(value))
        self.slider.setValue(min(int(value), self.slider.maximum()))
        for w in (self.slider, self.spin):
            w.blockSignals(False)

    def _from_slider(self, v):
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(min(v, self.slider.maximum()))
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)


# ── tip thumbnails ───────────────────────────────────────────────────────────
class _TipThumb(QLabel):
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)

    def __init__(self, value: str, tooltip: str, size: int, parent=None):
        super().__init__(parent)
        self.value = value
        self.setPixmap(tip_pixmap(value, size - 8))
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip(tooltip)
        self.set_selected(False)

    def set_selected(self, selected: bool):
        border = theme.ACCENT if selected else "transparent"
        self.setStyleSheet(f"border:2px solid {border};border-radius:4px;background:{theme.MANTLE};")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.value)
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.value)
        super().mouseDoubleClickEvent(ev)


class BrushTipGrid(QScrollArea):
    """All tips as thumbnails; follows the library."""

    tip_selected = pyqtSignal(str)
    tip_activated = pyqtSignal(str)     # double click
    rows_changed = pyqtSignal()

    def __init__(self, columns: int = 3, thumb: int = 64, parent=None):
        super().__init__(parent)
        self._columns, self._thumb = columns, thumb
        self._current = "round"
        self._thumbs: list[_TipThumb] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme.apply_style(self, lambda: f"QScrollArea{{border:none;background:{theme.BASE};}}")
        self._body = QWidget()
        theme.apply_style(self._body, lambda: f"background:{theme.BASE};")
        self._grid = QGridLayout(self._body)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(4)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self._body)
        tip_library().changed.connect(self._rebuild)
        self._rebuild()

    def set_current(self, value):
        self._current = value
        for t in self._thumbs:
            t.set_selected(t.value == value)

    def current(self):
        return self._current

    def _rebuild(self):
        for t in self._thumbs:
            t.deleteLater()
        self._thumbs.clear()
        lib = tip_library()
        for i, tip in enumerate(lib.tips()):
            thumb = _TipThumb(tip.value, lib.title(tip), self._thumb)
            thumb.clicked.connect(self._on_click)
            thumb.double_clicked.connect(self.tip_activated)
            self._grid.addWidget(thumb, i // self._columns, i % self._columns)
            self._thumbs.append(thumb)
        self.set_current(self._current)
        self.rows_changed.emit()

    def row_count(self) -> int:
        return -(-len(self._thumbs) // self._columns)

    def _on_click(self, value):
        self.set_current(value)
        self.tip_selected.emit(value)


# ── stamp preview ────────────────────────────────────────────────────────────
class BrushTipPreview(QWidget):
    """The stamp at the current size, hardness and angle — actual size when
    it fits, scaled down otherwise (the size is written underneath)."""

    def __init__(self, box: int = 120, parent=None):
        super().__init__(parent)
        self._box = box
        self._size, self._hardness, self._tip, self._angle = 10, 1.0, "round", 0.0
        self.setFixedHeight(box + 20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(self._box, self._box + 20)

    def set_brush(self, size: int, hardness: float, tip, angle: float = 0.0):
        self._size, self._hardness, self._tip, self._angle = int(size), float(hardness), tip, float(angle)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(0, 0, self.width(), self._box)
        p.fillRect(area, QColor(theme.MANTLE))
        shown = min(self._size, self._box - 8)
        pix = tip_pixmap(self._tip, shown if self._size > self._box - 8 else self._size,
                         self._hardness)
        p.save()
        p.translate(area.center())
        p.rotate(self._angle)
        p.drawPixmap(QPointF(-pix.width() / 2, -pix.height() / 2), pix)
        p.restore()
        p.setPen(QColor(theme.SUBTEXT))
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        p.drawText(QRectF(0, self._box, self.width(), 20), Qt.AlignmentFlag.AlignCenter,
                   f"{self._size} px")
        p.end()
