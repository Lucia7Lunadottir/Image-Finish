"""Curves adjustment dialog — per-channel draggable tone curve over a
histogram backdrop, real-time canvas preview, black/gray/white-point
eyedroppers sampling straight from the document canvas, and a freehand
(pencil) draw mode."""

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QDialogButtonBox, QWidget, QSizePolicy, QSpinBox,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QEvent, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QPainterPath

from core.locale import tr
from ui.base_dialog import BaseDialog
from ui.adjustments_dialog import _to_argb32
from ui.levels_dialog import compute_histogram
from core.adjustments.curves import apply_curves, spline_lut, IDENTITY_POINTS

from ui import theme

_CHANNELS = ("rgb", "r", "g", "b")
_CHANNEL_LABEL_KEYS = {"rgb": "ch.rgb", "r": "ch.red", "g": "ch.green", "b": "ch.blue"}
_HIT_RADIUS = 9.0


def _luma(color: QColor) -> int:
    return round(0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue())


class _CurveWidget(QWidget):
    """Draggable tone-curve editor for one channel at a time.

    Point mode: click empty space to add a point, drag a point to move it,
    right-click (or double-click) a point to delete it — endpoints can move
    in both X and Y (so the black/white eyedropper can clip them inward)
    but never be removed, so the curve always spans the full input range.

    Freehand mode: drag across the graph to paint the curve directly, like
    Photoshop/Photopea's pencil tool. The stroke is stored as one point per
    input column (0..255), which the same monotone-spline LUT builder
    downstream renders essentially as-drawn (points 1 unit apart leave the
    spline no room to curve between them).
    """

    PAD = 14

    curve_changed = pyqtSignal()
    point_selected = pyqtSignal(object)  # (x, y) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._histograms = {ch: [0] * 256 for ch in _CHANNELS}
        self._points = {ch: list(IDENTITY_POINTS) for ch in _CHANNELS}
        self._channel = "rgb"
        self._drag_idx = None
        self._selected_idx = None
        self._freehand = False
        self._freehand_dragging = False
        self._freehand_samples: dict = {}
        self._last_freehand_x = None

    # ── data ────────────────────────────────────────────────────────────────

    def set_histograms(self, histograms: dict):
        self._histograms = histograms
        self.update()

    def set_channel(self, channel: str):
        self._channel = channel
        self._drag_idx = None
        self._selected_idx = None
        self.point_selected.emit(None)
        self.update()

    def set_freehand(self, on: bool):
        self._freehand = on
        self._drag_idx = None
        self._selected_idx = None
        self.point_selected.emit(None)
        self.update()

    def points(self) -> dict:
        return {ch: list(pts) for ch, pts in self._points.items()}

    def set_points(self, points: dict):
        self._points = {ch: list(points.get(ch) or IDENTITY_POINTS) for ch in _CHANNELS}
        self._selected_idx = None
        self.point_selected.emit(None)
        self.update()

    def reset_channel(self):
        self._points[self._channel] = list(IDENTITY_POINTS)
        self._drag_idx = None
        self._selected_idx = None
        self.point_selected.emit(None)
        self.update()
        self.curve_changed.emit()

    def set_selected_point_xy(self, x: int, y: int):
        """Move the currently selected point (spinboxes call this)."""
        i = self._selected_idx
        if i is None:
            return
        pts = self._points[self._channel]
        if i == 0:
            x = max(0, min(pts[1][0] - 1, x))
        elif i == len(pts) - 1:
            x = max(pts[i - 1][0] + 1, min(255, x))
        else:
            x = max(pts[i - 1][0] + 1, min(pts[i + 1][0] - 1, x))
        pts[i] = (x, max(0, min(255, y)))
        self.update()
        self.curve_changed.emit()

    def add_or_move_point(self, channel: str, x: int, y: int, *, anchor_end: str | None = None):
        """Used by the eyedropper: set the black/white endpoint of *channel*
        to (x, y): the endpoint's *input* moves to the sampled tone x while
        its *output* stays pinned at the black/white value passed in y —
        e.g. a black-point sample at input 51 becomes point (51, 0), so
        everything below input 51 clips to output 0, like Photoshop's
        Curves eyedroppers. With no anchor_end (gray point), inserts or
        moves an interior point instead."""
        pts = self._points[channel]
        if anchor_end == "min":
            x = max(0, min(pts[1][0] - 1, x))
            pts[0] = (x, max(0, min(255, y)))
        elif anchor_end == "max":
            x = max(pts[-2][0] + 1, min(255, x))
            pts[-1] = (x, max(0, min(255, y)))
        else:
            for i, (px, _py) in enumerate(pts):
                if px == x and 0 < i < len(pts) - 1:
                    pts[i] = (x, y)
                    break
            else:
                pts.append((x, y))
                pts.sort(key=lambda p: p[0])
        if channel == self._channel:
            self.update()
        self.curve_changed.emit()

    # ── coordinate mapping ────────────────────────────────────────────────────

    def _plot_rect(self) -> QRectF:
        return QRectF(self.PAD, self.PAD,
                      self.width() - 2 * self.PAD, self.height() - 2 * self.PAD)

    def _val_to_pt(self, x: float, y: float) -> QPointF:
        r = self._plot_rect()
        return QPointF(r.left() + x / 255.0 * r.width(),
                       r.bottom() - y / 255.0 * r.height())

    def _pos_to_val(self, pos: QPointF):
        r = self._plot_rect()
        x = (pos.x() - r.left()) / max(1.0, r.width()) * 255.0
        y = (r.bottom() - pos.y()) / max(1.0, r.height()) * 255.0
        return max(0, min(255, int(round(x)))), max(0, min(255, int(round(y))))

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()

        p.fillRect(self.rect(), QColor(theme.CRUST))

        # histogram (of the channel being edited)
        hist = self._histograms.get(self._channel) or [0] * 256
        max_c = max(hist) or 1
        bar_w = max(1.0, r.width() / 256.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE1))
        for i, c in enumerate(hist):
            if c == 0:
                continue
            bh = r.height() * (c / max_c) ** 0.5  # sqrt scale: low counts stay visible
            x = r.left() + i * bar_w
            p.drawRect(QRectF(x, r.bottom() - bh, bar_w, bh))

        # grid
        p.setPen(QPen(QColor(theme.SURFACE0), 1))
        for i in range(1, 4):
            gx = r.left() + r.width() * i / 4.0
            gy = r.top() + r.height() * i / 4.0
            p.drawLine(QPointF(gx, r.top()), QPointF(gx, r.bottom()))
            p.drawLine(QPointF(r.left(), gy), QPointF(r.right(), gy))

        p.setPen(QPen(QColor(theme.SURFACE1), 1))
        p.drawRect(r)

        # diagonal reference (identity) line
        p.setPen(QPen(QColor(theme.MUTED), 1, Qt.PenStyle.DashLine))
        p.drawLine(self._val_to_pt(0, 0), self._val_to_pt(255, 255))

        # curve (freehand strokes are dense enough that the spline is
        # essentially just connecting adjacent points — renders as drawn)
        pts = self._points[self._channel]
        lut = spline_lut(pts)
        path = QPainterPath()
        path.moveTo(self._val_to_pt(0, lut[0]))
        for x in range(1, 256):
            path.lineTo(self._val_to_pt(x, lut[x]))
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.drawPath(path)

        # control points (selected one gets a highlight ring) — skip in
        # freehand mode, where "points" is a dense 256-entry trace
        if not self._freehand:
            for i, (x, y) in enumerate(pts):
                center = self._val_to_pt(x, y)
                if i == self._selected_idx:
                    p.setPen(QPen(QColor(theme.TEXT), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(center, 7.5, 7.5)
                p.setPen(QPen(QColor(theme.TEXT), 1.5))
                p.setBrush(QColor(theme.ACCENT))
                p.drawEllipse(center, 4.5, 4.5)

        p.end()

    # ── mouse interaction: point mode ─────────────────────────────────────────

    def _hit_test(self, pos: QPointF):
        pts = self._points[self._channel]
        for i, (x, y) in enumerate(pts):
            if (self._val_to_pt(x, y) - pos).manhattanLength() < _HIT_RADIUS * 1.6:
                return i
        return None

    def _select(self, idx):
        self._selected_idx = idx
        pts = self._points[self._channel]
        self.point_selected.emit(pts[idx] if idx is not None else None)

    def _point_mouse_press(self, ev):
        pos = ev.position()
        idx = self._hit_test(pos)
        pts = self._points[self._channel]

        if ev.button() == Qt.MouseButton.RightButton:
            if idx is not None and 0 < idx < len(pts) - 1:
                pts.pop(idx)
                self._select(None)
                self.update()
                self.curve_changed.emit()
            return

        if ev.button() != Qt.MouseButton.LeftButton:
            return

        if idx is not None:
            self._drag_idx = idx
            self._select(idx)
            self.update()
            return

        x, y = self._pos_to_val(pos)
        pts.append((x, y))
        pts.sort(key=lambda p: p[0])
        new_idx = next(i for i, p in enumerate(pts) if p == (x, y))
        self._drag_idx = new_idx
        self._select(new_idx)
        self.update()
        self.curve_changed.emit()

    def _point_mouse_move(self, ev):
        if self._drag_idx is None:
            return
        pts = self._points[self._channel]
        i = self._drag_idx
        x, y = self._pos_to_val(ev.position())
        if i == 0:
            x = max(0, min(pts[1][0] - 1, x))
        elif i == len(pts) - 1:
            x = max(pts[i - 1][0] + 1, min(255, x))
        else:
            x = max(pts[i - 1][0] + 1, min(pts[i + 1][0] - 1, x))
        pts[i] = (x, y)
        self.update()
        self.curve_changed.emit()
        self.point_selected.emit(pts[i])

    # ── mouse interaction: freehand mode ──────────────────────────────────────

    def _freehand_mouse_press(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self._freehand_dragging = True
        self._freehand_samples = {}
        x, y = self._pos_to_val(ev.position())
        self._freehand_samples[x] = y
        self._last_freehand_x = x
        self._apply_freehand_samples()

    def _freehand_mouse_move(self, ev):
        if not self._freehand_dragging:
            return
        x, y = self._pos_to_val(ev.position())
        lx = self._last_freehand_x
        if lx is not None and x != lx:
            ly = self._freehand_samples.get(lx, y)
            step = 1 if x > lx else -1
            span = x - lx
            for xi in range(lx, x + step, step):
                t = (xi - lx) / span if span else 0.0
                self._freehand_samples[xi] = int(round(ly + (y - ly) * t))
        self._freehand_samples[x] = y
        self._last_freehand_x = x
        self._apply_freehand_samples()

    def _apply_freehand_samples(self):
        samples = self._freehand_samples
        if not samples:
            return
        lo, hi = min(samples), max(samples)
        y_lo, y_hi = samples[lo], samples[hi]
        pts = []
        for x in range(256):
            if x < lo:
                y = y_lo
            elif x > hi:
                y = y_hi
            else:
                y = samples[x]
            pts.append((x, y))
        self._points[self._channel] = pts
        self.update()
        self.curve_changed.emit()

    # ── mouse interaction: dispatch ────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if self._freehand:
            self._freehand_mouse_press(ev)
        else:
            self._point_mouse_press(ev)

    def mouseMoveEvent(self, ev):
        if self._freehand:
            self._freehand_mouse_move(ev)
        else:
            self._point_mouse_move(ev)

    def mouseReleaseEvent(self, _ev):
        self._drag_idx = None
        self._freehand_dragging = False
        self._last_freehand_x = None

    def mouseDoubleClickEvent(self, ev):
        if self._freehand:
            return
        pts = self._points[self._channel]
        idx = self._hit_test(ev.position())
        if idx is not None and 0 < idx < len(pts) - 1:
            pts.pop(idx)
            self._drag_idx = None
            self._select(None)
            self.update()
            self.curve_changed.emit()


class CurvesDialog(BaseDialog):
    """Non-destructive Curves dialog with real-time canvas preview.

    NON_BLOCKING = True: the black/gray/white-point eyedroppers need real
    mouse clicks on the main document canvas (like Photopea's own Curves,
    which reuses its main image view rather than an embedded copy) — but
    QDialog.exec() forces Qt::WA_ShowModal regardless of setModal(),
    blocking input to every other window in the app. Callers (see
    AdjustmentActionsMixin._show_adj_dialog and LayerActionsMixin.
    _new_adj_layer/_on_edit_layer) check this flag and use show() plus the
    `finished` signal instead of a blocking exec().
    """

    NON_BLOCKING = True
    _DEBOUNCE_MS = 40

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("adj.curves.title"))
        self.setModal(False)
        self.setMinimumSize(420, 620)

        self._image = image
        self._original = image.copy()
        self._orig_argb32 = _to_argb32(self._original)
        self._curve_points = {ch: list(IDENTITY_POINTS) for ch in _CHANNELS}
        self._picking = None       # "black" | "gray" | "white" | None
        self._pick_canvas = None

        argb = self._orig_argb32
        self._histograms = {
            "rgb": compute_histogram(argb),
            "r": _channel_histogram(argb, 2),
            "g": _channel_histogram(argb, 1),
            "b": _channel_histogram(argb, 0),
        }

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._apply_preview)

        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setSpacing(8)

        ch_row = QHBoxLayout()
        ch_lbl = QLabel(tr("adj.curves.channel"))
        self._ch_combo = QComboBox()
        for ch in _CHANNELS:
            self._ch_combo.addItem(tr(_CHANNEL_LABEL_KEYS[ch]), ch)
        self._ch_combo.currentIndexChanged.connect(self._on_channel_changed)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem(tr("adj.curves.mode_smooth"), "smooth")
        self._mode_combo.addItem(tr("adj.curves.mode_freehand"), "freehand")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        ch_row.addWidget(ch_lbl)
        ch_row.addWidget(self._ch_combo, 1)
        ch_row.addWidget(self._mode_combo, 1)
        lo.addLayout(ch_row)

        self._curve = _CurveWidget()
        self._curve.set_histograms(self._histograms)
        self._curve.curve_changed.connect(self._on_change)
        self._curve.point_selected.connect(self._on_point_selected)
        lo.addWidget(self._curve, 1)

        # ── selected-point precise X/Y entry ───────────────────────────────
        xy_row = QHBoxLayout()
        self._x_lbl = QLabel(tr("adj.curves.x_in"))
        self._x_sp = QSpinBox(); self._x_sp.setRange(0, 255)
        self._y_lbl = QLabel(tr("adj.curves.y_out"))
        self._y_sp = QSpinBox(); self._y_sp.setRange(0, 255)
        self._x_sp.valueChanged.connect(self._on_xy_spin_changed)
        self._y_sp.valueChanged.connect(self._on_xy_spin_changed)
        for w in (self._x_lbl, self._x_sp, self._y_lbl, self._y_sp):
            xy_row.addWidget(w)
        xy_row.addStretch()
        lo.addLayout(xy_row)
        self._set_xy_enabled(False)

        # ── eyedropper: click the document canvas for black/gray/white ─────
        pick_row = QHBoxLayout()
        self._pick_hint = QLabel(tr("adj.curves.sample"))
        pick_row.addWidget(self._pick_hint)
        self._black_btn = QPushButton(tr("adj.curves.sample_black"))
        self._gray_btn = QPushButton(tr("adj.curves.sample_gray"))
        self._white_btn = QPushButton(tr("adj.curves.sample_white"))
        for btn, name in ((self._black_btn, "black"), (self._gray_btn, "gray"), (self._white_btn, "white")):
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, n=name: self._toggle_pick(n))
            pick_row.addWidget(btn)
        pick_row.addStretch()
        lo.addLayout(pick_row)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton(tr("adj.reset"))
        reset_btn.clicked.connect(self._reset_channel)
        dlg_btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dlg_btns.accepted.connect(self.accept)
        dlg_btns.rejected.connect(self.reject)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(dlg_btns)
        lo.addLayout(btn_row)

    # ── selected-point spinboxes ──────────────────────────────────────────────

    def _set_xy_enabled(self, enabled: bool):
        for w in (self._x_lbl, self._x_sp, self._y_lbl, self._y_sp):
            w.setEnabled(enabled)

    def _on_point_selected(self, xy):
        self._set_xy_enabled(xy is not None)
        if xy is None:
            return
        x, y = xy
        for sp, v in ((self._x_sp, x), (self._y_sp, y)):
            sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)

    def _on_xy_spin_changed(self, _v):
        self._curve.set_selected_point_xy(self._x_sp.value(), self._y_sp.value())

    # ── channel / mode / reset ─────────────────────────────────────────────────

    def _on_channel_changed(self, _idx):
        self._curve.set_channel(self._ch_combo.currentData())

    def _on_mode_changed(self, _idx):
        self._curve.set_freehand(self._mode_combo.currentData() == "freehand")

    def _reset_channel(self):
        self._curve.reset_channel()

    def _on_change(self):
        self._curve_points = self._curve.points()
        self._timer.start()

    # ── eyedropper: click the document canvas to sample black/gray/white ─────

    def _toggle_pick(self, which: str):
        buttons = {"black": self._black_btn, "gray": self._gray_btn, "white": self._white_btn}
        this_btn = buttons[which]
        for name, btn in buttons.items():
            if name != which:
                btn.setChecked(False)

        canvas = getattr(self.parent(), "_canvas", None) if self.parent() else None
        if not this_btn.isChecked() or canvas is None:
            self._stop_picking()
            return

        self._picking = which
        self._pick_canvas = canvas
        canvas.setCursor(Qt.CursorShape.CrossCursor)
        canvas.installEventFilter(self)

    def _stop_picking(self):
        if self._pick_canvas is not None:
            self._pick_canvas.removeEventFilter(self)
            self._pick_canvas.unsetCursor()
        self._picking = None
        self._pick_canvas = None
        for btn in (self._black_btn, self._gray_btn, self._white_btn):
            btn.setChecked(False)

    def eventFilter(self, obj, event):
        if self._picking and obj is self._pick_canvas and \
                event.type() == QEvent.Type.MouseButtonPress and \
                event.button() == Qt.MouseButton.LeftButton:
            doc_pos = self._pick_canvas.to_doc(event.position())
            self._sample_point(doc_pos.x(), doc_pos.y())
            self._stop_picking()
            return True
        return super().eventFilter(obj, event)

    def _sample_point(self, doc_x: int, doc_y: int):
        img = self._orig_argb32
        x = max(0, min(img.width() - 1, doc_x))
        y = max(0, min(img.height() - 1, doc_y))
        color = img.pixelColor(x, y)

        if self._picking == "gray":
            # Neutralizes a color cast at this sample: each channel's curve
            # maps its own sampled value to the pixel's overall luminance,
            # regardless of which channel tab happens to be selected.
            target = _luma(color)
            self._curve.add_or_move_point("r", color.red(), target)
            self._curve.add_or_move_point("g", color.green(), target)
            self._curve.add_or_move_point("b", color.blue(), target)
            return

        channel = self._ch_combo.currentData()
        if channel == "rgb":
            sample_val = _luma(color)
        else:
            sample_val = {"r": color.red(), "g": color.green(), "b": color.blue()}[channel]

        out_y = 0 if self._picking == "black" else 255
        anchor = "min" if self._picking == "black" else "max"
        self._curve.add_or_move_point(channel, sample_val, out_y, anchor_end=anchor)

    def done(self, result):
        self._stop_picking()
        super().done(result)

    # ── preview + apply ───────────────────────────────────────────────────────

    def _apply_preview(self):
        res = apply_curves(self._orig_argb32, self._curve_points)
        if not getattr(self, "_is_adj_layer", False):
            p = QPainter(self._image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(0, 0, res)
            p.end()
        if hasattr(self, "_canvas_refresh"):
            self._canvas_refresh()
        elif self.parent() and hasattr(self.parent(), "_canvas_refresh"):
            self.parent()._canvas_refresh()

    def reject(self):
        self._timer.stop()
        self._stop_picking()
        if getattr(self, "_is_adj_layer", False) and hasattr(self, "_layer"):
            self._layer.adjustment_data = getattr(self, "_orig_adj_data", {})
        else:
            p = QPainter(self._image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(0, 0, self._original)
            p.end()
        if hasattr(self, "_canvas_refresh"):
            self._canvas_refresh()
        elif self.parent() and hasattr(self.parent(), "_canvas_refresh"):
            self.parent()._canvas_refresh()
        super().reject()


def _channel_histogram(argb: QImage, channel_idx: int) -> list:
    """256-bucket histogram of one BGRA channel index (0=B,1=G,2=R)."""
    try:
        import numpy as np
        ptr = argb.constBits()
        ptr.setsize(argb.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((argb.height(), argb.width(), 4))
        mask = arr[:, :, 3] > 0
        if not np.any(mask):
            return [0] * 256
        vals = arr[:, :, channel_idx][mask]
        counts, _ = np.histogram(vals, bins=256, range=(0, 256))
        return counts.tolist()
    except ImportError:
        hist = [0] * 256
        for y in range(argb.height()):
            for x in range(argb.width()):
                px = argb.pixel(x, y)
                if (px >> 24) & 0xFF > 0:
                    shift = {0: 0, 1: 8, 2: 16}[channel_idx]
                    hist[(px >> shift) & 0xFF] += 1
        return hist
