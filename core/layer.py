import math
from PyQt6.QtGui import QImage, QColor, QPainterPath, QPainter, QPen, QTransform
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QBuffer, QIODevice, QByteArray
import uuid
from typing import TYPE_CHECKING

from core.shape_model import ShapeSpec, ShapeAppearance, combine_paths

if TYPE_CHECKING:
    from core.render_context import CompositeContext


def _img_to_bytes(img: QImage | None):
    if not img or img.isNull():
        return None
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return ba.data()


def _bytes_to_img(b) -> QImage | None:
    if not b:
        return None
    img = QImage()
    img.loadFromData(b, "PNG")
    return img


class Layer:
    """Represents a single layer in the document.

    Subclasses (RasterLayer, TextLayer, VectorLayer, AdjustmentLayer,
    FillLayer, SmartObjectLayer, GroupLayer, ArtboardLayer, FrameLayer)
    each own only the field(s) relevant to their kind and set `_LAYER_TAG`
    — the string written to `.imfn` files and returned by the read-only
    `layer_type` property below. `layer_type` has no setter on purpose: a
    layer's kind is its class, not a flag that can drift out of sync with
    it; code that needs to change a layer's kind must build a new instance
    of the target subclass (see `Document.replace_layer`).

    Universal fields and the copy()/to_dict()/from_dict() machinery live
    here; each subclass extends them through the three
    `_copy_extra`/`_to_dict_extra`/`_from_dict_extra` hooks instead of
    overriding the whole method, so adding a new layer type never means
    touching this class or duplicating the universal-field handling.
    """

    BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay"]

    _LAYER_TAG = "raster"

    @property
    def layer_type(self) -> str:
        return self._LAYER_TAG

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        self.name = name
        self.layer_id = str(uuid.uuid4())
        self.parent_id: str | None = None
        self.expanded: bool = True
        self.link_id: str | None = None
        self.visible: bool = True
        self.locked: bool = False
        self.lock_alpha: bool = False
        self.lock_pixels: bool = False
        self.lock_position: bool = False
        self.lock_artboard: bool = False
        self.mask: QImage | None = None
        self.mask_enabled: bool = True
        self.editing_mask: bool = False
        self.vector_mask: QPainterPath | None = None
        self.vector_mask_enabled: bool = True
        self.clipping: bool = False
        self.is_quick_mask: bool = False
        self.opacity: float = 1.0
        self.blend_mode: str = "Normal"
        self.offset: QPoint = QPoint(0, 0)

        self.image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        if fill_color:
            self.image.fill(fill_color)
        else:
            self.image.fill(Qt.GlobalColor.transparent)

        self.layer_styles: dict | None = None     # layer styles / blending options

    # ------------------------------------------------------------- Extension hooks
    def _copy_extra(self, clone: "Layer", deep_image: bool) -> None:
        """Subclasses copy their own extra field(s) onto `clone` here."""

    def _to_dict_extra(self, d: dict) -> None:
        """Subclasses add their own extra field(s) to `d` here."""

    def _from_dict_extra(self, d: dict) -> None:
        """Subclasses restore their own extra field(s) from `d` here."""

    # --------------------------------------------------------- Compositing hooks
    # `_is_container`: True for layer kinds that hold children
    # (GroupLayer, ArtboardLayer) instead of drawing pixels of their own —
    # `Document._render_layer_list` uses it to skip the "clipped layer with
    # no base to clip against" gate, which only makes sense for pixel layers.
    _is_container = False

    # `_PIXEL_ACCESS`: can pixel commands (filters, Image > Adjustments)
    # work on this layer's `image`?
    #   "direct"    — yes, `image` is what the layer shows (raster, smart
    #                 object, frame);
    #   "rasterize" — the layer is drawn from data (text, shapes, fill) and
    #                 `image` is only a baked copy, so an edit there would
    #                 never show: it has to be rasterized first;
    #   "none"      — no pixels of its own (adjustment layers, containers).
    _PIXEL_ACCESS = "direct"

    @property
    def pixel_access(self) -> str:
        return "none" if self._is_container else self._PIXEL_ACCESS

    def pixel_access_for(self, op: str) -> str:
        """`pixel_access` for one kind of pixel operation: "filter" (Filter
        menu, Image > Adjustments), "paint" (brush-like tools) or
        "transform" (warps). Same answer for all three except where a layer
        kind says otherwise (smart objects take filters but not paint)."""
        return self.pixel_access

    def content_image(self, document) -> QImage:
        """What the layer looks like, as pixels at its own size/offset —
        also for layers drawn from data (fill layers render on demand)."""
        return self._get_source_image(document)

    # `_move_tool_uniform_scale_only`: True forbids MoveTool free (per-axis)
    # resize — edge handles are hidden and corner handles always scale with
    # locked aspect ratio, as if Shift were held. Text: independent width/
    # height stretch distorts glyphs; resizing text is meant to go through
    # font-size, not a bounding-box drag.
    _move_tool_uniform_scale_only = False

    def _get_source_image(self, document) -> QImage:
        """The pixels this layer contributes before stroke/style/mask are
        applied. Overridden by `FillLayer`, which has no `self.image` of its
        own and renders its fill on demand at document size."""
        return self.image

    def render_into(self, ctx: "CompositeContext", layer_artboard_rect, is_clipping: bool, next_clipping: bool) -> None:
        """Draw this layer into `ctx.painter` (or, for `AdjustmentLayer`,
        directly into `ctx.result`'s pixels) as part of
        `Document._render_composite`. This default handles every layer kind
        that is "a rectangle of pixels drawn with the normal blend/opacity/
        mask/clip machinery" — raster, text, vector, smart-object and (via
        `_get_source_image`) fill. `AdjustmentLayer`, `FrameLayer`,
        `GroupLayer` and `ArtboardLayer` override this wholesale; they don't
        fit the "draw pixels" shape at all.
        """
        from core.blend_modes import composition_mode as _get_composition_mode
        from core.pixel_buffer import (ensure_owned_copy as _ensure_owned_copy,
                                       qimage_argb_view as _qimage_argb_view,
                                       shift_pixels_edge as _shift_pixels_edge)
        from core.document import _composite_active_stroke
        import numpy as np

        document = ctx.document
        painter = ctx.painter
        img_to_draw = self._get_source_image(document)

        active_stroke = getattr(self, "active_stroke", None)
        if active_stroke and not getattr(self, "editing_mask", False):
            stroke_img = active_stroke["img"]
            offset_style = (getattr(self, "layer_styles", None) or {}).get("offset", {})
            if offset_style.get("enabled"):
                dx_pct = offset_style.get("dx_pct", 0)
                dy_pct = offset_style.get("dy_pct", 0)
                edge_mode = offset_style.get("edge_mode", "wrap")
                if dx_pct != 0 or dy_pct != 0:
                    h, w = stroke_img.height(), stroke_img.width()
                    dx = -int(w * dx_pct / 100.0)
                    dy = -int(h * dy_pct / 100.0)
                    arr = _qimage_argb_view(stroke_img, writable=False)
                    res_arr = _shift_pixels_edge(arr, w, h, dx, dy, edge_mode)
                    stroke_img = QImage(res_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied)
                    stroke_img.ndarray = res_arr

            img_to_draw = _ensure_owned_copy(img_to_draw)
            _composite_active_stroke(img_to_draw, stroke_img, active_stroke, self.offset)

        current_offset = self.offset
        if getattr(self, "layer_styles", None):
            from core.layer_styles import apply_layer_styles
            # Styles (shadows, glows, bevel) are expensive; reuse the
            # rendered result until the source pixels or the style settings
            # change. cacheKey() covers the pixels, the JSON fingerprint
            # covers the settings.
            fp = None
            try:
                import json
                from core.serialization import encode_qt
                fp = json.dumps(encode_qt(self.layer_styles), sort_keys=True, default=str)
            except Exception:
                pass
            cache_key = (img_to_draw.cacheKey(), fp)
            cached = getattr(self, "_style_cache", None)
            if fp is not None and cached is not None and cached[0] == cache_key:
                # Fresh QImage instance: shares pixels COW and has no
                # is_copy mark, so later pipeline stages copy before
                # painting instead of mutating the cache.
                img_to_draw = QImage(cached[1])
                offset_delta = cached[2]
            else:
                src_is_layer_image = img_to_draw is self.image
                img_to_draw, offset_delta = apply_layer_styles(img_to_draw, self.layer_styles)
                if fp is not None and src_is_layer_image:
                    self._style_cache = (cache_key, img_to_draw, offset_delta)
            current_offset = current_offset + offset_delta

            # Apply the Offset style
            offset_style = self.layer_styles.get("offset", {})
            if offset_style.get("enabled"):
                dx_pct = offset_style.get("dx_pct", 0)
                dy_pct = offset_style.get("dy_pct", 0)
                edge_mode = offset_style.get("edge_mode", "wrap")
                if dx_pct != 0 or dy_pct != 0:
                    h, w = img_to_draw.height(), img_to_draw.width()
                    dx = int(w * dx_pct / 100.0)
                    dy = int(h * dy_pct / 100.0)
                    arr = _qimage_argb_view(img_to_draw, writable=False)
                    res_arr = _shift_pixels_edge(arr, w, h, dx, dy, edge_mode)
                    img_to_draw = QImage(res_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
                    img_to_draw.is_copy = True

        has_mask = getattr(self, "mask", None) is not None and getattr(self, "mask_enabled", True)

        if (has_mask or is_clipping) and not getattr(img_to_draw, "is_copy", False):
            img_to_draw = img_to_draw.copy()
            img_to_draw.is_copy = True

        if has_mask or is_clipping:
            arr_full = _qimage_argb_view(img_to_draw, writable=True)
            arr = arr_full[:, :img_to_draw.width(), :]

            if has_mask:
                current_mask = self.mask
                active_stroke = getattr(self, "active_stroke", None)
                if active_stroke and getattr(self, "editing_mask", False):
                    current_mask = current_mask.copy()
                    _composite_active_stroke(current_mask, active_stroke["img"], active_stroke, self.offset)

                m_arr = _qimage_argb_view(current_mask, writable=False)[:, :img_to_draw.width(), :]
                mask_f = m_arr[..., 1].astype(np.float32) / 255.0
                arr[:] = (arr.astype(np.float32) * mask_f[..., np.newaxis]).astype(np.uint8)

            if is_clipping:
                ox, oy = self.offset.x(), self.offset.y()
                w, h = img_to_draw.width(), img_to_draw.height()
                dx1, dy1 = max(0, ox), max(0, oy)
                dx2, dy2 = min(document.width, ox + w), min(document.height, oy + h)

                clip_mask = np.zeros((h, w), dtype=np.float32)
                if ctx.clip_alpha is not None and dx1 < dx2 and dy1 < dy2:
                    sx1, sy1 = dx1 - ox, dy1 - oy
                    sx2, sy2 = sx1 + (dx2 - dx1), sy1 + (dy2 - dy1)
                    clip_mask[sy1:sy2, sx1:sx2] = ctx.clip_alpha[dy1:dy2, dx1:dx2]

                arr[:] = (arr.astype(np.float32) * clip_mask[..., np.newaxis]).astype(np.uint8)

        if not is_clipping and next_clipping:
            base_alpha_img = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
            base_alpha_img.fill(0)
            ap = QPainter(base_alpha_img)
            clip_path = self._render_clip_path()
            if clip_path is not None:
                ap.setClipPath(clip_path)
            ap.setOpacity(self.opacity)
            ap.drawImage(self.offset, img_to_draw)
            ap.end()

            arr_alpha = _qimage_argb_view(base_alpha_img, writable=False)
            ctx.clip_alpha = arr_alpha[:, :document.width, 3].astype(np.float32).copy() / 255.0
        elif not is_clipping:
            ctx.clip_alpha = None

        painter.save()
        if layer_artboard_rect:
            painter.setClipRect(layer_artboard_rect)

        clip_path = self._render_clip_path()
        if clip_path is not None:
            painter.setClipPath(clip_path, Qt.ClipOperation.IntersectClip)
        painter.setCompositionMode(_get_composition_mode(getattr(self, "blend_mode", "SourceOver")))
        painter.setOpacity(self.opacity)
        painter.drawImage(current_offset, img_to_draw)
        painter.restore()

    def _render_clip_path(self):
        """The vector mask the composite clips this layer to, or None.
        Overridden by VectorLayer: for a Pen Tool layer `vector_mask` is
        the shape itself, not a mask on top of it."""
        if getattr(self, "vector_mask", None) is not None and getattr(self, "vector_mask_enabled", True):
            return self.vector_mask
        return None

    # ------------------------------------------------------------------
    def copy(self, deep_image: bool = True) -> "Layer":
        """Copy layer. When *deep_image* is False the QImage is shared (faster
        for undo snapshots of layers that won't be modified)."""
        clone = type(self).__new__(type(self))
        self._copy_universal_into(clone, deep_image)
        self._copy_extra(clone, deep_image)
        return clone

    def convert_to(self, target_cls: type, deep_image: bool = True) -> "Layer":
        """Build a `target_cls` instance carrying over this layer's universal
        fields (image, mask, opacity, blend_mode, offset, ...) but none of
        its type-specific extra data. Use this — never a `layer_type`
        assignment — whenever an operation invalidates a layer's kind
        (apply-mask, perspective-warp, rasterize, convert-to-smart-object):
        a layer's kind is its class now, so changing it means building a
        new instance, then splicing it in via `Document.replace_layer`."""
        new_layer = target_cls.__new__(target_cls)
        self._copy_universal_into(new_layer, deep_image)
        return new_layer

    def _copy_universal_into(self, clone: "Layer", deep_image: bool) -> None:
        clone.name = self.name
        clone.layer_id = getattr(self, "layer_id", str(uuid.uuid4()))
        clone.parent_id = getattr(self, "parent_id", None)
        clone.expanded = getattr(self, "expanded", True)
        clone.link_id = getattr(self, "link_id", None)
        clone.visible = self.visible
        clone.locked = self.locked
        clone.lock_alpha = getattr(self, "lock_alpha", False)
        clone.lock_pixels = getattr(self, "lock_pixels", False)
        clone.lock_position = getattr(self, "lock_position", False)
        clone.lock_artboard = getattr(self, "lock_artboard", False)
        if getattr(self, "mask", None) is not None:
            # QImage(other) shares pixel data copy-on-write: later in-place
            # painting on either side detaches, so snapshots stay intact.
            clone.mask = self.mask.copy() if deep_image else QImage(self.mask)
        else:
            clone.mask = None
        clone.mask_enabled = getattr(self, "mask_enabled", True)
        clone.editing_mask = getattr(self, "editing_mask", False)
        if getattr(self, "vector_mask", None) is not None:
            clone.vector_mask = QPainterPath(self.vector_mask)
        else:
            clone.vector_mask = None
        clone.vector_mask_enabled = getattr(self, "vector_mask_enabled", True)
        clone.clipping = getattr(self, "clipping", False)
        clone.is_quick_mask = getattr(self, "is_quick_mask", False)
        clone.opacity = self.opacity
        clone.blend_mode = self.blend_mode
        clone.offset = QPoint(self.offset)
        clone.image = self.image.copy() if deep_image else QImage(self.image)

        import copy as _copy_mod
        clone.layer_styles = _copy_mod.deepcopy(getattr(self, "layer_styles", None))

    def to_dict(self):
        d = {
            "name": self.name,
            "layer_id": getattr(self, "layer_id", None),
            "parent_id": getattr(self, "parent_id", None),
            "link_id": getattr(self, "link_id", None),
            "layer_type": self.layer_type,
            "visible": self.visible,
            "locked": self.locked,
            "lock_alpha": getattr(self, "lock_alpha", False),
            "lock_pixels": getattr(self, "lock_pixels", False),
            "lock_position": getattr(self, "lock_position", False),
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "offset": (self.offset.x(), self.offset.y()),
            "image": _img_to_bytes(self.image),
            "mask": _img_to_bytes(self.mask),
            "mask_enabled": getattr(self, "mask_enabled", True),
            "layer_styles": getattr(self, "layer_styles", None),
            "clipping": getattr(self, "clipping", False),
            "expanded": getattr(self, "expanded", True),
            "vector_mask": getattr(self, "vector_mask", None),
            "vector_mask_enabled": getattr(self, "vector_mask_enabled", True),
        }
        self._to_dict_extra(d)
        return d

    @classmethod
    def from_dict(cls, d, w, h):
        layer = cls(d["name"], w, h)
        if d.get("layer_id"):
            layer.layer_id = d["layer_id"]
        layer.parent_id = d.get("parent_id", None)
        layer.link_id = d.get("link_id", None)
        layer.visible = d.get("visible", True)
        layer.locked = d.get("locked", False)
        layer.lock_alpha = d.get("lock_alpha", False)
        layer.lock_pixels = d.get("lock_pixels", False)
        layer.lock_position = d.get("lock_position", False)
        layer.opacity = d.get("opacity", 1.0)
        layer.blend_mode = d.get("blend_mode", "Normal")
        layer.clipping = d.get("clipping", False)
        layer.expanded = d.get("expanded", True)
        ox, oy = d.get("offset", (0, 0))
        layer.offset = QPoint(ox, oy)

        img = _bytes_to_img(d.get("image"))
        if img:
            layer.image = img

        layer.mask = _bytes_to_img(d.get("mask"))
        layer.mask_enabled = d.get("mask_enabled", True)
        layer.layer_styles = d.get("layer_styles", None)
        layer.vector_mask = d.get("vector_mask", None)
        layer.vector_mask_enabled = d.get("vector_mask_enabled", True)

        layer._from_dict_extra(d)
        return layer

    def width(self) -> int:
        return self.image.width()

    def height(self) -> int:
        return self.image.height()

    # ------------------------------------------------------------- Move-tool hooks
    # `tools/move_tool.py` used to dispatch on `layer_type == "artboard"/
    # "frame"/"text"/"group"` in four separate places (bounds setup, apply,
    # cancel, numeric transform-params). These hooks replace that the same
    # way `render_into` replaced the composite-render dispatch: each hook
    # has a default that covers plain pixel layers (raster/text/vector/
    # smart-object), and the few layer kinds with their own idea of
    # "bounds"/"commit"/"cancel" override just that hook.
    def move_tool_bounds(self) -> QRectF:
        """Document-space rect MoveTool treats as this layer's outline
        (handles are drawn on it, and it seeds `_original_rect`)."""
        from core.document import Document
        br = Document._nontransparent_bounds(self.image)
        if br.isEmpty():
            return QRectF(self.offset.x(), self.offset.y(), self.width(), self.height())
        return QRectF(br).translated(QPointF(self.offset))

    def move_tool_container_bounds(self, linked_children: list[dict]) -> QRectF:
        """Bounds for a container layer (`_is_container`), computed from
        its already-collected linked descendants instead of its own pixels.
        Never called on non-container layers."""
        raise NotImplementedError

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        """Commit any layer-kind-specific geometry (artboard_rect,
        frame_data rect, text position) as part of `MoveTool.apply_transform`.
        Returns True if this fully handled the commit — the generic pixel
        transform below should be skipped entirely (artboard/group/text);
        False if the generic pixel commit should still run afterward too
        (the default, and `FrameLayer`, which needs both)."""
        return False

    def move_tool_cancel_extra(self, original_rect) -> None:
        """Restore any layer-kind-specific geometry as part of
        `MoveTool.cancel_transform`. Default: nothing extra to restore."""

    def move_tool_set_params_extra(self, final_transform, original_rect) -> bool:
        """Live-preview equivalent of `move_tool_apply_extra`, used while
        the Transform panel's numeric fields are being edited (no commit,
        no `fit_to_artboards`, no re-render — just the rect). Returns True
        if handled, so the caller skips its own floating-selection-outline
        update (mutually exclusive: only a plain raster/vector layer with
        an active selection is ever floating). Default: not handled."""
        return False

    def __repr__(self) -> str:
        return f"<{type(self).__name__} '{self.name}' {self.width()}x{self.height()} visible={self.visible}>"


class RasterLayer(Layer):
    """Plain pixel layer — the default/fallback layer kind. No extra fields."""


def decompose_transform(t: "QTransform") -> tuple[float, float, float]:
    """Decomposes an affine QTransform built from translate+rotate+scale
    only (MoveTool's drag/resize transforms — no shear) into
    (scale_x, scale_y, angle_degrees). Single source of truth for this
    formula — used to be duplicated between TextLayer.move_tool_apply_extra,
    VectorLayer's shape_data equivalent, and MoveTool.get_transform_params's
    own numeric Transform-panel readout."""
    import math
    m11, m12, m21, m22 = t.m11(), t.m12(), t.m21(), t.m22()
    scale_x = math.hypot(m11, m12)
    angle = math.degrees(math.atan2(m12, m11))
    det = m11 * m22 - m12 * m21
    scale_y = det / scale_x if scale_x != 0 else math.hypot(m21, m22)
    return scale_x, scale_y, angle


def transform_shape_rect(rect: QRectF, angle: float, transform) -> tuple[QRectF, float]:
    """Applies a MoveTool drag/resize transform to a shape_data-style
    axis-aligned rect + angle pair, returning the new (rect, angle).
    Shared by VectorLayer.move_tool_apply_extra's shape_data commit and
    MoveTool's live shape_data drag preview (tools/move_tool.py::
    floating_preview / ui/overlay_renderers.py::draw_transform_preview) —
    both need the exact same "where does this shape end up" math, one to
    commit it, one to draw it a frame earlier."""
    new_center = transform.map(rect.center())
    scale_x, scale_y, delta_angle = decompose_transform(transform)
    new_rect = QRectF(0, 0, rect.width() * scale_x, rect.height() * scale_y)
    new_rect.moveCenter(new_center)
    return new_rect, (angle + delta_angle) % 360


class LiveRenderedLayer(Layer):
    _live_edit_hidden = False   # class default: clones made via __new__ skip __init__
    _PIXEL_ACCESS = "rasterize"

    """A layer whose pixels are a rendering of data (shape geometry, text)
    rather than stored pixels. Subclasses implement `has_live_content()`,
    `paint_content(painter)` (document coordinates, at whatever resolution
    the painter's transform implies) and `content_bounds()`.

    Compositing paints the content directly at the target's resolution
    (`_render_direct`) — sharp at any zoom in Document.render_view — and
    only falls back to the document-resolution raster pipeline for what is
    inherently pixel-based (layer styles, an in-progress brush stroke).
    `self.image` is just a baked copy for the Layers-panel thumbnail,
    merge-down and rasterize."""

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        # Transient, never serialized: True while something else (a drag
        # preview, the text editor) is the only visible copy of this layer.
        self._live_edit_hidden = False

    def has_live_content(self) -> bool:
        raise NotImplementedError

    def paint_content(self, painter: QPainter) -> None:
        raise NotImplementedError

    def content_bounds(self) -> QRectF:
        raise NotImplementedError

    def _get_source_image(self, document) -> QImage:
        """Document-resolution raster of the geometry — only used when the
        raster pipeline is needed (mask, layer styles, clipping, a clip
        base for the layer above); otherwise render_into paints directly."""
        if self._live_edit_hidden or not self.has_live_content():
            if self._live_edit_hidden:
                img = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.transparent)
                img.is_copy = True
                return img
            return super()._get_source_image(document)
        img = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The base pipeline draws the source at self.offset; paint_content
        # works in document coordinates, so cancel it here.
        painter.translate(-self.offset.x(), -self.offset.y())
        self.paint_content(painter)
        painter.end()
        img.is_copy = True
        return img

    def _needs_raster_pipeline(self, is_clipping: bool) -> bool:
        """Only an in-progress brush stroke on the layer needs the
        document-resolution pixel pipeline (Layer.render_into); masks,
        clipping, blend, opacity and layer styles are all applied by
        _render_direct on a render of the content at the target's own
        resolution."""
        return bool(getattr(self, "active_stroke", None))

    def _has_pixel_mask(self) -> bool:
        return getattr(self, "mask", None) is not None and getattr(self, "mask_enabled", True)

    def _doc_coverage(self, document, clip_alpha):
        """Document-space float coverage from the layer mask (layer-local,
        placed at self.offset) times the clipping base's alpha, or None
        when neither applies."""
        import numpy as np
        from core.pixel_buffer import qimage_argb_view as _qimage_argb_view
        cov = None
        if self._has_pixel_mask():
            cov = np.zeros((document.height, document.width), dtype=np.float32)
            m = _qimage_argb_view(self.mask, writable=False)
            ox, oy = self.offset.x(), self.offset.y()
            mh, mw = self.mask.height(), self.mask.width()
            x1, y1 = max(0, ox), max(0, oy)
            x2, y2 = min(document.width, ox + mw), min(document.height, oy + mh)
            if x1 < x2 and y1 < y2:
                cov[y1:y2, x1:x2] = m[y1 - oy:y2 - oy, x1 - ox:x2 - ox, 1].astype(np.float32) / 255.0
        if clip_alpha is not None:
            cov = clip_alpha.copy() if cov is None else cov * clip_alpha
        return cov

    # ── MoveTool ────────────────────────────────────────────────────
    # The geometry change is one method (apply_move_geometry); the commit
    # and the live drag preview both use it, so the preview is exactly
    # what releasing the mouse will produce.
    def apply_move_geometry(self, transform: QTransform) -> None:
        raise NotImplementedError

    def move_preview(self, transform: QTransform) -> "LiveRenderedLayer":
        """A lightweight copy with `transform` applied — painted by
        MoveTool's drag preview (ui/overlay_renderers.py)."""
        clone = self.copy(deep_image=False)
        clone.apply_move_geometry(transform)
        return clone

    def _thumbnail_canvas_for_move(self, original_img: QImage) -> None:
        """Called before re-baking after a move (MoveTool swapped .image for
        a 1x1 placeholder during the drag)."""

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        if not self.has_live_content():
            return super().move_tool_apply_extra(doc, final_transform, original_rect, original_img)
        self.apply_move_geometry(final_transform)
        self._thumbnail_canvas_for_move(original_img)
        self.rebake_thumbnail()
        return True

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        if self._live_edit_hidden:
            # A drag (MoveTool, ShapeLayerItem) or the text editor's fast
            # typing mode is the only visible representation right now.
            if not is_clipping:
                ctx.clip_alpha = None
            return
        if not self.has_live_content() or self._needs_raster_pipeline(is_clipping):
            super().render_into(ctx, layer_artboard_rect, is_clipping, next_clipping)
            return
        self._render_direct(ctx, layer_artboard_rect, is_clipping, next_clipping)

    def render_layer_image(self, to_device: QTransform, device_rect: QRect):
        """The layer's own pixels (content + layer styles) rendered through
        `to_device` (document -> target pixels), limited to what can affect
        `device_rect`. Returns (image, device top-left) or (None, None).

        Layer styles are applied here at the target resolution, with their
        pixel sizes scaled to match — so a shadowed or stroked shape/text
        stays sharp in a zoomed view instead of being a magnified
        document-resolution bitmap. Gradient/pattern overlays span the
        layer's full content frame even when only part of it is rendered."""
        styles = getattr(self, "layer_styles", None) or None
        scale = math.sqrt(abs(to_device.determinant())) or 1.0
        frame = to_device.mapRect(self.content_bounds())
        reach = 0
        if styles:
            from core.layer_styles import layer_styles_padding, scale_layer_styles
            styles = scale_layer_styles(styles, scale)
            reach = layer_styles_padding(styles)
        area = frame.toAlignedRect().adjusted(-1, -1, 1, 1)
        area = area.intersected(device_rect.adjusted(-reach, -reach, reach, reach))
        if area.isEmpty():
            return None, None
        img = QImage(area.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(to_device * QTransform.fromTranslate(-area.x(), -area.y()))
        self.paint_content(p)
        p.end()
        top_left = area.topLeft()
        if styles:
            from core.layer_styles import apply_layer_styles
            img, delta = apply_layer_styles(img, styles, frame.translated(-area.x(), -area.y()))
            top_left = top_left + delta
            offset_style = styles.get("offset", {})
            if offset_style.get("enabled") and (offset_style.get("dx_pct") or offset_style.get("dy_pct")):
                from core.pixel_buffer import qimage_argb_view as _qimage_argb_view, shift_pixels_edge as _shift_pixels_edge
                w, h = img.width(), img.height()
                arr = _qimage_argb_view(img, writable=False)
                shifted = _shift_pixels_edge(arr, w, h, int(w * offset_style.get("dx_pct", 0) / 100.0),
                                             int(h * offset_style.get("dy_pct", 0) / 100.0),
                                             offset_style.get("edge_mode", "wrap"))
                img = QImage(shifted.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        return img, top_left

    def _render_direct(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        """Composites the layer at the target's resolution — the
        composite's own device pixels, whether that's document resolution
        or Document.render_view's zoomed viewport. That's what keeps shapes
        and text (and their layer styles) sharp at any zoom. Rendered into
        a temporary first so opacity and blend mode apply to the layer as a
        whole, exactly like a pixel layer."""
        from core.blend_modes import composition_mode as _get_composition_mode
        from core.pixel_buffer import qimage_argb_view as _qimage_argb_view
        import numpy as np
        painter = ctx.painter
        document = ctx.document

        # Mask and (when this layer is clipped onto the one below) the
        # clip base's alpha, in document space.
        coverage = self._doc_coverage(document, ctx.clip_alpha if is_clipping else None)

        if not is_clipping:
            if next_clipping:
                # The layer above clips to this one: it needs this layer's
                # alpha at document resolution, same as Layer.render_into.
                base_alpha = QImage(document.width, document.height, QImage.Format.Format_ARGB32_Premultiplied)
                base_alpha.fill(0)
                doc_img, doc_pos = self.render_layer_image(QTransform(), base_alpha.rect())
                if doc_img is not None:
                    ap = QPainter(base_alpha)
                    clip_path = self._render_clip_path()
                    if clip_path is not None:
                        ap.setClipPath(clip_path)
                    ap.setOpacity(self.opacity)
                    ap.drawImage(doc_pos, doc_img)
                    ap.end()
                arr = _qimage_argb_view(base_alpha, writable=False)
                alpha = arr[:, :document.width, 3].astype(np.float32) / 255.0
                ctx.clip_alpha = alpha * coverage if coverage is not None else alpha.copy()
            else:
                ctx.clip_alpha = None

        to_device = painter.transform()
        device = painter.device()
        tmp, top_left = self.render_layer_image(to_device, QRect(0, 0, device.width(), device.height()))
        if tmp is None:
            return

        if coverage is not None:
            smooth = painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            local = to_device * QTransform.fromTranslate(-top_left.x(), -top_left.y())
            cov = _resample_coverage(coverage, local, tmp.width(), tmp.height(), smooth)
            tarr = _qimage_argb_view(tmp, writable=True)
            w = tmp.width()
            tarr[:, :w, :] = (tarr[:, :w, :].astype(np.float32) * cov[..., np.newaxis]).astype(np.uint8)
            del tarr

        painter.save()
        if layer_artboard_rect:
            painter.setClipRect(layer_artboard_rect, Qt.ClipOperation.IntersectClip)
        clip_path = self._render_clip_path()
        if clip_path is not None:
            painter.setClipPath(clip_path, Qt.ClipOperation.IntersectClip)
        painter.setCompositionMode(_get_composition_mode(getattr(self, "blend_mode", "SourceOver")))
        painter.setOpacity(self.opacity)
        painter.setTransform(QTransform())
        painter.drawImage(top_left, tmp)
        painter.restore()


class TextLayer(LiveRenderedLayer):
    """Text as data (`text_data`, see core/text_model.py::TextData),
    rendered live as glyph outlines (core/text_engine.py) — sharp at any
    zoom, re-laid-out whenever the data changes, never a stale bitmap.
    `self.image` is a tight bake (at `self.offset`) for the thumbnail,
    merge-down, rasterize and MoveTool's drag preview."""
    _LAYER_TAG = "text"
    _move_tool_uniform_scale_only = True
    # Class defaults: convert_to()/copy() build instances via __new__.
    text_data = None
    _layout_cache = None

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.text_data: dict | None = None
        self._layout_cache = None

    def _copy_extra(self, clone, deep_image):
        import copy
        clone.text_data = copy.deepcopy(self.text_data) if self.text_data else None
        clone._layout_cache = None

    def _to_dict_extra(self, d):
        d["text_data"] = self.text_data

    def _from_dict_extra(self, d):
        self.text_data = d.get("text_data")
        self._layout_cache = None

    # ── data + layout ───────────────────────────────────────────────
    def _cached(self):
        if not self.text_data:
            return None
        import json
        key = json.dumps(self.text_data, sort_keys=True, default=str)
        cache = getattr(self, "_layout_cache", None)
        if cache is None or cache[0] != key:
            from core.text_model import TextData
            from core.text_engine import layout_text
            data = TextData.from_dict(self.text_data)
            cache = (key, data, layout_text(data))
            self._layout_cache = cache
        return cache

    def data(self):
        """A fresh TextData copy (edit it, then set_data)."""
        c = self._cached()
        return c[1].copy() if c else None

    def set_data(self, data) -> None:
        self.text_data = data.to_dict()

    def text_layout(self):
        c = self._cached()
        return c[2] if c else None

    def text_transform(self) -> QTransform:
        from core.text_engine import text_transform
        c = self._cached()
        return text_transform(c[1]) if c else QTransform()

    def frame_polygon(self):
        """The text's frame (point text: its lines; paragraph text: its
        box) in document coordinates — rotated with the text."""
        from PyQt6.QtGui import QPolygonF
        lay = self.text_layout()
        if lay is None:
            return QPolygonF()
        return self.text_transform().map(QPolygonF(lay.bounds()))

    def contains_doc_point(self, pt: QPointF, tolerance: float = 4.0) -> bool:
        lay = self.text_layout()
        if lay is None:
            return False
        inv, ok = self.text_transform().inverted()
        if not ok:
            return False
        local = inv.map(QPointF(pt))
        r = lay.bounds().united(lay.ink_bounds()).adjusted(-tolerance, -tolerance, tolerance, tolerance)
        return r.contains(local)

    # ── LiveRenderedLayer ───────────────────────────────────────────
    def has_live_content(self) -> bool:
        c = self._cached()
        return bool(c and c[1].text)

    def paint_content(self, painter: QPainter) -> None:
        c = self._cached()
        if not c:
            return
        from core.text_engine import paint_text, text_transform
        painter.save()
        painter.setTransform(text_transform(c[1]), combine=True)
        paint_text(painter, c[1], c[2])
        painter.restore()

    def content_bounds(self) -> QRectF:
        c = self._cached()
        if not c:
            return QRectF()
        from core.text_engine import effects_padding, text_transform
        e = c[1].effects
        r = c[2].ink_bounds().united(c[2].bounds())
        if e.shadow:
            r = r.united(r.translated(e.shadow_dx, e.shadow_dy))
        pad = effects_padding(c[1])
        return text_transform(c[1]).mapRect(r.adjusted(-pad, -pad, pad, pad))

    def rebake_thumbnail(self) -> None:
        """Tight bake: the image covers just the text, placed at offset
        (the text's own position lives in text_data, not in the offset)."""
        bounds = self.content_bounds().toAlignedRect() if self.has_live_content() else QRect(0, 0, 1, 1)
        img = QImage(max(1, bounds.width()), max(1, bounds.height()), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        if self.has_live_content():
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.translate(-bounds.x(), -bounds.y())
            self.paint_content(p)
            p.end()
        self.image = img
        self.offset = bounds.topLeft()

    # ── MoveTool ────────────────────────────────────────────────────
    def move_tool_bounds(self) -> QRectF:
        if not self.has_live_content():
            return super().move_tool_bounds()
        return self.frame_polygon().boundingRect().united(self.content_bounds())

    def apply_move_geometry(self, transform: QTransform) -> None:
        data = self.data()
        if data is None:
            return
        new_pt = transform.map(QPointF(data.x, data.y))
        sx, sy, delta_angle = decompose_transform(transform)
        k = (abs(sx) + abs(sy)) / 2
        if abs(k - 1.0) > 1e-3:
            # Text resizes by font size (uniform-only, see
            # _move_tool_uniform_scale_only), never by stretching glyphs.
            data.scale_sizes(k)
        data.x, data.y = new_pt.x(), new_pt.y()
        data.angle = (data.angle + delta_angle) % 360
        self.set_data(data)


def paint_path_style(painter: QPainter, path: QPainterPath, path_style: dict) -> None:
    """Fill/stroke a Pen Tool path per its path_style dict — through the
    same ShapeAppearance renderer shape_data layers use, so both kinds of
    vector layer support the same fill/stroke options and stay sharp at
    any zoom (painting happens in device space)."""
    ShapeAppearance.from_path_style(path_style).paint(painter, path, closed=True)


class VectorLayer(LiveRenderedLayer):
    """Two independent ways a layer ends up "vector": `shape_data`
    (ShapesTool's rect/ellipse/polygon/... primitives) and `path_style` +
    `Layer.vector_mask` (Pen Tool's true bezier path). Both are live now —
    `_get_source_image` renders straight from `shape_data`/`vector_mask`
    every composite, matching `FillLayer`'s "no `self.image` of its own,
    render on demand" pattern, so a raster is never the source of truth a
    resize/edit can drift out of sync with. `self.image` for a `shape_data`
    layer is still kept baked by `ShapesTool._bake_shape` (called after
    every edit) purely so the Layers-panel thumbnail — which reads
    `layer.image` directly, not through the composite pipeline — has
    something to show; the *canvas* never looks at it. A layer only ever
    uses one of `shape_data`/`path_style`, never both."""
    _LAYER_TAG = "vector"

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.shape_data: dict | None = None   # ShapesTool primitives (rendered live; also kept baked to image for thumbnails)
        self.path_style: dict | None = None   # Pen Tool path: {"fill_color", "stroke_color", "stroke_width"}

    def _copy_extra(self, clone, deep_image):
        sd = self.shape_data
        clone.shape_data = dict(sd) if sd else None
        ps = self.path_style
        clone.path_style = dict(ps) if ps else None

    def _to_dict_extra(self, d):
        d["shape_data"] = self.shape_data
        d["path_style"] = self.path_style

    def _from_dict_extra(self, d):
        self.shape_data = d.get("shape_data")
        self.path_style = d.get("path_style")

    # ── vector geometry ─────────────────────────────────────────────────
    def has_vector_geometry(self) -> bool:
        if self.shape_data and "rect" in self.shape_data:
            return True
        return bool(self.path_style) and self.vector_mask is not None and not self.vector_mask.isEmpty()

    def _is_path_layer(self) -> bool:
        return bool(self.path_style) and self.vector_mask is not None and not self.vector_mask.isEmpty()

    def shape_spec(self) -> "ShapeSpec | None":
        if self.shape_data and "rect" in self.shape_data:
            return ShapeSpec.from_dict(self.shape_data)
        return None

    def appearance(self) -> ShapeAppearance | None:
        if self._is_path_layer():
            return ShapeAppearance.from_path_style(self.path_style)
        spec = self.shape_spec()
        return spec.appearance if spec else None

    def _geometry_transform(self) -> QTransform:
        # shape_data has always been drawn at layer.offset (it went through
        # the generic offset-aware pixel path); Pen paths are document-space.
        if self._is_path_layer():
            return QTransform()
        return QTransform.fromTranslate(self.offset.x(), self.offset.y())

    def vector_outline(self) -> QPainterPath:
        """This layer's geometry as one region in document space — what
        boolean path operations combine (see combine_with)."""
        if self._is_path_layer():
            return QPainterPath(self.vector_mask)
        spec = self.shape_spec()
        if spec is None:
            return QPainterPath()
        return self._geometry_transform().map(spec.boolean_operand())

    def vector_bounds(self) -> QRectF:
        if self._is_path_layer():
            pad = self.appearance().outer_extent()
            return self.vector_mask.boundingRect().adjusted(-pad, -pad, pad, pad)
        spec = self.shape_spec()
        if spec is None:
            return QRectF()
        return self._geometry_transform().mapRect(spec.bounds())

    def paint_vector(self, painter: QPainter) -> None:
        """Paints just the geometry (no opacity/blend/mask) in document
        coordinates, at whatever resolution `painter`'s transform implies."""
        if self._is_path_layer():
            paint_path_style(painter, self.vector_mask, self.path_style)
            return
        spec = self.shape_spec()
        if spec is None:
            return
        painter.save()
        painter.setTransform(self._geometry_transform(), combine=True)
        spec.paint(painter)
        painter.restore()

    def combine_with(self, other: QPainterPath, op: str) -> None:
        """Photoshop path operation: merges `other` (document space) into
        this layer's geometry. A parametric shape can't represent the
        result, so the layer becomes a Pen-style path layer keeping its
        current fill/stroke appearance."""
        appearance = self.appearance() or ShapeAppearance()
        result = combine_paths(self.vector_outline(), other, op)
        self.shape_data = None
        self.vector_mask = result
        self.vector_mask_enabled = True
        self.path_style = appearance.to_path_style()
        self.offset = QPoint(0, 0)
        self.rebake_thumbnail()

    # LiveRenderedLayer hooks
    def has_live_content(self) -> bool:
        return self.has_vector_geometry()

    def paint_content(self, painter: QPainter) -> None:
        self.paint_vector(painter)

    def content_bounds(self) -> QRectF:
        return self.vector_bounds()

    def rebake_thumbnail(self) -> None:
        """Bakes into the existing (document-sized) image at self.offset —
        shape_data geometry depends on the offset, so it can't be moved
        to make the bake tight the way TextLayer's is."""
        self.image.fill(Qt.GlobalColor.transparent)
        p = QPainter(self.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-self.offset.x(), -self.offset.y())
        self.paint_vector(p)
        p.end()

    def _render_clip_path(self):
        if self._is_path_layer():
            return None
        return super()._render_clip_path()

    def move_tool_bounds(self) -> QRectF:
        if self.path_style and self.vector_mask is not None and not self.vector_mask.isEmpty():
            return self.vector_mask.boundingRect()
        return super().move_tool_bounds()

    def apply_move_geometry(self, transform: QTransform) -> None:
        """A Pen path transforms its document-space vector_mask; a shape
        recomputes shape_data's rect/angle (a line its two endpoints) so it
        re-renders crisply at the new size instead of stretching pixels."""
        if self._is_path_layer():
            self.vector_mask = transform.map(self.vector_mask)
            return
        spec = self.shape_spec()
        if spec is None:
            return
        if spec.kind.is_open:
            start = transform.map(spec.params.start)
            end = transform.map(spec.params.end)
            spec = spec.with_geometry(rect=QRectF(start, end).normalized(), start=start, end=end)
        else:
            new_rect, new_angle = transform_shape_rect(spec.params.rect, spec.angle, transform)
            spec = spec.with_geometry(rect=new_rect, angle=new_angle,
                                      start=new_rect.topLeft(), end=new_rect.bottomRight())
        self.shape_data = spec.to_dict(base=self.shape_data)

    def _thumbnail_canvas_for_move(self, original_img: QImage) -> None:
        # The vector bake is document-sized (shape_data depends on offset).
        self.image = QImage(original_img.width(), original_img.height(),
                            QImage.Format.Format_ARGB32_Premultiplied)


class AdjustmentLayer(Layer):
    _LAYER_TAG = "adjustment"
    _PIXEL_ACCESS = "none"

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.adjustment_data: dict | None = None   # adjustment layer params

    def _copy_extra(self, clone, deep_image):
        ad = self.adjustment_data
        clone.adjustment_data = dict(ad) if ad else None

    def _to_dict_extra(self, d):
        d["adjustment_data"] = self.adjustment_data

    def _from_dict_extra(self, d):
        self.adjustment_data = d.get("adjustment_data")

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        """Adjustment layers don't draw pixels of their own — they re-grade
        everything composited into `ctx.result` so far. That means direct
        numpy access to `ctx.result`'s buffer, which needs the painter torn
        down first (a QImage can't be both painted-into and bits()-mutated
        at once) and rebuilt afterward."""
        from core.document import _apply_layer_adjustment
        from core.pixel_buffer import qimage_argb_view as _qimage_argb_view
        import numpy as np

        document = ctx.document
        view = getattr(ctx, "view_transform", None)
        world = ctx.painter.transform()
        smooth = ctx.painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ctx.painter.end()

        result = ctx.result
        backup = result.copy()
        adjusted = _apply_layer_adjustment(backup, self)

        arr_res = _qimage_argb_view(result, writable=True)
        arr_adj = _qimage_argb_view(adjusted, writable=False)

        # Coverage of the adjustment, in document space (masks, vector
        # mask, artboard and clip base are all document-resolution).
        doc_w, doc_h = document.width, document.height
        frac = np.full((doc_h, doc_w), self.opacity, dtype=np.float32)
        spatial = False

        has_mask = getattr(self, "mask", None) is not None and getattr(self, "mask_enabled", True)
        if has_mask:
            m_arr = _qimage_argb_view(self.mask, writable=False)
            mw = min(doc_w, self.mask.width())
            mh = min(doc_h, self.mask.height())
            mask_f = m_arr[:mh, :mw, 1].astype(np.float32) / 255.0
            frac[:mh, :mw] *= mask_f
            spatial = True

        has_vmask = getattr(self, "vector_mask", None) is not None and getattr(self, "vector_mask_enabled", True)
        if has_vmask:
            vmask_img = QImage(doc_w, doc_h, QImage.Format.Format_Grayscale8)
            vmask_img.fill(0)
            vp = QPainter(vmask_img)
            vp.fillPath(self.vector_mask, QColor(255, 255, 255))
            vp.end()
            v_ptr = vmask_img.bits(); v_ptr.setsize(vmask_img.sizeInBytes())
            v_arr = np.ndarray((doc_h, vmask_img.bytesPerLine()), dtype=np.uint8, buffer=v_ptr)
            vmask_f = v_arr[:doc_h, :doc_w].astype(np.float32) / 255.0
            frac *= vmask_f
            spatial = True

        if layer_artboard_rect:
            ax, ay, aw, ah = layer_artboard_rect.getRect()
            ax = max(0, min(doc_w, ax))
            ay = max(0, min(doc_h, ay))
            aw = max(0, min(doc_w - ax, aw))
            ah = max(0, min(doc_h - ay, ah))
            mask_art = np.zeros((doc_h, doc_w), dtype=np.float32)
            mask_art[ay:ay+ah, ax:ax+aw] = 1.0
            frac *= mask_art
            spatial = True

        if is_clipping and ctx.clip_alpha is not None:
            frac *= ctx.clip_alpha
            spatial = True

        h_end, w_end = backup.height(), backup.width()
        if view is not None:
            frac = (_resample_coverage(frac, view, w_end, h_end, smooth) if spatial
                    else np.full((h_end, w_end), self.opacity, dtype=np.float32))
        frac_4 = frac[:h_end, :w_end, np.newaxis]

        roi_a = arr_adj[:h_end, :w_end, :].astype(np.float32)
        roi_b = arr_res[:h_end, :w_end, :].astype(np.float32)

        roi_a -= roi_b
        roi_a *= frac_4.astype(np.float32)
        roi_a += roi_b
        arr_res[:h_end, :w_end, :] = roi_a.astype(np.uint8)

        if not is_clipping:
            ctx.clip_alpha = None

        ctx.painter = QPainter(result)
        ctx.painter.setTransform(world)
        ctx.painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)


def _resample_coverage(frac, view_transform, width: int, height: int, smooth: bool):
    """Maps a document-space float coverage array onto a `width`x`height`
    viewport through `view_transform` (Document.render_view), the same way
    pixel layers are magnified there."""
    import numpy as np
    from core.pixel_buffer import qimage_argb_view as _qimage_argb_view
    h, w = frac.shape
    src = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    src.fill(0)
    sarr = _qimage_argb_view(src, writable=True)
    a8 = np.clip(frac * 255.0 + 0.5, 0, 255).astype(np.uint8)
    for c in range(4):
        sarr[:, :w, c] = a8
    del sarr
    dst = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    dst.fill(0)
    p = QPainter(dst)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
    p.setTransform(view_transform)
    p.drawImage(0, 0, src)
    p.end()
    darr = _qimage_argb_view(dst, writable=False)
    return darr[:height, :width, 3].astype(np.float32) / 255.0


class FillLayer(Layer):
    _LAYER_TAG = "fill"
    _PIXEL_ACCESS = "rasterize"

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.fill_data: dict | None = None   # fill layer params

    def _copy_extra(self, clone, deep_image):
        fd = self.fill_data
        clone.fill_data = dict(fd) if fd else None

    def _to_dict_extra(self, d):
        d["fill_data"] = self.fill_data

    def _from_dict_extra(self, d):
        self.fill_data = d.get("fill_data")

    def _get_source_image(self, document) -> QImage:
        from core.document import _render_fill_layer
        img = _render_fill_layer(self, document.width, document.height)
        img.is_copy = True
        return img


class SmartObjectLayer(Layer):
    _LAYER_TAG = "smart_object"

    def pixel_access_for(self, op: str) -> str:
        # Filters/warps apply to the placed image (smart filters keep the
        # original); painting into it has to rasterize it first.
        return "rasterize" if op == "paint" else self.pixel_access

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.smart_data: dict | None = None   # {"original": QImage}

    def _copy_extra(self, clone, deep_image):
        smd = self.smart_data
        if smd:
            clone.smart_data = {"original": smd["original"].copy() if deep_image
                                 else QImage(smd["original"])}
        else:
            clone.smart_data = None

    def _to_dict_extra(self, d):
        if self.smart_data and "original" in self.smart_data:
            d["smart_data_original"] = _img_to_bytes(self.smart_data["original"])

    def _from_dict_extra(self, d):
        smd_b = d.get("smart_data_original")
        if smd_b:
            self.smart_data = {"original": _bytes_to_img(smd_b)}


class GroupLayer(Layer):
    """Container layer — children are other layers whose `parent_id`
    matches this layer's `layer_id`. No extra fields of its own."""
    _LAYER_TAG = "group"
    _is_container = True

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        ctx.clip_alpha = None
        ctx.document._render_layer_list(ctx.children_map.get(self.layer_id, []), layer_artboard_rect, ctx)

    def move_tool_container_bounds(self, linked_children: list[dict]) -> QRectF:
        from core.document import Document
        union_br = QRectF()
        for kid_data in linked_children:
            kid = kid_data["layer"]
            if kid.image and not kid.image.isNull():
                br = Document._nontransparent_bounds(kid.image)
                if not br.isEmpty():
                    union_br = union_br.united(QRectF(br).translated(QPointF(kid.offset)))
        if union_br.isEmpty():
            union_br = QRectF(self.offset.x(), self.offset.y(), 100, 100)
        return union_br

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        return True  # linked children already committed live during on_move


class ArtboardLayer(Layer):
    _LAYER_TAG = "artboard"
    _is_container = True

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.artboard_rect: QRect | None = None

    def _copy_extra(self, clone, deep_image):
        ar = self.artboard_rect
        clone.artboard_rect = QRect(ar) if ar is not None else None

    def _to_dict_extra(self, d):
        ar = self.artboard_rect
        d["artboard_rect"] = (ar.x(), ar.y(), ar.width(), ar.height()) if ar is not None else None

    def _from_dict_extra(self, d):
        ar = d.get("artboard_rect")
        if ar:
            self.artboard_rect = QRect(int(ar[0]), int(ar[1]), int(ar[2]), int(ar[3]))

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        ar = getattr(self, "artboard_rect", None)
        if ar:
            ctx.painter.fillRect(ar, QColor(255, 255, 255))
        ctx.clip_alpha = None
        ctx.document._render_layer_list(ctx.children_map.get(self.layer_id, []), ar, ctx)

    def move_tool_container_bounds(self, linked_children: list[dict]) -> QRectF:
        return QRectF(self.artboard_rect or QRect())

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        self.artboard_rect = final_transform.mapRect(QRectF(original_rect)).toRect()
        doc.fit_to_artboards()
        return True

    def move_tool_cancel_extra(self, original_rect) -> None:
        self.artboard_rect = QRect(original_rect) if original_rect else None

    def move_tool_set_params_extra(self, final_transform, original_rect) -> bool:
        self.artboard_rect = final_transform.mapRect(QRectF(original_rect)).toRect()
        return True


class FrameLayer(Layer):
    _LAYER_TAG = "frame"

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.frame_data: dict | None = None   # {"shape": "rect"|"ellipse", "rect": QRectF}

    def _copy_extra(self, clone, deep_image):
        fd = self.frame_data
        if fd:
            clone.frame_data = {"shape": fd.get("shape", "rect"), "rect": QRectF(fd.get("rect", QRectF()))}
        else:
            clone.frame_data = None

    def _to_dict_extra(self, d):
        d["frame_data"] = self.frame_data

    def _from_dict_extra(self, d):
        self.frame_data = d.get("frame_data")

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        from core.blend_modes import composition_mode as _get_composition_mode
        painter = ctx.painter
        img_to_draw = self.image
        is_empty = (img_to_draw.width() <= 1 and img_to_draw.height() <= 1)
        fd = getattr(self, "frame_data", {})
        f_rect = fd.get("rect", QRectF(0, 0, 100, 100))

        path = QPainterPath()
        if fd.get("shape") == "ellipse":
            path.addEllipse(f_rect)
        else:
            path.addRect(f_rect)

        painter.save()
        if layer_artboard_rect:
            painter.setClipRect(layer_artboard_rect)

        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)

        if is_empty:
            painter.fillRect(f_rect, QColor(220, 220, 220))
            painter.setPen(QPen(QColor(150, 150, 150), 2))
            if fd.get("shape") == "rect":
                painter.drawLine(f_rect.topLeft(), f_rect.bottomRight())
                painter.drawLine(f_rect.topRight(), f_rect.bottomLeft())
        else:
            painter.setOpacity(self.opacity)
            painter.setCompositionMode(_get_composition_mode(getattr(self, "blend_mode", "SourceOver")))
            painter.drawImage(self.offset, img_to_draw)

        painter.restore()

    def move_tool_bounds(self) -> QRectF:
        return QRectF(getattr(self, "frame_data", {}).get("rect", QRectF(0, 0, 100, 100)))

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        self.frame_data["rect"] = final_transform.mapRect(QRectF(original_rect))
        return False  # still needs the generic pixel commit below (frame's own image)

    def move_tool_cancel_extra(self, original_rect) -> None:
        self.frame_data["rect"] = QRectF(original_rect) if original_rect else QRectF()

    def move_tool_set_params_extra(self, final_transform, original_rect) -> bool:
        self.frame_data["rect"] = final_transform.mapRect(QRectF(original_rect))
        return True


_LAYER_CLASSES = {
    "raster": RasterLayer,
    "text": TextLayer,
    "vector": VectorLayer,
    "adjustment": AdjustmentLayer,
    "fill": FillLayer,
    "smart_object": SmartObjectLayer,
    "group": GroupLayer,
    "artboard": ArtboardLayer,
    "frame": FrameLayer,
}


def layer_from_dict(d: dict, w: int, h: int) -> Layer:
    """Deserialization entry point: picks the right Layer subclass from the
    saved `layer_type` string. The only place that needs updating if a new
    layer type is ever added to _LAYER_CLASSES."""
    cls = _LAYER_CLASSES.get(d.get("layer_type", "raster"), RasterLayer)
    return cls.from_dict(d, w, h)
