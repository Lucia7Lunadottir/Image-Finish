"""Filter > Other gallery (see ui/filter_gallery.py)."""
import numpy as np

from tools.tool_utils import fast_box_blur_np
from ui.filter_gallery import Choice, FilterGalleryDialog, FilterMode, Kernel3, Slider, Spin


class HighPass(FilterMode):
    key, title_key = "high_pass", "menu.other.high_pass"
    params = (Slider("radius", "other.radius", 1, 250, 10, spatial=True),)

    def apply(self, src, p, ctx):
        res = src.copy()
        blurred = fast_box_blur_np(src, p["radius"])
        out = src[..., :3].astype(np.float32) - blurred[..., :3].astype(np.float32) + 128.0
        res[..., :3] = np.clip(out, 0, 255).astype(np.uint8)
        return res


class Minimum(FilterMode):
    key, title_key = "minimum", "menu.other.minimum"
    params = (Slider("radius", "other.radius", 1, 100, 1, spatial=True),)
    op = staticmethod(np.minimum)

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        r, op = p["radius"], self.op
        padded_x = np.pad(src[..., :3], ((0, 0), (r, r), (0, 0)), mode='edge')
        tmp = padded_x[:, r:w + r, :]
        for i in range(-r, r + 1):
            tmp = op(tmp, padded_x[:, r + i: w + r + i, :]) if i != -r else padded_x[:, r + i: w + r + i, :]
        padded_y = np.pad(tmp, ((r, r), (0, 0), (0, 0)), mode='edge')
        out = padded_y[r:h + r, :, :]
        for i in range(-r, r + 1):
            out = op(out, padded_y[r + i: h + r + i, :, :]) if i != -r else padded_y[r + i: h + r + i, :, :]
        res[..., :3] = out
        return res


class Maximum(Minimum):
    key, title_key = "maximum", "menu.other.maximum"
    op = staticmethod(np.maximum)


class Offset(FilterMode):
    key, title_key = "offset", "menu.other.offset"
    params = (Spin("dx", "other.horiz", -9999, 9999, 0, spatial=True),
              Spin("dy", "other.vert", -9999, 9999, 0, spatial=True),
              Choice("edge", "other.edge", (("other.wrap", 0), ("other.repeat", 1), ("other.bg", 2))))

    def apply(self, src, p, ctx):
        h, w = src.shape[:2]
        dx, dy = p["dx"], p["dy"]
        if p["edge"] == 0:
            return np.roll(np.roll(src, dy, axis=0), dx, axis=1)
        if p["edge"] == 1:
            Y, X = np.ogrid[:h, :w]
            return src[np.clip(Y - dy, 0, h - 1), np.clip(X - dx, 0, w - 1)]
        res = np.zeros_like(src)
        y1s, y2s = max(0, -dy), min(h, h - dy)
        x1s, x2s = max(0, -dx), min(w, w - dx)
        y1d, y2d = max(0, dy), min(h, h + dy)
        x1d, x2d = max(0, dx), min(w, w + dx)
        if y1s < y2s and x1s < x2s:
            res[y1d:y2d, x1d:x2d] = src[y1s:y2s, x1s:x2s]
        return res


class Custom(FilterMode):
    key, title_key = "custom", "menu.other.custom"
    params = (Kernel3("kernel"),
              Spin("scale", "other.scale", 1, 9999, 1),
              Spin("offset", "other.offset_val", -9999, 9999, 0))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        kernel = np.array(p["kernel"], dtype=np.float32).reshape(3, 3)
        padded = np.pad(src[..., :3].astype(np.float32), ((1, 1), (1, 1), (0, 0)), mode='edge')
        out = np.zeros((h, w, 3), dtype=np.float32)
        for dy in range(3):
            for dx in range(3):
                if kernel[dy, dx] != 0:
                    out += padded[dy:h + dy, dx:w + dx] * kernel[dy, dx]
        res[..., :3] = np.clip(out / p["scale"] + p["offset"], 0, 255).astype(np.uint8)
        return res


class OtherFiltersDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.other"
    MODES = {m.key: m for m in (Custom, HighPass, Maximum, Minimum, Offset)}
