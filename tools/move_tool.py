from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QImage, QPainterPath
from tools.base_tool import BaseTool


class MoveTool(BaseTool):
    """
    Без выделения  → двигает весь активный слой.
    С выделением   → вырезает выделенные пиксели и тащит их (с превью).
    """
    name = "Move"
    icon = "✋"
    shortcut = "V"

    def __init__(self):
        self._last:         QPoint       | None = None
        self._floating:     QImage       | None = None
        self._floating_pos: QPoint       | None = None
        self._sel_origin:   QPainterPath | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        self._last = pos
        sel = doc.selection
        if not (sel and not sel.isEmpty()):
            return

        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return

        br = sel.boundingRect().toRect()
        self._floating = layer.image.copy(br)
        local_sel = sel.translated(-br.x(), -br.y())
        full = QPainterPath()
        full.addRect(QRectF(self._floating.rect()))
        outside = full.subtracted(local_sel)
        mp = QPainter(self._floating)
        mp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        mp.setClipPath(outside)
        mp.fillRect(self._floating.rect(), QColor(0, 0, 0, 0))
        mp.end()

        p = QPainter(layer.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setClipPath(sel)
        p.fillRect(br, QColor(0, 0, 0, 0))
        p.end()

        self._floating_pos = br.topLeft()
        self._sel_origin   = QPainterPath(sel)

    def on_move(self, pos, doc, fg, bg, opts):
        if not self._last:
            return
        delta = pos - self._last
        self._last = pos

        if self._floating is not None:
            self._floating_pos = self._floating_pos + delta
            doc.selection = self._sel_origin.translated(
                self._floating_pos.x() - self._sel_origin.boundingRect().x(),
                self._floating_pos.y() - self._sel_origin.boundingRect().y(),
            )
        else:
            layer = doc.get_active_layer()
            if layer:
                layer.offset = layer.offset + delta

    def on_release(self, pos, doc, fg, bg, opts):
        if self._floating is not None and self._floating_pos is not None:
            layer = doc.get_active_layer()
            if layer:
                p = QPainter(layer.image)
                p.drawImage(self._floating_pos, self._floating)
                p.end()
            self._floating     = None
            self._floating_pos = None
            self._sel_origin   = None
        self._last = None

    def floating_preview(self):
        if self._floating is not None and self._floating_pos is not None:
            return (self._floating, self._floating_pos)
        return None

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.SizeAllCursor
