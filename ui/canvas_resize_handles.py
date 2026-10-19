"""Canvas-size handles on the canvas edges, as in Microsoft Paint — on all
four sides: a small square at the middle of each edge and at each corner.
Dragging one shows the new canvas as a dashed frame with "W × H";
releasing asks the window to extend the canvas by that much on each side
(Document.extend_canvas: growing on the left / top moves the content
with it).

Hidden while the document has artboards (its size follows them) or the
view is rotated.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from ui import theme

HANDLE = 7          # px, side of a handle square on screen
GAP = 3             # px between the canvas edge and a handle

# handle -> (moves left edge, moves top edge, moves right edge, moves bottom edge)
_EDGES = {
    "l": (True, False, False, False), "r": (False, False, True, False),
    "t": (False, True, False, False), "b": (False, False, False, True),
    "tl": (True, True, False, False), "tr": (False, True, True, False),
    "bl": (True, False, False, True), "br": (False, False, True, True),
}
_CURSORS = {"l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
            "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor}


class CanvasResizeHandles:
    def __init__(self, canvas, on_extend):
        self._canvas = canvas
        self._on_extend = on_extend          # callable(left, top, right, bottom)
        self._drag = None                    # handle name while dragging
        self._ext = None                     # (left, top, right, bottom) the drag shows

    @property
    def active(self) -> bool:
        return self._drag is not None

    @property
    def _size(self):
        """(w, h) the drag currently shows, or None."""
        if self._ext is None:
            return None
        doc = self._canvas.document
        l, t, r, b = self._ext
        return doc.width + l + r, doc.height + t + b

    def _visible(self) -> bool:
        c = self._canvas
        doc = c.document
        return (doc is not None and not c._view_rotation and not c._stroke_in_progress
                and not doc.artboards())

    def _frame(self) -> QRectF:
        """The (new) canvas in document coordinates."""
        doc = self._canvas.document
        l, t, r, b = self._ext or (0, 0, 0, 0)
        return QRectF(-l, -t, doc.width + l + r, doc.height + t + b)

    def _rects(self) -> dict:
        """Widget-space squares, keyed by handle name."""
        c = self._canvas
        f = self._frame()
        tl = c.to_widget(f.topLeft())
        br = c.to_widget(f.bottomRight())
        left, top = tl.x() - GAP - HANDLE, tl.y() - GAP - HANDLE
        right, bottom = br.x() + GAP, br.y() + GAP
        mid_x = (tl.x() + br.x()) / 2 - HANDLE / 2
        mid_y = (tl.y() + br.y()) / 2 - HANDLE / 2
        xs = {"l": left, "r": right, "m": mid_x}
        ys = {"t": top, "b": bottom, "m": mid_y}
        spots = {"l": ("l", "m"), "r": ("r", "m"), "t": ("m", "t"), "b": ("m", "b"),
                 "tl": ("l", "t"), "tr": ("r", "t"), "bl": ("l", "b"), "br": ("r", "b")}
        return {name: QRectF(xs[x], ys[y], HANDLE, HANDLE) for name, (x, y) in spots.items()}

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
        self._ext = (0, 0, 0, 0)
        self._canvas.setCursor(_CURSORS[name])
        return True

    def move(self, ev) -> bool:
        if self._drag is None:
            return False
        c = self._canvas
        doc = c.document
        p = c.to_doc(ev.position())
        moves_l, moves_t, moves_r, moves_b = _EDGES[self._drag]
        l, t, r, b = self._ext
        # Each moving edge follows the pointer; the canvas keeps >= 1 px.
        if moves_l:
            l = max(-round(p.x()), 1 - doc.width - r)
        if moves_r:
            r = max(round(p.x()) - doc.width, 1 - doc.width - l)
        if moves_t:
            t = max(-round(p.y()), 1 - doc.height - b)
        if moves_b:
            b = max(round(p.y()) - doc.height, 1 - doc.height - t)
        self._ext = (l, t, r, b)
        c.update()
        return True

    def release(self, ev) -> bool:
        if self._drag is None:
            return False
        ext, self._drag, self._ext = self._ext, None, None
        self._canvas._update_cursor()
        self._canvas.update()
        if any(ext):
            self._on_extend(*ext)
        return True

    # ------------------------------------------------------------ paint
    def paint(self, painter):
        if not self._visible():
            return
        c = self._canvas
        painter.save()
        painter.resetTransform()
        if self._ext is not None:
            w, h = self._size
            f = self._frame()
            frame = QRectF(c.to_widget(f.topLeft()), c.to_widget(f.bottomRight()))
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
