from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction
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

    @require_document
    def _open_file_as_layer(self):
        """Adds a raster image as a new layer on top of the CURRENT
        document, instead of _open_file_path's "always a brand-new
        document/tab" behavior — same idea as Photoshop's "Place Embedded",
        implemented the same way _paste() already adds clipboard content as
        a layer (centered on the canvas, no independent offset/transform)."""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg.open_image_as_layer"), "", tr("dlg.open_filter_images"))
        if not path:
            return

        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QImage, QPainter
        img = QImage(path)
        if img.isNull():
            QMessageBox.critical(self, tr("err.title.error"), tr("err.could_not_open", path=path))
            return
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        doc = self._document
        self._push_history(tr("history.open_as_layer"))

        from core.layer import RasterLayer
        name = path.split("/")[-1]
        new_layer = RasterLayer(name, doc.width, doc.height)
        cx = (doc.width  - img.width())  // 2
        cy = (doc.height - img.height()) // 2
        p = QPainter(new_layer.image)
        p.drawImage(QPoint(cx, cy), img)
        p.end()

        doc.layers.append(new_layer)
        doc.active_layer_index = len(doc.layers) - 1
        self._refresh_layers()
        self._canvas_refresh()

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
                from core.layer import RasterLayer
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
                    layer = RasterLayer(pl.name, doc.width, doc.height)
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
        
        from core.layer import RasterLayer
        layer = RasterLayer("Background", img.width(), img.height())
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
        if hasattr(self, "_commit_text_edit_if_active"):
            self._commit_text_edit_if_active()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.export_png"), "export.png", "PNG (*.png)")
        if path:
            self._do_save(path, flatten=True)

    @require_document
    def _do_save(self, path: str, flatten: bool = False):
        if hasattr(self, "_commit_text_edit_if_active"):
            self._commit_text_edit_if_active()
        from core.serialization import save_document, save_image_atomic, SerializationError
        try:
            if path.lower().endswith(".imfn"):
                save_document(self._document, path)
            else:
                save_image_atomic(self._document.get_composite(respect_live_hidden=False), path)
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

    # ── Recent files ──────────────────────────────────────────────────────

    def _load_recent_files(self):
        settings = QSettings("ImageFinish", "RecentFiles")
        self._recent_files = settings.value("recent", [])
        if not isinstance(self._recent_files, list):
            self._recent_files = []

    def _save_recent_files(self):
        settings = QSettings("ImageFinish", "RecentFiles")
        settings.setValue("recent", self._recent_files)

    def _add_recent_file(self, path):
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        if len(self._recent_files) > 30:
            self._recent_files = self._recent_files[:30]
        self._save_recent_files()
        self._update_recent_menu()
        if hasattr(self, "_welcome_panel"):
            self._welcome_panel.refresh_recent(self._recent_files)

    def _remove_recent_file(self, path):
        if path in self._recent_files:
            self._recent_files.remove(path)
            self._save_recent_files()
            self._update_recent_menu()

    def _update_recent_menu(self):
        if not hasattr(self, "_recent_menu"): return
        self._recent_menu.clear()
        if not self._recent_files:
            act = QAction(tr("menu.no_recent"), self)
            act.setEnabled(False)
            self._recent_menu.addAction(act)
        else:
            for path in self._recent_files:
                act = QAction(path, self)
                act.triggered.connect(lambda checked, p=path: self._open_recent(p))
                self._recent_menu.addAction(act)
            self._recent_menu.addSeparator()
            clear_act = QAction(tr("menu.clear_recent"), self)
            clear_act.triggered.connect(self._clear_recent)
            self._recent_menu.addAction(clear_act)

    def _clear_recent(self):
        self._recent_files.clear()
        self._save_recent_files()
        self._update_recent_menu()

    def _open_recent(self, path):
        import os
        if not os.path.exists(path):
            QMessageBox.warning(self, tr("err.title.error"), tr("err.could_not_open").format(path=path))
            self._remove_recent_file(path)
            return
        self._open_file_path(path)
