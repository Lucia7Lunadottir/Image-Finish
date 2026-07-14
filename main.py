"""
ImageFinish — A PyQt6 image editor inspired by Photoshop.

Usage:
    python main.py

Requirements:
    pip install PyQt6
"""

import sys
import os
import glob

# Make sure sibling packages are importable when running from any CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Only lightweight imports before the splash goes up: the heavy ones
# (ui.main_window, numpy, tools) happen while the banner is visible.
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QIcon, QFontDatabase, QPixmap, QColor
from PyQt6.QtCore import Qt

from core.app_logging import setup_logging, install_excepthook, get_logger

logger = get_logger("main")

_APP_DIR   = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR  = os.path.join(_APP_DIR, "fonts")
BRUSHES_DIR = os.path.join(_APP_DIR, "brushes")
PATTERNS_DIR = os.path.join(_APP_DIR, "patterns")
ICON_PATH  = os.path.join(_APP_DIR, "imagefinish.png")


def _load_custom_fonts():
    """Load all .ttf/.otf fonts from the fonts/ directory."""
    os.makedirs(FONTS_DIR, exist_ok=True)
    os.makedirs(BRUSHES_DIR, exist_ok=True)
    os.makedirs(PATTERNS_DIR, exist_ok=True)
    patterns = ("**/*.ttf", "**/*.otf", "**/*.TTF", "**/*.OTF")
    loaded = 0
    for pat in patterns:
        for path in glob.glob(os.path.join(FONTS_DIR, pat), recursive=True):
            if QFontDatabase.addApplicationFont(path) != -1:
                loaded += 1
    if loaded:
        logger.info("Loaded custom fonts: %d", loaded)


def _make_splash(app) -> QSplashScreen:
    pix = QPixmap(ICON_PATH)
    if pix.isNull():
        pix = QPixmap(420, 260)
        pix.fill(QColor("#1e1e2e"))
    else:
        pix = pix.scaled(420, 420,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash


def _splash_message(app, splash, text):
    splash.showMessage(text,
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                       QColor("#cdd6f4"))
    app.processEvents()


def main():
    setup_logging()
    app = QApplication(sys.argv)
    install_excepthook(app)
    app.setApplicationName("ImageFinish")
    app.setApplicationVersion("1.1.0")
    app.setDesktopFileName("imagefinish")
    app.setWindowIcon(QIcon(ICON_PATH))

    splash = _make_splash(app)

    _splash_message(app, splash, "Loading fonts…")
    _load_custom_fonts()

    _splash_message(app, splash, "Loading editor…")
    from ui.main_window import MainWindow  # heavy import behind the splash

    _splash_message(app, splash, "Building workspace…")
    window = MainWindow()
    window.show()
    splash.finish(window)

    if len(sys.argv) > 1:
        try:
            window._open_file_path(sys.argv[1])
        except Exception:
            logger.exception("Failed to open file from command line: %s", sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
