from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QPainterPath
from tools.base_tool import BaseTool


class SelectTool(BaseTool):
    """
    Прямоугольное выделение:
      • Drag вне выделения      → новое выделение
      • Shift+drag              → добавить к выделению (union)
      • Ctrl+drag               → вычесть из выделения (subtract)
      • Drag ВНУТРИ выделения   → переместить контур выделения
    """
    name = "Select"
    icon = "⬜"
    shortcut = "M"

    def __init__(self):
        self._start:            QPoint       | None = None
        self._drag_end:         QPoint       | None = None
        self._mode:             str                 = "new"
        self._move_origin:      QPoint       | None = None
        self._move_origin_path: QPainterPath | None = None
        self._drag_base_path:   QPainterPath | None = None

    @staticmethod
    def _path_from_rect(r: QRect) -> QPainterPath:
        p = QPainterPath()
        p.addRect(QRectF(r))
        return p

    def on_press(self, pos, doc, fg, bg, opts):
        sel     = doc.selection
        shift   = bool(opts.get("_shift", False))
        ctrl    = bool(opts.get("_ctrl",  False))
        has_sel = sel and not sel.isEmpty()

        if has_sel and sel.contains(QPointF(pos)):
            self._mode             = "move"
            self._move_origin      = pos
            self._move_origin_path = QPainterPath(sel)
            return

        if shift and has_sel:
            self._mode           = "add"
            self._drag_base_path = QPainterPath(sel)
        elif ctrl and has_sel:
            self._mode           = "sub"
            self._drag_base_path = QPainterPath(sel)
        else:
            self._mode           = "new"
            self._drag_base_path = None
            doc.selection        = QPainterPath()
        self._start    = pos
        self._drag_end = pos

    def on_move(self, pos, doc, fg, bg, opts):
        if self._mode == "move" and self._move_origin and self._move_origin_path:
            delta = pos - self._move_origin
            doc.selection = self._move_origin_path.translated(delta.x(), delta.y())
            return

        if self._start:
            self._drag_end = pos
            drag_path = self._path_from_rect(QRect(self._start, pos).normalized())
            if self._mode == "add" and self._drag_base_path:
                doc.selection = self._drag_base_path.united(drag_path)
            elif self._mode == "sub" and self._drag_base_path:
                doc.selection = self._drag_base_path.subtracted(drag_path)
            else:
                doc.selection = drag_path

    def on_release(self, pos, doc, fg, bg, opts):
        self._start = self._drag_end = None
        self._move_origin = self._move_origin_path = None
        self._drag_base_path = None
        self._mode = "new"

    def sub_drag_rect(self) -> QRect | None:
        if self._mode == "sub" and self._start and self._drag_end:
            return QRect(self._start, self._drag_end).normalized()
        return None

    def needs_history_push(self) -> bool:
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor
