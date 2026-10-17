"""Filter > Sharpen gallery (see ui/filter_gallery.py)."""
import numpy as np

from tools.tool_utils import fast_box_blur_np
from ui.filter_gallery import FilterGalleryDialog, FilterMode, Slider


def apply_conv3x3(arr, kernel):
    h, w = arr.shape[:2]
    padded = np.pad(arr[..., :3].astype(np.float32), ((1,1),(1,1),(0,0)), mode='edge')
    res = np.zeros((h, w, 3), dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            if kernel[dy, dx] != 0:
                res += padded[dy:h+dy, dx:w+dx] * kernel[dy, dx]
    return np.clip(res, 0, 255).astype(np.uint8)


_SHARPEN = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
_SHARPEN_MORE = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)


class Sharpen(FilterMode):
    key, title_key = "sharpen", "menu.sharpen.sharpen"
    kernel = _SHARPEN

    def apply(self, src, p, ctx):
        res = src.copy()
        res[..., :3] = apply_conv3x3(src, self.kernel)
        return res


class SharpenMore(Sharpen):
    key, title_key = "more", "menu.sharpen.more"
    kernel = _SHARPEN_MORE


class SharpenEdges(FilterMode):
    key, title_key = "edges", "menu.sharpen.edges"

    def apply(self, src, p, ctx):
        res = src.copy()
        gray = 0.299 * src[..., 2] + 0.587 * src[..., 1] + 0.114 * src[..., 0]
        gy = np.abs(np.roll(gray, -1, axis=0) - gray)
        gx = np.abs(np.roll(gray, -1, axis=1) - gray)
        edges = (gx + gy) > 15
        sharp = apply_conv3x3(src, _SHARPEN)
        res[edges, :3] = sharp[edges]
        return res


def _unsharp(src, amount, radius_tenths, noise_tenths=0, threshold=None):
    """Shared by Unsharp Mask and Smart Sharpen. radius/noise in 0.1 px."""
    res = src.copy()
    amt = amount / 100.0
    rad = max(1, radius_tenths // 10)
    base = src[..., :3].copy()
    if noise_tenths > 0:
        base = fast_box_blur_np(base, max(1, noise_tenths // 10))
    blurred = fast_box_blur_np(base, rad)
    diff = src[..., :3].astype(np.int16) - blurred.astype(np.int16)
    mask = True if threshold is None else np.max(np.abs(diff), axis=-1, keepdims=True) > threshold
    sharpened = np.clip(src[..., :3].astype(np.float32) + diff * amt, 0, 255).astype(np.uint8)
    res[..., :3] = np.where(mask, sharpened, src[..., :3])
    return res


class UnsharpMask(FilterMode):
    key, title_key = "unsharp", "menu.sharpen.unsharp"
    params = (Slider("amount", "sharpen.amount", 1, 500, 50),
              Slider("radius", "sharpen.radius", 1, 250, 10, spatial=True),     # 0.1 px
              Slider("threshold", "sharpen.threshold", 0, 255, 0))

    def apply(self, src, p, ctx):
        return _unsharp(src, p["amount"], p["radius"], threshold=p["threshold"])


class SmartSharpen(FilterMode):
    key, title_key = "smart", "menu.sharpen.smart"
    params = (Slider("amount", "sharpen.amount", 1, 500, 100),
              Slider("radius", "sharpen.radius", 1, 250, 10, spatial=True),
              Slider("noise", "sharpen.reduce_noise", 0, 100, 10, spatial=True))

    def apply(self, src, p, ctx):
        return _unsharp(src, p["amount"], p["radius"], noise_tenths=p["noise"])


class SharpenDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.sharpen_gallery"
    MODES = {m.key: m for m in (Sharpen, SharpenMore, SharpenEdges, UnsharpMask, SmartSharpen)}
