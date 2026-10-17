"""~9 filter/adjustment preview dialogs (Noise, Stylize, Sharpen, Pixelate,
Other Filters, Specific Filters/Liquify, Blur Gallery, Distort, Render,
Select and Mask) each carried their own ~50-90 line copy of a pan/zoom/
checkerboard QWidget (99.8% identical for 5 of them per difflib). Extracted
into ui.preview_canvas_base.PreviewCanvasBase (+ DragCenterMixin for the
"drag a center point" interaction shared by Blur Gallery/Distort/Render).

These tests cover the shared base/mixin in isolation (fast, no real
dialogs) plus a couple of end-to-end smoke tests through real dialogs to
confirm the hook wiring (checkerboard visibility, cursor, clip rect,
pan-trigger override) actually reaches subclasses correctly.
"""
from types import SimpleNamespace

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QImage, QColor

from ui.preview_canvas_base import (
    PreviewCanvasBase, DragCenterMixin,
    downscale_for_live_preview, init_live_preview_arrays, restore_full_res_before_accept,
)


def _dialog_stub(w=40, h=30, **extra):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(255, 255, 255, 255))
    base = dict(preview_img=img, cx=w / 2.0, cy=h / 2.0, mode="x",
                _trigger_update=lambda: None)
    base.update(extra)
    return SimpleNamespace(**base)


def _press(canvas, pos, button=Qt.MouseButton.MiddleButton):
    """Dispatches via canvas.event(), like real Qt does — NOT a direct
    canvas.mousePressEvent(ev) call. Calling the override method directly
    from Python bypasses PyQt6's return-type validation for virtual
    overrides and would have hidden the real bug this file's tests
    originally missed: mousePressEvent/mouseMoveEvent are void in C++, and
    a subclass that doesn't itself override them (e.g. `class X(Base):
    pass`) has Qt call straight into the base implementation as the
    *actual* dispatch target — if that returns non-None, PyQt6 raises
    TypeError there, not on a direct Python call."""
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(*pos), button, button,
                      Qt.KeyboardModifier.NoModifier)
    canvas.event(ev)


def _move(canvas, pos, buttons=Qt.MouseButton.MiddleButton):
    ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(*pos), Qt.MouseButton.NoButton, buttons,
                      Qt.KeyboardModifier.NoModifier)
    canvas.event(ev)


def _release(canvas, pos, button=Qt.MouseButton.MiddleButton):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(*pos), button, Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier)
    canvas.event(ev)


def test_middle_button_pans_canvas(qapp):
    canvas = PreviewCanvasBase(_dialog_stub())
    start_pan = QPointF(canvas._pan)

    _press(canvas, (10, 10))
    assert canvas._panning is True
    _move(canvas, (25, 40))
    assert canvas._pan != start_pan
    assert canvas._pan == start_pan + QPointF(15, 30)
    _release(canvas, (25, 40))
    assert canvas._panning is False


def test_left_button_without_space_does_not_pan(qapp):
    canvas = PreviewCanvasBase(_dialog_stub())
    _press(canvas, (10, 10), button=Qt.MouseButton.LeftButton)
    assert canvas._panning is False


def test_space_held_makes_left_button_pan(qapp):
    canvas = PreviewCanvasBase(_dialog_stub())
    canvas._space = True
    _press(canvas, (10, 10), button=Qt.MouseButton.LeftButton)
    assert canvas._panning is True


def test_wheel_zoom_changes_zoom_and_keeps_pivot_stable():
    canvas = PreviewCanvasBase(_dialog_stub())
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)

    class FakeWheel:
        def angleDelta(self):
            return QPointF(0, 120)

        def position(self):
            return QPointF(20, 20)

    canvas.wheelEvent(FakeWheel())
    assert canvas.zoom > 1.0
    # the pivot point in image-space must not jump under the cursor
    img_x_before = (20 - 0) / 1.0
    img_x_after = (20 - canvas._pan.x()) / canvas.zoom
    assert abs(img_x_before - img_x_after) < 1e-6


def test_idle_cursor_hook_used_on_release(qapp):
    class BlankIdleCanvas(PreviewCanvasBase):
        def _idle_cursor(self):
            return Qt.CursorShape.BlankCursor

    canvas = BlankIdleCanvas(_dialog_stub())
    _press(canvas, (5, 5))
    _release(canvas, (5, 5))
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor


def test_no_preview_image_paints_without_crashing(qapp):
    canvas = PreviewCanvasBase(_dialog_stub())
    canvas.dialog.preview_img = None
    canvas.resize(50, 50)
    canvas.repaint()  # must not raise


def test_bare_subclass_mouse_events_return_none_to_qt(qapp):
    """Regression: the filter-gallery canvases (once bare `class
    X(PreviewCanvasBase): pass` per dialog, now ui.filter_gallery.
    GalleryCanvas and Liquify's canvas) — no Python override sits between Qt's dispatch and PreviewCanvasBase's own
    mousePressEvent/mouseMoveEvent. Those are void in C++; if the method
    Qt actually calls returns non-None, PyQt6 raises "TypeError: invalid
    result from X.mouseMoveEvent()" the moment a real mouse event arrives
    (crystallize/pointillize mode, reported live). canvas.event(ev) goes
    through the same dispatch path Qt itself uses, unlike calling
    mousePressEvent directly from Python — that's why this needs
    .event(), not a direct method call, to actually catch the bug."""
    from core.layer import RasterLayer
    from ui.noise_dialog import NoiseDialog
    from ui.stylize_dialog import StylizeDialog
    from ui.sharpen_dialog import SharpenDialog
    from ui.pixelate_dialog import PixelateDialog
    from ui.other_filters_dialog import OtherFiltersDialog
    from ui.distort_dialog import DistortDialog
    from ui.render_dialog import RenderDialog
    from ui.blur_gallery_dialog import BlurGalleryDialog
    from ui.specific_filters_dialog import SpecificFiltersDialog

    canvases = [PreviewCanvasBase(_dialog_stub())]
    for cls, mode in ((NoiseDialog, "median"), (StylizeDialog, "solarize"), (SharpenDialog, "unsharp"),
                      (PixelateDialog, "crystallize"), (OtherFiltersDialog, "high_pass"),
                      (DistortDialog, "twirl"), (RenderDialog, "lighting"), (BlurGalleryDialog, "iris"),
                      (SpecificFiltersDialog, "liquify")):
        layer = RasterLayer("r", 40, 30)
        layer.image.fill(QColor(120, 80, 40, 255))
        canvases.append(cls(layer, mode, lambda: None).canvas)
    for canvas in canvases:
        canvas.resize(100, 100)
        _press(canvas, (10, 10), button=Qt.MouseButton.MiddleButton)
        _move(canvas, (20, 30), buttons=Qt.MouseButton.MiddleButton)
        _release(canvas, (20, 30), button=Qt.MouseButton.MiddleButton)
        _press(canvas, (10, 10), button=Qt.MouseButton.LeftButton)
        _move(canvas, (20, 30), buttons=Qt.MouseButton.LeftButton)
        _release(canvas, (20, 30), button=Qt.MouseButton.LeftButton)


# --- DragCenterMixin (Blur Gallery / Distort / Render's grabbable center) ---

class _CenterCanvas(DragCenterMixin, PreviewCanvasBase):
    _center_hit_radius = 20


def test_drag_center_hit_moves_dialog_cx_cy(qapp):
    dialog = _dialog_stub(w=100, h=100)
    dialog.cx, dialog.cy = 50.0, 50.0
    triggered = []
    dialog._trigger_update = lambda: triggered.append(1)

    canvas = _CenterCanvas(dialog)
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)

    _press(canvas, (52, 51), button=Qt.MouseButton.LeftButton)  # within 20px of (50,50)
    assert canvas._dragging_center is True

    _move(canvas, (70, 80), buttons=Qt.MouseButton.LeftButton)
    assert dialog.cx == 70.0
    assert dialog.cy == 80.0
    assert triggered  # dialog._trigger_update() was called

    _release(canvas, (70, 80), button=Qt.MouseButton.LeftButton)
    assert canvas._dragging_center is False


def test_drag_center_miss_outside_radius_does_not_drag(qapp):
    dialog = _dialog_stub(w=100, h=100)
    dialog.cx, dialog.cy = 50.0, 50.0
    canvas = _CenterCanvas(dialog)
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)

    _press(canvas, (90, 90), button=Qt.MouseButton.LeftButton)  # far from center
    assert canvas._dragging_center is False


def test_drag_center_respects_center_active_hook(qapp):
    class GatedCenterCanvas(_CenterCanvas):
        def _center_active(self):
            return False

    dialog = _dialog_stub(w=100, h=100)
    dialog.cx, dialog.cy = 50.0, 50.0
    canvas = GatedCenterCanvas(dialog)
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)

    _press(canvas, (50, 50), button=Qt.MouseButton.LeftButton)
    assert canvas._dragging_center is False


# --- Integration smoke tests through real dialogs ---

def test_blur_gallery_dialog_drag_moves_focus_center(qapp, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    from core.document import Document
    from ui.blur_gallery_dialog import BlurGalleryDialog

    doc = Document(80, 60)
    layer = doc.layers[0]
    layer.image.fill(QColor(200, 200, 200, 255))

    dlg = BlurGalleryDialog(layer, "iris", lambda: None)
    canvas = dlg.canvas
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)
    old_cx, old_cy = dlg.cx, dlg.cy

    _press(canvas, (old_cx + 1, old_cy), button=Qt.MouseButton.LeftButton)
    assert canvas._dragging_center is True
    _move(canvas, (old_cx + 10, old_cy + 15), buttons=Qt.MouseButton.LeftButton)
    assert dlg.cx == old_cx + 10
    assert dlg.cy == old_cy + 15

    canvas.repaint()  # overlay drawing must not crash
    dlg.reject()


def test_select_and_mask_dialog_brush_stroke_paints_mask(qapp, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    from core.document import Document
    from ui.select_and_mask_dialog import SelectAndMaskDialog
    import numpy as np

    doc = Document(60, 60)
    doc.layers[0].image.fill(QColor(128, 128, 128, 255))

    dlg = SelectAndMaskDialog(doc)
    canvas = dlg.canvas
    assert canvas.dialog is dlg  # set via constructor now, not a follow-up assignment
    canvas.zoom = 1.0
    canvas._pan = QPointF(0, 0)
    canvas.resize(200, 200)

    assert dlg.active_tool == "refine"
    dlg.active_tool = "brush"  # "refine" needs pre-existing fg/bg marks to do anything on a blank mask
    before = dlg.base_mask.copy()
    _press(canvas, (30, 30), button=Qt.MouseButton.LeftButton)
    _move(canvas, (35, 35), buttons=Qt.MouseButton.LeftButton)
    _release(canvas, (35, 35), button=Qt.MouseButton.LeftButton)

    assert not np.array_equal(before, dlg.base_mask)  # stroke actually changed the mask
    canvas.repaint()
    dlg.reject()


# --- live-preview downscaling (the "all filters lag on my laptop" fix) ---
#
# Every dialog in this family re-ran _apply_effect() on the FULL image on
# every debounced slider tick — fine at a few megapixels, but a multi-
# second recompute per tick on an 8K+ photo. init_live_preview_arrays()
# swaps dialog.orig_img/.orig_arr for a capped-resolution proxy during
# interactive editing; restore_full_res_before_accept() swaps back (and
# rescales any image-space coordinates like Blur Gallery/Distort/Render's
# cx/cy) for exactly one full-resolution pass when the dialog is accepted.

class _FakeDialog:
    pass


def test_downscale_for_live_preview_noop_when_already_small():
    img = QImage(200, 150, QImage.Format.Format_ARGB32_Premultiplied)
    assert downscale_for_live_preview(img, max_dim=1600) is None


def test_downscale_for_live_preview_caps_long_edge_and_keeps_aspect(qapp):
    img = QImage(4000, 2000, QImage.Format.Format_ARGB32_Premultiplied)
    small = downscale_for_live_preview(img, max_dim=1000)
    assert small is not None
    assert small.width() == 1000
    assert small.height() == 500  # aspect ratio preserved


def test_init_live_preview_arrays_downscales_large_image(qapp):
    from core.document import Document
    doc = Document(4000, 2000)
    layer = doc.layers[0]
    layer.image.fill(QColor(100, 150, 200, 255))

    d = _FakeDialog()
    init_live_preview_arrays(d, layer, max_dim=1000)

    assert d.orig_img_full is not None
    assert d.orig_img_full.width() == 4000
    assert d.orig_img.width() == 1000
    assert d.orig_arr.shape[:2] == (500, 1000)
    assert d.preview_img.width() == 1000


def test_init_live_preview_arrays_leaves_small_image_untouched(qapp):
    from core.document import Document
    doc = Document(400, 300)
    layer = doc.layers[0]

    d = _FakeDialog()
    init_live_preview_arrays(d, layer, max_dim=1000)

    assert d.orig_img_full is None
    assert d.orig_img.width() == 400
    assert d.orig_arr.shape[:2] == (300, 400)


def test_restore_full_res_before_accept_returns_false_when_not_downscaled(qapp):
    from core.document import Document
    doc = Document(400, 300)
    d = _FakeDialog()
    init_live_preview_arrays(d, doc.layers[0], max_dim=1000)
    assert restore_full_res_before_accept(d) is False
    assert d.orig_arr.shape[:2] == (300, 400)


def test_restore_full_res_before_accept_restores_full_image_and_rescales_coords(qapp):
    from core.document import Document
    doc = Document(4000, 2000)
    layer = doc.layers[0]
    layer.image.fill(QColor(10, 20, 30, 255))

    d = _FakeDialog()
    init_live_preview_arrays(d, layer, max_dim=1000)
    d.cx = 500.0  # set as if dragged on the 1000px-wide downscaled canvas
    d.cy = 250.0

    assert restore_full_res_before_accept(d, scale_attrs=("cx", "cy")) is True
    assert d.orig_img.width() == 4000
    assert d.orig_arr.shape[:2] == (2000, 4000)
    assert d.cx == 2000.0  # 500 * (4000/1000)
    assert d.cy == 1000.0
    # calling again is a no-op (already at full res)
    assert restore_full_res_before_accept(d, scale_attrs=("cx", "cy")) is False
    assert d.cx == 2000.0
