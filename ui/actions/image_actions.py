from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QImage
from core.locale import tr


class ImageActionsMixin:
    def _flip_h(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.flip_h"))
        layer.image = layer.image.mirrored(horizontal=True, vertical=False)
        self._canvas_refresh()

    def _flip_v(self):
        layer = self._document.get_active_layer()
        if not layer:
            return
        self._push_history(tr("history.flip_v"))
        layer.image = layer.image.mirrored(horizontal=False, vertical=True)
        self._canvas_refresh()

    def _resize_canvas(self):
        from utils.new_document_dialog import NewDocumentDialog
        dlg = NewDocumentDialog(self)
        dlg.setWindowTitle(tr("dlg.resize_canvas"))
        dlg._width_spin.setValue(self._document.width)
        dlg._height_spin.setValue(self._document.height)
        if dlg.exec():
            self._push_history(tr("history.resize_canvas"))
            new_w, new_h = dlg.get_width(), dlg.get_height()
            for layer in self._document.layers:
                new_img = QImage(new_w, new_h, QImage.Format.Format_ARGB32_Premultiplied)
                new_img.fill(Qt.GlobalColor.transparent)
                p = QPainter(new_img)
                p.drawImage(0, 0, layer.image)
                p.end()
                layer.image = new_img
            self._document.width  = new_w
            self._document.height = new_h
            self._canvas_refresh()
            self._canvas.reset_zoom()
            self._refresh_layers()

    def _apply_crop(self):
        from tools.other_tools import CropTool
        tool = self._tools.get("Crop")
        if isinstance(tool, CropTool) and tool.pending_rect:
            self._push_history(tr("history.crop"))
            self._document.apply_crop(tool.pending_rect)
            tool.pending_rect = None
            self._canvas_refresh()
            self._canvas.reset_zoom()
            self._refresh_layers()
