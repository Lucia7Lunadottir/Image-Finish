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
        p.setBrush(QBrush(grad))
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
        grad.setColorAt(0,          QColor(0, 0, 0, 255))
        grad.setColorAt(inner_stop, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0,        QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
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
        self._stamp_cache: tuple | None = None   # (size, hardness, mask, QImage)
        self._stroke_layer = None
        self._stroke_img: QImage | None = None
        self._stroke_opacity: float = 1.0
        self._stroke_clip = None  # QPainterPath | None

    def on_press(self, pos, doc, fg, bg, opts):
        self._last_pos = pos
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return
        self._stroke_layer = layer
        self._stroke_img = QImage(layer.image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._stroke_img.fill(Qt.GlobalColor.transparent)
        self._stroke_opacity = float(opts.get("brush_opacity", 1.0))
        sel = doc.selection
        self._stroke_clip = sel if (sel and not sel.isEmpty()) else None
        self._paint(pos, pos, doc, fg, opts)

    def on_move(self, pos, doc, fg, bg, opts):
        if self._last_pos:
            self._paint(self._last_pos, pos, doc, fg, opts)
        self._last_pos = pos

    def on_release(self, pos, doc, fg, bg, opts):
        # Apply stroke buffer once (opacity per stroke)
        if self._stroke_layer and self._stroke_img is not None and not self._stroke_layer.locked:
            painter = QPainter(self._stroke_layer.image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self._stroke_clip is not None:
                painter.setClipPath(self._stroke_clip)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
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

    # ── рисование штампами вдоль отрезка ────────────────────────────────────
    def _paint(self, p1: QPoint, p2: QPoint, doc, color: QColor, opts: dict):
        layer = self._stroke_layer
        if not layer or layer.locked or self._stroke_img is None:
            return

        size     = max(1, int(opts.get("brush_size", 10)))
        # Opacity is applied once on release; keep full-strength within the stroke.
        hardness = float(opts.get("brush_hardness", 1.0))
        mask     = opts.get("brush_mask", "round")

        # Для очень жёстких круглых кистей — быстрый QPen
        if mask == "round" and hardness >= 0.98:
            self._paint_fast(p1, p2, layer, color, size)
            return

        # Штамп-кисть: рисуем вдоль отрезка с шагом size/3
        stamp = self._get_stamp(size, hardness, mask)
        step  = max(1, size // 3)
        dx    = p2.x() - p1.x()
        dy    = p2.y() - p1.y()
        dist  = max(1, math.hypot(dx, dy))
        steps = max(1, int(dist / step))

        c = QColor(color)

        painter = QPainter(self._stroke_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._stroke_clip is not None:
            painter.setClipPath(self._stroke_clip)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        for i in range(steps + 1):
            t  = i / steps
            sx = p1.x() + dx * t - size / 2
            sy = p1.y() + dy * t - size / 2
            # Тонируем штамп в цвет кисти
            painter.save()
            painter.translate(sx, sy)
            # Применяем alpha-маску штампа
            colored = QImage(stamp.size(), QImage.Format.Format_ARGB32)
            colored.fill(c)
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
        pen = QPen(c, size, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.end()

    def _get_stamp(self, size, hardness, mask) -> QImage:
        """Кэш штампа — не пересчитываем если параметры не изменились."""
        key = (size, round(hardness, 2), mask)
        if self._stamp_cache and self._stamp_cache[:3] == key:
            return self._stamp_cache[3]
        img = _make_brush_stamp(size, hardness, mask)
        self._stamp_cache = (*key, img)
        return img
