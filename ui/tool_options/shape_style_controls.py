"""Fill / stroke / path-operation controls of a vector shape, as one block
shared by the Shapes tool's options bar and the Pen tools' (shape mode) —
Photoshop shows the same controls for both. They emit the same `shape_*`
option keys, so both tools draw with, and live-edit, the same appearance."""
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QComboBox, QCheckBox, QGridLayout, QLabel, QMenu, QToolButton, QWidget, QWidgetAction

from core.adjustments._widgets import _ColorButton
from core.gradient_model import Gradient
from core.locale import tr
from core.shape_model import FILL_TYPES, STROKE_ALIGNS, STROKE_CAPS, STROKE_JOINS, STROKE_STYLES
from ui.gradient_editor import GradientEditorDialog, GradientPreviewWidget


class KeyedCombo(QComboBox):
    """A combo whose items are (value, translation key) pairs, so the
    emitted/selected value never depends on the UI language and the texts
    can be retranslated in place."""

    def __init__(self, values, key_prefix: str, parent=None):
        super().__init__(parent)
        self._values = list(values)
        self._prefix = key_prefix
        self.addItems([tr(f"{key_prefix}.{v}") for v in self._values])

    def value(self):
        return self._values[self.currentIndex()]

    def set_value(self, v):
        if v in self._values:
            self.blockSignals(True)
            self.setCurrentIndex(self._values.index(v))
            self.blockSignals(False)

    def retranslate(self):
        for i, v in enumerate(self._values):
            self.setItemText(i, tr(f"{self._prefix}.{v}"))


def _spin(lo: int, hi: int, value: int, width: int = 50, suffix: str = ""):
    from PyQt6.QtWidgets import QSpinBox
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setValue(value)
    sp.setFixedWidth(width)
    if suffix:
        sp.setSuffix(suffix)
    return sp


class ShapeStyleControls:
    """Builds the widgets on `page` (a BaseOptions) and wires them to its
    option_changed. `fill_group`, `stroke_group` and `path_op_group` are
    the widget groups the page lays out (each one an overflow unit)."""

    PATH_OPS = ("new", "unite", "subtract", "intersect", "exclude")

    def __init__(self, page):
        self._page = page
        emit = page.option_changed.emit

        # ── fill ─────────────────────────────────────────────────────
        # Photoshop's fill swatch: none / solid color / gradient in one
        # control. Maps onto two model fields (shape_fill + shape_fill_type)
        # so turning the fill off keeps the chosen type.
        self.fill_lbl = page._lbl("opts.shape.fill_label")
        self.fill_type = KeyedCombo(("none",) + FILL_TYPES, "opts.shape.fill_type")
        self.fill_type.currentIndexChanged.connect(self._on_fill_type_changed)
        self.color_btn = _ColorButton(QColor(0, 0, 0))   # fill color
        self.color_btn.setToolTip(tr("opts.shape.fill_color_tip"))
        self.color_btn.colorChanged.connect(lambda c: emit("shape_fill_color", c))
        # Gradient fill: a swatch that opens the full gradient editor
        # (stops, midpoints, presets, style/angle/scale/reverse), with the
        # selected shape updating live while the editor is open.
        self.gradient = Gradient.two_color(QColor(0, 0, 0), QColor(255, 255, 255))
        self.grad_swatch = GradientPreviewWidget()
        self.grad_swatch.setFixedSize(70, 24)
        self.grad_swatch.set_gradient(self.gradient)
        self.grad_swatch.setToolTip(tr("opts.shape.gradient_tip"))
        self.grad_swatch.clicked.connect(self._edit_gradient)

        # ── stroke ───────────────────────────────────────────────────
        self.stroke_cb = QCheckBox(tr("opts.shape.stroke_enabled"))
        self.stroke_cb.setChecked(True)
        self.stroke_cb.toggled.connect(lambda v: emit("shape_stroke", v))
        self.stroke_color_btn = _ColorButton(QColor(0, 0, 0))
        self.stroke_color_btn.setToolTip(tr("opts.shape.stroke_color_tip"))
        self.stroke_color_btn.colorChanged.connect(lambda c: emit("shape_stroke_color", c))
        self.stroke_sp = _spin(0, 500, 2, 60, " px")
        self.stroke_sp.setToolTip(tr("opts.shape.stroke_width_tip"))
        self.stroke_sp.valueChanged.connect(lambda v: emit("shape_stroke_width", v))

        self.stroke_style = KeyedCombo(STROKE_STYLES, "opts.shape.stroke_style")
        self.stroke_align = KeyedCombo(STROKE_ALIGNS, "opts.shape.stroke_align")
        self.stroke_cap = KeyedCombo(STROKE_CAPS, "opts.shape.stroke_cap")
        self.stroke_join = KeyedCombo(STROKE_JOINS, "opts.shape.stroke_join")
        for combo, key in ((self.stroke_style, "shape_stroke_style"), (self.stroke_align, "shape_stroke_align"),
                           (self.stroke_cap, "shape_stroke_cap"), (self.stroke_join, "shape_stroke_join")):
            combo.currentIndexChanged.connect(lambda _i, c=combo, k=key: emit(k, c.value()))
        self.stroke_more = QToolButton()
        self.stroke_more.setText("⚙")
        self.stroke_more.setToolTip(tr("opts.shape.stroke_options"))
        self.stroke_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.stroke_more)
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 8, 10, 8)
        self._stroke_popup_labels = []
        for row, (key, combo) in enumerate((("opts.shape.stroke_style", self.stroke_style),
                                            ("opts.shape.stroke_align", self.stroke_align),
                                            ("opts.shape.stroke_cap", self.stroke_cap),
                                            ("opts.shape.stroke_join", self.stroke_join))):
            lbl = QLabel(tr(key))
            self._stroke_popup_labels.append((lbl, key))
            grid.addWidget(lbl, row, 0)
            grid.addWidget(combo, row, 1)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(panel)
        menu.addAction(wa)
        self.stroke_more.setMenu(menu)

        # ── path operation ───────────────────────────────────────────
        self.path_op = KeyedCombo(self.PATH_OPS, "opts.shape.path_op")
        self.path_op.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.path_op.setMinimumContentsLength(11)
        self.path_op.setToolTip(tr("opts.shape.path_op_tip"))
        self.path_op.currentIndexChanged.connect(lambda _i: emit("shape_path_op", self.path_op.value()))

        self.fill_group = (self.fill_lbl, self.fill_type, self.color_btn, self.grad_swatch)
        self.stroke_group = (self.stroke_cb, self.stroke_color_btn, self.stroke_sp, self.stroke_more)
        self.path_op_group = (self.path_op,)

        self._last_fill_type = "solid"
        self.fill_type.set_value("none")   # canvas default: shape_fill False
        self._update_fill_widgets()

    # ── fill ────────────────────────────────────────────────────────
    def _on_fill_type_changed(self, _i):
        self._update_fill_widgets()
        value = self.fill_type.value()
        if value != "none":
            self._last_fill_type = value
        self._page.option_changed.emit("shape_fill", value != "none")
        if value != "none":
            self._page.option_changed.emit("shape_fill_type", value)

    def _update_fill_widgets(self):
        value = self.fill_type.value()
        self.color_btn.setVisible(value == "solid")
        self.grad_swatch.setVisible(value == "gradient")

    def set_fill_enabled(self, enabled: bool):
        for w in self.fill_group:
            w.setEnabled(enabled)

    def _edit_gradient(self):
        """Opens the gradient editor. Every change is streamed as
        `shape_gradient_live` (the selected shape updates as you edit, all
        in one undo step); OK commits, Cancel puts the original back."""
        page = self._page
        original = self.gradient.copy()
        canvas = getattr(page.window(), "_canvas", None)
        fg = getattr(canvas, "fg_color", QColor(0, 0, 0))
        bg = getattr(canvas, "bg_color", QColor(255, 255, 255))
        dlg = GradientEditorDialog(original, fg, bg, page, with_layout=True)

        def _live(g):
            self.grad_swatch.set_gradient(g)
            page.option_changed.emit("shape_gradient_live", g.to_dict())
        dlg.gradient_changed.connect(_live)
        result = original
        if dlg.exec():
            result = dlg.result_gradient()
        self.gradient = result
        self.grad_swatch.set_gradient(result)
        page.option_changed.emit("shape_gradient", result.to_dict())

    # ── texts / model -> widgets ────────────────────────────────────
    def retranslate(self):
        for combo in (self.fill_type, self.stroke_style, self.stroke_align,
                      self.stroke_cap, self.stroke_join, self.path_op):
            combo.retranslate()
        for lbl, key in self._stroke_popup_labels:
            lbl.setText(tr(key))
        self.stroke_cb.setText(tr("opts.shape.stroke_enabled"))
        for w, key in ((self.color_btn, "opts.shape.fill_color_tip"),
                       (self.grad_swatch, "opts.shape.gradient_tip"),
                       (self.stroke_color_btn, "opts.shape.stroke_color_tip"),
                       (self.stroke_sp, "opts.shape.stroke_width_tip"),
                       (self.stroke_more, "opts.shape.stroke_options"),
                       (self.path_op, "opts.shape.path_op_tip")):
            w.setToolTip(tr(key))

    def update_from_opts(self, opts: dict):
        """Model state -> widgets without re-emitting option_changed."""
        silently = self._page.set_silently
        if "shape_color" in opts:
            c = QColor(opts["shape_color"])
            for btn in (self.color_btn, self.stroke_color_btn):
                silently(btn, btn.set_color, c)
        for key, btn in (("shape_fill_color", self.color_btn),
                         ("shape_stroke_color", self.stroke_color_btn)):
            if opts.get(key) is not None:
                silently(btn, btn.set_color, QColor(opts[key]))
        if opts.get("shape_gradient"):
            self.gradient = Gradient.from_dict(opts["shape_gradient"])
            self.grad_swatch.set_gradient(self.gradient)
        if "shape_stroke" in opts:
            silently(self.stroke_cb, self.stroke_cb.setChecked, bool(opts["shape_stroke"]))
        if "shape_fill" in opts or "shape_fill_type" in opts:
            fill_on = opts.get("shape_fill", self.fill_type.value() != "none")
            ftype = opts.get("shape_fill_type", self._last_fill_type)
            if ftype in FILL_TYPES:
                self._last_fill_type = ftype
            self.fill_type.set_value(self._last_fill_type if fill_on else "none")
        for key, combo in (("shape_stroke_style", self.stroke_style), ("shape_stroke_align", self.stroke_align),
                           ("shape_stroke_cap", self.stroke_cap), ("shape_stroke_join", self.stroke_join),
                           ("shape_path_op", self.path_op)):
            if key in opts:
                combo.set_value(opts[key])
        width = opts.get("shape_stroke_width", opts.get("brush_size"))
        if width is not None:
            silently(self.stroke_sp, self.stroke_sp.setValue, int(width))
        self._update_fill_widgets()
