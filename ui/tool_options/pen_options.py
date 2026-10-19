from PyQt6.QtWidgets import QCheckBox, QPushButton
from .base_options import BaseOptions
from .shape_style_controls import KeyedCombo, ShapeStyleControls, _spin
from core.locale import tr


class PenOptions(BaseOptions):
    """Options bar of every pen tool, modeled on Photoshop's: the mode
    (Shape: the pen draws a shape layer, with the same fill / stroke /
    path-operation controls as the Shapes tool; Path: it draws the work
    path, turned into a selection or a shape with the buttons), Auto
    Add/Delete, and rounding the path's corners."""

    _MODES = ("shape", "path")

    def __init__(self, parent=None):
        super().__init__(parent)
        emit = self.option_changed.emit

        self._mode = KeyedCombo(self._MODES, "opts.pen.mode")
        self._mode.setToolTip(tr("opts.pen.mode_tip"))
        self._mode.currentIndexChanged.connect(self._on_mode_changed)

        # Path mode: what to make of the work path.
        self._btn_sel = QPushButton(tr("opts.pen.selection"))
        self._btn_sel.setObjectName("smallBtn")
        self._btn_sel.clicked.connect(lambda: emit("pen_action", "selection"))
        self._btn_shape = QPushButton(tr("opts.pen.shape"))
        self._btn_shape.setObjectName("smallBtn")
        self._btn_shape.clicked.connect(lambda: emit("pen_action", "shape"))
        self._btn_clear = QPushButton(tr("opts.pen.clear"))
        self._btn_clear.setObjectName("smallBtn")
        self._btn_clear.clicked.connect(lambda: emit("pen_action", "clear"))
        self._path_buttons = (self._btn_sel, self._btn_shape, self._btn_clear)

        # Shape mode: the Shapes tool's fill / stroke / path operation.
        self._style = ShapeStyleControls(self)

        self._auto_cb = QCheckBox(tr("opts.pen.auto_add_delete"))
        self._auto_cb.setChecked(True)
        self._auto_cb.setToolTip(tr("opts.pen.auto_add_delete_tip"))
        self._auto_cb.toggled.connect(lambda v: emit("pen_auto_add_delete", v))

        self._radius_lbl = self._lbl("opts.pen.corner_radius")
        self._radius_sp = _spin(1, 2000, 10, 64, " px")
        self._radius_sp.valueChanged.connect(lambda v: emit("pen_corner_radius", v))
        self._btn_round = QPushButton(tr("opts.pen.round_corners"))
        self._btn_round.setObjectName("smallBtn")
        self._btn_round.setToolTip(tr("opts.pen.round_corners_tip"))
        self._btn_round.clicked.connect(lambda: emit("pen_round_corners", self._radius_sp.value()))

        self._hint = self._lbl("opts.pen_hint")

        groups = (
            (self._mode,),
            self._path_buttons,
            self._style.fill_group,
            self._style.stroke_group,
            self._style.path_op_group,
            (self._auto_cb,),
            (self._radius_lbl, self._radius_sp, self._btn_round),
            (self._hint,),
        )
        for gi, group in enumerate(groups):
            if gi:
                self.layout.addSpacing(14)
            for w in group:
                self.layout.addWidget(w)
        self.layout.addStretch()
        self._update_mode_widgets()

    def _on_mode_changed(self, _i):
        self._update_mode_widgets()
        self.option_changed.emit("pen_mode", self._mode.value())

    def _update_mode_widgets(self):
        shape = self._mode.value() == "shape"
        for w in self._path_buttons:
            w.setVisible(not shape)
        st = self._style
        for w in st.fill_group + st.stroke_group + st.path_op_group:
            w.setVisible(shape)
        if shape:
            st._update_fill_widgets()

    def retranslate(self):
        super().retranslate()
        self._mode.retranslate()
        self._mode.setToolTip(tr("opts.pen.mode_tip"))
        self._btn_sel.setText(tr("opts.pen.selection"))
        self._btn_shape.setText(tr("opts.pen.shape"))
        self._btn_clear.setText(tr("opts.pen.clear"))
        self._style.retranslate()
        self._auto_cb.setText(tr("opts.pen.auto_add_delete"))
        self._auto_cb.setToolTip(tr("opts.pen.auto_add_delete_tip"))
        self._btn_round.setText(tr("opts.pen.round_corners"))
        self._btn_round.setToolTip(tr("opts.pen.round_corners_tip"))

    def update_from_opts(self, opts: dict):
        if "pen_mode" in opts:
            self._mode.set_value(opts["pen_mode"])
        if "pen_auto_add_delete" in opts:
            self.set_silently(self._auto_cb, self._auto_cb.setChecked, bool(opts["pen_auto_add_delete"]))
        if "pen_corner_radius" in opts:
            self.set_silently(self._radius_sp, self._radius_sp.setValue, int(opts["pen_corner_radius"]))
        self._style.update_from_opts(opts)
        self._update_mode_widgets()
