from PyQt6.QtWidgets import QFileDialog, QMessageBox
from core.document import Document
from core.locale import tr


class FileActionsMixin:
    def _new_doc(self):
        from utils.new_document_dialog import NewDocumentDialog
        dlg = NewDocumentDialog(self)
        if dlg.exec():
            self._document = Document(dlg.get_width(), dlg.get_height(), dlg.get_bg_color())
            self._history.clear()
            self._canvas.set_document(self._document)
            self._refresh_layers()
            self._push_history(tr("history.new_document"))
            self._update_mode_menu()
            self._filepath = None

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg.open_image"), "", tr("dlg.open_filter"))
        if path:
            self._open_file_path(path)
            
    def _open_file_path(self, path: str):
        from PyQt6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            QMessageBox.critical(self, tr("err.title.error"), tr("err.could_not_open", path=path))
            return
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self._document = Document.__new__(Document)
        self._document.width  = img.width()
        self._document.height = img.height()
        self._document.selection = None
        from core.layer import Layer
        from PyQt6.QtCore import QPoint
        layer = Layer.__new__(Layer)
        layer.name = "Background"
        layer.visible = True
        layer.locked  = False
        layer.opacity = 1.0
        layer.blend_mode = "Normal"
        layer.text_data  = None
        layer.offset = QPoint(0, 0)
        layer.image  = img
        self._document.layers = [layer]
        self._document.active_layer_index = 0
        self._history.clear()
        self._canvas.set_document(self._document)
        self._filepath = path
        self._refresh_layers()
        self._update_mode_menu()

    def _save(self):
        if hasattr(self, "_filepath") and self._filepath:
            self._do_save(self._filepath)
        else:
            self._save_as()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.save_as"), "untitled.png", tr("dlg.save_filter"))
        if path:
            self._filepath = path
            self._do_save(path)

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.export_png"), "export.png", "PNG (*.png)")
        if path:
            self._do_save(path, flatten=True)

    def _do_save(self, path: str, flatten: bool = False):
        if flatten:
            img = self._document.get_composite()
        else:
            layer = self._document.get_active_layer()
            img = layer.image if layer else self._document.get_composite()
        ok = img.save(path)
        if ok:
            self._status.showMessage(tr("status.saved", path=path))
        else:
            QMessageBox.critical(self, tr("err.title.save_error"), tr("err.could_not_save", path=path))
