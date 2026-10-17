"""Keeps a tool-options page usable when it's wider than the window: the
controls that don't fit move into a popup behind a "»" button, the way
Photoshop's and Qt's own toolbars handle overflow — instead of a page
running off the edge behind a horizontal scrollbar.

Works on any options page without per-page code: the page's row layout
is split once into *units* — a label together with the controls that
follow it, up to the next label/spacing/separator — so a label never
ends up separated from its control. Units then move between the row and
the popup as the available width changes.
"""
from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QSpacerItem, QToolButton,
                             QVBoxLayout, QWidget)


def page_layout(page) -> QLayout | None:
    """BaseOptions shadows QWidget.layout() with an attribute."""
    lay = getattr(page, "layout", None)
    if isinstance(lay, QLayout):
        return lay
    return lay() if callable(lay) else None


def _is_label(w) -> bool:
    return isinstance(w, QLabel) and w.objectName() == "optLabel"


def _is_separator(w) -> bool:
    return isinstance(w, QFrame) and w.frameShape() == QFrame.Shape.VLine


class _Unit(QWidget):
    def __init__(self, widgets):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for w in widgets:
            lay.addWidget(w)
        self.widgets = list(widgets)

    def width_hint(self) -> int:
        if not any(not w.isHidden() for w in self.widgets):
            return 0
        return self.sizeHint().width()


class _PageEntries:
    """The page's row as an ordered list of units and spacer items."""

    def __init__(self, page):
        self.page = page
        self.layout = page_layout(page)
        self.entries = []          # ("unit", _Unit) | ("item", QLayoutItem)
        self.overflowed: set = set()
        self._split()

    def _split(self):
        lay = self.layout
        items = []
        while lay.count():
            items.append(lay.takeAt(0))
        current = []

        def flush():
            if current:
                self.entries.append(("unit", _Unit(list(current))))
                current.clear()

        for item in items:
            w = item.widget()
            if w is None:
                flush()
                self.entries.append(("item", item))
                continue
            if _is_label(w) or _is_separator(w):
                flush()
            current.append(w)
            if _is_separator(w):
                flush()
        flush()
        self.rebuild()

    def units(self):
        return [e for kind, e in self.entries if kind == "unit"]

    def rebuild(self):
        lay = self.layout
        while lay.count():
            lay.takeAt(0)
        for kind, e in self.entries:
            if kind == "item":
                lay.addItem(e)
            elif e not in self.overflowed:
                lay.addWidget(e)


class OptionsOverflow(QObject):
    """Owned by ToolOptionsBar: `fit(page, width)` decides which units of
    the page stay in the row; the rest go into the popup."""

    BUTTON_W = 30

    def __init__(self, button: QToolButton, parent=None):
        super().__init__(parent)
        self.button = button
        self.button.setText("»")
        self.button.setAutoRaise(True)
        self.button.setFixedWidth(self.BUTTON_W)
        self.button.clicked.connect(self._show_popup)
        self.button.hide()
        self._pages: dict[int, _PageEntries] = {}
        self._current = None
        self._last_sig = None
        self._popup = QFrame(button, Qt.WindowType.Popup)
        self._popup.setObjectName("optionsOverflowPopup")
        self._popup_layout = QVBoxLayout(self._popup)
        self._popup_layout.setContentsMargins(10, 8, 10, 8)
        self._popup_layout.setSpacing(6)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._width = 0
        self._timer.timeout.connect(lambda: self.fit(self._current, self._width, force=True))

    def _entries(self, page) -> _PageEntries | None:
        if page_layout(page) is None:
            return None
        key = id(page)
        if key not in self._pages:
            self._pages[key] = _PageEntries(page)
            page.installEventFilter(self)
            for u in self._pages[key].units():
                u.installEventFilter(self)
        return self._pages[key]

    def eventFilter(self, obj, ev):
        # A control shown/hidden inside the page (e.g. the shape-kind
        # specific fields) changes what fits: re-fit once things settle.
        if ev.type() == QEvent.Type.LayoutRequest and self._current is not None:
            self._timer.start(0)
        return False

    def fit(self, page, width: int, force: bool = False):
        if page is None:
            return
        entries = self._entries(page)
        self._current, self._width = page, width
        if entries is None:
            self.button.hide()
            return
        units = entries.units()
        hints = [u.width_hint() for u in units]
        sig = (id(page), width, tuple(hints))
        if sig == self._last_sig and not force:
            return
        self._last_sig = sig
        spacing = max(0, entries.layout.spacing())
        fixed = sum(e.sizeHint().width() for kind, e in entries.entries
                    if kind == "item" and e.sizeHint().width() < 1000)
        total = sum(hints) + spacing * len(units) + fixed
        overflow = set()
        if total > width:
            budget = width - self.BUTTON_W - fixed
            used = 0
            for u, h in zip(units, hints):
                used += h + (spacing if h else 0)
                if used > budget:
                    overflow.add(u)
        if overflow == entries.overflowed and not force:
            self.button.setVisible(bool(overflow))
            return
        entries.overflowed = overflow
        entries.rebuild()
        self._fill_popup(entries)
        self.button.setVisible(bool(overflow))

    def _fill_popup(self, entries: _PageEntries):
        while self._popup_layout.count():
            self._popup_layout.takeAt(0)
        for u in entries.units():
            if u in entries.overflowed:
                self._popup_layout.addWidget(u, 0, Qt.AlignmentFlag.AlignLeft)
                u.show()

    def _show_popup(self):
        self._popup.adjustSize()
        pos = self.button.mapToGlobal(QPoint(self.button.width(), self.button.height()))
        self._popup.move(pos.x() - self._popup.width(), pos.y())
        self._popup.show()
