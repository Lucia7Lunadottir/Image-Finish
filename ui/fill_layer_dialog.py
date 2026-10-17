from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QPushButton, QDialogButtonBox, QWidget)
from PyQt6.QtGui import QColor, QPixmap, QIcon
from PyQt6.QtCore import Qt
from core.locale import tr


class FillLayerDialog(QDialog):

    def __init__(self, layer, canvas_refresh=None, parent=None):
        # Callers pass either a Layer (live preview possible) or a plain
        # settings dict; the second argument may be the parent widget.
        if canvas_refresh is not None and not callable(canvas_refresh) and parent is None:
            parent = canvas_refresh
            canvas_refresh = None
        super().__init__(parent)
        self.setWindowTitle(tr("fill_layer.title"))
        self.setMinimumWidth(300)

        if hasattr(layer, "fill_data"):
            self.layer = layer
            data = layer.fill_data
        else:
            self.layer = None
            data = layer
        self.canvas_refresh = canvas_refresh
        self._original_data = dict(data) if data else {}
        self._data = dict(self._original_data) if self._original_data else {"type": "solid",
                                                                            "color": QColor(128, 128, 128)}
        if not isinstance(self._data.get("type"), str):
            self._data["type"] = "solid"

        lo = QVBoxLayout(self)
        lo.setSpacing(8)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel(tr("fill_layer.type")))
        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("fill_layer.solid"),    "solid")
        self._type_combo.addItem(tr("fill_layer.gradient"), "gradient")
        cur = self._data.get("type", "solid")
        idx = next((i for i in range(self._type_combo.count())
                    if self._type_combo.itemData(i) == cur), 0)
        self._type_combo.setCurrentIndex(idx)
        type_row.addWidget(self._type_combo, 1)
        lo.addLayout(type_row)

        # ── Solid color ──────────────────────────────────────────────────
        self._solid_widget = QWidget()
        sr = QHBoxLayout(self._solid_widget)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel(tr("fill_layer.color")))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(48, 24)
        self._color = self._data.get("color", QColor(128, 128, 128))
        if not isinstance(self._color, QColor):
            self._color = QColor(128, 128, 128)
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        sr.addWidget(self._color_btn)
        sr.addStretch()
        lo.addWidget(self._solid_widget)

        # ── Gradient ─────────────────────────────────────────────────────
        # The same gradient model and editor as shape fills and the Gradient
        # tool (core/gradient_model.py); old files' two-color fills load as
        # a two-stop gradient.
        from core.gradient_model import Gradient
        from ui.gradient_editor import GradientPreviewWidget
        self._gradient = (Gradient.from_dict(self._data["gradient"]) if self._data.get("gradient")
                          else Gradient.two_color(QColor(self._data.get("color1", QColor(0, 0, 0))),
                                                  QColor(self._data.get("color2", QColor(255, 255, 255)))))
        self._grad_widget = QWidget()
        gr = QHBoxLayout(self._grad_widget)
        gr.setContentsMargins(0, 0, 0, 0)
        self._grad_swatch = GradientPreviewWidget()
        self._grad_swatch.setFixedSize(160, 26)
        self._grad_swatch.set_gradient(self._gradient)
        self._grad_swatch.setToolTip(tr("opts.gradient.edit_tip"))
        self._grad_swatch.clicked.connect(self._edit_gradient)
        gr.addWidget(self._grad_swatch)
        gr.addStretch()
        lo.addWidget(self._grad_widget)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

    # ── Color buttons ─────────────────────────────────────────────────────

    def _update_color_btn(self):
        pix = QPixmap(44, 20)
        pix.fill(self._color)
        self._color_btn.setIcon(QIcon(pix))
        self._color_btn.setIconSize(pix.size())

    def _pick_color(self):
        from ui.hsv_picker import ColorPickerDialog
        c = ColorPickerDialog.get_color(self._color, self, tr("adj.choose_color"))
        if c is not None:
            self._color = c
            self._update_color_btn()
            self._trigger_preview()

    def _edit_gradient(self):
        from ui.gradient_editor import GradientEditorDialog
        original = self._gradient.copy()
        dlg = GradientEditorDialog(original, parent=self, with_layout=True)

        def _live(g):
            self._gradient = g
            self._grad_swatch.set_gradient(g)
            self._trigger_preview()
        dlg.gradient_changed.connect(_live)
        if not dlg.exec():
            _live(original)

    def _on_type_changed(self):
        t = self._type_combo.currentData()
        self._solid_widget.setVisible(t == "solid")
        self._grad_widget.setVisible(t == "gradient")
        self.adjustSize()
        self._trigger_preview()

    # ── Result ────────────────────────────────────────────────────────────

    def result_data(self) -> dict:
        t = self._type_combo.currentData()
        if t == "gradient":
            return {"type": "gradient", "gradient": self._gradient.to_dict()}
        return {"type": "solid", "color": self._color}

    def _trigger_preview(self):
        if self.layer is not None:
            self.layer.fill_data = self.result_data()
        if self.canvas_refresh is not None:
            self.canvas_refresh()

    def accept(self):
        if self.layer is not None:
            self.layer.fill_data = self.result_data()
        super().accept()

    def reject(self):
        if self.layer is not None:
            self.layer.fill_data = self._original_data
        if self.canvas_refresh is not None:
            self.canvas_refresh()
        super().reject()
