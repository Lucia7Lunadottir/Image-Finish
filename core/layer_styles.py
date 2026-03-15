import math
import numpy as np
import ctypes
from PyQt6.QtGui import QImage, QPainter, QColor, QBrush, QLinearGradient
from PyQt6.QtCore import QPoint
from core.adjustments.hdr_toning import _gauss_blur

def _get_comp_mode(mode_str):
    from PyQt6.QtGui import QPainter
    mapping = {
        "SourceOver": QPainter.CompositionMode.CompositionMode_SourceOver,
        "Multiply": QPainter.CompositionMode.CompositionMode_Multiply,
        "Screen": QPainter.CompositionMode.CompositionMode_Screen,
        "Overlay": QPainter.CompositionMode.CompositionMode_Overlay,
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
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, go.get("color1", QColor(255,255,255)))
        grad.setColorAt(1, go.get("color2", QColor(0,0,0)))
        bp.setOpacity(go.get("opacity", 100) / 100.0)
        bp.fillRect(base_img.rect(), QBrush(grad))
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
            mask_f = mask.astype(np.float32) / 255.0
            mask_3d = mask_f[..., np.newaxis].repeat(3, axis=2)
            blurred = _gauss_blur(mask_3d, blur_r)
            mask = (blurred[..., 0] * 255).astype(np.uint8)
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

    painter.end()
    return result, QPoint(-pad, -pad)