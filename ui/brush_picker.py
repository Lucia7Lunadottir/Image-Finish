"""The brush picker a right click opens for brush-like tools (Photoshop's
Brush Preset Picker): size, hardness, angle, a preview of the stamp and
every brush tip.

Changes go through the window's option handler at once, so the options
bar, the Brushes panel and every open document follow; while the picker
is open the canvas keeps the brush outline drawn where the click was, so
the size can be judged against the image.
"""
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout

from core.locale import tr
from ui import theme
from ui.brush_widgets import BrushTipGrid, BrushTipPreview, SliderSpin


class BrushPicker(QFrame):

    def __init__(self, win, canvas, anchor: QPointF, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._win, self._canvas, self._anchor = win, canvas, QPointF(anchor)
        self.setObjectName("brushPicker")
        theme.apply_style(self, lambda: (
            f"QFrame#brushPicker{{background:{theme.OVERLAY};border:1px solid #414559;"
            f"border-radius:6px;}}"
            f"QFrame#brushPicker QLabel{{background:transparent;color:{theme.TEXT};}}"))
        opts = canvas.tool_opts

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        rows = QGridLayout()
        rows.setHorizontalSpacing(8)
        self._size = SliderSpin(1, 500, 5000, " px", slider_width=180)
        self._hardness = SliderSpin(0, 100, suffix="%", slider_width=180)
        self._angle = SliderSpin(0, 359, suffix="°", slider_width=180)
        for r, (key, ctl) in enumerate((("opts.size", self._size),
                                        ("opts.hardness", self._hardness),
                                        ("opts.angle", self._angle))):
            rows.addWidget(QLabel(tr(key)), r, 0)
            rows.addWidget(ctl, r, 1)
        lay.addLayout(rows)

        self._preview = BrushTipPreview(box=110)
        lay.addWidget(self._preview)

        self._grid = BrushTipGrid(columns=5, thumb=52)
        self._fit_grid()
        self._grid.rows_changed.connect(self._fit_grid)
        lay.addWidget(self._grid)

        self._size.setValue(int(opts.get("brush_size", 10)))
        self._hardness.setValue(round(float(opts.get("brush_hardness", 1.0)) * 100))
        self._angle.setValue(int(opts.get("brush_angle", 0.0)) % 360)
        self._grid.set_current(opts.get("brush_mask", "round"))

        self._size.valueChanged.connect(lambda v: self._set("brush_size", v))
        self._hardness.valueChanged.connect(lambda v: self._set("brush_hardness", v / 100.0))
        self._angle.valueChanged.connect(lambda v: self._set("brush_angle", float(v)))
        self._grid.tip_selected.connect(lambda v: self._set("brush_mask", v))
        self._grid.tip_activated.connect(lambda _v: self.close())   # as in Photoshop
        self._sync_preview()

    def _fit_grid(self):
        """As tall as its rows, up to four (then it scrolls)."""
        rows = min(4, max(1, self._grid.row_count()))
        self._grid.setFixedHeight(rows * 56 + 10)

    # ------------------------------------------------------------------ show
    def exec(self, global_pos: QPoint):
        """Open at the click (kept on screen), outline pinned on the canvas."""
        self.adjustSize()
        screen = self.screen().availableGeometry() if self.screen() else None
        x, y = global_pos.x(), global_pos.y()
        if screen is not None:
            x = min(max(screen.left(), x), screen.right() - self.width())
            y = min(max(screen.top(), y), screen.bottom() - self.height())
        self.move(x, y)
        self._canvas.pin_brush_outline(self._anchor)
        self.show()
        self._size.spin.setFocus()
        self._size.spin.selectAll()

    def hideEvent(self, ev):
        self._canvas.pin_brush_outline(None)
        super().hideEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.close()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------------ edits
    def _set(self, key, value):
        self._win._on_opt_changed(key, value)
        self._sync_preview()
        self._canvas.update()

    def _sync_preview(self):
        self._preview.set_brush(self._size.value(), self._hardness.value() / 100.0,
                                self._grid.current(), self._angle.value())
