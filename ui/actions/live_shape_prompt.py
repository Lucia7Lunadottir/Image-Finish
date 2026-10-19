"""Photoshop's "This operation will turn a live shape into a regular path"
question, asked before a pen tool edits the points of a Shapes-tool shape
(see tools/pen_tool.py: BasePenTool.live_shape_edit_at). "Don't ask
again" is remembered."""
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QMessageBox

from core.locale import tr

_SKIP_KEY = "prompts/skip_live_shape_conversion"


def _settings() -> QSettings:
    return QSettings("ImageFinish", "ImageFinish")


def confirm_live_shape_conversion(parent, layer) -> bool:
    """True if `layer` may be turned into a path layer."""
    settings = _settings()
    if settings.value(_SKIP_KEY, False, type=bool):
        return True
    box = QMessageBox(QMessageBox.Icon.Question, tr("dlg.live_shape.title"),
                      tr("dlg.live_shape.text", name=layer.name),
                      QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
    box.setDefaultButton(QMessageBox.StandardButton.Ok)
    dont_ask = QCheckBox(tr("dlg.live_shape.dont_ask"))
    box.setCheckBox(dont_ask)
    if box.exec() != QMessageBox.StandardButton.Ok:
        return False
    if dont_ask.isChecked():
        settings.setValue(_SKIP_KEY, True)
    return True
