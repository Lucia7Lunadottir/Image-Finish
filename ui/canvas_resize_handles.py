"""Canvas-size handles on the canvas edges, as in Microsoft Paint: small
squares at the middle of the right edge, the middle of the bottom edge
and the bottom-right corner. Dragging one shows the new size as a dashed
frame with "W × H"; releasing asks the window to resize the canvas (image
anchored at the top-left, see Document.resize_canvas).

Hidden while the document has artboards (its size follows them) or the
view is rotated.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from ui import theme

HANDLE = 7          # px, side of a handle square on screen
GAP = 3             # px between the canvas edge and a handle
_CURSORS = {"r": Qt.CursorShape.SizeHorCursor, "b": Qt.CursorShape.SizeVerCursor,
            "br": Qt.CursorShape.SizeFDiagCursor}


class CanvasResizeHandles:
    def __init__(self, canvas, on_resize):
        self._canvas = canvas
        self._on_resize = on_resize          # callable(width, height)
        self._drag = None                    # handle name while dragging
        self._size = None                    # (w, h) the drag currently shows

    @property
    def active(self) -> bool:
        return self._drag is not None

    def _visible(self) -> bool:
        c = self._canvas
        doc = c.document
        return (doc is not None and not c._view_rotation and not c._stroke_in_progress
                and not doc.artboards())

    def _rects(self) -> dict:
        """Widget-space squares, keyed "r", "b", "br"."""
        c = self._canvas
        w, h = self._size if self._size else (c.document.width, c.document.height)
        right = c.to_widget(QPointF(w, 0)).x() + GAP
        bottom = c.to_widget(QPointF(0, h)).y() + GAP
        left = c.to_widget(QPointF(0, 0)).x()
        top = c.to_widget(QPointF(0, 0)).y()
        mid_x, mid_y = (left + right - GAP) / 2, (top + bottom - GAP) / 2
        return {
            "r": QRectF(right, mid_y - HANDLE / 2, HANDLE, HANDLE),
            "b": QRectF(mid_x - HANDLE / 2, bottom, HANDLE, HANDLE),
            "br": QRectF(right, bottom, HANDLE, HANDLE),
        }

    def hit(self, pos: QPointF):
        if not self._visible():
            return None
        for name, r in self._rects().items():
            if r.adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return None

    def cursor_at(self, pos: QPointF):
        name = self._drag or self.hit(pos)
        return _CURSORS.get(name)

    # ------------------------------------------------------------ drag
    def press(self, ev) -> bool:
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        name = self.hit(ev.position())
        if name is None:
            return False
        self._drag = name
        self._size = (self._canvas.document.width, self._canvas.document.height)
        self._canvas.setCursor(_CURSORS[name])
        return True

    def move(self, ev) -> bool:
        if self._drag is None:
            return False
        c = self._canvas
        doc_pos = c.to_doc(ev.position())
        w, h = c.document.width, c.document.height
        if self._drag in ("r", "br"):
            w = max(1, round(doc_pos.x()))
        if self._drag in ("b", "br"):
            h = max(1, round(doc_pos.y()))
        self._size = (w, h)
        c.update()
        return True

    def release(self, ev) -> bool:
        if self._drag is None:
            return False
        size, self._drag, self._size = self._size, None, None
        self._canvas._update_cursor()
        self._canvas.update()
        if size != (self._canvas.document.width, self._canvas.document.height):
            self._on_resize(*size)
        return True

    # ------------------------------------------------------------ paint
    def paint(self, painter):
        if not self._visible():
            return
        c = self._canvas
        painter.save()
        painter.resetTransform()
        if self._size is not None:
            w, h = self._size
            frame = QRectF(c.to_widget(QPointF(0, 0)), c.to_widget(QPointF(w, h)))
            pen = QPen(QColor(theme.TEXT), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(frame)
            label = f"{w} × {h}"
            fm = painter.fontMetrics()
            box = QRectF(frame.right() + 10, frame.bottom() + 10,
                         fm.horizontalAdvance(label) + 12, fm.height() + 6)
            painter.fillRect(box, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QPen(QColor(theme.SURFACE2), 1))
        painter.setBrush(QColor(theme.TEXT))
        for r in self._rects().values():
            painter.drawRect(r)
        painter.restore()
