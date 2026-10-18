"""Filter > Distort gallery (see ui/filter_gallery.py).

Every mode is a backward coordinate map: `_map(X, Y, p, ctx)` says where
each output pixel samples the source; `apply` does the nearest-pixel
lookup and clears what falls outside."""
import math

import numpy as np

from ui.filter_gallery import (Choice, FilterGalleryDialog, FilterMode, ImageFile, Slider,
                               paint_center_rings)


class _DistortMode(FilterMode):
    identity_at_zero = True     # amount 0 = no change (not for polar/displace)

    def _map(self, X, Y, p, ctx, w, h):
        raise NotImplementedError

    def apply(self, src, p, ctx):
        if self.identity_at_zero and p.get("amount", 1) == 0:
            return ctx.orig_img.copy()
        h, w = src.shape[:2]
        Yg, Xg = np.ogrid[:h, :w]
        X = np.broadcast_to(Xg, (h, w)).astype(np.float32).copy()
        Y = np.broadcast_to(Yg, (h, w)).astype(np.float32).copy()
        X, Y = self._map(X, Y, p, ctx, w, h)
        res = src[np.clip(np.round(Y).astype(np.int32), 0, h - 1),
                  np.clip(np.round(X).astype(np.int32), 0, w - 1)]
        outside = (X < 0) | (X >= w) | (Y < 0) | (Y >= h)
        if np.any(outside):
            res[outside] = 0
        return res


class _CenteredMode(_DistortMode):
    center = True

    def paint_overlay(self, painter, dialog, w, h):
        paint_center_rings(painter, dialog, dialog.canvas.zoom)

    @staticmethod
    def _polar(X, Y, ctx):
        dx, dy = X - ctx.cx, Y - ctx.cy
        return np.hypot(dx, dy), np.arctan2(dy, dx)

    @staticmethod
    def _rmax(w, h):
        return max(1.0, math.hypot(w, h) / 2.0)


class Twirl(_CenteredMode):
    key, title_key = "twirl", "menu.distort.twirl"
    params = (Slider("amount", "distort.angle", -720, 720, 100),)

    def _map(self, X, Y, p, ctx, w, h):
        r, theta = self._polar(X, Y, ctx)
        rmax = self._rmax(w, h)
        m = r < rmax
        theta_src = theta.copy()
        theta_src[m] = theta[m] - np.radians(p["amount"]) * ((rmax - r[m]) / rmax)
        X[m] = ctx.cx + r[m] * np.cos(theta_src[m])
        Y[m] = ctx.cy + r[m] * np.sin(theta_src[m])
        return X, Y


class Pinch(_CenteredMode):
    key, title_key = "pinch", "menu.distort.pinch"
    params = (Slider("amount", "distort.amount", -100, 100, 50),)
    sign = 1.0

    def _map(self, X, Y, p, ctx, w, h):
        r, theta = self._polar(X, Y, ctx)
        rmax = self._rmax(w, h)
        a = self.sign * p["amount"] / 100.0
        m = r < rmax
        r_src = r.copy()
        r_src[m] = rmax * np.power(np.maximum(r[m], 1e-5) / rmax, 1.0 - a)
        X[m] = ctx.cx + r_src[m] * np.cos(theta[m])
        Y[m] = ctx.cy + r_src[m] * np.sin(theta[m])
        return X, Y


class Spherize(Pinch):
    key, title_key = "spherize", "menu.distort.spherize"
    sign = -1.0


class ZigZag(_CenteredMode):
    key, title_key = "zigzag", "menu.distort.zigzag"
    params = (Slider("amount", "distort.amount", -100, 100, 30, spatial=True),
              Slider("ridges", "distort.ridges", 1, 50, 10))

    def _map(self, X, Y, p, ctx, w, h):
        r, theta = self._polar(X, Y, ctx)
        r_src = r - p["amount"] * np.sin(max(1, p["ridges"]) * 2 * np.pi * r / self._rmax(w, h))
        return ctx.cx + r_src * np.cos(theta), ctx.cy + r_src * np.sin(theta)


class Ripple(_DistortMode):
    key, title_key = "ripple", "menu.distort.ripple"
    params = (Slider("amount", "distort.amount", 1, 100, 10, spatial=True),
              Slider("period", "distort.period", 1, 100, 30, spatial=True))
    second = staticmethod(np.sin)

    def _map(self, X, Y, p, ctx, w, h):
        a, period = p["amount"], max(1, p["period"])
        X += a * np.sin(2 * np.pi * Y / period)
        Y += a * self.second(2 * np.pi * X / period)
        return X, Y


class Wave(Ripple):
    key, title_key = "wave", "menu.distort.wave"
    params = (Slider("amount", "distort.amount", 1, 200, 20, spatial=True),
              Slider("period", "distort.period", 1, 500, 120, spatial=True))
    second = staticmethod(np.cos)


class Shear(_DistortMode):
    key, title_key = "shear", "menu.distort.shear"
    params = (Slider("amount", "distort.amount", -100, 100, 50, spatial=True),)

    def _map(self, X, Y, p, ctx, w, h):
        X -= p["amount"] * np.sin(Y / h * np.pi)
        return X, Y


class Polar(_DistortMode):
    key, title_key = "polar", "menu.distort.polar"
    identity_at_zero = False
    params = (Choice("direction", None, (("distort.polar.r2p", 0), ("distort.polar.p2r", 1))),)

    def _map(self, X, Y, p, ctx, w, h):
        rmax = max(1.0, math.hypot(w, h) / 2.0)
        if p["direction"] == 0:
            r, theta = Y * (rmax / h), (X / w) * 2 * np.pi - np.pi
        else:
            r, theta = Y / h * rmax, (X / w) * 2 * np.pi - np.pi
        return ctx.cx + r * np.cos(theta), ctx.cy + r * np.sin(theta)


class Displace(_DistortMode):
    key, title_key = "displace", "menu.distort.displace"
    identity_at_zero = False
    params = (Slider("amount", "distort.h_scale", -200, 200, 20, spatial=True),
              Slider("vertical", "distort.v_scale", -200, 200, 20, spatial=True),
              ImageFile("map", "distort.load_map"))

    def _map(self, X, Y, p, ctx, w, h):
        disp = p["map"]
        if disp is None:
            return X, Y
        dh, dw = disp.shape[:2]
        mY = np.clip((Y / h * dh).astype(np.int32), 0, dh - 1)
        mX = np.clip((X / w * dw).astype(np.int32), 0, dw - 1)
        d = disp[mY, mX]
        X = X - ((d[..., 2].astype(np.float32) - 128.0) / 128.0) * p["amount"]
        Y = Y - ((d[..., 1].astype(np.float32) - 128.0) / 128.0) * p["vertical"]
        return X, Y


class DistortDialog(FilterGalleryDialog):
    GALLERY_TITLE_KEY = "menu.distort"
    CENTER_HIT_RADIUS = 30
    MODES = {m.key: m for m in (Displace, Pinch, Polar, Ripple, Shear, Spherize, Twirl, Wave, ZigZag)}
