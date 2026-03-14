import numpy as np
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage, QBitmap, QRegion, QPainterPath, QColor
from tools.base_tool import BaseTool
from tools.lasso_tools import LassoMixin


class MagicWandTool(BaseTool, LassoMixin):
    name = "MagicWand"
    icon = "🪄"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._tmp_mask = None  # Важно хранить ссылку на массив памяти, пока живет QImage

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        layer = doc.get_active_layer()
        if not layer or layer.locked or layer.image.isNull():
            return

        if getattr(layer, "editing_mask", False) and getattr(layer, "mask", None) is not None:
            img = layer.mask
        else:
            img = layer.image
            
        w, h = img.width(), img.height()
        cx, cy = pos.x(), pos.y()

        if not (0 <= cx < w and 0 <= cy < h):
            return

        target_px = img.pixel(cx, cy)
        if (target_px >> 24) & 0xFF == 0:
            return

        tr = (target_px >> 16) & 0xFF
        tg = (target_px >> 8) & 0xFF
        tb = target_px & 0xFF

        tolerance_pct = opts.get("fill_tolerance", 32)
        max_dist_sq = 255**2 * 3
        tolerance_sq = (tolerance_pct / 100.0)**2 * max_dist_sq
        contiguous = bool(opts.get("fill_contiguous", True))

        # 1. Читаем оригинальное изображение
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        bpl = img.bytesPerLine()
        arr = np.ndarray((h, w, 4), dtype=np.uint8, buffer=ptr, strides=(bpl, 4, 1))

        B = arr[..., 0].astype(np.int32)
        G = arr[..., 1].astype(np.int32)
        R = arr[..., 2].astype(np.int32)
        A = arr[..., 3]

        dist_sq = (R - tr)**2 + (G - tg)**2 + (B - tb)**2
        color_mask = (dist_sq <= tolerance_sq) & (A > 0)

        if not color_mask[cy, cx]:
            return

        if contiguous:
            # 2. Создаем чистую логическую маску для Flood Fill
            visited = np.zeros((h, w), dtype=bool)
            # 3. АЛГОРИТМ FLOOD FILL
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
        else:
            visited = color_mask.copy()
            visited[cy, cx] = True

        # 4. Собираем маску выделения через Альфа-канал
        # Создаем пустой прозрачный массив [0, 0, 0, 0]
        self._tmp_mask = np.zeros((h, w, 4), dtype=np.uint8)
        # Делаем выделенную область непрозрачной: Alpha = 255
        self._tmp_mask[visited, 3] = 255

        # Format_RGBA8888 идеален, так как 4 байта на пиксель всегда выровнены!
        mask_img = QImage(self._tmp_mask.data, w, h, w * 4, QImage.Format.Format_RGBA8888)

        # Строим Битмап строго по Альфа-каналу (никакой инверсии цветов!)
        bitmap = QBitmap.fromImage(mask_img.createAlphaMask())

        # 5. Превращаем в регион и ОБЯЗАТЕЛЬНО УПРОЩАЕМ ПУТЬ
        region = QRegion(bitmap)
        path = QPainterPath()
        path.addRegion(region)

        # ГЛАВНАЯ МАГИЯ: Сливаем тысячи прямоугольников в один гладкий контур
        path = path.simplified()

        self._apply_path(doc, path, opts)



    def on_move(self, pos, doc, fg, bg, opts): pass
    def on_release(self, pos, doc, fg, bg, opts): pass

    def needs_history_push(self) -> bool:
        return True

    def cursor(self):
        return Qt.CursorShape.CrossCursor
