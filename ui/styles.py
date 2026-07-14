"""Backwards-compatible entry point: the stylesheet now lives in ui.theme."""

from ui.theme import build_stylesheet

DARK_STYLE = build_stylesheet()
