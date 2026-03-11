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

    def on_press(self, pos, doc, fg, bg, opts):
        self._last_pos = pos
        self._paint(pos, pos, doc, fg, opts)

    def on_move(self, pos, doc, fg, bg, opts):
        if self._last_pos:
            self._paint(self._last_pos, pos, doc, fg, opts)
        self._last_pos = pos

    def on_release(self, pos, doc, fg, bg, opts):
        self._last_pos = None

    # ── рисование штампами вдоль отрезка ────────────────────────────────────
    def _paint(self, p1: QPoint, p2: QPoint, doc, color: QColor, opts: dict):
        layer = doc.get_active_layer()
        if not layer or layer.locked:
            return

        size     = max(1, int(opts.get("brush_size", 10)))
        opacity  = float(opts.get("brush_opacity", 1.0))
        hardness = float(opts.get("brush_hardness", 1.0))
        mask     = opts.get("brush_mask", "round")

        # Для очень жёстких круглых кистей — быстрый QPen
        if mask == "round" and hardness >= 0.98:
            self._paint_fast(p1, p2, layer, doc, color, size, opacity)
            return

        # Штамп-кисть: рисуем вдоль отрезка с шагом size/3
        stamp = self._get_stamp(size, hardness, mask)
        step  = max(1, size // 3)
        dx    = p2.x() - p1.x()
        dy    = p2.y() - p1.y()
        dist  = max(1, math.hypot(dx, dy))
        steps = max(1, int(dist / step))

        c = QColor(color)
        c.setAlphaF(c.alphaF() * opacity)

        painter = QPainter(layer.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if doc.selection and not doc.selection.isEmpty():
            painter.setClipPath(doc.selection)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        for i in range(steps + 1):
            t  = i / steps
            sx = p1.x() + dx * t - size / 2
            sy = p1.y() + dy * t - size / 2
            # Тонируем штамп в цвет кисти
            painter.save()
            painter.translate(sx, sy)
            # Сначала рисуем цвет через маску
            painter.setOpacity(opacity)
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

    def _paint_fast(self, p1, p2, layer, doc, color, size, opacity):
        """Быстрый путь: QPen без штампа."""
        c = QColor(color)
        c.setAlphaF(c.alphaF() * opacity)
        painter = QPainter(layer.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if doc.selection and not doc.selection.isEmpty():
            painter.setClipPath(doc.selection)
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
