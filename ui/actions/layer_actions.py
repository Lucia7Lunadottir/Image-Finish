from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QPainter
from core.locale import tr


class LayerActionsMixin:
    def _refresh_layers(self):
        self._layers_panel.refresh(self._document)
        self._update_status()

    def _on_layer_selected(self, index: int):
        self._document.active_layer_index = index
        self._refresh_layers()

    def _on_layer_visibility(self, index: int, visible: bool):
        self._document.layers[index].visible = visible
        self._canvas_refresh()

    def _on_layer_opacity(self, index: int, opacity: float):
        self._document.layers[index].opacity = opacity
        self._canvas_refresh()
        self._refresh_layers()

    def _add_layer(self):
        self._push_history(tr("history.add_layer"))
        self._document.add_layer()
        self._refresh_layers()
        self._canvas_refresh()

    def _duplicate_layer(self):
        self._push_history(tr("history.duplicate_layer"))
        self._document.duplicate_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    def _delete_layer(self):
        if len(self._document.layers) <= 1:
            QMessageBox.warning(self, tr("err.title.delete_layer"), tr("err.delete_last_layer"))
            return
        self._push_history(tr("history.delete_layer"))
        self._document.remove_layer(self._document.active_layer_index)
        self._refresh_layers()
        self._canvas_refresh()

    def _layer_up(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_up"))
        self._document.move_layer(i, i + 1)
        self._refresh_layers()
        self._canvas_refresh()

    def _layer_down(self):
        i = self._document.active_layer_index
        self._push_history(tr("history.layer_down"))
        self._document.move_layer(i, i - 1)
        self._refresh_layers()
        self._canvas_refresh()

    def _merge_down(self):
        i = self._document.active_layer_index
        if i == 0:
            return
        self._push_history(tr("history.merge_down"))
        bottom = self._document.layers[i - 1]
        top    = self._document.layers[i]
        p = QPainter(bottom.image)
        p.setOpacity(top.opacity)
        p.drawImage(top.offset, top.image)
        p.end()
        self._document.remove_layer(i)
        self._refresh_layers()
        self._canvas_refresh()

    def _flatten(self):
        self._push_history(tr("history.flatten"))
        self._document.flatten()
        self._refresh_layers()
        self._canvas_refresh()
