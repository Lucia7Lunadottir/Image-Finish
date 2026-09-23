from PyQt6.QtGui import QImage, QPainter, QColor, QPainterPath, QLinearGradient, QBrush, qAlpha, QPolygonF, QTransform
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from .layer import Layer, RasterLayer
from .render_context import CompositeContext
from core.pixel_buffer import qimage_argb_view as _qimage_argb_view
from core.pixel_buffer import ensure_owned_copy as _ensure_owned_copy
from core.pixel_buffer import shift_pixels_edge as _shift_pixels_edge

from core.app_logging import get_logger

logger = get_logger("document")


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
    
    def get_v(keywords, default):
        for kw in keywords:
            if kw in d: return d[kw]
        best_val = default
        for k, v in d.items():
            if not isinstance(v, (int, float)): continue
            kl = k.lower()
            if any(kw in kl for kw in keywords):
                if "max" in keywords[0] and "min" in kl: continue
                if "min" in keywords[0] and "max" in kl: continue
                if "out" in keywords[0] and "in" in kl: continue
                if "in" in keywords[0] and "out" in kl: continue
                best_val = v
                if isinstance(v, float): return v
        return best_val

    try:
        if t == "brightness_contrast":
            from ui.adjustments_dialog import apply_brightness_contrast
            return apply_brightness_contrast(image, int(get_v(["brightness", "bright"], 0)), int(get_v(["contrast", "contr"], 0)))
        elif t == "hue_saturation":
            from ui.adjustments_dialog import apply_hue_saturation
            return apply_hue_saturation(image, int(get_v(["hue"], 0)), int(get_v(["saturation", "sat"], 0)), int(get_v(["lightness", "light"], 0)))
        elif t == "invert":
            from ui.adjustments_dialog import apply_invert
            return apply_invert(image)
        elif t == "curves":
            from core.adjustments.curves import apply_curves
            return apply_curves(image, d.get("points") or {})
        elif t == "levels":
            from ui.levels_dialog import apply_levels
            in_min = int(get_v(["in_min", "in_black", "in_low", "black_sp"], 0))
            in_max = int(get_v(["in_max", "in_white", "in_high", "white_sp"], 255))
            gamma  = float(get_v(["gamma", "mid", "gamma_sp"], 1.0))
            out_min = int(get_v(["out_min", "out_black", "out_low", "out_min_sp"], 0))
            out_max = int(get_v(["out_max", "out_white", "out_high", "out_max_sp"], 255))
            
            if gamma > 5.0: gamma /= 100.0
            if gamma <= 0.0: gamma = 1.0
            if in_max <= in_min: in_max = in_min + 1
            
            return apply_levels(image, in_min, gamma, in_max, out_min, out_max)
        elif t == "exposure":
            from core.adjustments.exposure import apply_exposure
            exp = float(get_v(["exposure", "exp"], 0.0))
            off = float(get_v(["offset", "off"], 0.0))
            gam = float(get_v(["gamma", "gam"], 1.0))
            
            if exp > 20.0 or exp < -20.0: exp /= 100.0
            if off > 1.0 or off < -1.0: off /= 1000.0
            if gam > 5.0: gam /= 100.0
            if gam <= 0.0: gam = 1.0
            
            return apply_exposure(image, exp, off, gam)
        elif t == "vibrance":
            from core.adjustments.vibrance import apply_vibrance
            return apply_vibrance(image, int(get_v(["vibrance", "vib"], 0)), int(get_v(["saturation", "sat"], 0)))
        elif t == "black_white":
            from core.adjustments.black_white import apply_black_white
            return apply_black_white(image, int(get_v(["red"], 40)), int(get_v(["yellow"], 60)), int(get_v(["green"], 40)), int(get_v(["cyan"], 60)), int(get_v(["blue"], 20)), int(get_v(["magenta"], 80)))
        elif t == "posterize":
            from core.adjustments.posterize import apply_posterize
            return apply_posterize(image, int(get_v(["level", "lvl"], 4)))
        elif t == "threshold":
            from core.adjustments.threshold import apply_threshold
            return apply_threshold(image, int(get_v(["threshold", "thresh"], 128)))
        elif t == "photo_filter":
            from core.adjustments.photo_filter import apply_photo_filter
            color = d.get("color", QColor(255, 140, 0))
            return apply_photo_filter(image, color, int(get_v(["density", "dens"], 25)), bool(get_v(["preserve"], True)))
        elif t == "gradient_map":
            from core.adjustments.gradient_map import apply_gradient_map
            return apply_gradient_map(image, d.get("shadows", QColor(0,0,0)), d.get("highlights", QColor(255,255,255)))
        elif t == "color_lookup":
            from core.adjustments.color_lookup import apply_color_lookup
            return apply_color_lookup(image, d.get("lut", None), int(get_v(["intensity"], 100)))
        elif t == "hdr_toning":
            from core.adjustments.hdr_toning import apply_hdr_toning
            return apply_hdr_toning(image, int(get_v(["radius", "rad"], 10)), float(get_v(["strength", "str"], 0.5)), float(get_v(["gamma"], 1.0)), float(get_v(["detail", "det"], 1.0)))
    except Exception as e:
        logger.exception("Error applying adjustment layer %r", t)
    return image


def _composite_active_stroke(target: QImage, stroke_img: QImage, active_stroke: dict, offset: QPoint) -> None:
    """Paint `stroke_img` onto `target` in place using `active_stroke`'s
    clip path / blend mode / opacity, at document-space `offset`. Shared by
    the normal per-layer stroke preview and the mask-editing stroke preview
    so the two compositing rules can't drift apart."""
    p = QPainter(target)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if active_stroke["clip"]:
        p.setClipPath(active_stroke["clip"].translated(-offset.x(), -offset.y()))
    p.setCompositionMode(active_stroke["mode"])
    p.setOpacity(active_stroke["opacity"])
    p.drawImage(0, 0, stroke_img)
    p.end()


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
        
        self.guides_v: list[float] = []
        self.guides_h: list[float] = []
        self.slices: list[QRect] = []
        self.work_path: dict = {"nodes": [], "closed": False}
        self.show_slices: bool = True
        self.show_guides: bool = True
        self.show_grid: bool = False
        self.grid_size: int = 50
        self.snap_enabled: bool = True
        self.snap_to_guides: bool = True
        self.snap_to_grid: bool = False
        self.snap_to_bounds: bool = True
        self.snap_to_layers: bool = True
        self.alpha_channels: list[dict] = []
        self.color_mode: str = "RGB"
        self.bit_depth: int = 8

        # Create default background layer
        bg = bg_color if bg_color else QColor(255, 255, 255)
        self.add_layer(name="Background", fill_color=bg)

    # ------------------------------------------------------------------ Layers
    def add_layer(self, name: str = None, index: int = None,
                  fill_color: QColor = None, layer_cls: type = RasterLayer) -> Layer:
        if name is None:
            name = f"Layer {len(self.layers) + 1}"

        parent_id = None
        if self.layers and 0 <= self.active_layer_index < len(self.layers):
            active = self.layers[self.active_layer_index]
            if getattr(active, "layer_type", "raster") in ("artboard", "group"):
                parent_id = getattr(active, "layer_id", None)
                if index is not None and index == self.active_layer_index + 1:
                    # Insert INSIDE the group (at the group's position, shifting the group itself up)
                    insert_idx = self.active_layer_index
            else:
                parent_id = getattr(active, "parent_id", None)

        layer = layer_cls(name, self.width, self.height, fill_color)
        layer.parent_id = parent_id
        
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
        import uuid
        clone.layer_id = str(uuid.uuid4())
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

    def _all_layers_including_quick_mask(self) -> list[Layer]:
        return self.layers + ([self.quick_mask_layer] if getattr(self, "quick_mask_layer", None) else [])

    def replace_layer(self, old: Layer, new: Layer) -> Layer:
        """Swap `old` for `new` wherever it lives (`self.layers` or
        `quick_mask_layer`), carrying over `old`'s `layer_id` so undo
        history, selection-by-id and active-layer tracking keep working
        unchanged. Needed because a layer's kind is now its class, not a
        settable `layer_type` flag — see `Layer.convert_to`."""
        new.layer_id = old.layer_id
        if getattr(self, "quick_mask_layer", None) is old:
            self.quick_mask_layer = new
            return new
        idx = self.layers.index(old)
        self.layers[idx] = new
        return new

    # ---------------------------------------------------------------- Composite
    def invalidate_composite(self):
        self._composite_cache_doc = None

    def _composite_eligible_for_partial(self) -> bool:
        """Whether a sub-rect re-render can be safely blitted into the
        existing cache instead of recomposing the whole canvas.

        Adjustment layers, artboards and clipping groups all rely on
        canvas-sized numpy buffers (built with self.width/self.height, not
        rect-relative math) inside the render loop below; those branches
        are only ever exercised on a full-canvas rect. Excluding documents
        that use them keeps that invariant true without having to rewrite
        that arithmetic to be rect-relative.

        Layer styles (shadow/glow/bevel) are excluded too: they can paint
        pixels well outside the rect that changed on the *source* layer
        (e.g. a drop shadow offset away from the stroke), and the caller
        supplying dirty_rect has no general way to know how far a given
        style spreads. Restricting to documents with no styles anywhere
        keeps that safe regardless of which caller passes dirty_rect,
        rather than relying on every caller to reason about style spread.
        """
        if getattr(self, "quick_mask_layer", None) is not None:
            return False
        for layer in self.layers:
            lt = getattr(layer, "layer_type", "raster")
            if lt in ("adjustment", "artboard"):
                return False
            if getattr(layer, "clipping", False):
                return False
            if getattr(layer, "layer_styles", None):
                return False
        return True

    def get_composite(self, dirty_rect: QRect | None = None) -> QImage:
        cached = getattr(self, "_composite_cache_doc", None)

        if (dirty_rect is not None and cached is not None
                and cached.width() == self.width and cached.height() == self.height
                and self._composite_eligible_for_partial()):
            region = dirty_rect.intersected(QRect(0, 0, self.width, self.height))
            if region.isEmpty():
                return cached
            patch = self._render_composite(region)
            p = QPainter(cached)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(region.topLeft(), patch)
            p.end()
            return cached

        if cached is not None:
            return cached

        result = self._render_composite(QRect(0, 0, self.width, self.height))
        self._composite_cache_doc = result
        return result

    def _render_composite(self, rect: QRect) -> QImage:
        """Render layers restricted to `rect` (document coordinates).

        Only ever called with a non-full-canvas rect for documents that
        passed `_composite_eligible_for_partial()` — i.e. no adjustment
        layers, artboards, or clipping, so the self.width/self.height-sized
        numpy buffers further down never execute off a partial rect.
        """
        # Fast path: single visible raster layer, full opacity, no masks/styles
        visible = [l for l in self.layers if l.visible]
        if len(visible) == 1:
            l = visible[0]
            lt = getattr(l, "layer_type", "raster")
            if (lt == "raster" and l.opacity >= 1.0
                    and not getattr(l, "mask", None)
                    and not getattr(l, "vector_mask", None)
                    and not getattr(l, "clipping", False)
                    and not getattr(l, "layer_styles", None)
                    and getattr(self, "quick_mask_layer", None) is None
                    and l.offset.x() == 0 and l.offset.y() == 0
                    and l.image.width() == self.width and l.image.height() == self.height):
                active_stroke = getattr(l, "active_stroke", None)
                if not active_stroke:
                    return l.image.copy(rect)
                # Same fast path, but mid-stroke: the general path below
                # handles this by `img_to_draw = img_to_draw.copy()`ing the
                # WHOLE layer image before compositing the stroke preview
                # onto it — on an 8000x8000 canvas that's a 256MB copy on
                # every single mouse-move sample during a stroke (measured:
                # ~90ms/sample, the actual "lags while drawing" cost, an
                # order of magnitude more than the GPU texture upload).
                # Crop to `rect` first — this is exactly the plain-layer,
                # no-mask/clip/style case the fast path above already
                # covers, active_stroke is the only thing excluding it.
                base = l.image.copy(rect)
                p = QPainter(base)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                if active_stroke["clip"]:
                    p.setClipPath(active_stroke["clip"].translated(-rect.x(), -rect.y()))
                p.setCompositionMode(active_stroke["mode"])
                p.setOpacity(active_stroke["opacity"])
                p.drawImage(-rect.topLeft(), active_stroke["img"])
                p.end()
                return base

        result = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)

        painter = QPainter(result)
        painter.translate(-rect.topLeft())

        children_map = {}
        for layer in self.layers:
            pid = getattr(layer, "parent_id", None)
            children_map.setdefault(pid, []).append(layer)

        ctx = CompositeContext(document=self, result=result, painter=painter, children_map=children_map)
        self._render_layer_list(children_map.get(None, []), None, ctx)
        painter = ctx.painter

        if painter.isActive():
            painter.end()
            
        if getattr(self, "quick_mask_layer", None) is not None:
            qm = self.quick_mask_layer.image
            import numpy as np
            ptr = qm.bits(); ptr.setsize(qm.sizeInBytes())
            bpl = qm.bytesPerLine()
            arr = np.ndarray((qm.height(), bpl // 4, 4), dtype=np.uint8, buffer=ptr)[:, :self.width, :]
            
            # Black (or alpha=0) becomes a red overlay; white becomes transparent
            gray = 0.299*arr[..., 2] + 0.587*arr[..., 1] + 0.114*arr[..., 0]
            mask_val = (255 - gray) * (arr[..., 3] / 255.0)
            
            red_overlay = np.zeros((qm.height(), self.width, 4), dtype=np.uint8)
            alpha = (mask_val * 0.5).astype(np.uint8)
            red_overlay[..., 2] = alpha # R (Premultiplied)
            red_overlay[..., 3] = alpha # A
            
            red_img = QImage(self.width, qm.height(), QImage.Format.Format_ARGB32_Premultiplied)
            r_ptr = red_img.bits()
            r_ptr.setsize(red_img.sizeInBytes())
            r_arr = np.frombuffer(r_ptr, dtype=np.uint8).reshape((qm.height(), self.width, 4))
            r_arr[:] = red_overlay
            del r_arr
            del r_ptr
            p2 = QPainter(result)
            p2.drawImage(0, 0, red_img)
            p2.end()
            
            del arr
            del ptr

        return result

    def _render_layer_list(self, layers: list[Layer], layer_artboard_rect, ctx: "CompositeContext") -> None:
        """Render one sibling list (top-level layers, or one group's/
        artboard's children) into `ctx`. Dispatch used to be `if ltype ==
        "adjustment": ... elif ltype == "frame": ... else: ...` here;
        `Layer.render_into` (overridden per subclass) replaced that, so
        adding a new layer kind means adding a `render_into` override, not
        another branch in this loop."""
        for i, layer in enumerate(layers):
            if not layer.visible:
                continue

            is_clipping = getattr(layer, "clipping", False)
            next_clipping = False
            if i + 1 < len(layers):
                nl = layers[i + 1]
                if getattr(nl, "clipping", False) and nl.visible:
                    next_clipping = True

            # Containers (group/artboard) recurse regardless of clipping —
            # "clipped with nothing to clip against yet" only applies to
            # layers that draw pixels of their own.
            if not layer._is_container and is_clipping and ctx.clip_alpha is None:
                continue

            layer.render_into(ctx, layer_artboard_rect, is_clipping, next_clipping)

    # ----------------------------------------------------------------- History
    def snapshot_layers(self, modified_index: int | None = None) -> list[Layer]:
        """Snapshot layers for undo.

        Pixel data is always shared copy-on-write (`QImage(other)`): every
        later mutation goes through QPainter/bits(), which detaches the
        live image first, so snapshots stay intact without deep copies.
        Snapshots must be taken *before* the mutating code acquires pixel
        pointers (the press/menu paths already do).

        `modified_index` is kept for call-site documentation only — it no
        longer changes behavior.
        """
        snap = [layer.copy(deep_image=False) for layer in self.layers]
        if getattr(self, "quick_mask_layer", None) is not None:
            snap.append(self.quick_mask_layer.copy(deep_image=False))
        return snap

    def apply_layer_mask(self, layer):
        if getattr(layer, "mask", None) is None: return
        import numpy as np
        if getattr(layer, "layer_type", "raster") != "raster":
            # Baking the mask into pixels can carve alpha in ways the
            # original type's data (text_data, shape_data, ...) can no
            # longer reproduce — demote to plain raster first.
            layer = self.replace_layer(layer, layer.convert_to(RasterLayer))
        w = layer.width()
        arr_full = _qimage_argb_view(layer.image, writable=True)
        arr = arr_full[:, :w, :]
        m_arr_full = _qimage_argb_view(layer.mask, writable=False)
        m_arr = m_arr_full[:, :w, :]
        mask_f = m_arr[..., 1].astype(np.float32) / 255.0
        arr[:] = (arr.astype(np.float32) * mask_f[..., np.newaxis]).astype(np.uint8)
        layer.mask = None
        layer.editing_mask = False

    def restore_layers(self, snapshot: list[Layer]):
        # deep_image=False: pixel data is shared copy-on-write with the
        # snapshot, so restore is cheap and later painting detaches safely.
        self.layers = []
        self.quick_mask_layer = None
        for layer in snapshot:
            if getattr(layer, "is_quick_mask", False):
                self.quick_mask_layer = layer.copy(deep_image=False)
            else:
                self.layers.append(layer.copy(deep_image=False))

    # ------------------------------------------------------------------- Crop
    def apply_crop(self, rect: QRect):
        if rect.isEmpty():
            return
        tl = rect.topLeft()
        all_layers = self._all_layers_including_quick_mask()
        for layer in all_layers:
            old_offset = layer.offset
            new_img = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            p = QPainter(new_img)
            # Re-render layer into the cropped coordinate system (doc-space aware)
            p.drawImage(old_offset - tl, layer.image)
            p.end()
            layer.image = new_img
            layer.offset = QPoint(0, 0)
            self._shift_layer_content_data(layer, old_offset - tl)
        self.width = rect.width()
        self.height = rect.height()
        self.selection = None

    @staticmethod
    def _shift_layer_content_data(layer: Layer, shift: QPoint):
        """Keep cached local-space anchors (text/shape origin) in sync when a
        layer's image is re-baked into a new local coordinate origin (crop).
        Without this, re-editing a text/shape layer after a crop redraws it
        at its stale pre-crop position."""
        td = getattr(layer, "text_data", None)
        if td:
            td["x"] = td.get("x", 0) + shift.x()
            td["y"] = td.get("y", 0) + shift.y()
        sd = getattr(layer, "shape_data", None)
        if sd:
            rx, ry, rw, rh = sd.get("rect", (0, 0, 0, 0))
            sd["rect"] = (rx + shift.x(), ry + shift.y(), rw, rh)
            sx, sy = sd.get("start", (0, 0))
            sd["start"] = (sx + shift.x(), sy + shift.y())
            ex, ey = sd.get("end", (0, 0))
            sd["end"] = (ex + shift.x(), ey + shift.y())

    def apply_perspective_crop(self, quad: QPolygonF):
        if quad.isEmpty() or quad.count() < 4:
            return

        # Extract 4 points
        pts = [quad[i] for i in range(4)]

        # Sort points: find the two topmost (minimum Y) and two bottommost
        pts.sort(key=lambda p: p.y())
        top_pts = pts[:2]
        bottom_pts = pts[2:]

        # Sort each pair by X (left to right)
        top_pts.sort(key=lambda p: p.x())
        bottom_pts.sort(key=lambda p: p.x())

        # Strict order: Top-Left, Top-Right, Bottom-Left, Bottom-Right
        tl, tr = top_pts
        bl, br = bottom_pts

        # Distance helper (avoids importing math)
        def _dist(p1, p2):
            return ((p1.x() - p2.x())**2 + (p1.y() - p2.y())**2) ** 0.5

        # Compute the actual canvas dimensions without stretching
        new_w = int(max(_dist(tl, tr), _dist(bl, br)))
        new_h = int(max(_dist(tl, bl), _dist(tr, br)))

        if new_w <= 0 or new_h <= 0:
            return

        # Create a sorted source polygon (strictly clockwise)
        sorted_quad = QPolygonF([tl, tr, br, bl])

        # Explicitly define 4 destination points (same order: TL, TR, BR, BL)
        dst_quad = QPolygonF([
            QPointF(0, 0),
            QPointF(new_w, 0),
            QPointF(new_w, new_h),
            QPointF(0, new_h)
        ])

        all_layers = self._all_layers_including_quick_mask()
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
            # A perspective warp invalidates any stored text/shape anchor —
            # unlike a plain crop this isn't a pure translation, so the
            # anchor can't be corrected. Demote to plain raster so a later
            # re-edit creates a fresh layer instead of redrawing at a stale,
            # now-meaningless position.
            if getattr(layer, "text_data", None) or getattr(layer, "shape_data", None):
                self.replace_layer(layer, layer.convert_to(RasterLayer))

        # Update the document dimensions
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

        try:
            import numpy as np
            arr = _qimage_argb_view(img, writable=False)[:, :w, :]
            alpha = arr[..., 3].copy()
            rows = np.any(alpha, axis=1)
            if not np.any(rows): return QRect()
            cols = np.any(alpha, axis=0)
            rmin, rmax = np.where(rows)[0][[0, -1]]
            cmin, cmax = np.where(cols)[0][[0, -1]]
            return QRect(int(cmin), int(rmin), int(cmax - cmin + 1), int(rmax - rmin + 1))
        except Exception:
            return QRect(0, 0, w, h)

    def fit_to_artboards(self) -> bool:
        """Wrap document bounds tightly around all artboards and shift layers if they go negative."""
        bounds = None
        has_artboards = False
        for layer in self.layers:
            if getattr(layer, "layer_type", "") == "artboard" and getattr(layer, "artboard_rect", None):
                has_artboards = True
                bounds = layer.artboard_rect if bounds is None else bounds.united(layer.artboard_rect)

        if not has_artboards or bounds is None:
            return False

        shift = bounds.topLeft()
        if shift == QPoint(0, 0) and self.width == bounds.width() and self.height == bounds.height():
            return False

        for layer in self.layers:
            layer.offset = layer.offset - shift
            if getattr(layer, "layer_type", "") == "artboard" and getattr(layer, "artboard_rect", None):
                layer.artboard_rect.translate(-shift)

        self.width = bounds.width()
        self.height = bounds.height()
        self.selection = None
        return True

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
        bg = RasterLayer("Background", self.width, self.height)
        bg.image = composite
        self.layers.append(bg)
        self.active_layer_index = 0

    def save_to_imfn(self, path: str):
        from core.serialization import save_document
        save_document(self, path)

    @classmethod
    def load_from_imfn(cls, path: str):
        from core.serialization import load_document
        doc, _was_legacy = load_document(path)
        return doc

    def __repr__(self) -> str:
        return f"<Document {self.width}x{self.height} layers={len(self.layers)}>"
