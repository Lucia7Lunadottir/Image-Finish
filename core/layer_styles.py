import os
import math
import numpy as np
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QColor, QBrush, QPixmap, QTransform
from PyQt6.QtCore import QPoint, QRectF, Qt


def _box_blur_gray(ch: "np.ndarray", r: int) -> "np.ndarray":
    """Single-channel box blur via padded cumsum and contiguous slicing —
    much faster than per-channel fancy indexing on large masks."""
    h, w = ch.shape
    r = max(1, min(r, min(h, w) // 2 - 1))
    k = 2 * r + 1
    p = np.pad(ch, ((0, 0), (r, r)), mode="edge")
    s = np.zeros((h, p.shape[1] + 1), dtype=np.float32)
    np.cumsum(p, axis=1, dtype=np.float32, out=s[:, 1:])
    ch = (s[:, k:] - s[:, :-k]) / k
    p = np.pad(ch, ((r, r), (0, 0)), mode="edge")
    s = np.zeros((p.shape[0] + 1, w), dtype=np.float32)
    np.cumsum(p, axis=0, dtype=np.float32, out=s[1:, :])
    return (s[k:, :] - s[:-k, :]) / k


def _blur_mask(mask_u8: "np.ndarray", r: int) -> "np.ndarray":
    """3-pass gaussian-approximation blur of a uint8 mask. Large radii are
    computed at reduced resolution and smoothly upscaled — visually
    indistinguishable for soft shadows/glows, an order of magnitude faster."""
    if r <= 0:
        return mask_u8
    h, w = mask_u8.shape
    scale = 4 if r >= 8 else (2 if r >= 3 else 1)
    if scale > 1 and min(h, w) > scale * 8:
        small = mask_u8[::scale, ::scale]
        rr = max(1, round(r / scale))
    else:
        small, rr, scale = mask_u8, r, 1
    f = small.astype(np.float32)
    for _ in range(3):
        f = _box_blur_gray(f, rr)
    out = np.clip(f, 0, 255).astype(np.uint8)
    if scale > 1:
        out = np.ascontiguousarray(out)
        qi = QImage(out.data, out.shape[1], out.shape[0], out.shape[1],
                    QImage.Format.Format_Grayscale8)
        qi = qi.scaled(w, h,
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        ptr = qi.constBits()
        ptr.setsize(qi.sizeInBytes())
        full = np.frombuffer(ptr, dtype=np.uint8).reshape(h, qi.bytesPerLine())
        out = full[:, :w].copy()
    return out

from core.blend_modes import composition_mode as _get_comp_mode  # noqa: E402

# Style parameters measured in pixels — what has to be multiplied when the
# styles are rendered at another resolution than the document's (zoomed
# view of a shape/text layer, see core/layer.py::LiveRenderedLayer).
_PIXEL_KEYS = ("distance", "size")


def scale_layer_styles(styles: dict, k: float) -> dict:
    """Copy of `styles` with every pixel-sized parameter multiplied by k
    (pattern overlay scale too, so the pattern keeps its document size)."""
    if abs(k - 1.0) < 1e-6:
        return styles
    out = {}
    for key, opts in styles.items():
        o = dict(opts) if isinstance(opts, dict) else opts
        if isinstance(o, dict):
            for pk in _PIXEL_KEYS:
                if pk in o and isinstance(o[pk], (int, float)):
                    o[pk] = o[pk] * k
            if key == "pattern_overlay" and isinstance(o.get("scale"), (int, float)):
                o["scale"] = o["scale"] * k
        out[key] = o
    return out


STROKE_POSITIONS = ("outside", "inside", "center")


def stroke_coverage(alpha: "np.ndarray", size: float, position: str = "outside") -> "np.ndarray":
    """uint8 coverage of a `size`-px stroke along the edge of `alpha`
    (uint8), by exact distance to the edge like Photoshop's: outside,
    inside or centred on it. One pixel of falloff keeps it antialiased;
    an outside stroke also fills under the layer's soft edge pixels, never
    under its opaque inside (so it shows the outline only, even at 0% Fill)."""
    from scipy import ndimage
    a = alpha.astype(np.float32) / 255.0
    inside = alpha >= 128
    d_out = ndimage.distance_transform_edt(~inside)        # outside pixels: to the shape
    d_in = ndimage.distance_transform_edt(inside)          # inside pixels: to the outside
    if position == "inside":
        cov = np.clip(size + 0.5 - d_in, 0.0, 1.0) * a
    elif position == "center":
        half = size / 2.0
        cov = (np.clip(half + 0.5 - d_out, 0.0, 1.0) * (1.0 - a)
               + np.clip(half + 0.5 - d_in, 0.0, 1.0) * a)
    else:
        cov = np.clip(size + 0.5 - d_out, 0.0, 1.0) * (1.0 - a)
    return np.clip(cov * 255.0 + 0.5, 0, 255).astype(np.uint8)


def fill_opacity(styles: dict | None) -> float:
    """Photoshop's Fill opacity, 0..100 — a plain number in `styles` (not
    an effect: it doesn't switch the styles render path on by itself)."""
    v = (styles or {}).get("fill_opacity", 100)
    return max(0.0, min(100.0, float(v))) if isinstance(v, (int, float)) else 100.0


def layer_styles_padding(styles: dict) -> int:
    """How far (pixels) the enabled effects reach outside the layer's pixels."""
    pad = 0
    for key, opts in (styles or {}).items():
        if not isinstance(opts, dict) or not opts.get("enabled"):
            continue
        if key == "drop_shadow":
            pad = max(pad, opts.get("distance", 0) + opts.get("size", 0) * 2)
        elif key in ("outer_glow", "inner_shadow"):
            pad = max(pad, opts.get("size", 0) * 2)
        elif key == "stroke":
            pad = max(pad, opts.get("size", 0))
    return int(math.ceil(pad)) + 4


def _blend_overlay(img: QImage, brush: QBrush, blend_mode: str, opacity: float,
                   area: QPainterPath | None = None) -> QImage:
    """An overlay style (colour / gradient / pattern) the way Photoshop
    applies it: the overlay's colour is blended into the layer's colour with
    `blend_mode` at `opacity` %, and the layer keeps its own transparency.

    QPainter alone can't express that — its blend modes also produce alpha
    where the layer is transparent, and clipping to the layer (SourceAtop,
    which the old code used) replaced the chosen mode with plain Normal. So:
    blend onto an opaque copy of the layer's colours, then put the layer's
    alpha back. `area` limits it to a region (Edit > Stroke with Preserve
    Transparency); by default the whole image."""
    from core.pixel_buffer import qimage_argb_view
    w = img.width()
    straight = img.convertToFormat(QImage.Format.Format_ARGB32)
    view = qimage_argb_view(straight, writable=True)[:, :w]
    alpha = view[..., 3].copy()
    view[..., 3] = 255                       # opaque: straight == premultiplied
    opaque = straight.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(opaque)
    p.setCompositionMode(_get_comp_mode(blend_mode))
    p.setOpacity(max(0.0, min(1.0, opacity / 100.0)))
    if area is None:
        p.fillRect(opaque.rect(), brush)
    else:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(area, brush)
    p.end()
    out = opaque.convertToFormat(QImage.Format.Format_ARGB32)
    qimage_argb_view(out, writable=True)[:, :w, 3] = alpha
    return out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def apply_layer_styles(img: QImage, styles: dict, frame: QRectF | None = None) -> tuple[QImage, QPoint]:
    """`frame` (in `img` coordinates) is the layer's full extent for the
    overlays that are laid out over it (gradient, pattern) — by default the
    whole image. A live-rendered layer passes its content frame, so the
    overlay spans the layer (like Photoshop) even when `img` is only the
    visible part of it at screen resolution."""
    if not styles or img.isNull():
        return img, QPoint(0, 0)

    pad = layer_styles_padding(styles)
    w, h = img.width(), img.height()
    out_w, out_h = w + pad * 2, h + pad * 2
    
    result = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(0)
    
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Overlays, bottom to top as in Photoshop: pattern, gradient, colour.
    base_img = img.copy()
    po = styles.get("pattern_overlay")
    if po and po.get("enabled"):
        path = po.get("pattern", "")
        pixmap = QPixmap(path) if path and os.path.exists(path) else QPixmap()
        if not pixmap.isNull():
            b = QBrush(pixmap)
            t = QTransform()
            t.scale(po.get("scale", 100) / 100.0, po.get("scale", 100) / 100.0)
            if frame is not None:   # the pattern is anchored to the layer, not to this image
                t = t * QTransform.fromTranslate(frame.x(), frame.y())
            b.setTransform(t)
            base_img = _blend_overlay(base_img, b, po.get("blend_mode", "SourceOver"), po.get("opacity", 100))

    go = styles.get("gradient_overlay")
    if go and go.get("enabled"):
        # Same gradient model as fills/shapes/the Gradient tool. The
        # style's angle is stored math-style (counter-clockwise, y up);
        # Gradient angles are screen-clockwise, hence the sign flip.
        from core.gradient_model import Gradient, GRADIENT_STYLES
        stops = go.get("stops", [(0.0, QColor(0,0,0)), (1.0, QColor(255,255,255))])
        gtype = go.get("type", "linear")
        g = Gradient.from_merged_stops(stops, style=gtype if gtype in GRADIENT_STYLES else "linear",
                                       angle=-float(go.get("angle", 90)),
                                       scale=float(go.get("scale", 100)),
                                       reverse=bool(go.get("reverse", False)))
        brush = g.brush(frame if frame is not None else QRectF(0, 0, w, h), 0.0, QTransform(),
                        base_img.rect())
        base_img = _blend_overlay(base_img, brush, go.get("blend_mode", "SourceOver"), go.get("opacity", 100))

    co = styles.get("color_overlay")
    if co and co.get("enabled"):
        base_img = _blend_overlay(base_img, QBrush(QColor(co.get("color", QColor(255, 0, 0)))),
                                  co.get("blend_mode", "SourceOver"), co.get("opacity", 100))

    from core.pixel_buffer import qimage_argb_view
    arr = qimage_argb_view(img, writable=False)[:, :w]
    alpha_np = arr[..., 3]
    
    def get_blurred_alpha(blur_r, dx=0, dy=0):
        mask = np.zeros((out_h, out_w), dtype=np.uint8)
        sy1, sy2 = pad + dy, pad + dy + h
        sx1, sx2 = pad + dx, pad + dx + w
        my1, my2 = max(0, sy1), min(out_h, sy2)
        mx1, mx2 = max(0, sx1), min(out_w, sx2)
        ay1, ay2 = my1 - sy1, my1 - sy1 + (my2 - my1)
        ax1, ax2 = mx1 - sx1, mx1 - sx1 + (mx2 - mx1)
        if my1 < my2 and mx1 < mx2:
            mask[my1:my2, mx1:mx2] = alpha_np[ay1:ay2, ax1:ax2]
        if blur_r > 0:
            mask = _blur_mask(mask, int(blur_r))
        return mask
        
    def render_effect_layer(mask, color, opacity, mode):
        if not np.any(mask): return
        eff = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
        eff.fill(0)
        e_arr = qimage_argb_view(eff, writable=True)[:, :out_w]
        c_np = np.array([color.blue(), color.green(), color.red()], dtype=np.float32)
        alpha_f = (mask.astype(np.float32) / 255.0) * (opacity / 100.0)
        e_arr[..., 0] = (c_np[0] * alpha_f).astype(np.uint8)
        e_arr[..., 1] = (c_np[1] * alpha_f).astype(np.uint8)
        e_arr[..., 2] = (c_np[2] * alpha_f).astype(np.uint8)
        e_arr[..., 3] = (alpha_f * 255).astype(np.uint8)
        painter.setCompositionMode(mode)
        painter.drawImage(0, 0, eff)

    ds = styles.get("drop_shadow")
    if ds and ds.get("enabled"):
        dist = ds.get("distance", 5)
        angle = math.radians(ds.get("angle", 90))
        dx, dy = int(dist * math.cos(angle)), int(-dist * math.sin(angle))
        mask = get_blurred_alpha(ds.get("size", 5), dx, dy)
        render_effect_layer(mask, ds.get("color", QColor(0,0,0)), ds.get("opacity", 75), _get_comp_mode(ds.get("blend_mode", "Multiply")))

    og = styles.get("outer_glow")
    if og and og.get("enabled"):
        mask = get_blurred_alpha(og.get("size", 5), 0, 0)
        render_effect_layer(mask, og.get("color", QColor(255,255,150)), og.get("opacity", 75), _get_comp_mode(og.get("blend_mode", "Screen")))
        
    st = styles.get("stroke")
    stroke_mask = None
    if st and st.get("enabled") and st.get("size", 3) > 0:
        stroke_mask = stroke_coverage(get_blurred_alpha(0, 0, 0), float(st.get("size", 3)),
                                      st.get("position", "outside"))

    def render_stroke():
        render_effect_layer(stroke_mask, st.get("color", QColor(0, 0, 0)), st.get("opacity", 100),
                            _get_comp_mode(st.get("blend_mode", "SourceOver")))

    # An outside stroke lies under the layer's pixels; inside / centre ones
    # cover their edge, so they're drawn after them.
    if stroke_mask is not None and st.get("position", "outside") == "outside":
        render_stroke()

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    # Fill opacity (Photoshop's "Fill"): the layer's own pixels and its
    # overlays fade, the effects around them don't.
    painter.setOpacity(fill_opacity(styles) / 100.0)
    painter.drawImage(pad, pad, base_img)
    painter.setOpacity(1.0)

    if stroke_mask is not None and st.get("position", "outside") != "outside":
        render_stroke()

    ins = styles.get("inner_shadow")
    if ins and ins.get("enabled"):
        dist, angle = ins.get("distance", 5), math.radians(ins.get("angle", 90))
        dx, dy = int(dist * math.cos(angle)), int(-dist * math.sin(angle))
        orig_mask = get_blurred_alpha(0, 0, 0)
        mask = (255 - get_blurred_alpha(ins.get("size", 5), dx, dy)).astype(np.float32)
        mask = (mask * (orig_mask.astype(np.float32) / 255.0)).astype(np.uint8)
        render_effect_layer(mask, ins.get("color", QColor(0,0,0)), ins.get("opacity", 75), _get_comp_mode(ins.get("blend_mode", "Multiply")))

    ig = styles.get("inner_glow")
    if ig and ig.get("enabled"):
        orig_mask = get_blurred_alpha(0, 0, 0)
        shifted = get_blurred_alpha(ig.get("size", 5), 0, 0).astype(np.float32)
        mask = (255.0 - shifted) * (orig_mask.astype(np.float32) / 255.0)
        mask = np.clip(mask, 0, 255).astype(np.uint8)
        render_effect_layer(mask, ig.get("color", QColor(255,255,150)), ig.get("opacity", 75), _get_comp_mode(ig.get("blend_mode", "Screen")))

    sat = styles.get("satin")
    if sat and sat.get("enabled"):
        dist, angle = sat.get("distance", 11), math.radians(sat.get("angle", 90))
        dx, dy = int(dist * math.cos(angle)), int(-dist * math.sin(angle))
        orig_mask = get_blurred_alpha(0, 0, 0)
        mask1 = get_blurred_alpha(0, dx, dy).astype(np.float32)
        mask2 = get_blurred_alpha(0, -dx, -dy).astype(np.float32)
        satin_mask = (255.0 - np.abs(mask1 - mask2)) * (orig_mask.astype(np.float32) / 255.0)
        blur_size = int(sat.get("size", 14))
        if blur_size > 0:
            satin_mask = _blur_mask(np.clip(satin_mask, 0, 255).astype(np.uint8), blur_size).astype(np.float32)
        render_effect_layer(np.clip(satin_mask, 0, 255).astype(np.uint8), sat.get("color", QColor(0,0,0)), sat.get("opacity", 50), _get_comp_mode(sat.get("blend_mode", "Multiply")))

    bevel = styles.get("bevel")
    if bevel and bevel.get("enabled"):
        dist, angle = bevel.get("distance", 5), math.radians(bevel.get("angle", 90))
        dx, dy = int(dist * math.cos(angle)), int(-dist * math.sin(angle))
        orig_mask = get_blurred_alpha(0, 0, 0)
        blur_size = int(bevel.get("size", 5))
        hl_mask = np.clip(orig_mask.astype(np.float32) - get_blurred_alpha(blur_size, dx, dy).astype(np.float32), 0, 255).astype(np.uint8)
        sh_mask = np.clip(orig_mask.astype(np.float32) - get_blurred_alpha(blur_size, -dx, -dy).astype(np.float32), 0, 255).astype(np.uint8)
        render_effect_layer(hl_mask, bevel.get("color", QColor(255,255,255)), bevel.get("opacity", 75), _get_comp_mode("Screen"))
        render_effect_layer(sh_mask, bevel.get("shadow_color", QColor(0,0,0)), bevel.get("opacity", 75), _get_comp_mode("Multiply"))

    painter.end()
    return result, QPoint(-pad, -pad)