from PyQt6.QtWidgets import QHBoxLayout, QCheckBox
from PyQt6.QtGui import QImage, QColor

from core.locale import tr
from core.gradient_model import Gradient
from ui.adjustments_dialog import _to_argb32, _in_place_arr, _AdjustDialog


def gradient_map_from_data(d: dict) -> Gradient:
    """The adjustment's gradient: `gradient` (Gradient.to_dict) plus
    `reverse`, or the original two-colour {"shadows", "highlights"} form."""
    if d.get("gradient"):
        g = Gradient.from_dict(d["gradient"])
    else:
        g = Gradient.two_color(QColor(d.get("shadows", QColor(0, 0, 0))),
                               QColor(d.get("highlights", QColor(255, 255, 255))))
    g.reverse = bool(d.get("reverse", False))
    return g


def apply_gradient_map(src: QImage, gradient: Gradient) -> QImage:
    """Maps each pixel's luminance through `gradient` (shadows -> its start,
    highlights -> its end), keeping the pixel's own alpha — Photoshop's
    Gradient Map. Uses the gradient's colors; its opacity stops don't
    make pixels transparent."""
    import numpy as np
    img = _to_argb32(src).copy()
    arr = _in_place_arr(img)
    lut = np.empty((256, 3), dtype=np.uint8)
    for i in range(256):
        c = gradient.color_at(i / 255.0)
        lut[i] = (c.blue(), c.green(), c.red())
    R = arr[:, :, 2].astype(np.uint32)
    G = arr[:, :, 1].astype(np.uint32)
    B = arr[:, :, 0].astype(np.uint32)
    lum = ((299 * R + 587 * G + 114 * B) // 1000).astype(np.uint8)
    arr[:, :, :3] = lut[lum]
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


class GradientMapDialog(_AdjustDialog):
    """Gradient Map with the full gradient editor (stops, midpoints,
    presets) instead of two fixed color swatches."""
    ADJUSTMENT_TYPE = "gradient_map"

    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__(tr("adj.gradient_map.title"), layer, canvas_refresh, parent)
        self.setMinimumWidth(420)
        from ui.gradient_editor import GradientPreviewWidget
        self._gradient = Gradient.two_color(QColor(0, 0, 0), QColor(255, 255, 255))

        row = QHBoxLayout()
        self._swatch = GradientPreviewWidget()
        self._swatch.setFixedHeight(26)
        self._swatch.setMinimumWidth(240)
        self._swatch.setToolTip(tr("opts.gradient.edit_tip"))
        self._swatch.clicked.connect(self._edit_gradient)
        row.addWidget(self._swatch, 1)
        self._reverse = self._bind("reverse", QCheckBox(tr("gradient_editor.reverse")))
        self._reverse.toggled.connect(lambda _v: self._on_change())
        row.addWidget(self._reverse)
        self._vbox.addLayout(row)

        self._seal(reset_fn=self._reset_to_defaults)
        self._sync_swatch()

    # The edited gradient isn't a control, so it's added to the bound values
    # ("reverse" is the checkbox).
    def adjustment_data(self) -> dict:
        d = super().adjustment_data()
        d["gradient"] = self._gradient.to_dict()
        return d

    def _after_load(self, params: dict):
        g = gradient_map_from_data(params)
        g.reverse = False           # kept on the checkbox, not the gradient
        self._gradient = g
        self._sync_swatch()

    # ── UI ────────────────────────────────────────────────────────────
    def _current(self) -> Gradient:
        g = self._gradient.copy()
        g.reverse = self._reverse.isChecked()
        return g

    def _sync_swatch(self):
        self._swatch.set_gradient(self._current())

    def _edit_gradient(self):
        from ui.gradient_editor import GradientEditorDialog
        original = self._gradient.copy()
        dlg = GradientEditorDialog(original, parent=self)

        def _live(g):
            self._gradient = g
            self._sync_swatch()
            self._on_change()
        dlg.gradient_changed.connect(_live)
        if not dlg.exec():
            _live(original)

    def _on_change(self):
        self._sync_swatch()
        super()._on_change()

