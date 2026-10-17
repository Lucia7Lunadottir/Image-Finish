"""core/adjustments/registry.py + the dialogs bound to it.

Adjustment-layer data used to be scraped from dialog widget attribute
names and read back by substring guessing; several layer types silently did
nothing (Photo Filter, Gradient Map), HDR Toning ran at 100x strength, and
re-opening any adjustment layer reset its settings to the dialog defaults."""
import pytest
from PyQt6.QtGui import QColor, QImage

from core.document import Document
from core.layer import AdjustmentLayer
from core.adjustments.registry import get_kind, adjustment_types, apply_adjustment


def _img():
    img = QImage(8, 4, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(8):
        for y in range(4):
            img.setPixelColor(x, y, QColor(30 * x % 256, 60 + 20 * y, 200 - 25 * x))
    return img


def _same(a: QImage, b: QImage) -> bool:
    a = a.convertToFormat(QImage.Format.Format_ARGB32)
    b = b.convertToFormat(QImage.Format.Format_ARGB32)
    return all(a.pixel(x, y) == b.pixel(x, y) for x in range(a.width()) for y in range(a.height()))


# ── the registry against the original functions (oracle) ─────────────────

def test_registry_matches_the_adjustment_functions(qapp):
    from ui.adjustments_dialog import apply_brightness_contrast, apply_hue_saturation, apply_invert
    from ui.levels_dialog import apply_levels
    from core.adjustments.exposure import apply_exposure
    from core.adjustments.vibrance import apply_vibrance
    from core.adjustments.black_white import apply_black_white
    from core.adjustments.posterize import apply_posterize
    from core.adjustments.threshold import apply_threshold
    from core.adjustments.photo_filter import apply_photo_filter
    img = _img()
    cases = [
        ({"type": "brightness_contrast", "brightness": 30, "contrast": -20},
         apply_brightness_contrast(img, 30, -20)),
        ({"type": "hue_saturation", "hue": 40, "saturation": 20, "lightness": -10},
         apply_hue_saturation(img, 40, 20, -10)),
        ({"type": "invert"}, apply_invert(img)),
        ({"type": "levels", "black": 20, "gamma": 1.4, "white": 230, "out_min": 10, "out_max": 240},
         apply_levels(img, 20, 1.4, 230, 10, 240)),
        ({"type": "exposure", "exposure": 0.7, "offset": 0.05, "gamma": 1.2},
         apply_exposure(img, 0.7, 0.05, 1.2)),
        ({"type": "vibrance", "vibrance": 40, "saturation": -10}, apply_vibrance(img, 40, -10)),
        ({"type": "black_white", "reds": 120, "yellows": 80, "greens": 90, "cyans": 100,
          "blues": 60, "magentas": 140},
         apply_black_white(img, 120, 80, 90, 100, 60, 140)),
        ({"type": "posterize", "levels": 5}, apply_posterize(img, 5)),
        ({"type": "threshold", "threshold": 100}, apply_threshold(img, 100)),
        ({"type": "photo_filter", "color": QColor(10, 120, 240), "density": 60, "preserve": False},
         apply_photo_filter(img, 10, 120, 240, 60, False)),
    ]
    for data, expected in cases:
        assert _same(apply_adjustment(img, data), expected), data["type"]


# ── older saved data ──────────────────────────────────────────────────────

@pytest.mark.parametrize("data,key,value", [
    ({"type": "brightness_contrast", "bright": 25, "contr": 5}, "brightness", 25),
    ({"type": "hue_saturation", "sat": 33, "lght": 7}, "lightness", 7),
    ({"type": "exposure", "exp": 150}, "exposure", 1.5),                 # raw slider ints
    ({"type": "black_white", "red": 140}, "reds", 140),
    ({"type": "threshold", "thresh": 90}, "threshold", 90),
    ({"type": "levels", "black_sp": 12, "gamma_sp": 1.5, "white_sp": 200}, "white", 200),
    ({"type": "levels", "gamma_sp": 150}, "gamma", 1.5),
    ({"type": "photo_filter", "color_btn": QColor(1, 2, 3)}, "color", QColor(1, 2, 3)),
    ({"type": "hdr_toning", "str": 0.5}, "strength", 50.0),
])
def test_old_keys_are_read(qapp, data, key, value):
    assert get_kind(data["type"]).normalize(data)[key] == value


# ── layers that used to render nothing ────────────────────────────────────

def _layer_doc(data):
    doc = Document(4, 4)
    doc.layers[0].image.fill(QColor(200, 200, 200))
    layer = doc.add_layer(name="adj", layer_cls=AdjustmentLayer)
    layer.adjustment_data = data
    return doc


def test_photo_filter_layer_now_renders(qapp):
    doc = _layer_doc({"type": "photo_filter", "color": QColor(255, 0, 0), "density": 100,
                      "preserve": False})
    c = doc.get_composite().pixelColor(1, 1)
    assert c.red() > c.blue() + 50


def test_hdr_strength_is_a_percentage(qapp):
    k = get_kind("hdr_toning")
    assert k.normalize({"type": "hdr_toning", "strength": 50})["strength"] == 50.0


def test_unknown_type_is_a_no_op(qapp):
    img = _img()
    assert apply_adjustment(img, {"type": "nope"}) is img


# ── dialogs: save explicitly, restore on re-open ──────────────────────────

SAVED = {
    "brightness_contrast": {"brightness": 33, "contrast": -12},
    "hue_saturation": {"hue": 25, "saturation": -40, "lightness": 9},
    "levels": {"black": 15, "gamma": 1.3, "white": 220, "out_min": 5, "out_max": 250},
    "exposure": {"exposure": 1.25, "offset": 0.1, "gamma": 1.5},
    "vibrance": {"vibrance": 55, "saturation": 12},
    "black_white": {"reds": 150, "yellows": 70, "greens": 110, "cyans": 90, "blues": 30, "magentas": 180},
    "posterize": {"levels": 7},
    "threshold": {"threshold": 77},
    "photo_filter": {"color": QColor(20, 200, 90), "density": 66, "preserve": False},
    "curves": {"points": {"rgb": [(0, 0), (128, 170), (255, 255)], "r": [(0, 0), (255, 255)],
                          "g": [(0, 0), (255, 255)], "b": [(0, 0), (255, 255)]}},
}


def test_every_layer_type_in_the_menu_is_registered():
    import re
    menu = open("ui/menu_builder.py").read()
    for t in set(re.findall(r'_new_adj_layer\("(\w+)"\)', menu)):
        assert t in adjustment_types(), t


@pytest.mark.parametrize("adj_type", sorted(SAVED))
def test_reopening_an_adjustment_layer_keeps_its_settings(main_window, mocked_dialogs, adj_type):
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    layer = doc.add_layer(name="adj", layer_cls=AdjustmentLayer)
    layer.adjustment_data = {"type": adj_type, **SAVED[adj_type]}
    expected = get_kind(adj_type).normalize(layer.adjustment_data)

    dlg = w._get_adj_dialog(layer, adj_type)
    got = get_kind(adj_type).normalize(dlg.adjustment_data())
    for key, value in SAVED[adj_type].items():
        assert got[key] == pytest.approx(expected[key]) if isinstance(value, float) else got[key] == expected[key], key
    # opening the dialog must not have overwritten the layer with defaults
    assert get_kind(adj_type).normalize(layer.adjustment_data) == got
    dlg.reject()
    assert layer.adjustment_data["type"] == adj_type


def test_destructive_dialog_preview_equals_the_registry(qapp):
    from ui.adjustments_dialog import BrightnessContrastDialog
    from core.layer import RasterLayer
    layer = RasterLayer("r", 8, 4)
    layer.image = _img()
    dlg = BrightnessContrastDialog(layer, lambda: None)
    dlg._bright.set_value(40)
    dlg._contr.set_value(-15)
    dlg._apply_preview()
    expected = apply_adjustment(_img(), {"type": "brightness_contrast", "brightness": 40, "contrast": -15})
    assert _same(layer.image, expected)


# ── destructive-only dialogs (Image > Adjustments) on the registry ────────
# Channel Mixer, Selective Color, Shadows/Highlights, Replace Color and
# Match Color used to read their widgets inside their own _apply_preview —
# which, for a large image, the final full-resolution apply runs on a
# worker thread. Now they go through the frozen parameter dict like the rest.

def _raster(img=None):
    from core.layer import RasterLayer
    layer = RasterLayer("r", 8, 4)
    layer.image = img or _img()
    return layer


def test_new_kinds_match_their_functions(qapp):
    from core.adjustments.channel_mixer import apply_channel_mixer
    from core.adjustments.selective_color import apply_selective_color
    from core.adjustments.shadows_highlights import apply_shadows_highlights
    from core.adjustments.replace_color import apply_replace_color
    from core.adjustments.match_color import apply_match_color
    img = _img()
    other = _img().mirrored(True, False)
    ranges = {"Reds": [20, -10, 5, 0], "Blues": [0, 0, -30, 15]}
    cases = [
        ({"type": "channel_mixer", "red": [80, 20, 0], "green": [0, 120, -20],
          "blue": [10, 0, 90], "monochrome": False},
         apply_channel_mixer(img, 80, 20, 0, 0, 120, -20, 10, 0, 90)),
        ({"type": "channel_mixer", "red": [50, 30, 20], "monochrome": True},
         apply_channel_mixer(img, 50, 30, 20, 0, 100, 0, 0, 0, 100, monochrome=True)),
        ({"type": "selective_color", "ranges": ranges}, apply_selective_color(img, ranges)),
        ({"type": "shadows_highlights", "shadows": 40, "highlights": 25},
         apply_shadows_highlights(img, 40, 25)),
        ({"type": "replace_color", "color": QColor(0, 120, 200), "fuzziness": 60,
          "hue": 90, "saturation": -20, "lightness": 10},
         apply_replace_color(img, 0, 120, 200, 60, 90, -20, 10)),
        ({"type": "match_color", "source": other, "luminance": 120, "intensity": 80, "fade": 30},
         apply_match_color(img, other, 120, 80, 30)),
    ]
    for data, expected in cases:
        assert _same(apply_adjustment(img, data), expected), data["type"]


def test_match_color_without_source_is_a_no_op(qapp):
    img = _img()
    assert apply_adjustment(img, {"type": "match_color"}) is img


def test_defaults_are_fresh_copies(qapp):
    kind = get_kind("channel_mixer")
    a = kind.defaults()
    a["red"][0] = -200
    assert kind.defaults()["red"] == [100, 0, 0]
    ranges = get_kind("selective_color").normalize({"ranges": {"Reds": [1, 2, 3, 4]}})["ranges"]
    assert ranges["Reds"] == [1, 2, 3, 4] and ranges["Blacks"] == [0, 0, 0, 0]


def test_channel_mixer_dialog_keeps_each_output_row(qapp):
    from core.adjustments.channel_mixer import ChannelMixerDialog
    layer = _raster()
    dlg = ChannelMixerDialog(layer, lambda: None)
    dlg._src_r.set_value(70)
    dlg._src_g.set_value(30)
    dlg._ch_combo.setCurrentIndex(2)          # Blue output
    dlg._src_b.set_value(150)
    dlg._ch_combo.setCurrentIndex(0)          # back to Red: its row survived
    assert (dlg._src_r.value(), dlg._src_g.value()) == (70, 30)
    data = dlg.adjustment_data()
    assert data["red"] == [70, 30, 0] and data["blue"] == [0, 0, 150]
    dlg._apply_preview()
    assert _same(layer.image, apply_adjustment(_img(), data))


def test_selective_color_dialog_preview_equals_the_registry(qapp):
    from core.adjustments.selective_color import SelectiveColorDialog
    layer = _raster()
    dlg = SelectiveColorDialog(layer, lambda: None)
    dlg._cyan.set_value(40)
    dlg._rng_combo.setCurrentIndex(4)         # Blues
    dlg._black.set_value(-25)
    data = dlg.adjustment_data()
    assert data["ranges"]["Reds"] == [40, 0, 0, 0]
    assert data["ranges"]["Blues"] == [0, 0, 0, -25]
    dlg._apply_preview()
    assert _same(layer.image, apply_adjustment(_img(), data))


@pytest.mark.parametrize("dialog", ["channel_mixer", "selective_color", "shadows_highlights",
                                    "replace_color", "match_color"])
def test_reset_restores_registry_defaults(qapp, dialog):
    from core.adjustments.channel_mixer import ChannelMixerDialog
    from core.adjustments.selective_color import SelectiveColorDialog
    from core.adjustments.shadows_highlights import ShadowsHighlightsDialog
    from core.adjustments.replace_color import ReplaceColorDialog
    from core.adjustments.match_color import MatchColorDialog
    layer = _raster()
    if dialog == "match_color":
        dlg = MatchColorDialog(layer, [("other", _img().mirrored(True, False))], lambda: None)
        dlg._src_combo.setCurrentIndex(1)
        dlg._fade.set_value(60)
    else:
        cls = {"channel_mixer": ChannelMixerDialog, "selective_color": SelectiveColorDialog,
               "shadows_highlights": ShadowsHighlightsDialog,
               "replace_color": ReplaceColorDialog}[dialog]
        dlg = cls(layer, lambda: None)
        for w in dlg._bindings.values():
            if hasattr(w, "set_value"):
                w.set_value(17)
        if dialog == "channel_mixer":
            dlg._src_g.set_value(55)
            dlg._ch_combo.setCurrentIndex(1)
        if dialog == "selective_color":
            dlg._yellow.set_value(33)
            dlg._rng_combo.setCurrentIndex(3)
    dlg._apply_preview()
    dlg._reset_to_defaults()
    kind = get_kind(dialog)
    got = kind.normalize(dlg.adjustment_data())
    want = kind.defaults()
    want = kind.normalize({**want})
    for key in want:
        assert got[key] == want[key], key
    assert _same(layer.image, apply_adjustment(_img(), {"type": dialog, **want}))


def test_full_res_apply_does_not_read_widgets(qapp):
    """The final apply uses the parameters frozen on the GUI thread."""
    from core.adjustments.replace_color import ReplaceColorDialog
    layer = _raster()
    dlg = ReplaceColorDialog(layer, lambda: None)
    dlg._hue.set_value(120)
    dlg._frozen_data = dlg.adjustment_data()
    dlg._hue.set_value(-50)                   # a widget change after freezing is ignored
    dlg._apply_preview()
    assert _same(layer.image, apply_adjustment(_img(), dlg._frozen_data))


def test_match_color_offers_only_layers_with_pixels(main_window, mocked_dialogs, monkeypatch):
    import core.adjustments.match_color as mc
    seen = {}
    real_init = mc.MatchColorDialog.__init__

    def spy(self, layer, sources, *a, **k):
        seen["names"] = [n for n, _ in sources]
        real_init(self, layer, sources, *a, **k)

    monkeypatch.setattr(mc.MatchColorDialog, "__init__", spy)
    w = main_window
    w._add_tab(Document(20, 20), "t")
    doc = w._document
    doc.add_layer(name="pixels")
    doc.add_layer(name="adj", layer_cls=AdjustmentLayer)
    doc.active_layer_index = 0
    w._match_color()
    assert "pixels" in seen["names"] and "adj" not in seen["names"]
    assert doc.layers[0].name not in seen["names"]


def test_has_own_pixels(qapp):
    from core.layer import RasterLayer, GroupLayer
    assert RasterLayer("r", 2, 2).has_own_pixels
    assert not AdjustmentLayer("a", 2, 2).has_own_pixels
    assert not GroupLayer("g", 2, 2).has_own_pixels
