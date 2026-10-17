"""Every adjustment that can live on an adjustment layer, as a class:
its parameters (exact keys, real units, defaults), how old saved data maps
onto them, and how it's applied.

Before this, an adjustment layer's data was whatever the dialog's widget
*attribute names* happened to be ("bright", "shadow_btn", "color_btn"...),
scraped by name, and the renderer guessed keys back by substring with
unit-fixing heuristics ("if exposure > 20, divide by 100"). Several layers
silently did nothing (Gradient Map, Photo Filter: wrong keys / wrong call
signature, swallowed by a catch-all) or rendered wrong (HDR Toning strength
off by 100x), and re-opening a layer reset its settings.

Now: the dialog's live preview, the destructive Image > Adjustments apply
and the adjustment layer render all call the same `AdjustmentKind.apply`
with the same parameter dict, and `normalize` is the one place that reads
older saved data.
"""
from dataclasses import dataclass

from PyQt6.QtGui import QColor, QImage


@dataclass(frozen=True)
class Param:
    key: str
    default: object
    type: type = int
    aliases: tuple = ()      # keys older versions saved this value under

    def coerce(self, v):
        if self.type is QColor:
            if isinstance(v, (tuple, list)) and len(v) >= 3:
                return QColor(*v[:3])
            return QColor(v)
        if self.type is bool:
            return bool(v)
        if self.type in (int, float):
            return self.type(round(v) if self.type is int else v)
        return v


class AdjustmentKind:
    type = ""
    params: tuple = ()

    def defaults(self) -> dict:
        return {p.key: (QColor(p.default) if isinstance(p.default, QColor) else p.default)
                for p in self.params}

    def normalize(self, data: dict | None) -> dict:
        """Canonical parameters from saved data (current or older format)."""
        data = data or {}
        out = self.defaults()
        for p in self.params:
            for key in (p.key, *p.aliases):
                if key in data and data[key] is not None:
                    try:
                        out[p.key] = p.coerce(data[key])
                    except (TypeError, ValueError):
                        pass
                    break
        self._fix_legacy_units(out, data)
        return out

    def _fix_legacy_units(self, p: dict, raw: dict) -> None:
        """Hook for data saved in other units by older versions."""

    def apply(self, image: QImage, p: dict) -> QImage:
        raise NotImplementedError


_REGISTRY: dict[str, AdjustmentKind] = {}


def register(cls):
    _REGISTRY[cls.type] = cls()
    return cls


def get_kind(adj_type: str) -> AdjustmentKind | None:
    return _REGISTRY.get(adj_type)


def adjustment_types() -> list:
    return list(_REGISTRY)


def apply_adjustment(image: QImage, data: dict | None) -> QImage:
    """Adjustment-layer render: `data` is the layer's adjustment_data."""
    kind = get_kind((data or {}).get("type", ""))
    if kind is None:
        return image
    return kind.apply(image, kind.normalize(data))


# ── the adjustments ────────────────────────────────────────────────────────

@register
class BrightnessContrast(AdjustmentKind):
    type = "brightness_contrast"
    params = (Param("brightness", 0, aliases=("bright",)),
              Param("contrast", 0, aliases=("contr",)))

    def apply(self, image, p):
        from ui.adjustments_dialog import apply_brightness_contrast
        return apply_brightness_contrast(image, p["brightness"], p["contrast"])


@register
class HueSaturation(AdjustmentKind):
    type = "hue_saturation"
    params = (Param("hue", 0), Param("saturation", 0, aliases=("sat",)),
              Param("lightness", 0, aliases=("lght", "light")))

    def apply(self, image, p):
        from ui.adjustments_dialog import apply_hue_saturation
        return apply_hue_saturation(image, p["hue"], p["saturation"], p["lightness"])


@register
class Invert(AdjustmentKind):
    type = "invert"

    def apply(self, image, p):
        from ui.adjustments_dialog import apply_invert
        return apply_invert(image)


@register
class Levels(AdjustmentKind):
    type = "levels"
    params = (Param("black", 0, aliases=("black_sp", "in_min", "in_black", "in_low")),
              Param("gamma", 1.0, float, aliases=("gamma_sp", "mid")),
              Param("white", 255, aliases=("white_sp", "in_max", "in_white", "in_high")),
              Param("out_min", 0, aliases=("out_min_sp", "out_black", "out_low")),
              Param("out_max", 255, aliases=("out_max_sp", "out_white", "out_high")))

    def _fix_legacy_units(self, p, raw):
        if p["gamma"] > 5.0:
            p["gamma"] /= 100.0
        if p["gamma"] <= 0.0:
            p["gamma"] = 1.0
        if p["white"] <= p["black"]:
            p["white"] = p["black"] + 1

    def apply(self, image, p):
        from ui.levels_dialog import apply_levels
        return apply_levels(image, p["black"], p["gamma"], p["white"], p["out_min"], p["out_max"])


@register
class Curves(AdjustmentKind):
    type = "curves"
    params = (Param("points", None, object, aliases=("curve_points",)),)

    def apply(self, image, p):
        from core.adjustments.curves import apply_curves
        return apply_curves(image, p["points"] or {})


@register
class Exposure(AdjustmentKind):
    type = "exposure"
    params = (Param("exposure", 0.0, float, aliases=("exp",)),
              Param("offset", 0.0, float, aliases=("off",)),
              Param("gamma", 1.0, float, aliases=("gam",)))

    def _fix_legacy_units(self, p, raw):
        # Very old saves stored the raw slider integers.
        if abs(p["exposure"]) > 20.0:
            p["exposure"] /= 100.0
        if abs(p["offset"]) > 1.0:
            p["offset"] /= 100.0
        if p["gamma"] > 10.0:
            p["gamma"] /= 100.0
        if p["gamma"] <= 0.0:
            p["gamma"] = 1.0

    def apply(self, image, p):
        from core.adjustments.exposure import apply_exposure
        return apply_exposure(image, p["exposure"], p["offset"], p["gamma"])


@register
class Vibrance(AdjustmentKind):
    type = "vibrance"
    params = (Param("vibrance", 0, aliases=("vib",)), Param("saturation", 0, aliases=("sat",)))

    def apply(self, image, p):
        from core.adjustments.vibrance import apply_vibrance
        return apply_vibrance(image, p["vibrance"], p["saturation"])


@register
class BlackWhite(AdjustmentKind):
    type = "black_white"
    params = tuple(Param(k, 100, aliases=(k[:-1],))
                   for k in ("reds", "yellows", "greens", "cyans", "blues", "magentas"))

    def apply(self, image, p):
        from core.adjustments.black_white import apply_black_white
        return apply_black_white(image, p["reds"], p["yellows"], p["greens"],
                                 p["cyans"], p["blues"], p["magentas"])


@register
class Posterize(AdjustmentKind):
    type = "posterize"
    params = (Param("levels", 4, aliases=("level", "lvl")),)

    def apply(self, image, p):
        from core.adjustments.posterize import apply_posterize
        return apply_posterize(image, max(2, p["levels"]))


@register
class Threshold(AdjustmentKind):
    type = "threshold"
    params = (Param("threshold", 128, aliases=("thresh",)),)

    def apply(self, image, p):
        from core.adjustments.threshold import apply_threshold
        return apply_threshold(image, p["threshold"])


@register
class PhotoFilter(AdjustmentKind):
    type = "photo_filter"
    params = (Param("color", QColor(235, 115, 25), QColor, aliases=("color_btn",)),
              Param("density", 25, aliases=("dens",)),
              Param("preserve", True, bool))

    def apply(self, image, p):
        from core.adjustments.photo_filter import apply_photo_filter
        c = p["color"]
        return apply_photo_filter(image, c.red(), c.green(), c.blue(), p["density"], p["preserve"])


@register
class GradientMap(AdjustmentKind):
    type = "gradient_map"
    params = (Param("gradient", None, object), Param("reverse", False, bool),
              Param("shadows", QColor(0, 0, 0), QColor), Param("highlights", QColor(255, 255, 255), QColor))

    def apply(self, image, p):
        from core.adjustments.gradient_map import apply_gradient_map, gradient_map_from_data
        return apply_gradient_map(image, gradient_map_from_data(p))


@register
class ColorLookup(AdjustmentKind):
    type = "color_lookup"
    params = (Param("lut", None, object), Param("intensity", 100))

    def apply(self, image, p):
        if not p["lut"]:
            return image
        from core.adjustments.color_lookup import apply_color_lookup
        return apply_color_lookup(image, p["lut"], p["intensity"])


@register
class HDRToning(AdjustmentKind):
    type = "hdr_toning"
    # Dialog units: radius px, strength/detail 0..100 %, gamma as a factor.
    params = (Param("radius", 50, float, aliases=("rad",)),
              Param("strength", 50, float, aliases=("str",)),
              Param("gamma", 1.0, float),
              Param("detail", 0, float, aliases=("det",)))

    def _fix_legacy_units(self, p, raw):
        # The old renderer's defaults were fractions (0.5); stored dialog
        # values are percentages.
        if "strength" not in raw and "str" not in raw:
            return
        if 0 < p["strength"] <= 1.0:
            p["strength"] *= 100.0

    def apply(self, image, p):
        from core.adjustments.hdr_toning import apply_hdr_toning
        return apply_hdr_toning(image, radius=int(p["radius"]), strength=p["strength"] / 100.0,
                                gamma=p["gamma"], detail=p["detail"] / 100.0)
