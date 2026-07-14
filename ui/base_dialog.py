"""Common base class for application dialogs.

Gives every dialog the same margins, button-box conventions and a
retranslate() hook, so individual dialogs stop hand-rolling their own
styling. The visual theme itself comes from the application stylesheet
(ui.theme) — dialogs must not set their own colors.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from core.locale import tr


class BaseDialog(QDialog):
    """QDialog with app-wide conventions.

    Subclasses build their content into `self.content_layout` (or use
    their own layout as before) and may call `add_button_box()` to get a
    standard OK/Cancel row wired to accept/reject.
    """

    def __init__(self, parent=None, title_key: str | None = None):
        super().__init__(parent)
        self._title_key = title_key
        self.setModal(True)
        if title_key:
            self.setWindowTitle(tr(title_key))

    def add_button_box(self, layout: QVBoxLayout,
                       buttons=QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel) -> QDialogButtonBox:
        box = QDialogButtonBox(buttons)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self._button_box = box
        return box

    def retranslate(self):
        if self._title_key:
            self.setWindowTitle(tr(self._title_key))

    def keyPressEvent(self, event):
        # Enter in a text field must not instantly accept a complex dialog
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) \
                and not getattr(self, "_accept_on_enter", True):
            event.ignore()
            return
        super().keyPressEvent(event)
