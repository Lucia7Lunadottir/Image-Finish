"""The layer/brush blend modes: one list, one mapping to QPainter modes.

Used to be four copies of the same mapping (document compositing, layer
styles, the brush tool) and three of the same UI list (Layers panel,
brush options, Layer Style dialog) — see ui/blend_mode_combo.py for the
UI side."""
from PyQt6.QtGui import QPainter

_CM = QPainter.CompositionMode

# (stored value, translation key)
BLEND_MODES = (
    ("SourceOver", "blend.normal"),
    ("Multiply", "blend.multiply"),
    ("Screen", "blend.screen"),
    ("Overlay", "blend.overlay"),
    ("Darken", "blend.darken"),
    ("Lighten", "blend.lighten"),
    ("ColorDodge", "blend.color_dodge"),
    ("ColorBurn", "blend.color_burn"),
    ("HardLight", "blend.hard_light"),
    ("SoftLight", "blend.soft_light"),
    ("Difference", "blend.difference"),
    ("Exclusion", "blend.exclusion"),
)

_MODES = {value: getattr(_CM, f"CompositionMode_{value}") for value, _ in BLEND_MODES}


def composition_mode(name: str) -> QPainter.CompositionMode:
    """QPainter mode for a stored blend-mode name (unknown -> Normal)."""
    return _MODES.get(name, _CM.CompositionMode_SourceOver)


_KEYS = dict(BLEND_MODES)
_KEYS["Normal"] = "blend.normal"     # layers' default value


def blend_mode_key(name: str) -> str:
    """Translation key of a stored blend-mode name (unknown -> Normal)."""
    return _KEYS.get(name, "blend.normal")


def blend_mode_items(tr) -> list:
    """[(translated label, value)] for combo boxes."""
    return [(tr(key), value) for value, key in BLEND_MODES]
