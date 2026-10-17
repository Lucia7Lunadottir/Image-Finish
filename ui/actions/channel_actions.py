"""Channels panel: channel view, saving/loading selections as alpha channels (moved out of MainWindow)."""

from PyQt6.QtGui import QPainterPath
from core.locale import tr
from ui.document_controller import require_document


class ChannelActionsMixin:
    def _on_channel_changed(self, ch: str):
        if not self._canvas:
            return
        self._canvas.view_channel = ch
        self._canvas_refresh()

    @require_document
    def _save_selection(self):
        sel = self._document.selection
        if not sel or sel.isEmpty():
            return
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, tr("menu.save_selection"), tr("dlg.define_name"))
        if ok and name:
            self._push_history(tr("history.save_selection"))
            if not hasattr(self._document, "alpha_channels"):
                self._document.alpha_channels = []
            self._document.alpha_channels.append({"name": name, "path": QPainterPath(sel)})
            self._channels_panel.refresh(self._document)

    @require_document
    def _load_selection(self):
        if not hasattr(self._document, "alpha_channels") or not self._document.alpha_channels:
            return
        from PyQt6.QtWidgets import QInputDialog
        names = [ch["name"] for ch in self._document.alpha_channels]
        name, ok = QInputDialog.getItem(self, tr("menu.load_selection"), "Channel:", names, 0, False)
        if ok and name:
            for ch in self._document.alpha_channels:
                if ch["name"] == name:
                    self._document.selection = QPainterPath(ch["path"])
                    self._push_history(tr("history.load_selection"))
                    self._canvas_refresh()
                    break

    @require_document
    def _load_selection_btn(self, idx):
        if hasattr(self._document, "alpha_channels") and 0 <= idx < len(self._document.alpha_channels):
            self._document.selection = QPainterPath(self._document.alpha_channels[idx]["path"])
            self._push_history(tr("history.load_selection"))
            self._canvas_refresh()

    @require_document
    def _delete_alpha_channel(self, idx):
        if hasattr(self._document, "alpha_channels") and 0 <= idx < len(self._document.alpha_channels):
            self._push_history(tr("history.delete_layer"))
            self._document.alpha_channels.pop(idx)
            self._channels_panel.refresh(self._document)
            if self._canvas.view_channel == f"alpha_{idx}":
                self._canvas.view_channel = "RGB"
                self._canvas_refresh()
            elif self._canvas.view_channel.startswith("alpha_"):
                cur_idx = int(self._canvas.view_channel.split("_")[1])
                if cur_idx > idx:
                    self._canvas.view_channel = f"alpha_{cur_idx - 1}"
