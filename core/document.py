from PyQt6.QtGui import QImage, QPainter, QColor, QPainterPath, QPolygonF, QTransform
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from .layer import Layer, RasterLayer
from .render_context import CompositeContext
from core.pixel_buffer import qimage_argb_view as _qimage_argb_view

from core.app_logging import get_logger

logger = get_logger("document")



def _apply_layer_adjustment(image: QImage, layer) -> QImage:
    """An adjustment layer's effect — see core/adjustments/registry.py."""
    from core.adjustments.registry import apply_adjustment
    try:
        return apply_adjustment(image, layer.adjustment_data or {})
    except Exception:
        logger.exception("Error applying adjustment layer %r", (layer.adjustment_data or {}).get("type"))
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
        from core.gradient_model import Gradient
        g = (Gradient.from_dict(d["gradient"]) if d.get("gradient")
             else Gradient.two_color(QColor(d.get("color1", QColor(0, 0, 0))),
                                     QColor(d.get("color2", QColor(255, 255, 255)))))
        p.fillRect(img.rect(), g.brush(QRectF(img.rect()), 0.0, QTransform(), img.rect()))
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
        # Named, permanent paths (Paths panel) — same {"nodes","closed"}
        # node shape as work_path, plus "name". work_path itself stays the
        # single ephemeral, unsaved path Pen Tool draws into; "New Path"
        # promotes its current contents into an entry here and clears it.
        self.saved_paths: list[dict] = []
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
            if active.is_container:
                parent_id = getattr(active, "layer_id", None)
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

    # ── layer tree queries ────────────────────────────────────────────────
    def layer_by_id(self, layer_id) -> Layer | None:
        if not layer_id:
            return None
        return next((l for l in self.layers if l.layer_id == layer_id), None)

    def descendants(self, layer: Layer) -> list[Layer]:
        """Every layer nested under `layer` (children, grandchildren...)."""
        out, seen, stack = [], set(), [layer.layer_id]
        while stack:
            pid = stack.pop(0)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            for l in self.layers:
                if l.parent_id == pid:
                    out.append(l)
                    stack.append(l.layer_id)
        return out

    def artboards(self) -> list:
        """Artboard layers that have a rectangle."""
        from core.layer import ArtboardLayer
        return [l for l in self.layers if isinstance(l, ArtboardLayer) and l.artboard_rect]

    def enclosing_artboard(self, layer: Layer):
        """The artboard `layer` sits in (through any groups), or None."""
        from core.layer import ArtboardLayer
        seen = set()
        parent = self.layer_by_id(layer.parent_id)
        while parent is not None and parent.layer_id not in seen:
            seen.add(parent.layer_id)
            if isinstance(parent, ArtboardLayer) and parent.artboard_rect:
                return parent
            parent = self.layer_by_id(parent.parent_id)
        return None

    def next_layer_name(self, layer_cls: type, name_key: str) -> str:
        """Auto-name for a new layer: "<translated kind> <n>", n = how many
        layers of that class exist + 1."""
        from core.locale import tr
        n = sum(1 for l in self.layers if isinstance(l, layer_cls)) + 1
        return f"{tr(name_key)} {n}"

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
            if layer.has_active_styles:
                return False
        return True

    def get_composite(self, dirty_rect: QRect | None = None, respect_live_hidden: bool = True) -> QImage:
        """`respect_live_hidden=False` is the "ground truth" render used by
        anything that must never silently drop pixels — export/save,
        flatten, merge-down's adjustment-preview, the eyedropper, Image >
        Calculations. `_live_edit_hidden` is a canvas-DISPLAY-only concept:
        set while a shape layer is being dragged (ui/shape_scene_overlay.py's
        ShapeLayerItem, or MoveTool) and the drag's own preview is the only
        visible copy of it. Callers reading the document for real must see
        the actual shape, not a hole where the preview was.

        Bypasses `_composite_cache_doc` entirely rather than trying to
        make one cache serve two different results for the same document
        state — but only when something is actually hidden right now."""
        if not respect_live_hidden:
            hidden = [l for l in self.layers if getattr(l, "_live_edit_hidden", False)]
            if not hidden:
                return self.get_composite(dirty_rect)
            for l in hidden:
                l._live_edit_hidden = False
            try:
                return self._render_composite(QRect(0, 0, self.width, self.height))
            finally:
                for l in hidden:
                    l._live_edit_hidden = True

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
                    and not l.has_active_styles
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
            p2 = QPainter(result)
            p2.translate(-rect.topLeft())
            p2.drawImage(0, 0, self._quick_mask_overlay())
            p2.end()

        return result

    def _quick_mask_overlay(self) -> QImage:
        """Quick Mask's translucent red overlay at document resolution:
        black (or alpha=0) in the mask becomes red, white transparent."""
        import numpy as np
        qm = self.quick_mask_layer.image
        ptr = qm.bits(); ptr.setsize(qm.sizeInBytes())
        bpl = qm.bytesPerLine()
        arr = np.ndarray((qm.height(), bpl // 4, 4), dtype=np.uint8, buffer=ptr)[:, :self.width, :]
        gray = 0.299*arr[..., 2] + 0.587*arr[..., 1] + 0.114*arr[..., 0]
        mask_val = (255 - gray) * (arr[..., 3] / 255.0)
        alpha = (mask_val * 0.5).astype(np.uint8)
        red_img = QImage(self.width, qm.height(), QImage.Format.Format_ARGB32_Premultiplied)
        red_img.fill(0)
        r_ptr = red_img.bits(); r_ptr.setsize(red_img.sizeInBytes())
        r_arr = np.ndarray((qm.height(), red_img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=r_ptr)
        r_arr[:, :self.width, 2] = alpha  # R (premultiplied)
        r_arr[:, :self.width, 3] = alpha  # A
        del r_arr, r_ptr, arr, ptr
        return red_img

    def render_view(self, view_transform: QTransform, size) -> QImage:
        """Renders the composite straight into a viewport-sized image whose
        pixels are screen pixels: `view_transform` maps document
        coordinates to that image (zoom + pan). Pixel layers come out
        magnified exactly like the zoomed canvas shows them (nearest
        neighbour), but vector layers (VectorLayer.render_into's direct
        path) are painted *at this resolution* — that's what keeps shapes
        and Pen paths sharp at 1600% instead of showing the document-
        resolution raster blown up. Layer order, masks, clipping, blend
        modes and adjustment layers all go through the same render_into
        chain as get_composite, so nothing can end up drawn on top of a
        layer that should cover it.

        Respects `_live_edit_hidden` like the canvas composite does."""
        result = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                              view_transform.m11() < 1.0)
        painter.setTransform(view_transform)

        children_map = {}
        for layer in self.layers:
            children_map.setdefault(getattr(layer, "parent_id", None), []).append(layer)
        ctx = CompositeContext(document=self, result=result, painter=painter, children_map=children_map)
        ctx.view_transform = QTransform(view_transform)
        self._render_layer_list(children_map.get(None, []), None, ctx)
        painter = ctx.painter
        if painter.isActive():
            painter.end()

        if getattr(self, "quick_mask_layer", None) is not None:
            p2 = QPainter(result)
            p2.setTransform(view_transform)
            p2.drawImage(0, 0, self._quick_mask_overlay())
            p2.end()
        return result

    def has_vector_content(self) -> bool:
        """Whether any visible layer would look sharper in render_view than
        in the document-resolution composite — shapes, Pen paths *and*
        text (with their layer styles): every layer drawn from data."""
        return any(layer.visible and layer.sharper_when_zoomed() for layer in self.layers)

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
        if type(layer) is not RasterLayer:
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

    # ------------------------------------------------------------ Canvas size
    def resize_canvas(self, width: int, height: int, fill_color: QColor | None = None):
        """New canvas size, the image anchored at the top-left (Image >
        Canvas Size, the canvas edge handles). Layer pixels are kept, even
        beyond a smaller canvas; layers grow to cover a bigger one. An
        opaque background layer gets the new area in `fill_color` (as in
        Photoshop and Paint), every other layer leaves it transparent."""
        width, height = max(1, int(width)), max(1, int(height))
        background = self._opaque_background()
        for layer in self.layers:
            if layer.is_container or layer.image is None:
                continue
            need_w = max(layer.image.width(), width - layer.offset.x())
            need_h = max(layer.image.height(), height - layer.offset.y())
            if need_w <= layer.image.width() and need_h <= layer.image.height():
                continue
            grown = QImage(need_w, need_h, QImage.Format.Format_ARGB32_Premultiplied)
            grown.fill(fill_color if layer is background and fill_color is not None
                       else Qt.GlobalColor.transparent)
            p = QPainter(grown)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(0, 0, layer.image)
            p.end()
            layer.image = grown
        self.width, self.height = width, height
        self.invalidate_composite()

    def extend_canvas(self, left: int, top: int, right: int, bottom: int,
                      fill_color: QColor | None = None):
        """Grow (positive) or shrink (negative) the canvas on each side —
        the canvas edge handles on all four sides. Left / top changes move
        the whole document's content with them (every layer by its own
        rules, see Layer.shift_for_canvas; guides, slices, selection and
        paths too), then the size changes as in resize_canvas. An opaque
        background gets the new area in `fill_color` on every side."""
        left, top, right, bottom = int(left), int(top), int(right), int(bottom)
        width = max(1, self.width + left + right)
        height = max(1, self.height + top + bottom)
        if left or top:
            background = self._opaque_background()
            for layer in self._all_layers_including_quick_mask():
                if layer is background and left >= 0 and top >= 0:
                    self._pad_background(layer, left, top, fill_color)
                else:
                    layer.shift_for_canvas(left, top)
            self._shift_document_marks(left, top)
        self.resize_canvas(width, height, fill_color)

    @staticmethod
    def _pad_background(layer: Layer, dx: int, dy: int, fill_color: QColor | None):
        """The opaque background stays a plain full-canvas layer at (0, 0):
        its pixels move right/down inside a bigger image, the new strip in
        the background colour."""
        from core.layer import shifted_mask
        img = layer.image
        grown = QImage(img.width() + dx, img.height() + dy, QImage.Format.Format_ARGB32_Premultiplied)
        grown.fill(fill_color if fill_color is not None else Qt.GlobalColor.transparent)
        p = QPainter(grown)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(dx, dy, img)
        p.end()
        layer.image = grown
        if layer.mask is not None:
            layer.mask = shifted_mask(layer.mask, dx, dy)
        layer._shift_vector_mask(dx, dy)

    def _shift_document_marks(self, dx: int, dy: int):
        """What belongs to the document rather than a layer: guides,
        slices, the selection, the work path and saved paths."""
        from core.path_model import translate_path
        self.guides_v = [g + dx for g in self.guides_v]
        self.guides_h = [g + dy for g in self.guides_h]
        self.slices = [QRect(r).translated(dx, dy) for r in self.slices]
        if self.selection is not None:
            self.selection = self.selection.translated(dx, dy)
        translate_path(getattr(self, "work_path", None), dx, dy)
        for path in getattr(self, "saved_paths", []):
            translate_path(path, dx, dy)

    def _opaque_background(self):
        """The bottom layer when it is a plain raster layer covering the
        whole canvas with no transparency — the one a canvas extension
        fills with the background colour."""
        if not self.layers:
            return None
        layer = self.layers[0]
        if type(layer) is not RasterLayer or not layer.offset.isNull():
            return None
        img = layer.image
        if img is None or img.width() < self.width or img.height() < self.height:
            return None
        arr = _qimage_argb_view(img, writable=False)[:self.height, :self.width, 3]
        return layer if arr.min() == 255 else None

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
        # Vector masks (and a Pen layer's path, which lives in vector_mask)
        # are document-space too; without this they stayed at their
        # pre-crop position while everything else moved.
        vm = getattr(layer, "vector_mask", None)
        if vm is not None and not vm.isEmpty():
            layer.vector_mask = vm.translated(shift.x(), shift.y())

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
        artboards = self.artboards()
        if not artboards:
            return False
        bounds = artboards[0].artboard_rect
        for a in artboards[1:]:
            bounds = bounds.united(a.artboard_rect)

        shift = bounds.topLeft()
        if shift == QPoint(0, 0) and self.width == bounds.width() and self.height == bounds.height():
            return False

        for layer in self.layers:
            layer.offset = layer.offset - shift
        for a in artboards:
            a.artboard_rect.translate(-shift)

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
        composite = self.get_composite(respect_live_hidden=False)
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
