from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from core.locale import tr


class EditActionsMixin:
    def _undo(self):
        # Если активна рамка трансформации, Ctrl+Z работает как Escape (Отмена трансформации)
        tool = self._canvas.active_tool
        if hasattr(tool, "is_transforming") and getattr(tool, "is_transforming", False):
            tool.cancel_transform(self._document)
            self._canvas_refresh()
            return

        from core.history import HistoryState
        state = self._history.undo()
        if not state:
            return
        self._history.save_for_redo(HistoryState(
            description="redo",
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
            doc_width=self._document.width,
            doc_height=self._document.height,
            selection_snapshot=QPainterPath(self._document.selection) if self._document.selection else None,
        ))
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._document.selection = QPainterPath(state.selection_snapshot) if state.selection_snapshot else None
        if state.doc_width and state.doc_height:
            dims_changed = (self._document.width != state.doc_width or
                            self._document.height != state.doc_height)
            self._document.width  = state.doc_width
            self._document.height = state.doc_height
            if dims_changed:
                self._canvas.reset_zoom()
        self._refresh_layers()
        self._canvas_refresh()
        self._status.showMessage(tr("status.undo", desc=state.description))

    def _redo(self):
        from core.history import HistoryState
        state = self._history.redo()
        if not state:
            return
        self._history.push(HistoryState(
            description="undo",
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
            doc_width=self._document.width,
            doc_height=self._document.height,
            selection_snapshot=QPainterPath(self._document.selection) if self._document.selection else None,
        ))
        self._document.restore_layers(state.layers_snapshot)
        self._document.active_layer_index = state.active_layer_index
        self._document.selection = QPainterPath(state.selection_snapshot) if state.selection_snapshot else None
        if state.doc_width and state.doc_height:
            dims_changed = (self._document.width != state.doc_width or
                            self._document.height != state.doc_height)
            self._document.width  = state.doc_width
            self._document.height = state.doc_height
            if dims_changed:
                self._canvas.reset_zoom()
        self._refresh_layers()
        self._canvas_refresh()

    def _clear_layer(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
            
        tool = self._canvas.active_tool
        if self._active_tool_name == "Move" and hasattr(tool, "is_transforming") and tool.is_transforming:
            is_float = getattr(tool, "_is_floating", False)
            tool.cancel_transform(self._document)
            self._push_history(tr("history.clear_layer"))
            if is_float:
                sel = self._document.selection
                if sel and not sel.isEmpty():
                    p = QPainter(layer.image)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                    p.setClipPath(sel)
                    p.fillRect(sel.boundingRect().toRect(), QColor(0, 0, 0, 0))
                    p.end()
                self._document.selection = None
            else:
                layer.image.fill(Qt.GlobalColor.transparent)
            self._canvas_refresh()
            return
            
        self._push_history(tr("history.clear_layer"))
        sel = self._document.selection
        if sel and not sel.isEmpty():
            p = QPainter(layer.image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setClipPath(sel)
            p.fillRect(sel.boundingRect().toRect(), QColor(0, 0, 0, 0))
            p.end()
        else:
            layer.image.fill(Qt.GlobalColor.transparent)
        self._canvas_refresh()

    def _deselect(self):
        # Сохраняем текущее выделение для функции Reselect
        if self._document.selection and not self._document.selection.isEmpty():
            self._last_selection = QPainterPath(self._document.selection)
            self._push_history(tr("history.deselect"))

        self._document.selection = None
        self._canvas_refresh()

    def _select_all(self):
        self._push_history(tr("history.select_all"))
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self._document.width, self._document.height))
        self._document.selection = p
        self._canvas_refresh()

    def _reselect(self):
        # Восстанавливаем последнее снятое выделение
        if hasattr(self, "_last_selection") and self._last_selection:
            self._push_history(tr("history.reselect"))
            self._document.selection = QPainterPath(self._last_selection)
            self._canvas_refresh()

    def _inverse_selection(self):
        self._push_history(tr("history.inverse"))
        sel = self._document.selection

        if not sel or sel.isEmpty():
            # Если ничего не выделено, инверсия выделяет весь холст
            self._select_all()
        else:
            # Вычитаем текущее выделение из площади всего холста
            full_rect = QPainterPath()
            full_rect.addRect(QRectF(0, 0, self._document.width, self._document.height))
            self._document.selection = full_rect.subtracted(sel)
            self._canvas_refresh()

    def _color_range(self):
        layer = self._document.get_active_layer()
        if not layer or layer.image.isNull():
            return
        
        from core.history import HistoryState
        pre_state = HistoryState(
            description=tr("history.color_range"),
            layers_snapshot=self._document.snapshot_layers(),
            active_layer_index=self._document.active_layer_index,
            doc_width=self._document.width,
            doc_height=self._document.height,
            selection_snapshot=QPainterPath(self._document.selection) if self._document.selection else None,
        )
        
        from ui.color_range_dialog import ColorRangeDialog
        dlg = ColorRangeDialog(self._document, self._canvas_refresh, self)
        if dlg.exec():
            self._history.push(pre_state)
        else:
            self._document.selection = pre_state.selection_snapshot
            self._canvas_refresh()

    def _cut(self):
        if hasattr(self, "_commit_move_transform"):
            self._commit_move_transform()
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
        if hasattr(self, "_commit_move_transform"):
            self._commit_move_transform()
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
