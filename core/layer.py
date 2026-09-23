from PyQt6.QtGui import QImage, QColor, QPainterPath, QPainter, QPen
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QBuffer, QIODevice, QByteArray
import uuid
from typing import TYPE_CHECKING

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
        from core.document import (
            _get_composition_mode, _ensure_owned_copy, _qimage_argb_view,
            _shift_pixels_edge, _composite_active_stroke,
        )
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
            if getattr(self, "vector_mask", None) is not None and getattr(self, "vector_mask_enabled", True):
                ap.setClipPath(self.vector_mask)
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

        if getattr(self, "vector_mask", None) is not None and getattr(self, "vector_mask_enabled", True):
            painter.setClipPath(self.vector_mask, Qt.ClipOperation.IntersectClip)
        painter.setCompositionMode(_get_composition_mode(getattr(self, "blend_mode", "SourceOver")))
        painter.setOpacity(self.opacity)
        painter.drawImage(current_offset, img_to_draw)
        painter.restore()

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


class TextLayer(Layer):
    _LAYER_TAG = "text"
    _move_tool_uniform_scale_only = True

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.text_data: dict | None = None   # text layer params

    def _copy_extra(self, clone, deep_image):
        td = self.text_data
        clone.text_data = dict(td) if td else None

    def _to_dict_extra(self, d):
        d["text_data"] = self.text_data

    def _from_dict_extra(self, d):
        self.text_data = d.get("text_data")

    def move_tool_apply_extra(self, doc, final_transform, original_rect, original_img) -> bool:
        import math
        td = getattr(self, "text_data", None)
        if td:
            orig_pt = QPointF(td.get("x", 0), td.get("y", 0))
            new_pt = final_transform.map(orig_pt)
            m11, m12 = final_transform.m11(), final_transform.m12()
            delta_angle = math.degrees(math.atan2(m12, m11))
            new_angle = float(td.get("text_angle", 0.0)) + delta_angle
            new_td = dict(td)
            new_td["x"] = new_pt.x()
            new_td["y"] = new_pt.y()
            new_td["text_angle"] = new_angle
            w, h = original_img.width(), original_img.height()
            new_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            from tools.text_tool import _render_text
            _render_text(new_img, int(new_pt.x()), int(new_pt.y()),
                         new_td.get("text", ""), new_td, None)
            self.image = new_img
            self.text_data = new_td
        return True


class VectorLayer(Layer):
    """Two independent ways a layer ends up "vector": `shape_data`
    (ShapesTool's rect/ellipse/polygon/... primitives — baked to `image`
    fresh on every resize by `ShapesTool._bake_shape`, so already
    non-destructive) and `path_style` + `Layer.vector_mask` (Pen Tool's
    true bezier path). `path_style` is the live one: no `image` involved
    at all, `render_into` fills/strokes `vector_mask` directly every
    render, so the geometry stays exact at any zoom instead of being a
    one-time raster bake. A layer only ever uses one or the other."""
    _LAYER_TAG = "vector"

    def __init__(self, name: str, width: int, height: int, fill_color: QColor = None):
        super().__init__(name, width, height, fill_color)
        self.shape_data: dict | None = None   # ShapesTool primitives (baked to image)
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

    def render_into(self, ctx, layer_artboard_rect, is_clipping, next_clipping):
        if not self.path_style or self.vector_mask is None or self.vector_mask.isEmpty():
            # A baked ShapesTool primitive (or no geometry at all yet) —
            # it's real pixels in `self.image`, render like any other layer.
            super().render_into(ctx, layer_artboard_rect, is_clipping, next_clipping)
            return

        painter = ctx.painter
        painter.save()
        if layer_artboard_rect:
            painter.setClipRect(layer_artboard_rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.opacity)
        from core.document import _get_composition_mode
        painter.setCompositionMode(_get_composition_mode(getattr(self, "blend_mode", "SourceOver")))

        # vector_mask is already in document-space coordinates (Pen Tool
        # builds it from raw mouse positions, not layer-local ones) — same
        # assumption the mask-as-clip-path code in the base render_into
        # makes, no offset translation needed.
        fill = self.path_style.get("fill_color")
        if fill is not None:
            painter.fillPath(self.vector_mask, fill)
        stroke = self.path_style.get("stroke_color")
        width = self.path_style.get("stroke_width", 0)
        if stroke is not None and width > 0:
            painter.strokePath(self.vector_mask, QPen(stroke, width))

        painter.restore()

    def move_tool_bounds(self) -> QRectF:
        if self.path_style and self.vector_mask is not None and not self.vector_mask.isEmpty():
            return self.vector_mask.boundingRect()
        return super().move_tool_bounds()


class AdjustmentLayer(Layer):
    _LAYER_TAG = "adjustment"

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
        from core.document import _apply_layer_adjustment, _qimage_argb_view
        import numpy as np

        document = ctx.document
        ctx.painter.end()

        result = ctx.result
        backup = result.copy()
        adjusted = _apply_layer_adjustment(backup, self)

        arr_res = _qimage_argb_view(result, writable=True)
        arr_adj = _qimage_argb_view(adjusted, writable=False)

        frac = np.full((backup.height(), backup.width()), self.opacity, dtype=np.float32)

        has_mask = getattr(self, "mask", None) is not None and getattr(self, "mask_enabled", True)
        if has_mask:
            m_arr = _qimage_argb_view(self.mask, writable=False)
            mw = min(backup.width(), self.mask.width())
            mh = min(backup.height(), self.mask.height())
            mask_f = m_arr[:mh, :mw, 1].astype(np.float32) / 255.0
            frac[:mh, :mw] *= mask_f

        has_vmask = getattr(self, "vector_mask", None) is not None and getattr(self, "vector_mask_enabled", True)
        if has_vmask:
            vmask_img = QImage(backup.width(), backup.height(), QImage.Format.Format_Grayscale8)
            vmask_img.fill(0)
            vp = QPainter(vmask_img)
            vp.fillPath(self.vector_mask, QColor(255, 255, 255))
            vp.end()
            v_ptr = vmask_img.bits(); v_ptr.setsize(vmask_img.sizeInBytes())
            v_arr = np.ndarray((backup.height(), vmask_img.bytesPerLine()), dtype=np.uint8, buffer=v_ptr)
            vmask_f = v_arr[:backup.height(), :backup.width()].astype(np.float32) / 255.0
            frac *= vmask_f

        if layer_artboard_rect:
            ax, ay, aw, ah = layer_artboard_rect.getRect()
            ax = max(0, min(document.width, ax))
            ay = max(0, min(document.height, ay))
            aw = max(0, min(document.width - ax, aw))
            ah = max(0, min(document.height - ay, ah))
            mask_art = np.zeros((document.height, document.width), dtype=np.float32)
            mask_art[ay:ay+ah, ax:ax+aw] = 1.0
            frac *= mask_art

        if is_clipping and ctx.clip_alpha is not None:
            frac *= ctx.clip_alpha

        frac_4 = frac[..., np.newaxis]

        h_end, w_end = backup.height(), backup.width()
        roi_a = arr_adj[:h_end, :w_end, :].astype(np.float32)
        roi_b = arr_res[:h_end, :w_end, :].astype(np.float32)

        roi_a -= roi_b
        roi_a *= frac_4.astype(np.float32)
        roi_a += roi_b
        arr_res[:h_end, :w_end, :] = roi_a.astype(np.uint8)

        if not is_clipping:
            ctx.clip_alpha = None

        ctx.painter = QPainter(result)


class FillLayer(Layer):
    _LAYER_TAG = "fill"

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
        from core.document import _get_composition_mode
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
