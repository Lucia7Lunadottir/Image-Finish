"""Layer masks, vector masks, clipping masks and Quick Mask (moved out of MainWindow)."""

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QPainterPath
from core.locale import tr
from ui.document_controller import require_document


class MaskActionsMixin:
    @require_document
    def _on_layer_mask_toggled(self, index: int):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "mask", None) is not None:
                layer.mask_enabled = not getattr(layer, "mask_enabled", True)
                self._push_history(tr("history.toggle_mask"))
                self._refresh_layers()
                self._canvas_refresh()

    @require_document
    def _add_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is None:
            from PyQt6.QtGui import QImage, QColor
            layer.mask = QImage(layer.width(), layer.height(), QImage.Format.Format_ARGB32_Premultiplied)
            layer.mask.fill(QColor(255, 255, 255))
            layer.editing_mask = True
            self._push_history(tr("history.add_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _delete_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            layer.mask = None
            layer.editing_mask = False
            self._push_history(tr("history.delete_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _apply_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            self._document.apply_layer_mask(layer)
            self._push_history(tr("history.apply_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _invert_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "mask", None) is not None:
            layer.mask.invertPixels()
            self._push_history(tr("history.invert_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _add_vector_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "vector_mask", None) is None:
            if self._document.selection and not self._document.selection.isEmpty():
                layer.vector_mask = QPainterPath(self._document.selection)
            else:
                path = QPainterPath()
                path.addRect(QRectF(0, 0, self._document.width, self._document.height))
                layer.vector_mask = path
            layer.vector_mask_enabled = True
            self._push_history(tr("history.add_vector_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _delete_vector_mask(self):
        layer = self._document.get_active_layer()
        if layer and getattr(layer, "vector_mask", None) is not None:
            layer.vector_mask = None
            self._push_history(tr("history.delete_vector_mask"))
            self._refresh_layers()
            self._canvas_refresh()

    @require_document
    def _on_layer_vmask_toggled(self, index: int):
        if 0 <= index < len(self._document.layers):
            layer = self._document.layers[index]
            if getattr(layer, "vector_mask", None) is not None:
                layer.vector_mask_enabled = not getattr(layer, "vector_mask_enabled", True)
                self._push_history(tr("history.toggle_vector_mask"))
                self._refresh_layers()
                self._canvas_refresh()

    def _toggle_clipping_mask(self):
        if self._document and self._document.get_active_layer():
            self._on_layer_clipping_toggled(self._document.active_layer_index)

    @require_document
    def _on_layer_clipping_toggled(self, index: int):
        if 0 < index < len(self._document.layers): # Cannot apply to the bottom layer
            layer = self._document.layers[index]
            self._push_history(tr("history.clipping_mask"))
            layer.clipping = not getattr(layer, "clipping", False)
            self._refresh_layers()
            self._canvas_refresh()

    def _toggle_quick_mask(self):
        if not self._document: return
        
        pre_state = self._make_history_state(tr("history.quick_mask"))
        
        if getattr(self._document, "quick_mask_layer", None) is not None:
            # Exit Quick Mask mode
            qm = self._document.quick_mask_layer.image
            from core.pixel_buffer import qimage_argb_view

            arr = qimage_argb_view(qm, writable=True)[:, :self._document.width, :]
            
            gray = 0.299*arr[..., 2] + 0.587*arr[..., 1] + 0.114*arr[..., 0]
            mask_val = (255 - gray) * (arr[..., 3] / 255.0)
            
            from core.pixel_buffer import mask_to_path
            self._document.selection = mask_to_path(mask_val < 128)
            self._document.quick_mask_layer = None
            
            if hasattr(self, "_qm_old_fg"):
                self._color_panel.set_fg(self._qm_old_fg)
                self._canvas.fg_color = self._qm_old_fg
                self._color_panel.set_bg(self._qm_old_bg)
                self._canvas.bg_color = self._qm_old_bg
        else:
            # Enter Quick Mask mode
            from core.layer import RasterLayer
            from PyQt6.QtGui import QPainter

            layer = RasterLayer("Quick Mask", self._document.width, self._document.height)
            layer.is_quick_mask = True
            
            sel = self._document.selection
            if sel and not sel.isEmpty():
                layer.image.fill(QColor(0, 0, 0))
                p = QPainter(layer.image)
                p.setClipPath(sel)
                p.fillRect(layer.image.rect(), QColor(255, 255, 255))
                p.end()
            else:
                layer.image.fill(QColor(255, 255, 255))
            
            self._document.quick_mask_layer = layer
            
            self._qm_old_fg = self._canvas.fg_color
            self._qm_old_bg = self._canvas.bg_color
            self._color_panel.set_fg(QColor(0, 0, 0))
            self._canvas.fg_color = QColor(0, 0, 0)
            self._color_panel.set_bg(QColor(255, 255, 255))
            self._canvas.bg_color = QColor(255, 255, 255)
            
        self._history.push(pre_state)
        self._canvas_refresh()
        self._refresh_layers()
