from PyQt6.QtCore import QPoint, QRect, Qt
from tools.base_tool import BaseTool


class CropTool(BaseTool):
    name = "Crop"
    icon = "✂️"
    shortcut = "C"

    def __init__(self):
        self._start: QPoint | None = None
        self.pending_rect: QRect | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        self._start = pos
        self.pending_rect = None

    def on_move(self, pos, doc, fg, bg, opts):
        if self._start:
            self.pending_rect = QRect(self._start, pos).normalized()

    def on_release(self, pos, doc, fg, bg, opts):
        if self._start:
            self.pending_rect = QRect(self._start, pos).normalized()
        self._start = None

    def needs_history_push(self):
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor
