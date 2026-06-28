"""
effect_tools.py - Blur, Sharpen, Smudge, Dodge, Burn, Sponge.

Architecture:
- BrushEffectTool  - base class: all boilerplate in one place
  * layer.locked / lock_pixels -> early return
  * layer.lock_alpha           -> restore alpha after effect
  * layer.offset               -> correct coordinate system
  * doc.selection (clip)       -> constrain to selection
  * CompositionMode_Source     -> write without transparency artifacts
  * _make_mask()               -> brush mask (overridden by subclass)

- Each tool implements only _compute_effect(patch_f, mask, strength, opts)
  and optionally _apply_qt_fallback() for use without numpy.

- _SoftMaskMixin - for Dodge/Burn/Sponge: always soft smoothstep gradient,
  regardless of brush_hardness (these tools have no hardness slider).
"""

from PyQt6.QtGui import QPainter, QColor, QImage
from PyQt6.QtCore import QPoint, QRect
from tools.base_tool import BaseTool
from tools.tool_utils import (
    _HAS_NUMPY,
    _clamp_rect, _qimage_to_np, _np_to_qimage,
    _circle_mask, _soft_circle_mask, _brush_mask,
    _box_blur_rgb, _box_blur_np, _sharpen_np, _apply_qt_blur,
)

if _HAS_NUMPY:
    import numpy as np


# ═══════════════════════════════════════════════════════════════ _EffectStrokeMixin

class _EffectStrokeMixin:
    """
    Mixin for effect tools (Blur, Sharpen, Smudge, etc.).

    canvas_widget optimization:
    - needs_background_composite = True -> canvas caches background without active layer
    - stroke_preview() -> canvas draws active layer over cache (no get_composite())
    - Result: one get_composite() at stroke start instead of one per mouse move.
    """

    needs_background_composite: bool = True

    def _init_effect_stroke(self):
        self._eff_layer_ref = None
        # True only when canvas has enabled optimization (_start_effect_stroke).
        self._stroke_preview_active = False

    def _begin_effect_stroke(self, doc):
        self._eff_layer_ref = doc.get_active_layer()

    def _end_effect_stroke(self):
        self._eff_layer_ref = None
        self._stroke_preview_active = False

    def stroke_preview(self):
        """Returns (QImage, offset, opacity) or None - called by canvas each frame."""
        if not self._stroke_preview_active:
            return None
        layer = self._eff_layer_ref
        if layer is None:
            return None
        return (layer.image, layer.offset, layer.opacity)


# ═══════════════════════════════════════════════════════════════ BrushEffectTool

class BrushEffectTool(_EffectStrokeMixin, BaseTool):
    """
    Base class for all brush-like effect tools.

    Subclass must implement _compute_effect().
    Optionally: _make_mask() and _apply_qt_fallback().
    """

    modifies_canvas_on_move = True

    def __init__(self):
        self._init_effect_stroke()
        self._last: QPoint | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def on_press(self, pos, doc, fg, bg, opts):
        self._begin_effect_stroke(doc)
        self._last = pos
        self._apply(pos, doc, opts)

    def on_move(self, pos, doc, fg, bg, opts):
        if self._last:
            self._apply(pos, doc, opts)
        self._last = pos

    def on_release(self, pos, doc, fg, bg, opts):
        self._end_effect_stroke()
        self._last = None

    # ── core ──────────────────────────────────────────────────────────────────

    def _apply(self, pos: QPoint, doc, opts: dict):
        """Apply effect to the patch under the brush. All boilerplate is here."""
        layer = doc.get_active_layer()
        if not layer or layer.locked or getattr(layer, "lock_pixels", False):
            return

        size     = max(4, int(opts.get("brush_size", 20)))
        hardness = float(opts.get("brush_hardness", 1.0))
        strength = float(opts.get("effect_strength", 0.5))

        cx   = pos.x() - layer.offset.x()
        cy   = pos.y() - layer.offset.y()
        clip = doc.selection if (doc.selection and not doc.selection.isEmpty()) else None

        if not _HAS_NUMPY:
            self._apply_qt_fallback(layer, cx, cy, size, clip, opts)
            return

        r = size // 2
        src_rect = _clamp_rect(
            QRect(cx - r, cy - r, size, size),
            layer.image.width(), layer.image.height())
        if clip:
            src_rect = src_rect.intersected(
                clip.boundingRect().toRect().translated(-layer.offset))
        if src_rect.isEmpty():
            return

        patch_f = _qimage_to_np(layer.image.copy(src_rect)).astype(np.float32)
        mask    = self._make_mask(src_rect, cx, cy, r, hardness)

        result_f = self._compute_effect(patch_f, mask, strength, opts)

        # lock_alpha: effect must not change transparency
        if getattr(layer, "lock_alpha", False):
            result_f[..., 3:4] = patch_f[..., 3:4]

        result_img = _np_to_qimage(result_f.clip(0, 255).astype(np.uint8))
        p = QPainter(layer.image)
        # Source: write pixels directly, without SourceOver compositing ->
        # transparent pixels at edges remain transparent
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        if clip:
            p.setClipPath(clip.translated(-layer.offset.x(), -layer.offset.y()))
        p.drawImage(src_rect.topLeft(), result_img)
        p.end()

    # ── overridable methods ───────────────────────────────────────────────

    def _make_mask(self, src_rect, cx, cy, r, hardness):
        """Brush mask. Default: hardness-aware smoothstep.
        Dodge/Burn/Sponge override to always-soft via _SoftMaskMixin."""
        return _brush_mask(src_rect, cx, cy, r, hardness)

    def _compute_effect(self, patch_f, mask, strength, opts) -> "np.ndarray":
        """
        Effect logic. Override in subclass.

        Args:
            patch_f: float32 (H, W, 4) BGRA - original patch
            mask:    float32 (H, W, 1)  - brush mask [0.0-1.0]
            strength: float             - effect strength [0.0-1.0]
            opts:    dict               - all tool parameters

        Returns:
            float32 (H, W, 4) - result (alpha channel is copied from patch_f;
            if lock_alpha is enabled, base class restores it automatically)
        """
        return patch_f

    def _apply_qt_fallback(self, layer, cx: int, cy: int, size: int, clip, opts: dict):
        """Qt fallback (without numpy). Override if needed."""
        pass


# ═══════════════════════════════════════════════════════════════ _SoftMaskMixin

class _SoftMaskMixin:
    """
    Overrides brush mask to always-soft (smoothstep without hardness).
    Used by Dodge, Burn, Sponge - they have no hardness slider in the UI.
    """

    def _make_mask(self, src_rect, cx, cy, r, hardness):
        return _soft_circle_mask(src_rect, cx, cy, r)


# ═══════════════════════════════════════════════════════════════ BlurTool

class BlurTool(BrushEffectTool):
    """Brush blur.
    RGB is blurred in premultiplied alpha space -> no dark edges on transparency."""
    name     = "Blur"
    icon     = "💧"
    shortcut = "R"

    def _compute_effect(self, patch_f, mask, strength, opts):
        radius = max(1, int(opts.get("brush_size", 20) * strength * 0.5))

        alpha       = patch_f[..., 3:4] / 255.0        # [0, 1]
        rgb_pre     = patch_f[..., :3] * alpha           # premultiplied [0, 255]
        blurred_pre = _box_blur_rgb(rgb_pre, radius)     # blur(RGB × α)
        blurred_a   = _box_blur_rgb(alpha,   radius)     # blur(α)
        safe        = np.maximum(blurred_a, 1e-6)
        blurred_rgb = blurred_pre / safe                 # unpremultiplied [0, 255]

        t = mask * strength
        result = patch_f.copy()
        result[..., :3]  = (patch_f[..., :3]  * (1.0 - t) + blurred_rgb       * t).clip(0, 255)
        result[..., 3:4] = (patch_f[..., 3:4] * (1.0 - t) + blurred_a * 255.0 * t).clip(0, 255)
        return result

    def _apply_qt_fallback(self, layer, cx, cy, size, clip, opts):
        _apply_qt_blur(layer.image, cx, cy, size // 2)


# ═══════════════════════════════════════════════════════════════ SharpenTool

class SharpenTool(BrushEffectTool):
    """Sharpen - unsharp mask inside the brush circle."""
    name     = "Sharpen"
    icon     = "🔺"
    shortcut = "Y"

    def _compute_effect(self, patch_f, mask, strength, opts):
        patch_u8  = patch_f.clip(0, 255).astype(np.uint8)
        sharpened = _sharpen_np(patch_u8, strength).astype(np.float32)
        result    = patch_f.copy()
        result[...] = (patch_f * (1.0 - mask * strength) +
                       sharpened * (mask * strength)).clip(0, 255)
        return result

    # Without numpy we do nothing (sharpen without float arithmetic is pointless)


# ═══════════════════════════════════════════════════════════════ SmudgeTool

class SmudgeTool(BrushEffectTool):
    """Smudge - drags a color drop in the brush movement direction."""
    name     = "Smudge"
    icon     = "👆"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._color: QColor | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        """Remember the initial color under the brush, but do NOT apply the effect."""
        self._begin_effect_stroke(doc)
        self._last = pos
        layer = doc.get_active_layer()
        if layer:
            x = pos.x() - layer.offset.x()
            y = pos.y() - layer.offset.y()
            if 0 <= x < layer.width() and 0 <= y < layer.height():
                self._color = QColor(layer.image.pixel(x, y))
            else:
                self._color = QColor(0, 0, 0, 0)

    def on_release(self, pos, doc, fg, bg, opts):
        super().on_release(pos, doc, fg, bg, opts)
        self._color = None

    def _compute_effect(self, patch_f, mask, strength, opts):
        if self._color is None:
            return patch_f

        # Drop - BGRA; drop alpha decreases when passing through transparent pixels,
        # but never increases - otherwise the drop paints the transparent background.
        drop_a = self._color.alpha()
        smudge = np.array([self._color.blue(), self._color.green(),
                           self._color.red(),  drop_a],
                          dtype=np.float32)

        t = strength * mask
        blended = (patch_f * (1.0 - t) + smudge * t).clip(0, 255)

        result = patch_f.copy()
        result[..., :3] = blended[..., :3]
        # Alpha: take minimum - drop can fade but does not create new opacity
        result[..., 3:4] = np.minimum(patch_f[..., 3:4], blended[..., 3:4])

        # Update drop: RGB from patch, alpha = min(current, patch average)
        avg = patch_f.mean(axis=(0, 1))
        new_a = min(drop_a, int(avg[3]))
        self._color = QColor(int(avg[2]), int(avg[1]), int(avg[0]), new_a)
        return result

    def _apply_qt_fallback(self, layer, cx: int, cy: int, size: int, clip, opts: dict):
        if not self._color or not self._last:
            return
        from PyQt6.QtGui import QPen
        from PyQt6.QtCore import Qt
        strength = float(opts.get("effect_strength", 0.7))
        c = QColor(self._color)
        c.setAlphaF(strength * 0.6)
        pen = QPen(c, size, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p = QPainter(layer.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if clip:
            p.setClipPath(clip.translated(-layer.offset.x(), -layer.offset.y()))
        p.setPen(pen)
        start = QPoint(self._last.x() - layer.offset.x(),
                       self._last.y() - layer.offset.y())
        p.drawLine(start, QPoint(cx, cy))
        p.end()
        if 0 <= cx < layer.width() and 0 <= cy < layer.height():
            orig = QColor(layer.image.pixel(cx, cy))
            self._color = QColor(
                int(orig.red()   * (1-strength) + self._color.red()   * strength),
                int(orig.green() * (1-strength) + self._color.green() * strength),
                int(orig.blue()  * (1-strength) + self._color.blue()  * strength),
            )


# ═══════════════════════════════════════════════════════════════ DodgeTool

class DodgeTool(_SoftMaskMixin, BrushEffectTool):
    """Dodge - shifts RGB toward white."""
    name     = "Dodge"
    icon     = "🌔"
    shortcut = "O"

    def _compute_effect(self, patch_f, mask, strength, opts):
        rgb    = patch_f[..., :3]
        factor = strength * 0.2 * mask
        result = patch_f.copy()
        result[..., :3] = (rgb + (255.0 - rgb) * factor).clip(0, 255)
        return result


# ═══════════════════════════════════════════════════════════════ BurnTool

class BurnTool(_SoftMaskMixin, BrushEffectTool):
    """Burn - shifts RGB toward black."""
    name     = "Burn"
    icon     = "🌒"
    shortcut = "O"

    def _compute_effect(self, patch_f, mask, strength, opts):
        rgb    = patch_f[..., :3]
        factor = strength * 0.2 * mask
        result = patch_f.copy()
        result[..., :3] = (rgb * (1.0 - factor)).clip(0, 255)
        return result


# ═══════════════════════════════════════════════════════════════ SpongeTool

class SpongeTool(_SoftMaskMixin, BrushEffectTool):
    """Sponge - saturate or desaturate."""
    name     = "Sponge"
    icon     = "🧽"
    shortcut = "O"

    def _compute_effect(self, patch_f, mask, strength, opts):
        rgb  = patch_f[..., :3]
        # Luminance (BGRA: ch0=Blue, ch1=Green, ch2=Red)
        gray = (0.114 * rgb[..., 0:1] +
                0.587 * rgb[..., 1:2] +
                0.299 * rgb[..., 2:3])
        factor = strength * 0.2 * mask
        mode = opts.get("sponge_mode", "desaturate")
        if mode == "desaturate":
            res_rgb = rgb * (1.0 - factor) + gray * factor
        else:
            res_rgb = rgb + (rgb - gray) * factor
        result = patch_f.copy()
        result[..., :3] = res_rgb.clip(0, 255)
        return result
