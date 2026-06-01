from abc import ABC, abstractmethod
import traceback
from PyQt6.QtCore import QPoint, Qt, QObject, pyqtSignal, QRunnable, QThreadPool
from PyQt6.QtGui import QColor

class BaseTool(ABC):
    """
    Абстрактный базовый класс для всех инструментов рисования и редактирования.
    Каждый инструмент получает координаты в пространстве документа.
    """
    name: str = "Tool"
    icon_name: str = "move.svg"
    shortcut: str = ""
    modifies_canvas_on_move: bool = False

    def on_press(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Вызывается при нажатии кнопки мыши."""
        pass

    def on_move(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Вызывается при движении мыши с зажатой кнопкой."""
        pass

    def on_release(self, pos: QPoint, doc, fg: QColor, bg: QColor, opts: dict):
        """Вызывается при отпускании кнопки мыши."""
        pass

    def cursor(self) -> Qt.CursorShape:
        return Qt.CursorShape.CrossCursor

    def needs_history_push(self) -> bool:
        """Возвращает True, если инструмент должен сохранять снимок истории при нажатии."""
        return True

    def __repr__(self) -> str:
        return f"<Tool:{self.name}>"


class AsyncToolSignals(QObject):
    """Система сигналов для безопасного возврата результатов вычислений в GUI-поток."""
    finished = pyqtSignal(object, object, dict)  # (result_data, doc, opts)
    error = pyqtSignal(str)


class GenericToolWorker(QRunnable):
    """Универсальный фоновый рабочий для выполнения тяжелых расчетов любого инструмента."""
    def __init__(self, target_func, *args, **kwargs):
        super().__init__()
        self.signals = AsyncToolSignals()
        self.target_func = target_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            # Выполняем тяжелые вычисления в отдельном потоке ОС
            result = self.target_func(*self.args, **self.kwargs)
            self.signals.finished.emit(result, self.kwargs.get('doc'), self.kwargs.get('opts'))
        except Exception:
            self.signals.error.emit(traceback.format_exc())


class AbstractAsyncTool(BaseTool, ABC):
    """
    Абстрактный класс-предохранитель для инструментов, требующих асинхронных вычислений.
    Предотвращает зависание графического интерфейса (UI Lag).
    """
    def __init__(self):
        super().__init__()
        self._is_working = False

    def execute_async(self, background_func, on_finished_gui_callback, doc, opts, *args, **kwargs):
        """Упаковывает переданную функцию вычислений в поток и отправляет в QThreadPool."""
        if self._is_working:
            return  # Блокировка повторного запуска до окончания текущего расчета

            self._is_working = True
            kwargs['doc'] = doc
            kwargs['opts'] = opts

            worker = GenericToolWorker(background_func, *args, **kwargs)
            
            # Потокобезопасное связывание сигналов
            worker.signals.finished.connect(
                lambda res, d=doc, o=opts: self._safe_gui_wrapper(on_finished_gui_callback, res, d, o)
            )
            worker.signals.error.connect(self._safe_error_handler)

            # Запуск в глобальном пуле потоков приложения
            QThreadPool.globalInstance().start(worker)

        def _safe_gui_wrapper(self, callback, result, doc, opts):
            try:
                callback(result, doc, opts)
            except Exception:
                print(f"🛑 Сбой отрисовки интерфейса в инструменте {self.name}:\n{traceback.format_exc()}")
            finally:
                self._is_working = False

        def _safe_error_handler(self, err_trace):
            print(f"💥 Критическая ошибка вычислений в инструменте {self.name}:\n{err_trace}")
            self._is_working = False