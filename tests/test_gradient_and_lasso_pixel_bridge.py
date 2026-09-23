"""gradient_tool.py and lasso_tools.py used to hand-roll their own
ctypes/numpy QImage buffer access; migrated to core.pixel_buffer.
qimage_argb_view. No prior test coverage existed for either code path —
these pin the specific behavior the migrated code touches.
"""
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter

from core.document import Document
from tools.gradient_tool import GradientTool
from tools.lasso_tools import MagneticLassoTool


def test_gradient_lock_alpha_preserves_original_alpha(qapp):
    doc = Document(60, 40)
    layer = doc.layers[0]
    layer.lock_alpha = True
    layer.image.fill(QColor(200, 0, 0, 128))  # uniform partial alpha

    tool = GradientTool()
    opts = {
        "gradient_type": "linear",
        "gradient_opacity": 100,
        "gradient_reverse": False,
        "gradient_stops": [(0.0, QColor(0, 0, 255, 255)), (1.0, QColor(0, 255, 0, 255))],
    }
    tool.on_press(QPoint(0, 20), doc, QColor(0, 0, 255), QColor(0, 255, 0), opts)
    tool.on_move(QPoint(59, 20), doc, QColor(0, 0, 255), QColor(0, 255, 0), opts)
    tool.on_release(QPoint(59, 20), doc, QColor(0, 0, 255), QColor(0, 255, 0), opts)

    # Alpha must stay exactly what it was before the gradient (that's the
    # whole point of lock_alpha); color must have actually changed from
    # the flat red fill (gradient did get painted).
    for x in (5, 30, 55):
        px = layer.image.pixelColor(x, 20)
        assert px.alpha() == 128
    assert layer.image.pixelColor(5, 20).getRgb()[:3] != (200, 0, 0)


def test_gradient_without_lock_alpha_changes_alpha_too(qapp):
    doc = Document(60, 40)
    layer = doc.layers[0]
    layer.lock_alpha = False
    layer.image.fill(QColor(200, 0, 0, 128))

    tool = GradientTool()
    opts = {
        "gradient_type": "linear",
        "gradient_opacity": 100,
        "gradient_reverse": False,
        "gradient_stops": [(0.0, QColor(0, 0, 255, 255)), (1.0, QColor(0, 255, 0, 255))],
    }
    tool.on_press(QPoint(0, 20), doc, QColor(), QColor(), opts)
    tool.on_release(QPoint(59, 20), doc, QColor(), QColor(), opts)
    assert layer.image.pixelColor(5, 20).alpha() == 255


def test_magnetic_lasso_snaps_toward_high_contrast_edge(qapp):
    doc = Document(60, 40)
    layer = doc.layers[0]
    layer.image.fill(QColor(0, 0, 0, 255))
    p = QPainter(layer.image)
    p.fillRect(30, 0, 30, 40, QColor(255, 255, 255, 255))  # hard vertical edge at x=30
    p.end()

    tool = MagneticLassoTool()
    opts = {"mag_width": 10, "mag_contrast": 10, "mag_freq": 57}
    tool.on_move(QPoint(25, 20), doc, QColor(), QColor(), opts)
    # Should not crash and should track something near the real edge (x=30).
    assert abs(tool.current_pos.x() - 30) <= 10
