from PyQt6.QtGui import QImage, QColor
from PyQt6.QtCore import QPoint, QPointF
from tools.base_tool import BaseTool
from collections import deque


class FillTool(BaseTool):
    name = "Fill"
    icon = "🪣"
    shortcut = "G"

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
        w, h = image.width(), image.height()
        if not (0 <= x < w and 0 <= y < h):
            return

        # If there's a selection, the seed point must be inside it
        if selection is not None and not selection.contains(QPointF(x, y)):
            return

        target = image.pixel(x, y)
        fill_rgba = fill_color.rgba()

        if target == fill_rgba:
            return

        def colour_match(pixel) -> bool:
            dr = abs(((pixel >> 16) & 0xFF) - ((target >> 16) & 0xFF))
            dg = abs(((pixel >> 8)  & 0xFF) - ((target >> 8)  & 0xFF))
            db = abs((pixel         & 0xFF) - (target         & 0xFF))
            da = abs(((pixel >> 24) & 0xFF) - ((target >> 24) & 0xFF))
            return (dr + dg + db + da) <= tolerance * 4

        queue: deque[tuple[int, int]] = deque()
        queue.append((x, y))
        visited: set[tuple[int, int]] = {(x, y)}

        while queue:
            cx, cy = queue.popleft()
            if not colour_match(image.pixel(cx, cy)):
                continue
            image.setPixel(cx, cy, fill_rgba)
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                    if selection is None or selection.contains(QPointF(nx, ny)):
                        visited.add((nx, ny))
                        queue.append((nx, ny))
