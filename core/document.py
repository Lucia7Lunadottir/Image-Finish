from PyQt6.QtGui import QImage, QPainter, QColor, QPainterPath, QLinearGradient, QBrush, qAlpha, QPolygonF, QTransform
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from .layer import Layer


def _get_composition_mode(mode_str: str) -> QPainter.CompositionMode:
    mapping = {
        "SourceOver": QPainter.CompositionMode.CompositionMode_SourceOver,
        "Multiply": QPainter.CompositionMode.CompositionMode_Multiply,
        "Screen": QPainter.CompositionMode.CompositionMode_Screen,
        "Overlay": QPainter.CompositionMode.CompositionMode_Overlay,
        "Darken": QPainter.CompositionMode.CompositionMode_Darken,
        "Lighten": QPainter.CompositionMode.CompositionMode_Lighten,
        "ColorDodge": QPainter.CompositionMode.CompositionMode_ColorDodge,
        "ColorBurn": QPainter.CompositionMode.CompositionMode_ColorBurn,
        "HardLight": QPainter.CompositionMode.CompositionMode_HardLight,
        "SoftLight": QPainter.CompositionMode.CompositionMode_SoftLight,
        "Difference": QPainter.CompositionMode.CompositionMode_Difference,
        "Exclusion": QPainter.CompositionMode.CompositionMode_Exclusion,
    }
    return mapping.get(mode_str, QPainter.CompositionMode.CompositionMode_SourceOver)

def _apply_layer_adjustment(image: QImage, layer) -> QImage:
    d = layer.adjustment_data or {}
    t = d.get("type", "")
    try:
        if t == "brightness_contrast":
            from ui.adjustments_dialog import apply_brightness_contrast
            return apply_brightness_contrast(image, d.get("brightness", 0), d.get("contrast", 0))
        elif t == "hue_saturation":
            from ui.adjustments_dialog import apply_hue_saturation
            return apply_hue_saturation(image, d.get("hue", 0),
                                        d.get("saturation", 0), d.get("lightness", 0))
        elif t == "invert":
            from ui.adjustments_dialog import apply_invert
            return apply_invert(image)
        elif t == "levels":
            from ui.levels_dialog import apply_levels
            return apply_levels(image, d.get("in_min", 0), d.get("in_max", 255), d.get("in_gamma", 1.0), d.get("out_min", 0), d.get("out_max", 255))
        elif t == "exposure":
            from core.adjustments.exposure import apply_exposure
            return apply_exposure(image, d.get("exposure", 0.0), d.get("offset", 0.0), d.get("gamma", 1.0))
        elif t == "vibrance":
            from core.adjustments.vibrance import apply_vibrance
            return apply_vibrance(image, d.get("vibrance", 0), d.get("saturation", 0))
        elif t == "black_white":
            from core.adjustments.black_white import apply_black_white
            return apply_black_white(image, d.get("reds", 40), d.get("yellows", 60), d.get("greens", 40), d.get("cyans", 60), d.get("blues", 20), d.get("magentas", 80))
        elif t == "posterize":
            from core.adjustments.posterize import apply_posterize
            return apply_posterize(image, d.get("levels", 4))
        elif t == "threshold":
            from core.adjustments.threshold import apply_threshold
            return apply_threshold(image, d.get("threshold", 128))
        elif t == "photo_filter":
            from core.adjustments.photo_filter import apply_photo_filter
            return apply_photo_filter(image, d.get("color", QColor(255,140,0)), d.get("density", 25), d.get("preserve", True))
        elif t == "gradient_map":
            from core.adjustments.gradient_map import apply_gradient_map
            return apply_gradient_map(image, d.get("shadows", QColor(0,0,0)), d.get("highlights", QColor(255,255,255)))
        elif t == "color_lookup":
            from core.adjustments.color_lookup import apply_color_lookup
            return apply_color_lookup(image, d.get("lut", None), d.get("intensity", 100))
        elif t == "hdr_toning":
            from core.adjustments.hdr_toning import apply_hdr_toning
            return apply_hdr_toning(image, d.get("radius", 10), d.get("strength", 0.5), d.get("gamma", 1.0), d.get("detail", 1.0))
    except Exception as e:
        print(f"Error applying adjustment layer '{t}':", e)
    return image


def _render_fill_layer(layer, w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    d = layer.fill_data or {}
    p = QPainter(img)
    ft = d.get("type", "solid")
    if ft == "solid":
        p.fillRect(img.rect(), d.get("color", QColor(128, 128, 128)))
    elif ft == "gradient":
        c1 = d.get("color1", QColor(0, 0, 0))
        c2 = d.get("color2", QColor(255, 255, 255))
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.fillRect(img.rect(), QBrush(grad))
    p.end()
    return img


class Document:
    """
    Holds all layers, document size, and selection state.
    The single source of truth for image data.
    """

    def __init__(self, width: int = 800, height: int = 600, bg_color: QColor = None):
        self.width: int = width
        self.height: int = height
        self.layers: list[Layer] = []
        self.active_layer_index: int = 0
        self.selection: QPainterPath | None = None  # active selection (may be non-rectangular)
        self.quick_mask_layer: Layer | None = None

        # Create default background layer
        bg = bg_color if bg_color else QColor(255, 255, 255)
        self.add_layer(name="Background", fill_color=bg)

    # ------------------------------------------------------------------ Layers
    def add_layer(self, name: str = None, index: int = None,
                  fill_color: QColor = None) -> Layer:
        if name is None:
            name = f"Layer {len(self.layers) + 1}"
        layer = Layer(name, self.width, self.height, fill_color)
        if index is None:
            self.layers.append(layer)
            self.active_layer_index = len(self.layers) - 1
        else:
            self.layers.insert(index, layer)
            self.active_layer_index = index
        return layer

    def duplicate_layer(self, index: int) -> Layer:
        src = self.layers[index]
        clone = src.copy()
        clone.name = f"{src.name} copy"
        self.layers.insert(index + 1, clone)
        self.active_layer_index = index + 1
        return clone

    def remove_layer(self, index: int):
        if len(self.layers) <= 1:
            return  # always keep at least one layer
        self.layers.pop(index)
        self.active_layer_index = max(0, min(self.active_layer_index, len(self.layers) - 1))

    def move_layer(self, from_index: int, to_index: int):
        """Move layer up/down in the stack."""
        if from_index < 0 or from_index >= len(self.layers):
            return
        to_index = max(0, min(to_index, len(self.layers) - 1))
        layer = self.layers.pop(from_index)
        self.layers.insert(to_index, layer)
        self.active_layer_index = to_index

    def get_active_layer(self) -> Layer | None:
        if getattr(self, "quick_mask_layer", None) is not None:
            return self.quick_mask_layer
        if self.layers and 0 <= self.active_layer_index < len(self.layers):
            return self.layers[self.active_layer_index]
        return None

    # ---------------------------------------------------------------- Composite
    def get_composite(self) -> QImage:
        result = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)

        painter = QPainter(result)
        current_clip_alpha = None
        
        for layer in self.layers:  # bottom → top
            if not layer.visible:
                continue
                
            ltype = getattr(layer, "layer_type", "raster")
            is_clipping = getattr(layer, "clipping", False)
            
            if is_clipping and current_clip_alpha is None:
                continue

            if ltype == "adjustment":
                painter.end()
                
                backup = result.copy()
                adjusted = _apply_layer_adjustment(backup, layer)
                
                import numpy as np
                ptr_b = backup.bits(); ptr_b.setsize(backup.sizeInBytes())
                arr_b = np.ndarray((backup.height(), backup.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr_b)
                
                ptr_a = adjusted.bits(); ptr_a.setsize(adjusted.sizeInBytes())
                arr_a = np.ndarray((adjusted.height(), adjusted.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr_a)
                
                frac = np.full((backup.height(), backup.width()), layer.opacity, dtype=np.float32)
                
                has_mask = getattr(layer, "mask", None) is not None and getattr(layer, "mask_enabled", True)
                if has_mask:
                    m_ptr = layer.mask.bits(); m_ptr.setsize(layer.mask.sizeInBytes())
                    m_arr = np.ndarray((layer.mask.height(), layer.mask.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=m_ptr)
                    mw = min(backup.width(), layer.mask.width())
                    mh = min(backup.height(), layer.mask.height())
                    mask_f = (m_arr[:mh, :mw, 1].astype(np.float32) / 255.0) * \
                             (m_arr[:mh, :mw, 3].astype(np.float32) / 255.0)
                    frac[:mh, :mw] *= mask_f
                    
                has_vmask = getattr(layer, "vector_mask", None) is not None and getattr(layer, "vector_mask_enabled", True)
                if has_vmask:
                    vmask_img = QImage(backup.width(), backup.height(), QImage.Format.Format_Grayscale8)
                    vmask_img.fill(0)
                    vp = QPainter(vmask_img)
                    vp.fillPath(layer.vector_mask, QColor(255, 255, 255))
                    vp.end()
                    v_ptr = vmask_img.bits(); v_ptr.setsize(vmask_img.sizeInBytes())
                    v_arr = np.ndarray((backup.height(), vmask_img.bytesPerLine()), dtype=np.uint8, buffer=v_ptr)
                    vmask_f = v_arr[:backup.height(), :backup.width()].astype(np.float32) / 255.0
                    frac *= vmask_f
                    
                if is_clipping and current_clip_alpha is not None:
                    frac *= current_clip_alpha
                
                frac_4 = frac[..., np.newaxis]
                
                ptr_res = result.bits(); ptr_res.setsize(result.sizeInBytes())
                arr_res = np.ndarray((result.height(), result.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr_res)
                
                arr_res[:backup.height(), :backup.width(), :] = (
                    arr_b[:backup.height(), :backup.width(), :] * (1.0 - frac_4) + 
                    arr_a[:backup.height(), :backup.width(), :] * frac_4
                ).astype(np.uint8)
                
                if not is_clipping:
                    current_clip_alpha = None
                
                painter = QPainter(result)

            else:
                if ltype == "fill":
                    img_to_draw = _render_fill_layer(layer, self.width, self.height)
                    img_to_draw.is_copy = True
                else:
                    img_to_draw = layer.image

                has_mask = getattr(layer, "mask", None) is not None and getattr(layer, "mask_enabled", True)
                
                if (has_mask or is_clipping) and not getattr(img_to_draw, "is_copy", False):
                    img_to_draw = img_to_draw.copy()
                    img_to_draw.is_copy = True

                if has_mask or is_clipping:
                    import numpy as np
                    ptr = img_to_draw.bits(); ptr.setsize(img_to_draw.sizeInBytes())
                    bpl = img_to_draw.bytesPerLine()
                    arr_full = np.ndarray((img_to_draw.height(), bpl // 4, 4), dtype=np.uint8, buffer=ptr)
                    arr = arr_full[:, :img_to_draw.width(), :]

                    if has_mask:
                        m_ptr = layer.mask.bits(); m_ptr.setsize(layer.mask.sizeInBytes())
                        m_bpl = layer.mask.bytesPerLine()
                        m_arr_full = np.ndarray((layer.mask.height(), m_bpl // 4, 4), dtype=np.uint8, buffer=m_ptr)
                        m_arr = m_arr_full[:, :img_to_draw.width(), :]
                        
                        mask_f = (m_arr[..., 1].astype(np.float32) / 255.0) * (m_arr[..., 3].astype(np.float32) / 255.0)
                        arr[..., 0] = (arr[..., 0] * mask_f).astype(np.uint8)
                        arr[..., 1] = (arr[..., 1] * mask_f).astype(np.uint8)
                        arr[..., 2] = (arr[..., 2] * mask_f).astype(np.uint8)
                        arr[..., 3] = (arr[..., 3] * mask_f).astype(np.uint8)
                        
                    if is_clipping:
                        ox, oy = layer.offset.x(), layer.offset.y()
                        w, h = img_to_draw.width(), img_to_draw.height()
                        dx1, dy1 = max(0, ox), max(0, oy)
                        dx2, dy2 = min(self.width, ox + w), min(self.height, oy + h)
                        
                        clip_mask = np.zeros((h, w), dtype=np.float32)
                        if dx1 < dx2 and dy1 < dy2:
                            sx1, sy1 = dx1 - ox, dy1 - oy
                            sx2, sy2 = sx1 + (dx2 - dx1), sy1 + (dy2 - dy1)
                            clip_mask[sy1:sy2, sx1:sx2] = current_clip_alpha[dy1:dy2, dx1:dx2]
                            
                        arr[..., 0] = (arr[..., 0] * clip_mask).astype(np.uint8)
                        arr[..., 1] = (arr[..., 1] * clip_mask).astype(np.uint8)
                        arr[..., 2] = (arr[..., 2] * clip_mask).astype(np.uint8)
                        arr[..., 3] = (arr[..., 3] * clip_mask).astype(np.uint8)

                    img_to_draw = QImage(arr_full.data, img_to_draw.width(), img_to_draw.height(), bpl, QImage.Format.Format_ARGB32_Premultiplied)
                    img_to_draw.ndarr = arr_full

                if not is_clipping:
                    import numpy as np
                    base_alpha_img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
                    base_alpha_img.fill(0)
                    ap = QPainter(base_alpha_img)
                    if getattr(layer, "vector_mask", None) is not None and getattr(layer, "vector_mask_enabled", True):
                        ap.setClipPath(layer.vector_mask)
                    ap.setOpacity(layer.opacity)
                    ap.drawImage(layer.offset, img_to_draw)
                    ap.end()
                    
                    ptr = base_alpha_img.bits(); ptr.setsize(base_alpha_img.sizeInBytes())
                    arr_alpha = np.ndarray((self.height, base_alpha_img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=ptr)
                    current_clip_alpha = arr_alpha[:, :self.width, 3].astype(np.float32) / 255.0

                painter.save()
                if getattr(layer, "vector_mask", None) is not None and getattr(layer, "vector_mask_enabled", True):
                    painter.setClipPath(layer.vector_mask)
                painter.setCompositionMode(_get_composition_mode(getattr(layer, "blend_mode", "SourceOver")))
                painter.setOpacity(layer.opacity)
                painter.drawImage(layer.offset, img_to_draw)
                painter.restore()

        if painter.isActive():
            painter.end()
            
        if getattr(self, "quick_mask_layer", None) is not None:
            qm = self.quick_mask_layer.image
            import numpy as np
            ptr = qm.bits(); ptr.setsize(qm.sizeInBytes())
            bpl = qm.bytesPerLine()
            arr = np.ndarray((qm.height(), bpl // 4, 4), dtype=np.uint8, buffer=ptr)[:, :self.width, :]
            
            # Чёрный цвет (или альфа=0) станет красной плёнкой, белый — прозрачным
            gray = 0.299*arr[..., 2] + 0.587*arr[..., 1] + 0.114*arr[..., 0]
            mask_val = (255 - gray) * (arr[..., 3] / 255.0)
            
            red_overlay = np.zeros((qm.height(), self.width, 4), dtype=np.uint8)
            red_overlay[..., 2] = 255 # R
            red_overlay[..., 3] = (mask_val * 0.5).astype(np.uint8) # A
            
            red_img = QImage(red_overlay.data, self.width, qm.height(), self.width*4, QImage.Format.Format_ARGB32_Premultiplied)
            red_img.ndarr = red_overlay # Защита от сборщика мусора
            p2 = QPainter(result)
            p2.drawImage(0, 0, red_img)
            p2.end()
            
        return result

    # ----------------------------------------------------------------- History
    def snapshot_layers(self) -> list[Layer]:
        snap = [layer.copy() for layer in self.layers]
        if getattr(self, "quick_mask_layer", None) is not None:
            snap.append(self.quick_mask_layer.copy())
        return snap

    def apply_layer_mask(self, layer):
        if getattr(layer, "mask", None) is None: return
        import numpy as np
        if getattr(layer, "layer_type", "raster") != "raster":
            layer.layer_type = "raster"
        w, h = layer.width(), layer.height()
        ptr = layer.image.bits(); ptr.setsize(layer.image.sizeInBytes())
        bpl = layer.image.bytesPerLine()
        arr_full = np.ndarray((h, bpl // 4, 4), dtype=np.uint8, buffer=ptr)
        arr = arr_full[:, :w, :]
        m_ptr = layer.mask.bits(); m_ptr.setsize(layer.mask.sizeInBytes())
        m_bpl = layer.mask.bytesPerLine()
        m_arr_full = np.ndarray((h, m_bpl // 4, 4), dtype=np.uint8, buffer=m_ptr)
        m_arr = m_arr_full[:, :w, :]
        mask_f = (m_arr[..., 1].astype(np.float32) / 255.0) * (m_arr[..., 3].astype(np.float32) / 255.0)
        arr[..., 0] = (arr[..., 0] * mask_f).astype(np.uint8)
        arr[..., 1] = (arr[..., 1] * mask_f).astype(np.uint8)
        arr[..., 2] = (arr[..., 2] * mask_f).astype(np.uint8)
        arr[..., 3] = (arr[..., 3] * mask_f).astype(np.uint8)
        layer.mask = None
        layer.editing_mask = False

    def restore_layers(self, snapshot: list[Layer]):
        self.layers = []
        self.quick_mask_layer = None
        for layer in snapshot:
            if getattr(layer, "is_quick_mask", False):
                self.quick_mask_layer = layer.copy()
            else:
                self.layers.append(layer.copy())

    # ------------------------------------------------------------------- Crop
    def apply_crop(self, rect: QRect):
        if rect.isEmpty():
            return
        tl = rect.topLeft()
        all_layers = self.layers + ([self.quick_mask_layer] if getattr(self, "quick_mask_layer", None) else [])
        for layer in all_layers:
            new_img = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            p = QPainter(new_img)
            # Re-render layer into the cropped coordinate system (doc-space aware)
            p.drawImage(layer.offset - tl, layer.image)
            p.end()
            layer.image = new_img
            layer.offset = QPoint(0, 0)
        self.width = rect.width()
        self.height = rect.height()
        self.selection = None

    def apply_perspective_crop(self, quad: QPolygonF):
        if quad.isEmpty() or quad.count() < 4:
            return

        # Извлекаем 4 точки
        pts = [quad[i] for i in range(4)]

        # Сортируем точки: находим две верхние (с минимальным Y) и две нижние
        pts.sort(key=lambda p: p.y())
        top_pts = pts[:2]
        bottom_pts = pts[2:]

        # Сортируем их по оси X (слева направо)
        top_pts.sort(key=lambda p: p.x())
        bottom_pts.sort(key=lambda p: p.x())

        # Получаем строгий порядок: Лево-Верх, Право-Верх, Лево-Низ, Право-Низ
        tl, tr = top_pts
        bl, br = bottom_pts

        # Вспомогательная функция для расчета расстояния (чтобы не импортировать math)
        def _dist(p1, p2):
            return ((p1.x() - p2.x())**2 + (p1.y() - p2.y())**2) ** 0.5

        # Вычисляем реальные размеры будущего холста без растяжений
        new_w = int(max(_dist(tl, tr), _dist(bl, br)))
        new_h = int(max(_dist(tl, bl), _dist(tr, br)))

        if new_w <= 0 or new_h <= 0:
            return

        # Создаем отсортированный многоугольник-источник (строго по часовой)
        sorted_quad = QPolygonF([tl, tr, br, bl])

        # Явно задаем 4 точки приемника (в том же порядке TL, TR, BR, BL)
        dst_quad = QPolygonF([
            QPointF(0, 0),
            QPointF(new_w, 0),
            QPointF(new_w, new_h),
            QPointF(0, new_h)
        ])

        all_layers = self.layers + ([self.quick_mask_layer] if getattr(self, "quick_mask_layer", None) else [])
        for layer in all_layers:
            new_img = QImage(new_w, new_h, QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)

            p = QPainter(new_img)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            src_quad = QPolygonF(sorted_quad)
            src_quad.translate(QPointF(-layer.offset))

            xform = QTransform()
            ok = QTransform.quadToQuad(src_quad, dst_quad, xform)
            if ok:
                p.setTransform(xform)
                p.drawImage(0, 0, layer.image)

            p.end()
            layer.image = new_img
            layer.offset = QPoint(0, 0)

        # Обновляем размеры самого документа
        self.width = new_w
        self.height = new_h
        self.selection = None

    # ------------------------------------------------------------------- Trim / Reveal All
    @staticmethod
    def _nontransparent_bounds(img: QImage) -> QRect:
        """Bounding rect of pixels with alpha > 0. Returns empty QRect if none."""
        w, h = img.width(), img.height()
        if w <= 0 or h <= 0:
            return QRect()

        min_x, min_y = w, h
        max_x, max_y = -1, -1

        for y in range(h):
            row_has = False
            for x in range(w):
                if qAlpha(img.pixel(x, y)) != 0:
                    row_has = True
                    if x < min_x: min_x = x
                    if y < min_y: min_y = y
                    if x > max_x: max_x = x
                    if y > max_y: max_y = y
            if row_has:
                # Small optimization: nothing else for this row
                pass

        if max_x < 0:
            return QRect()
        return QRect(min_x, min_y, (max_x - min_x + 1), (max_y - min_y + 1))

    def trim_transparent(self) -> bool:
        """Trim document to non-transparent pixels of the composite."""
        comp = self.get_composite()
        br = self._nontransparent_bounds(comp)
        if br.isEmpty() or (br.width() == self.width and br.height() == self.height and br.topLeft() == QPoint(0, 0)):
            return False
        self.apply_crop(br)
        return True

    def reveal_all(self) -> bool:
        """Expand canvas so all layer pixels (incl. offsets) fit inside."""
        bounds: QRect | None = None
        for layer in self.layers:
            # Adjustment layers don't contribute pixels; fill layers typically cover current canvas.
            ltype = getattr(layer, "layer_type", "raster")
            if ltype == "adjustment":
                continue
            br = self._nontransparent_bounds(layer.image)
            if br.isEmpty():
                continue
            br = br.translated(layer.offset)
            bounds = br if bounds is None else bounds.united(br)

        if bounds is None or bounds.isEmpty():
            return False

        # If everything already fits in current canvas (0..w,h), nothing to do.
        canvas = QRect(0, 0, self.width, self.height)
        if canvas.contains(bounds):
            return False

        # New canvas = union of current canvas and pixel bounds
        new_bounds = canvas.united(bounds)
        shift = new_bounds.topLeft()

        # Move all layers so new_bounds top-left becomes (0,0)
        for layer in self.layers:
            layer.offset = layer.offset - shift

        self.width = new_bounds.width()
        self.height = new_bounds.height()
        self.selection = None
        return True

    # ------------------------------------------------------------------ Flatten
    def flatten(self):
        composite = self.get_composite()
        self.layers.clear()
        bg = Layer("Background", self.width, self.height)
        bg.image = composite
        self.layers.append(bg)
        self.active_layer_index = 0

    def __repr__(self) -> str:
        return f"<Document {self.width}x{self.height} layers={len(self.layers)}>"
