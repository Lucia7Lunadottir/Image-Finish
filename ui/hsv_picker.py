"""
hsv_picker.py -- HSV Color Picker with hue wheel, eyedropper, and recent colors.

Contains:
  - HueSaturationMap : SV square (Saturation x Value) for a given Hue
  - HueSlider       : horizontal rainbow bar for hue selection
  - HueWheel        : conical hue ring with embedded SV square
  - AlphaSlider     : alpha transparency slider with checker background
  - ScreenPicker     : fullscreen overlay for picking a color from the screen
  - ColorPickerDialog: full dialog with preview, hex field, HSV/RGB spinboxes,
                       mode toggle (square/wheel), eyedropper, and recent colors
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QSpinBox, QPushButton, QWidget,
                             QDialogButtonBox, QSizePolicy, QApplication,
                             QStackedWidget, QGridLayout, QFrame)
from PyQt6.QtCore    import Qt, QPoint, QPointF, QRect, pyqtSignal, QSize
from PyQt6.QtGui     import (QPainter, QColor, QLinearGradient, QConicalGradient,
                             QRadialGradient, QImage, QPixmap, QPen, QBrush,
                             QPainterPath, QScreen, QCursor)
import math


# Module-level recent colors list (persists across dialog invocations)
_recent_colors: list[QColor] = []
_MAX_RECENT = 16


# ─────────────────────────────────────────────────────────────────────────────
class HueSaturationMap(QWidget):
    """SV square: X = Saturation (0..1), Y = Value (1..0 top-to-bottom).
    Hue is set externally. Click/drag changes S and V."""
    sv_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue   = 0.0
        self._sat   = 1.0
        self._val   = 1.0
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._cache: QPixmap | None = None
        self._cache_hue: float = -1.0
        self._cache_size: QSize = QSize(0, 0)

    def set_hue(self, hue: float):
        if abs(hue - self._hue) > 0.001:
            self._hue = hue
            self._cache = None
            self.update()

    def set_sv(self, s: float, v: float):
        self._sat = s
        self._val = v
        self.update()

    def _build_cache(self):
        """Build SV map using two overlaid gradients (no per-pixel loop)."""
        w, h = self.width(), self.height()
        pix = QPixmap(w, h)
        p = QPainter(pix)

        base = QColor.fromHsvF(self._hue, 1.0, 1.0)
        p.fillRect(0, 0, w, h, base)

        white_grad = QLinearGradient(0, 0, w, 0)
        white_grad.setColorAt(0, QColor(255, 255, 255, 255))
        white_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, h, white_grad)

        black_grad = QLinearGradient(0, 0, 0, h)
        black_grad.setColorAt(0, QColor(0, 0, 0, 0))
        black_grad.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, w, h, black_grad)

        p.end()
        self._cache = pix
        self._cache_hue = self._hue
        self._cache_size = QSize(w, h)

    def paintEvent(self, _e):
        if (self._cache is None or self._cache_hue != self._hue
                or self._cache_size != self.size()):
            self._build_cache()

        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        cx = int(self._sat * (self.width() - 1))
        cy = int((1.0 - self._val) * (self.height() - 1))
        p.setPen(QPen(Qt.GlobalColor.black, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPoint(cx, cy), 7, 7)
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.drawEllipse(QPoint(cx, cy), 6, 6)
        p.end()

    def _update_from_pos(self, pos: QPoint):
        s = max(0.0, min(1.0, pos.x() / max(1, self.width() - 1)))
        v = max(0.0, min(1.0, 1.0 - pos.y() / max(1, self.height() - 1)))
        self._sat, self._val = s, v
        self.update()
        self.sv_changed.emit(s, v)

    def mousePressEvent(self, e):
        self._update_from_pos(e.pos())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_pos(e.pos())


# ─────────────────────────────────────────────────────────────────────────────
class HueSlider(QWidget):
    """Horizontal rainbow bar for selecting hue (0..360)."""
    hue_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def set_hue(self, h: float):
        self._hue = h
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), 0)
        for stop in range(7):
            grad.setColorAt(stop / 6, QColor.fromHsvF(stop / 6, 1.0, 1.0))
        p.fillRect(self.rect(), grad)
        p.setPen(QPen(QColor(40, 40, 60), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        cx = int(self._hue * (self.width() - 1))
        p.setPen(QPen(Qt.GlobalColor.black, 2))
        p.drawLine(cx, 0, cx, self.height())
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.drawLine(cx, 1, cx, self.height() - 1)
        p.end()

    def _update_from_x(self, x: int):
        h = max(0.0, min(0.9999, x / max(1, self.width() - 1)))
        self._hue = h
        self.update()
        self.hue_changed.emit(h)

    def mousePressEvent(self, e):
        self._update_from_x(e.pos().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_x(e.pos().x())


# ─────────────────────────────────────────────────────────────────────────────
class HueWheel(QWidget):
    """Conical hue ring with an embedded SV square inside."""
    hue_changed = pyqtSignal(float)
    sv_changed = pyqtSignal(float, float)

    RING_WIDTH = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._sat = 1.0
        self._val = 1.0
        self._dragging_ring = False
        self._dragging_sv = False
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._ring_cache: QPixmap | None = None
        self._ring_cache_size: int = 0
        self._sv_cache: QPixmap | None = None
        self._sv_cache_hue: float = -1.0
        self._sv_cache_size: int = 0

    def set_hue(self, h: float):
        if abs(h - self._hue) > 0.001:
            self._hue = h
            self._sv_cache = None
            self.update()

    def set_sv(self, s: float, v: float):
        self._sat = s
        self._val = v
        self.update()

    def _outer_r(self):
        return min(self.width(), self.height()) // 2 - 2

    def _inner_r(self):
        return self._outer_r() - self.RING_WIDTH

    def _center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    def _sv_rect(self):
        ir = self._inner_r()
        side = int(ir * math.sqrt(2)) - 4
        c = self._center()
        half = side / 2
        return QRect(int(c.x() - half), int(c.y() - half), side, side)

    def _build_ring_cache(self):
        sz = min(self.width(), self.height())
        pix = QPixmap(self.width(), self.height())
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = self._center()
        outer = self._outer_r()
        inner = self._inner_r()

        cg = QConicalGradient(c, 90)
        for i in range(13):
            cg.setColorAt(i / 12, QColor.fromHsvF((i / 12) % 1.0, 1.0, 1.0))

        ring = QPainterPath()
        ring.addEllipse(c, outer, outer)
        hole = QPainterPath()
        hole.addEllipse(c, inner, inner)
        ring_path = ring - hole

        p.fillPath(ring_path, QBrush(cg))
        p.setPen(QPen(QColor(30, 30, 40), 1))
        p.drawEllipse(c, outer, outer)
        p.drawEllipse(c, inner, inner)
        p.end()

        self._ring_cache = pix
        self._ring_cache_size = sz

    def _build_sv_cache(self):
        r = self._sv_rect()
        w, h = r.width(), r.height()
        if w <= 0 or h <= 0:
            return
        pix = QPixmap(w, h)
        p = QPainter(pix)

        base = QColor.fromHsvF(self._hue, 1.0, 1.0)
        p.fillRect(0, 0, w, h, base)

        wg = QLinearGradient(0, 0, w, 0)
        wg.setColorAt(0, QColor(255, 255, 255, 255))
        wg.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, h, wg)

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(0, 0, 0, 0))
        bg.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, w, h, bg)
        p.end()

        self._sv_cache = pix
        self._sv_cache_hue = self._hue
        self._sv_cache_size = w

    def paintEvent(self, _e):
        sz = min(self.width(), self.height())
        if self._ring_cache is None or self._ring_cache_size != sz:
            self._build_ring_cache()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._ring_cache)

        # Hue indicator on ring
        c = self._center()
        mid_r = (self._outer_r() + self._inner_r()) / 2
        angle = self._hue * 2 * math.pi + math.pi / 2
        hx = c.x() + mid_r * math.cos(angle)
        hy = c.y() - mid_r * math.sin(angle)
        p.setPen(QPen(Qt.GlobalColor.black, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(hx, hy), 6, 6)
        p.setPen(QPen(Qt.GlobalColor.white, 1.5))
        p.drawEllipse(QPointF(hx, hy), 5, 5)

        # SV square
        svr = self._sv_rect()
        if svr.width() > 0 and svr.height() > 0:
            if (self._sv_cache is None or self._sv_cache_hue != self._hue
                    or self._sv_cache_size != svr.width()):
                self._build_sv_cache()
            p.drawPixmap(svr.topLeft(), self._sv_cache)
            p.setPen(QPen(QColor(30, 30, 40), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(svr)

            # SV cursor
            sx = svr.x() + int(self._sat * (svr.width() - 1))
            sy = svr.y() + int((1.0 - self._val) * (svr.height() - 1))
            p.setPen(QPen(Qt.GlobalColor.black, 2))
            p.drawEllipse(QPoint(sx, sy), 6, 6)
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.drawEllipse(QPoint(sx, sy), 5, 5)

        p.end()

    def _is_on_ring(self, pos: QPoint) -> bool:
        c = self._center()
        dist = math.hypot(pos.x() - c.x(), pos.y() - c.y())
        return self._inner_r() <= dist <= self._outer_r()

    def _hue_from_pos(self, pos: QPoint) -> float:
        c = self._center()
        angle = math.atan2(-(pos.y() - c.y()), pos.x() - c.x())
        h = (angle - math.pi / 2) / (2 * math.pi)
        h = h % 1.0
        return min(h, 0.9999)

    def _sv_from_pos(self, pos: QPoint):
        svr = self._sv_rect()
        s = max(0.0, min(1.0, (pos.x() - svr.x()) / max(1, svr.width() - 1)))
        v = max(0.0, min(1.0, 1.0 - (pos.y() - svr.y()) / max(1, svr.height() - 1)))
        return s, v

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._is_on_ring(e.pos()):
            self._dragging_ring = True
            h = self._hue_from_pos(e.pos())
            self._hue = h
            self._sv_cache = None
            self.update()
            self.hue_changed.emit(h)
        elif self._sv_rect().contains(e.pos()):
            self._dragging_sv = True
            s, v = self._sv_from_pos(e.pos())
            self._sat, self._val = s, v
            self.update()
            self.sv_changed.emit(s, v)

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._dragging_ring:
            h = self._hue_from_pos(e.pos())
            self._hue = h
            self._sv_cache = None
            self.update()
            self.hue_changed.emit(h)
        elif self._dragging_sv:
            s, v = self._sv_from_pos(e.pos())
            self._sat, self._val = s, v
            self.update()
            self.sv_changed.emit(s, v)

    def mouseReleaseEvent(self, e):
        self._dragging_ring = False
        self._dragging_sv = False


# ─────────────────────────────────────────────────────────────────────────────
class AlphaSlider(QWidget):
    """Alpha transparency slider (0..255) with checker background."""
    alpha_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alpha = 255
        self._color = QColor(255, 0, 0)
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def set_color(self, c: QColor):
        self._color = c
        self.update()

    def set_alpha(self, a: int):
        self._alpha = a
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        tile = 8
        for tx in range(0, self.width(), tile):
            for ty in range(0, self.height(), tile):
                shade = QColor(200, 200, 200) if (tx // tile + ty // tile) % 2 == 0 else QColor(240, 240, 240)
                p.fillRect(tx, ty, tile, tile, shade)

        c_transp = QColor(self._color)
        c_transp.setAlpha(0)
        c_opaque = QColor(self._color)
        c_opaque.setAlpha(255)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0, c_transp)
        grad.setColorAt(1, c_opaque)
        p.fillRect(self.rect(), grad)

        p.setPen(QPen(QColor(40, 40, 60), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        cx = int(self._alpha / 255 * (self.width() - 1))
        p.setPen(QPen(Qt.GlobalColor.black, 2))
        p.drawLine(cx, 0, cx, self.height())
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.drawLine(cx, 1, cx, self.height() - 1)
        p.end()

    def _update_from_x(self, x: int):
        a = max(0, min(255, int(x / max(1, self.width() - 1) * 255)))
        self._alpha = a
        self.update()
        self.alpha_changed.emit(a)

    def mousePressEvent(self, e):
        self._update_from_x(e.pos().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_x(e.pos().x())


# ─────────────────────────────────────────────────────────────────────────────
class ColorPreview(QWidget):
    """Old color | New color preview rectangle with checker background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._old = QColor(0, 0, 0)
        self._new = QColor(0, 0, 0)
        self.setFixedHeight(32)

    def set_old(self, c: QColor): self._old = c; self.update()
    def set_new(self, c: QColor): self._new = c; self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w = self.width()
        tile = 8
        for side, color, x0 in [("old", self._old, 0), ("new", self._new, w // 2)]:
            for tx in range(x0, x0 + w // 2, tile):
                for ty in range(0, self.height(), tile):
                    shade = QColor(200, 200, 200) if ((tx - x0) // tile + ty // tile) % 2 == 0 else QColor(240, 240, 240)
                    p.fillRect(tx, ty, tile, tile, shade)
            p.fillRect(x0, 0, w // 2, self.height(), color)
        p.setPen(QPen(QColor(40, 40, 60), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.drawLine(w // 2, 0, w // 2, self.height())
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
class ScreenPicker(QWidget):
    """Fullscreen overlay for picking a color from the screen."""
    color_picked = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._screenshot: QPixmap | None = None

    def start(self):
        screen = QApplication.primaryScreen()
        if screen:
            self._screenshot = screen.grabWindow(0)
        geo = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
        self.setGeometry(geo)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, _e):
        p = QPainter(self)
        if self._screenshot:
            p.drawPixmap(0, 0, self._screenshot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 30))
        p.end()

    def mousePressEvent(self, e):
        if self._screenshot:
            img = self._screenshot.toImage()
            pos = e.pos()
            if 0 <= pos.x() < img.width() and 0 <= pos.y() < img.height():
                c = QColor(img.pixel(pos.x(), pos.y()))
                self.color_picked.emit(c)
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()


# ─────────────────────────────────────────────────────────────────────────────
class _RecentSwatch(QFrame):
    """Small clickable color square for the recent colors strip."""
    clicked = pyqtSignal(QColor)

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        tile = 4
        for tx in range(0, self.width(), tile):
            for ty in range(0, self.height(), tile):
                shade = QColor(180, 180, 180) if (tx // tile + ty // tile) % 2 == 0 else QColor(220, 220, 220)
                p.fillRect(tx, ty, tile, tile, shade)
        p.fillRect(self.rect(), self._color)
        p.setPen(QPen(QColor(60, 60, 80), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, _e):
        self.clicked.emit(self._color)


# ─────────────────────────────────────────────────────────────────────────────
def _spin(lo: int, hi: int, val: int, width: int = 58) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setFixedWidth(width)
    return s


def _label(text: str) -> QLabel:
    l = QLabel(text)
    l.setFixedWidth(22)
    l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    l.setStyleSheet("color: #a6adc8; font-size: 12px;")
    return l


# ─────────────────────────────────────────────────────────────────────────────
class ColorPickerDialog(QDialog):
    """Full HSV color picker with hue wheel, eyedropper, and recent colors.

    Usage:
        color = ColorPickerDialog.get_color(initial, parent, title)
    """

    def __init__(self, initial: QColor = None, parent=None, title: str = "Pick Color"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(320, 520)
        self.resize(400, 600)

        if initial is None:
            initial = QColor(0, 0, 0)
        self._color = QColor(initial)
        self._old_color = QColor(initial)
        self._updating = False
        self._screen_picker: ScreenPicker | None = None

        self._build_ui()
        self._load_color(self._color)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Mode toggle
        toggle_row = QHBoxLayout()
        self._mode_btn = QPushButton("Wheel")
        self._mode_btn.setFixedSize(60, 24)
        self._mode_btn.setToolTip("Switch between Square and Wheel mode")
        self._mode_btn.clicked.connect(self._toggle_mode)
        toggle_row.addStretch()
        toggle_row.addWidget(self._mode_btn)
        root.addLayout(toggle_row)

        # Stacked widget: square mode vs wheel mode
        self._mode_stack = QStackedWidget()

        # -- Square mode (SV map + hue slider)
        square_w = QWidget()
        sq_lay = QVBoxLayout(square_w)
        sq_lay.setContentsMargins(0, 0, 0, 0)
        sq_lay.setSpacing(6)
        self._sv_map = HueSaturationMap()
        self._sv_map.sv_changed.connect(self._on_sv_changed)
        sq_lay.addWidget(self._sv_map)
        sq_lay.addWidget(QLabel("Hue", styleSheet="color:#a6adc8;font-size:11px;"))
        self._hue_slider = HueSlider()
        self._hue_slider.hue_changed.connect(self._on_hue_changed)
        sq_lay.addWidget(self._hue_slider)

        # -- Wheel mode
        wheel_w = QWidget()
        wh_lay = QVBoxLayout(wheel_w)
        wh_lay.setContentsMargins(0, 0, 0, 0)
        self._hue_wheel = HueWheel()
        self._hue_wheel.hue_changed.connect(self._on_hue_changed)
        self._hue_wheel.sv_changed.connect(self._on_sv_changed)
        wh_lay.addWidget(self._hue_wheel)

        self._mode_stack.addWidget(square_w)  # index 0
        self._mode_stack.addWidget(wheel_w)   # index 1
        self._mode_stack.setCurrentIndex(0)
        root.addWidget(self._mode_stack, 1)

        # Alpha slider
        root.addWidget(QLabel("Alpha", styleSheet="color:#a6adc8;font-size:11px;"))
        self._alpha_slider = AlphaSlider()
        self._alpha_slider.alpha_changed.connect(self._on_alpha_changed)
        root.addWidget(self._alpha_slider)

        # Preview
        self._preview = ColorPreview()
        self._preview.set_old(self._old_color)
        root.addWidget(self._preview)

        # HSV row
        hsv_row = QHBoxLayout()
        hsv_row.setSpacing(4)
        self._spin_h = _spin(0, 359, 0)
        self._spin_s = _spin(0, 255, 0)
        self._spin_v = _spin(0, 255, 255)
        for lbl, sp in [("H", self._spin_h), ("S", self._spin_s), ("V", self._spin_v)]:
            hsv_row.addWidget(_label(lbl))
            hsv_row.addWidget(sp)
        hsv_row.addStretch()
        root.addLayout(hsv_row)

        # RGB row
        rgb_row = QHBoxLayout()
        rgb_row.setSpacing(4)
        self._spin_r = _spin(0, 255, 0)
        self._spin_g = _spin(0, 255, 0)
        self._spin_b = _spin(0, 255, 0)
        for lbl, sp in [("R", self._spin_r), ("G", self._spin_g), ("B", self._spin_b)]:
            rgb_row.addWidget(_label(lbl))
            rgb_row.addWidget(sp)
        rgb_row.addStretch()
        root.addLayout(rgb_row)

        # Alpha + Hex + Eyedropper row
        hex_row = QHBoxLayout()
        hex_row.setSpacing(4)
        self._spin_a = _spin(0, 255, 255)
        hex_row.addWidget(_label("A"))
        hex_row.addWidget(self._spin_a)
        hex_row.addSpacing(8)
        hex_label = QLabel("#")
        hex_label.setStyleSheet("color:#a6adc8; font-size:13px;")
        self._hex_edit = QLineEdit()
        self._hex_edit.setMaxLength(8)
        self._hex_edit.setFixedWidth(80)
        self._hex_edit.setPlaceholderText("RRGGBBAA")
        hex_row.addWidget(hex_label)
        hex_row.addWidget(self._hex_edit)
        hex_row.addSpacing(4)

        self._eyedropper_btn = QPushButton("\u2388")  # ⎈ target symbol
        self._eyedropper_btn.setToolTip("Pick color from screen")
        self._eyedropper_btn.setFixedSize(28, 28)
        self._eyedropper_btn.clicked.connect(self._start_eyedropper)
        hex_row.addWidget(self._eyedropper_btn)
        hex_row.addStretch()
        root.addLayout(hex_row)

        # Recent colors
        self._recent_layout = QHBoxLayout()
        self._recent_layout.setSpacing(2)
        self._recent_label = QLabel("Recent:")
        self._recent_label.setStyleSheet("color:#a6adc8;font-size:11px;")
        self._recent_layout.addWidget(self._recent_label)
        self._rebuild_recent_swatches()
        self._recent_layout.addStretch()
        root.addLayout(self._recent_layout)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Wire spin/hex signals
        self._spin_h.valueChanged.connect(self._on_hsv_spin)
        self._spin_s.valueChanged.connect(self._on_hsv_spin)
        self._spin_v.valueChanged.connect(self._on_hsv_spin)
        self._spin_r.valueChanged.connect(self._on_rgb_spin)
        self._spin_g.valueChanged.connect(self._on_rgb_spin)
        self._spin_b.valueChanged.connect(self._on_rgb_spin)
        self._spin_a.valueChanged.connect(self._on_alpha_spin)
        self._hex_edit.editingFinished.connect(self._on_hex_edit)

    def _toggle_mode(self):
        if self._mode_stack.currentIndex() == 0:
            self._mode_stack.setCurrentIndex(1)
            self._mode_btn.setText("Square")
            self._hue_wheel.set_hue(self._hue_slider._hue)
            self._hue_wheel.set_sv(self._sv_map._sat, self._sv_map._val)
        else:
            self._mode_stack.setCurrentIndex(0)
            self._mode_btn.setText("Wheel")
            self._sv_map.set_hue(self._hue_wheel._hue)
            self._sv_map.set_sv(self._hue_wheel._sat, self._hue_wheel._val)
            self._hue_slider.set_hue(self._hue_wheel._hue)

    def _rebuild_recent_swatches(self):
        # Remove old swatches (keep the label at index 0)
        while self._recent_layout.count() > 1:
            item = self._recent_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        for c in _recent_colors[:_MAX_RECENT]:
            sw = _RecentSwatch(c)
            sw.clicked.connect(self._on_recent_clicked)
            self._recent_layout.addWidget(sw)
        self._recent_layout.addStretch()

    def _on_recent_clicked(self, c: QColor):
        self._apply(c)

    def _start_eyedropper(self):
        self._screen_picker = ScreenPicker()
        self._screen_picker.color_picked.connect(self._on_screen_color)
        self.hide()
        self._screen_picker.start()

    def _on_screen_color(self, c: QColor):
        self.show()
        self._apply(c)

    def _load_color(self, c: QColor):
        self._updating = True
        h, s, v, a = c.hsvHue(), c.hsvSaturation(), c.value(), c.alpha()
        if h < 0:
            h = 0

        hf = h / 359.0
        sf = s / 255.0
        vf = v / 255.0

        self._sv_map.set_hue(hf)
        self._sv_map.set_sv(sf, vf)
        self._hue_slider.set_hue(hf)
        self._hue_wheel.set_hue(hf)
        self._hue_wheel.set_sv(sf, vf)
        self._alpha_slider.set_color(c)
        self._alpha_slider.set_alpha(a)
        self._preview.set_new(c)

        self._spin_h.setValue(h)
        self._spin_s.setValue(s)
        self._spin_v.setValue(v)
        self._spin_r.setValue(c.red())
        self._spin_g.setValue(c.green())
        self._spin_b.setValue(c.blue())
        self._spin_a.setValue(a)

        hex_str = f"{c.red():02X}{c.green():02X}{c.blue():02X}"
        if a < 255:
            hex_str += f"{a:02X}"
        self._hex_edit.setText(hex_str)
        self._updating = False

    def _apply(self, c: QColor):
        self._color = c
        self._load_color(c)

    def _on_hue_changed(self, h: float):
        if self._updating:
            return
        c = QColor.fromHsvF(h, self._color.hsvSaturationF(),
                            self._color.valueF(), self._color.alphaF())
        self._apply(c)

    def _on_sv_changed(self, s: float, v: float):
        if self._updating:
            return
        hue = self._color.hsvHueF()
        if hue < 0:
            hue = 0.0
        c = QColor.fromHsvF(hue, s, v, self._color.alphaF())
        self._apply(c)

    def _on_alpha_changed(self, a: int):
        if self._updating:
            return
        c = QColor(self._color)
        c.setAlpha(a)
        self._apply(c)

    def _on_hsv_spin(self):
        if self._updating:
            return
        c = QColor.fromHsv(self._spin_h.value(), self._spin_s.value(),
                           self._spin_v.value(), self._spin_a.value())
        self._apply(c)

    def _on_rgb_spin(self):
        if self._updating:
            return
        c = QColor(self._spin_r.value(), self._spin_g.value(),
                   self._spin_b.value(), self._spin_a.value())
        self._apply(c)

    def _on_alpha_spin(self):
        if self._updating:
            return
        c = QColor(self._color)
        c.setAlpha(self._spin_a.value())
        self._apply(c)

    def _on_hex_edit(self):
        if self._updating:
            return
        text = self._hex_edit.text().strip().lstrip("#")
        try:
            if len(text) == 6:
                r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
                c = QColor(r, g, b, self._color.alpha())
            elif len(text) == 8:
                r, g, b, a = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16)
                c = QColor(r, g, b, a)
            else:
                return
            self._apply(c)
        except ValueError:
            pass

    def accept(self):
        global _recent_colors
        c = QColor(self._color)
        # Deduplicate
        _recent_colors = [rc for rc in _recent_colors if rc.name() != c.name() or rc.alpha() != c.alpha()]
        _recent_colors.insert(0, c)
        _recent_colors = _recent_colors[:_MAX_RECENT]
        super().accept()

    def color(self) -> QColor:
        return self._color

    @staticmethod
    def get_color(initial: QColor = None, parent=None, title: str = "Pick Color") -> QColor | None:
        """Returns picked QColor or None if cancelled."""
        dlg = ColorPickerDialog(initial, parent, title)
        if dlg.exec():
            return dlg.color()
        return None
