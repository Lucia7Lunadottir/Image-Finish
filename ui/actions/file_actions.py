import os

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from core.document import Document
from core.image_formats import format_for_filter, format_for_path, open_filter, save_filter
from core.locale import tr
from ui.document_controller import require_document


_PSD_EXTENSIONS = (".psd", ".psb")


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
            self, tr("dlg.open_image"), "", open_filter(tr("dlg.filter.supported"), tr("dlg.filter.all_files")))
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
            self, tr("dlg.open_image_as_layer"), "",
            open_filter(tr("dlg.filter.supported"), tr("dlg.filter.all_files"), images_only=True))
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
                
        if path.lower().endswith(_PSD_EXTENSIONS):
            self._open_psd(path)
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

    def _open_psd(self, path: str):
        """Photoshop .psd/.psb through core.psd_import (no PSD library)."""
        from core.psd_import import PsdImporter, PsdFormatError
        importer = PsdImporter(path)
        try:
            doc = importer.load()
        except (PsdFormatError, OSError) as e:
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
        if importer.skipped_layers:
            self._status.showMessage(tr("status.psd_skipped_layers", count=importer.skipped_layers))

    @require_document
    def _save(self):
        path = getattr(self, "_filepath", None)
        if path and format_for_path(path) is not None:
            self._do_save(path)
        elif path:
            # Opened from a format we read but can't write (GIF, camera RAW,
            # SVG…): keep the layers in .imfn next to it.
            self._save_as(suggested_name=os.path.splitext(path)[0] + ".imfn")
        else:
            self._save_as()

    @require_document
    def _save_as(self, *, suggested_name: str = "untitled.png"):
        suggested_fmt = format_for_path(suggested_name)
        path, selected = QFileDialog.getSaveFileName(
            self, tr("dlg.save_as"), suggested_name, save_filter(),
            suggested_fmt.filter if suggested_fmt else "")
        if not path:
            return
        fmt = format_for_path(path)
        if fmt is None:
            # No (known) extension typed: the format picked in the dialog.
            fmt = format_for_filter(selected) or format_for_path("x.png")
            path = f"{path}.{fmt.default_extension}"
        if fmt.lossy:
            from ui.export_quality_dialog import ask_quality
            if ask_quality(fmt, self) is None:
                return
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
        from core.image_formats import write_flat_image
        from core.serialization import save_document, SerializationError
        fmt = format_for_path(path)
        note = None
        try:
            if fmt is None:
                raise SerializationError(tr("err.unsupported_format"))
            if fmt.writer == "imfn":
                save_document(self._document, path)
            elif fmt.writer == "psd" and not flatten:
                from core.psd_export import PsdExporter
                exporter = PsdExporter(self._document)
                exporter.save(path)
                if exporter.rasterized or exporter.skipped:
                    note = tr("status.psd_saved_notes", raster=exporter.rasterized, skipped=exporter.skipped)
            else:
                from ui.export_quality_dialog import remembered_quality
                write_flat_image(self._document.get_composite(respect_live_hidden=False), path, fmt,
                                 remembered_quality(fmt) if fmt.lossy else -1)
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
        self._status.showMessage(tr("status.saved", path=path) + (f"  |  {note}" if note else ""))
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

    @require_document
    def _export_slices(self):
        from core.serialization import save_image_atomic, SerializationError
        slices = getattr(self._document, "slices", [])
        if not slices:
            QMessageBox.information(self, "ImageFinish", tr("err.no_slices"))
            return
        dir_path = QFileDialog.getExistingDirectory(self, tr("dlg.export_slices"))
        if not dir_path: return
        comp = self._document.get_composite(respect_live_hidden=False)
        count = 0
        for i, r in enumerate(slices):
            c = r.intersected(comp.rect())
            if not c.isEmpty():
                try:
                    save_image_atomic(comp.copy(c), f"{dir_path}/slice_{i+1}.png")
                    count += 1
                except (SerializationError, OSError) as e:
                    QMessageBox.critical(self, tr("err.title.save_error"),
                                         tr("err.could_not_save", path=f"slice_{i+1}.png") + f"\n{e}")
                    return
        self._status.showMessage(tr("status.slices_exported", count=count))
