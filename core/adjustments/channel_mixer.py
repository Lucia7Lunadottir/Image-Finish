from PyQt6.QtWidgets import QHBoxLayout, QLabel, QCheckBox, QComboBox
from PyQt6.QtGui import QImage

from core.locale import tr
from ui.adjustments_dialog import _to_argb32, _in_place_arr, _AdjustDialog, _SliderRow
from core.adjustments.registry import get_kind, CHANNEL_MIXER_OUTPUTS


def apply_channel_mixer(src: QImage,
                        rR: int, rG: int, rB: int,
                        gR: int, gG: int, gB: int,
                        bR: int, bG: int, bB: int,
                        monochrome: bool = False) -> QImage:
    """3×3 channel mix. Each value in [-200, +200]; 100 = identity.
    If monochrome: all output channels use the Red row."""
    img = _to_argb32(src)
    try:
        import numpy as np
        img = img.copy()
        arr = _in_place_arr(img)
        R = arr[:, :, 2].astype(np.float32)
        G = arr[:, :, 1].astype(np.float32)
        B = arr[:, :, 0].astype(np.float32)
        c = 1.0 / 100.0
        OR = np.clip(R * rR * c + G * rG * c + B * rB * c, 0, 255)
        if monochrome:
            gray = OR.astype(np.uint8)
            arr[:, :, 2] = gray;  arr[:, :, 1] = gray;  arr[:, :, 0] = gray
        else:
            OG = np.clip(R * gR * c + G * gG * c + B * gB * c, 0, 255)
            OB = np.clip(R * bR * c + G * bG * c + B * bB * c, 0, 255)
            arr[:, :, 2] = OR.astype(np.uint8)
            arr[:, :, 1] = OG.astype(np.uint8)
            arr[:, :, 0] = OB.astype(np.uint8)
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    except ImportError:
        result = img.copy()
        c = 1.0 / 100.0
        for y in range(result.height()):
            for x in range(result.width()):
                px  = result.pixel(x, y)
                a   = (px >> 24) & 0xFF
                ri  = (px >> 16) & 0xFF
                gi  = (px >>  8) & 0xFF
                bi  = px & 0xFF
                or_ = int(max(0, min(255, ri*rR*c + gi*rG*c + bi*rB*c)))
                if monochrome:
                    result.setPixel(x, y,
                        (a << 24) | (or_ << 16) | (or_ << 8) | or_)
                else:
                    og = int(max(0, min(255, ri*gR*c + gi*gG*c + bi*gB*c)))
                    ob = int(max(0, min(255, ri*bR*c + gi*bG*c + bi*bB*c)))
                    result.setPixel(x, y,
                        (a << 24) | (or_ << 16) | (og << 8) | ob)
        return result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


_CM_CHANNEL_KEYS = ("adj.channel_mixer.red", "adj.channel_mixer.green", "adj.channel_mixer.blue")


class ChannelMixerDialog(_AdjustDialog):
    """The three source sliders edit one output channel's row at a time;
    the rows themselves live in self._values (keyed like the registry)."""
    ADJUSTMENT_TYPE = "channel_mixer"

    def __init__(self, layer, canvas_refresh, parent=None):
        super().__init__(tr("adj.channel_mixer.title"), layer, canvas_refresh, parent)

        defaults = get_kind(self.ADJUSTMENT_TYPE).defaults()
        self._values     = {k: defaults[k] for k in CHANNEL_MIXER_OUTPUTS}
        self._current_ch = 0

        # Output channel selector
        ch_row = QHBoxLayout()
        ch_lbl = QLabel(tr("adj.channel_mixer.output"))
        ch_lbl.setFixedWidth(90)
        self._ch_combo = QComboBox()
        self._ch_combo.addItems([tr(k) for k in _CM_CHANNEL_KEYS])
        self._ch_combo.currentIndexChanged.connect(self._switch_channel)
        ch_row.addWidget(ch_lbl)
        ch_row.addWidget(self._ch_combo)
        ch_row.addStretch()
        self._vbox.addLayout(ch_row)

        self._src_r = _SliderRow(tr("adj.channel_mixer.src_red"),   -200, 200, 100)
        self._src_g = _SliderRow(tr("adj.channel_mixer.src_green"), -200, 200,   0)
        self._src_b = _SliderRow(tr("adj.channel_mixer.src_blue"),  -200, 200,   0)
        for row in (self._src_r, self._src_g, self._src_b):
            self._add_row(row)

        self._mono = self._bind("monochrome", QCheckBox(tr("adj.channel_mixer.mono")))
        self._mono.stateChanged.connect(self._on_mono)
        self._vbox.addWidget(self._mono)

        self._seal(reset_fn=self._reset_to_defaults)

    # ── parameters ────────────────────────────────────────────────────────────

    def adjustment_data(self) -> dict:
        self._save_current()
        d = super().adjustment_data()
        d.update({k: list(v) for k, v in self._values.items()})
        return d

    def _after_load(self, params):
        self._values = {k: list(params[k]) for k in CHANNEL_MIXER_OUTPUTS}
        self._select_channel(0)
        self._ch_combo.setEnabled(not params["monochrome"])

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save_current(self):
        self._values[CHANNEL_MIXER_OUTPUTS[self._current_ch]] = [
            self._src_r.value(), self._src_g.value(), self._src_b.value()]

    def _select_channel(self, idx):
        """Show row *idx* in the sliders (without saving the current one)."""
        self._current_ch = idx
        self._ch_combo.blockSignals(True)
        self._ch_combo.setCurrentIndex(idx)
        self._ch_combo.blockSignals(False)
        rr, rg, rb = self._values[CHANNEL_MIXER_OUTPUTS[idx]]
        self._src_r.set_value(rr)
        self._src_g.set_value(rg)
        self._src_b.set_value(rb)

    def _switch_channel(self, idx):
        self._save_current()
        self._select_channel(idx)
        self._on_change()

    def _on_mono(self):
        self._ch_combo.setEnabled(not self._mono.isChecked())
        if self._mono.isChecked():
            # Monochrome mixes from the red row only — show that one.
            self._save_current()
            self._select_channel(0)
        self._on_change()
