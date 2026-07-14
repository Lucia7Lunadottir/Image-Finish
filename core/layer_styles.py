import os
import math
import numpy as np
import ctypes
from PyQt6.QtGui import QImage, QPainter, QColor, QBrush, QLinearGradient, QRadialGradient, QPixmap, QTransform
from PyQt6.QtCore import QPoint, Qt
from core.adjustments.hdr_toning import _gauss_blur


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

def _get_comp_mode(mode_str):
    from PyQt6.QtGui import QPainter
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

def apply_layer_styles(img: QImage, styles: dict) -> tuple[QImage, QPoint]:
    if not styles or img.isNull():
        return img, QPoint(0, 0)
        
    pad = 0
    for key, opts in styles.items():
        if not opts.get("enabled"): continue
        if key == "drop_shadow":
            pad = max(pad, opts.get("distance", 0) + opts.get("size", 0) * 2)
        elif key in ("outer_glow", "inner_shadow"):
            pad = max(pad, opts.get("size", 0) * 2)
        elif key == "stroke":
            pad = max(pad, opts.get("size", 0))
            
    pad = int(math.ceil(pad)) + 4
    w, h = img.width(), img.height()
    out_w, out_h = w + pad * 2, h + pad * 2
    
    result = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(0)
    
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    base_img = img.copy()
    bp = QPainter(base_img)
    
    co = styles.get("color_overlay")
    if co and co.get("enabled"):
        bp.setCompositionMode(_get_comp_mode(co.get("blend_mode", "SourceOver")))
        c = QColor(co.get("color", QColor(255,0,0)))
        c.setAlphaF(co.get("opacity", 100) / 100.0)
        bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        bp.fillRect(base_img.rect(), c)
        
    go = styles.get("gradient_overlay")
    if go and go.get("enabled"):
        bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        
        stops = go.get("stops", [(0.0, QColor(0,0,0)), (1.0, QColor(255,255,255))])
        gtype = go.get("type", "linear")
        angle = math.radians(go.get("angle", 90))
        cx, cy = w / 2.0, h / 2.0
        
        if gtype == "radial":
            grad = QRadialGradient(cx, cy, math.hypot(w, h) / 2.0)
        else:
            # Calculate ideal gradient vector for filling the entire rectangle at an angle
            r = (w * abs(math.cos(angle)) + h * abs(math.sin(angle))) / 2.0
            sx, sy = cx - r * math.cos(angle), cy + r * math.sin(angle)
            ex, ey = cx + r * math.cos(angle), cy - r * math.sin(angle)
            grad = QLinearGradient(sx, sy, ex, ey)
            
        for pos, color in stops:
            grad.setColorAt(pos, QColor(color))
            
        bp.setOpacity(go.get("opacity", 100) / 100.0)
        bp.fillRect(base_img.rect(), QBrush(grad))
        
    po = styles.get("pattern_overlay")
    if po and po.get("enabled"):
        bp.setCompositionMode(_get_comp_mode(po.get("blend_mode", "SourceOver")))
        path = po.get("pattern", "")
        if path and os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                scale = po.get("scale", 100) / 100.0
                b = QBrush(pixmap)
                t = QTransform()
                t.scale(scale, scale)
                b.setTransform(t)
                bp.setOpacity(po.get("opacity", 100) / 100.0)
                bp.fillRect(base_img.rect(), b)
    bp.end()

    ptr = img.constBits()
    buf = (ctypes.c_uint8 * img.sizeInBytes()).from_address(int(ptr))
    arr = np.ndarray((h, img.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=buf)[:, :w]
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
        e_ptr = eff.bits()
        e_buf = (ctypes.c_uint8 * eff.sizeInBytes()).from_address(int(e_ptr))
        e_arr = np.ndarray((out_h, eff.bytesPerLine() // 4, 4), dtype=np.uint8, buffer=e_buf)[:, :out_w]
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
    if st and st.get("enabled"):
        size = st.get("size", 3)
        if size > 0:
            mask = get_blurred_alpha(size, 0, 0)
            mask[mask > 10] = 255
            mask[get_blurred_alpha(0, 0, 0) > 128] = 0
            render_effect_layer(mask, st.get("color", QColor(0,0,0)), st.get("opacity", 100), _get_comp_mode(st.get("blend_mode", "SourceOver")))

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawImage(pad, pad, base_img)

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