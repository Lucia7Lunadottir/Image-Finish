"""Overlay layer styles (colour / gradient / pattern) honour their blend
mode and keep the layer's own transparency.

The gradient overlay ignored its blend mode entirely, and the colour
overlay set it and then overwrote it with SourceAtop — both always
rendered as Normal."""
import pytest
from PyQt6.QtGui import QColor, QImage

from core.layer_styles import apply_layer_styles


def _layer(color=QColor(200, 40, 40), alpha_corner=False):
    img = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    for x in range(5, 15):
        for y in range(5, 15):
            img.setPixelColor(x, y, color)
    if alpha_corner:
        img.setPixelColor(5, 5, QColor(200, 40, 40, 128))
    return img


def _px(styles, x, y, **kw):
    out, off = apply_layer_styles(_layer(**kw), styles)
    return out.pixelColor(x - off.x(), y - off.y())


def _color(mode, color):
    return {"color_overlay": {"enabled": True, "blend_mode": mode, "color": color, "opacity": 100}}


def test_color_overlay_normal_replaces_the_colour(qapp):
    assert _px(_color("SourceOver", QColor(0, 0, 255)), 10, 10) == QColor(0, 0, 255)


def test_color_overlay_multiply_and_screen(qapp):
    assert _px(_color("Multiply", QColor(255, 255, 255)), 10, 10) == QColor(200, 40, 40)
    c = _px(_color("Screen", QColor(0, 0, 255)), 10, 10)
    assert (c.red(), c.green(), c.blue()) == (200, 40, 255)


def test_overlay_keeps_the_layer_transparency(qapp):
    assert _px(_color("Multiply", QColor(0, 0, 255)), 1, 1).alpha() == 0
    assert _px(_color("Screen", QColor(0, 0, 255)), 1, 1).alpha() == 0
    assert _px(_color("Multiply", QColor(0, 0, 255)), 5, 5, alpha_corner=True).alpha() == pytest.approx(128, abs=1)


def test_gradient_overlay_uses_its_blend_mode(qapp):
    white = [(0.0, QColor(255, 255, 255)), (1.0, QColor(255, 255, 255))]
    base = {"enabled": True, "stops": white, "opacity": 100, "type": "linear", "angle": 90, "scale": 100}
    normal = _px({"gradient_overlay": dict(base, blend_mode="SourceOver")}, 10, 10)
    multiply = _px({"gradient_overlay": dict(base, blend_mode="Multiply")}, 10, 10)
    assert normal == QColor(255, 255, 255)
    assert multiply == QColor(200, 40, 40)          # white x layer = layer


def test_overlay_opacity(qapp):
    styles = {"color_overlay": {"enabled": True, "blend_mode": "SourceOver",
                                "color": QColor(0, 0, 0), "opacity": 50}}
    c = _px(styles, 10, 10)
    assert c.red() == pytest.approx(100, abs=2) and c.alpha() == 255


def test_colour_overlay_sits_above_the_gradient_overlay(qapp):
    white = [(0.0, QColor(255, 255, 255)), (1.0, QColor(255, 255, 255))]
    styles = {"gradient_overlay": {"enabled": True, "stops": white, "opacity": 100,
                                   "blend_mode": "SourceOver", "type": "linear", "angle": 90, "scale": 100},
              "color_overlay": {"enabled": True, "blend_mode": "SourceOver",
                                "color": QColor(0, 255, 0), "opacity": 100}}
    assert _px(styles, 10, 10) == QColor(0, 255, 0)


def test_disabled_styles_do_not_count(qapp):
    """The dialog stores every effect (disabled ones keep their settings);
    only enabled ones may switch the layer to the styles render path."""
    from core.layer import RasterLayer
    layer = RasterLayer("r", 4, 4)
    assert not layer.has_active_styles
    layer.layer_styles = {"drop_shadow": {"enabled": False, "opacity": 40}}
    assert not layer.has_active_styles
    layer.layer_styles["stroke"] = {"enabled": True}
    assert layer.has_active_styles
