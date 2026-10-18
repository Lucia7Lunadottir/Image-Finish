from PyQt6.QtCore import Qt, QPoint

from core.app_logging import get_logger
from core.locale import tr

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
        self._push_history(tr("history.move_layer"))
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
        self._push_history(tr("history.align_layer"))
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
        # Through the option handler: every open document, the options bar
        # list and this session's defaults follow (it used to set only the
        # current canvas, and the options bar kept showing the old tip).
        self._on_opt_changed("brush_mask", mask)

    def _on_preset_save_requested(self, name: str):
        if self._canvas:
            opts = dict(self._canvas.tool_opts)
            self._tool_presets_panel.add_preset(name, self._active_tool_name, opts)

    def _on_preset_selected(self, tool_name: str, opts: dict):
        if self._canvas:
            self._canvas.tool_opts.update(opts)
            self._activate_tool(tool_name)
            self._opts_bar.update_tool_state(opts)

    # ── Paths panel (pen-tool work path + named saved paths) ────────────────

    def _selected_path_dict(self):
        """Resolves the Paths panel's current selection to its actual
        {"nodes": [...], "closed": bool} payload — either the live
        work_path or one entry of doc.saved_paths."""
        kind, idx = self._paths_panel._selected_kind()
        if kind == "work":
            return getattr(self._document, "work_path", None)
        if kind == "saved":
            paths = getattr(self._document, "saved_paths", [])
            if 0 <= idx < len(paths):
                return paths[idx]
        return None

    def _path_payload(self, wp):
        """`wp` as given (the canvas menu passes the work path), else the
        path selected in the Paths panel — None when it has no nodes."""
        if not self._document:
            return None
        if wp is None or isinstance(wp, bool):     # bool: a clicked() signal's arg
            wp = self._selected_path_dict()
        return wp if wp and wp.get("nodes") else None

    @staticmethod
    def _path_shape(wp):
        from tools.pen_tool import build_bezier_path
        path = build_bezier_path(wp)
        if wp.get("closed"):
            path.closeSubpath()
        return path

    def _path_make_selection(self, wp=None):
        wp = self._path_payload(wp)
        if wp is None:
            return
        self._push_history(tr("history.make_selection"))
        self._document.selection = self._path_shape(wp)
        self._canvas_refresh()

    def _path_fill(self, wp=None):
        self._paint_path(wp, "history.fill_path", fill=True)

    def _path_stroke(self, wp=None):
        self._paint_path(wp, "history.stroke_path", fill=False)

    def _paint_path(self, wp, history_key: str, fill: bool):
        """Fill or stroke a path with the foreground colour on the active
        layer (stroke width = the brush size)."""
        from PyQt6.QtGui import QPainter, QPen
        from ui.actions.pixel_target import pixel_layer_for_edit
        wp = self._path_payload(wp)
        if wp is None:
            return
        layer = pixel_layer_for_edit(self, "paint")
        if layer is None:
            return
        self._push_history(tr(history_key))
        p = QPainter(layer.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-layer.offset.x(), -layer.offset.y())
        if fill:
            p.setBrush(self._canvas.fg_color)
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setPen(QPen(self._canvas.fg_color, self._canvas.tool_opts.get("brush_size", 2)))
        p.drawPath(self._path_shape(wp))
        p.end()
        self._canvas_refresh()

    def _path_delete(self):
        if not self._document:
            return
        kind, idx = self._paths_panel._selected_kind()
        if kind is None:
            return
        self._push_history(tr("history.delete_path"))
        if kind == "work":
            self._document.work_path = {"nodes": [], "closed": False}
        elif kind == "saved":
            paths = getattr(self._document, "saved_paths", [])
            if 0 <= idx < len(paths):
                paths.pop(idx)
        self._paths_panel.refresh(self._canvas)
        self._canvas_refresh()

    def _path_new(self):
        """Promotes the current (ephemeral) work path into a permanent,
        named entry in doc.saved_paths, then clears work_path — matching
        Photoshop: the work path IS the new saved path, not a duplicate of it."""
        if not self._document:
            return
        wp = getattr(self._document, "work_path", None)
        if not wp or not wp.get("nodes"):
            return
        from core.history import clone_work_path
        self._push_history(tr("history.new_path"))
        saved = clone_work_path(wp)
        n = len(getattr(self._document, "saved_paths", [])) + 1
        saved["name"] = tr("paths.default_name", n=n) if tr("paths.default_name", n=n) != "paths.default_name" else f"Path {n}"
        self._document.saved_paths.append(saved)
        self._document.work_path = {"nodes": [], "closed": False}
        self._paths_panel.refresh(self._canvas)
        self._canvas_refresh()

    def _path_rename(self, index: int, new_name: str):
        if not self._document:
            return
        paths = getattr(self._document, "saved_paths", [])
        if 0 <= index < len(paths):
            paths[index]["name"] = new_name
        self._paths_panel.refresh(self._canvas)
