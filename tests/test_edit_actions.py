"""Copy/paste with an active selection must preserve the selection's position.

Regression test: paste used to always re-center the clipboard on the canvas,
discarding the selection's original location entirely.
"""

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainterPath

from core.document import Document


def test_paste_lands_at_selection_origin_not_canvas_center(main_window):
    w = main_window
    w._add_tab(Document(100, 80), "t")
    layer = w._document.get_active_layer()
    layer.image.fill(QColor(10, 10, 10))

    # Off-center rectangular selection, well away from the canvas center.
    path = QPainterPath()
    path.addRect(5, 5, 20, 15)
    w._document.selection = path

    marker = QColor(200, 50, 50)
    for y in range(5, 20):
        for x in range(5, 25):
            layer.image.setPixelColor(x, y, marker)

    w._copy()
    w._document.selection = None
    w._paste()

    pasted = w._document.layers[-1]
    assert pasted.offset.x() == 0 and pasted.offset.y() == 0  # full-canvas layer, content is placed via pixels

    # Content must reappear at the same (5, 5) origin it was copied from,
    # not centered on the 100x80 canvas.
    assert pasted.image.pixelColor(5, 5) == marker
    assert pasted.image.pixelColor(24, 19) == marker
    # Canvas-center pixel must NOT have received the pasted content.
    assert pasted.image.pixelColor(50, 40) != marker


def test_copy_masks_pixels_outside_a_non_rectangular_selection(main_window):
    """Regression: copy used to only crop to the selection's bounding box,
    so an elliptical/lasso selection would still bring along the square
    corner pixels that were never actually selected."""
    w = main_window
    w._add_tab(Document(40, 40), "t")
    layer = w._document.get_active_layer()
    layer.image.fill(QColor(10, 10, 10, 255))

    path = QPainterPath()
    path.addEllipse(QRectF(5, 5, 20, 20))  # bbox: (5,5)-(25,25)
    w._document.selection = path

    w._copy()

    clip = w._clipboard
    # Center of the ellipse's bbox must be fully opaque (inside the shape).
    assert clip.pixelColor(clip.width() // 2, clip.height() // 2).alpha() == 255
    # The bbox's corners lie outside the ellipse and must be masked to transparent.
    assert clip.pixelColor(0, 0).alpha() == 0
    assert clip.pixelColor(clip.width() - 1, clip.height() - 1).alpha() == 0


def test_paste_without_selection_still_centers(main_window):
    """No selection at copy time -> clipboard is the whole (smaller) source
    layer, and pasting into a larger canvas must fall back to centering."""
    w = main_window
    w._add_tab(Document(10, 10), "src")
    marker = QColor(80, 160, 240)
    w._document.get_active_layer().image.fill(marker)

    w._document.selection = None
    w._copy()

    w._add_tab(Document(100, 80), "dst")
    w._paste()

    pasted = w._document.layers[-1]
    cx = (100 - 10) // 2
    cy = (80 - 10) // 2
    assert pasted.image.pixelColor(cx, cy) == marker
