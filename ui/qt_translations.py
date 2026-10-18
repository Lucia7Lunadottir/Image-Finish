"""Qt's own strings (OK / Cancel / Yes / No / Save in dialog button
boxes and message boxes, file dialogs) in the app's language: Qt ships
them as qtbase_<lang>.qm, which nothing loaded — so they stayed English
in every other language."""
from PyQt6.QtCore import QLibraryInfo, QTranslator
from PyQt6.QtWidgets import QApplication

# App locale code -> Qt translation file suffix, where they differ.
_QT_NAMES = {"pt": "pt_BR", "zh": "zh_CN"}

_translator: QTranslator | None = None


def install_qt_translator(lang: str) -> bool:
    """Swap in Qt's translation for `lang` (English: none needed)."""
    global _translator
    app = QApplication.instance()
    if app is None:
        return False
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None
    if lang == "en":
        return True
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load(f"qtbase_{_QT_NAMES.get(lang, lang)}", folder):
        return False
    app.installTranslator(translator)
    _translator = translator
    return True
