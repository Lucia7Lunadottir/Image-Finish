import os
import glob
from PyQt6.QtWidgets import QComboBox, QCheckBox, QToolButton
from .base_options import BaseOptions
from .shape_style_controls import KeyedCombo as _KeyedCombo, ShapeStyleControls, _spin
from core.locale import tr


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

        # ── fill / stroke / path operation (shared with the Pen tools) ──
        self._style = ShapeStyleControls(self)
        st = self._style
        # Names the rest of the app (and tests) know these widgets by.
        self._fill_type, self._color_btn, self._grad_swatch = st.fill_type, st.color_btn, st.grad_swatch
        self._stroke_cb, self._stroke_color_btn, self._stroke_sp = st.stroke_cb, st.stroke_color_btn, st.stroke_sp
        self._path_op = st.path_op
        self._stroke_style, self._stroke_align = st.stroke_style, st.stroke_align
        self._stroke_cap, self._stroke_join, self._stroke_more = st.stroke_cap, st.stroke_join, st.stroke_more

        groups = (
            (self._lbl("opts.shape"), self._combo,
             self._sides_lbl, self._sides_sp,
             self._star_lbl, self._star_points_sp, self._star_inner_lbl, self._star_inner_sp,
             self._radius_lbl, *self._radius_sps, self._radius_link,
             self._angle_lbl, self._angle_sp, self._angle_random_cb),
            st.fill_group,
            st.stroke_group,
            st.path_op_group,
        )
        for gi, group in enumerate(groups):
            if gi:
                self.layout.addSpacing(14)
            for w in group:
                self.layout.addWidget(w)
        self.layout.addStretch()

        self._update_visibility_for_shape("rect")
        self._on_radius_link_toggled(True)

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
        self._style.set_fill_enabled(kind.supports_fill)

    def _current_shape(self) -> str:
        return self._shape_at_index(self._combo.currentIndex())

    def _on_radius_link_toggled(self, linked: bool):
        if linked:
            v = self._radius_sps[0].value()
            for sp in self._radius_sps[1:]:
                self.set_silently(sp, sp.setValue, v)
        self._update_visibility_for_shape(self._current_shape())
        if linked:
            self.option_changed.emit("shape_corner_radii", [self._radius_sps[0].value()] * 4)

    def _on_radius_changed(self, corner: int, value: int):
        if self._radius_link.isChecked():
            for sp in self._radius_sps:
                if sp.value() != value:
                    self.set_silently(sp, sp.setValue, value)
        self.option_changed.emit("shape_corner_radii", [sp.value() for sp in self._radius_sps])

    def add_custom_shape(self, path, name):
        self._combo.addItem(name)
        self._custom_shapes.append(path)
        self._combo.setCurrentIndex(self._combo.count() - 1)

    def retranslate(self):
        super().retranslate()
        for i, v in enumerate(self._SHAPE_VALUES):
            self._combo.setItemText(i, tr(f"opts.shape.{v}"))
        self._style.retranslate()
        self._angle_random_cb.setText(tr("opts.angle_random"))
        for sp, corner in zip(self._radius_sps, ("tl", "tr", "br", "bl")):
            sp.setToolTip(tr(f"opts.shape.radius_{corner}"))
        self._radius_link.setToolTip(tr("opts.shape.radius_link"))

    # ── model -> widgets ────────────────────────────────────────────
    def update_from_opts(self, opts: dict):
        """Pushes model state into the widgets without re-emitting
        option_changed — used on tool activation (canvas.tool_opts, the
        defaults for the next shape) and when a shape layer is selected
        (its own values), so editing always starts from the real value."""
        self._style.update_from_opts(opts)

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
            self.set_silently(self._combo, self._combo.setCurrentIndex, idx)

        for key, sp in (("shape_sides", self._sides_sp), ("shape_angle", self._angle_sp),
                        ("shape_star_points", self._star_points_sp), ("shape_star_inner", self._star_inner_sp)):
            if key in opts:
                self.set_silently(sp, sp.setValue, int(opts[key]))

        radii = opts.get("shape_corner_radii")
        if radii is None and "shape_corner_radius" in opts:
            radii = [opts["shape_corner_radius"]] * 4
        if radii is not None:
            for sp, v in zip(self._radius_sps, radii):
                self.set_silently(sp, sp.setValue, int(v))
            self.set_silently(self._radius_link, self._radius_link.setChecked, len(set(int(v) for v in radii)) == 1)

        self._update_visibility_for_shape(self._current_shape())

