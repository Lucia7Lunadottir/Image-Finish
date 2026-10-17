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
