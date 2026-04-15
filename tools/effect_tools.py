"""
effect_tools.py — Blur, Sharpen, Smudge, Dodge, Burn, Sponge.

Архитектура:
- BrushEffectTool  — базовый класс: весь бойлерплейт один раз
  * layer.locked / lock_pixels → early return
  * layer.lock_alpha           → восстанавливаем alpha после эффекта
  * layer.offset               → правильная система координат
  * doc.selection (clip)       → ограничение по выделению
  * CompositionMode_Source     → запись без артефактов прозрачности
  * _make_mask()               → маска кисти (переопределяется подклассом)

- Каждый инструмент реализует только _compute_effect(patch_f, mask, strength, opts)
  и при необходимости _apply_qt_fallback() для работы без numpy.

- _SoftMaskMixin — для Dodge/Burn/Sponge: всегда мягкий smoothstep-градиент,
  независимо от brush_hardness (у этих инструментов нет слайдера hardness).
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
    Mixin для эффект-инструментов (Blur, Sharpen, Smudge и т.п.).

    Оптимизация canvas_widget:
    - needs_background_composite = True → canvas кэширует фон без активного слоя
    - stroke_preview() → canvas рисует активный слой поверх кэша (без get_composite())
    - Итог: один get_composite() на старте мазка вместо одного на каждое движение.
    """

    needs_background_composite: bool = True

    def _init_effect_stroke(self):
        self._eff_layer_ref = None
        # True только когда canvas включил оптимизацию (_start_effect_stroke).
        self._stroke_preview_active = False

    def _begin_effect_stroke(self, doc):
        self._eff_layer_ref = doc.get_active_layer()

    def _end_effect_stroke(self):
        self._eff_layer_ref = None
        self._stroke_preview_active = False

    def stroke_preview(self):
        """Возвращает (QImage, offset, opacity) или None — вызывается canvas на каждый кадр."""
        if not self._stroke_preview_active:
            return None
        layer = self._eff_layer_ref
        if layer is None:
            return None
        return (layer.image, layer.offset, layer.opacity)


# ═══════════════════════════════════════════════════════════════ BrushEffectTool

class BrushEffectTool(_EffectStrokeMixin, BaseTool):
    """
    Базовый класс для всех кисть-like инструментов-эффектов.

    Подкласс должен реализовать _compute_effect().
    Опционально: _make_mask() и _apply_qt_fallback().
    """

    modifies_canvas_on_move = True

    def __init__(self):
        self._init_effect_stroke()
        self._last: QPoint | None = None

    # ── жизненный цикл ────────────────────────────────────────────────────────

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

    # ── ядро ──────────────────────────────────────────────────────────────────

    def _apply(self, pos: QPoint, doc, opts: dict):
        """Применяет эффект к патчу под кистью. Весь бойлерплейт здесь."""
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

        # lock_alpha: эффект не должен менять прозрачность
        if getattr(layer, "lock_alpha", False):
            result_f[..., 3:4] = patch_f[..., 3:4]

        result_img = _np_to_qimage(result_f.clip(0, 255).astype(np.uint8))
        p = QPainter(layer.image)
        # Source: пишем пиксели напрямую, без SourceOver-композитинга →
        # прозрачные пиксели на границах остаются прозрачными
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        if clip:
            p.setClipPath(clip.translated(-layer.offset.x(), -layer.offset.y()))
        p.drawImage(src_rect.topLeft(), result_img)
        p.end()

    # ── переопределяемые методы ───────────────────────────────────────────────

    def _make_mask(self, src_rect, cx, cy, r, hardness):
        """Маска кисти. По умолчанию: hardness-aware smoothstep.
        Dodge/Burn/Sponge переопределяют на всегда-мягкую через _SoftMaskMixin."""
        return _brush_mask(src_rect, cx, cy, r, hardness)

    def _compute_effect(self, patch_f, mask, strength, opts) -> "np.ndarray":
        """
        Логика эффекта. Переопределить в подклассе.

        Args:
            patch_f: float32 (H, W, 4) BGRA — оригинальный патч
            mask:    float32 (H, W, 1)  — маска кисти [0.0–1.0]
            strength: float             — сила эффекта [0.0–1.0]
            opts:    dict               — все параметры инструмента

        Returns:
            float32 (H, W, 4) — результат (alpha канал копируется из patch_f,
            если включён lock_alpha — base class восстановит его автоматически)
        """
        return patch_f

    def _apply_qt_fallback(self, layer, cx: int, cy: int, size: int, clip, opts: dict):
        """Qt-fallback (без numpy). Переопределить при необходимости."""
        pass


# ═══════════════════════════════════════════════════════════════ _SoftMaskMixin

class _SoftMaskMixin:
    """
    Переопределяет маску кисти на всегда-мягкую (smoothstep без hardness).
    Используется Dodge, Burn, Sponge — у них нет слайдера hardness в UI.
    """

    def _make_mask(self, src_rect, cx, cy, r, hardness):
        return _soft_circle_mask(src_rect, cx, cy, r)


# ═══════════════════════════════════════════════════════════════ BlurTool

class BlurTool(BrushEffectTool):
    """Размытие кистью.
    RGB размывается в premultiplied alpha пространстве → нет тёмных краёв на прозрачности."""
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
    """Резкость — unsharp mask внутри круга кисти."""
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

    # Без numpy ничего не делаем (sharpen без float-арифметики бессмысленен)


# ═══════════════════════════════════════════════════════════════ SmudgeTool

class SmudgeTool(BrushEffectTool):
    """Палец — тащит «каплю» цвета в направлении движения кисти."""
    name     = "Smudge"
    icon     = "👆"
    shortcut = "W"

    def __init__(self):
        super().__init__()
        self._color: QColor | None = None

    def on_press(self, pos, doc, fg, bg, opts):
        """Запоминаем начальный цвет под кистью, но НЕ применяем эффект."""
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

        # «Капля» — BGRA; alpha капли убывает когда она проходит через прозрачные пиксели,
        # но никогда не растёт — иначе капля «красит» прозрачный фон своим цветом.
        drop_a = self._color.alpha()
        smudge = np.array([self._color.blue(), self._color.green(),
                           self._color.red(),  drop_a],
                          dtype=np.float32)

        t = strength * mask
        blended = (patch_f * (1.0 - t) + smudge * t).clip(0, 255)

        result = patch_f.copy()
        result[..., :3] = blended[..., :3]
        # Alpha: берём минимум — капля может убывать, но не создаёт новую непрозрачность
        result[..., 3:4] = np.minimum(patch_f[..., 3:4], blended[..., 3:4])

        # Обновляем каплю: RGB из патча, alpha — min(текущей, средней по патчу)
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
    """Осветление — сдвигает RGB к белому."""
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
    """Затемнение — сдвигает RGB к чёрному."""
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
    """Губка — насыщение или десатурация."""
    name     = "Sponge"
    icon     = "🧽"
    shortcut = "O"

    def _compute_effect(self, patch_f, mask, strength, opts):
        rgb  = patch_f[..., :3]
        # Яркость (BGRA: ch0=Blue, ch1=Green, ch2=Red)
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
