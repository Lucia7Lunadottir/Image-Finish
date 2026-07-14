from PyQt6.QtWidgets import QFileDialog, QMessageBox
from core.document import Document
from core.locale import tr
from ui.document_controller import require_document


class FileActionsMixin:
    def _new_doc(self):
        from utils.new_document_dialog import NewDocumentDialog
        dlg = NewDocumentDialog(self)
        if dlg.exec():
            doc = Document(dlg.get_width(), dlg.get_height(), dlg.get_bg_color())
            self._add_tab(doc, tr("title.untitled", mode="RGB/8"))
            self._push_history(tr("history.new_document"))

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg.open_image"), "", tr("dlg.open_filter"))
        if path:
            self._open_file_path(path)
            
    def _open_file_path(self, path: str):
        if path.lower().endswith(".imfn"):
            from core.serialization import load_document, SerializationError
            try:
                doc, was_legacy = load_document(path)
            except SerializationError as e:
                QMessageBox.critical(self, tr("err.title.error"),
                                     tr("err.could_not_open", path=path) + f"\n{e}")
                return
            except Exception:
                from core.app_logging import get_logger
                get_logger("file_actions").exception("Unexpected error loading %s", path)
                QMessageBox.critical(self, tr("err.title.error"),
                                     tr("err.could_not_open", path=path))
                return
            self._add_tab(doc, path.split("/")[-1], path)
            if was_legacy:
                self._status.showMessage(tr("status.legacy_format"))
            return
                
        if path.lower().endswith(".psd"):
            try:
                from psd_tools import PSDImage
                psd = PSDImage.open(path)
                doc = Document(psd.width, psd.height)
                doc.layers = []
                from core.layer import Layer
                from PyQt6.QtGui import QImage, QPainter
                from PyQt6.QtCore import QPoint
                for pl in psd:
                    if pl.is_group(): continue
                    pil_img = pl.topil()
                    if not pil_img: continue
                    if pil_img.mode != "RGBA": pil_img = pil_img.convert("RGBA")
                    data = pil_img.tobytes("raw", "RGBA")
                    qim = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888).copy()
                    qim = qim.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                    layer = Layer(pl.name, doc.width, doc.height)
                    p = QPainter(layer.image)
                    p.drawImage(QPoint(pl.left, pl.top), qim)
                    p.end()
                    layer.visible = pl.visible
                    layer.opacity = pl.opacity / 255.0
                    doc.layers.insert(0, layer)
                if not doc.layers: doc.add_layer("Background")
                doc.active_layer_index = len(doc.layers) - 1
                self._add_tab(doc, path.split("/")[-1], path)
                return
            except ImportError:
                QMessageBox.warning(self, tr("err.title.error"), "Please install 'psd-tools' (pip install psd-tools) to open PSD files.")
                return
            except Exception as e:
                QMessageBox.critical(self, tr("err.title.error"), f"Failed to open PSD: {e}")
                return

        from PyQt6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            QMessageBox.critical(self, tr("err.title.error"), tr("err.could_not_open", path=path))
            return
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        
        doc = Document(img.width(), img.height())
        doc.layers.clear()
        
        from core.layer import Layer
        layer = Layer("Background", img.width(), img.height())
        layer.image = img
        doc.layers.append(layer)
        
        doc.active_layer_index = 0
        self._add_tab(doc, path.split("/")[-1], path)

    @require_document
    def _save(self):
        if hasattr(self, "_filepath") and self._filepath:
            self._do_save(self._filepath)
        else:
            self._save_as()

    @require_document
    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.save_as"), "untitled.png", tr("dlg.save_filter"))
        if path:
            self._filepath = path
            self._do_save(path)

    @require_document
    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.export_png"), "export.png", "PNG (*.png)")
        if path:
            self._do_save(path, flatten=True)

    @require_document
    def _do_save(self, path: str, flatten: bool = False):
        from core.serialization import save_document, save_image_atomic, SerializationError
        try:
            if path.lower().endswith(".imfn"):
                save_document(self._document, path)
            else:
                save_image_atomic(self._document.get_composite(), path)
        except (SerializationError, OSError) as e:
            QMessageBox.critical(self, tr("err.title.save_error"),
                                 tr("err.could_not_save", path=path) + f"\n{e}")
            return
        except Exception:
            from core.app_logging import get_logger
            get_logger("file_actions").exception("Unexpected error saving %s", path)
            QMessageBox.critical(self, tr("err.title.save_error"),
                                 tr("err.could_not_save", path=path))
            return
        self._status.showMessage(tr("status.saved", path=path))
        c = self._canvas
        if c:
            c.is_modified = False
