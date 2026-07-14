"""Persistence of window geometry and dock layout between sessions."""

from PyQt6.QtCore import QSettings

from core.app_logging import get_logger

logger = get_logger("workspace")

# Bump when the dock set changes incompatibly; restoreState with a
# mismatched version is rejected by Qt instead of restoring garbage.
STATE_VERSION = 1


def _settings() -> QSettings:
    return QSettings("ImageFinish", "ImageFinish")


def save(window) -> None:
    try:
        s = _settings()
        s.setValue("workspace/geometry", window.saveGeometry())
        s.setValue("workspace/state", window.saveState(STATE_VERSION))
    except Exception:
        logger.exception("Could not save workspace layout")


def restore(window) -> bool:
    """Restore saved geometry/layout; returns True if a layout was applied."""
    try:
        s = _settings()
        geo = s.value("workspace/geometry")
        state = s.value("workspace/state")
        if geo is not None:
            window.restoreGeometry(geo)
        if state is not None and window.restoreState(state, STATE_VERSION):
            return True
    except Exception:
        logger.exception("Could not restore workspace layout")
    return False
