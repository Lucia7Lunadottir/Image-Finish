"""core/shape_model.py — ShapeSpec/ShapeAppearance (the one renderer for
shape layers) plus everything built on it: per-corner radii, stroke
alignment/dashes/caps, gradient fill, boolean path operations, rotation
and per-corner handles on ShapeLayerItem, MoveTool on lines, crop."""
import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath

from core.document import Document
from core.layer import VectorLayer
from core.shape_model import ShapeSpec, ShapeAppearance, combine_paths
from tools.shapes_tool import ShapesTool


def _sd(**over):
    sd = {"shape": "rect", "rect": (10, 10, 40, 40), "fg": "#ff0000", "bg": "#ff0000",
          "fill": True, "size": 0, "sides": 6, "angle": 0}
    sd.update(over)
    return sd


def _paint(sd, size=(60, 60), aa=True):
    img = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, aa)
    ShapeSpec.from_dict(sd).paint(p)
    p.end()
    return img


def _a(img, x, y):
    return img.pixelColor(x, y).alpha()


# ── data model ──────────────────────────────────────────────────────────

def test_legacy_shape_data_uses_single_color_for_fill_and_stroke():
    spec = ShapeSpec.from_dict(_sd(fg="#123456", size=3))
    assert spec.appearance.fill_color.name() == "#123456"
    assert spec.appearance.stroke_color.name() == "#123456"
    assert spec.appearance.stroke_width == 3


def test_legacy_single_corner_radius_becomes_four():
    spec = ShapeSpec.from_dict(_sd(shape="rounded_rect", corner_radius=7))
    assert spec.params.corner_radii == (7, 7, 7, 7)


def test_to_dict_roundtrip_keeps_everything():
    sd = _sd(shape="rounded_rect", corner_radii=[1, 2, 3, 4], fill_type="gradient",
             gradient={"start": "#ff00ff00", "end": "#ff0000ff", "angle": 45},
             stroke_color="#ff112233", size=5, stroke_style="dash", stroke_align="outside",
             stroke_cap="round", stroke_join="bevel", stroke_enabled=False, angle=30)
    again = ShapeSpec.from_dict(ShapeSpec.from_dict(sd).to_dict(base=sd))
    a = again.appearance
    assert again.params.corner_radii == (1, 2, 3, 4)
    assert again.angle == 30
    assert (a.fill_type, a.stroke_style, a.stroke_align, a.stroke_cap, a.stroke_join) == \
        ("gradient", "dash", "outside", "round", "bevel")
    assert a.gradient.angle == 45 and a.gradient.color_stops[-1].color.name() == "#0000ff"
    assert a.stroke_enabled is False and a.stroke_width == 5


def test_unknown_style_values_fall_back_safely():
    a = ShapeSpec.from_dict(_sd(stroke_style="wavy", stroke_align="sideways")).appearance
    assert (a.stroke_style, a.stroke_align) == ("solid", "center")


# ── rendering ───────────────────────────────────────────────────────────

def test_per_corner_radii_round_only_the_requested_corner():
    img = _paint(_sd(shape="rounded_rect", corner_radii=[15, 0, 0, 0]))
    assert _a(img, 11, 11) == 0          # top-left rounded away
    assert _a(img, 48, 11) > 0           # top-right still square
    assert _a(img, 48, 48) > 0 and _a(img, 11, 48) > 0


def test_oversized_radii_scale_down_proportionally_not_self_intersect():
    from core.shape_kinds import clamp_corner_radii
    tl, tr, br, bl = clamp_corner_radii(QRectF(0, 0, 40, 20), (100, 100, 0, 0))
    assert tl + tr <= 40.0001 and tl == tr


def test_stroke_alignment_inside_center_outside():
    base = _sd(fill=False, size=6, stroke_color="#ff0000ff")
    inside = _paint(dict(base, stroke_align="inside"))
    center = _paint(dict(base, stroke_align="center"))
    outside = _paint(dict(base, stroke_align="outside"))
    # The rect edge is x=10. Inside covers 10..16, outside 4..10, center 7..13.
    assert _a(inside, 13, 30) > 0 and _a(inside, 6, 30) == 0
    assert _a(outside, 6, 30) > 0 and _a(outside, 13, 30) == 0
    assert _a(center, 8, 30) > 0 and _a(center, 12, 30) > 0 and _a(center, 5, 30) == 0


def test_stroke_can_be_switched_off_keeping_its_width():
    sd = _sd(fill=False, size=6, stroke_enabled=False)
    assert _a(_paint(sd), 10, 30) == 0
    assert ShapeSpec.from_dict(sd).appearance.stroke_width == 6


def test_dashed_stroke_has_gaps():
    img = _paint(_sd(fill=False, size=2, stroke_style="dash", rect=(5, 30, 50, 20)), aa=False)
    row = [_a(img, x, 30) > 0 for x in range(8, 52)]
    assert any(row) and not all(row)


def test_separate_fill_and_stroke_colors():
    img = _paint(_sd(size=6, fill_color="#ff00ff00", stroke_color="#ff0000ff"))
    assert img.pixelColor(30, 30).getRgb()[:3] == (0, 255, 0)
    assert img.pixelColor(10, 30).getRgb()[:3] == (0, 0, 255)


def test_gradient_fill_runs_between_its_colors():
    img = _paint(_sd(fill_type="gradient", gradient={"start": "#ff000000", "end": "#ffffffff", "angle": 0}))
    left, right = img.pixelColor(11, 30).red(), img.pixelColor(48, 30).red()
    assert left < 40 and right > 215


def test_gradient_turns_with_the_shape():
    img = _paint(_sd(angle=90, fill_type="gradient",
                     gradient={"start": "#ff000000", "end": "#ffffffff", "angle": 0}))
    assert img.pixelColor(30, 12).red() < 40 and img.pixelColor(30, 47).red() > 215


def test_rotation_is_applied_to_the_outline():
    img = _paint(_sd(rect=(10, 25, 40, 10), angle=90))
    assert _a(img, 30, 12) > 0      # rotated tall
    assert _a(img, 12, 30) == 0


def test_star_points_and_inner_radius():
    sharp = _paint(_sd(shape="star", rect=(0, 0, 60, 60), star_points=5, star_inner=0.1))
    fat = _paint(_sd(shape="star", rect=(0, 0, 60, 60), star_points=5, star_inner=0.9))
    assert _a(sharp, 30, 18) == 0 or _a(sharp, 18, 30) == 0
    assert _a(fat, 18, 30) > 0


def test_painting_is_resolution_independent():
    """A painter scaled 8x must produce an outline flattened at 8x, not a
    1x path blown up — the core of 'sharp at any zoom'."""
    img = QImage(480, 480, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(8, 8)
    ShapeSpec.from_dict(_sd(shape="ellipse", rect=(5, 5, 50, 50))).paint(p)
    p.end()
    y = 100
    partial = sum(1 for x in range(0, 240) if 0 < img.pixelColor(x, y).alpha() < 255)
    assert partial <= 3


# ── boolean path operations ─────────────────────────────────────────────

def _rect_path(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def test_combine_paths_ops():
    a, b = _rect_path(0, 0, 20, 20), _rect_path(10, 0, 20, 20)
    assert combine_paths(a, b, "unite").contains(QPointF(25, 5))
    sub = combine_paths(a, b, "subtract")
    assert sub.contains(QPointF(5, 5)) and not sub.contains(QPointF(15, 5))
    inter = combine_paths(a, b, "intersect")
    assert inter.contains(QPointF(15, 5)) and not inter.contains(QPointF(5, 5))
    exc = combine_paths(a, b, "exclude")
    assert exc.contains(QPointF(5, 5)) and exc.contains(QPointF(25, 5)) and not exc.contains(QPointF(15, 5))


def test_drawing_with_subtract_cuts_a_hole_in_the_selected_shape():
    doc = Document(80, 80)
    tool = ShapesTool()
    opts = {"shape_type": "rect", "shape_fill": True, "shape_stroke_width": 0,
            "shape_color": QColor(255, 0, 0)}
    tool.on_press(QPoint(10, 10), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    tool.on_release(QPoint(60, 60), doc, QColor(255, 0, 0), QColor(0, 0, 0), opts)
    layer = doc.layers[-1]
    n = len(doc.layers)

    opts_sub = dict(opts, shape_type="ellipse", shape_path_op="subtract")
    tool.on_press(QPoint(25, 25), doc, QColor(0, 0, 255), QColor(0, 0, 0), opts_sub)
    tool.on_release(QPoint(45, 45), doc, QColor(0, 0, 255), QColor(0, 0, 0), opts_sub)

    assert len(doc.layers) == n                     # no new layer
    assert layer.shape_data is None and layer.path_style is not None
    comp = doc.get_composite()
    assert comp.pixelColor(35, 35).getRgb()[:3] == (255, 255, 255)   # hole shows background
    assert comp.pixelColor(15, 15).getRgb()[:3] == (255, 0, 0)       # kept its own color


def test_layer_menu_combine_shapes_unites_with_the_layer_below(main_window, mocked_dialogs):
    w = main_window
    doc = Document(80, 80)
    w._add_tab(doc, "t")
    doc = w._document
    bottom = doc.add_layer(name="a", layer_cls=VectorLayer)
    bottom.shape_data = _sd(rect=(5, 5, 20, 20), fg="#00ff00")
    top = doc.add_layer(name="b", layer_cls=VectorLayer)
    top.shape_data = _sd(rect=(40, 40, 20, 20), fg="#0000ff")
    doc.active_layer_index = doc.layers.index(top)
    n = len(doc.layers)

    w._combine_shapes("unite")

    assert len(doc.layers) == n - 1
    assert doc.get_active_layer() is bottom
    comp = doc.get_composite()
    assert comp.pixelColor(10, 10).getRgb()[:3] == (0, 255, 0)
    assert comp.pixelColor(50, 50).getRgb()[:3] == (0, 255, 0)   # top's geometry, bottom's style
    w._undo()
    assert len(doc.layers) == n


# ── layers built on the model ───────────────────────────────────────────

def test_pen_path_layer_gets_the_same_stroke_options():
    doc = Document(60, 60)
    layer = doc.add_layer(name="p", layer_cls=VectorLayer)
    layer.vector_mask = _rect_path(10, 10, 40, 40)
    layer.path_style = {"fill_color": None, "stroke_color": QColor(0, 0, 255), "stroke_width": 6,
                        "stroke_align": "outside"}
    comp = doc.get_composite()
    assert comp.pixelColor(6, 30).getRgb()[:3] == (0, 0, 255)     # outside the path
    assert comp.pixelColor(13, 30).getRgb()[:3] == (255, 255, 255)


def test_crop_moves_pen_path_with_the_rest_of_the_document():
    from PyQt6.QtCore import QRect
    doc = Document(100, 100)
    layer = doc.add_layer(name="p", layer_cls=VectorLayer)
    layer.vector_mask = _rect_path(50, 50, 10, 10)
    layer.path_style = {"fill_color": QColor(255, 0, 0), "stroke_color": None, "stroke_width": 0}
    doc.apply_crop(QRect(40, 40, 50, 50))
    assert layer.vector_mask.boundingRect() == QRectF(10, 10, 10, 10)


def test_move_tool_on_a_line_keeps_its_direction():
    from PyQt6.QtGui import QTransform
    layer = VectorLayer("l", 100, 100)
    layer.shape_data = _sd(shape="line", rect=(10, 10, 30, 20), start=(10, 30), end=(40, 10), size=2)
    layer.move_tool_apply_extra(Document(100, 100), QTransform.fromTranslate(5, 5),
                                QRectF(10, 10, 30, 20), layer.image)
    assert layer.shape_data["start"] == (15, 35)
    assert layer.shape_data["end"] == (45, 15)


def test_shapes_stroke_width_is_independent_of_brush_size():
    from tools.shapes_tool import shape_data_from_opts
    sd = shape_data_from_opts({"brush_size": 80, "shape_stroke_width": 3}, QColor(0, 0, 0),
                              QPoint(0, 0), QPoint(10, 10), 0)
    assert sd["size"] == 3


# ── ShapeLayerItem handles ──────────────────────────────────────────────

class _Ev:
    def __init__(self, pos, mods=Qt.KeyboardModifier.NoModifier):
        self._pos, self._mods = pos, mods

    def scenePos(self):
        return self._pos

    def modifiers(self):
        return self._mods

    def accept(self):
        pass


def _item_for(w, sd):
    doc = Document(200, 200)
    w._add_tab(doc, "t")
    doc = w._document
    layer = doc.add_layer(name="s", layer_cls=VectorLayer)
    layer.shape_data = sd
    ShapesTool.rebake(layer)
    doc.active_layer_index = doc.layers.index(layer)
    w._activate_tool("Shapes")
    overlay = w._canvas._shape_overlay
    overlay.refresh_items()
    return layer, overlay._items[layer.layer_id]


def test_rotate_handle_rotates_around_center_and_snaps(main_window):
    layer, item = _item_for(main_window, _sd(rect=(50, 50, 40, 20)))
    assert item._rotate_handle.isVisible()
    c = QPointF(70, 60)
    item.rotate_drag_started(QPointF(70, 30))                 # straight up from center
    item.rotate_dragged(QPointF(100, 61), snap=True)          # ~90° clockwise
    item.rotate_drag_finished()
    assert layer.shape_data["angle"] == 90
    assert layer.shape_data["rect"] == (50, 50, 40, 20)       # rotation doesn't move the box
    assert main_window._history.can_undo()


def test_resizing_a_rotated_shape_keeps_the_opposite_corner_fixed(main_window):
    layer, item = _item_for(main_window, _sd(rect=(50, 50, 40, 20), angle=90))
    rot = item._spec.rotation()
    anchor_before = rot.map(QPointF(50, 50))                  # local top-left, world position
    item.handle_drag_started()
    item.handle_dragged("br", QPointF(-10, 10))               # grows in world space
    item.handle_drag_finished()
    spec = ShapeSpec.from_dict(layer.shape_data)
    anchor_after = spec.rotation().map(spec.params.rect.topLeft())
    assert abs(anchor_after.x() - anchor_before.x()) <= 1.01
    assert abs(anchor_after.y() - anchor_before.y()) <= 1.01
    assert spec.params.rect.width() != 40 or spec.params.rect.height() != 20


def test_shift_resize_keeps_aspect_ratio(main_window):
    layer, item = _item_for(main_window, _sd(rect=(50, 50, 40, 20)))
    item.handle_drag_started()
    item.handle_dragged("br", QPointF(40, 0), Qt.KeyboardModifier.ShiftModifier)
    item.handle_drag_finished()
    x, y, w, h = layer.shape_data["rect"]
    assert (x, y) == (50, 50) and w == 2 * h


def test_four_radius_handles_and_alt_changes_one_corner(main_window):
    layer, item = _item_for(main_window, _sd(shape="rounded_rect", rect=(50, 50, 60, 60),
                                             corner_radii=[5, 5, 5, 5]))
    assert all(h.isVisible() for h in item._radius_handles)
    item.radius_handle_drag_started()
    item.radius_handle_dragged(QPointF(110 - 20, 110 - 20), corner=2, only_this=True)
    item.radius_handle_drag_finished()
    assert layer.shape_data["corner_radii"] == [5, 5, 20, 5]

    item.radius_handle_drag_started()
    item.radius_handle_dragged(QPointF(60, 60), corner=0)     # no Alt: all corners
    item.radius_handle_drag_finished()
    assert layer.shape_data["corner_radii"] == [10, 10, 10, 10]


def test_hit_area_follows_the_real_outline(main_window):
    layer, item = _item_for(main_window, _sd(shape="ellipse", rect=(50, 50, 60, 60)))
    shape = item.shape()
    assert shape.contains(QPointF(80, 80))
    assert not shape.contains(QPointF(52, 52))   # inside the bounding box, outside the ellipse


def test_selecting_a_pen_layer_syncs_its_stroke_settings(main_window):
    w = main_window
    w._add_tab(Document(60, 60), "t")
    doc = w._document
    layer = doc.add_layer(name="p", layer_cls=VectorLayer)
    layer.vector_mask = _rect_path(10, 10, 20, 20)
    layer.path_style = {"fill_color": QColor(255, 0, 0), "stroke_color": QColor(0, 0, 255),
                        "stroke_width": 7, "stroke_align": "inside"}
    w._activate_tool("Shapes")
    w._sync_shape_options_from_layer(layer)
    page = w._opts_bar._pages["Shapes"]
    assert page._stroke_sp.value() == 7
    assert page._stroke_align.value() == "inside"

    doc.active_layer_index = doc.layers.index(layer)
    w._on_opt_changed("shape_stroke_align", "outside")
    assert layer.path_style["stroke_align"] == "outside"


def test_new_shape_properties_survive_save_and_load(tmp_path):
    from core.serialization import save_document, load_document
    doc = Document(80, 80)
    shape = doc.add_layer(name="s", layer_cls=VectorLayer)
    shape.shape_data = ShapeSpec.from_dict(_sd(
        shape="rounded_rect", corner_radii=[1, 2, 3, 4], fill_type="gradient",
        gradient={"start": "#ff00ff00", "end": "#ff0000ff", "angle": 30},
        size=4, stroke_style="dot", stroke_align="inside", angle=15)).to_dict()
    combined = doc.add_layer(name="c", layer_cls=VectorLayer)
    combined.shape_data = _sd(rect=(5, 5, 30, 30))
    combined.combine_with(_rect_path(20, 20, 30, 30), "exclude")
    path = str(tmp_path / "shapes.imfn")
    save_document(doc, path)

    doc2, _ = load_document(path)
    s2, c2 = doc2.layers[1], doc2.layers[2]
    spec = ShapeSpec.from_dict(s2.shape_data)
    assert spec.params.corner_radii == (1, 2, 3, 4)
    assert spec.appearance.stroke_style == "dot" and spec.appearance.fill_type == "gradient"
    assert c2.path_style is not None and not c2.vector_mask.isEmpty()
    assert (doc2.get_composite().pixelColor(25, 25).getRgb()
            == doc.get_composite().pixelColor(25, 25).getRgb())
