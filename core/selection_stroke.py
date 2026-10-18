"""Edit > Stroke: a band of colour along the selection edge (Photoshop's
Stroke dialog — width, colour, location, blend mode, opacity, preserve
transparency)."""
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPainterPathStroker

from core.blend_modes import composition_mode

LOCATIONS = ("inside", "center", "outside")


def stroke_region(selection: QPainterPath, width: float, location: str) -> QPainterPath:
    """The band `width` px wide along the selection edge — inside it,
    centred on it, or outside it."""
    stroker = QPainterPathStroker()
    stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
    if location == "center":
        stroker.setWidth(width)
        return stroker.createStroke(selection).simplified()
    stroker.setWidth(width * 2)
    band = stroker.createStroke(selection).simplified()
    sel = selection.simplified()
    return band.intersected(sel) if location == "inside" else band.subtracted(sel)


def stroke_selection(image: QImage, offset: QPoint, selection: QPainterPath, *, width: float,
                     color: QColor, location: str = "center", blend_mode: str = "SourceOver",
                     opacity: float = 100.0, preserve_transparency: bool = False) -> QImage:
    """`image` (placed at document `offset`) with the stroke painted in;
    may return a new image."""
    region = stroke_region(selection, width, location).translated(-offset.x(), -offset.y())
    if preserve_transparency:
        from core.layer_styles import _blend_overlay
        return _blend_overlay(image, QBrush(color), blend_mode, opacity, area=region)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setCompositionMode(composition_mode(blend_mode))
    p.setOpacity(max(0.0, min(1.0, opacity / 100.0)))
    p.fillPath(region, color)
    p.end()
    return image
