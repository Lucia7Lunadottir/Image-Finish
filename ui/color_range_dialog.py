import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QPushButton, QColorDialog, QDialogButtonBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QBitmap, QRegion, QPainterPath, QPixmap
from core.locale import tr

class ColorRangeDialog(QDialog):
    def __init__(self, document, update_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("color_range.title"))
        self.setMinimumWidth(300)
        self.document = document
        self.update_cb = update_cb
        self.layer = document.get_active_layer()
        
        self.target_color = QColor(255, 255, 255)
        self._final_mask = None

        self.layout = QVBoxLayout(self)

        # Чёрно-белое превью выделения, как в Photoshop (чтобы не лагал QPainterPath)
        self.preview_lbl = QLabel()
        self.preview_lbl.setFixedSize(280, 200)
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet("background-color: #000; border: 1px solid #555;")
        self.layout.addWidget(self.preview_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("adj.photo_filter.color")))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(40, 24)
        self.color_btn.setStyleSheet(f"background-color: {self.target_color.name()}; border: 1px solid #aaa;")
        self.color_btn.clicked.connect(self.choose_color)
        row1.addWidget(self.color_btn)
        row1.addStretch()
        self.layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("color_range.fuzziness")))
        self.fuzz_slider = QSlider(Qt.Orientation.Horizontal)
        self.fuzz_slider.setRange(0, 200)
        self.fuzz_slider.setValue(40)
        self.fuzz_slider.valueChanged.connect(self.apply_preview)
        row2.addWidget(self.fuzz_slider)
        self.layout.addLayout(row2)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        self.layout.addWidget(btns)

        self.apply_preview()

    def choose_color(self):
        c = QColorDialog.getColor(self.target_color, self)
        if c.isValid():
            self.target_color = c
            self.color_btn.setStyleSheet(f"background-color: {self.target_color.name()}; border: 1px solid #aaa;")
            self.apply_preview()

    def apply_preview(self):
        if not self.layer or self.layer.image.isNull():
            return
            
        fuzz = self.fuzz_slider.value()
        img = self.layer.image
        w, h = img.width(), img.height()
        
        tr_c, tg, tb = self.target_color.red(), self.target_color.green(), self.target_color.blue()
        
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        arr = np.ndarray((h, img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr)[:, :w, :]

        dist_sq = (arr[..., 2].astype(np.int32) - tr_c)**2 + \
                  (arr[..., 1].astype(np.int32) - tg)**2 + \
                  (arr[..., 0].astype(np.int32) - tb)**2
                  
        threshold_sq = (fuzz / 200.0)**2 * (255**2 * 3)
        self._final_mask = (dist_sq <= threshold_sq) & (arr[..., 3] > 0)
        
        # Отрисовываем маску в окно предпросмотра (это мгновенно)
        preview_arr = np.zeros((h, w), dtype=np.uint8)
        preview_arr[self._final_mask] = 255
        
        preview_img = QImage(preview_arr.data, w, h, w, QImage.Format.Format_Grayscale8)
        pixmap = QPixmap.fromImage(preview_img).scaled(
            self.preview_lbl.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        self.preview_lbl.setPixmap(pixmap)
        
    def accept(self):
        # Тяжелая конвертация в QPainterPath происходит ТОЛЬКО при нажатии OK
        if self._final_mask is not None:
            h, w = self._final_mask.shape
            tmp = np.zeros((h, w, 4), dtype=np.uint8)
            tmp[self._final_mask, 3] = 255
            
            mask_img = QImage(tmp.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            path = QPainterPath()
            path.addRegion(QRegion(QBitmap.fromImage(mask_img.createAlphaMask())))
            
            self.document.selection = path.simplified()
            self.update_cb()
            
        super().accept()