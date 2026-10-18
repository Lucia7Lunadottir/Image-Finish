from PyQt6.QtCore import Qt
from tools.base_tool import BaseTool


class HandTool(BaseTool):
    CONTEXT_MENU = "view"
    name     = "Hand"
    icon     = "🖐"
    shortcut = "H"

    def needs_history_push(self) -> bool:
        return False

    def cursor(self):
        return Qt.CursorShape.OpenHandCursor


class ZoomTool(BaseTool):
    CONTEXT_MENU = "view"
    name     = "Zoom"
    icon     = "🔍"
    shortcut = "Z"

    def needs_history_push(self) -> bool:
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor


class RotateViewTool(BaseTool):
    CONTEXT_MENU = "view"
    REPAINT_ON_HOVER = True
    name     = "RotateView"
    icon     = "🔄"
    shortcut = ""

    def needs_history_push(self) -> bool:
        return False

    def cursor(self):
        return Qt.CursorShape.CrossCursor
