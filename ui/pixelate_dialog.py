"""Filter > Pixelate gallery (see ui/filter_gallery.py)."""
import numpy as np

from ui.filter_gallery import Choice, FilterGalleryDialog, FilterMode, Slider


class Mosaic(FilterMode):
    key, title_key = "mosaic", "menu.pixelate.mosaic"
    params = (Slider("size", "pixelate.radius", 2, 200, 10, spatial=True),)

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        s = max(2, p["size"])
        Y, X = np.ogrid[:h, :w]
        res[..., :3] = src[np.clip((Y // s) * s + s // 2, 0, h - 1), np.clip((X // s) * s + s // 2, 0, w - 1), :3]
        return res


def _jittered_cells(h, w, s):
    """Nearest jittered seed per pixel: (owner_y, owner_x, squared distance)."""
    small_h, small_w = (h + s - 1) // s, (w + s - 1) // s
    grid_y, grid_x = np.mgrid[:small_h, :small_w]
    cy = grid_y * s + s // 2
    cx = grid_x * s + s // 2
    rng = np.random.RandomState(42)
    cy = np.clip(cy + rng.randint(-s // 2, s // 2, (small_h, small_w)), 0, h - 1)
    cx = np.clip(cx + rng.randint(-s // 2, s // 2, (small_h, small_w)), 0, w - 1)
    # Nearest-seed lookup via a Euclidean distance transform instead of a
    # hand-rolled 3x3-neighbor search: the old version materialized several
    # full (h, w) arrays nine times — multi-gigabyte allocations and
    # minutes-long hangs on 8K-16K images. Jitter is bounded to +/-s/2, so
    # the true nearest seed is always within the 3x3 neighborhood of grid
    # cells — same search space, computed by scipy's C implementation.
    from scipy.ndimage import distance_transform_edt
    marker = np.ones((h, w), dtype=bool)
    marker[cy.ravel(), cx.ravel()] = False
    _, (owner_y, owner_x) = distance_transform_edt(marker, return_indices=True)
    dist2 = (np.arange(h)[:, None] - owner_y) ** 2 + (np.arange(w)[None, :] - owner_x) ** 2
    return owner_y, owner_x, dist2


class Crystallize(FilterMode):
    key, title_key = "crystallize", "menu.pixelate.crystallize"
    params = (Slider("size", "pixelate.radius", 3, 300, 10, spatial=True),)

    def apply(self, src, p, ctx):
        res = src.copy()
        oy, ox, _ = _jittered_cells(*src.shape[:2], max(3, p["size"]))
        res[..., :3] = src[oy, ox, :3]
        return res


class Pointillize(Crystallize):
    key, title_key = "pointillize", "menu.pixelate.pointillize"

    def apply(self, src, p, ctx):
        res = src.copy()
        s = max(3, p["size"])
        oy, ox, dist2 = _jittered_cells(*src.shape[:2], s)
        mask = np.expand_dims(dist2 < (s * 0.6) ** 2, -1)
        res[..., :3] = np.where(mask, src[oy, ox, :3], ctx.bgr(ctx.bg))
        return res


class Fragment(FilterMode):
    key, title_key = "fragment", "menu.pixelate.fragment"

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        Y, X = np.ogrid[:h, :w]
        y1, y2 = np.clip(Y - 4, 0, h - 1), np.clip(Y + 4, 0, h - 1)
        x1, x2 = np.clip(X - 4, 0, w - 1), np.clip(X + 4, 0, w - 1)
        acc = src[y1, x1, :3].astype(np.uint16) + src[y1, x2, :3] + src[y2, x1, :3] + src[y2, x2, :3]
        res[..., :3] = (acc // 4).astype(np.uint8)
        return res


class Facet(FilterMode):
    key, title_key = "facet", "menu.pixelate.facet"

    def apply(self, src, p, ctx):
        from scipy.ndimage import median_filter
        res = src.copy()
        current = src[..., :3].copy()
        for _ in range(2):
            current = median_filter(current, size=(3, 3, 1), mode='nearest')
        res[..., :3] = current
        return res


class ColorHalftone(FilterMode):
    key, title_key = "color_halftone", "menu.pixelate.color_halftone"
    params = (Slider("size", "pixelate.radius", 4, 127, 8, spatial=True),)

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        s = max(4, p["size"])
        R = src[..., 2].astype(np.float32) / 255.0
        G = src[..., 1].astype(np.float32) / 255.0
        B = src[..., 0].astype(np.float32) / 255.0
        K = 1.0 - np.maximum(np.maximum(R, G), B)
        safe_K = np.where(K == 1.0, 1e-5, 1.0 - K)
        C, M, Yc = (1.0 - R - K) / safe_K, (1.0 - G - K) / safe_K, (1.0 - B - K) / safe_K

        def dots(val, angle):
            a = np.radians(angle)
            Y, X = np.ogrid[:h, :w]
            Xr, Yr = X * np.cos(a) - Y * np.sin(a), X * np.sin(a) + Y * np.cos(a)
            return ((Xr - ((Xr // s) * s + s / 2.0)) ** 2 + (Yr - ((Yr // s) * s + s / 2.0)) ** 2
                    <= val * (s * 0.707) ** 2).astype(np.float32)

        dC, dM, dY, dK = dots(C, 15), dots(M, 75), dots(Yc, 0), dots(K, 45)
        res[..., 2] = ((1.0 - np.clip(dC + dK, 0.0, 1.0)) * 255).astype(np.uint8)
        res[..., 1] = ((1.0 - np.clip(dM + dK, 0.0, 1.0)) * 255).astype(np.uint8)
        res[..., 0] = ((1.0 - np.clip(dY + dK, 0.0, 1.0)) * 255).astype(np.uint8)
        return res


_MEZZOTINT_TYPES = ("fine_dots", "medium_dots", "grainy_dots", "short_lines", "medium_lines",
                    "long_lines", "short_strokes", "medium_strokes", "long_strokes")


class Mezzotint(FilterMode):
    key, title_key = "mezzotint", "menu.pixelate.mezzotint"
    params = (Choice("type", "pixelate.type", tuple((f"pixelate.mezzotint.{t}", t) for t in _MEZZOTINT_TYPES)),)

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        mt = p["type"]
        rng = np.random.RandomState(42)
        if "dots" in mt:
            k = 1 if "fine" in mt else 2 if "medium" in mt else 3
            n = rng.uniform(-0.5, 0.5, (h // k + 1, w // k + 1, 3) if k > 1 else (h, w, 3))
            if k > 1:
                n = n.repeat(k, axis=0).repeat(k, axis=1)[:h, :w]
        elif "lines" in mt:
            k = 3 if "short" in mt else 8 if "medium" in mt else 16
            n = rng.uniform(-0.5, 0.5, (h, w // k + 1, 3)).repeat(k, axis=1)[:h, :w]
        else:
            n0 = rng.uniform(-0.5, 0.5, (h, w, 3))
            shift = 3 if "short" in mt else 8 if "medium" in mt else 15
            n = np.zeros_like(n0)
            for i in range(shift):
                n += np.roll(np.roll(n0, i, axis=0), i, axis=1)
            n /= shift
        res[..., :3] = ((src[..., :3].astype(np.float32) / 255.0 + n * 1.5) > 0.5) * 255
        return res


class PixelateDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.pixelate"
    MODES = {m.key: m for m in (ColorHalftone, Crystallize, Facet, Fragment, Mezzotint, Mosaic, Pointillize)}
