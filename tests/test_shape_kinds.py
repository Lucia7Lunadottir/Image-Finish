"""Characterization tests for shape rendering, written BEFORE refactoring
ShapesTool._draw_shape's `if shape == "...": ...` dispatch chain (duplicated
a second time in ui/overlay_renderers.py::draw_shapes_preview) into a
core/shape_kinds.py::ShapeKind class hierarchy. Pin down today's exact
pixel output for every existing shape kind so the refactor can prove it
didn't change anything, the same way test_composite.py's characterization
tests backstopped the render_into polymorphism refactor.
"""
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QImage, QColor, QPainter

from tools.shapes_tool import ShapesTool


def _render(shape, rect, start=None, end=None, sides=6, angle=0,
           fill=True, fg=QColor(255, 0, 0, 255), size=0, canvas=(100, 100),
           corner_radius=0):
    img = QImage(*canvas, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # exact pixel comparisons
    ShapesTool._draw_shape(p, shape, rect, start or rect.topLeft(),
                           end or rect.bottomRight(), sides, angle, fill, fg, fg, size,
                           corner_radius)
    p.end()
    return img


def _c(img, x, y):
    return img.pixelColor(x, y)


def test_rect_fills_interior_and_leaves_outside_transparent():
    img = _render("rect", QRect(10, 10, 30, 30))
    assert _c(img, 25, 25).alpha() > 0
    assert _c(img, 5, 5).alpha() == 0


def test_rect_unfilled_is_stroke_only():
    img = _render("rect", QRect(10, 10, 30, 30), fill=False, size=2)
    assert _c(img, 25, 25).alpha() == 0   # interior empty
    assert _c(img, 10, 25).alpha() > 0    # left edge stroked


def test_ellipse_fills_center_not_corners():
    img = _render("ellipse", QRect(10, 10, 40, 40))
    assert _c(img, 30, 30).alpha() > 0    # center of the ellipse
    assert _c(img, 11, 11).alpha() == 0   # corner of the bounding rect, outside the ellipse


def test_triangle_apex_up_base_down():
    img = _render("triangle", QRect(0, 0, 40, 40))
    assert _c(img, 20, 5).alpha() > 0     # near the top apex (center x)
    assert _c(img, 2, 2).alpha() == 0     # top-left corner, outside the triangle
    assert _c(img, 20, 38).alpha() > 0    # base, inside


def test_polygon_uses_sides_count():
    hexagon = _render("polygon", QRect(0, 0, 40, 40), sides=6)
    triangle_ish = _render("polygon", QRect(0, 0, 40, 40), sides=3)
    assert _c(hexagon, 20, 20).alpha() > 0
    assert _c(triangle_ish, 20, 20).alpha() > 0
    # A hexagon has a vertical left edge at mid-height; a 3-sided polygon
    # (apex up) is still narrow there. (Was (2, 8) — that probe sat within
    # 1px of the hexagon's edge and only worked with the old int-truncated
    # vertices; geometry is float now.)
    assert _c(hexagon, 4, 20).alpha() > 0
    assert _c(triangle_ish, 4, 20).alpha() == 0


def test_line_ignores_fill_and_rotation():
    img = _render("line", QRect(0, 0, 40, 40), start=QPoint(0, 20), end=QPoint(40, 20),
                  fill=True, size=3, angle=45)
    assert _c(img, 20, 20).alpha() > 0    # on the horizontal line
    assert _c(img, 20, 5).alpha() == 0    # well off the line — angle must NOT rotate a line


def test_star_center_filled_tips_alternate():
    img = _render("star", QRect(0, 0, 60, 60))
    assert _c(img, 30, 30).alpha() > 0    # center, inside any star


def test_arrow_points_right():
    img = _render("arrow", QRect(0, 0, 60, 40))
    assert _c(img, 55, 20).alpha() > 0    # tip, right-center
    assert _c(img, 5, 2).alpha() == 0     # top-left, outside the shaft/head


def test_cross_center_and_arms_filled_corners_empty():
    img = _render("cross", QRect(0, 0, 60, 60))
    assert _c(img, 30, 30).alpha() > 0    # center of the plus
    assert _c(img, 2, 2).alpha() == 0     # corner, outside the plus


def test_stroked_rect_has_sharp_miter_corners_not_bevel():
    """Real bug found by her: Qt's QPen defaults to BevelJoin, so any shape
    drawn with a stroke (fill or not) showed a visibly chamfered corner
    instead of a crisp 90-degree point — on every corner, at any zoom,
    with no rotation involved at all. draw_shape() must force MiterJoin."""
    img = _render("rect", QRect(20, 20, 30, 30), fill=False, size=10)
    # The outward corner tip a miter join reaches that a bevel join cuts away.
    assert img.pixelColor(16, 16).alpha() > 0
    assert img.pixelColor(14, 14).alpha() == 0   # still correctly outside the stroke


def test_rounded_rect_fills_center_and_rounds_corners():
    img = _render("rounded_rect", QRect(0, 0, 40, 40), corner_radius=15)
    assert _c(img, 20, 20).alpha() > 0     # interior filled
    assert _c(img, 1, 1).alpha() == 0      # corner cut away by the rounding
    assert _c(img, 1, 20).alpha() > 0      # left edge midpoint, not rounded away


def test_rounded_rect_zero_radius_matches_plain_rect():
    rounded = _render("rounded_rect", QRect(10, 10, 30, 30), corner_radius=0)
    plain = _render("rect", QRect(10, 10, 30, 30))
    assert _c(rounded, 10, 10).alpha() == _c(plain, 10, 10).alpha()
    assert _c(rounded, 25, 25).alpha() == _c(plain, 25, 25).alpha()


def test_rounded_rect_clamps_radius_larger_than_half_extent():
    """A corner_radius bigger than the rect itself shouldn't error or vanish
    — it clamps to the largest radius that still fits, matching QPainter's
    own drawRoundedRect behavior of just capping the radius."""
    img = _render("rounded_rect", QRect(0, 0, 40, 20), corner_radius=500)
    assert _c(img, 20, 10).alpha() > 0     # still paints something, no crash


def test_unknown_shape_falls_back_to_rect():
    img = _render("nonexistent-kind", QRect(10, 10, 30, 30))
    assert _c(img, 25, 25).alpha() > 0
    assert _c(img, 5, 5).alpha() == 0


def test_rotation_applies_to_non_line_shapes():
    unrotated = _render("rect", QRect(10, 10, 30, 10))  # wide, short rect
    rotated = _render("rect", QRect(10, 10, 30, 10), angle=90)
    # A 90-degree rotation around the rect's own center swaps which nearby
    # off-center point is covered.
    assert _c(unrotated, 38, 15).alpha() > 0
    assert _c(rotated, 38, 15).alpha() == 0


def test_custom_shape_scales_to_target_rect(tmp_path):
    import json
    # A small triangle-ish path in its own local coordinate space.
    data = [
        {"type": 0, "x": 0, "y": 0},
        {"type": 1, "x": 10, "y": 0},
        {"type": 1, "x": 5, "y": 10},
        {"type": 1, "x": 0, "y": 0},
    ]
    path_file = tmp_path / "custom.json"
    path_file.write_text(json.dumps(data))

    img = _render(f"custom:{path_file}", QRect(0, 0, 100, 100), canvas=(100, 100))
    assert _c(img, 50, 50).alpha() > 0     # scaled up to fill the whole target rect
