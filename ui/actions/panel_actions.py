from PyQt6.QtCore import Qt, QPoint

from core.app_logging import get_logger

logger = get_logger("panel_actions")


class PanelActionsMixin:
    """Callbacks wired to the dock panels (history, navigator, glyphs,
    properties, tool presets) and to the pen-tool work path."""

    def _history_jump(self, steps: int):
        """Called by HistoryPanel.jump_requested: positive=undo N, negative=redo N."""
        if not self._canvas:
            return
        if steps > 0:
            for _ in range(steps):
                self._undo()
        elif steps < 0:
            for _ in range(-steps):
                self._redo()

    def _on_nav_zoom(self, zoom_factor: float):
        if not self._canvas:
            return
        current = self._canvas.zoom
        if current > 0:
            self._canvas._apply_zoom(zoom_factor / current, self._canvas.rect().center())

    def _on_glyph_inserted(self, char: str):
        """Insert a glyph character — for now copies to clipboard."""
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(char)

    def _on_action_requested(self, action_name: str):
        if not self._canvas or not self._document:
            return
        self._push_history(f"Before {action_name}")
        from PyQt6.QtGui import QImage
        import numpy as np
        doc = self._document
        layer = doc.get_active_layer()

        if action_name == "Invert":
            from ui.adjustments_dialog import apply_invert
            if layer:
                layer.image = apply_invert(layer.image)

        elif action_name in ("Desaturate", "Grayscale Mode"):
            from ui.adjustments_dialog import apply_hue_saturation
            if layer:
                src = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
                layer.image = apply_hue_saturation(src, 0, -100, 0)

        elif action_name == "Sharpen":
            if layer:
                img = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
                try:
                    ptr = img.bits(); ptr.setsize(img.sizeInBytes())
                    arr = np.frombuffer(ptr, dtype=np.uint8).copy().reshape(img.height(), img.width(), 4)
                    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]], dtype=float)
                    from scipy.ndimage import convolve
                    for c in range(3):
                        arr[...,c] = np.clip(convolve(arr[...,c].astype(float), kernel), 0, 255).astype(np.uint8)
                    out = QImage(arr.tobytes(), img.width(), img.height(), QImage.Format.Format_ARGB32)
                    layer.image = out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                except Exception:
                    logger.exception("Action %s failed", action_name)

        elif action_name == "Flatten Image":
            self._flatten()
            return

        elif action_name == "Auto Levels":
            if layer:
                img = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
                try:
                    ptr = img.bits(); ptr.setsize(img.sizeInBytes())
                    arr = np.frombuffer(ptr, dtype=np.uint8).copy().reshape(img.height(), img.width(), 4)
                    for c in range(3):
                        ch = arr[...,c]
                        lo, hi = int(ch.min()), int(ch.max())
                        if hi > lo:
                            arr[...,c] = np.clip((ch.astype(float) - lo) * 255 / (hi - lo), 0, 255).astype(np.uint8)
                    out = QImage(arr.tobytes(), img.width(), img.height(), QImage.Format.Format_ARGB32)
                    layer.image = out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                except Exception:
                    logger.exception("Action %s failed", action_name)

        self._canvas_refresh()
        self._refresh_layers()

    def _on_transform_changed(self, x: int, y: int):
        if not self._canvas:
            return
        self._push_history("Move Layer")
        self._canvas_refresh()
        self._properties_panel.refresh(self._canvas)

    def _do_align_layer(self, direction: str):
        if not self._canvas or not self._document:
            return
        layer = self._document.get_active_layer()
        if not layer:
            return
        doc = self._document
        off = getattr(layer, "offset", QPoint(0, 0))
        lw = layer.image.width() if layer.image and not layer.image.isNull() else 0
        lh = layer.image.height() if layer.image and not layer.image.isNull() else 0
        self._push_history("Align Layer")
        if direction == "left":
            layer.offset = QPoint(0, off.y())
        elif direction == "center_h":
            layer.offset = QPoint((doc.width - lw) // 2, off.y())
        elif direction == "right":
            layer.offset = QPoint(doc.width - lw, off.y())
        elif direction == "top":
            layer.offset = QPoint(off.x(), 0)
        elif direction == "center_v":
            layer.offset = QPoint(off.x(), (doc.height - lh) // 2)
        elif direction == "bottom":
            layer.offset = QPoint(off.x(), doc.height - lh)
        self._canvas_refresh()
        self._properties_panel.refresh(self._canvas)

    def _on_brush_selected(self, mask: str):
        if self._canvas:
            self._canvas.tool_opts["brush_mask"] = mask
            self._opts_bar.update_tool_state({"brush_mask": mask})

    def _on_preset_save_requested(self, name: str):
        if self._canvas:
            opts = dict(self._canvas.tool_opts)
            self._tool_presets_panel.add_preset(name, self._active_tool_name, opts)

    def _on_preset_selected(self, tool_name: str, opts: dict):
        if self._canvas:
            self._canvas.tool_opts.update(opts)
            self._activate_tool(tool_name)
            self._opts_bar.update_tool_state(opts)

    # ── Pen tool work path ──────────────────────────────────────────────────

    def _path_make_selection(self):
        if not self._document:
            return
        wp = getattr(self._document, "work_path", None)
        if not wp or not wp.get("nodes"):
            return
        from PyQt6.QtGui import QPainterPath
        from PyQt6.QtCore import QPointF
        path = QPainterPath()
        nodes = wp["nodes"]
        if nodes:
            path.moveTo(QPointF(nodes[0]["p"]))
            for i in range(1, len(nodes)):
                path.cubicTo(QPointF(nodes[i-1]["c2"]), QPointF(nodes[i]["c1"]), QPointF(nodes[i]["p"]))
            if wp.get("closed") and len(nodes) > 1:
                path.cubicTo(QPointF(nodes[-1]["c2"]), QPointF(nodes[0]["c1"]), QPointF(nodes[0]["p"]))
                path.closeSubpath()
        self._push_history("Before Make Selection")
        self._document.selection = path
        self._canvas_refresh()

    def _path_fill(self):
        if not self._document:
            return
        self._push_history("Before Fill Path")
        layer = self._document.get_active_layer()
        if layer:
            from PyQt6.QtGui import QPainter, QColor
            p = QPainter(layer.image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setBrush(self._canvas.fg_color)
            p.setPen(Qt.PenStyle.NoPen)
            wp = getattr(self._document, "work_path", None)
            if wp and wp.get("nodes"):
                from PyQt6.QtGui import QPainterPath
                from PyQt6.QtCore import QPointF
                path = QPainterPath()
                nodes = wp["nodes"]
                path.moveTo(QPointF(nodes[0]["p"]))
                for i in range(1, len(nodes)):
                    path.cubicTo(QPointF(nodes[i-1]["c2"]), QPointF(nodes[i]["c1"]), QPointF(nodes[i]["p"]))
                if wp.get("closed"):
                    path.closeSubpath()
                p.drawPath(path)
            p.end()
        self._canvas_refresh()

    def _path_stroke(self):
        if not self._document:
            return
        self._push_history("Before Stroke Path")
        layer = self._document.get_active_layer()
        if layer:
            from PyQt6.QtGui import QPainter, QPen
            p = QPainter(layer.image)
            pen = QPen(self._canvas.fg_color, self._canvas.tool_opts.get("brush_size", 2))
            p.setPen(pen)
            wp = getattr(self._document, "work_path", None)
            if wp and wp.get("nodes"):
                from PyQt6.QtGui import QPainterPath
                from PyQt6.QtCore import QPointF
                path = QPainterPath()
                nodes = wp["nodes"]
                path.moveTo(QPointF(nodes[0]["p"]))
                for i in range(1, len(nodes)):
                    path.cubicTo(QPointF(nodes[i-1]["c2"]), QPointF(nodes[i]["c1"]), QPointF(nodes[i]["p"]))
                if wp.get("closed"):
                    path.closeSubpath()
                p.drawPath(path)
            p.end()
        self._canvas_refresh()

    def _path_delete(self):
        if self._document:
            self._push_history("Before Delete Path")
            self._document.work_path = {"nodes": [], "closed": False}
            self._paths_panel.refresh(self._canvas)
            self._canvas_refresh()
