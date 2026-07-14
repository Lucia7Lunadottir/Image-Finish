from abc import ABC, abstractmethod
import traceback
from PyQt6.QtCore import QPoint, Qt, QObject, pyqtSignal, QRunnable, QThreadPool
from PyQt6.QtGui import QColor

from core.app_logging import get_logger

logger = get_logger("tools")

class BaseTool(ABC):
    """Abstract base class for all drawing and editing tools.
    Each tool receives coordinates in document space."""
    name: str = "Tool"
    icon_name: str = "move.svg"
    shortcut: str = ""
    modifies_canvas_on_move: bool = False

    def on_press(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Called on mouse button press."""
        pass

    def on_move(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Called on mouse move while button is held."""
        pass

    def on_release(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Called on mouse button release."""
        pass

    def cursor(self) -> Qt.CursorShape:
        return Qt.CursorShape.CrossCursor

    def needs_history_push(self) -> bool:
        """Returns True if the tool should save a history snapshot on press."""
        return True

    def __repr__(self) -> str:
        return f"<Tool:{self.name}>"


class AsyncToolSignals(QObject):
    """Signals for safely returning computation results to the GUI thread."""
    finished = pyqtSignal(object, object, dict)  # (result_data, doc, opts)
    error = pyqtSignal(str)


class GenericToolWorker(QRunnable):
    """Background worker for executing heavy tool computations."""
    def __init__(self, target_func, *args, **kwargs):
        super().__init__()
        self.signals = AsyncToolSignals()
        self.target_func = target_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.target_func(*self.args, **self.kwargs)
            self.signals.finished.emit(result, self.kwargs.get('doc'), self.kwargs.get('opts'))
        except Exception:
            self.signals.error.emit(traceback.format_exc())


class AbstractAsyncTool(BaseTool, ABC):
    """Abstract base for tools requiring async computations.
    Prevents GUI freezing by offloading work to QThreadPool."""
    def __init__(self):
        super().__init__()
        self._is_working = False
        self._liveness_check = None

    def set_liveness_check(self, predicate):
        """Inject a callable(doc) -> bool that tells whether the document
        is still open. Keeps tools decoupled from the window that owns
        the tabs (dependency inversion)."""
        self._liveness_check = predicate

    def execute_async(self, background_func, on_finished_gui_callback, doc, opts, *args, **kwargs):
        """Wraps the given function and submits it to QThreadPool."""
        if self._is_working:
            return

        self._is_working = True
        kwargs['doc'] = doc
        kwargs['opts'] = opts

        worker = GenericToolWorker(background_func, *args, **kwargs)

        worker.signals.finished.connect(
            lambda res, d=doc, o=opts: self._safe_gui_wrapper(on_finished_gui_callback, res, d, o)
        )
        worker.signals.error.connect(self._safe_error_handler)

        QThreadPool.globalInstance().start(worker)

    def _safe_gui_wrapper(self, callback, result, doc, opts):
        try:
            if self._liveness_check is not None and not self._liveness_check(doc):
                logger.info("[%s] Result dropped: document was closed "
                            "before the computation finished", self.name)
                return
            callback(result, doc, opts)
        except Exception:
            logger.exception("[%s] GUI callback error", self.name)
        finally:
            self._is_working = False

    def _safe_error_handler(self, err_trace):
        logger.error("[%s] Background computation error:\n%s", self.name, err_trace)
        self._is_working = False
