"""Filter > Render gallery (see ui/filter_gallery.py)."""
import math
import random

import numpy as np
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient

from core.app_logging import get_logger
from ui.filter_gallery import Choice, Color, FilterGalleryDialog, FilterMode, Slider

logger = get_logger("render_dialog")


def _generate_noise_image(w, h, rng, octaves=6, scale_x=None, scale_y=None):
    """True gradient noise (Perlin Noise) via NumPy for ideal clouds.
    `rng` (a numpy RandomState) makes it repeatable: the same seed gives
    the preview and the applied result the same pattern."""
    res = np.zeros((h, w), dtype=np.float32)
    base_sx = scale_x if scale_x else max(w, h) / 3.0
    base_sy = scale_y if scale_y else max(w, h) / 3.0
    amp = 1.0
    
    y_coords, x_coords = np.mgrid[0:h:1, 0:w:1]
    
    for i in range(octaves):
        sx = max(1.0, base_sx)
        sy = max(1.0, base_sy)
        
        x = x_coords / sx
        y = y_coords / sy
        
        x0 = x.astype(int)
        y0 = y.astype(int)
        x1 = x0 + 1
        y1 = y0 + 1
        
        angles = rng.rand(y1.max()+1, x1.max()+1) * 2 * np.pi
        gx = np.cos(angles)
        gy = np.sin(angles)
        
        g00 = gx[y0, x0] * (x - x0) + gy[y0, x0] * (y - y0)
        g10 = gx[y0, x1] * (x - x1) + gy[y0, x1] * (y - y0)
        g01 = gx[y1, x0] * (x - x0) + gy[y1, x0] * (y - y1)
        g11 = gx[y1, x1] * (x - x1) + gy[y1, x1] * (y - y1)
        
        dx = x - x0
        dy = y - y0
        u = dx * dx * (3.0 - 2.0 * dx)
        v = dy * dy * (3.0 - 2.0 * dy)
        
        nx0 = g00 * (1 - u) + g10 * u
        nx1 = g01 * (1 - u) + g11 * u
        n = nx0 * (1 - v) + nx1 * v
        
        res += n * amp
        amp *= 0.5
        base_sx *= 0.5
        base_sy *= 0.5
        
    return (res - res.min()) / (res.max() - res.min() + 1e-5)


def _blend(fg_bgr, bg_bgr, t):
    return bg_bgr + (fg_bgr - bg_bgr) * t[..., np.newaxis]


class Clouds(FilterMode):
    key, title_key = "clouds", "menu.render.clouds"

    def _color_noise(self, src, ctx):
        h, w = src.shape[:2]
        noise = _generate_noise_image(w, h, ctx.rng(), octaves=7).astype(np.float32)
        return _blend(ctx.bgr(ctx.fg, np.float32), ctx.bgr(ctx.bg, np.float32), noise)

    def apply(self, src, p, ctx):
        res = src.copy()
        res[..., :3] = self._color_noise(src, ctx).astype(np.uint8)
        res[..., 3] = 255      # opaque even on an empty layer
        return res


class DifferenceClouds(Clouds):
    key, title_key = "diff_clouds", "menu.render.diff_clouds"

    def apply(self, src, p, ctx):
        res = src.copy()
        res[..., :3] = np.abs(src[..., :3].astype(np.float32) - self._color_noise(src, ctx)).astype(np.uint8)
        res[..., 3] = 255
        return res


class Fibers(FilterMode):
    key, title_key = "fibers", "menu.render.fibers"
    params = (Slider("variance", "render.variance", 1, 64, 16),
              Slider("strength", "render.strength", 1, 64, 4))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        noise = _generate_noise_image(w, h, ctx.rng(), octaves=5, scale_x=w / 10.0, scale_y=h / (p["strength"] * 5.0))
        noise = np.clip((noise - 0.5) * (p["variance"] / 16.0) + 0.5, 0, 1)
        res[..., :3] = _blend(ctx.bgr(ctx.fg, np.float32), ctx.bgr(ctx.bg, np.float32), noise).astype(np.uint8)
        res[..., 3] = 255
        return res


class Wood(FilterMode):
    key, title_key = "wood", "menu.render.wood"
    params = (Slider("rings", "render.rings", 1, 100, 15),
              Slider("turbulence", "render.turbulence", 0, 100, 30),
              Choice("type", "render.wood_type", (("render.wood.rings", 0), ("render.wood.bark", 1))))

    def apply(self, src, p, ctx):
        res = src.copy()
        h, w = src.shape[:2]
        rings, turb = p["rings"], p["turbulence"] / 100.0
        rng = ctx.rng()
        Y, X = np.ogrid[:h, :w]
        if p["type"] == 0:
            noise = _generate_noise_image(w, h, rng, octaves=5).astype(np.float32)
            dx = X - w / 2 + (noise - 0.5) * turb * w
            dy = Y - h / 2 + (noise - 0.5) * turb * h
            r = np.hypot(dx, dy)
            ring_val = (np.sin(r * rings / max(w, h) * 2 * np.pi) + 1) / 2.0
            grain = (np.sin((r + (noise - 0.5) * turb * w * 0.5) * rings * 10 / max(w, h) * 2 * np.pi) + 1) / 2.0
            val = ring_val * 0.6 + grain * 0.2 + noise * 0.2
            c1, c2 = np.array([30, 60, 100]), np.array([80, 140, 200])
        else:
            base = _generate_noise_image(w, h, rng, octaves=6, scale_x=max(10, w / rings), scale_y=max(50, h / 2.0)).astype(np.float32)
            distort = _generate_noise_image(w, h, rng, octaves=4, scale_x=50, scale_y=50).astype(np.float32)
            X_dist = np.clip(X + (distort - 0.5) * turb * 100, 0, w - 1).astype(int)
            val = np.power(np.abs(base[Y, X_dist] - 0.5) * 2.0, 0.5 + turb)    # deep cracks
            c1, c2 = np.array([15, 25, 40]), np.array([50, 80, 110])
        res[..., :3] = (c1 + (c2 - c1) * val[..., np.newaxis]).astype(np.uint8)
        res[..., 3] = 255
        return res


class _PainterMode(FilterMode):
    """Drawn with QPainter over a copy of the source."""

    def paint(self, painter, w, h, p, ctx):
        raise NotImplementedError

    def apply(self, src, p, ctx):
        h, w = src.shape[:2]
        img = QImage(ctx.orig_img)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(painter, w, h, p, ctx)
        painter.end()
        from core.pixel_buffer import qimage_argb_view
        return qimage_argb_view(img, writable=False)[:, :w, :].copy()


class _CenteredPainterMode(_PainterMode):
    center = True

    def paint_overlay(self, p, dialog, w, h):
        cx, cy, zoom = dialog.cx, dialog.cy, dialog.canvas.zoom
        p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 1.5 / zoom)))
        p.setBrush(QColor(0, 0, 0, 100))
        cr = max(4.0, 6.0 / zoom)
        p.drawEllipse(QPointF(cx, cy), cr, cr)
        p.drawLine(QPointF(cx - cr * 2, cy), QPointF(cx + cr * 2, cy))
        p.drawLine(QPointF(cx, cy - cr * 2), QPointF(cx, cy + cr * 2))


class LensFlare(_CenteredPainterMode):
    key, title_key = "lens_flare", "menu.render.lens_flare"
    params = (Slider("brightness", "render.brightness", 10, 300, 100),
              Choice("lens", "render.lens_type", (("render.lens.50_300", 0), ("render.lens.35", 1),
                                                  ("render.lens.105", 2))),
              Color("color", "render.color", (255, 255, 255)))

    def paint(self, painter, w, h, p, ctx):
        b, color = p["brightness"] / 100.0, p["color"]
        r1 = w * 0.4 * b
        grad = QRadialGradient(ctx.cx, ctx.cy, r1)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), int(255 * min(1, b))))
        grad.setColorAt(0.1, QColor(color.red(), color.green(), color.blue(), int(150 * min(1, b))))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.fillRect(0, 0, w, h, QBrush(grad))
        # Artifacts along the line through the centre
        dx, dy = ctx.cx - w / 2, ctx.cy - h / 2
        colors = [QColor(color.red(), 100, 100, 100), QColor(100, color.green(), 100, 80),
                  QColor(100, 100, color.blue(), 120)]
        for i, mult in enumerate([-0.2, -0.5, -1.2, -1.5, 0.8]):
            ar = r1 * 0.1 * abs(mult)
            painter.setBrush(QBrush(colors[i % len(colors)]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(w / 2 + dx * mult, h / 2 + dy * mult), ar, ar)


class Lighting(_CenteredPainterMode):
    key, title_key = "lighting", "menu.render.lighting"
    params = (Slider("intensity", "render.intensity", 0, 100, 50),
              Slider("focus", "render.focus", 0, 100, 50))

    def paint(self, painter, w, h, p, ctx):
        intensity = p["intensity"] / 50.0
        r = max(w, h) * (0.2 + p["focus"] / 100.0 * 0.8)
        grad = QRadialGradient(ctx.cx, ctx.cy, r)
        grad.setColorAt(0, QColor(255, 255, 255, int(255 * min(1, intensity))))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
        painter.fillRect(0, 0, w, h, QBrush(grad))


class Frame(_PainterMode):
    key, title_key = "frame", "menu.render.frame"
    params = (Slider("margin", "render.margin", 1, 100, 20, spatial=True),
              Slider("size", "render.size", 1, 50, 10, spatial=True))

    def paint(self, painter, w, h, p, ctx):
        m = p["margin"]
        painter.setPen(QPen(ctx.fg, p["size"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(m, m, w - m * 2, h - m * 2)


def _work_path_or_default(work_path, w, h):
    """The Pen tool's work path as a QPainterPath, or a vertical line."""
    from tools.pen_tool import build_bezier_path, has_path
    try:
        if has_path(work_path):
            return build_bezier_path(work_path)
    except Exception as e:
        logger.warning("Flame path parsing error: %s", e)
    path = QPainterPath()
    path.moveTo(w / 2, h * 0.9)
    path.lineTo(w / 2, h * 0.1)
    return path


class Flame(_PainterMode):
    key, title_key = "flame", "menu.render.flame"
    params = (Slider("width", "render.width", 1, 200, 50, spatial=True),
              Slider("lines", "render.length", 10, 500, 100),
              Slider("turbulence", "render.turbulence", 0, 100, 30),
              Slider("complexity", "render.complexity", 1, 20, 5),
              Slider("core", "render.core", 1, 100, 80),
              Choice("type", "render.flame_type", (("render.flame.single", 0), ("render.flame.multiple", 1),
                                                   ("render.flame.candle", 2))),
              Color("color", "render.color", (255, 100, 0)))

    def paint(self, painter, w, h, p, ctx):
        width, lines_count = p["width"], p["lines"]
        turb, complexity, core = p["turbulence"] / 100.0, p["complexity"], p["core"] / 100.0
        f_type, c = p["type"], QColor(p["color"])
        base_path = _work_path_or_default(ctx.work_path, w, h)

        # Fire is drawn on a separate transparent layer for correct alpha compositing
        fire = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        fire.fill(0)
        fp = QPainter(fire)
        fp.setRenderHint(QPainter.RenderHint.Antialiasing)
        fp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        rnd = random.Random(42)
        path_len = base_path.length()
        if path_len < 10:
            path_len = max(100.0, h * 0.8)
        base_opacity = min(1.0, 10.0 / max(1, lines_count))
        c_pen = QColor(c.red(), c.green(), c.blue(), int(255 * base_opacity))
        c_core_pen = QColor(255, 255, 255, int(255 * base_opacity * core))

        for _ in range(lines_count):
            flame_path = QPainterPath()
            phase = rnd.uniform(0, 100)
            freq = rnd.uniform(2.0, 5.0) * complexity
            if f_type == 0:
                t_start, t_end = 0.0, rnd.uniform(0.3, 1.0)
                x_offset = rnd.uniform(-width, width)
            elif f_type == 1:
                t_start = rnd.uniform(0.0, 0.8)
                t_end = t_start + rnd.uniform(0.1, 0.5)
                x_offset = rnd.uniform(-width, width)
            else:
                t_start, t_end = 0.0, rnd.uniform(0.5, 1.0)
                x_offset = rnd.uniform(-width * 0.2, width * 0.2)
            t_end = min(t_end, 1.0)
            steps = max(10, int(path_len * (t_end - t_start) / 5))
            for s in range(steps + 1):
                norm_s = s / steps if steps > 0 else 0
                t = t_start + norm_s * (t_end - t_start)
                pt = base_path.pointAtPercent(t)
                rad = math.radians(base_path.angleAtPercent(t))
                nx, ny = -math.sin(rad), math.cos(rad)
                envelope = 1.0 - norm_s ** 2
                if f_type == 2:
                    envelope = math.sin(norm_s * math.pi) * (1.0 - norm_s) + 0.1
                wiggle = math.sin(norm_s * freq + phase) * turb * width * norm_s
                off = x_offset * envelope + wiggle
                q = QPointF(pt.x() + nx * off, pt.y() + ny * off)
                if s == 0:
                    flame_path.moveTo(q)
                else:
                    flame_path.lineTo(q)
            pen_width = max(1.0, rnd.uniform(width * 0.1, width * 0.4))
            fp.setPen(QPen(c_pen, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            fp.drawPath(flame_path)
            fp.setPen(QPen(c_core_pen, pen_width * 0.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            fp.drawPath(flame_path)
        fp.end()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(0, 0, fire)


class RenderDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.render_gallery"
    CENTER_HIT_RADIUS = 40
    MODES = {m.key: m for m in (Clouds, DifferenceClouds, Fibers, Flame, Frame, LensFlare, Lighting, Wood)}
