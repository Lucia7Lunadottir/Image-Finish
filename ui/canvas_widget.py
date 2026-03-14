import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QBrush, QPen, QImage, QCursor, QInputDevice,
                         QRadialGradient, QPainterPath, QPolygon, QPolygonF, QBitmap, QRegion)

from tools.other_tools import (SelectTool, CropTool, ShapesTool,
                               HandTool, ZoomTool, RotateViewTool, GradientTool, PerspectiveCropTool)

# Инструменты с кистью — для них показываем кружок-курсор
_BRUSH_TOOLS = {"Brush", "Eraser", "BackgroundEraser", "Blur", "Sharpen", "Smudge"}


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
            "brush_angle":    0.0,
            "brush_angle_random": False,
            "brush_mask":     "round",  # round | square | scatter
            "brush_blend_mode": "SourceOver",
            "fill_tolerance": 32,
            "fill_contiguous": True,
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
            "shape_fill":     False,
            "shape_sides":    6,
            "shape_angle":    0,
            "effect_strength": 0.5,
        }

        self.zoom: float   = 1.0
        self._pan: QPointF = QPointF(0, 0)
        self._pan_last: QPointF | None = None
        self._panning: bool = False
        self._space:   bool = False

        self._view_rotation: float = 0.0
        self._rotating:      bool  = False
        self._rotate_last_angle: float = 0.0

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

    def reset_rotation(self):
        self._view_rotation = 0.0
        self.update()

    def zoom_in(self):
        self._apply_zoom(1.25, self.rect().center())

    def zoom_out(self):
        self._apply_zoom(1 / 1.25, self.rect().center())

    # ──────────────────────────────────────── координаты
    def to_doc(self, widget_pos: QPointF) -> QPoint:
        if self._view_rotation:
            cx = self.width()  / 2
            cy = self.height() / 2
            dx = widget_pos.x() - cx
            dy = widget_pos.y() - cy
            a  = math.radians(-self._view_rotation)
            widget_pos = QPointF(
                dx * math.cos(a) - dy * math.sin(a) + cx,
                dx * math.sin(a) + dy * math.cos(a) + cy,
            )
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
        if self.zoom > 0.9:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        painter.fillRect(self.rect(), QColor(30, 30, 40))

        if not self.document:
            return

        if self._view_rotation:
            buf = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            buf.fill(QColor(0, 0, 0, 0))
            bp = QPainter(buf)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._paint_canvas_content(bp)
            bp.end()
            cx = self.width()  / 2
            cy = self.height() / 2
            painter.translate(cx, cy)
            painter.rotate(self._view_rotation)
            painter.translate(-cx, -cy)
            painter.drawImage(0, 0, buf)
            painter.resetTransform()
        else:
            self._paint_canvas_content(painter)

        # Курсор кисти — всегда в координатах виджета, без поворота
        if self._show_brush_cursor and not self._panning and not self._space:
            self._draw_brush_cursor(painter)

        painter.end()

    def _paint_canvas_content(self, painter: QPainter):
        """Renders checkerboard, composite, overlays (no brush cursor)."""
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
            painter.setClipPath(sel)
            painter.fillRect(sel.boundingRect().toRect(), QColor(100, 160, 255, 40))
            painter.setClipping(False)
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

        # 4.5. Превью subtract-drag
        if self.active_tool and hasattr(self.active_tool, "sub_drag_path"):
            sub_p = self.active_tool.sub_drag_path()
            if sub_p:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                painter.setClipPath(sub_p)
                painter.fillRect(sub_p.boundingRect().toRect(), QColor(255, 80, 80, 50))
                painter.setClipping(False)
                pw = max(1.0, 1.0 / self.zoom)
                pen = QPen(QColor(220, 60, 60), pw)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(sub_p)
                painter.restore()
        elif isinstance(self.active_tool, SelectTool):
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

    # 4.6. Превью Lasso Tools
        if self.active_tool and hasattr(self.active_tool, "lasso_preview"):
            preview_data = self.active_tool.lasso_preview()
            if preview_data:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)

                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                pw = max(1.0, 1.0 / self.zoom)

                # Черно-белая пунктирная линия для лучшей видимости
                pen1 = QPen(QColor(0, 0, 0), pw)
                pen2 = QPen(QColor(255, 255, 255), pw)
                pen2.setStyle(Qt.PenStyle.DashLine)

                # Распаковка данных в зависимости от инструмента
                points = preview_data[0] if isinstance(preview_data, tuple) else preview_data
                current_pos = preview_data[1] if isinstance(preview_data, tuple) else None

                if len(points) > 0:
                    poly = QPolygonF(points)
                    painter.setPen(pen1)
                    painter.drawPolyline(poly)
                    painter.setPen(pen2)
                    painter.drawPolyline(poly)

                    # Для полигонального рисуем линию тянущуюся за курсором
                    if current_pos:
                        painter.setPen(pen1)
                        painter.drawLine(points[-1], current_pos)
                        painter.setPen(pen2)
                        painter.drawLine(points[-1], current_pos)

                painter.restore()


        # 5. Floating preview (MoveTool)
        if self.active_tool and hasattr(self.active_tool, "floating_preview"):
            fp = self.active_tool.floating_preview()
            if fp:
                img, tl = fp
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                painter.drawImage(tl, img)
                painter.restore()

        # 5.2 Live stroke preview (BrushTool-style)
        if self.active_tool and hasattr(self.active_tool, "stroke_preview"):
            sp = self.active_tool.stroke_preview()
            if sp:
                img, tl, op = sp
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                
                if hasattr(self.active_tool, "stroke_composition_mode"):
                    painter.setCompositionMode(self.active_tool.stroke_composition_mode(self.tool_opts))
                
                painter.setOpacity(max(0.0, min(1.0, float(op))))
                painter.drawImage(tl, img)
                painter.restore()

        # 6. Превью кропа
        if isinstance(self.active_tool, CropTool) and self.active_tool.pending_rect:
            cr = self.active_tool.pending_rect
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            
            path = QPainterPath()
            path.addRect(QRectF(0, 0, self.document.width, self.document.height))
            path.addRect(QRectF(cr))
            path.setFillRule(Qt.FillRule.OddEvenFill)
            painter.fillPath(path, QColor(0, 0, 0, 100))
            
            painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / self.zoom)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cr)
            painter.restore()

        # 6.1. Превью перспективного кропа
        if isinstance(self.active_tool, PerspectiveCropTool):
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)

            # Если собраны все 4 точки - рисуем затемнение фона и основную желтую рамку
            if self.active_tool.pending_quad:
                quad = self.active_tool.pending_quad
                path = QPainterPath()
                path.addRect(QRectF(0, 0, self.document.width, self.document.height))
                path.addPolygon(QPolygonF([QPointF(p) for p in quad]))
                path.setFillRule(Qt.FillRule.OddEvenFill)
                painter.fillPath(path, QColor(0, 0, 0, 100))

                painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / self.zoom)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(quad)

            # Отрисовка узлов и направляющих линий (показываем всегда, пока есть точки)
            if self.active_tool.points:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                pen = QPen(QColor(255, 255, 255), max(1.0, 1.5 / self.zoom))
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QColor(255, 255, 255, 180))

                pts = self.active_tool.points
                # Радиус точек тоже должен зависеть от зума, иначе при отдалении их не увидеть
                r = max(4.0, 6.0 / self.zoom)
                for i, p in enumerate(pts):
                    painter.drawEllipse(QPointF(p), r, r)
                    # Рисуем линии соединения, пока фигура не замкнута
                    if i > 0 and not self.active_tool.pending_quad:
                        painter.drawLine(pts[i-1], pts[i])

            painter.restore()

        # 6.5. Превью фигуры (ShapesTool)
        if isinstance(self.active_tool, ShapesTool):
            ps = self.active_tool.preview_shape()
            if ps:
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                stroke = max(1, int(self.tool_opts.get("brush_size", 3)))
                pen = QPen(self.fg_color, stroke)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                shape = ps["shape"]
                rect  = ps["rect"]
                angle = ps.get("angle", 0)
                if angle and shape != "line":
                    cx, cy = rect.center().x(), rect.center().y()
                    painter.translate(cx, cy)
                    painter.rotate(angle)
                    painter.translate(-cx, -cy)
                if shape == "ellipse":
                    painter.drawEllipse(rect)
                elif shape == "triangle":
                    painter.drawPolygon(QPolygon([
                        QPoint(rect.center().x(), rect.top()),
                        QPoint(rect.left(),  rect.bottom()),
                        QPoint(rect.right(), rect.bottom()),
                    ]))
                elif shape == "polygon":
                    painter.drawPolygon(
                        ShapesTool._polygon_points(rect, ps["sides"]))
                elif shape == "line":
                    painter.drawLine(ps["start"], ps["end"])
                elif shape == "star":
                    painter.drawPolygon(ShapesTool._star_points(rect))
                elif shape == "arrow":
                    painter.drawPath(ShapesTool._arrow_path(rect))
                elif shape == "cross":
                    painter.drawPath(ShapesTool._cross_path(rect))
                else:
                    painter.drawRect(rect)
                painter.restore()

        # 6.6. Превью градиента (GradientTool) — линия от start до end
        if isinstance(self.active_tool, GradientTool):
            pg = self.active_tool.preview_gradient()
            if pg:
                p0, p1 = pg
                painter.save()
                painter.translate(self._pan)
                painter.scale(self.zoom, self.zoom)
                pw = max(1.0, 1.0 / self.zoom)
                pen = QPen(QColor(255, 255, 255, 200), pw * 1.5)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(p0, p1)
                # Маркеры на концах
                painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
                painter.setPen(QPen(QColor(0, 0, 0, 160), pw))
                r = pw * 3
                painter.drawEllipse(QPointF(p0), r, r)
                painter.drawEllipse(QPointF(p1), r, r)
                painter.restore()

    def _draw_brush_cursor(self, painter: QPainter):
        """Рисует кружок размером с кисть вместо системного курсора."""
        size   = int(self.tool_opts.get("brush_size", 10))
        mask   = self.tool_opts.get("brush_mask", "round")
        hard   = float(self.tool_opts.get("brush_hardness", 1.0))
        angle  = float(self.tool_opts.get("brush_angle", 0.0))

        if getattr(self.active_tool, "name", "") == "BackgroundEraser":
            mask = "round"
            hard = 1.0
            angle = 0.0

        # Нормализация маски: QPixmap или путь к файлу -> QImage
        actual_mask = mask
        if isinstance(actual_mask, QPixmap):
            actual_mask = actual_mask.toImage()
        elif isinstance(actual_mask, str):
            if actual_mask == "scatter":
                from tools.brush_tool import _make_brush_stamp
                # Генерируем реальный штамп разброса, чтобы он стал маской контура
                actual_mask = _make_brush_stamp(size, hard, "scatter")
            elif actual_mask not in ("round", "square"):
                tmp = QImage(actual_mask)
                if not tmp.isNull():
                    actual_mask = tmp

        # Размер курсора в пикселях виджета
        w_size = max(2, int(size * self.zoom))
        r = w_size / 2.0
        cx = int(self._mouse_pos.x())
        cy = int(self._mouse_pos.y())

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Применяем поворот ко всему курсору кисти
        if angle != 0.0:
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.translate(-cx, -cy)

        # Контур (черный и белый для контраста)
        outer_pen = QPen(QColor(0, 0, 0, 160), 1.5)
        inner_pen = QPen(QColor(255, 255, 255, 200), 1)

        # --- Курсор для кастомной кисти ---
        if isinstance(actual_mask, QImage) and not actual_mask.isNull():
            # 1. Масштабируем маску кисти до размера курсора
            scaled_img = actual_mask.scaled(w_size, w_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            # 2. Превращаем форму в контур. Если картинка без прозрачности, используем эвристику.
            if not scaled_img.hasAlphaChannel():
                mask_img = scaled_img.createHeuristicMask()
            else:
                mask_img = scaled_img.createAlphaMask()
                
            bitmap = QBitmap.fromImage(mask_img)
            region = QRegion(bitmap)
            path = QPainterPath()
            path.addRegion(region)
            path = path.simplified()  # Сливаем мелкие части в один контур

            # 3. Центрируем и рисуем контур
            br = path.boundingRect()
            path.translate(cx - br.center().x(), cy - br.center().y())

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(outer_pen)
            painter.drawPath(path)
            painter.setPen(inner_pen)
            painter.drawPath(path)

        # --- Стандартные курсоры (круг/квадрат) ---
        else:
            # Мягкая кисть — показываем градиентный ореол
            if hard < 0.8 and actual_mask != "square":
                grad = QRadialGradient(cx, cy, r)
                grad.setColorAt(0,   QColor(255, 255, 255, 80))
                grad.setColorAt(hard, QColor(255, 255, 255, 40))
                grad.setColorAt(1,   QColor(255, 255, 255, 0))
                painter.setBrush(grad)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(cx, cy), int(r), int(r))

            # Рисуем контур
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if actual_mask == "square":
                rect = QRect(int(cx - r), int(cy - r), w_size, w_size)
                painter.setPen(outer_pen)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
                painter.setPen(inner_pen)
                painter.drawRect(rect)
            else:  # round
                painter.setPen(outer_pen)
                painter.drawEllipse(QPoint(cx, cy), int(r) + 1, int(r) + 1)
                painter.setPen(inner_pen)
                painter.drawEllipse(QPoint(cx, cy), int(r), int(r))

        # Крестик в центре (только при большом размере)
        if w_size > 16:
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.drawLine(cx - 3, cy, cx + 3, cy)
            painter.drawLine(cx, cy - 3, cx, cy + 3)

        painter.restore()

    # ──────────────────────────────────────── мышь
    def tabletEvent(self, ev):
        self.tool_opts["_pressure"] = ev.pressure()
        ev.ignore()

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

        if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
            self.tool_opts["_pressure"] = 1.0

        if ev.button() == Qt.MouseButton.LeftButton:
            if isinstance(self.active_tool, HandTool):
                self._panning = True
                self._pan_last = ev.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

            if isinstance(self.active_tool, ZoomTool):
                alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
                self._apply_zoom(1 / 1.25 if alt else 1.25, ev.position())
                return

            if isinstance(self.active_tool, RotateViewTool):
                self._rotating = True
                cx = self.width()  / 2
                cy = self.height() / 2
                self._rotate_last_angle = math.degrees(
                    math.atan2(ev.position().y() - cy, ev.position().x() - cx))
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

        if ev.button() == Qt.MouseButton.LeftButton and self.active_tool:
            self._stroke_in_progress = True

            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
            self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)

            if self.active_tool.needs_history_push():
                from core.history import HistoryState
                self._pre_stroke_state = HistoryState(
                    description=self.active_tool.name,
                    layers_snapshot=self.document.snapshot_layers(),
                    active_layer_index=self.document.active_layer_index,
                    doc_width=self.document.width,
                    doc_height=self.document.height,
                    selection_snapshot=QPainterPath(self.document.selection) if self.document.selection else None,
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
        if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
            self.tool_opts["_pressure"] = 1.0

        self._mouse_pos = ev.position()

        if self._panning and self._pan_last is not None:
            delta = ev.position() - self._pan_last
            self._pan += delta
            self._pan_last = ev.position()
            self.update()
            return

        if self._rotating:
            cx = self.width()  / 2
            cy = self.height() / 2
            curr = math.degrees(
                math.atan2(ev.position().y() - cy, ev.position().x() - cx))
            delta = curr - self._rotate_last_angle
            if delta >  180: delta -= 360
            if delta < -180: delta += 360
            self._view_rotation += delta
            self._rotate_last_angle = curr
            self.update()
            return

        # Перерисовываем курсор / overlay
        if self._show_brush_cursor:
            self.update()
        elif isinstance(self.active_tool, (SelectTool, ShapesTool, RotateViewTool, GradientTool)) or (
                self.active_tool and hasattr(self.active_tool, "sub_drag_path")):
            self.update()

        if (ev.buttons() & Qt.MouseButton.LeftButton
                and self._stroke_in_progress and self.active_tool):
            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
            self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)
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

        if self._rotating and ev.button() == Qt.MouseButton.LeftButton:
            self._rotating = False
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
