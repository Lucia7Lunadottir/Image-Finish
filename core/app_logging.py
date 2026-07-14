"""Application-wide logging and global exception handling.

Single responsibility: everything about *where errors go* lives here —
the rotating log file, the console handler, the Qt message redirect and
the crash dialog shown for unhandled exceptions.
"""

import logging
import logging.handlers
import os
import sys
import threading
import traceback

_LOG_INITIALIZED = False
_EXCEPTHOOK_ACTIVE = False  # re-entrancy guard for the crash dialog


def _log_dir() -> str:
    # Deliberately not QStandardPaths: setup_logging() runs before
    # QApplication exists, and the path must not depend on that ordering.
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "share"))
    return os.path.join(base, "ImageFinish", "logs")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"imagefinish.{name}")


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the root 'imagefinish' logger. Safe to call twice."""
    global _LOG_INITIALIZED
    root = logging.getLogger("imagefinish")
    if _LOG_INITIALIZED:
        return root
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)

    try:
        log_dir = _log_dir()
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "imagefinish.log"),
            maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(file_handler)
    except OSError:
        root.warning("Log file unavailable, logging to console only", exc_info=True)

    _LOG_INITIALIZED = True
    return root


def log_file_path() -> str:
    return os.path.join(_log_dir(), "imagefinish.log")


def _qt_message_handler(mode, context, message):
    from PyQt6.QtCore import QtMsgType
    logger = logging.getLogger("imagefinish.qt")
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        logger.error(message)
    elif mode == QtMsgType.QtWarningMsg:
        logger.warning(message)
    else:
        logger.debug(message)


def install_excepthook(app=None) -> None:
    """Route unhandled exceptions (main + worker threads) to the log and,
    when a QApplication exists, to a user-facing crash dialog."""
    logger = logging.getLogger("imagefinish.crash")

    def _show_dialog(text: str) -> None:
        global _EXCEPTHOOK_ACTIVE
        if _EXCEPTHOOK_ACTIVE:
            return
        _EXCEPTHOOK_ACTIVE = True
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return
            from core.locale import tr
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(tr("crash.title"))
            box.setText(tr("crash.message", path=log_file_path()))
            box.setDetailedText(text)
            box.setStandardButtons(QMessageBox.StandardButton.Ok
                                   | QMessageBox.StandardButton.Abort)
            box.button(QMessageBox.StandardButton.Ok).setText(tr("crash.continue"))
            box.button(QMessageBox.StandardButton.Abort).setText(tr("crash.quit"))
            if box.exec() == QMessageBox.StandardButton.Abort:
                os._exit(1)
        except Exception:
            logger.exception("Crash dialog itself failed")
        finally:
            _EXCEPTHOOK_ACTIVE = False

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("Unhandled exception:\n%s", text)
        _show_dialog(text)

    def _thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        logger.error("Unhandled exception in thread %r:\n%s",
                     getattr(args.thread, "name", "?"), text)

    sys.excepthook = _hook
    threading.excepthook = _thread_hook

    try:
        from PyQt6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        logger.warning("Could not install Qt message handler", exc_info=True)
