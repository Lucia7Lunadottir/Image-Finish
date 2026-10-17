"""Filter > Noise gallery (see ui/filter_gallery.py)."""
import numpy as np

from tools.tool_utils import fast_box_blur_np
from ui.filter_gallery import Check, Choice, FilterGalleryDialog, FilterMode, Slider


class AddNoise(FilterMode):
    key, title_key = "add_noise", "menu.noise.add"
    params = (Slider("amount", "noise.amount", 1, 400, 12),
              Choice("distribution", "noise.distribution", (("noise.uniform", 0), ("noise.gaussian", 1))),
              Check("mono", "noise.monochromatic"))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        amt = p["amount"] / 100.0
        shape = (h, w, 1) if p["mono"] else (h, w, 3)
        if p["distribution"] == 1:
            noise = np.random.normal(0, amt * 127, shape)
        else:
            noise = np.random.uniform(-amt * 255, amt * 255, shape)
        res[..., :3] = np.clip(src[..., :3].astype(np.float32) + noise, 0, 255).astype(np.uint8)
        return res


class Despeckle(FilterMode):
    key, title_key = "despeckle", "menu.noise.despeckle"

    def apply(self, src, p, ctx):
        # scipy.ndimage.median_filter instead of stacking all 9 shifted
        # copies of the image (was a (h, w, 3, 9) allocation — tens of GB
        # and a multi-minute hang on 8K-16K images; verified pixel-identical
        # to the old stack+np.median approach at mode='nearest' == 'edge' padding).
        from scipy.ndimage import median_filter
        res = src.copy()
        res[..., :3] = median_filter(src[..., :3], size=(3, 3, 1), mode='nearest')
        return res


class Median(FilterMode):
    key, title_key = "median", "menu.noise.median"
    params = (Slider("radius", "noise.radius", 1, 50, 1, spatial=True),)

    def _threshold(self, p):
        return 0

    def apply(self, src, p, ctx):
        from scipy.ndimage import median_filter
        res = src.copy()
        current = src[..., :3].copy()
        # Repeated 3x3 passes emulate a wide median without the cost of one.
        for _ in range(min(p["radius"], 10)):
            current = median_filter(current, size=(3, 3, 1), mode='nearest')
        thresh = self._threshold(p)
        if thresh > 0:
            diff = np.abs(src[..., :3].astype(np.int16) - current.astype(np.int16))
            mask = np.max(diff, axis=-1, keepdims=True) > thresh
            res[..., :3] = np.where(mask, current, src[..., :3])
        else:
            res[..., :3] = current
        return res


class DustScratches(Median):
    key, title_key = "dust_scratches", "menu.noise.dust"
    params = (Slider("radius", "noise.radius", 1, 50, 1, spatial=True),
              Slider("threshold", "noise.threshold", 0, 255, 0))

    def _threshold(self, p):
        return p["threshold"]


class ReduceNoise(FilterMode):
    key, title_key = "reduce_noise", "menu.noise.reduce"
    params = (Slider("strength", "noise.strength", 1, 10, 5, spatial=True),
              Slider("preserve", "noise.preserve", 0, 100, 50),
              Slider("color", "noise.color", 0, 100, 50))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        st = p["strength"]
        pr = p["preserve"] / 100.0
        cn = p["color"] / 100.0
        blurred = fast_box_blur_np(src, st * 2)
        if cn > 0:
            luma = src[..., :3].mean(axis=-1, keepdims=True)
            chroma = src[..., :3].astype(np.float32) - luma
            chroma_arr = np.clip(chroma + 128, 0, 255).astype(np.uint8)
            chroma_arr = np.concatenate([chroma_arr, np.zeros((h, w, 1), dtype=np.uint8)], axis=-1)
            chroma_blurred = fast_box_blur_np(chroma_arr, st * 3)[..., :3].astype(np.float32) - 128
            chroma = chroma * (1 - cn) + chroma_blurred * cn
            base = np.clip(luma + chroma, 0, 255).astype(np.uint8)
        else:
            base = src[..., :3].copy()
        diff = np.abs(base.astype(np.float32) - blurred[..., :3].astype(np.float32)).mean(axis=-1, keepdims=True)
        weight = np.clip(1.0 - (diff / (5 + pr * 45)), 0.0, 1.0)
        final = base.astype(np.float32) * (1 - weight) + blurred[..., :3].astype(np.float32) * weight
        res[..., :3] = final.astype(np.uint8)
        return res


class NoiseDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.noise"
    MODES = {m.key: m for m in (AddNoise, Despeckle, DustScratches, Median, ReduceNoise)}
