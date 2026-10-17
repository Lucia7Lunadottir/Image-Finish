from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal

from core.locale import tr

from ui import theme

def ITEM_STYLE():
    return (
    f"QListWidget{{background:{theme.BASE};border:none;color:{theme.TEXT};}}"
                  "QListWidget::item{padding:4px 8px;}"
                  f"QListWidget::item:selected{{background:{theme.SURFACE0};color:{theme.ACCENT};}}"
                  f"QListWidget::item:hover{{background:{theme.SURFACE1};}}"
    )
def BTN_STYLE():
    return (
    f"QPushButton{{background:{theme.SURFACE0};color:{theme.TEXT};border:none;"
                 "padding:4px 10px;border-radius:4px;}"
                 f"QPushButton:hover{{background:{theme.SURFACE1};}}"
                 f"QPushButton:pressed{{background:{theme.SURFACE2};}}"
    )
def LABEL_STYLE():
    return (f"color:{theme.SUBTEXT};font-size:11px;")

_NO_PATHS_PLACEHOLDER = "(no paths)"


def _tr_or(key: str, fallback: str) -> str:
    """tr() falls back to returning the key itself when it's missing from
    the locale file — this tells that case apart from a real translation."""
    val = tr(key)
    return val if val != key else fallback


class PathsPanel(QWidget):
    """
    Displays the document's work path (the single, unsaved path Pen Tool
    is currently drawing) and any permanent, named entries in
    doc.saved_paths. "New Path" promotes the current work path into a
    saved entry; saved entries can be renamed in place (double-click) and
    Make Selection/Fill/Stroke/Delete act on whichever row is selected,
    work path or saved.

    Signals allow the main window to carry out the actual path operations.
    """

    make_selection_requested = pyqtSignal()
    fill_path_requested      = pyqtSignal()
    stroke_path_requested    = pyqtSignal()
    delete_path_requested    = pyqtSignal()
    new_path_requested        = pyqtSignal()
    rename_path_requested     = pyqtSignal(int, str)  # (saved_paths index, new name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Title
        self._title = QLabel(self._title_text())
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)

        # Path list
        self._list = QListWidget()
        theme.apply_style(self._list, ITEM_STYLE)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.currentItemChanged.connect(lambda *_: self._update_btn_state())
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, 1)

        # Button grid (2×3 keeps the panel narrow enough to dock tightly)
        from PyQt6.QtWidgets import QGridLayout
        btn_bar = QWidget()
        btn_lo = QGridLayout(btn_bar)
        btn_lo.setContentsMargins(0, 4, 0, 0)
        btn_lo.setSpacing(4)

        self._btn_new    = QPushButton()
        self._btn_sel    = QPushButton()
        self._btn_fill   = QPushButton()
        self._btn_stroke = QPushButton()
        self._btn_delete = QPushButton()

        for i, btn in enumerate((self._btn_new, self._btn_sel, self._btn_fill,
                                 self._btn_stroke, self._btn_delete)):
            theme.apply_style(btn, BTN_STYLE)
            btn.setFixedHeight(26)
            btn.setMinimumWidth(40)
            btn_lo.addWidget(btn, i // 2, i % 2)

        self._btn_new.clicked.connect(self._on_new_path)
        self._btn_sel.clicked.connect(self._on_make_selection)
        self._btn_fill.clicked.connect(self._on_fill)
        self._btn_stroke.clicked.connect(self._on_stroke)
        self._btn_delete.clicked.connect(self._on_delete)

        layout.addWidget(btn_bar)

        self._canvas = None
        self._has_work_path = False
        self._num_saved = 0
        self._suppress_item_changed = False

        self.retranslate()

    # ----------------------------------------------------------------- public

    def refresh(self, canvas):
        """Rebuild the path list from canvas.document.work_path and
        canvas.document.saved_paths. Tries to keep whatever was selected
        (by kind + index) selected across the rebuild."""
        prev_kind, prev_idx = self._selected_kind()

        self._canvas = canvas
        self._suppress_item_changed = True
        self._list.clear()
        self._has_work_path = False
        self._num_saved = 0

        try:
            work_path = canvas.document.work_path
        except Exception:
            work_path = None
        try:
            saved_paths = canvas.document.saved_paths
        except Exception:
            saved_paths = []

        work_nodes = work_path.get("nodes", []) if isinstance(work_path, dict) else []
        self._has_work_path = bool(work_nodes)
        self._num_saved = len(saved_paths) if isinstance(saved_paths, list) else 0

        row_to_select = None
        if self._has_work_path:
            item = QListWidgetItem(_tr_or("paths.work_path", "Work Path"))
            item.setData(Qt.ItemDataRole.UserRole, ("work", None))
            self._list.addItem(item)
            if prev_kind == "work":
                row_to_select = self._list.count() - 1

        for i, sp in enumerate(saved_paths or []):
            item = QListWidgetItem(sp.get("name", "") if isinstance(sp, dict) else "")
            item.setData(Qt.ItemDataRole.UserRole, ("saved", i))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._list.addItem(item)
            if prev_kind == "saved" and prev_idx == i:
                row_to_select = self._list.count() - 1

        if self._list.count() == 0:
            item = QListWidgetItem(_tr_or("paths.no_paths", _NO_PATHS_PLACEHOLDER))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(Qt.GlobalColor.darkGray)
            self._list.addItem(item)
        else:
            self._list.setCurrentRow(row_to_select if row_to_select is not None else 0)

        self._suppress_item_changed = False
        self._update_btn_state()

    def retranslate(self):
        """Update button labels and title via tr()."""
        self._title.setText(self._title_text())
        self._btn_new.setText(_tr_or("paths.new", "New Path"))
        self._btn_sel.setText(_tr_or("paths.make_sel", "Make Selection"))
        self._btn_fill.setText(_tr_or("paths.fill", "Fill Path"))
        self._btn_stroke.setText(_tr_or("paths.stroke", "Stroke Path"))
        self._btn_delete.setText(_tr_or("paths.delete", "Delete Path"))

    # ----------------------------------------------------------------- private

    def _title_text(self) -> str:
        return _tr_or("panel.paths", "Paths")

    def _selected_kind(self):
        """Returns (kind, index) for the current selection — ("work", None),
        ("saved", i), or (None, None) if nothing real is selected."""
        item = self._list.currentItem()
        if item is None:
            return (None, None)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return (None, None)
        return data

    def _update_btn_state(self):
        kind, _ = self._selected_kind()
        has_selection = kind is not None
        for btn in (self._btn_sel, self._btn_fill, self._btn_stroke, self._btn_delete):
            btn.setEnabled(has_selection)
        self._btn_new.setEnabled(self._has_work_path)

    def _on_new_path(self):
        if self._has_work_path:
            self.new_path_requested.emit()

    def _on_make_selection(self):
        if self._selected_kind()[0] is not None:
            self.make_selection_requested.emit()

    def _on_fill(self):
        if self._selected_kind()[0] is not None:
            self.fill_path_requested.emit()

    def _on_stroke(self):
        if self._selected_kind()[0] is not None:
            self.stroke_path_requested.emit()

    def _on_delete(self):
        if self._selected_kind()[0] is not None:
            self.delete_path_requested.emit()

    def _on_item_changed(self, item: QListWidgetItem):
        """Inline rename (double-click a saved path row, type, Enter)."""
        if self._suppress_item_changed:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data[0] != "saved":
            return
        new_name = item.text().strip()
        if new_name:
            self.rename_path_requested.emit(data[1], new_name)
