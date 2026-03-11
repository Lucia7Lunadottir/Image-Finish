from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QSlider, QCheckBox, QAbstractItemView, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPainter


def _make_eye_icon(visible: bool) -> QIcon:
    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    if visible:
        p.setPen(QColor(200, 200, 220))
        p.drawEllipse(4, 6, 12, 8)
        p.setBrush(QColor(140, 120, 200))
        p.drawEllipse(7, 8, 6, 6)
    else:
        p.setPen(QColor(80, 80, 100))
        p.drawLine(2, 2, 18, 18)
        p.drawEllipse(4, 6, 12, 8)
    p.end()
    return QIcon(pix)


class LayerItem(QWidget):
    """
    Custom widget for one row in the layers list.
    Shows:  👁 [thumbnail]  Name          [opacity]
    """
    visibility_toggled = pyqtSignal(int, bool)   # (row_index, new_visible)
    selected           = pyqtSignal(int)          # row_index

    def __init__(self, layer, index: int, is_active: bool, parent=None):
        super().__init__(parent)
        self._index = index
        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 2, 4, 2)
        lo.setSpacing(6)

        # Visibility toggle
        self._vis_btn = QPushButton("👁")
        self._vis_btn.setObjectName("smallBtn")
        self._vis_btn.setFixedSize(24, 24)
        self._vis_btn.setCheckable(True)
        self._vis_btn.setChecked(layer.visible)
        self._vis_btn.setToolTip("Toggle visibility")
        self._vis_btn.clicked.connect(
            lambda checked: self.visibility_toggled.emit(index, checked))
        lo.addWidget(self._vis_btn)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_pix = QPixmap.fromImage(
            layer.image.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.FastTransformation))
        thumb_lbl.setPixmap(thumb_pix)
        thumb_lbl.setFixedSize(26, 26)
        thumb_lbl.setStyleSheet("border: 1px solid #45475a; background: white;")
        lo.addWidget(thumb_lbl)

        # Name
        name_lbl = QLabel(layer.name)
        if is_active:
            name_lbl.setStyleSheet("color: #cba6f7; font-weight: bold;")
        lo.addWidget(name_lbl, 1)

        # Opacity
        op_lbl = QLabel(f"{int(layer.opacity * 100)}%")
        op_lbl.setStyleSheet("color: #7f849c; font-size: 11px;")
        op_lbl.setFixedWidth(36)
        lo.addWidget(op_lbl)

        # Text layer indicator
        if getattr(layer, "text_data", None) is not None:
            t_lbl = QLabel("T")
            t_lbl.setStyleSheet(
                "color:#89b4fa; font-weight:bold; font-size:13px;")
            t_lbl.setFixedWidth(14)
            t_lbl.setToolTip("Текстовый слой — кликните инструментом Text для редактирования")
            lo.addWidget(t_lbl)

        # Lock indicator
        if layer.locked:
            lock_lbl = QLabel("🔒")
            lock_lbl.setFixedWidth(18)
            lo.addWidget(lock_lbl)


class LayersPanel(QWidget):
    """
    Right-side layers panel.
    Emits signals to let the app modify the document.
    """

    layer_selected     = pyqtSignal(int)
    layer_added        = pyqtSignal()
    layer_duplicated   = pyqtSignal()
    layer_deleted      = pyqtSignal()
    layer_moved_up     = pyqtSignal()
    layer_moved_down   = pyqtSignal()
    layer_visibility   = pyqtSignal(int, bool)
    layer_opacity      = pyqtSignal(int, float)
    layer_merged_down  = pyqtSignal()
    layer_flatten      = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumWidth(200)
        self.setMaximumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title
        title = QLabel("LAYERS")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        # Opacity slider for active layer
        op_widget = QWidget()
        op_lo = QHBoxLayout(op_widget)
        op_lo.setContentsMargins(8, 2, 8, 2)
        op_lo.setSpacing(6)
        op_lo.addWidget(QLabel("Opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_lo.addWidget(self._opacity_slider, 1)
        self._opacity_label = QLabel("100%")
        self._opacity_label.setFixedWidth(36)
        self._opacity_label.setStyleSheet("color: #7f849c; font-size:11px;")
        op_lo.addWidget(self._opacity_label)
        layout.addWidget(op_widget)

        # Layer list
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list, 1)

        # Bottom buttons
        btn_bar = QWidget()
        btn_lo = QHBoxLayout(btn_bar)
        btn_lo.setContentsMargins(6, 4, 6, 6)
        btn_lo.setSpacing(4)

        def _btn(text, tip, signal):
            b = QPushButton(text)
            b.setObjectName("smallBtn")
            b.setFixedHeight(26)
            b.setToolTip(tip)
            b.clicked.connect(signal.emit)
            return b

        btn_lo.addWidget(_btn("+",  "New layer",       self.layer_added))
        btn_lo.addWidget(_btn("⧉",  "Duplicate layer", self.layer_duplicated))
        btn_lo.addWidget(_btn("↑",  "Move layer up",   self.layer_moved_up))
        btn_lo.addWidget(_btn("↓",  "Move layer down", self.layer_moved_down))

        del_btn = QPushButton("🗑")
        del_btn.setObjectName("dangerBtn")
        del_btn.setFixedHeight(26)
        del_btn.setToolTip("Delete layer")
        del_btn.clicked.connect(self.layer_deleted.emit)
        btn_lo.addWidget(del_btn)

        layout.addWidget(btn_bar)

        self._document = None
        self._updating = False

    # ---------------------------------------------------------------- Public
    def refresh(self, document):
        """Rebuild the list from the document."""
        self._document = document
        self._updating = True
        self._list.clear()

        # Show layers in reverse order (top-most first)
        for i in range(len(document.layers) - 1, -1, -1):
            layer = document.layers[i]
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)

            widget = LayerItem(layer, i, i == document.active_layer_index)
            widget.visibility_toggled.connect(self.layer_visibility.emit)
            item.setSizeHint(widget.sizeHint())
            self._list.setItemWidget(item, widget)

        # Select active layer row
        active = document.active_layer_index
        # find matching row (list is reversed)
        for row in range(self._list.count()):
            it = self._list.item(row)
            if it.data(Qt.ItemDataRole.UserRole) == active:
                self._list.setCurrentRow(row)
                break

        # Sync opacity slider
        layer = document.get_active_layer()
        if layer:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(int(layer.opacity * 100))
            self._opacity_slider.blockSignals(False)
            self._opacity_label.setText(f"{int(layer.opacity * 100)}%")

        self._updating = False

    # ---------------------------------------------------------------- Private
    def _on_row_changed(self, row: int):
        if self._updating or row < 0:
            return
        item = self._list.item(row)
        if item:
            real_index = item.data(Qt.ItemDataRole.UserRole)
            self.layer_selected.emit(real_index)

    def _on_opacity_changed(self, value: int):
        self._opacity_label.setText(f"{value}%")
        if self._document and not self._updating:
            active = self._document.active_layer_index
            self.layer_opacity.emit(active, value / 100)

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Duplicate",    self.layer_duplicated.emit)
        menu.addAction("Merge Down",   self.layer_merged_down.emit)
        menu.addSeparator()
        menu.addAction("Flatten Image", self.layer_flatten.emit)
        menu.addSeparator()
        del_act = menu.addAction("Delete")
        del_act.triggered.connect(self.layer_deleted.emit)
        menu.exec(self._list.mapToGlobal(pos))
