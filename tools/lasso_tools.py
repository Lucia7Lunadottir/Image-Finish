import math
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QPainterPath, QPolygonF, QColor
from tools.base_tool import BaseTool

class LassoMixin:
    """Общая логика режимов выделения (Add, Subtract, Intersect)"""
    def _apply_path(self, doc, path: QPainterPath, opts: dict):
        sel = doc.selection
        ctrl = bool(opts.get("_ctrl", False))
        alt = bool(opts.get("_alt", False))

        if not sel or sel.isEmpty():
            doc.selection = path
            return

        base_path = QPainterPath(sel)
        if ctrl and alt:
            doc.selection = base_path.intersected(path)
        elif ctrl:
            doc.selection = base_path.united(path)
        elif alt:
            doc.selection = base_path.subtracted(path)
        else:
            doc.selection = path


class LassoTool(BaseTool, LassoMixin):
    name = "Lasso"
    icon = "➰"
    shortcut = "L"

    def __init__(self):
        self.points: list[QPointF] = []

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        self.points = [QPointF(pos)]

    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if self.points:
            self.points.append(QPointF(pos))

    def on_release(self, pos: QPoint, doc, fg, bg, opts):
        if len(self.points) > 2:
            path = QPainterPath()
            path.addPolygon(QPolygonF(self.points))
            path.closeSubpath()
            self._apply_path(doc, path, opts)
        self.points = []

    def needs_history_push(self) -> bool: return True
    def cursor(self): return Qt.CursorShape.CrossCursor
    def lasso_preview(self): return self.points


class PolygonalLassoTool(BaseTool, LassoMixin):
    name = "PolygonalLasso"
    icon = "⬡"
    shortcut = "L"

    def __init__(self):
        self.points: list[QPointF] = []
        self.current_pos: QPointF | None = None

    def on_press(self, pos: QPoint, doc, fg, bg, opts):
        # Завершение выделения по двойному клику (или если клик близко к началу)
        if self.points:
            start = self.points[0]
            dist = math.hypot(pos.x() - start.x(), pos.y() - start.y())
            if dist < 10:  # Замыкаем, если кликнули рядом с первой точкой
                self._commit(doc, opts)
                return

        self.points.append(QPointF(pos))
        self.current_pos = QPointF(pos)

    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if self.points:
            self.current_pos = QPointF(pos)

    def on_release(self, pos, doc, fg, bg, opts):
        pass # Полигональное лассо работает по кликам, а не по drag & drop

    def _commit(self, doc, opts):
        if len(self.points) > 2:
            path = QPainterPath()
            path.addPolygon(QPolygonF(self.points))
            path.closeSubpath()
            self._apply_path(doc, path, opts)
        self.points = []
        self.current_pos = None

    def needs_history_push(self) -> bool: return True
    def cursor(self): return Qt.CursorShape.CrossCursor
    def lasso_preview(self): return self.points, self.current_pos


class MagneticLassoTool(PolygonalLassoTool):
    name = "MagneticLasso"
    icon = "🧲"
    shortcut = "L"

    # Базовая версия (Poor Man's Magnetic Lasso).
    # Ищет самый темный/контрастный пиксель в радиусе 5px от курсора.
    def on_move(self, pos: QPoint, doc, fg, bg, opts):
        if not self.points:
            return

        layer = doc.get_active_layer()
        if not layer or layer.image.isNull():
            self.current_pos = QPointF(pos)
            return

        # Простой поиск пикселя (Edge snapping)
        snap_pos = pos
        best_diff = -1
        r = 5

        img = layer.image
        w, h = img.width(), img.height()

        if 0 <= pos.x() < w and 0 <= pos.y() < h:
            base_col = QColor(img.pixel(pos.x(), pos.y()))
            base_v = base_col.value()

            for dx in range(-r, r+1):
                for dy in range(-r, r+1):
                    nx, ny = pos.x() + dx, pos.y() + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        col = QColor(img.pixel(nx, ny))
                        diff = abs(col.value() - base_v)
                        if diff > best_diff:
                            best_diff = diff
                            snap_pos = QPoint(nx, ny)

        self.current_pos = QPointF(snap_pos)

        # Автоматически ставим точки при движении (как в настоящем магнитном)
        if len(self.points) > 0:
            last = self.points[-1]
            if math.hypot(snap_pos.x() - last.x(), snap_pos.y() - last.y()) > 15:
                self.points.append(QPointF(snap_pos))
