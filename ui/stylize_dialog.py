"""Filter > Stylize gallery (see ui/filter_gallery.py)."""
import numpy as np

from tools.tool_utils import fast_box_blur_np
from ui.filter_gallery import Choice, FilterGalleryDialog, FilterMode, Slider


def apply_kuwahara(arr, r):
    """Powerful Kuwahara mathematical filter using integral images."""
    if r <= 0: return arr.copy()
    h, w = arr.shape[:2]
    pad_arr = np.pad(arr, ((r+1, r+1), (r+1, r+1), (0, 0)), mode='edge').astype(np.float32)
    
    # float64 protects against overflow on large photos
    int_img = np.cumsum(np.cumsum(pad_arr, axis=0, dtype=np.float64), axis=1, dtype=np.float64)
    intensity = 0.299 * pad_arr[..., 2] + 0.587 * pad_arr[..., 1] + 0.114 * pad_arr[..., 0]
    int_i = np.cumsum(np.cumsum(intensity, axis=0, dtype=np.float64), axis=1, dtype=np.float64)
    int_i2 = np.cumsum(np.cumsum(intensity**2, axis=0, dtype=np.float64), axis=1, dtype=np.float64)
    
    def region_stats(dy1, dy2, dx1, dx2):
        y2 = np.arange(r+1, r+1+h) + dy2; y1m1 = np.arange(r+1, r+1+h) + dy1 - 1
        x2 = np.arange(r+1, r+1+w) + dx2; x1m1 = np.arange(r+1, r+1+w) + dx1 - 1
        Y2, X2 = np.ix_(y2, x2); Y1m1, X1m1 = np.ix_(y1m1, x1m1)
        Y2_X1m1 = np.ix_(y2, x1m1); Y1m1_X2 = np.ix_(y1m1, x2)
        area = (dy2 - dy1 + 1) * (dx2 - dx1 + 1)
        S = int_i[Y2, X2] - int_i[Y1m1_X2] - int_i[Y2_X1m1] + int_i[Y1m1, X1m1]
        S2 = int_i2[Y2, X2] - int_i2[Y1m1_X2] - int_i2[Y2_X1m1] + int_i2[Y1m1, X1m1]
        var = np.abs(S2 - (S**2)/area) / area
        C = int_img[Y2, X2] - int_img[Y1m1_X2] - int_img[Y2_X1m1] + int_img[Y1m1, X1m1]
        return var, C / area
        
    v1, m1 = region_stats(-r, 0, -r, 0)
    v2, m2 = region_stats(-r, 0, 0, r)
    v3, m3 = region_stats(0, r, -r, 0)
    v4, m4 = region_stats(0, r, 0, r)
    
    vars_stack = np.stack([v1, v2, v3, v4], axis=-1)
    means_stack = np.stack([m1, m2, m3, m4], axis=3)
    min_idx = np.argmin(vars_stack, axis=-1)
    Y, X = np.ogrid[:h, :w]
    res = np.empty((h, w, 3), dtype=np.float32)
    for c in range(3): res[..., c] = means_stack[Y, X, c, min_idx]
    return res


def _shift_clamped(gray, dx, dy):
    """gray shifted by (-dx, -dy), edge rows/columns kept from gray."""
    shifted = np.roll(np.roll(gray, -dy, axis=0), -dx, axis=1)
    if dy > 0: shifted[-dy:, :] = gray[-dy:, :]
    elif dy < 0: shifted[:-dy, :] = gray[:-dy, :]
    if dx > 0: shifted[:, -dx:] = gray[:, -dx:]
    elif dx < 0: shifted[:, :-dx] = gray[:, :-dx]
    return shifted


class Emboss(FilterMode):
    key, title_key = "emboss", "menu.stylize.emboss"
    params = (Slider("angle", "stylize.angle", -180, 180, 135),
              Slider("height", "stylize.height", 1, 10, 3, spatial=True),
              Slider("amount", "stylize.amount", 1, 500, 100))

    def apply(self, src, p, ctx):
        res = src.copy()
        a = np.radians(p["angle"])
        dx, dy = int(np.round(np.cos(a) * p["height"])), int(np.round(np.sin(a) * p["height"]))
        arr_f = src[..., :3].astype(np.float32)
        gray = 0.299 * arr_f[..., 2] + 0.587 * arr_f[..., 1] + 0.114 * arr_f[..., 0]
        out = 128 + (_shift_clamped(gray, dx, dy) - gray) * (p["amount"] / 100.0)
        res[..., 0] = res[..., 1] = res[..., 2] = np.clip(out, 0, 255).astype(np.uint8)
        return res


class Extrude(FilterMode):
    key, title_key = "extrude", "menu.stylize.extrude"
    params = (Slider("size", "stylize.size", 2, 255, 30, spatial=True),
              Slider("depth", "stylize.depth", 1, 255, 30, spatial=True))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        size, depth = p["size"], p["depth"]
        Y, X = np.ogrid[:h, :w]
        grid_Y, grid_X = Y // size, X // size
        depths = np.random.RandomState(42).randint(1, depth + 1, (h // size + 1, w // size + 1))
        block_depths = depths[grid_Y, grid_X]
        cy = np.clip(grid_Y * size + size // 2, 0, h - 1)
        cx = np.clip(grid_X * size + size // 2, 0, w - 1)
        block_colors = src[cy, cx, :3]
        inner_y, inner_x = Y % size, X % size
        shade = np.ones((h, w, 3), dtype=np.float32)
        border = np.clip(block_depths // 2, 1, size // 2)
        shade[inner_y < border] = 1.3
        shade[inner_x < border] = 1.1
        shade[inner_y > (size - border)] = 0.7
        shade[inner_x > (size - border)] = 0.5
        res[..., :3] = np.clip(block_colors * shade, 0, 255).astype(np.uint8)
        return res


class FindEdges(FilterMode):
    key, title_key = "find_edges", "menu.stylize.find_edges"

    def apply(self, src, p, ctx):
        res = src.copy()
        arr_f = src[..., :3].astype(np.int16)
        gx = np.abs(np.roll(arr_f, -1, axis=1) - np.roll(arr_f, 1, axis=1))
        gy = np.abs(np.roll(arr_f, -1, axis=0) - np.roll(arr_f, 1, axis=0))
        res[..., :3] = 255 - np.clip(gx + gy, 0, 255).astype(np.uint8)
        return res


class OilPaint(FilterMode):
    key, title_key = "oil_paint", "menu.stylize.oil_paint"
    params = (Slider("stylization", "stylize.stylization", 1, 10, 5, spatial=True),
              Slider("cleanliness", "stylize.cleanliness", 0, 10, 3, spatial=True),
              Slider("scale", "stylize.scale", 1, 10, 5, spatial=True),
              Slider("bristle", "stylize.bristle", 0, 10, 5),
              Slider("angle", "stylize.angle", -180, 180, 90),
              Slider("shine", "stylize.shine", 0, 100, 25))

    def apply(self, src, p, ctx):
        res = src.copy()
        stylization, cleanliness, scale = p["stylization"], p["cleanliness"], p["scale"]
        base = src[..., :3].copy()
        if cleanliness > 0:
            base = fast_box_blur_np(base, cleanliness)
        base = base.astype(np.float32)
        if stylization > 0:
            base = apply_kuwahara(base, stylization)
            if cleanliness > 5:
                base = apply_kuwahara(base, stylization // 2)
        if p["shine"] > 0:
            gray = 0.299 * base[..., 2] + 0.587 * base[..., 1] + 0.114 * base[..., 0]
            smooth_radius = 10 - p["bristle"]
            if smooth_radius > 0:
                gray_3d = np.repeat(gray[..., np.newaxis], 3, axis=2).astype(np.uint8)
                gray = fast_box_blur_np(gray_3d, smooth_radius)[..., 0].astype(np.float32)
            a = np.radians(p["angle"])
            dx, dy = int(np.round(np.cos(a) * scale)), int(np.round(np.sin(a) * scale))
            if dx == 0 and dy == 0:
                dx = 1
            bump = (gray - _shift_clamped(gray, dx, dy)) * (p["shine"] / 100.0) * 1.5
            base = np.clip(base + bump[..., np.newaxis], 0, 255)
        res[..., :3] = base.astype(np.uint8)
        return res


class Solarize(FilterMode):
    key, title_key = "solarize", "menu.stylize.solarize"
    params = (Slider("threshold", "adj.threshold.threshold", 0, 255, 128),)

    def apply(self, src, p, ctx):
        res = src.copy()
        c = src[..., :3]
        res[..., :3] = np.where(c > p["threshold"], 255 - c, c)
        return res


class Tiles(FilterMode):
    key, title_key = "tiles", "menu.stylize.tiles"
    params = (Slider("count", "stylize.tiles_num", 10, 99, 10),
              Slider("offset", "stylize.offset", 1, 90, 10))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        size = max(2, w // p["count"])
        pct = p["offset"]
        Y, X = np.ogrid[:h, :w]
        grid_Y, grid_X = Y // size, X // size
        rng = np.random.RandomState(42)
        lo, hi = -size * pct // 100, size * pct // 100 + 1      # floor of the negative bound
        shift_y = rng.randint(lo, hi, (h // size + 1, w // size + 1))
        shift_x = rng.randint(lo, hi, (h // size + 1, w // size + 1))
        src_Y = np.clip(Y + shift_y[grid_Y, grid_X], 0, h - 1)
        src_X = np.clip(X + shift_x[grid_Y, grid_X], 0, w - 1)
        gap = max(1, size // 10)
        is_gap = ((Y % size) < gap) | ((X % size) < gap)
        res[..., :3] = np.where(is_gap[..., np.newaxis], ctx.bgr(ctx.bg), src[src_Y, src_X, :3])
        return res


class TraceContour(FilterMode):
    key, title_key = "trace_contour", "menu.stylize.trace_contour"
    params = (Slider("level", "stylize.level", 0, 255, 128),
              Choice("edge", "stylize.edge", (("stylize.lower", 0), ("stylize.upper", 1))))

    def apply(self, src, p, ctx):
        res = src.copy()
        c = src[..., :3]
        mask = c <= p["level"] if p["edge"] == 0 else c >= p["level"]
        edges = (mask ^ np.roll(mask, 1, axis=0)) | (mask ^ np.roll(mask, 1, axis=1))
        res[..., :3] = np.where(edges, c, 255)
        return res


class Wind(FilterMode):
    key, title_key = "wind", "menu.stylize.wind"
    params = (Choice("method", "stylize.method", (("stylize.wind.wind", 0), ("stylize.wind.blast", 1),
                                                  ("stylize.wind.stagger", 2))),
              Choice("direction", "stylize.direction", (("stylize.right", 0), ("stylize.left", 1))))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        method = p["method"]
        f = src[..., :3].copy()
        rng = np.random.RandomState(42)
        prob = 0.05 if method == 0 else 0.15 if method == 1 else 0.1
        length = 20 if method == 0 else 40 if method == 1 else 10
        for i in range(1, length):
            mask = rng.rand(h, w, 1) < prob
            if p["direction"] == 0:
                shifted = np.roll(f, i, axis=1); shifted[:, :i] = f[:, :i]
            else:
                shifted = np.roll(f, -i, axis=1); shifted[:, -i:] = f[:, -i:]
            f = np.where(mask, shifted, f)
        res[..., :3] = f
        return res


class StylizeDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.stylize"
    MODES = {m.key: m for m in (Emboss, Extrude, FindEdges, OilPaint, Solarize, Tiles, TraceContour, Wind)}
