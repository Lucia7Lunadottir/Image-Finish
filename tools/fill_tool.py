from PyQt6.QtGui import QImage, QColor
from PyQt6.QtCore import QPoint, QPointF
from tools.base_tool import BaseTool
from collections import deque


class FillTool(BaseTool):
    name = "Fill"
    icon = "🪣"
    shortcut = "K"

    def on_press(self, pos, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return
        tolerance = int(opts.get("fill_tolerance", 32))
        sel = doc.selection if (doc.selection and not doc.selection.isEmpty()) else None
        self._flood_fill(layer.image, pos.x(), pos.y(), fg, tolerance, sel)

    # ---------------------------------------------------------------- Algorithm
    @staticmethod
    def _flood_fill(image: QImage, x: int, y: int, fill_color: QColor,
                    tolerance: int, selection=None):
        import math
        w, h = image.width(), image.height()
        if not (0 <= x < w and 0 <= y < h):
            return

        target_rgba = image.pixel(x, y)
        fill_rgba = fill_color.rgba()
        if target_rgba == fill_rgba:
            return

        # Распаковка целевого цвета
        tr, tg, tb, ta = (target_rgba >> 16) & 0xFF, (target_rgba >> 8) & 0xFF, \
                         target_rgba & 0xFF, (target_rgba >> 24) & 0xFF

        queue = deque([(x, y)])
        visited = { (x, y) }
        to_fill = set()

        # 1. ОСНОВНОЙ ПРОХОД (Поиск области)
        while queue:
            cx, cy = queue.popleft()

            pixel = image.pixel(cx, cy)
            pr, pg, pb, pa = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, \
                             pixel & 0xFF, (pixel >> 24) & 0xFF

            # Считаем разницу (Евклид)
            dist = math.sqrt((pr-tr)**2 + (pg-tg)**2 + (pb-tb)**2 + (pa-ta)**2)

            if dist <= tolerance:
                to_fill.add((cx, cy))
                for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if selection is None or selection.contains(QPointF(nx, ny)):
                            visited.add((nx, ny))
                            queue.append((nx, ny))

        # 2. ФАЗА "ПОЖИРАНИЯ" ГРАНИЦ (Anti-Halo)
        # Мы берем каждый найденный пиксель и смотрим его соседей.
        # Если сосед еще не закрашен, мы проверяем его с ПОВЫШЕННЫМ допуском.
        final_to_fill = set(to_fill)
        border_tolerance = tolerance * 1.5 + 20 # Агрессивный порог для краев

        for cx, cy in to_fill:
            for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in final_to_fill:
                    pixel = image.pixel(nx, ny)
                    dist = math.sqrt((((pixel >> 16) & 0xFF)-tr)**2 +
                                     (((pixel >> 8) & 0xFF)-tg)**2 +
                                     ((pixel & 0xFF)-tb)**2)

                    if dist <= border_tolerance:
                        final_to_fill.add((nx, ny))

        # 3. ФИНАЛЬНАЯ ЗАЛИВКА
        for fx, fy in final_to_fill:
            image.setPixel(fx, fy, fill_rgba)
