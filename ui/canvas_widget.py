from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QBrush,
                         QPen, QImage, QCursor, QRadialGradient, QPainterPath)

from tools.other_tools import SelectTool, CropTool

# Инструменты с кистью — для них показываем кружок-курсор
_BRUSH_TOOLS = {"Brush", "Eraser", "Blur", "Sharpen", "Smudge"}


class CanvasWidget(QWidget):
    document_changed = pyqtSignal()
    pixels_changed   = pyqtSignal()
    color_picked     = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.document    = None
        self.active_tool = None

        self.fg_color = QColor(0, 0, 0)
        self.bg_color = QColor(255, 255, 255)
        self.tool_opts: dict = {
            "brush_size":     10,
            "brush_opacity":  1.0,
            "brush_hardness": 1.0,   # 0.0 = мягкая, 1.0 = жёсткая
            "brush_mask":     "round",  # round | square | scatter
            "fill_tolerance": 32,
            "font_size":        24,
            "font_family":      "Sans Serif",
            "font_bold":        False,
            "font_italic":      False,
            "font_underline":   False,
            "font_strikeout":   False,
            "text_color":       QColor(0, 0, 0),
            "text_stroke_w":    0,
            "text_stroke_color": QColor(0, 0, 0),
            "text_shadow":      False,
            "text_shadow_color": QColor(0, 0, 0, 160),
            "text_shadow_dx":   3,
            "text_shadow_dy":   3,
            "shape_type":     "rect",
            "effect_strength": 0.5,
        }

        self.zoom: float   = 1.0
        self._pan: QPointF = QPointF(0, 0)
        self._pan_last: QPointF | None = None
        self._panning: bool = False
        self._space:   bool = False

        self._stroke_in_progress: bool = False
        self._pre_stroke_state = None

        # Позиция мыши для курсора-кружка
        self._mouse_pos: QPointF = QPointF(-100, -100)
        self._show_brush_cursor: bool = False

        self._composite_cache: QImage | None = None
        self._cache_dirty: bool = True

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._checker = self._build_checker()

    # ──────────────────────────────────────── шахматка
    @staticmethod
    def _build_checker(tile: int = 16) -> QPixmap:
        pix = QPixmap(tile * 2, tile * 2)
        p = QPainter(pix)
        p.fillRect(0,    0,    tile, tile, QColor(180, 180, 180))
        p.fillRect(tile, 0,    tile, tile, QColor(220, 220, 220))
        p.fillRect(0,    tile, tile, tile, QColor(220, 220, 220))
        p.fillRect(tile, tile, tile, tile, QColor(180, 180, 180))
        p.end()
        return pix

    # ──────────────────────────────────────── публичное API
    def set_document(self, doc):
        self.document = doc
        self._cache_dirty = True
        self._pre_stroke_state = None
        self._fit_to_window()
        self.update()

    def invalidate_cache(self):
        self._cache_dirty = True
        self.update()

    def reset_zoom(self):
        self._fit_to_window()
        self.update()

    def zoom_in(self):
        self._apply_zoom(1.25, self.rect().center())

    def zoom_out(self):
        self._apply_zoom(1 / 1.25, self.rect().center())

    # ──────────────────────────────────────── координаты
    def to_doc(self, widget_pos: QPointF) -> QPoint:
        x = (widget_pos.x() - self._pan.x()) / self.zoom
        y = (widget_pos.y() - self._pan.y()) / self.zoom
        return QPoint(int(x), int(y))

    def _doc_rect_in_widget(self) -> QRect:
        if not self.document:
            return QRect()
        return QRect(
            int(self._pan.x()), int(self._pan.y()),
            int(self.document.width  * self.zoom),
            int(self.document.height * self.zoom),
        )

    # ──────────────────────────────────────── зум
    def _fit_to_window(self):
        if not self.document or self.width() == 0 or self.height() == 0:
            return
        margin = 40
        sx = (self.width()  - margin * 2) / self.document.width
        sy = (self.height() - margin * 2) / self.document.height
        self.zoom = min(sx, sy, 1.0)
        self._pan = QPointF(
            (self.width()  - self.document.width  * self.zoom) / 2,
            (self.height() - self.document.height * self.zoom) / 2,
        )

    def _apply_zoom(self, factor: float, pivot):
        if isinstance(pivot, QPoint):
            pivot = QPointF(pivot)
        new_zoom = max(0.02, min(32.0, self.zoom * factor))
        scale = new_zoom / self.zoom
        self._pan = QPointF(
            pivot.x() - (pivot.x() - self._pan.x()) * scale,
            pivot.y() - (pivot.y() - self._pan.y()) * scale,
        )
        self.zoom = new_zoom
        self.update()

    # ──────────────────────────────────────── отрисовка
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(30, 30, 40))

        if not self.document:
            return

        dr = self._doc_rect_in_widget()

        # 1. Шахматка
        painter.save()
        painter.setClipRect(dr)
        painter.translate(self._pan)
        painter.scale(self.zoom, self.zoom)
        painter.fillRect(0, 0, self.document.width, self.document.height,
                         QBrush(self._checker))
        painter.restore()

        # 2. Композит (кэш)
        if self._cache_dirty or self._composite_cache is None:
            self._composite_cache = self.document.get_composite()
            self._cache_dirty = False
        painter.save()
        painter.translate(self._pan)
        painter.scale(self.zoom, self.zoom)
        painter.drawImage(0, 0, self._composite_cache)
        painter.restore()

        # 3. Рамка документа
        painter.setPen(QPen(QColor(80, 80, 100), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(dr.adjusted(0, 0, -1, -1))

        # 4. Выделение
        sel = self.document.selection
        if sel and not sel.isEmpty():
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            # Заливка по форме
            painter.setClipPath(sel)
            painter.fillRect(sel.boundingRect().toRect(), QColor(100, 160, 255, 40))
            painter.setClipping(False)
            # Контур по реальной форме
            pw = max(1.0, 1.0 / self.zoom)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(0, 0, 0, 160), pw * 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(sel)
            pen2 = QPen(QColor(255, 255, 255, 220), pw)
            pen2.setStyle(Qt.PenStyle.DashLine)
            pen2.setDashOffset(4)
            painter.setPen(pen2)
            painter.drawPath(sel)
            painter.restore()

        # 4.5. Превью subtract-drag (Ctrl+drag): показываем что вычитается
        if isinstance(self.active_tool, SelectTool):
            sub_r = self.active_tool.sub_drag_rect()
            if sub_r:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                painter.fillRect(sub_r, QColor(255, 80, 80, 50))
                pw = max(1.0, 1.0 / self.zoom)
                pen = QPen(QColor(220, 60, 60), pw)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(sub_r)
                painter.restore()

        # 5. Floating preview (MoveTool с выделением)
        if self.active_tool and hasattr(self.active_tool, "floating_preview"):
            fp = self.active_tool.floating_preview()
            if fp:
                img, tl = fp
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                painter.drawImage(tl, img)
                painter.restore()

        # 6. Превью кропа
        if isinstance(self.active_tool, CropTool) and self.active_tool.pending_rect:
            cr = self.active_tool.pending_rect
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.fillRect(0, 0, self.document.width, self.document.height,
                             QColor(0, 0, 0, 100))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(cr, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / self.zoom)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cr)
            painter.restore()

        # 7. Курсор кисти — кружок в размер кисти
        if self._show_brush_cursor and not self._panning and not self._space:
            self._draw_brush_cursor(painter)

        painter.end()

    def _draw_brush_cursor(self, painter: QPainter):
        """Рисует кружок размером с кисть вместо системного курсора."""
        size   = int(self.tool_opts.get("brush_size", 10))
        mask   = self.tool_opts.get("brush_mask", "round")
        hard   = float(self.tool_opts.get("brush_hardness", 1.0))

        # Радиус в пикселях виджета
        r = max(1, int(size * self.zoom / 2))
        cx = int(self._mouse_pos.x())
        cy = int(self._mouse_pos.y())

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Мягкая кисть — показываем градиентный ореол
        if hard < 0.8:
            inner_r = int(r * hard)
            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0,   QColor(255, 255, 255, 80))
            grad.setColorAt(hard, QColor(255, 255, 255, 40))
            grad.setColorAt(1,   QColor(255, 255, 255, 0))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(cx, cy), r, r)

        # Контур кружка
        outer_pen = QPen(QColor(0, 0, 0, 160), 1.5)
        inner_pen = QPen(QColor(255, 255, 255, 200), 1)

        if mask == "square":
            rect = QRect(cx - r, cy - r, r * 2, r * 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(outer_pen)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.setPen(inner_pen)
            painter.drawRect(rect)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(outer_pen)
            painter.drawEllipse(QPoint(cx, cy), r + 1, r + 1)
            painter.setPen(inner_pen)
            painter.drawEllipse(QPoint(cx, cy), r, r)

        # Крестик в центре (только при большом размере)
        if r > 8:
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.drawLine(cx - 3, cy, cx + 3, cy)
            painter.drawLine(cx, cy - 3, cx, cy + 3)

        painter.restore()

    # ──────────────────────────────────────── мышь
    def mousePressEvent(self, ev):
        if not self.document:
            return

        is_pan = (ev.button() == Qt.MouseButton.MiddleButton or
                  (self._space and ev.button() == Qt.MouseButton.LeftButton))
        if is_pan:
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if ev.button() == Qt.MouseButton.LeftButton and self.active_tool:
            self._stroke_in_progress = True

            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)

            if self.active_tool.needs_history_push():
                from core.history import HistoryState
                self._pre_stroke_state = HistoryState(
                    description=self.active_tool.name,
                    layers_snapshot=self.document.snapshot_layers(),
                    active_layer_index=self.document.active_layer_index,
                )

            doc_pos = self.to_doc(ev.position())
            self.active_tool.on_press(doc_pos, self.document,
                                      self.fg_color, self.bg_color, self.tool_opts)
            self._cache_dirty = True
            self.update()

            # Инструменты, завершающие всё в on_press (TextTool):
            # сразу коммитим историю и обновляем панель слоёв
            if getattr(self.active_tool, "needs_immediate_commit", False):
                self._stroke_in_progress = False
                self.document_changed.emit()

    def mouseMoveEvent(self, ev):
        self._mouse_pos = ev.position()

        if self._panning and self._pan_last is not None:
            delta = ev.position() - self._pan_last
            self._pan += delta
            self._pan_last = ev.position()
            self.update()
            return

        # Перерисовываем курсор / overlay
        if self._show_brush_cursor:
            self.update()
        elif isinstance(self.active_tool, SelectTool):
            self.update()

        if (ev.buttons() & Qt.MouseButton.LeftButton
                and self._stroke_in_progress and self.active_tool):
            doc_pos = self.to_doc(ev.position())
            self.active_tool.on_move(doc_pos, self.document,
                                     self.fg_color, self.bg_color, self.tool_opts)
            self._cache_dirty = True
            self.update()
            self.pixels_changed.emit()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton or (
                self._panning and ev.button() == Qt.MouseButton.LeftButton):
            self._panning = False
            self._pan_last = None
            self._update_cursor()
            return

        if ev.button() == Qt.MouseButton.LeftButton and self._stroke_in_progress:
            doc_pos = self.to_doc(ev.position())
            if self.active_tool:
                self.active_tool.on_release(doc_pos, self.document,
                                            self.fg_color, self.bg_color, self.tool_opts)
            self._stroke_in_progress = False
            self._cache_dirty = True
            self.update()
            self.document_changed.emit()

    def enterEvent(self, ev):
        self._update_cursor()

    def leaveEvent(self, ev):
        self._show_brush_cursor = False
        self.update()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self._apply_zoom(factor, ev.position())
        else:
            super().wheelEvent(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif k == Qt.Key.Key_Plus or k == Qt.Key.Key_Equal:
            self.zoom_in()
        elif k == Qt.Key.Key_Minus:
            self.zoom_out()
        elif k == Qt.Key.Key_0:
            self.reset_zoom()
        # [ и ] — быстрое изменение размера кисти
        elif k == Qt.Key.Key_BracketLeft:
            new_size = max(1, self.tool_opts.get("brush_size", 10) - 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        elif k == Qt.Key.Key_BracketRight:
            new_size = min(500, self.tool_opts.get("brush_size", 10) + 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self._update_cursor()
        else:
            super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pan == QPointF(0, 0):
            self._fit_to_window()

    def _update_cursor(self):
        tool_name = getattr(self.active_tool, "name", "") if self.active_tool else ""
        if tool_name in _BRUSH_TOOLS:
            self._show_brush_cursor = True
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self._show_brush_cursor = False
            if self.active_tool:
                self.setCursor(QCursor(self.active_tool.cursor()))
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
