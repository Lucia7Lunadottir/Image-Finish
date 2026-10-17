import os
import glob
from PyQt6.QtWidgets import (QWidget, QGridLayout, QLabel, QSpinBox, QComboBox,
                             QCheckBox, QToolButton, QMenu, QWidgetAction)
from PyQt6.QtGui import QColor
from .base_options import BaseOptions
from core.locale import tr
from core.adjustments._widgets import _ColorButton
from core.gradient_model import Gradient
from ui.gradient_editor import GradientPreviewWidget, GradientEditorDialog
from core.shape_model import STROKE_STYLES, STROKE_ALIGNS, STROKE_CAPS, STROKE_JOINS, FILL_TYPES


class _KeyedCombo(QComboBox):
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


def _spin(lo: int, hi: int, value: int, width: int = 50, suffix: str = "") -> QSpinBox:
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setValue(value)
    sp.setFixedWidth(width)
    if suffix:
        sp.setSuffix(suffix)
    return sp


class ShapesOptions(BaseOptions):
    """Shapes tool options, modeled on Photoshop's shape options bar:
    shape kind + its own parameters, fill (none/color/gradient), stroke
    (on/off, color, width, and a popup with dash type, alignment, caps,
    joins), and the path operation applied when drawing onto an existing
    shape layer. Every control both sets the default for the next shape
    and — via ShapeActionsMixin — live-edits the selected shape layer."""

    _SHAPE_VALUES = ["rect", "rounded_rect", "ellipse", "triangle", "polygon", "line", "star", "arrow", "cross"]
    _PATH_OPS = ("new", "unite", "subtract", "intersect", "exclude")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout.setSpacing(8)
        emit = self.option_changed.emit

        # ── shape kind ────────────────────────────────────────────────
        self._combo = QComboBox()
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._combo.addItems([tr(f"opts.shape.{v}") for v in self._SHAPE_VALUES])
        self._custom_shapes = []
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        shapes_dir = os.path.join(base_dir, "shapes")
        if os.path.exists(shapes_dir):
            for f in sorted(glob.glob(os.path.join(shapes_dir, "*.json"))):
                self._combo.addItem(os.path.splitext(os.path.basename(f))[0])
                self._custom_shapes.append(f)

        def _on_shape_change(i):
            shape = self._shape_at_index(i)
            emit("shape_type", shape)
            self._update_visibility_for_shape(shape)
        self._combo.currentIndexChanged.connect(_on_shape_change)

        # ── kind-specific geometry ────────────────────────────────────
        self._sides_lbl = self._lbl("opts.shape.sides")
        self._sides_sp = _spin(3, 64, 6, 44)
        self._sides_sp.valueChanged.connect(lambda v: emit("shape_sides", v))

        self._star_lbl = self._lbl("opts.shape.star_points")
        self._star_points_sp = _spin(3, 64, 5, 44)
        self._star_points_sp.valueChanged.connect(lambda v: emit("shape_star_points", v))
        self._star_inner_lbl = self._lbl("opts.shape.star_inner")
        self._star_inner_sp = _spin(1, 99, 40, 56, "%")
        self._star_inner_sp.valueChanged.connect(lambda v: emit("shape_star_inner", v))

        self._radius_lbl = self._lbl("opts.shape.radius_short")
        self._radius_sps = []
        for corner in ("tl", "tr", "br", "bl"):
            sp = _spin(0, 5000, 20, 48)
            sp.setToolTip(tr(f"opts.shape.radius_{corner}"))
            sp.valueChanged.connect(lambda v, c=len(self._radius_sps): self._on_radius_changed(c, v))
            self._radius_sps.append(sp)
        self._radius_sp = self._radius_sps[0]   # kept: the top-left / uniform value
        self._radius_link = QToolButton()
        self._radius_link.setText("🔗")
        self._radius_link.setCheckable(True)
        self._radius_link.setChecked(True)
        self._radius_link.setToolTip(tr("opts.shape.radius_link"))
        self._radius_link.toggled.connect(self._on_radius_link_toggled)

        self._angle_lbl = self._lbl("opts.shape.angle")
        self._angle_sp = _spin(0, 359, 0, 56, "°")
        self._angle_sp.setWrapping(True)
        self._angle_sp.valueChanged.connect(lambda v: emit("shape_angle", v))
        self._angle_random_cb = QCheckBox(tr("opts.angle_random"))
        self._angle_random_cb.toggled.connect(lambda v: emit("shape_angle_random", v))

        # ── fill ─────────────────────────────────────────────────────
        # Photoshop's fill swatch: none / solid color / gradient in one
        # control. Maps onto two model fields (shape_fill + shape_fill_type)
        # so turning the fill off keeps the chosen type.
        self._fill_lbl = self._lbl("opts.shape.fill_label")
        self._fill_type = _KeyedCombo(("none",) + FILL_TYPES, "opts.shape.fill_type")
        self._fill_type.currentIndexChanged.connect(self._on_fill_type_changed)
        self._color_btn = _ColorButton(QColor(0, 0, 0))   # fill color
        self._color_btn.setToolTip(tr("opts.shape.fill_color_tip"))
        self._color_btn.colorChanged.connect(lambda c: emit("shape_fill_color", c))
        # Gradient fill: a swatch that opens the full gradient editor
        # (stops, midpoints, presets, style/angle/scale/reverse), with the
        # selected shape updating live while the editor is open.
        self._gradient = Gradient.two_color(QColor(0, 0, 0), QColor(255, 255, 255))
        self._grad_swatch = GradientPreviewWidget()
        self._grad_swatch.setFixedSize(70, 24)
        self._grad_swatch.set_gradient(self._gradient)
        self._grad_swatch.setToolTip(tr("opts.shape.gradient_tip"))
        self._grad_swatch.clicked.connect(self._edit_gradient)

        # ── stroke ───────────────────────────────────────────────────
        self._stroke_cb = QCheckBox(tr("opts.shape.stroke_enabled"))
        self._stroke_cb.setChecked(True)
        self._stroke_cb.toggled.connect(lambda v: emit("shape_stroke", v))
        self._stroke_color_btn = _ColorButton(QColor(0, 0, 0))
        self._stroke_color_btn.setToolTip(tr("opts.shape.stroke_color_tip"))
        self._stroke_color_btn.colorChanged.connect(lambda c: emit("shape_stroke_color", c))
        self._stroke_sp = _spin(0, 500, 2, 60, " px")
        self._stroke_sp.setToolTip(tr("opts.shape.stroke_width_tip"))
        self._stroke_sp.valueChanged.connect(lambda v: emit("shape_stroke_width", v))

        self._stroke_style = _KeyedCombo(STROKE_STYLES, "opts.shape.stroke_style")
        self._stroke_align = _KeyedCombo(STROKE_ALIGNS, "opts.shape.stroke_align")
        self._stroke_cap = _KeyedCombo(STROKE_CAPS, "opts.shape.stroke_cap")
        self._stroke_join = _KeyedCombo(STROKE_JOINS, "opts.shape.stroke_join")
        for combo, key in ((self._stroke_style, "shape_stroke_style"), (self._stroke_align, "shape_stroke_align"),
                           (self._stroke_cap, "shape_stroke_cap"), (self._stroke_join, "shape_stroke_join")):
            combo.currentIndexChanged.connect(lambda _i, c=combo, k=key: emit(k, c.value()))
        self._stroke_more = QToolButton()
        self._stroke_more.setText("⚙")
        self._stroke_more.setToolTip(tr("opts.shape.stroke_options"))
        self._stroke_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self._stroke_more)
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 8, 10, 8)
        self._stroke_popup_labels = []
        for row, (key, combo) in enumerate((("opts.shape.stroke_style", self._stroke_style),
                                            ("opts.shape.stroke_align", self._stroke_align),
                                            ("opts.shape.stroke_cap", self._stroke_cap),
                                            ("opts.shape.stroke_join", self._stroke_join))):
            lbl = QLabel(tr(key))
            self._stroke_popup_labels.append((lbl, key))
            grid.addWidget(lbl, row, 0)
            grid.addWidget(combo, row, 1)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(panel)
        menu.addAction(wa)
        self._stroke_more.setMenu(menu)

        # ── path operation ───────────────────────────────────────────
        self._path_op = _KeyedCombo(self._PATH_OPS, "opts.shape.path_op")
        self._path_op.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._path_op.setMinimumContentsLength(11)
        self._path_op.setToolTip(tr("opts.shape.path_op_tip"))
        self._path_op.currentIndexChanged.connect(lambda _i: emit("shape_path_op", self._path_op.value()))

        groups = (
            (self._lbl("opts.shape"), self._combo,
             self._sides_lbl, self._sides_sp,
             self._star_lbl, self._star_points_sp, self._star_inner_lbl, self._star_inner_sp,
             self._radius_lbl, *self._radius_sps, self._radius_link,
             self._angle_lbl, self._angle_sp, self._angle_random_cb),
            (self._fill_lbl, self._fill_type, self._color_btn, self._grad_swatch),
            (self._stroke_cb, self._stroke_color_btn, self._stroke_sp, self._stroke_more),
            (self._path_op,),
        )
        for gi, group in enumerate(groups):
            if gi:
                self.layout.addSpacing(14)
            for w in group:
                self.layout.addWidget(w)
        self.layout.addStretch()

        self._last_fill_type = "solid"
        self._fill_type.set_value("none")   # canvas default: shape_fill False
        self._update_visibility_for_shape("rect")
        self._on_radius_link_toggled(True)
        self._update_fill_widgets()

    # ── helpers ─────────────────────────────────────────────────────
    def _shape_at_index(self, i: int) -> str:
        if i < len(self._SHAPE_VALUES):
            return self._SHAPE_VALUES[i]
        return "custom:" + self._custom_shapes[i - len(self._SHAPE_VALUES)]

    def _update_visibility_for_shape(self, shape: str):
        from core.shape_kinds import get_shape_kind
        kind = get_shape_kind(shape)
        for w in (self._sides_lbl, self._sides_sp):
            w.setVisible(kind.uses_sides)
        for w in (self._star_lbl, self._star_points_sp, self._star_inner_lbl, self._star_inner_sp):
            w.setVisible(kind.uses_star)
        self._radius_lbl.setVisible(kind.uses_corner_radii)
        self._radius_link.setVisible(kind.uses_corner_radii)
        linked = self._radius_link.isChecked()
        for i, sp in enumerate(self._radius_sps):
            sp.setVisible(kind.uses_corner_radii and (i == 0 or not linked))
        for w in (self._angle_lbl, self._angle_sp, self._angle_random_cb):
            w.setVisible(kind.supports_rotation)
        for w in (self._fill_lbl, self._fill_type, self._color_btn, self._grad_swatch):
            w.setEnabled(kind.supports_fill)

    def _current_shape(self) -> str:
        return self._shape_at_index(self._combo.currentIndex())

    def _on_radius_link_toggled(self, linked: bool):
        if linked:
            v = self._radius_sps[0].value()
            for sp in self._radius_sps[1:]:
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
        self._update_visibility_for_shape(self._current_shape())
        if linked:
            self.option_changed.emit("shape_corner_radii", [self._radius_sps[0].value()] * 4)

    def _on_radius_changed(self, corner: int, value: int):
        if self._radius_link.isChecked():
            for sp in self._radius_sps:
                if sp.value() != value:
                    sp.blockSignals(True)
                    sp.setValue(value)
                    sp.blockSignals(False)
        self.option_changed.emit("shape_corner_radii", [sp.value() for sp in self._radius_sps])

    def _on_fill_type_changed(self, _i):
        self._update_fill_widgets()
        value = self._fill_type.value()
        if value != "none":
            self._last_fill_type = value
        self.option_changed.emit("shape_fill", value != "none")
        if value != "none":
            self.option_changed.emit("shape_fill_type", value)

    def _update_fill_widgets(self):
        value = self._fill_type.value()
        gradient = value == "gradient"
        self._color_btn.setVisible(value == "solid")
        self._grad_swatch.setVisible(gradient)

    def _edit_gradient(self):
        """Opens the gradient editor. Every change is streamed as
        `shape_gradient_live` (the selected shape updates as you edit, all
        in one undo step); OK commits, Cancel puts the original back."""
        original = self._gradient.copy()
        win = self.window()
        canvas = getattr(win, "_canvas", None)
        fg = getattr(canvas, "fg_color", QColor(0, 0, 0))
        bg = getattr(canvas, "bg_color", QColor(255, 255, 255))
        dlg = GradientEditorDialog(original, fg, bg, self, with_layout=True)

        def _live(g):
            self._grad_swatch.set_gradient(g)
            self.option_changed.emit("shape_gradient_live", g.to_dict())
        dlg.gradient_changed.connect(_live)
        result = original
        if dlg.exec():
            result = dlg.result_gradient()
        self._gradient = result
        self._grad_swatch.set_gradient(result)
        self.option_changed.emit("shape_gradient", result.to_dict())

    def add_custom_shape(self, path, name):
        self._combo.addItem(name)
        self._custom_shapes.append(path)
        self._combo.setCurrentIndex(self._combo.count() - 1)

    def retranslate(self):
        super().retranslate()
        for i, v in enumerate(self._SHAPE_VALUES):
            self._combo.setItemText(i, tr(f"opts.shape.{v}"))
        for combo in (self._fill_type, self._stroke_style, self._stroke_align,
                      self._stroke_cap, self._stroke_join, self._path_op):
            combo.retranslate()
        for lbl, key in self._stroke_popup_labels:
            lbl.setText(tr(key))
        self._stroke_cb.setText(tr("opts.shape.stroke_enabled"))
        self._angle_random_cb.setText(tr("opts.angle_random"))
        for sp, corner in zip(self._radius_sps, ("tl", "tr", "br", "bl")):
            sp.setToolTip(tr(f"opts.shape.radius_{corner}"))
        for w, key in ((self._radius_link, "opts.shape.radius_link"),
                       (self._color_btn, "opts.shape.fill_color_tip"),
                       (self._grad_swatch, "opts.shape.gradient_tip"),
                       (self._stroke_color_btn, "opts.shape.stroke_color_tip"),
                       (self._stroke_sp, "opts.shape.stroke_width_tip"),
                       (self._stroke_more, "opts.shape.stroke_options"),
                       (self._path_op, "opts.shape.path_op_tip")):
            w.setToolTip(tr(key))

    # ── model -> widgets ────────────────────────────────────────────
    @staticmethod
    def _set(widget, setter, value):
        widget.blockSignals(True)
        setter(value)
        widget.blockSignals(False)

    def update_from_opts(self, opts: dict):
        """Pushes model state into the widgets without re-emitting
        option_changed — used on tool activation (canvas.tool_opts, the
        defaults for the next shape) and when a shape layer is selected
        (its own values), so editing always starts from the real value."""
        if "shape_color" in opts:
            c = QColor(opts["shape_color"])
            for btn in (self._color_btn, self._stroke_color_btn):
                self._set(btn, btn.set_color, c)
        for key, btn in (("shape_fill_color", self._color_btn),
                         ("shape_stroke_color", self._stroke_color_btn)):
            if opts.get(key) is not None:
                self._set(btn, btn.set_color, QColor(opts[key]))
        if opts.get("shape_gradient"):
            self._gradient = Gradient.from_dict(opts["shape_gradient"])
            self._grad_swatch.set_gradient(self._gradient)

        if "shape_type" in opts:
            shape = opts["shape_type"]
            if shape.startswith("custom:"):
                filepath = shape[7:]
                idx = (self._custom_shapes.index(filepath) + len(self._SHAPE_VALUES)
                       if filepath in self._custom_shapes else self._combo.currentIndex())
            elif shape in self._SHAPE_VALUES:
                idx = self._SHAPE_VALUES.index(shape)
            else:
                idx = self._SHAPE_VALUES.index("rect")
            self._set(self._combo, self._combo.setCurrentIndex, idx)

        if "shape_stroke" in opts:
            self._set(self._stroke_cb, self._stroke_cb.setChecked, bool(opts["shape_stroke"]))
        if "shape_fill" in opts or "shape_fill_type" in opts:
            fill_on = opts.get("shape_fill", self._fill_type.value() != "none")
            ftype = opts.get("shape_fill_type", self._last_fill_type)
            if ftype in FILL_TYPES:
                self._last_fill_type = ftype
            self._fill_type.set_value(self._last_fill_type if fill_on else "none")
        for key, combo in (("shape_stroke_style", self._stroke_style), ("shape_stroke_align", self._stroke_align),
                           ("shape_stroke_cap", self._stroke_cap), ("shape_stroke_join", self._stroke_join),
                           ("shape_path_op", self._path_op)):
            if key in opts:
                combo.set_value(opts[key])

        width = opts.get("shape_stroke_width", opts.get("brush_size"))
        if width is not None:
            self._set(self._stroke_sp, self._stroke_sp.setValue, int(width))
        for key, sp in (("shape_sides", self._sides_sp), ("shape_angle", self._angle_sp),
                        ("shape_star_points", self._star_points_sp), ("shape_star_inner", self._star_inner_sp)):
            if key in opts:
                self._set(sp, sp.setValue, int(opts[key]))

        radii = opts.get("shape_corner_radii")
        if radii is None and "shape_corner_radius" in opts:
            radii = [opts["shape_corner_radius"]] * 4
        if radii is not None:
            for sp, v in zip(self._radius_sps, radii):
                self._set(sp, sp.setValue, int(v))
            self._set(self._radius_link, self._radius_link.setChecked, len(set(int(v) for v in radii)) == 1)

        self._update_visibility_for_shape(self._current_shape())
        self._update_fill_widgets()

