"""Current-document access for the main window.

Single responsibility: answer "which canvas/document/history is active
right now, and is it still valid?" — the one piece of state every action
handler needs but none should own. Handlers go through this object (or
the @require_document guard) instead of dereferencing possibly-None
references scattered across the window.
"""

import functools
import inspect

from PyQt6.QtCore import QObject

from core.app_logging import get_logger

logger = get_logger("document_controller")


def require_document(method):
    """Skip the handler (with a debug log) when no document is open.

    Designed for MainWindow/mixin slots that dereference `self._document`:
    menu actions and panel signals can fire while no tab exists.

    The wrapper's `*args` signature makes PyQt pass QAction.triggered's
    `checked` bool even to zero-argument handlers, so stray positional
    arguments beyond what the method accepts are dropped here.
    """
    params = list(inspect.signature(method).parameters.values())[1:]  # skip self
    has_varargs = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params)
    max_pos = len([p for p in params
                   if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                 inspect.Parameter.POSITIONAL_OR_KEYWORD)])
    required_pos = len([p for p in params
                        if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                      inspect.Parameter.POSITIONAL_OR_KEYWORD)
                        and p.default is inspect.Parameter.empty])

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if getattr(self, "_document", None) is None:
            logger.debug("%s skipped: no open document", method.__name__)
            return None
        if not has_varargs:
            if len(args) > max_pos:
                args = args[:max_pos]
            # QAction.triggered(checked) into a handler whose positional
            # params are all optional: the bool is noise, not an argument.
            if required_pos == 0 and len(args) == 1 and type(args[0]) is bool:
                args = ()
        return method(self, *args, **kwargs)
    return wrapper


class DocumentController(QObject):
    """Owns lookups into the document tab widget.

    All getters tolerate the empty state (no tabs) and bad indices,
    returning None instead of raising.
    """

    def __init__(self, doc_tabs, parent=None):
        super().__init__(parent)
        self._doc_tabs = doc_tabs

    # ── current object lookups ───────────────────────────────────────────
    def canvas(self):
        if self._doc_tabs.count() > 0:
            return self._doc_tabs.currentWidget()
        return None

    def document(self):
        c = self.canvas()
        return c.document if c else None

    def history(self):
        c = self.canvas()
        return getattr(c, "history", None) if c else None

    # ── guarded layer access ─────────────────────────────────────────────
    def layer_at(self, index):
        """Bounds-checked layer lookup; logs and returns None on a miss."""
        doc = self.document()
        if doc is None:
            logger.debug("layer_at(%s): no document", index)
            return None
        if not isinstance(index, int) or not (0 <= index < len(doc.layers)):
            logger.warning("layer_at(%s): out of range (%d layers)",
                           index, len(doc.layers))
            return None
        return doc.layers[index]

    def active_layer(self):
        doc = self.document()
        return doc.get_active_layer() if doc else None

    def set_active_layer_index(self, index) -> bool:
        """Clamp-checked assignment; returns False if index is invalid."""
        doc = self.document()
        if doc is None or not isinstance(index, int):
            return False
        if not (0 <= index < len(doc.layers)):
            logger.warning("set_active_layer_index(%s): out of range (%d layers)",
                           index, len(doc.layers))
            return False
        doc.active_layer_index = index
        return True

    # ── liveness for async work ──────────────────────────────────────────
    def is_alive(self, doc) -> bool:
        """True if `doc` still belongs to one of the open tabs."""
        if doc is None:
            return False
        for i in range(self._doc_tabs.count()):
            canvas = self._doc_tabs.widget(i)
            if canvas is not None and getattr(canvas, "document", None) is doc:
                return True
        return False
