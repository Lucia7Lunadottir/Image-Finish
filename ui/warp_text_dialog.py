"""Warp Text dialog (Photoshop's Type > Warp Text): style, orientation,
Bend and the two distortions. Every change is reported through
`on_change(TextWarp)` so the layer previews live; the caller keeps the
undo step and the Cancel path (see TextActionsMixin._warp_text)."""
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QRadioButton, QVBoxLayout

from core.locale import tr
from core.text_warp import STYLE_KEYS, TextWarp
from ui.adjustments_dialog import _SliderRow
from ui.base_dialog import BaseDialog
from ui.tool_options.shape_style_controls import KeyedCombo


class WarpTextDialog(BaseDialog):
    def __init__(self, warp: TextWarp, on_change, parent=None):
        super().__init__(parent, "dlg.warp_text_title")
        self._on_change = on_change
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        self._style_lbl = QLabel(tr("warp.style"))
        self._style = KeyedCombo(STYLE_KEYS, "warp.style")
        self._style.set_value(warp.style)
        self._style.currentIndexChanged.connect(self._changed)
        row.addWidget(self._style_lbl)
        row.addWidget(self._style, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self._horizontal = QRadioButton(tr("warp.horizontal"))
        self._vertical = QRadioButton(tr("warp.vertical"))
        group = QButtonGroup(self)
        group.addButton(self._horizontal)
        group.addButton(self._vertical)
        (self._horizontal if warp.horizontal else self._vertical).setChecked(True)
        self._horizontal.toggled.connect(self._changed)
        row.addWidget(self._horizontal)
        row.addWidget(self._vertical)
        row.addStretch()
        lay.addLayout(row)

        self._bend = _SliderRow(tr("warp.bend"), -100, 100, 50)
        self._hdist = _SliderRow(tr("warp.hdist"), -100, 100, 0)
        self._vdist = _SliderRow(tr("warp.vdist"), -100, 100, 0)
        for r, v in ((self._bend, warp.bend), (self._hdist, warp.hdist), (self._vdist, warp.vdist)):
            r.set_value(int(round(v)))
            r.valueChanged.connect(self._changed)
            lay.addLayout(r)

        self.add_button_box(lay)
        self._update_enabled()

    def warp(self) -> TextWarp:
        return TextWarp(style=self._style.value(), horizontal=self._horizontal.isChecked(),
                        bend=float(self._bend.value()), hdist=float(self._hdist.value()),
                        vdist=float(self._vdist.value()))

    def _update_enabled(self):
        active = self._style.value() != "none"
        for w in (self._horizontal, self._vertical, self._bend._slider,
                  self._hdist._slider, self._vdist._slider):
            w.setEnabled(active)

    def _changed(self, *_):
        self._update_enabled()
        self._on_change(self.warp())

    def retranslate(self):
        super().retranslate()
        self._style_lbl.setText(tr("warp.style"))
        self._style.retranslate()
        self._horizontal.setText(tr("warp.horizontal"))
        self._vertical.setText(tr("warp.vertical"))
