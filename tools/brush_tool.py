import math, random
from PyQt6.QtGui import (QPainter, QColor, QPen, QRadialGradient, QBrush,
                         QImage, QPixmap)
from PyQt6.QtCore import QPoint, QPointF, Qt, QRect
from tools.base_tool import BaseTool


def _make_brush_stamp(size: int, hardness: float, mask: str) -> QImage:
    """
    Возвращает QImage (size×size ARGB32) — «штамп» кисти.
    Alpha-канал определяет форму: 255 = полная краска, 0 = пусто.

    mask:
      round   — круглая с мягкостью по hardness
      square  — квадратная
      scatter — круглая с шумом по краям
    """
    s = max(2, size)
    img = QImage(s, s, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, r = s / 2, s / 2, s / 2 - 0.5

    if mask == "square":
        margin = int(s * (1 - hardness) * 0.3)
        inner = QRect(margin, margin, s - 2 * margin, s - 2 * margin)
        p.fillRect(img.rect(), Qt.GlobalColor.transparent)
        p.setBrush(QBrush(QColor(0, 0, 0, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(inner, margin * 0.5, margin * 0.5)

    elif mask == "scatter":
        # Основа — мягкий круг, по краю — случайные выбросы
        grad = QRadialGradient(cx, cy, r)
        inner_stop = max(0.0, min(1.0, hardness))
        grad.setColorAt(0,          QColor(0, 0, 0, 255))
        grad.setColorAt(inner_stop, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0,        QColor(0, 0, 0, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        # Добавляем случайные "брызги" снаружи
        p.setBrush(QBrush(QColor(0, 0, 0, 180)))
        rng = random.Random(size)   # детерминированный seed
        for _ in range(int(s * 0.4)):
            angle = rng.uniform(0, 2 * math.pi)
            dist  = rng.uniform(r * 0.6, r * 1.3)
            sx = cx + math.cos(angle) * dist
            sy = cy + math.sin(angle) * dist
            dr = rng.uniform(0.5, max(1, s * 0.04))
            p.drawEllipse(QPointF(sx, sy), dr, dr)

    else:  # round (default)
        grad = QRadialGradient(cx, cy, r)
        inner_stop = max(0.0, min(0.99, hardness))

        # Common start for all round brushes
        grad.setColorAt(0, QColor(0, 0, 0, 255))
        grad.setColorAt(inner_stop, QColor(0, 0, 0, 255))

        # Smoother, quadratic falloff for soft brushes feels more natural
        if inner_stop < 0.1:  # Apply to very soft brushes (hardness < 10%)
            # Approximation of y=(1-x)^2 curve from inner_stop to 1.0
            span = 1.0 - inner_stop
            if span > 0:
                # y = (1 - (x-is)/span)^2. We start from t=0.25
                for i in range(1, 5):
                    t = i / 4.0
                    x = inner_stop + t * span
                    y = (1.0 - t)**2
                    grad.setColorAt(x, QColor(0, 0, 0, int(255 * y)))
            else:  # this case is inner_stop >= 1, but for safety
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:  # Original linear falloff for harder brushes
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))

        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

    p.end()
    return img


class BrushTool(BaseTool):
    name     = "Brush"
    icon     = "🖌️"
    shortcut = "B"

    def __init__(self):
        self._last_pos: QPoint | None = None
        self._last_pressure: float = 1.0
        self._stamp_cache: dict = {}  # key: (size, hardness, mask), val: QImage
        self._stroke_layer = None
        self._stroke_img: QImage | None = None
        self._stroke_opacity: float = 1.0
        self._stroke_clip = None  # QPainterPath | None

    def on_press(self, pos, doc, fg, bg, opts):
        self._last_pos = pos
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return
        self._last_pressure = float(opts.get("_pressure", 1.0))
        self._stroke_layer = layer
        self._stroke_img = QImage(layer.image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._stroke_img.fill(Qt.GlobalColor.transparent)
        self._stroke_opacity = float(opts.get("brush_opacity", 1.0))
        sel = doc.selection
        self._stroke_clip = sel if (sel and not sel.isEmpty()) else None
        self._paint(pos, pos, doc, fg, opts, self._last_pressure, self._last_pressure)

    def on_move(self, pos, doc, fg, bg, opts):
        curr_pressure = float(opts.get("_pressure", 1.0))
        if self._last_pos:
            self._paint(self._last_pos, pos, doc, fg, opts, self._last_pressure, curr_pressure)
        self._last_pos = pos
        self._last_pressure = curr_pressure

    def on_release(self, pos, doc, fg, bg, opts):
        # Apply stroke buffer once (opacity per stroke)
        if self._stroke_layer and self._stroke_img is not None and not self._stroke_layer.locked:
            painter = QPainter(self._stroke_layer.image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self._stroke_clip is not None:
                painter.setClipPath(self._stroke_clip)
            painter.setCompositionMode(self.stroke_composition_mode())
            painter.setOpacity(max(0.0, min(1.0, float(self._stroke_opacity))))
            painter.drawImage(0, 0, self._stroke_img)
            painter.end()
        self._last_pos = None
        self._stroke_layer = None
        self._stroke_img = None
        self._stroke_clip = None
        self._stroke_opacity = 1.0

    def stroke_preview(self):
        """Return (QImage, top_left: QPoint, opacity: float) for live canvas overlay."""
        if self._stroke_img is None:
            return None
        return (self._stroke_img, QPoint(0, 0), float(self._stroke_opacity))

    def stroke_composition_mode(self):
        return QPainter.CompositionMode.CompositionMode_SourceOver

    def _get_stamp(self, size: int, hardness: float, mask) -> QImage:
        """
        Возвращает «штамп» кисти, используя кэш.
        """
        actual_mask = mask
        if isinstance(actual_mask, QPixmap):
            actual_mask = actual_mask.toImage()
        elif isinstance(actual_mask, str) and actual_mask not in ("round", "square", "scatter"):
            tmp = QImage(actual_mask)
            if not tmp.isNull():
                actual_mask = tmp

        cache_key = id(actual_mask) if isinstance(actual_mask, QImage) else actual_mask
        full_key = (size, hardness, cache_key)

        if full_key in self._stamp_cache:
            return self._stamp_cache[full_key]

        if isinstance(actual_mask, QImage) and not actual_mask.isNull():
            # Для кастомных кистей, маска — это QImage. Масштабируем его до размера кисти.
            # Игнорируем соотношение сторон, чтобы он соответствовал квадратной области штампа.
            stamp = actual_mask.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            # Если у кисти нет прозрачности (например, чёрно-белый исходник),
            # она нарисуется сплошным квадратом. Вытягиваем альфу из яркости!
            if not stamp.hasAlphaChannel():
                stamp = stamp.convertToFormat(QImage.Format.Format_ARGB32)
                import numpy as np
                ptr = stamp.bits()
                ptr.setsize(stamp.sizeInBytes())
                arr = np.ndarray((stamp.height(), stamp.width(), 4), dtype=np.uint8, buffer=ptr)
                
                # Считаем яркость. Тёмное = кисть, белое = фон.
                luma = (arr[..., 2]*0.299 + arr[..., 1]*0.587 + arr[..., 0]*0.114).astype(np.uint8)
                
                # Делаем альфа-канал из инвертированной яркости
                arr[..., 3] = 255 - luma
                # Основной цвет делаем чёрным (потом он окрасится в нужный цвет при рисовании)
                arr[..., 0:3] = 0
        else:
            # Для стандартных кистей ("round", "square") генерируем штамп.
            stamp = _make_brush_stamp(size, hardness, actual_mask)

        # Ограничиваем кэш, чтобы не забить память при динамическом размере
        if len(self._stamp_cache) > 50:
            self._stamp_cache.clear()
        self._stamp_cache[full_key] = stamp
        return stamp

    # ── рисование штампами вдоль отрезка ────────────────────────────────────
    def _paint(self, p1: QPoint, p2: QPoint, doc, color: QColor, opts: dict, press1: float = 1.0, press2: float = 1.0):
        layer = self._stroke_layer
        if not layer or layer.locked or self._stroke_img is None:
            return

        # Opacity is applied once on release; keep full-strength within the stroke.
        hardness = float(opts.get("brush_hardness", 1.0))
        mask     = opts.get("brush_mask", "round")
        angle    = float(opts.get("brush_angle", 0.0))
        angle_random = bool(opts.get("brush_angle_random", False))
        size_base = max(1, int(opts.get("brush_size", 10)))
        size_dyn = bool(opts.get("brush_size_dynamic", False))
        op_dyn   = bool(opts.get("brush_opacity_dynamic", False))

        # Для очень жёстких круглых кистей — быстрый QPen
        if mask == "round" and hardness >= 0.98 and not size_dyn and not op_dyn:
            self._paint_fast(p1, p2, layer, color, size_base)
            return

        # Штамп-кисть: рисуем вдоль отрезка с шагом size/3
        step  = max(1, size_base // 3)
        dx    = p2.x() - p1.x()
        dy    = p2.y() - p1.y()
        dist  = math.hypot(dx, dy)
        
        if dist == 0:
            steps = 0
            start_i = 0
        else:
            steps = max(1, int(dist / step))
            start_i = 1

        c = QColor(color)

        painter = QPainter(self._stroke_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._stroke_clip is not None:
            painter.setClipPath(self._stroke_clip)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)

        for i in range(start_i, steps + 1):
            t = 0 if steps == 0 else i / steps
            cur_press = press1 + (press2 - press1) * t
            
            cur_size = size_base
            if size_dyn:
                cur_size = max(1, int(size_base * cur_press))
                
            stamp = self._get_stamp(cur_size, hardness, mask)
            
            center_x = p1.x() + dx * t
            center_y = p1.y() + dy * t
            # Тонируем штамп в цвет кисти
            painter.save()
            painter.translate(center_x, center_y)
            current_angle = random.uniform(0, 360) if angle_random else angle
            if current_angle != 0.0:
                painter.rotate(current_angle)
            painter.translate(-cur_size / 2.0, -cur_size / 2.0)
            # Применяем alpha-маску штампа
            colored = QImage(stamp.size(), QImage.Format.Format_ARGB32)
            stamp_color = QColor(c)
            if op_dyn:
                stamp_color.setAlpha(int(255 * cur_press))
            colored.fill(stamp_color)
            
            cp = QPainter(colored)
            cp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn)
            cp.drawImage(0, 0, stamp)
            cp.end()
            painter.drawImage(0, 0, colored)
            painter.restore()

        painter.end()

    def _paint_fast(self, p1, p2, layer, color, size):
        """Быстрый путь: QPen без штампа."""
        c = QColor(color)
        painter = QPainter(self._stroke_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._stroke_clip is not None:
            painter.setClipPath(self._stroke_clip)
        
        pen = QPen(c, size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.end()


class EraserTool(BrushTool):
    name     = "Eraser"
    icon     = "🧽"
    shortcut = "E"

    def stroke_composition_mode(self):
        return QPainter.CompositionMode.CompositionMode_DestinationOut