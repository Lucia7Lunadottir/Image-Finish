"""
tool_icons.py — Inline SVG tool icons styled like Photoshop.

All icons: viewBox 0 0 24 24, white strokes/fills, transparent background.
Usage:
    from ui.tool_icons import get_tool_icon
    btn.setIcon(get_tool_icon("Brush"))
    btn.setIconSize(QSize(22, 22))
"""

from PyQt6.QtCore import Qt, QByteArray, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter

try:
    from PyQt6.QtSvg import QSvgRenderer
    _SVG_OK = True
except ImportError:
    _SVG_OK = False


# ── SVG builder helpers ───────────────────────────────────────────────────────

_ATTR = ('stroke="white" stroke-width="1.5" '
         'stroke-linecap="round" stroke-linejoin="round" fill="none"')
_HEAD = f'<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" {_ATTR}>'
_FOOT = '</svg>'


def _s(*parts: str) -> bytes:
    """Outline icon: white stroke, no fill."""
    return (_HEAD + "".join(parts) + _FOOT).encode()


def _raw(*parts: str) -> bytes:
    """Raw SVG body — for icons needing mixed fill/stroke attributes."""
    return (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        + "".join(parts) + '</svg>'
    ).encode()


_W   = 'stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
_W2  = 'stroke="white" stroke-width="2"   stroke-linecap="round" stroke-linejoin="round"'
_W25 = 'stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"'
_WF  = 'fill="white" stroke="none"'
_WS  = 'fill="none" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'


# ── Icon definitions ──────────────────────────────────────────────────────────

_ICONS: dict[str, bytes] = {

    # ── Move / Transform ──────────────────────────────────────────────────────

    "Move": _raw(
        # Classic 4-way arrow cross
        f'<polygon {_WF} points="'
        '12,3 15,7 13.2,7 13.2,10.8 17,10.8 17,9 21,12 17,15 17,13.2 '
        '13.2,13.2 13.2,17 15,17 12,21 9,17 10.8,17 10.8,13.2 7,13.2 '
        '7,15 3,12 7,9 7,10.8 10.8,10.8 10.8,7 9,7"/>'
    ),

    "Artboard": _s(
        '<rect x="5" y="5" width="14" height="14"/>',
        # Corner tick marks
        '<line x1="5" y1="2" x2="5" y2="4"/>',
        '<line x1="19" y1="2" x2="19" y2="4"/>',
        '<line x1="5" y1="20" x2="5" y2="22"/>',
        '<line x1="19" y1="20" x2="19" y2="22"/>',
        '<line x1="2" y1="5" x2="4" y2="5"/>',
        '<line x1="20" y1="5" x2="22" y2="5"/>',
        '<line x1="2" y1="19" x2="4" y2="19"/>',
        '<line x1="20" y1="19" x2="22" y2="19"/>',
    ),

    "Warp": _s(
        '<path d="M3 6 Q12 3 21 6"/>',
        '<path d="M3 12 Q12 10 21 12"/>',
        '<path d="M3 18 Q12 16 21 18"/>',
        '<path d="M6 3 Q3 12 6 21"/>',
        '<path d="M12 3 Q10 12 12 21"/>',
        '<path d="M18 3 Q16 12 18 21"/>',
    ),

    "PuppetWarp": _raw(
        # Thumbtack / pin
        f'<circle cx="12" cy="7" r="3.5" {_WF}/>',
        f'<line x1="12" y1="10.5" x2="9" y2="20" {_W}/>',
        f'<line x1="12" y1="10.5" x2="15" y2="20" {_W}/>',
        f'<line x1="9" y1="16" x2="15" y2="16" {_W}/>',
    ),

    "PerspectiveWarp": _s(
        '<polygon points="3,20 21,20 17,6 7,6"/>',
        '<line x1="7" y1="6" x2="3" y2="20"/>',
        '<line x1="17" y1="6" x2="21" y2="20"/>',
        '<line x1="7" y1="13" x2="17" y2="13"/>',
    ),

    # ── Selection ─────────────────────────────────────────────────────────────

    "Select": _s(
        # Dashed marquee rectangle — show just corners so it's clear
        '<rect x="3" y="3" width="18" height="18" stroke-dasharray="4,3"/>',
    ),

    "EllipseSelect": _s(
        '<ellipse cx="12" cy="12" rx="9" ry="7" stroke-dasharray="4,3"/>',
    ),

    "Lasso": _s(
        '<path d="M12 5 C7 4 3 8 4 13 C5 18 9 20 13 19 '
        'C17 18 20 15 19 11 C18 7 15 4 12 5" stroke-dasharray="3,2"/>',
        f'<circle cx="12" cy="5" r="1.5" fill="white" stroke="none"/>',
    ),

    "PolygonalLasso": _s(
        '<polyline points="12,4 20,10 17,20 7,20 4,10 12,4" stroke-dasharray="3,2"/>',
        '<circle cx="12" cy="4" r="1.5" fill="white" stroke="none"/>',
        '<circle cx="20" cy="10" r="1.5" fill="white" stroke="none"/>',
        '<circle cx="17" cy="20" r="1.5" fill="white" stroke="none"/>',
    ),

    "MagneticLasso": _s(
        '<path d="M7 7 C4 10 4 15 7 18 C10 21 15 21 18 18 '
        'C21 15 21 10 18 7" stroke-dasharray="3,2"/>',
        '<circle cx="7" cy="7" r="2" fill="white" stroke="none"/>',
        '<circle cx="18" cy="7" r="2" fill="white" stroke="none"/>',
        '<circle cx="18" cy="18" r="2" fill="white" stroke="none"/>',
        '<circle cx="7" cy="18" r="2" fill="white" stroke="none"/>',
    ),

    "MagicWand": _raw(
        # Wand handle + sparkles
        f'<line x1="3" y1="21" x2="15" y2="9" {_W25} fill="none"/>',
        f'<line x1="17" y1="3" x2="17" y2="7" {_W}/>',
        f'<line x1="15" y1="5" x2="19" y2="5" {_W}/>',
        f'<line x1="21" y1="9" x2="21" y2="11" {_W}/>',
        f'<line x1="20" y1="10" x2="22" y2="10" {_W}/>',
        f'<line x1="20" y1="4" x2="22" y2="6" {_W}/>',
        f'<line x1="22" y1="4" x2="20" y2="6" {_W}/>',
    ),

    "QuickSelection": _s(
        '<circle cx="10" cy="14" r="6" stroke-dasharray="3,2"/>',
        '<path d="M16 6 Q20 9 19 13" stroke-width="2"/>',
        '<circle cx="16" cy="6" r="2" fill="white" stroke="none"/>',
    ),

    "ObjectSelection": _s(
        '<rect x="4" y="5" width="16" height="14" stroke-dasharray="4,2"/>',
        '<rect x="9" y="9" width="6" height="6"/>',
    ),

    # ── Crop / Frame / Slice ───────────────────────────────────────────────────

    "Crop": _raw(
        # Two bold L-brackets (classic PS crop icon)
        f'<path d="M7 2 L7 17 L22 17" {_W25} fill="none"/>',
        f'<path d="M2 7 L17 7 L17 22" {_W25} fill="none"/>',
    ),

    "Perspective Crop": _s(
        '<polygon points="3,21 21,21 18,7 6,7"/>',
        '<line x1="3" y1="21" x2="6" y2="7"/>',
        '<line x1="21" y1="21" x2="18" y2="7"/>',
    ),

    "Slice": _s(
        '<rect x="4" y="4" width="16" height="16" stroke-dasharray="3,2"/>',
        '<line x1="4" y1="4" x2="20" y2="20"/>',
        '<line x1="4" y1="20" x2="20" y2="4"/>',
    ),

    "Frame": _s(
        '<rect x="3" y="3" width="18" height="18"/>',
        '<rect x="7" y="7" width="10" height="10"/>',
        '<line x1="3" y1="3" x2="7" y2="7"/>',
        '<line x1="21" y1="3" x2="17" y2="7"/>',
        '<line x1="3" y1="21" x2="7" y2="17"/>',
        '<line x1="21" y1="21" x2="17" y2="17"/>',
    ),

    # ── Eyedropper / Measure ──────────────────────────────────────────────────

    "Eyedropper": _s(
        # Dropper body
        '<path d="M15 5 L18 8 L9 17 L6 17 L6 14 L15 5 Z"/>',
        # Tip
        '<line x1="6" y1="17" x2="4" y2="20"/>',
        # Top cap
        '<path d="M15 5 C16 3 18 3 19 4 C20 5 20 7 18 8"/>',
    ),

    "ColorSampler": _s(
        '<path d="M13 5 L16 8 L8 16 L5 16 L5 13 L13 5 Z"/>',
        '<line x1="5" y1="16" x2="3" y2="19"/>',
        '<path d="M13 5 C14 3 16 3 17 4 C18 5 18 7 16 8"/>',
        # Crosshair target
        '<line x1="21" y1="20" x2="21" y2="23"/>',
        '<line x1="19.5" y1="21.5" x2="22.5" y2="21.5"/>',
    ),

    "Ruler": _s(
        '<rect x="3" y="9" width="18" height="6" rx="1"/>',
        '<line x1="6" y1="9" x2="6" y2="12"/>',
        '<line x1="9" y1="9" x2="9" y2="11"/>',
        '<line x1="12" y1="9" x2="12" y2="12"/>',
        '<line x1="15" y1="9" x2="15" y2="11"/>',
        '<line x1="18" y1="9" x2="18" y2="12"/>',
    ),

    # ── Healing ────────────────────────────────────────────────────────────────

    "SpotHealing": _raw(
        f'<circle cx="11" cy="14" r="6" {_WS}/>',
        f'<line x1="11" y1="11" x2="11" y2="17" {_W}/>',
        f'<line x1="8" y1="14" x2="14" y2="14" {_W}/>',
        f'<circle cx="18" cy="6" r="1.5" {_WF}/>',
        f'<circle cx="21" cy="8" r="1" {_WF}/>',
        f'<circle cx="20" cy="4" r="1" {_WF}/>',
    ),

    "HealingBrush": _s(
        '<circle cx="11" cy="14" r="6"/>',
        '<line x1="11" y1="11" x2="11" y2="17"/>',
        '<line x1="8" y1="14" x2="14" y2="14"/>',
        '<path d="M16 5 Q19 3 21 6"/>',
    ),

    "Patch": _s(
        '<path d="M5 12 C5 7 8 4 12 4 C16 4 19 7 19 12 '
        'C19 17 16 20 12 20 C8 20 5 17 5 12 Z" stroke-dasharray="3,2"/>',
        '<line x1="12" y1="4" x2="12" y2="20"/>',
        '<line x1="5" y1="12" x2="19" y2="12"/>',
    ),

    "RedEye": _s(
        '<path d="M3 12 C5 8 8 5 12 5 C16 5 19 8 21 12 '
        'C19 16 16 19 12 19 C8 19 5 16 3 12"/>',
        '<circle cx="12" cy="12" r="3"/>',
        '<line x1="9" y1="9" x2="15" y2="15" stroke-width="2"/>',
    ),

    # ── Clone / Pattern Stamp ──────────────────────────────────────────────────

    "CloneStamp": _s(
        # Stamp head (round pad)
        '<rect x="5" y="4" width="14" height="10" rx="4"/>',
        # Handle
        '<line x1="12" y1="14" x2="12" y2="20"/>',
        '<line x1="8" y1="20" x2="16" y2="20"/>',
    ),

    "PatternStamp": _raw(
        f'<rect x="5" y="4" width="14" height="10" rx="4" {_WS}/>',
        f'<line x1="12" y1="14" x2="12" y2="20" {_W}/>',
        f'<line x1="8" y1="20" x2="16" y2="20" {_W}/>',
        # Pattern dots on the stamp face
        f'<circle cx="9" cy="8" r="1.2" {_WF}/>',
        f'<circle cx="12" cy="10" r="1.2" {_WF}/>',
        f'<circle cx="15" cy="8" r="1.2" {_WF}/>',
        f'<circle cx="12" cy="6" r="1.2" {_WF}/>',
    ),

    # ── Brush / Pencil ─────────────────────────────────────────────────────────

    "Brush": _raw(
        # Brush tip (filled teardrop)
        f'<path d="M6 21 C6 21 8 18 11 14 L18 7 C19 5 21 5 21 7 '
        f'C21 9 19 10 18 11 L11 18 C8 20 6 21 6 21 Z" {_WF}/>',
        # Bristle tip at bottom
        f'<path d="M6 21 C5 22 4 23 5 23 C6 23 7 22 6 21" {_WF}/>',
    ),

    "Pencil": _raw(
        # Pencil body (rotated rectangle)
        f'<path d="M5 19 L17 7 C18 6 20 6 21 7 C22 8 22 10 21 11 L9 19 Z" {_WF}/>',
        # Tip
        f'<path d="M5 19 L7 21 L4 22 Z" {_WF}/>',
        # Eraser band
        f'<line x1="17" y1="7" x2="19" y2="9" stroke="gray" stroke-width="1.5"/>',
    ),

    "ColorReplacement": _raw(
        # Brush stroke
        f'<path d="M6 20 C6 20 9 17 12 13 L19 6 C21 4 23 6 21 8 '
        f'L14 15 C11 18 7 20 6 20 Z" {_WF}/>',
        # Swap arrows (color replacement indicator)
        f'<path d="M4 5 Q4 3 6 3 Q8 3 8 5 Q8 7 6 7" {_WS}/>',
        f'<polyline points="4,7 6,9 8,7" {_WS}/>',
    ),

    "MixerBrush": _s(
        # Multiple bristles
        '<line x1="7" y1="4" x2="5" y2="20"/>',
        '<line x1="11" y1="3" x2="10" y2="20"/>',
        '<line x1="15" y1="3" x2="15" y2="20"/>',
        '<line x1="19" y1="4" x2="19" y2="20"/>',
        '<path d="M5 17 Q12 20 19 17"/>',
    ),

    "HistoryBrush": _raw(
        # History arc (spiral-like)
        f'<path d="M5 12 C5 7 8 4 12 4 C17 4 20 8 20 12" {_WS}/>',
        f'<polyline points="20,8 20,12 16,12" {_WS}/>',
        # Brush stroke coming from history arc
        f'<path d="M10 14 L18 6 C20 4 22 6 20 8 L12 16 C10 20 4 21 4 21" {_WS}/>',
    ),

    # ── Eraser ─────────────────────────────────────────────────────────────────

    "Eraser": _raw(
        # Classic PS eraser — angled rectangle, two-tone
        f'<path d="M21 19 L9 19 L3 13 C2 12 2 10 3 9 L12 4 '
        f'C13 3 15 4 16 5 L22 16 C23 18 22 19 21 19 Z" {_WS}/>',
        # Middle dividing line
        f'<line x1="9" y1="19" x2="15" y2="10" {_W}/>',
        # Bottom baseline
        f'<line x1="9" y1="19" x2="21" y2="19" {_W}/>',
    ),

    "BackgroundEraser": _s(
        '<rect x="3" y="12" width="9" height="8" rx="1" '
        'transform="rotate(-20 7.5 16)"/>',
        '<circle cx="16" cy="9" r="6" stroke-dasharray="3,2"/>',
    ),

    "MagicEraser": _raw(
        f'<rect x="3" y="13" width="9" height="8" rx="1" '
        f'transform="rotate(-20 7.5 17)" {_WS}/>',
        f'<circle cx="17" cy="7" r="1.5" {_WF}/>',
        f'<circle cx="20" cy="10" r="1.2" {_WF}/>',
        f'<circle cx="21" cy="5" r="1.2" {_WF}/>',
        f'<circle cx="14" cy="5" r="1.2" {_WF}/>',
    ),

    # ── Fill / Gradient ────────────────────────────────────────────────────────

    "Fill": _raw(
        # Bucket body
        f'<path d="M6 3 L14 11 L10 15 C8 17 6 16 6 14 Z" {_WF}/>',
        # Bucket spout
        f'<path d="M14 11 L16 13 C18 15 18 18 18 19 C18 22 15 22 15 22 '
        f'C15 22 12 22 12 19 C12 17 14 15 14 11" {_WS}/>',
        # Handle
        f'<line x1="16" y1="3" x2="20" y2="1" {_W}/>',
    ),

    "Gradient": _raw(
        '<defs>'
        '<linearGradient id="tig" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="white" stop-opacity="1"/>'
        '<stop offset="1" stop-color="white" stop-opacity="0.05"/>'
        '</linearGradient>'
        '</defs>'
        f'<rect x="3" y="7" width="18" height="10" rx="1.5" fill="url(#tig)"/>',
        f'<rect x="3" y="7" width="18" height="10" rx="1.5" {_WS}/>',
    ),

    # ── Effect tools ───────────────────────────────────────────────────────────

    "Blur": _raw(
        # Water-drop / teardrop shape
        f'<path d="M12 4 C12 4 5 12 5 16 C5 20 8 22 12 22 '
        f'C16 22 19 20 19 16 C19 12 12 4 12 4 Z" {_WS}/>',
        # Inner highlight (softness indicator)
        f'<path d="M9 16 C9 14 10 13 11 13" {_WS}/>',
    ),

    "Sharpen": _raw(
        # Upward-pointing diamond — sharpness symbol
        f'<polygon points="12,3 20,19 12,15 4,19" {_WF}/>',
    ),

    "Smudge": _s(
        # Fingertip + smear stroke
        '<path d="M5 6 C9 4 13 8 11 13 C9 18 7 19 7 19"/>',
        '<path d="M11 13 Q15 15 18 20"/>',
        '<circle cx="18" cy="20" r="2.5" fill="white" stroke="none"/>',
    ),

    "Dodge": _raw(
        # Classic dodge tool — lollipop / balloon on stick
        f'<circle cx="12" cy="8" r="6" {_WS}/>',
        f'<line x1="9" y1="13" x2="7" y2="22" {_W}/>',
        f'<line x1="15" y1="13" x2="17" y2="22" {_W}/>',
        f'<line x1="6" y1="20" x2="18" y2="20" {_W}/>',
    ),

    "Burn": _raw(
        # Classic burn tool — cupped / pinched arc
        f'<path d="M6 22 C3 17 4 12 8 10 C12 8 16 10 18 14 '
        f'C20 18 19 22 16 22" {_WS}/>',
        f'<line x1="6" y1="22" x2="16" y2="22" {_W}/>',
        f'<path d="M12 10 C10 7 11 5 12 4 C13 6 14 5 15 4 '
        f'C14 7 12 10 12 10 Z" {_WF}/>',
    ),

    "Sponge": _raw(
        # Rounded sponge cloud shape
        f'<path d="M8 6 C6 4 4 5 4 7 C4 9 5 10 7 11 '
        f'C5 12 4 14 5 16 C6 18 8 19 10 18 '
        f'C11 20 13 21 15 20 C17 21 19 19 19 17 '
        f'C21 16 21 14 20 12 C22 11 22 9 21 7 '
        f'C20 5 18 5 16 6 C15 4 13 3 12 4 C11 3 9 4 8 6 Z" {_WS}/>',
    ),

    # ── Pen ────────────────────────────────────────────────────────────────────

    "Pen": _raw(
        # Pen nib + handle
        f'<path d="M4 20 L11 13 L16 7 C17 5 19 5 20 6 '
        f'C21 7 19 9 18 10 L12 15 Z" {_WF}/>',
        # Nib tip (small triangle)
        f'<path d="M4 20 L7 22 L4 24 Z" {_WF}/>',
        # Nib fold line
        f'<line x1="11" y1="13" x2="14" y2="10" stroke="black" stroke-width="0.8"/>',
    ),

    "FreeformPen": _s(
        '<path d="M4 18 C7 12 10 14 13 10 C16 6 18 8 21 5"/>',
        '<path d="M4 18 L6 20 L3 21 Z" fill="white" stroke="none"/>',
        '<circle cx="4" cy="18" r="1.5" fill="white" stroke="none"/>',
    ),

    "CurvaturePen": _raw(
        f'<path d="M4 18 C5 10 9 8 12 12 C15 16 19 15 21 8" {_WS}/>',
        f'<circle cx="4" cy="18" r="2.5" {_WS}/>',
        f'<circle cx="12" cy="12" r="2.5" {_WS}/>',
        f'<circle cx="21" cy="8" r="2.5" {_WS}/>',
    ),

    "AddAnchor": _raw(
        f'<path d="M3 20 L9 14 L14 9" {_WS}/>',
        f'<circle cx="9" cy="14" r="2.5" {_WS}/>',
        # Plus sign
        f'<line x1="18" y1="3" x2="18" y2="11" {_W}/>',
        f'<line x1="14" y1="7" x2="22" y2="7" {_W}/>',
    ),

    "DeleteAnchor": _raw(
        f'<path d="M3 20 L9 14 L14 9" {_WS}/>',
        f'<circle cx="9" cy="14" r="2.5" {_WS}/>',
        # Minus sign
        f'<line x1="14" y1="7" x2="22" y2="7" {_W}/>',
    ),

    "ConvertPoint": _raw(
        # Arrow + corner point conversion
        f'<path d="M3 21 L12 4 L21 21" {_WS}/>',
        f'<circle cx="12" cy="12" r="3" {_WS}/>',
        f'<line x1="9" y1="16" x2="15" y2="16" {_W}/>',
    ),

    "PathSelection": _raw(
        # Solid black/filled arrow — path selection
        f'<polygon points="3,3 21,12 10,13 7,21" {_WF}/>',
    ),

    "DirectSelection": _raw(
        # Hollow arrow — direct/node selection
        f'<polygon points="3,3 21,12 10,13 7,21" {_WS}/>',
    ),

    # ── Text ───────────────────────────────────────────────────────────────────

    "Text": _raw(
        '<text x="12" y="20" font-size="20" font-family="Georgia,Times New Roman,serif" '
        'font-weight="bold" fill="white" text-anchor="middle">T</text>',
    ),

    "TextV": _raw(
        '<text x="12" y="20" font-size="18" font-family="Georgia,Times New Roman,serif" '
        'font-weight="bold" fill="white" text-anchor="middle" '
        'transform="rotate(-90 12 13)">T</text>',
        f'<line x1="2" y1="22" x2="22" y2="22" {_W}/>',
    ),

    "TextHMask": _raw(
        '<text x="12" y="19" font-size="17" font-family="Georgia,Times New Roman,serif" '
        'font-weight="bold" fill="none" stroke="white" stroke-width="0.7" '
        'text-anchor="middle">T</text>',
        f'<rect x="3" y="3" width="18" height="18" rx="1" fill="none" '
        f'stroke="white" stroke-width="1" stroke-dasharray="3,2"/>',
    ),

    "TextVMask": _raw(
        '<text x="12" y="19" font-size="17" font-family="Georgia,Times New Roman,serif" '
        'font-weight="bold" fill="none" stroke="white" stroke-width="0.7" '
        'text-anchor="middle" transform="rotate(-90 12 12)">T</text>',
        f'<rect x="3" y="3" width="18" height="18" rx="1" fill="none" '
        f'stroke="white" stroke-width="1" stroke-dasharray="3,2"/>',
    ),

    # ── Shapes ────────────────────────────────────────────────────────────────

    "Shapes": _raw(
        # Rectangle behind + polygon in front (like PS shapes panel)
        f'<rect x="3" y="9" width="13" height="12" rx="1" {_WS}/>',
        f'<polygon points="11,3 21,3 21,13" {_WF}/>',
    ),

    # ── Navigation ────────────────────────────────────────────────────────────

    "Hand": _s(
        # Simplified open hand
        '<path d="M9 21 L9 11 C9 9.5 10 9 11 9 C12 9 13 9.5 13 11"/>',
        '<path d="M13 10 C13 8.5 14 8 15 8 C16 8 17 8.5 17 10"/>',
        '<path d="M17 10 C17 8.5 18 8 19 9 C20 10 20 11 20 12 L20 16 '
        'C20 19 18 21 15 21 L9 21"/>',
        '<path d="M9 13 C9 13 7 12 6 13 C5 14 5 16 5 17 C5 19 7 21 9 21"/>',
    ),

    "Zoom": _raw(
        f'<circle cx="10" cy="10" r="7" {_WS}/>',
        f'<line x1="15.2" y1="15.2" x2="21" y2="21" {_W2} fill="none"/>',
        # + inside (zoom in)
        f'<line x1="7" y1="10" x2="13" y2="10" {_W}/>',
        f'<line x1="10" y1="7" x2="10" y2="13" {_W}/>',
    ),

    "RotateView": _s(
        '<path d="M20 8 C20 5 17 4 12 4 C7 4 4 8 4 12 C4 16 7 20 12 20 C17 20 20 17 20 14"/>',
        '<polyline points="20,4 20,8 16,8"/>',
    ),
}

# Fallback for unknown tools
_FALLBACK: bytes = _s('<rect x="4" y="4" width="16" height="16" rx="3"/>')


def get_tool_icon(name: str, size: int = 22) -> QIcon:
    """
    Return a QIcon for the given tool name.
    Returns QIcon() (isNull) if QtSvg is not available or rendering fails.
    """
    if not _SVG_OK:
        return QIcon()
    svg_bytes = _ICONS.get(name, _FALLBACK)
    try:
        renderer = QSvgRenderer(QByteArray(svg_bytes))
        if not renderer.isValid():
            return QIcon()
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon()
