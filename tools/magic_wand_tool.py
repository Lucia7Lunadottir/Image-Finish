import numpy as np
import ctypes
from PyQt6.QtCore import QPoint, Qt, QRect, QRectF
from PyQt6.QtGui import QImage, QBitmap, QRegion, QPainterPath, QColor
from tools.base_tool import BaseTool
from tools.lasso_tools import LassoMixin


def qimage_to_channels(img: QImage):
    """
    Безопасно извлекает R, G, B, A каналы из QImage в виде NumPy массивов,
    учитывая возможное выравнивание строк (bytesPerLine) и формат цвета.
    """
    h, w = img.height(), img.width()
    ptr = img.constBits()
    buf = (ctypes.c_uint8 * img.sizeInBytes()).from_address(int(ptr))
    bpl = img.bytesPerLine()
    
    # Создаем массив с учетом реального шага строки в памяти
    arr = np.ndarray((h, bpl // 4, 4), dtype=np.uint8, buffer=buf)[:, :w, :]
    
    fmt = img.format()
    # Обрабатываем порядок байтов в зависимости от формата Qt
    if fmt in (QImage.Format.Format_ARGB32, QImage.Format.Format_ARGB32_Premultiplied, QImage.Format.Format_RGB32):
        # В системе Little-Endian форматы ARGB/RGB32 хранятся как BGRA/BGRX
        b = arr[..., 0].astype(np.int32)
        g = arr[..., 1].astype(np.int32)
        r = arr[..., 2].astype(np.int32)
    else:
        # Для Format_RGBA8888 байты лежат прямо: RGBA
        r = arr[..., 0].astype(np.int32)
        g = arr[..., 1].astype(np.int32)
        b = arr[..., 2].astype(np.int32)
        
    a = arr[..., 3]
    return r, g, b, a


class MagicWandTool(BaseTool, LassoMixin):
    """Инструмент 'Волшебная палочка': выделяет смежные или глобальные области близких цветов"""
    name = "MagicWand"
    icon = "🪄"
    shortcut = "W"

    def __init__(self):
        super().__init__()

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            return

        # Работаем либо с маской слоя, либо с самим изображением
        img = layer.mask if (getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None) else layer.image
            
        w, h = img.width(), img.height()
        cx, cy = pos.x() - layer.offset.x(), pos.y() - layer.offset.y()

        if not (0 <= cx < w and 0 <= cy < h):
            return

        target_px = img.pixel(cx, cy)
        tr = (target_px >> 16) & 0xFF
        tg = (target_px >> 8) & 0xFF
        tb = target_px & 0xFF

        tolerance_pct = opts.get("fill_tolerance", 32)
        max_dist_sq = 255**2 * 3
        tolerance_sq = (tolerance_pct / 100.0)**2 * max_dist_sq
        contiguous = bool(opts.get("fill_contiguous", True))

        # Безопасно читаем каналы исходного изображения
        R, G, B, A = qimage_to_channels(img)

        # Считаем квадратичную дистанцию цветов
        dist_sq = (R - tr)**2 + (G - tg)**2 + (B - tb)**2
        color_mask = (dist_sq <= tolerance_sq) & (A > 0)

        if not color_mask[cy, cx]:
            return

        if contiguous:
            # Алгоритм Flood Fill (Смежные пиксели) через быстрый стек NumPy/Python
            visited = np.zeros((h, w), dtype=bool)
            stack = [(cy, cx)]
            visited[cy, cx] = True
            color_mask[cy, cx] = False

            while stack:
                y, x = stack.pop()
                # Проверка 4 соседних направлений
                if y > 0 and color_mask[y - 1, x]:
                    visited[y - 1, x] = True; color_mask[y - 1, x] = False; stack.append((y - 1, x))
                if y < h - 1 and color_mask[y + 1, x]:
                    visited[y + 1, x] = True; color_mask[y + 1, x] = False; stack.append((y + 1, x))
                if x > 0 and color_mask[y, x - 1]:
                    visited[y, x - 1] = True; color_mask[y, x - 1] = False; stack.append((y, x - 1))
                if x < w - 1 and color_mask[y, x + 1]:
                    visited[y, x + 1] = True; color_mask[y, x + 1] = False; stack.append((y, x + 1))
        else:
            # Глобальное выделение цвета по всему холсту
            visited = color_mask.copy()
            visited[cy, cx] = True

        # Создаем маску выделения
        mask_img = QImage(w, h, QImage.Format.Format_RGBA8888)
        mask_img.fill(0)
        
        m_ptr = mask_img.bits()
        m_buf = (ctypes.c_uint8 * mask_img.sizeInBytes()).from_address(int(m_ptr))
        m_bpl = mask_img.bytesPerLine()
        
        # ВАЖНО: оборачиваем с учетом выравнивания строк во избежание сдвигов памяти
        mask_arr = np.ndarray((h, m_bpl // 4, 4), dtype=np.uint8, buffer=m_buf)
        mask_arr[:, :w, 3][visited] = 255

        # Строим Битмап строго по Альфа-каналу
        bitmap = QBitmap.fromImage(mask_img.createAlphaMask())
        region = QRegion(bitmap)
        path = QPainterPath()
        path.addRegion(region)

        # Сливаем тысячи прямоугольников в один аккуратный векторный контур
        path = path.simplified()
        path.translate(layer.offset.x(), layer.offset.y())

        self._apply_path(doc, path, opts)

    def on_move(self, pos, doc, fg, bg, opts): pass
    def on_release(self, pos, doc, fg, bg, opts): pass
    def needs_history_push(self) -> bool: return True
    def cursor(self): return Qt.CursorShape.CrossCursor


class QuickSelectionTool(BaseTool, LassoMixin):
    """Инструмент 'Быстрое выделение': работает как кисть, расширяя область по схожести цветов"""
    name = "QuickSelection"
    icon = "🖌️✨"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._dragging = False
        self._mask = None
        self._target_img = None
        self._target_layer = None

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            return
        
        self._dragging = True
        self._target_layer = layer # ИСПРАВЛЕНО: Сохраняем ссылку на активный слой!
        
        if getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None:
            self._target_img = layer.mask
        else:
            self._target_img = layer.image

        w, h = self._target_img.width(), self._target_img.height()
        self._mask = np.zeros((h, w), dtype=bool)
        self._process_brush(pos, opts)

    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if self._dragging:
            self._process_brush(pos, opts)

    def on_release(self, pos: QPoint, doc, fg, bg, opts):
        if not self._dragging: 
            return
        self._dragging = False

        if self._mask is not None and np.any(self._mask) and self._target_layer:
            h, w = self._mask.shape
            mask_img = QImage(w, h, QImage.Format.Format_RGBA8888)
            mask_img.fill(0)
            
            m_ptr = mask_img.bits()
            m_buf = (ctypes.c_uint8 * mask_img.sizeInBytes()).from_address(int(m_ptr))
            m_bpl = mask_img.bytesPerLine()
            
            mask_arr = np.ndarray((h, m_bpl // 4, 4), dtype=np.uint8, buffer=m_buf)
            mask_arr[:, :w, 3][self._mask] = 255
            
            path = QPainterPath()
            path.addRegion(QRegion(QBitmap.fromImage(mask_img.createAlphaMask())))
            path.translate(self._target_layer.offset.x(), self._target_layer.offset.y())
            self._apply_path(doc, path.simplified(), opts)

        self._mask = None
        self._target_img = None
        self._target_layer = None

    def _process_brush(self, pos, opts):
        if self._target_img is None or self._mask is None or self._target_layer is None: 
            return

        cx, cy = pos.x() - self._target_layer.offset.x(), pos.y() - self._target_layer.offset.y()
        w, h = self._target_img.width(), self._target_img.height()
        if not (0 <= cx < w and 0 <= cy < h): 
            return

        target_px = self._target_img.pixel(cx, cy)
        tr, tg, tb = (target_px >> 16) & 0xFF, (target_px >> 8) & 0xFF, target_px & 0xFF

        brush_size = max(1, opts.get("brush_size", 20))
        radius = int(brush_size * 1.5)
        tolerance = opts.get("fill_tolerance", 32)
        tol_sq = (tolerance / 100.0 * 255)**2 * 3

        min_x, max_x = max(0, cx - radius), min(w, cx + radius + 1)
        min_y, max_y = max(0, cy - radius), min(h, cy + radius + 1)

        # Попиксельный разбор региона интереса (ROI) с правильным определением каналов
        R, G, B, A = qimage_to_channels(self._target_img)
        
        roi_R = R[min_y:max_y, min_x:max_x]
        roi_G = G[min_y:max_y, min_x:max_x]
        roi_B = B[min_y:max_y, min_x:max_x]
        roi_A = A[min_y:max_y, min_x:max_x]

        dist_sq = (roi_R - tr)**2 + (roi_G - tg)**2 + (roi_B - tb)**2
        local_mask = (dist_sq <= tol_sq) & (roi_A > 0)
        
        # Ограничиваем маску формой круглой кисти
        Y, X = np.ogrid[min_y - cy : max_y - cy, min_x - cx : max_x - cx]
        local_mask &= ((X**2 + Y**2) <= radius**2)

        self._mask[min_y:max_y, min_x:max_x] |= local_mask

    def stroke_preview(self):
        # Живой интерактивный предпросмотр выделения синим цветом
        if self._mask is not None and self._target_layer is not None:
            h, w = self._mask.shape
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            
            m_ptr = img.bits()
            m_buf = (ctypes.c_uint8 * img.sizeInBytes()).from_address(int(m_ptr))
            bpl = img.bytesPerLine()
            
            # В ARGB32 порядок байт в памяти на Little-Endian: BGRA
            img_arr = np.ndarray((h, bpl // 4, 4), dtype=np.uint8, buffer=m_buf)
            img_arr[:, :w][self._mask] = [250, 150, 50, 100] # Полупрозрачный лазурно-синий
            return (img, self._target_layer.offset, 1.0)
        return None

    def needs_history_push(self): return True
    def cursor(self): return Qt.CursorShape.CrossCursor


class ObjectSelectionTool(BaseTool, LassoMixin):
    """Инструмент 'Выделение объекта': автоматически находит контрастный объект внутри прямоугольной рамки"""
    name = "ObjectSelection"
    icon = "📦"
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

        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            self._start = None
            return

        target_img = layer.mask if (getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None) else layer.image

        doc_rect = QRect(self._start, self._end).normalized()
        w, h = target_img.width(), target_img.height()
        rect = doc_rect.translated(-layer.offset).intersected(QRect(0, 0, w, h))

        if rect.width() < 10 or rect.height() < 10:
            self._start = None
            return

        min_x, max_x, min_y, max_y = rect.left(), rect.right(), rect.top(), rect.bottom()
        
        # Читаем каналы
        R, G, B, A = qimage_to_channels(target_img)
        
        roi_R = R[min_y:max_y+1, min_x:max_x+1]
        roi_G = G[min_y:max_y+1, min_x:max_x+1]
        roi_B = B[min_y:max_y+1, min_x:max_x+1]
        roi_A = A[min_y:max_y+1, min_x:max_x+1]

        # Эвристика: берем медианный цвет центральной 40% зоны рамки
        roi_h, roi_w = roi_R.shape
        cw, ch = int(roi_w * 0.4), int(roi_h * 0.4)
        c_x1, c_y1 = (roi_w - cw) // 2, (roi_h - ch) // 2
        
        center_R = roi_R[c_y1:c_y1+ch, c_x1:c_x1+cw]
        center_G = roi_G[c_y1:c_y1+ch, c_x1:c_x1+cw]
        center_B = roi_B[c_y1:c_y1+ch, c_x1:c_x1+cw]
        
        if center_R.size > 0:
            avg_r = np.median(center_R)
            avg_g = np.median(center_G)
            avg_b = np.median(center_B)
        else:
            avg_r = roi_R[roi_h // 2, roi_w // 2]
            avg_g = roi_G[roi_h // 2, roi_w // 2]
            avg_b = roi_B[roi_h // 2, roi_w // 2]

        dist_sq = (roi_R - avg_r)**2 + (roi_G - avg_g)**2 + (roi_B - avg_b)**2

        # Интеллектуальный порог отсечения объекта от фона
        tolerance_sq = (50 / 100.0 * 255)**2 * 3
        local_mask = (dist_sq <= tolerance_sq) & (roi_A > 0)
        
        if np.any(local_mask):
            mask_img = QImage(w, h, QImage.Format.Format_RGBA8888)
            mask_img.fill(0)
            
            m_ptr = mask_img.bits()
            m_buf = (ctypes.c_uint8 * mask_img.sizeInBytes()).from_address(int(m_ptr))
            m_bpl = mask_img.bytesPerLine()
            
            mask_arr = np.ndarray((h, m_bpl // 4, 4), dtype=np.uint8, buffer=m_buf)
            mask_arr[min_y:max_y+1, min_x:max_x+1, 3][local_mask] = 255
            
            path = QPainterPath()
            path.addRegion(QRegion(QBitmap.fromImage(mask_img.createAlphaMask())))
            path.translate(layer.offset.x(), layer.offset.y())
            self._apply_path(doc, path.simplified(), opts)

        self._start = None

    def sub_drag_path(self):
        if self._dragging and self._start and self._end:
            p = QPainterPath()
            p.addRect(QRectF(QRect(self._start, self._end).normalized()))
            return p
        return None

    def needs_history_push(self): return True
    def cursor(self): return Qt.CursorShape.CrossCursor