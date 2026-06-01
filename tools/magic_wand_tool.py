import numpy as np
import traceback
from PyQt6.QtCore import QPoint, Qt, QRect, QRectF
from PyQt6.QtGui import QImage, QBitmap, QRegion, QPainterPath
from tools.base_tool import BaseTool, AbstractAsyncTool
from tools.lasso_tools import LassoMixin

class AbstractSelectionTool(AbstractAsyncTool, LassoMixin):
    """
    Промежуточный родительский класс для инструментов выделения.
    Содержит методы безопасного копирования памяти и векторизации масок.
    """
    def _get_safe_layer_snapshot(self, layer) -> tuple[QImage, np.ndarray] | None:
        """Создает изолированную копию пикселей слоя, исключая утечки и падения ядра C++."""
        try:
            img = layer.mask if (getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None) else layer.image
            if img.isNull():
                return None

            img_rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = img_rgba.width(), img_rgba.height()
            
            ptr = img_rgba.bits()
            ptr.setsize(img_rgba.sizeInBytes())
            
            # .copy() обязателен — он физически дублирует массив в изолированную память Python
            np_data = np.frombuffer(ptr, dtype=np.uint8).reshape((h, img_rgba.bytesPerLine() // 4, 4))[:, :w, :].copy()
            return img, np_data
        except Exception as e:
            print(f"Ошибка создания безопасного снимка памяти: {e}")
            return None

    def _convert_mask_to_path(self, mask: np.ndarray, layer_offset: QPoint) -> QPainterPath:
        """Переводит матрицу пикселей NumPy в оптимизированный векторный контур QPainterPath."""
        h, w = mask.shape
        mask_img = QImage(w, h, QImage.Format.Format_RGBA8888)
        mask_img.fill(0)

        m_ptr = mask_img.bits()
        m_ptr.setsize(mask_img.sizeInBytes())
        mask_arr = np.ndarray((h, mask_img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=m_ptr)
        mask_arr[:, :w, 3][mask] = 255

        bitmap = QBitmap.fromImage(mask_img.createAlphaMask())
        region = QRegion(bitmap)
        path = QPainterPath()
        path.addRegion(region)
        
        path = path.simplified()
        path.translate(layer_offset.x(), layer_offset.y())
        return path

    def cursor(self):
        return Qt.CursorShape.CrossCursor

    def needs_history_push(self) -> bool:
        return True


class MagicWandTool(AbstractSelectionTool):
    """Инструмент 'Волшебная палочка' — полностью асинхронный и отказоустойчивый."""
    name = "MagicWand"
    icon_name = "wand.svg"
    shortcut = "W"

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        try:
            layer = doc.get_active_layer()
            if not layer or layer.locked:
                return

            snapshot = self._get_safe_layer_snapshot(layer)
            if not snapshot:
                return
            img, np_data = snapshot

            w, h = img.width(), img.height()
            cx, cy = pos.x() - layer.offset.x(), pos.y() - layer.offset.y()

            if not (0 <= cx < w and 0 <= cy < h):
                return

            target_px = img.pixel(cx, cy)
            tr = (target_px >> 16) & 0xFF
            tg = (target_px >> 8) & 0xFF
            tb = target_px & 0xFF

            # Отправляем тяжелый расчет FloodFill в фоновый поток через execute_async
            self.execute_async(
                self._background_flood_fill,
                self._on_calculation_finished,
                doc,
                opts,
                np_data=np_data,
                start_pos=(cx, cy),
                target_color=(tr, tg, tb),
                tolerance_pct=opts.get("fill_tolerance", 32),
                contiguous=bool(opts.get("fill_contiguous", True)),
                layer_offset=layer.offset
            )
        except Exception:
            print(f"Предохранитель MagicWand: {traceback.format_exc()}")

    @staticmethod
    def _background_flood_fill(*args, **kwargs):
        """Этот метод выполняется строго в фоновом потоке ОС."""
        np_data = kwargs.get('np_data')
        cx, cy = kwargs.get('start_pos')
        tr, tg, tb = kwargs.get('target_color')
        tolerance_pct = kwargs.get('tolerance_pct')
        contiguous = kwargs.get('contiguous')

        h, w, _ = np_data.shape
        R = np_data[..., 0].astype(np.int32)
        G = np_data[..., 1].astype(np.int32)
        B = np_data[..., 2].astype(np.int32)
        A = np_data[..., 3]

        max_dist_sq = 255**2 * 3
        tolerance_sq = (tolerance_pct / 100.0)**2 * max_dist_sq
        
        dist_sq = (R - tr)**2 + (G - tg)**2 + (B - tb)**2
        color_mask = (dist_sq <= tolerance_sq) & (A > 0)

        if not color_mask[cy, cx]:
            return np.zeros((h, w), dtype=bool)

        if contiguous:
            visited = np.zeros((h, w), dtype=bool)
            stack = [(cy, cx)]
            visited[cy, cx] = True
            color_mask[cy, cx] = False

            while stack:
                y, x = stack.pop()
                if y > 0 and color_mask[y - 1, x]:
                    visited[y - 1, x] = True; color_mask[y - 1, x] = False; stack.append((y - 1, x))
                if y < h - 1 and color_mask[y + 1, x]:
                    visited[y + 1, x] = True; color_mask[y + 1, x] = False; stack.append((y + 1, x))
                if x > 0 and color_mask[y, x - 1]:
                    visited[y, x - 1] = True; color_mask[y, x - 1] = False; stack.append((y, x - 1))
                if x < w - 1 and color_mask[y, x + 1]:
                    visited[y, x + 1] = True; color_mask[y, x + 1] = False; stack.append((y, x + 1))
            return visited
        else:
            visited = color_mask.copy()
            visited[cy, cx] = True
            return visited

    def _on_calculation_finished(self, mask_result, doc, opts):
        """Этот метод вызывается автоматически в GUI-потоке, когда вычисления завершены."""
        layer = doc.get_active_layer()
        if not layer or mask_result is None or not np.any(mask_result):
            return
        path = self._convert_mask_to_path(mask_result, layer.offset)
        self._apply_path(doc, path, opts)

    def on_move(self, pos, doc, fg, bg, opts): pass
    def on_release(self, pos, doc, fg, bg, opts): pass


class QuickSelectionTool(AbstractSelectionTool):
    """Инструмент 'Быстрое выделение' (Интеллектуальная кисть)."""
    name = "QuickSelection"
    icon_name = "brush-selection.svg"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._dragging = False
        self._live_mask = None
        self._active_layer = None

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        try:
            layer = doc.get_active_layer()
            if not layer or layer.locked:
                return

            snapshot = self._get_safe_layer_snapshot(layer)
            if not snapshot:
                return
            _, np_data = snapshot

            self._dragging = True
            self._active_layer = layer
            self._live_mask = np.zeros((np_data.shape[0], np_data.shape[1]), dtype=bool)
            
            self._process_brush_step(pos, np_data, opts)
        except Exception:
            print(f"Сбой QuickSelection: {traceback.format_exc()}")
            self._dragging = False

    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if self._dragging and self._live_mask is not None and self._active_layer:
            snapshot = self._get_safe_layer_snapshot(self._active_layer)
            if snapshot:
                self._process_brush_step(pos, snapshot[1], opts)

    def on_release(self, pos: QPoint, doc, fg, bg, opts):
        if not self._dragging:
            return
        self._dragging = False

        try:
            if self._live_mask is not None and np.any(self._live_mask) and self._active_layer:
                path = self._convert_mask_to_path(self._live_mask, self._active_layer.offset)
                self._apply_path(doc, path, opts)
        except Exception:
            print(f"Сбой финализации QuickSelection: {traceback.format_exc()}")
        finally:
            self._live_mask = None
            self._active_layer = None

    def _process_brush_step(self, pos, np_data, opts):
        cx = pos.x() - self._active_layer.offset.x()
        cy = pos.y() - self._active_layer.offset.y()
        h, w, _ = np_data.shape

        if not (0 <= cx < w and 0 <= cy < h):
            return

        target_color = np_data[cy, cx, :3].astype(np.int32)
        brush_size = max(1, opts.get("brush_size", 20))
        radius = int(brush_size * 1.5)
        tolerance = opts.get("fill_tolerance", 32)
        tol_sq = (tolerance / 100.0 * 255)**2 * 3

        x1, x2 = max(0, cx - radius), min(w, cx + radius + 1)
        y1, y2 = max(0, cy - radius), min(h, cy + radius + 1)

        roi = np_data[y1:y2, x1:x2]
        dist_sq = (roi[..., 0] - target_color[0])**2 + (roi[..., 1] - target_color[1])**2 + (roi[..., 2] - target_color[2])**2
        
        local_mask = (dist_sq <= tol_sq) & (roi[..., 3] > 0)
        
        Y, X = np.ogrid[y1 - cy : y2 - cy, x1 - cx : x2 - cx]
        local_mask &= ((X**2 + Y**2) <= radius**2)

        self._live_mask[y1:y2, x1:x2] |= local_mask

    def stroke_preview(self):
        if self._dragging and self._live_mask is not None and self._active_layer:
            h, w = self._live_mask.shape
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            
            ptr = img.bits()
            ptr.setsize(img.sizeInBytes())
            img_arr = np.ndarray((h, img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr)
            img_arr[:, :w][self._live_mask] = [250, 150, 50, 120] 
            return img, self._active_layer.offset, 1.0
        return None


class ObjectSelectionTool(AbstractSelectionTool):
    """Инструмент 'Выделение объекта' в рамке."""
    name = "ObjectSelection"
    icon_name = "box-selection.svg"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._start = None
        self._end = None
        self._dragging = False

    def on_press(self, pos, doc, fg, bg, opts):
        self._start = pos
        self._end = pos
        self._dragging = True

    def on_move(self, pos, doc, fg, bg, opts):
        if self._dragging:
            self._end = pos

    def on_release(self, pos, doc, fg, bg, opts):
        if not self._dragging:
            return
        self._dragging = False
        self._end = pos

        try:
            layer = doc.get_active_layer()
            if not layer or layer.locked:
                return

            snapshot = self._get_safe_layer_snapshot(layer)
            if not snapshot:
                return
            img, np_data = snapshot

            doc_rect = QRect(self._start, self._end).normalized()
            rect = doc_rect.translated(-layer.offset).intersected(QRect(0, 0, img.width(), img.height()))

            if rect.width() < 8 or rect.height() < 8:
                return

            x1, x2, y1, y2 = rect.left(), rect.right(), rect.top(), rect.bottom()
            roi = np_data[y1:y2+1, x1:x2+1]

            rh, rw, _ = roi.shape
            cx1, cx2 = int(rw * 0.3), int(rw * 0.7)
            cy1, cy2 = int(rh * 0.3), int(rh * 0.7)
            center_zone = roi[cy1:cy2, cx1:cx2]

            if center_zone.size > 0:
                avg_color = np.median(center_zone[..., :3], axis=(0, 1))
            else:
                avg_color = roi[rh // 2, rw // 2, :3]

            dist_sq = (roi[..., 0] - avg_color[0])**2 + (roi[..., 1] - avg_color[1])**2 + (roi[..., 2] - avg_color[2])**2
            tolerance_sq = (45 / 100.0 * 255)**2 * 3
            
            local_mask = (dist_sq <= tolerance_sq) & (roi[..., 3] > 0)

            if np.any(local_mask):
                global_mask = np.zeros((img.height(), img.width()), dtype=bool)
                global_mask[y1:y2+1, x1:x2+1] = local_mask
                
                path = self._convert_mask_to_path(global_mask, layer.offset)
                self._apply_path(doc, path, opts)

        except Exception:
            print(f"Сбой ObjectSelection: {traceback.format_exc()}")
        finally:
            self._start = None
            self._end = None

    def sub_drag_path(self):
        if self._dragging and self._start and self._end:
            p = QPainterPath()
            p.addRect(QRectF(QRect(self._start, self._end).normalized()))
            return p
        return None