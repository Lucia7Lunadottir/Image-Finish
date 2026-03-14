import math
import numpy as np
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, qRed, qGreen, qBlue, qAlpha
from tools.base_tool import BaseTool



class MagicEraserTool(BaseTool):
    name = "MagicEraser"
    icon = "🎇"
    shortcut = "E"

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            return

        img = layer.image
        w, h = img.width(), img.height()
        sx, sy = pos.x(), pos.y()

        if not (0 <= sx < w and 0 <= sy < h):
            return

        target_pixel = img.pixel(sx, sy)
        if qAlpha(target_pixel) == 0:
            return  # Кликнули по пустой области

        # Подготавливаем цвета для быстрого сравнения
        tr, tg, tb = qRed(target_pixel), qGreen(target_pixel), qBlue(target_pixel)

        # Толерантность от 0 до 100 превращаем в дистанцию RGB
        tolerance_pct = opts.get("fill_tolerance", 32)
        max_dist = (255**2 * 3) ** 0.5
        tolerance = (tolerance_pct / 100.0) * max_dist

        transparent = QColor(0, 0, 0, 0)

        # Быстрый поиск в глубину (DFS) на стеке
        stack = [(sx, sy)]
        visited = set(stack)

        while stack:
            x, y = stack.pop()
            img.setPixelColor(x, y, transparent)

            # Проверяем соседей (верх, низ, лево, право)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                    px = img.pixel(nx, ny)
                    if qAlpha(px) > 0:
                        dist = math.sqrt((qRed(px)-tr)**2 + (qGreen(px)-tg)**2 + (qBlue(px)-tb)**2)
                        if dist <= tolerance:
                            visited.add((nx, ny))
                            stack.append((nx, ny))

    def on_move(self, pos, doc, fg, bg, opts): pass
    def on_release(self, pos, doc, fg, bg, opts): pass
    def needs_history_push(self) -> bool: return True
    def cursor(self): return Qt.CursorShape.CrossCursor




class BackgroundEraserTool(BaseTool):
    name = "BackgroundEraser"
    icon = "✂️"
    shortcut = "E"

    def __init__(self):
        super().__init__()
        self.sample_color = None
        self.last_paint_pos = None

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            self.sample_color = None
            return

        img = layer.image
        cx, cy = pos.x(), pos.y()

        if 0 <= cx < img.width() and 0 <= cy < img.height():
            px = img.pixel(cx, cy)
            if (px >> 24) & 0xFF > 0:
                self.sample_color = px
            else:
                self.sample_color = None

        if self.sample_color is not None:
            self.last_paint_pos = pos
            self._erase_background(pos, doc, opts)

    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if self.sample_color is None or not self.last_paint_pos:
            return

        radius = max(1, opts.get("brush_size", 20) / 2)
        # Оставляем легкий спейсинг, чтобы не ловить микро-дрожание мыши
        spacing = max(1.0, radius * 0.15)

        dx = pos.x() - self.last_paint_pos.x()
        dy = pos.y() - self.last_paint_pos.y()
        dist = (dx**2 + dy**2)**0.5

        if dist < spacing:
            return

        # Интерполяция для резких рывков мыши
        steps = int(dist / spacing)
        if steps > 1:
            step_dx = dx / steps
            step_dy = dy / steps
            for i in range(1, steps):
                inter_pos = QPoint(int(self.last_paint_pos.x() + step_dx * i),
                                   int(self.last_paint_pos.y() + step_dy * i))
                self._erase_background(inter_pos, doc, opts)

        self._erase_background(pos, doc, opts)
        self.last_paint_pos = pos

    def on_release(self, pos, doc, fg, bg, opts):
        self.sample_color = None
        self.last_paint_pos = None

    def _erase_background(self, pos: QPoint, doc, opts):
        layer = doc.get_active_layer()
        img = layer.image
        w, h = img.width(), img.height()
        cx, cy = pos.x(), pos.y()

        radius = int(opts.get("brush_size", 20) / 2)
        tolerance_pct = opts.get("fill_tolerance", 20)

        # Вычисляем границы квадрата (ROI), в котором будем работать
        min_x, max_x = max(0, cx - radius), min(w, cx + radius + 1)
        min_y, max_y = max(0, cy - radius), min(h, cy + radius + 1)

        if min_x >= max_x or min_y >= max_y:
            return

        sc = self.sample_color
        sr = (sc >> 16) & 0xFF
        sg = (sc >> 8) & 0xFF
        sb = sc & 0xFF

        # --- NUMPY МАГИЯ НАЧИНАЕТСЯ ЗДЕСЬ ---
        # 1. Получаем указатель на сырую память QImage (без копирования!)
        # --- NUMPY МАГИЯ НАЧИНАЕТСЯ ЗДЕСЬ ---
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        bpl = img.bytesPerLine()

        # Учитываем выравнивание строк
        arr_full = np.ndarray((h, bpl // 4, 4), dtype=np.uint8, buffer=ptr)
        arr = arr_full[:, :w, :]

        roi = arr[min_y:max_y, min_x:max_x]

        # 4. Создаем математическую круглую маску кисти с помощью сеток
        Y, X = np.ogrid[min_y - cy : max_y - cy, min_x - cx : max_x - cx]
        circle_mask = (X**2 + Y**2) <= radius**2

        # 5. В памяти PyQt ARGB32 хранится задом наперед (little-endian): B, G, R, A
        roi_B = roi[..., 0].astype(np.int32)
        roi_G = roi[..., 1].astype(np.int32)
        roi_R = roi[..., 2].astype(np.int32)
        roi_A = roi[..., 3]

        # 6. Маска альфа-канала (игнорируем то, что уже стерто)
        alpha_mask = roi_A > 0

        # 7. Векторно считаем квадрат расстояния цветов для ВСЕХ пикселей махом
        color_dist_sq = (roi_R - sr)**2 + (roi_G - sg)**2 + (roi_B - sb)**2

        max_dist_sq = 255**2 * 3
        tolerance_sq = (tolerance_pct / 100.0)**2 * max_dist_sq

        color_mask = color_dist_sq <= tolerance_sq

        # 8. Пересекаем маски: в круге + непрозрачный + подходит по цвету
        final_mask = circle_mask & alpha_mask & color_mask

        # 9. Мгновенно зануляем все 4 канала (ARGB) у пикселей, прошедших проверку
        roi[final_mask] = 0

    def needs_history_push(self) -> bool: return True

