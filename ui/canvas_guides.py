"""Guides on the canvas: dragging a new one out of a ruler, or (Move tool)
picking up an existing one; dropping it back onto the ruler deletes it.
Was spread over CanvasWidget's press, move and release handlers."""
from PyQt6.QtCore import Qt, QPoint

RULER_SIZE = 20     # px, the rulers' thickness


class GuideDrag:
    def __init__(self, canvas):
        self._canvas = canvas
        # ('v' | 'h', document coordinate, index it came from or None)
        self.current = None

    @property
    def active(self) -> bool:
        return self.current is not None

    def press(self, ev) -> bool:
        c = self._canvas
        if getattr(c, "show_rulers", False):
            pos = ev.position()
            if pos.x() < RULER_SIZE and pos.y() > RULER_SIZE:
                return self._start('v', c.to_doc(pos).x(), None)
            if pos.y() < RULER_SIZE and pos.x() > RULER_SIZE:
                return self._start('h', c.to_doc(pos).y(), None)

        if getattr(c.active_tool, "name", "") != "Move" or c._space:
            return False
        doc, doc_pos = c.document, c.to_doc(ev.position())
        snap = 5 / max(0.01, c.zoom)
        hit_v = hit_h = None
        if getattr(doc, "show_guides", False):
            for i, gx in enumerate(doc.guides_v):
                if abs(gx - doc_pos.x()) < snap: hit_v = (i, gx)
            for i, gy in enumerate(doc.guides_h):
                if abs(gy - doc_pos.y()) < snap: hit_h = (i, gy)
        if hit_v:
            doc.guides_v.pop(hit_v[0])
            self._start('v', hit_v[1], hit_v[0])
        elif hit_h:
            doc.guides_h.pop(hit_h[0])
            self._start('h', hit_h[1], hit_h[0])
        else:
            return False
        c.update()
        return True

    def _start(self, kind, value, index) -> bool:
        self.current = (kind, value, index)
        self._canvas.setCursor(Qt.CursorShape.SplitHCursor if kind == 'v' else Qt.CursorShape.SplitVCursor)
        return True

    def move(self, ev) -> bool:
        if self.current is None:
            return False
        kind, _, index = self.current
        doc_pos = self._canvas.to_doc(ev.position())
        self.current = (kind, doc_pos.x() if kind == 'v' else doc_pos.y(), index)
        self._canvas.update()
        return True

    def release(self, ev) -> bool:
        if self.current is None:
            return False
        c = self._canvas
        kind, value, _ = self.current
        ruler = RULER_SIZE if c.show_rulers else 0
        # Dropped onto the ruler = deleted
        if kind == 'v' and c.to_widget(QPoint(int(value), 0)).x() > ruler:
            c.document.guides_v.append(value)
        elif kind == 'h' and c.to_widget(QPoint(0, int(value))).y() > ruler:
            c.document.guides_h.append(value)
        self.current = None
        c._update_cursor()
        c.update()
        return True
