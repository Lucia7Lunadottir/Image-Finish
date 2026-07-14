"""Central theme: every color the UI uses, plus the stylesheet builder.

Panels and dialogs must import colors from here instead of hardcoding hex
strings. Two palettes are provided (Catppuccin Mocha dark / Latte light);
`set_theme()` rebinds the module-level names, so code reading `theme.X`
at call time follows the active theme. Styles baked at import time keep
the startup theme until restart.
"""

import sys
import weakref

PALETTES = {
    "dark": {   # Catppuccin Mocha
        "CRUST": "#11111b", "MANTLE": "#181825", "BASE": "#1e1e2e",
        "OVERLAY": "#24273a", "SURFACE0": "#313244", "SURFACE1": "#45475a",
        "SURFACE2": "#585b70",
        "TEXT": "#cdd6f4", "SUBTEXT": "#a6adc8", "MUTED": "#7f849c",
        "ACCENT": "#7c3aed", "ACCENT_LIGHT": "#a855f7", "ACCENT_DARK": "#6d28d9",
        "DANGER": "#8b1a1a", "DANGER_BORDER": "#a03030", "DANGER_TEXT": "#f38ba8",
    },
    "light": {  # Catppuccin Latte
        "CRUST": "#dce0e8", "MANTLE": "#e6e9ef", "BASE": "#eff1f5",
        "OVERLAY": "#e6e9ef", "SURFACE0": "#ccd0da", "SURFACE1": "#bcc0cc",
        "SURFACE2": "#acb0be",
        "TEXT": "#4c4f69", "SUBTEXT": "#5c5f77", "MUTED": "#7c7f93",
        "ACCENT": "#8839ef", "ACCENT_LIGHT": "#a06bfa", "ACCENT_DARK": "#6f2dbd",
        "DANGER": "#e64553", "DANGER_BORDER": "#d20f39", "DANGER_TEXT": "#7a0f1f",
    },
}

FONT_STACK = '"Segoe UI", "Ubuntu", "Noto Sans", sans-serif'
GRID_COLOR = "#808080"

_current_name = "dark"


def make_custom_palette(main_hex: str, base_name: str = "dark") -> dict:
    """Derive a full palette from one main color.

    Backgrounds keep the lightness profile of the base palette but take on
    the main color's hue (modulated saturation — the "gray × main color"
    idea); the accent family is the main color itself.
    """
    from PyQt6.QtGui import QColor
    base = PALETTES.get(base_name, PALETTES["dark"])
    tint = QColor(main_hex)
    if not tint.isValid():
        return dict(base)
    th, ts, tv, _ = tint.getHsvF()
    if th < 0:
        th = 0.0

    out = {}
    for key, hex_val in base.items():
        if key in ("DANGER", "DANGER_BORDER", "DANGER_TEXT"):
            out[key] = hex_val
            continue
        c = QColor(hex_val)
        _h, s, v, _a = c.getHsvF()
        if key == "ACCENT":
            out[key] = tint.name()
        elif key == "ACCENT_LIGHT":
            out[key] = QColor.fromHsvF(th, max(0.0, ts * 0.85), min(1.0, tv * 1.2 + 0.08)).name()
        elif key == "ACCENT_DARK":
            out[key] = QColor.fromHsvF(th, min(1.0, ts * 1.05), tv * 0.75).name()
        elif key in ("TEXT", "SUBTEXT", "MUTED"):
            # Readability first: keep near-neutral, just a whisper of hue
            out[key] = QColor.fromHsvF(th, min(s, 0.12), v).name()
        else:
            # Surfaces: base lightness × the main color's hue
            out[key] = QColor.fromHsvF(th, min(0.45, max(s, ts * 0.35)), v).name()
    return out


def set_theme(name: str) -> None:
    """Rebind the module-level color names to the chosen palette.
    `name` is "dark", "light" or "custom" (built from the saved main color)."""
    global _current_name
    if name == "custom":
        try:
            from PyQt6.QtCore import QSettings
            s = QSettings("ImageFinish", "ImageFinish")
            main_hex = str(s.value("theme_custom_color", "#7c3aed"))
            base_name = str(s.value("theme_custom_base", "dark"))
        except Exception:
            main_hex, base_name = "#7c3aed", "dark"
        palette = make_custom_palette(main_hex, base_name)
    else:
        palette = PALETTES.get(name)
    if palette is None:
        return
    _current_name = name
    mod = sys.modules[__name__]
    for key, value in palette.items():
        setattr(mod, key, value)
    # Semantic aliases
    mod.WINDOW_BG = palette["BASE"]
    mod.PANEL_BG = palette["MANTLE"]
    mod.POPUP_BG = palette["OVERLAY"]
    mod.INPUT_BG = palette["SURFACE0"]
    mod.BORDER = palette["SURFACE0"]
    mod.INPUT_BORDER = palette["SURFACE1"]
    mod.SELECTION = palette["ACCENT"]
    repolish_all()



def current_theme() -> str:
    return _current_name


# ── live restyling ───────────────────────────────────────────────────────────
# Widgets whose stylesheets contain palette colors register here; on a theme
# switch repolish_all() re-evaluates every style function and re-applies it.

_style_registry: list = []   # (weakref.ref(widget), callable -> str)


def apply_style(widget, style) -> None:
    """setStyleSheet + registration for live theme switching.
    `style` is a zero-arg callable returning the QSS text (evaluated now and
    again on every repolish_all()); plain strings are applied unregistered."""
    text = style() if callable(style) else style
    widget.setStyleSheet(text)
    if callable(style):
        if len(_style_registry) > 4096:
            _style_registry[:] = [(r, f) for r, f in _style_registry if r() is not None]
        _style_registry.append((weakref.ref(widget), style))


def repolish_all() -> None:
    alive = []
    for ref, fn in _style_registry:
        w = ref()
        if w is None:
            continue
        try:
            w.setStyleSheet(fn())
            alive.append((ref, fn))
        except RuntimeError:
            pass  # C++ side already deleted
    _style_registry[:] = alive


def load_saved_theme() -> str:
    try:
        from PyQt6.QtCore import QSettings
        return str(QSettings("ImageFinish", "ImageFinish").value("theme", "dark"))
    except Exception:
        return "dark"


def save_theme(name: str) -> None:
    try:
        from PyQt6.QtCore import QSettings
        QSettings("ImageFinish", "ImageFinish").setValue("theme", name)
    except Exception:
        pass


# Bind the saved (or default) palette at import time so import-time styles
# in panels pick up the right colors from the very start.
_saved = load_saved_theme()
set_theme(_saved if _saved in (*PALETTES, "custom") else "dark")


def build_stylesheet() -> str:
    """The application-wide QSS, generated from the palette above."""
    return f"""
/* ───────────────────────── Global ───────────────────────── */
QMainWindow, QDialog {{
    background-color: {BASE};
}}
QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}
QSplitter::handle {{
    background-color: {SURFACE0};
    width: 2px;
    height: 2px;
}}

/* ─────────────────────── Menu / Status ─────────────────── */
QMenuBar {{
    background-color: {MANTLE};
    color: {TEXT};
    border-bottom: 1px solid {SURFACE0};
    padding: 2px 4px;
}}
QMenuBar::item:selected {{
    background-color: {SURFACE0};
    border-radius: 4px;
}}
QMenu {{
    background-color: {OVERLAY};
    border: 1px solid #414559;
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QMenu::separator {{
    height: 1px;
    background-color: #414559;
    margin: 4px 8px;
}}
QStatusBar {{
    background-color: {MANTLE};
    color: {SUBTEXT};
    font-size: 12px;
}}

/* ─────────────────────── Toolbar (left) ────────────────── */
QWidget#toolbar {{
    background-color: {MANTLE};
    border-right: 1px solid {SURFACE0};
}}
QPushButton#toolBtn, QToolButton#toolBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {TEXT};
    font-size: 18px;
    padding: 4px;
}}
QPushButton#toolBtn:hover, QToolButton#toolBtn:hover {{
    background-color: {SURFACE0};
    border-color: {SURFACE2};
}}
QPushButton#toolBtn[active="true"], QToolButton#toolBtn[active="true"] {{
    background-color: {ACCENT};
    border-color: {ACCENT_LIGHT};
    color: white;
}}
QToolButton#toolBtn::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    bottom: 2px;
    right: 2px;
}}

/* ──────────────────── Tool Options Bar ─────────────────── */
QWidget#toolOptionsBar {{
    background-color: {MANTLE};
    border-bottom: 1px solid {SURFACE0};
    padding: 4px 8px;
}}
QLabel#optLabel {{
    color: {SUBTEXT};
    font-size: 12px;
    min-width: 70px;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {SURFACE0};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: {ACCENT_LIGHT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background-color: {ACCENT};
    border-radius: 2px;
}}
QSpinBox, QDoubleSpinBox {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    color: {TEXT};
    padding: 4px 6px;
}}
QComboBox {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    color: {TEXT};
    padding: 3px 8px;
    min-width: 90px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {SURFACE1};
    border-radius: 0 3px 3px 0;
}}
QComboBox::down-arrow {{
    image: url(ui/arrow_down.svg);
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {OVERLAY};
    border: 1px solid {SURFACE1};
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    outline: none;
}}

/* ────────────────────────── Panels ─────────────────────── */
QWidget#panel {{
    background-color: {MANTLE};
    border-left: 1px solid {SURFACE0};
}}
QLabel#panelTitle {{
    font-size: 11px;
    font-weight: bold;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 10px 4px 10px;
}}
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {SURFACE0};
}}
QTabBar::tab {{
    background-color: {MANTLE};
    color: {MUTED};
    padding: 6px 12px;
    border: none;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background-color: {BASE};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: {OVERLAY};
    color: {SUBTEXT};
}}

/* ─────────────────── Dock panels (Photoshop-like) ───────── */
QDockWidget {{
    background-color: {MANTLE};
    color: {TEXT};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {MANTLE};
    color: {MUTED};
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 6px 10px;
    border-bottom: 1px solid {SURFACE0};
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {SURFACE0};
    border-radius: 3px;
}}
QMainWindow::separator {{
    background-color: {SURFACE0};
    width: 3px;
    height: 3px;
}}
QMainWindow::separator:hover {{
    background-color: {ACCENT};
}}

/* ──────────────────────── Layer List ───────────────────── */
QListWidget {{
    background-color: {MANTLE};
    border: none;
    outline: none;
}}
QListWidget::item {{
    background-color: transparent;
    border-radius: 4px;
    padding: 2px 4px;
    min-height: 32px;
}}
QListWidget::item:selected {{
    background-color: {SURFACE0};
    color: white;
}}
QListWidget::item:hover {{
    background-color: {OVERLAY};
}}

/* ─────────────────────── Small Buttons ─────────────────── */
QPushButton#smallBtn {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    color: {TEXT};
    padding: 3px 6px;
    font-size: 12px;
}}
QPushButton#smallBtn:hover {{
    background-color: {SURFACE1};
}}
QPushButton#smallBtn:pressed {{
    background-color: {ACCENT};
}}
QPushButton#dangerBtn {{
    background-color: {DANGER};
    border: 1px solid {DANGER_BORDER};
    border-radius: 4px;
    color: {DANGER_TEXT};
    padding: 3px 6px;
    font-size: 12px;
}}
QPushButton#dangerBtn:hover {{
    background-color: {DANGER_BORDER};
}}

/* ────────────────── Text-tool style toggle buttons ─────────── */
QPushButton#styleToggleBtn {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    color: {TEXT};
    padding: 2px;
}}
QPushButton#styleToggleBtn:hover {{
    background-color: {SURFACE1};
}}
QPushButton#styleToggleBtn:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT_LIGHT};
    color: #ffffff;
}}
QPushButton#styleToggleBtn:checked:hover {{
    background-color: {ACCENT_DARK};
}}

/* ─────────────────────── Scroll Bars ───────────────────── */
QScrollBar:vertical {{
    background-color: {BASE};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {SURFACE1};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{
    background-color: {BASE};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {SURFACE1};
    border-radius: 4px;
    min-width: 20px;
}}

/* ───────────────────── Input / Line Edit ───────────────── */
QLineEdit {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    color: {TEXT};
    padding: 4px 8px;
}}
QLineEdit:focus {{
    border-color: {ACCENT_LIGHT};
}}

/* ──────────────────────── Tooltips ─────────────────────── */
QToolTip {{
    background-color: {OVERLAY};
    color: {TEXT};
    border: 1px solid {SURFACE2};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ─────────────────────── Document tabs ─────────────────── */
QTabWidget#docTabs QTabBar::tab {{
    padding: 6px 14px;
    background: {BASE};
    color: {SUBTEXT};
    border-right: 1px solid {SURFACE0};
    text-transform: none;
    letter-spacing: 0px;
}}
QTabWidget#docTabs QTabBar::tab:selected {{
    background: {SURFACE0};
    color: {TEXT};
    font-weight: bold;
}}
"""
