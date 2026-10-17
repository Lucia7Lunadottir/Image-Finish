"""core/gradient_model.py (color + opacity stops with midpoints, five
layout styles) and ui/gradient_editor.py (stops bar, presets, live
preview) — the gradient editor that replaced the shape fill's
two-color-and-an-angle stub."""
from PyQt6.QtCore import QPointF, QRectF, Qt, QPoint
from PyQt6.QtGui import QColor, QImage, QPainter, QMouseEvent
from PyQt6.QtCore import QEvent

from core.gradient_model import Gradient, ColorStop, OpacityStop, GRADIENT_STYLES
from core.shape_model import ShapeSpec


def _g(**kw):
    return Gradient(color_stops=[ColorStop(0, QColor(0, 0, 0)), ColorStop(1, QColor(255, 255, 255))], **kw)


def test_midpoint_moves_the_half_way_mix():
    g = _g()
    assert abs(g.color_at(0.5).red() - 128) <= 1
    g.color_stops[0].midpoint = 0.2
    assert abs(g.color_at(0.2).red() - 128) <= 2      # 50/50 mix now sits at 20%
    assert g.color_at(0.5).red() > 170


def test_opacity_stops_are_independent_of_color_stops():
    g = _g(opacity_stops=[OpacityStop(0, 1.0), OpacityStop(0.5, 0.0), OpacityStop(1, 1.0)])
    assert g.color_at(0.5).alpha() == 0
    assert g.color_at(0.0).alpha() == 255 and g.color_at(1.0).alpha() == 255
    assert g.color_at(0.25).red() == round(255 * 0.25) or abs(g.color_at(0.25).red() - 64) <= 1


def test_reverse_flips_the_ramp():
    g = _g(reverse=True)
    assert g.color_at(0.0).red() == 255 and g.color_at(1.0).red() == 0


def test_dict_roundtrip_and_legacy_two_color_format():
    g = _g(style="diamond", angle=30, scale=150, reverse=True)
    g.color_stops[0].midpoint = 0.3
    again = Gradient.from_dict(g.to_dict())
    assert again.to_dict() == g.to_dict()
    legacy = Gradient.from_dict({"start": "#ff0000", "end": "#0000ff", "angle": 45})
    assert legacy.angle == 45 and legacy.color_at(0).red() == 255 and legacy.color_at(1).blue() == 255


def test_merged_stops_compat_for_the_gradient_tool():
    stops = [(0.0, QColor(255, 0, 0, 255)), (1.0, QColor(0, 0, 255, 0))]
    g = Gradient.from_merged_stops(stops)
    merged = g.merged_stops()
    assert merged[0][1].red() == 255 and merged[0][1].alpha() == 255
    assert merged[-1][1].blue() == 255 and merged[-1][1].alpha() == 0


def _fill(style, **kw):
    sd = {"shape": "rect", "rect": (0, 0, 100, 100), "fill": True, "size": 0, "fill_type": "gradient",
          "gradient": _g(style=style, **kw).to_dict()}
    img = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    ShapeSpec.from_dict(sd).paint(p)
    p.end()
    return img


def test_every_style_paints_and_differs():
    reds = {}
    for style in GRADIENT_STYLES:
        img = _fill(style)
        assert img.pixelColor(50, 50).alpha() == 255
        reds[style] = (img.pixelColor(50, 50).red(), img.pixelColor(95, 50).red(), img.pixelColor(50, 5).red())
    assert reds["radial"][0] < 20 and reds["radial"][1] > 100          # dark center, lighter edge
    assert reds["reflected"][0] < 20 and reds["reflected"][1] > 200     # center start, edges end
    assert reds["linear"][0] > 100 and reds["linear"][1] > 230
    assert reds["diamond"][0] < 20 and reds["diamond"][2] > 200
    assert len(set(reds.values())) == len(GRADIENT_STYLES)


def test_scale_squeezes_the_ramp():
    full, half = _fill("linear"), _fill("linear", scale=50)
    assert half.pixelColor(80, 50).red() > full.pixelColor(80, 50).red()


# ── editor ──────────────────────────────────────────────────────────────

def _click(widget, x, y, double=False):
    from PyQt6.QtWidgets import QApplication
    t = QEvent.Type.MouseButtonDblClick if double else QEvent.Type.MouseButtonPress
    pos = QPointF(x, y)
    QApplication.sendEvent(widget, QMouseEvent(t, pos, pos, Qt.MouseButton.LeftButton,
                                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos, Qt.MouseButton.LeftButton,
                                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_clicking_above_and_below_the_bar_adds_opacity_and_color_stops(qapp):
    from ui.gradient_editor import GradientStopsBar
    bar = GradientStopsBar(_g())
    bar.resize(400, bar.height())
    b = bar._bar()
    _click(bar, b.left() + b.width() * 0.7, b.bottom() + 10)
    assert len(bar.gradient.color_stops) == 3 and bar.selected[0] == "color"
    _click(bar, b.left() + b.width() * 0.25, b.top() - 10)
    assert len(bar.gradient.opacity_stops) == 3 and bar.selected[0] == "opacity"


def test_dragging_a_stop_off_the_bar_removes_it_but_keeps_two(qapp):
    from PyQt6.QtWidgets import QApplication
    from ui.gradient_editor import GradientStopsBar
    bar = GradientStopsBar(_g())
    bar.resize(400, bar.height())
    b = bar._bar()
    x = b.left() + b.width() * 0.7
    _click(bar, x, b.bottom() + 10)                     # third color stop, selected
    stop = bar.selected_stop()
    y = bar._marker_y("color")
    def ev(t, yy, btn):
        p = QPointF(x, yy)
        QApplication.sendEvent(bar, QMouseEvent(t, p, p, Qt.MouseButton.LeftButton, btn,
                                                Qt.KeyboardModifier.NoModifier))
    ev(QEvent.Type.MouseButtonPress, y, Qt.MouseButton.LeftButton)
    ev(QEvent.Type.MouseMove, y + 80, Qt.MouseButton.LeftButton)
    ev(QEvent.Type.MouseButtonRelease, y + 80, Qt.MouseButton.NoButton)
    assert stop not in bar.gradient.color_stops and len(bar.gradient.color_stops) == 2
    bar.delete_selected()
    assert len(bar.gradient.color_stops) == 2          # never fewer than two


def test_dialog_streams_live_changes_and_keeps_flat_stops_api(qapp):
    from ui.gradient_editor import GradientEditorDialog
    dlg = GradientEditorDialog([(0.0, QColor(255, 0, 0)), (1.0, QColor(0, 0, 255))], with_layout=True)
    seen = []
    dlg.gradient_changed.connect(seen.append)
    dlg._style.setCurrentIndex(dlg._style.findData("radial"))
    dlg._bar.selected = ("color", 0)
    dlg._bar.set_selected_position(0.3)
    assert seen and seen[-1].style == "radial"
    assert dlg.result_gradient().color_stops[0].position == 0.3
    flat = dlg.result_stops()
    assert isinstance(flat, list) and isinstance(flat[0][1], QColor)


def test_user_presets_persist(qapp):
    from ui.gradient_editor import load_user_presets, save_user_presets
    save_user_presets([("Mine", _g(style="angle"))])
    loaded = load_user_presets()
    assert loaded[0][0] == "Mine" and loaded[0][1].style == "angle"
    save_user_presets([])


def test_gradient_editor_live_edits_the_selected_shape_as_one_undo_step(main_window):
    from core.document import Document
    from core.layer import VectorLayer
    w = main_window
    w._add_tab(Document(100, 100), "t")
    doc = w._document
    layer = doc.add_layer(name="s", layer_cls=VectorLayer)
    layer.shape_data = {"shape": "rect", "rect": (0, 0, 100, 100), "fill": True, "size": 0,
                        "fill_type": "gradient", "fg": "#000000"}
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")
    before = len(w._history._undo_stack)
    for angle in (10, 20, 30):
        w._on_opt_changed("shape_gradient_live", _g(angle=angle, style="radial").to_dict())
    w._on_opt_changed("shape_gradient", _g(angle=30, style="radial").to_dict())
    assert len(w._history._undo_stack) == before + 1
    assert layer.shape_data["gradient"]["style"] == "radial"
    assert layer.shape_data["gradient"]["angle"] == 30
