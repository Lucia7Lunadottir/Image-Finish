"""Photoshop layer effects ('lfx2' / 'lmfx' descriptors) -> our layer
styles (core/layer_styles.py), for core/psd_import.py.

One reader class per effect. Our styles are simpler than Photoshop's, so
what they have no setting for is dropped: contours, noise, gradient glows,
gradient/pattern strokes, bevel style and depth. A
pattern overlay needs the file's pattern data and isn't imported. With
several effects of a kind (Photoshop's "+" effects) the first one that is
on is used."""
from __future__ import annotations

from PyQt6.QtGui import QColor

# Blend mode enums ('BlnM') -> stored blend-mode values (core/blend_modes.py).
_BLEND = {
    "Nrml": "SourceOver", "Mltp": "Multiply", "Scrn": "Screen", "Ovrl": "Overlay",
    "Drkn": "Darken", "Lghn": "Lighten", "CDdg": "ColorDodge", "CBrn": "ColorBurn",
    "HrdL": "HardLight", "SftL": "SoftLight", "Dfrn": "Difference", "Xclu": "Exclusion",
    # Newer files spell them out.
    "normal": "SourceOver", "multiply": "Multiply", "screen": "Screen", "overlay": "Overlay",
    "darken": "Darken", "lighten": "Lighten", "colorDodge": "ColorDodge", "colorBurn": "ColorBurn",
    "hardLight": "HardLight", "softLight": "SoftLight", "difference": "Difference",
    "exclusion": "Exclusion",
}

_GRADIENT_TYPES = {"Lnr ": "linear", "Rdl ": "radial", "Angl": "angle",
                   "Rflc": "reflected", "Dmnd": "diamond"}


class _EffectContext:
    """What every effect reader needs from the file."""

    def __init__(self, global_angle: float, resolve_color):
        self.global_angle = global_angle
        self._resolve = resolve_color

    def color(self, d: dict, key: str = "Clr ", default=QColor(0, 0, 0)) -> QColor:
        clr = d.get(key)
        rgb = self._resolve(clr) if isinstance(clr, dict) else None
        return QColor(*rgb) if rgb is not None else QColor(default)

    @staticmethod
    def blend(d: dict, key: str = "Md  ", default: str = "SourceOver") -> str:
        v = d.get(key)
        return _BLEND.get(v[1], default) if isinstance(v, tuple) else default

    def angle(self, d: dict) -> float:
        if d.get("uglg", False):
            return self.global_angle
        return float(d.get("lagl", self.global_angle))


class EffectReader:
    """`keys`: the descriptor entries Photoshop stores this effect under
    (single, then the "Multi" list). `style`: our layer_styles key."""
    keys: tuple = ()
    style: str = ""

    def find(self, desc: dict) -> dict | None:
        for key in self.keys:
            value = desc.get(key)
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, dict) and item.get("enab", False):
                    return item
        return None

    def read(self, d: dict, ctx: _EffectContext) -> dict:
        raise NotImplementedError


class _ShadowReader(EffectReader):
    default_blend = "Multiply"

    def read(self, d, ctx):
        return {"enabled": True, "color": ctx.color(d), "opacity": float(d.get("Opct", 75)),
                "blend_mode": ctx.blend(d, default=self.default_blend), "angle": ctx.angle(d),
                "distance": float(d.get("Dstn", 5)), "size": float(d.get("blur", 5))}


class DropShadowReader(_ShadowReader):
    keys, style = ("DrSh", "dropShadowMulti"), "drop_shadow"


class InnerShadowReader(_ShadowReader):
    keys, style = ("IrSh", "innerShadowMulti"), "inner_shadow"


class _GlowReader(EffectReader):
    def read(self, d, ctx):
        return {"enabled": True, "color": ctx.color(d, default=QColor(255, 255, 190)),
                "opacity": float(d.get("Opct", 75)), "blend_mode": ctx.blend(d, default="Screen"),
                "size": float(d.get("blur", 5))}


class OuterGlowReader(_GlowReader):
    keys, style = ("OrGl",), "outer_glow"


class InnerGlowReader(_GlowReader):
    keys, style = ("IrGl",), "inner_glow"


class SatinReader(EffectReader):
    keys, style = ("ChFX",), "satin"

    def read(self, d, ctx):
        return {"enabled": True, "color": ctx.color(d), "opacity": float(d.get("Opct", 50)),
                "blend_mode": ctx.blend(d, default="Multiply"), "angle": float(d.get("lagl", 19)),
                "distance": float(d.get("Dstn", 11)), "size": float(d.get("blur", 14))}


class BevelReader(EffectReader):
    """Our bevel has one opacity: the larger of highlight / shadow."""
    keys, style = ("ebbl",), "bevel"

    def read(self, d, ctx):
        size = float(d.get("blur", 5))
        return {"enabled": True, "color": ctx.color(d, "hglC", QColor(255, 255, 255)),
                "shadow_color": ctx.color(d, "sdwC"),
                "opacity": max(float(d.get("hglO", 75)), float(d.get("sdwO", 75))),
                "angle": ctx.angle(d), "size": size, "distance": max(1.0, size / 2)}


class ColorOverlayReader(EffectReader):
    keys, style = ("SoFi", "solidFillMulti"), "color_overlay"

    def read(self, d, ctx):
        return {"enabled": True, "color": ctx.color(d, default=QColor(255, 0, 0)),
                "opacity": float(d.get("Opct", 100)), "blend_mode": ctx.blend(d)}


class GradientOverlayReader(EffectReader):
    keys, style = ("GrFl", "gradientFillMulti"), "gradient_overlay"

    def read(self, d, ctx):
        grad = d.get("Grad") if isinstance(d.get("Grad"), dict) else {}
        stops = []
        for st in grad.get("Clrs", []):
            if isinstance(st, dict):
                kind = st.get("Type")
                fallback = QColor(255, 255, 255) if isinstance(kind, tuple) and kind[1] == "BckC" else QColor(0, 0, 0)
                stops.append((min(1.0, max(0.0, st.get("Lctn", 0) / 4096.0)), ctx.color(st, default=fallback)))
        stops.sort(key=lambda s: s[0])
        kind = d.get("Type")
        return {"enabled": True, "opacity": float(d.get("Opct", 100)), "blend_mode": ctx.blend(d),
                "stops": stops or [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))],
                "type": _GRADIENT_TYPES.get(kind[1], "linear") if isinstance(kind, tuple) else "linear",
                "angle": float(d.get("Angl", 90)), "scale": float(d.get("Scl ", 100)),
                "reverse": bool(d.get("Rvrs", False))}


class StrokeReader(EffectReader):
    keys, style = ("FrFX", "frameFXMulti"), "stroke"
    _POSITIONS = {"OutF": "outside", "InsF": "inside", "CtrF": "center"}

    def read(self, d, ctx):
        pos = d.get("Styl")
        return {"enabled": True, "size": float(d.get("Sz  ", 3)), "color": ctx.color(d),
                "opacity": float(d.get("Opct", 100)), "blend_mode": ctx.blend(d),
                "position": self._POSITIONS.get(pos[1], "outside") if isinstance(pos, tuple) else "outside"}


READERS = (DropShadowReader(), InnerShadowReader(), OuterGlowReader(), InnerGlowReader(),
           SatinReader(), BevelReader(), ColorOverlayReader(), GradientOverlayReader(),
           StrokeReader())


def layer_styles_from_effects(desc: dict, global_angle: float, resolve_color) -> dict:
    """Our layer_styles for a layer's effects descriptor; {} when they are
    all off (or the master switch, "Layer Effects" visibility, is)."""
    if not isinstance(desc, dict) or not desc.get("masterFXSwitch", True):
        return {}
    ctx = _EffectContext(global_angle, resolve_color)
    styles = {}
    for reader in READERS:
        d = reader.find(desc)
        if d is not None:
            styles[reader.style] = reader.read(d, ctx)
    return styles
