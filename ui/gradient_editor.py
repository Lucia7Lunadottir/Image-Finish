"""Gradient editor, modeled on Photoshop's: a preset library (built-in +
your own, saved across sessions), a gradient bar with opacity stops above
it and color stops below it, a draggable midpoint between neighbouring
stops, and — when editing a fill rather than a bare color ramp — how the
gradient is laid out (style, angle, scale, reverse).

The model is core/gradient_model.py::Gradient. Older callers (Gradient
tool, layer-style Gradient Overlay) pass and read back plain
[(position, QColor-with-alpha)] lists; `GradientEditorDialog` accepts
either and `result_stops()` still returns that flat form.
"""
import json

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPointF, QSize, QSettings
from PyQt6.QtGui import (QColor, QPainter, QLinearGradient, QBrush, QPen, QPolygonF,
                         QPixmap, QIcon)
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSpinBox,
    QDialogButtonBox, QWidget, QSizePolicy, QListWidget, QListWidgetItem, QListView, QMenu,
    QInputDialog, QComboBox, QCheckBox, QGroupBox)

from core.gradient_model import (Gradient, ColorStop, OpacityStop, GRADIENT_STYLES,
                                 builtin_presets)
from core.locale import tr
from ui.base_dialog import BaseDialog


# ── shared painting ─────────────────────────────────────────────────────────

def _paint_checker(p: QPainter, r: QRect, tile: int = 6):
    p.save()
    p.setClipRect(r)
    for row in range(r.top(), r.bottom() + 1, tile):
        for col in range(r.left(), r.right() + 1, tile):
            shade = QColor(204, 204, 204) if ((row // tile + col // tile) % 2 == 0) else QColor(255, 255, 255)
            p.fillRect(col, row, tile, tile, shade)
    p.restore()


def paint_gradient_swatch(p: QPainter, r: QRect, gradient: Gradient):
    """Horizontal ramp of `gradient` (ignoring its style/angle) over a
    transparency checkerboard."""
    _paint_checker(p, r)
    g = QLinearGradient(r.left(), 0, r.right(), 0)
    g.setStops(gradient.qt_stops())
    p.fillRect(r, QBrush(g))


def gradient_icon(gradient: Gradient, size: QSize = QSize(52, 26)) -> QIcon:
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r = QRect(1, 1, size.width() - 2, size.height() - 2)
    paint_gradient_swatch(p, r, gradient)
    p.setPen(QPen(QColor(60, 60, 70), 1))
    p.drawRect(r)
    p.end()
    return QIcon(pm)


def _as_gradient(value) -> Gradient:
    if isinstance(value, Gradient):
        return value.copy()
    if isinstance(value, dict):
        return Gradient.from_dict(value)
    return Gradient.from_merged_stops(value or [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))])


# ── the stops bar ───────────────────────────────────────────────────────────

_PAD = 12          # horizontal padding so end stops are grabbable
_MARK = 14         # marker row height
_BAR_H = 30
_TOP = 4
_REMOVE_DIST = 28  # drag a stop this far off the bar to delete it


class GradientStopsBar(QWidget):
    """Opacity stops above the ramp, color stops below it; a diamond
    midpoint marker between the selected stop and its neighbours.

    Click above/below the ramp to add a stop there, drag stops (or a
    midpoint) along it, drag a stop well away from the bar (or press
    Delete) to remove it, double-click a color stop to pick its color."""

    changed = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, gradient: Gradient, parent=None):
        super().__init__(parent)
        self.gradient = gradient.sorted()
        self.selected: tuple[str, int] = ("color", 0)
        self._drag = None          # ("stop"|"mid", kind, stop object)
        self._drag_off = False
        self.setMinimumSize(360, self._height())
        self.setFixedHeight(self._height())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @staticmethod
    def _height() -> int:
        return _TOP + _MARK + _BAR_H + _MARK + 8

    # geometry
    def _bar(self) -> QRect:
        return QRect(_PAD, _TOP + _MARK, self.width() - 2 * _PAD, _BAR_H)

    def _x(self, pos: float) -> float:
        b = self._bar()
        return b.left() + pos * b.width()

    def _pos(self, x: float) -> float:
        b = self._bar()
        return max(0.0, min(1.0, (x - b.left()) / max(1, b.width())))

    def _stops(self, kind: str) -> list:
        return self.gradient.color_stops if kind == "color" else self.gradient.opacity_stops

    def selected_stop(self):
        kind, i = self.selected
        stops = self._stops(kind)
        return stops[i] if 0 <= i < len(stops) else None

    def _marker_y(self, kind: str) -> float:
        b = self._bar()
        return b.top() - _MARK / 2 if kind == "opacity" else b.bottom() + _MARK / 2 + 1

    def _midpoints(self):
        """(kind, left stop, x) for midpoints next to the selected stop."""
        kind, i = self.selected
        stops = self._stops(kind)
        out = []
        for j in (i - 1, i):
            if 0 <= j < len(stops) - 1:
                a, b = stops[j], stops[j + 1]
                out.append((kind, a, self._x(a.position + (b.position - a.position) * a.midpoint)))
        return out

    def _hit(self, x: float, y: float):
        b = self._bar()
        for kind in ("opacity", "color"):
            my = self._marker_y(kind)
            if abs(y - my) <= _MARK / 2 + 3:
                for i, s in enumerate(self._stops(kind)):
                    if abs(x - self._x(s.position)) <= 7:
                        return ("stop", kind, i)
        for k, a, mx in self._midpoints():
            if abs(x - mx) <= 5 and abs(y - self._midpoint_y(k)) <= 5:
                return ("mid", k, a)
        return None

    def _midpoint_y(self, kind: str) -> float:
        b = self._bar()
        return b.top() - 4 if kind == "opacity" else b.bottom() + 5

    # painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        b = self._bar()
        paint_gradient_swatch(p, b, self.gradient)
        p.setPen(QPen(QColor(70, 70, 80), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(b)

        sel_kind, sel_i = self.selected
        for kind in ("opacity", "color"):
            my = self._marker_y(kind)
            for i, s in enumerate(self._stops(kind)):
                x = self._x(s.position)
                selected = (kind == sel_kind and i == sel_i)
                if kind == "opacity":
                    g = round(255 * (1 - s.opacity))
                    fill = QColor(g, g, g)
                    poly = QPolygonF([QPointF(x - 6, my - 6), QPointF(x + 6, my - 6),
                                      QPointF(x + 6, my + 2), QPointF(x, my + 7), QPointF(x - 6, my + 2)])
                else:
                    fill = s.color
                    poly = QPolygonF([QPointF(x, my - 7), QPointF(x + 6, my - 2), QPointF(x + 6, my + 6),
                                      QPointF(x - 6, my + 6), QPointF(x - 6, my - 2)])
                faded = self._drag_off and self._drag and self._drag[0] == "stop" and self._drag[2] is s
                if faded:
                    p.setOpacity(0.3)
                p.setBrush(QBrush(fill))
                p.setPen(QPen(QColor(255, 200, 60) if selected else QColor(40, 40, 48), 2 if selected else 1))
                p.drawPolygon(poly)
                p.setOpacity(1.0)

        for kind, a, mx in self._midpoints():
            my = self._midpoint_y(kind)
            p.setBrush(QBrush(QColor(255, 200, 60) if (self._drag and self._drag[0] == "mid" and self._drag[2] is a)
                              else QColor(230, 230, 235)))
            p.setPen(QPen(QColor(40, 40, 48), 1))
            p.drawPolygon(QPolygonF([QPointF(mx, my - 4), QPointF(mx + 4, my), QPointF(mx, my + 4), QPointF(mx - 4, my)]))
        p.end()

    # interaction
    def _select(self, kind: str, stop):
        self.selected = (kind, self._stops(kind).index(stop))
        self.selection_changed.emit()
        self.update()

    def _resort(self, kind: str, keep):
        stops = self._stops(kind)
        stops.sort(key=lambda s: s.position)
        if keep is not None and keep in stops:
            self.selected = (kind, stops.index(keep))

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        x, y = ev.position().x(), ev.position().y()
        hit = self._hit(x, y)
        if hit and hit[0] == "stop":
            _, kind, i = hit
            stop = self._stops(kind)[i]
            self._select(kind, stop)
            self._drag = ("stop", kind, stop)
            return
        if hit and hit[0] == "mid":
            self._drag = hit
            self.update()
            return
        b = self._bar()
        kind = "opacity" if y < b.top() + 2 else ("color" if y > b.bottom() - 2 else None)
        if kind is None:
            return
        pos = self._pos(x)
        sample = self.gradient.color_at(pos) if not self.gradient.reverse else \
            Gradient.from_dict(dict(self.gradient.to_dict(), reverse=False)).color_at(pos)
        if kind == "color":
            sample.setAlpha(255)
            stop = ColorStop(pos, sample)
        else:
            stop = OpacityStop(pos, sample.alphaF())
        self._stops(kind).append(stop)
        self._resort(kind, stop)
        self._drag = ("stop", kind, stop)
        self.selection_changed.emit()
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, ev):
        if not self._drag:
            hit = self._hit(ev.position().x(), ev.position().y())
            self.setCursor(Qt.CursorShape.SizeHorCursor if hit else Qt.CursorShape.ArrowCursor)
            return
        x, y = ev.position().x(), ev.position().y()
        what, kind, obj = self._drag
        if what == "mid":
            stops = self._stops(kind)
            i = stops.index(obj)
            nxt = stops[i + 1]
            span = nxt.position - obj.position
            if span > 0:
                obj.midpoint = min(0.95, max(0.05, (self._pos(x) - obj.position) / span))
        else:
            self._drag_off = (len(self._stops(kind)) > 2
                              and abs(y - self._marker_y(kind)) > _REMOVE_DIST)
            obj.position = self._pos(x)
            self._resort(kind, obj)
            self.selection_changed.emit()
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag and self._drag[0] == "stop" and self._drag_off:
            _, kind, stop = self._drag
            self._remove(kind, stop)
        self._drag = None
        self._drag_off = False
        self.update()

    def mouseDoubleClickEvent(self, ev):
        hit = self._hit(ev.position().x(), ev.position().y())
        if hit and hit[0] == "stop" and hit[1] == "color":
            self.pick_color()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        else:
            super().keyPressEvent(ev)

    # editing API (also used by the dialog's fields)
    def _remove(self, kind: str, stop):
        stops = self._stops(kind)
        if len(stops) <= 2 or stop not in stops:
            return
        i = stops.index(stop)
        stops.remove(stop)
        self.selected = (kind, min(i, len(stops) - 1))
        self.selection_changed.emit()
        self.changed.emit()
        self.update()

    def delete_selected(self):
        stop = self.selected_stop()
        if stop is not None:
            self._remove(self.selected[0], stop)

    def set_selected_position(self, pos: float):
        stop = self.selected_stop()
        if stop is None:
            return
        stop.position = max(0.0, min(1.0, pos))
        self._resort(self.selected[0], stop)
        self.changed.emit()
        self.update()

    def set_selected_midpoint(self, mid: float):
        kind, i = self.selected
        stops = self._stops(kind)
        if 0 <= i < len(stops) - 1:
            stops[i].midpoint = min(0.95, max(0.05, mid))
            self.changed.emit()
            self.update()

    def set_selected_color(self, color: QColor):
        stop = self.selected_stop()
        if stop is not None and self.selected[0] == "color":
            c = QColor(color)
            c.setAlpha(255)
            stop.color = c
            self.changed.emit()
            self.update()

    def set_selected_opacity(self, opacity: float):
        stop = self.selected_stop()
        if stop is not None and self.selected[0] == "opacity":
            stop.opacity = max(0.0, min(1.0, opacity))
            self.changed.emit()
            self.update()

    def pick_color(self):
        stop = self.selected_stop()
        if stop is None or self.selected[0] != "color":
            return
        from ui.hsv_picker import ColorPickerDialog
        c = ColorPickerDialog.get_color(stop.color, self)
        if c is not None:
            self.set_selected_color(c)
            self.selection_changed.emit()

    def set_gradient(self, gradient: Gradient):
        layout = (self.gradient.style, self.gradient.angle, self.gradient.scale, self.gradient.reverse)
        g = gradient.sorted()
        self.gradient = Gradient(color_stops=g.color_stops, opacity_stops=g.opacity_stops,
                                 style=layout[0], angle=layout[1], scale=layout[2], reverse=layout[3])
        self.selected = ("color", 0)
        self.selection_changed.emit()
        self.changed.emit()
        self.update()


# ── toolbar swatch ──────────────────────────────────────────────────────────

class GradientPreviewWidget(QWidget):
    """Clickable gradient swatch. `_stops` (flat [(pos, QColor)]) is kept
    for older callers that read/write it directly."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gradient = Gradient()
        self._stops: list = self._gradient.merged_stops()
        self.setFixedSize(96, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_stops(self, stops: list):
        self.set_gradient(_as_gradient(stops))

    def set_gradient(self, gradient: Gradient):
        self._gradient = gradient.copy()
        self._stops = self._gradient.merged_stops()
        self.update()

    def gradient(self) -> Gradient:
        return self._gradient.copy()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -2, -2)
        paint_gradient_swatch(p, r, self._gradient)
        p.setPen(QPen(QColor(80, 80, 90), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ── user presets (persisted) ────────────────────────────────────────────────

_PRESET_KEY = "gradient_presets"


def load_user_presets() -> list:
    s = QSettings("ImageFinish", "ImageFinish")
    try:
        data = json.loads(str(s.value(_PRESET_KEY, "[]")))
        return [(d["name"], Gradient.from_dict(d["gradient"])) for d in data]
    except Exception:
        return []


def save_user_presets(presets: list) -> None:
    s = QSettings("ImageFinish", "ImageFinish")
    s.setValue(_PRESET_KEY, json.dumps([{"name": n, "gradient": g.to_dict()} for n, g in presets]))


# ── dialog ──────────────────────────────────────────────────────────────────

class GradientEditorDialog(BaseDialog):
    """`gradient_changed` fires on every edit (live preview); the caller
    restores its own state if the dialog is rejected. `with_layout=True`
    adds style/angle/scale/reverse — for fills that lay the gradient out
    over a shape, as opposed to a bare color ramp."""

    gradient_changed = pyqtSignal(object)

    def __init__(self, stops, fg: QColor = None, bg: QColor = None, parent=None,
                 with_layout: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("gradient_editor.title"))
        self.setMinimumWidth(560)
        self._fg = QColor(fg) if fg else QColor(0, 0, 0)
        self._bg = QColor(bg) if bg else QColor(255, 255, 255)
        self._updating = False
        gradient = _as_gradient(stops)

        lo = QVBoxLayout(self)
        lo.setSpacing(8)

        # presets
        lo.addWidget(self._label("gradient_editor.presets"))
        self._presets = QListWidget()
        self._presets.setViewMode(QListView.ViewMode.IconMode)
        self._presets.setIconSize(QSize(52, 26))
        self._presets.setGridSize(QSize(60, 34))
        self._presets.setMovement(QListView.Movement.Static)
        self._presets.setResizeMode(QListView.ResizeMode.Adjust)
        self._presets.setFixedHeight(84)
        self._presets.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._presets.customContextMenuRequested.connect(self._preset_menu)
        self._presets.itemClicked.connect(self._apply_preset)
        lo.addWidget(self._presets)
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._save_preset_btn = QPushButton(tr("gradient_editor.add_preset"))
        self._save_preset_btn.clicked.connect(self._save_preset)
        save_row.addWidget(self._save_preset_btn)
        lo.addLayout(save_row)
        self._user_presets = load_user_presets()
        self._fill_presets()

        # bar
        self._bar = GradientStopsBar(gradient)
        lo.addWidget(self._bar)
        hint = QLabel(tr("gradient_editor.hint"))
        hint.setObjectName("optLabel")
        hint.setWordWrap(True)
        lo.addWidget(hint)

        # selected stop
        box = QGroupBox(tr("gradient_editor.stops"))
        grid = QGridLayout(box)
        self._op_spin = self._pct_spin()
        self._op_pos = self._pct_spin()
        self._op_del = QPushButton(tr("gradient_editor.delete"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(52, 24)
        self._color_pos = self._pct_spin()
        self._color_del = QPushButton(tr("gradient_editor.delete"))
        self._mid_spin = self._pct_spin(5, 95)
        grid.addWidget(self._label("gradient_editor.opacity"), 0, 0)
        grid.addWidget(self._op_spin, 0, 1)
        grid.addWidget(self._label("gradient_editor.position"), 0, 2)
        grid.addWidget(self._op_pos, 0, 3)
        grid.addWidget(self._op_del, 0, 4)
        grid.addWidget(self._label("gradient_editor.color"), 1, 0)
        grid.addWidget(self._color_btn, 1, 1)
        grid.addWidget(self._label("gradient_editor.position"), 1, 2)
        grid.addWidget(self._color_pos, 1, 3)
        grid.addWidget(self._color_del, 1, 4)
        grid.addWidget(self._label("gradient_editor.midpoint"), 2, 0)
        grid.addWidget(self._mid_spin, 2, 1)
        grid.setColumnStretch(5, 1)
        lo.addWidget(box)

        # layout over the shape
        self._style = QComboBox()
        for st in GRADIENT_STYLES:
            self._style.addItem(tr(f"gradient_editor.style.{st}"), st)
        self._angle = QSpinBox()
        self._angle.setRange(-180, 180)
        self._angle.setSuffix("°")
        self._scale = QSpinBox()
        self._scale.setRange(10, 1000)
        self._scale.setSuffix("%")
        self._reverse = QCheckBox(tr("gradient_editor.reverse"))
        if with_layout:
            lbox = QGroupBox(tr("gradient_editor.layout"))
            lg = QGridLayout(lbox)
            self._style.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            lg.addWidget(self._label("gradient_editor.style"), 0, 0)
            lg.addWidget(self._style, 0, 1)
            lg.addWidget(self._reverse, 0, 2, 1, 2)
            lg.addWidget(self._label("gradient_editor.angle"), 1, 0)
            lg.addWidget(self._angle, 1, 1)
            lg.addWidget(self._label("gradient_editor.scale"), 1, 2)
            lg.addWidget(self._scale, 1, 3)
            lg.setColumnStretch(4, 1)
            lo.addWidget(lbox)
        self._load_layout(gradient)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

        # wiring
        self._bar.selection_changed.connect(self._show_selection)
        self._bar.changed.connect(self._emit_changed)
        self._op_spin.valueChanged.connect(lambda v: self._edit(lambda: self._bar.set_selected_opacity(v / 100)))
        self._op_pos.valueChanged.connect(lambda v: self._edit(lambda: self._bar.set_selected_position(v / 100)))
        self._color_pos.valueChanged.connect(lambda v: self._edit(lambda: self._bar.set_selected_position(v / 100)))
        self._mid_spin.valueChanged.connect(lambda v: self._edit(lambda: self._bar.set_selected_midpoint(v / 100)))
        self._color_btn.clicked.connect(self._bar.pick_color)
        self._op_del.clicked.connect(self._bar.delete_selected)
        self._color_del.clicked.connect(self._bar.delete_selected)
        self._style.currentIndexChanged.connect(lambda _i: self._layout_changed())
        self._angle.valueChanged.connect(lambda _v: self._layout_changed())
        self._scale.valueChanged.connect(lambda _v: self._layout_changed())
        self._reverse.toggled.connect(lambda _v: self._layout_changed())
        self._show_selection()

    # small builders
    @staticmethod
    def _label(key: str) -> QLabel:
        lbl = QLabel(tr(key))
        lbl.setObjectName("optLabel")
        return lbl

    @staticmethod
    def _pct_spin(lo: int = 0, hi: int = 100) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix("%")
        sp.setFixedWidth(70)
        return sp

    # presets
    def _fill_presets(self):
        self._presets.clear()
        for key, g in builtin_presets(self._fg, self._bg):
            item = QListWidgetItem(gradient_icon(g), "")
            item.setToolTip(tr(key))
            item.setData(Qt.ItemDataRole.UserRole, ("builtin", g))
            self._presets.addItem(item)
        for i, (name, g) in enumerate(self._user_presets):
            item = QListWidgetItem(gradient_icon(g), "")
            item.setToolTip(name)
            item.setData(Qt.ItemDataRole.UserRole, ("user", i))
            self._presets.addItem(item)

    def _preset_gradient(self, item) -> Gradient:
        kind, ref = item.data(Qt.ItemDataRole.UserRole)
        return ref.copy() if kind == "builtin" else self._user_presets[ref][1].copy()

    def _apply_preset(self, item):
        self._bar.set_gradient(self._preset_gradient(item))

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, tr("gradient_editor.add_preset"), tr("gradient_editor.preset_name"))
        if not ok or not name.strip():
            return
        self._user_presets.append((name.strip(), self.result_gradient()))
        save_user_presets(self._user_presets)
        self._fill_presets()

    def _preset_menu(self, pos):
        item = self._presets.itemAt(pos)
        if item is None or item.data(Qt.ItemDataRole.UserRole)[0] != "user":
            return
        idx = item.data(Qt.ItemDataRole.UserRole)[1]
        menu = QMenu(self)
        rename = menu.addAction(tr("gradient_editor.rename_preset"))
        delete = menu.addAction(tr("gradient_editor.delete_preset"))
        chosen = menu.exec(self._presets.mapToGlobal(pos))
        if chosen is rename:
            name, ok = QInputDialog.getText(self, tr("gradient_editor.rename_preset"),
                                            tr("gradient_editor.preset_name"), text=self._user_presets[idx][0])
            if ok and name.strip():
                self._user_presets[idx] = (name.strip(), self._user_presets[idx][1])
        elif chosen is delete:
            self._user_presets.pop(idx)
        else:
            return
        save_user_presets(self._user_presets)
        self._fill_presets()

    # selection <-> fields
    def _edit(self, fn):
        if not self._updating:
            fn()

    def _show_selection(self):
        self._updating = True
        kind, i = self._bar.selected
        stop = self._bar.selected_stop()
        is_op, is_col = kind == "opacity", kind == "color"
        for w in (self._op_spin, self._op_pos, self._op_del):
            w.setEnabled(is_op)
        for w in (self._color_btn, self._color_pos, self._color_del):
            w.setEnabled(is_col)
        if stop is not None:
            if is_op:
                self._op_spin.setValue(round(stop.opacity * 100))
                self._op_pos.setValue(round(stop.position * 100))
            else:
                self._color_pos.setValue(round(stop.position * 100))
                c = stop.color
                self._color_btn.setStyleSheet(
                    f"QPushButton {{ background: rgb({c.red()},{c.green()},{c.blue()}); "
                    f"border: 1px solid #555; border-radius: 3px; }}")
        stops = self._bar._stops(kind)
        has_mid = 0 <= i < len(stops) - 1
        self._mid_spin.setEnabled(has_mid)
        if has_mid:
            self._mid_spin.setValue(round(stops[i].midpoint * 100))
        self._op_del.setEnabled(is_op and len(self._bar.gradient.opacity_stops) > 2)
        self._color_del.setEnabled(is_col and len(self._bar.gradient.color_stops) > 2)
        self._updating = False

    def _load_layout(self, g: Gradient):
        self._updating = True
        self._style.setCurrentIndex(max(0, self._style.findData(g.style)))
        self._angle.setValue(int(round(((g.angle + 180) % 360) - 180)))
        self._scale.setValue(int(round(g.scale)))
        self._reverse.setChecked(g.reverse)
        self._updating = False

    def _layout_changed(self):
        if self._updating:
            return
        g = self._bar.gradient
        g.style = self._style.currentData()
        g.angle = float(self._angle.value())
        g.scale = float(self._scale.value())
        g.reverse = self._reverse.isChecked()
        self._bar.update()
        self._emit_changed()

    def _emit_changed(self):
        self._show_selection()
        self.gradient_changed.emit(self.result_gradient())

    # results
    def result_gradient(self) -> Gradient:
        return self._bar.gradient.copy()

    def result_stops(self) -> list:
        return self.result_gradient().merged_stops()
