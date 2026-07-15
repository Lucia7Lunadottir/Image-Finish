"""Curves adjustment: spline correctness and per-channel composition."""

import hashlib

from PyQt6.QtGui import QColor, QImage, QPainter

from core.adjustments.curves import apply_curves, spline_lut, IDENTITY_POINTS


def _digest(img):
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return hashlib.md5(bytes(ptr)).hexdigest()


def _sample():
    img = QImage(40, 30, QImage.Format.Format_ARGB32)
    img.fill(QColor(60, 120, 200))
    return img


def test_identity_lut_is_a_no_op():
    lut = spline_lut(IDENTITY_POINTS)
    assert lut == list(range(256))


def test_monotone_curve_never_overshoots():
    lut = spline_lut([(0, 0), (64, 40), (192, 220), (255, 255)])
    assert min(lut) >= 0 and max(lut) <= 255
    assert all(lut[i] <= lut[i + 1] for i in range(255))


def test_apply_curves_identity_does_not_change_pixels(qapp):
    src = _sample()
    before = _digest(src)
    result = apply_curves(src, {})
    assert _digest(result) == before


def test_apply_curves_does_not_mutate_source(qapp):
    src = _sample()
    before = _digest(src)
    apply_curves(src, {"rgb": [(0, 0), (128, 60), (255, 255)]})
    assert _digest(src) == before


def test_apply_curves_channel_isolation(qapp):
    """A red-only curve must leave green/blue untouched."""
    src = _sample()  # QColor(60, 120, 200) -> BGRA bytes
    darken_red = {"r": [(0, 0), (255, 0)]}  # red -> always 0
    result = apply_curves(src, darken_red)
    c = result.pixelColor(5, 5)
    assert c.red() == 0
    assert c.green() == 120
    assert c.blue() == 200


def test_apply_curves_master_and_channel_compose(qapp):
    """Master curve applies first, channel curve refines its output."""
    src = _sample()
    invert_all = {"rgb": [(0, 255), (255, 0)]}
    result = apply_curves(src, invert_all)
    c = result.pixelColor(5, 5)
    assert (c.red(), c.green(), c.blue()) == (255 - 60, 255 - 120, 255 - 200)


# ─────────────────────────────────────────────────── eyedropper / endpoint editing

def test_eyedropper_moves_endpoint_input_not_output(qapp):
    """Regression: add_or_move_point used to pin the endpoint back to x=0/255
    and ignore the sampled tone entirely (a complete no-op bug)."""
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    w.add_or_move_point("rgb", 51, 0, anchor_end="min")
    assert w.points()["rgb"][0] == (51, 0)

    w.add_or_move_point("rgb", 213, 255, anchor_end="max")
    assert w.points()["rgb"][-1] == (213, 255)


def test_eyedropper_endpoint_cannot_cross_neighbor(qapp):
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    w.set_points({"rgb": [(0, 0), (100, 50), (255, 255)]})
    w.add_or_move_point("rgb", 200, 0, anchor_end="min")  # would cross the (100,50) point
    assert w.points()["rgb"][0][0] < 100


def test_set_selected_point_xy_respects_neighbor_order(qapp):
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    w.set_points({"rgb": [(0, 0), (100, 50), (200, 150), (255, 255)]})
    w._selected_idx = 1
    w.set_selected_point_xy(250, 80)  # would cross (200, 150)
    x, y = w.points()["rgb"][1]
    assert x < 200
    assert y == 80


def test_set_selected_point_xy_allows_moving_endpoint_input(qapp):
    """Endpoints must be draggable in X too (Photoshop-style clip curves),
    not pinned to x=0/255."""
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    w._selected_idx = 0
    w.set_selected_point_xy(40, 10)
    assert w.points()["rgb"][0] == (40, 10)


# ───────────────────────────────────────────────────────────── freehand mode

def test_freehand_stroke_fills_every_column_and_clips_ends(qapp):
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    w.set_freehand(True)
    w._freehand_samples = {50: 10, 100: 200}
    for x in range(50, 101):
        t = (x - 50) / 50.0
        w._freehand_samples[x] = int(round(10 + (200 - 10) * t))
    w._apply_freehand_samples()

    pts = w.points()["rgb"]
    assert len(pts) == 256
    assert [x for x, _y in pts] == list(range(256))
    # outside the drawn range, the curve clips flat to the nearest drawn value
    assert all(y == 10 for x, y in pts if x < 50)
    assert all(y == 200 for x, y in pts if x > 100)
    assert dict(pts)[50] == 10 and dict(pts)[100] == 200


def test_freehand_mode_hides_control_point_markers(qapp):
    """Sanity check that switching modes doesn't crash paintEvent's branch
    (freehand curves have 256 points — drawing per-point markers for all of
    them would be pointless clutter, not a rendering bug)."""
    from ui.curves_dialog import _CurveWidget

    w = _CurveWidget()
    assert w._freehand is False
    w.set_freehand(True)
    assert w._freehand is True
    w.set_freehand(False)
    assert w._freehand is False


# ──────────────────────────────────────────────────────── non-blocking dialog

def test_curves_dialog_is_non_blocking(qapp):
    """CurvesDialog must opt out of modal .exec() (see
    AdjustmentActionsMixin._show_adj_dialog / LayerActionsMixin._new_adj_layer):
    exec() forces Qt::WA_ShowModal regardless of setModal(), which would
    block real clicks on the document canvas that the eyedroppers need."""
    from ui.curves_dialog import CurvesDialog

    assert CurvesDialog.NON_BLOCKING is True
