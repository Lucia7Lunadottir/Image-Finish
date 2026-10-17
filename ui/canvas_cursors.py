"""Canvas cursors: the selection-mode cursor and the brush-outline overlay.

Moved out of ui/canvas_widget.py. The brush overlay takes what it draws
from explicit arguments instead of reading the canvas's fields, uses
core.brush_symmetry for the mirrored outlines, and asks the tool class
about its quirks (PLAIN_BRUSH_CURSOR, ALT_PICKS_SOURCE) instead of
checking tool names.
"""
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect
from PyQt6.QtGui import (QBitmap, QColor, QCursor, QImage, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient, QRegion)

from core.app_logging import get_logger
from core.brush_symmetry import BrushSymmetry

logger = get_logger("canvas")


# ── selection cursor: crosshair + new/add/subtract/intersect badge ──────────

_sel_cursor_cache: dict = {}


def selection_cursor(mode: str) -> QCursor:
    """Crosshair with the selection mode badge: 'new' / 'add' / 'sub' / 'intersect'."""
    if mode in _sel_cursor_cache:
        return _sel_cursor_cache[mode]

    SIZE = 24
    HOT = SIZE // 2
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    mid = HOT
    gap = 4

    def _line(pen, x1, y1, x2, y2):
        p.setPen(pen)
        p.drawLine(x1, y1, x2, y2)

    white = QPen(Qt.GlobalColor.white, 2)
    black = QPen(Qt.GlobalColor.black, 1)

    for arm in [(mid, 0, mid, mid - gap),
                (mid, mid + gap, mid, SIZE - 1),
                (0, mid, mid - gap, mid),
                (mid + gap, mid, SIZE - 1, mid)]:
        _line(black, *arm)
        _line(white, *arm)

    bx, by = 15, 15
    bw = 7

    if mode == "add":
        cx, cy = bx + bw // 2, by + bw // 2
        for coords in [(cx, by, cx, by + bw), (bx, cy, bx + bw, cy)]:
            _line(black, *coords)
            _line(white, *coords)
    elif mode == "sub":
        cy = by + bw // 2
        _line(black, bx, cy, bx + bw, cy)
        _line(white, bx, cy, bx + bw, cy)
    elif mode == "intersect":
        for coords in [(bx, by, bx + bw, by + bw), (bx + bw, by, bx, by + bw)]:
            _line(black, *coords)
            _line(white, *coords)

    p.end()
    cur = QCursor(px, HOT, HOT)
    _sel_cursor_cache[mode] = cur
    return cur


def selection_mode(opts: dict) -> str:
    """Selection mode from the held modifiers (Ctrl add, Alt subtract, both intersect)."""
    ctrl = bool(opts.get("_ctrl", False))
    alt = bool(opts.get("_alt", False))
    if ctrl and alt:
        return "intersect"
    if ctrl:
        return "add"
    if alt:
        return "sub"
    return "new"


# ── brush outline ───────────────────────────────────────────────────────────

_REAL_PENS = (QPen(QColor(0, 0, 0, 160), 1.5), QPen(QColor(255, 255, 255, 200), 1))
# Mirrored outlines: reddish and more transparent
_MIRROR_PENS = (QPen(QColor(120, 0, 0, 70), 1.5), QPen(QColor(255, 120, 120, 110), 1))


class BrushCursorOverlay:
    """Draws the brush outline (and its mirror images) at the mouse.
    Keeps the traced outline of a custom brush tip between frames."""

    def __init__(self):
        self._tip_key = None
        self._tip_path = None

    def paint(self, painter: QPainter, *, tool, opts: dict, zoom: float, mouse: QPointF,
              to_doc, to_widget, doc_size):
        try:
            self._paint(painter, tool, opts, zoom, mouse, to_doc, to_widget, doc_size)
        except Exception:
            logger.debug("Brush cursor overlay failed", exc_info=True)

    def _centers(self, opts, mouse, to_doc, to_widget, doc_size):
        """(x, y, is_mirror) widget points: the cursor, then its mirrors."""
        sym = BrushSymmetry.from_opts(opts, *doc_size)
        doc_pos = to_doc(mouse)
        centers = [(int(mouse.x()), int(mouse.y()), False)]
        for x, y in sym.mirror_all([(doc_pos.x(), doc_pos.y())])[1:]:
            wp = to_widget(QPoint(int(x), int(y)))
            centers.append((int(wp.x()), int(wp.y()), True))
        return centers

    def _paint(self, painter, tool, opts, zoom, mouse, to_doc, to_widget, doc_size):
        size = int(opts.get("brush_size", 10))
        mask = opts.get("brush_mask", "round")
        hard = float(opts.get("brush_hardness", 1.0))
        angle = float(opts.get("brush_angle", 0.0))
        if getattr(tool, "PLAIN_BRUSH_CURSOR", False):
            mask, hard, angle = "round", 1.0, 0.0

        centers = self._centers(opts, mouse, to_doc, to_widget, doc_size)

        if getattr(tool, "ALT_PICKS_SOURCE", False) and opts.get("_alt", False):
            self._paint_source_crosshair(painter, centers)
            return

        tip = mask
        if isinstance(tip, QPixmap):
            tip = tip.toImage()
        elif isinstance(tip, str):
            if tip == "scatter":
                from tools.brush_tool import _make_brush_stamp
                tip = _make_brush_stamp(size, hard, "scatter")
            elif tip not in ("round", "square"):
                img = QImage(tip)
                if not img.isNull():
                    tip = img

        w_size = max(2, int(size * zoom))
        r = w_size / 2.0
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if isinstance(tip, QImage) and not tip.isNull():
            self._paint_custom_tip(painter, centers, self._tip_outline(mask, tip, w_size), angle)
        else:
            for cx, cy, is_mirror in centers:
                self._paint_round_or_square(painter, cx, cy, r, w_size, hard, tip == "square", angle, is_mirror)
        if w_size > 16:
            for cx, cy, is_mirror in centers:
                painter.setPen(QPen(QColor(255, 150, 150, 100) if is_mirror else QColor(255, 255, 255, 180), 1))
                painter.drawLine(cx - 3, cy, cx + 3, cy)
                painter.drawLine(cx, cy - 3, cx, cy + 3)
        painter.restore()

    @staticmethod
    def _paint_source_crosshair(painter, centers):
        """Clone Stamp with Alt held: where the source will be picked."""
        for cx, cy, is_mirror in centers:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if is_mirror:
                painter.setPen(QPen(QColor(100, 0, 0, 80), 3))
                painter.drawEllipse(QPointF(cx, cy), 8, 8)
                painter.setPen(QPen(QColor(255, 150, 150, 120), 1.5))
            else:
                painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
                painter.drawEllipse(QPointF(cx, cy), 8, 8)
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            painter.drawEllipse(QPointF(cx, cy), 8, 8)
            painter.drawLine(cx - 12, cy, cx + 12, cy)
            painter.drawLine(cx, cy - 12, cx, cy + 12)
            painter.restore()

    def _tip_outline(self, mask, tip: QImage, w_size: int) -> QPainterPath:
        key = (id(mask) if not isinstance(mask, str) else mask, w_size)
        if self._tip_key != key:
            scaled = tip.scaled(w_size, w_size, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            mask_img = scaled.createAlphaMask() if scaled.hasAlphaChannel() else scaled.createHeuristicMask()
            path = QPainterPath()
            path.addRegion(QRegion(QBitmap.fromImage(mask_img)))
            self._tip_key, self._tip_path = key, path.simplified()
        return self._tip_path

    @staticmethod
    def _rotate_about(painter, cx, cy, angle):
        if angle != 0.0:
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.translate(-cx, -cy)

    def _paint_custom_tip(self, painter, centers, path, angle):
        br = path.boundingRect()
        for cx, cy, is_mirror in centers:
            c_path = QPainterPath(path)
            c_path.translate(cx - br.center().x(), cy - br.center().y())
            outer, inner = _MIRROR_PENS if is_mirror else _REAL_PENS
            painter.save()
            self._rotate_about(painter, cx, cy, angle)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(outer)
            painter.drawPath(c_path)
            painter.setPen(inner)
            painter.drawPath(c_path)
            painter.restore()

    def _paint_round_or_square(self, painter, cx, cy, r, w_size, hard, square, angle, is_mirror):
        painter.save()
        self._rotate_about(painter, cx, cy, angle)
        if hard < 0.8 and not square:
            grad = QRadialGradient(cx, cy, r)
            if is_mirror:
                grad.setColorAt(0, QColor(255, 100, 100, 80))
                grad.setColorAt(hard, QColor(255, 50, 50, 40))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
            else:
                grad.setColorAt(0, QColor(255, 255, 255, 100))
                grad.setColorAt(hard, QColor(255, 255, 255, 80))
                grad.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(cx, cy), int(r), int(r))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer, inner = _MIRROR_PENS if is_mirror else _REAL_PENS
        if square:
            rect = QRect(int(cx - r), int(cy - r), w_size, w_size)
            painter.setPen(outer); painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.setPen(inner); painter.drawRect(rect)
        else:
            painter.setPen(outer); painter.drawEllipse(QPoint(cx, cy), int(r) + 1, int(r) + 1)
            painter.setPen(inner); painter.drawEllipse(QPoint(cx, cy), int(r), int(r))
        painter.restore()
