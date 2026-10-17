"""Gradient tool, fill layer and Gradient Overlay style all go through
core/gradient_model.py::Gradient (they used to be three separate
renderers with two styles between them)."""
from PyQt6.QtCore import QPoint, QPointF
from PyQt6.QtGui import QColor, QImage

from core.document import Document
from core.gradient_model import Gradient, ColorStop, GRADIENT_STYLES
from tools.gradient_tool import GradientTool, gradient_from_opts


def _drag(doc, opts, start=(10, 50), end=(90, 50), fg=QColor(0, 0, 0), bg=QColor(255, 255, 255)):
    tool = GradientTool()
    tool.on_press(QPoint(*start), doc, fg, bg, opts)
    tool.on_move(QPoint(*end), doc, fg, bg, opts)
    tool.on_release(QPoint(*end), doc, fg, bg, opts)
    return doc.get_active_layer().image


def test_default_is_foreground_to_background_linear():
    img = _drag(Document(100, 100), {})
    assert img.pixelColor(5, 50).red() < 10 and img.pixelColor(95, 50).red() > 245
    assert 100 < img.pixelColor(50, 50).red() < 155


def test_every_style_draws_something_different():
    seen = set()
    for style in GRADIENT_STYLES:
        img = _drag(Document(100, 100), {"gradient_type": style}, start=(50, 50), end=(80, 50))
        seen.add(tuple(img.pixelColor(x, y).red() for x, y in ((50, 50), (65, 50), (50, 65), (20, 20))))
    assert len(seen) == len(GRADIENT_STYLES)


def test_edited_gradient_reverse_opacity_and_mode():
    g = Gradient(color_stops=[ColorStop(0, QColor(255, 0, 0)), ColorStop(1, QColor(0, 0, 255))])
    img = _drag(Document(100, 100), {"gradient": g.to_dict(), "gradient_reverse": True})
    assert img.pixelColor(5, 50).blue() > 240 and img.pixelColor(95, 50).red() > 240
    img = _drag(Document(100, 100), {"gradient": g.to_dict(), "gradient_opacity": 50})
    assert 100 < img.pixelColor(5, 50).green() < 155        # half red over white
    img = _drag(Document(100, 100), {"gradient": g.to_dict(), "gradient_mode": "Multiply"})
    assert img.pixelColor(5, 50).getRgb()[:3] == (255, 0, 0)   # red x white = red


def test_shift_snaps_the_drag_to_45_degrees():
    img = _drag(Document(100, 100), {"_shift": True}, start=(10, 50), end=(90, 55))
    assert img.pixelColor(50, 5).red() == img.pixelColor(50, 95).red()   # perfectly horizontal


def test_legacy_stops_option_still_works():
    g = gradient_from_opts({"gradient_stops": [(0.0, QColor(255, 0, 0)), (1.0, QColor(0, 255, 0))]},
                           QColor(0, 0, 0), QColor(255, 255, 255))
    assert g.color_at(0).red() == 255 and g.color_at(1).green() == 255


def test_fill_layer_uses_the_full_gradient_and_reads_old_files():
    from core.document import _render_fill_layer
    from core.layer import FillLayer
    layer = FillLayer("f", 100, 100)
    layer.fill_data = {"type": "gradient", "color1": QColor(255, 0, 0), "color2": QColor(0, 0, 255)}
    old = _render_fill_layer(layer, 100, 100)
    assert old.pixelColor(1, 50).red() > 240 and old.pixelColor(98, 50).blue() > 240
    layer.fill_data = {"type": "gradient",
                       "gradient": Gradient(style="radial").to_dict()}
    radial = _render_fill_layer(layer, 100, 100)
    assert radial.pixelColor(50, 50).red() < 10 and radial.pixelColor(2, 2).red() > 200


def test_gradient_overlay_style_supports_new_styles_and_keeps_old_angle_convention():
    from core.layer_styles import apply_layer_styles
    img = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(128, 128, 128))
    stops = [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))]
    # The result is padded for effects; `off` is where the source's (0, 0) went.
    up, off = apply_layer_styles(img, {"gradient_overlay": {"enabled": True, "stops": stops,
                                                            "type": "linear", "angle": 90}})
    ox, oy = -off.x(), -off.y()
    assert up.pixelColor(ox + 50, oy + 95).red() < up.pixelColor(ox + 50, oy + 5).red()   # 90° = bottom -> top
    diamond, off = apply_layer_styles(img, {"gradient_overlay": {"enabled": True, "stops": stops,
                                                                 "type": "diamond", "angle": 0}})
    ox, oy = -off.x(), -off.y()
    assert diamond.pixelColor(ox + 50, oy + 50).red() < 20 and diamond.pixelColor(ox + 2, oy + 50).red() > 200
