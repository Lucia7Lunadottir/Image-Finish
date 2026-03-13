from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from core.locale import tr


class EditActionsMixin:
    def _undo(self):
        from core.history import HistoryState
        state = self._history.undo()
        if not state:
            return
        self._history.save_for_redo(HistoryState(
            description="redo",
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
        ))
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._refresh_layers()
        self._canvas_refresh()
        self._status.showMessage(tr("status.undo", desc=state.description))

    def _redo(self):
        state = self._history.redo()
        if not state:
            return
        self._push_history("undo")
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._refresh_layers()
        self._canvas_refresh()

    def _clear_layer(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.clear_layer"))
        layer.image.fill(Qt.GlobalColor.transparent)
        self._canvas_refresh()

    def _deselect(self):
        self._document.selection = None
        self._canvas_refresh()

    def _select_all(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self._document.width, self._document.height))
        self._document.selection = p
        self._canvas_refresh()

    def _cut(self):
        self._copy()
        layer = self._document.get_active_layer()
        if not layer:
            return
        sel = self._document.selection
        if sel and not sel.isEmpty():
            self._push_history(tr("history.cut"))
            p = QPainter(layer.image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setClipPath(sel)
            p.fillRect(sel.boundingRect().toRect(), QColor(0, 0, 0, 0))
            p.end()
            self._canvas_refresh()

    def _copy(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        sel = self._document.selection
        if sel and not sel.isEmpty():
            self._clipboard = layer.image.copy(sel.boundingRect().toRect())
        else:
            self._clipboard = layer.image.copy()

    def _paste(self):
        if not hasattr(self, "_clipboard") or self._clipboard is None:
            return
        self._push_history(tr("history.paste"))
        from core.layer import Layer
        from PyQt6.QtCore import QPoint
        new_layer = Layer(f"Pasted {len(self._document.layers)+1}",
                          self._document.width, self._document.height)
        cx = (self._document.width  - self._clipboard.width())  // 2
        cy = (self._document.height - self._clipboard.height()) // 2
        p = QPainter(new_layer.image)
        p.drawImage(QPoint(cx, cy), self._clipboard)
        p.end()
        self._document.layers.append(new_layer)
        self._document.active_layer_index = len(self._document.layers) - 1
        self._refresh_layers()
        self._canvas_refresh()

    def _fill_fg(self):
        self._fill_with(self._canvas.fg_color)

    def _fill_bg(self):
        self._fill_with(self._canvas.bg_color)

    def _fill_with(self, color: QColor):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.fill"))
        p = QPainter(layer.image)
        sel = self._document.selection
        if sel and not sel.isEmpty():
            p.setClipPath(sel)
            p.fillRect(sel.boundingRect().toRect(), color)
            p.setClipping(False)
        else:
            p.fillRect(layer.image.rect(), color)
        p.end()
        self._canvas_refresh()
