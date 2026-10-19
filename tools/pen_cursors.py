"""Pen tool cursors: a pen nib with Photoshop's badges telling what a click
will do — "+" add anchor, "-" delete anchor, "o" close the path, "^" convert
point, "*" start a new path, "" plain (continue drawing)."""
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QCursor, QPainter, QPen, QPixmap, QPolygonF

_cache: dict[str, QCursor] = {}

SIZE = 32
HOT = (1, 1)           # the nib's tip


def pen_cursor(badge: str = "") -> QCursor:
    if badge in _cache:
        return _cache[badge]
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # The nib: tip at the hotspot, body towards the bottom-right.
    nib = QPolygonF([QPointF(1, 1), QPointF(13, 6), QPointF(16, 16), QPointF(6, 13)])
    p.setPen(QPen(Qt.GlobalColor.black, 1.2))
    p.setBrush(Qt.GlobalColor.white)
    p.drawPolygon(nib)
    p.drawLine(QPointF(1, 1), QPointF(9.5, 9.5))             # the slit
    p.setBrush(Qt.GlobalColor.black)
    p.drawEllipse(QPointF(10, 10), 1.3, 1.3)
    p.drawLine(QPointF(16, 16), QPointF(19, 19))             # holder

    if badge:
        cx, cy, r = 24.0, 24.0, 4.0
        for color, width in ((Qt.GlobalColor.white, 3.4), (Qt.GlobalColor.black, 1.4)):
            p.setPen(QPen(color, width, cap=Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if badge == "+":
                p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
                p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
            elif badge == "-":
                p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
            elif badge == "o":
                p.drawEllipse(QPointF(cx, cy), r - 0.5, r - 0.5)
            elif badge == "^":
                p.drawLine(QPointF(cx - r, cy + r * 0.6), QPointF(cx, cy - r * 0.6))
                p.drawLine(QPointF(cx, cy - r * 0.6), QPointF(cx + r, cy + r * 0.6))
            elif badge == "*":
                for a, b in (((-r, 0), (r, 0)), ((-r * 0.6, -r * 0.8), (r * 0.6, r * 0.8)),
                             ((-r * 0.6, r * 0.8), (r * 0.6, -r * 0.8))):
                    p.drawLine(QPointF(cx + a[0], cy + a[1]), QPointF(cx + b[0], cy + b[1]))
    p.end()
    cursor = QCursor(px, *HOT)
    _cache[badge] = cursor
    return cursor
