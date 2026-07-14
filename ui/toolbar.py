import os
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy, QToolButton, QMenu
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QByteArray
from PyQt6.QtGui import QIcon, QPixmap

from core.locale import tr
from ui import theme

from core.app_logging import get_logger

logger = get_logger("toolbar")


# IMPORTANT: Compute absolute path to project root.
# __file__ points to ui/toolbar.py. 
# First dirname goes up to ui/, second — to project root (where assets lives).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class _ToolDef:
    name: str
    icon_file: str      # SVG filename in assets/icons/
    fallback_icon: str  # Emoji fallback if file not found
    shortcut: str
    tr_key: str


def _load_recolored_icon(icon_file: str, color: str | None = None) -> QIcon:
    """
    Safely loads an SVG file using a hard absolute path,
    replacing the default stroke color (currentColor) with the chosen one.
    Default follows the theme text color, so icons stay visible in the
    light theme too.
    """
    if color is None:
        color = theme.TEXT
    # FIXED: Path is now built from BASE_DIR, not from the terminal launch directory
    icon_path = os.path.join(BASE_DIR, "assets", "icons", icon_file)
    
    if os.path.exists(icon_path):
        try:
            with open(icon_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
            
            # Change stroke color on-the-fly in the SVG text structure
            svg_content = svg_content.replace('stroke="currentColor"', f'stroke="{color}"')
            
            # Convert modified string to bytes and load into QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(QByteArray(svg_content.encode('utf-8')), "SVG")
            return QIcon(pixmap)
        except Exception as e:
            logger.warning("Dynamic recolor error for %s: %s", icon_file, e)
    return QIcon()


def _tool_icon(td: _ToolDef) -> QIcon:
    """Icon fallback chain: SVG file -> drawn built-in icon -> null."""
    ico = _load_recolored_icon(td.icon_file)
    if not ico.isNull():
        return ico
    from ui.tool_icons import get_tool_icon
    return get_tool_icon(td.name)


def _apply_icon(btn, td: _ToolDef, size: int = 22) -> None:
    """Applies a recolored icon to a toolbar button."""
    ico = _tool_icon(td)
    if not ico.isNull():
        btn.setIcon(ico)
        btn.setIconSize(QSize(size, size))
        btn.setText("")
    else:
        btn.setIcon(QIcon())
        btn.setText(td.name[:2])


class ToolBar(QWidget):
    """
    Vertical tool panel (left side).
    Emits tool_selected(tool_name) signal on switch.
    """

    tool_selected = pyqtSignal(str)

    # Complete mapping of all 58 tools to SVG files
    _TOOL_DEFS: dict[str, _ToolDef] = {
        "Move":            _ToolDef("Move",            "move.svg",            "✋",  "V", "tool.move"),
        "Artboard":        _ToolDef("Artboard",        "artboard.svg",        "🔲", "V", "tool.artboard"),
        "Warp":            _ToolDef("Warp",            "warp.svg",            "🕸️", "V", "tool.warp"),
        "PuppetWarp":      _ToolDef("PuppetWarp",      "warp-puppet.svg",     "📌", "V", "tool.puppet_warp"),
        "PerspectiveWarp": _ToolDef("PerspectiveWarp",  "warp-perspective.svg", "🗺️", "V", "tool.perspective_warp"),
        
        "Brush":           _ToolDef("Brush",           "brush.svg",           "🖌️", "B", "tool.brush"),
        "Pencil":          _ToolDef("Pencil",          "pencil.svg",          "✏️", "B", "tool.pencil"),
        "ColorReplacement":_ToolDef("ColorReplacement", "brush.svg",           "🖌️🎨", "B", "tool.color_replacement"),
        "MixerBrush":      _ToolDef("MixerBrush",      "brush.svg",           "🖌️💧", "B", "tool.mixer_brush"),
        "HistoryBrush":    _ToolDef("HistoryBrush",    "history-brush.svg",   "🕰️", "Y", "tool.history_brush"),
        
        "CloneStamp":      _ToolDef("CloneStamp",      "patch-healing.svg",   "⎘",  "S", "tool.clone_stamp"),
        "PatternStamp":    _ToolDef("PatternStamp",    "patch-healing.svg",   "💠", "S", "tool.pattern_stamp"),
        
        "SpotHealing":     _ToolDef("SpotHealing",     "patch-spot.svg",      "🩹✨", "J", "tool.spot_healing"),
        "HealingBrush":    _ToolDef("HealingBrush",    "patch-healing.svg",   "🩹🖌️", "J", "tool.healing_brush"),
        "Patch":           _ToolDef("Patch",           "patch-spot.svg",      "🩹", "J", "tool.patch"),
        "RedEye":          _ToolDef("RedEye",          "other.svg",           "👁️", "J", "tool.red_eye"),
        
        "Eraser":          _ToolDef("Eraser",          "eraser.svg",          "🧹",  "E", "tool.eraser"),
        "BackgroundEraser":_ToolDef("BackgroundEraser", "eraser-background.svg", "✂️", "E", "tool.bg_eraser"),
        "MagicEraser":     _ToolDef("MagicEraser",     "eraser-background.svg", "🎇", "E", "tool.magic_eraser"),
        
        "Fill":            _ToolDef("Fill",            "paint-bucket.svg",    "🪣",  "K", "tool.fill"),
        "Gradient":        _ToolDef("Gradient",        "gradient.svg",        "🌈",  "G", "tool.gradient"),
        
        "Blur":            _ToolDef("Blur",            "effect-blur.svg",     "💧",  "R", "tool.blur"),
        "Sharpen":         _ToolDef("Sharpen",         "effect-sharpen.svg",  "🔺",  "Y", "tool.sharpen"),
        "Smudge":          _ToolDef("Smudge",          "effect-smudge.svg",   "👆",  "W", "tool.smudge"),
        
        "Dodge":           _ToolDef("Dodge",           "effect-dodge.svg",    "🌔",  "O", "tool.dodge"),
        "Burn":            _ToolDef("Burn",            "effect-burn.svg",     "🌒",  "O", "tool.burn"),
        "Sponge":          _ToolDef("Sponge",          "effect-sponge.svg",   "🧽",  "O", "tool.sponge"),
        
        "Select":          _ToolDef("Select",          "marquee-rect.svg",    "⬜",  "M", "tool.select"),
        "EllipseSelect":   _ToolDef("EllipseSelect",   "marquee-ellipse.svg", "⭕",  "",  "tool.ellipse_select"),
        "Shapes":          _ToolDef("Shapes",          "shape-rect.svg",      "🔷",  "U", "tool.shapes"),
        
        "Pen":             _ToolDef("Pen",             "pen.svg",             "✒️", "P", "tool.pen"),
        "FreeformPen":     _ToolDef("FreeformPen",     "pen.svg",             "✍️", "P", "tool.freeform_pen"),
        "CurvaturePen":    _ToolDef("CurvaturePen",    "pen.svg",             "〰️", "P", "tool.curvature_pen"),
        "AddAnchor":       _ToolDef("AddAnchor",       "pen.svg",             "✒️+", "", "tool.add_anchor"),
        "DeleteAnchor":    _ToolDef("DeleteAnchor",    "pen.svg",             "✒️-", "", "tool.delete_anchor"),
        "ConvertPoint":    _ToolDef("ConvertPoint",    "direct-selection.svg", "^",  "", "tool.convert_point"),
        
        "PathSelection":   _ToolDef("PathSelection",   "path-selection.svg",  "↖", "A", "tool.path_selection"),
        "DirectSelection": _ToolDef("DirectSelection", "direct-selection.svg", "↗", "A", "tool.direct_selection"),
        
        "Text":            _ToolDef("Text",            "text.svg",            "T",   "T", "tool.text"),
        "TextV":           _ToolDef("TextV",           "text.svg",            "Tv",  "",  "tool.text_v"),
        "TextHMask":       _ToolDef("TextHMask",       "text.svg",            "Tm",  "",  "tool.text_h_mask"),
        "TextVMask":       _ToolDef("TextVMask",       "text.svg",            "Vm",  "",  "tool.text_v_mask"),
        
        "Eyedropper":      _ToolDef("Eyedropper",      "eyedropper.svg",      "💉",  "I", "tool.eyedropper"),
        "ColorSampler":    _ToolDef("ColorSampler",    "eyedropper.svg",      "🎯",  "I", "tool.color_sampler"),
        "Ruler":           _ToolDef("Ruler",           "measure-ruler.svg",   "📏",  "I", "tool.ruler"),
        
        "Crop":            _ToolDef("Crop",            "crop.svg",            "✂️",  "C", "tool.crop"),
        "Perspective Crop":_ToolDef("Perspective Crop", "crop-perspective.svg", "📐", "", "tool.perspective_crop"),
        "Slice":           _ToolDef("Slice",           "slice.svg",           "🔪", "C", "tool.slice"),
        "Frame":           _ToolDef("Frame",           "frame.svg",           "⛶", "K", "tool.frame"),
        
        "Hand":            _ToolDef("Hand",            "nav-hand.svg",        "🖐",  "H", "tool.hand"),
        "Zoom":            _ToolDef("Zoom",            "nav-zoom.svg",        "🔍",  "Z", "tool.zoom"),
        "RotateView":      _ToolDef("RotateView",      "nav-rotate.svg",      "🔄",  "",  "tool.rotate_view"),
        
        "Lasso":           _ToolDef("Lasso",           "lasso.svg",           "➰", "L", "tool.lasso"),
        "PolygonalLasso":  _ToolDef("PolygonalLasso",  "lasso-polygonal.svg", "⬡",  "",  "tool.poly_lasso"),
        "MagneticLasso":   _ToolDef("MagneticLasso",   "lasso-magnetic.svg",  "🧲", "",  "tool.mag_lasso"),
        
        "MagicWand":       _ToolDef("MagicWand",       "wand.svg",            "🪄", "W", "tool.magic_wand"),
        "QuickSelection":  _ToolDef("QuickSelection",  "brush-selection.svg", "🖌️✨", "W", "tool.quick_selection"),
        "ObjectSelection": _ToolDef("ObjectSelection", "box-selection.svg",   "📦",  "W", "tool.object_selection"),
    }

    _LAYOUT = [
        ("MoveGroup", ["Move", "Artboard", "Warp", "PuppetWarp", "PerspectiveWarp"]),
        ("HealingGroup", ["SpotHealing", "HealingBrush", "Patch", "RedEye", "CloneStamp", "PatternStamp"]),
        ("BrushGroup", ["Brush", "Pencil", "ColorReplacement", "MixerBrush", "HistoryBrush"]),
        ("EraserGroup", ["Eraser", "BackgroundEraser", "MagicEraser"]),
        "Fill",
        "Gradient",
        ("Effects", ["Blur", "Sharpen", "Smudge"]),
        ("ToningGroup", ["Dodge", "Burn", "Sponge"]),
        ("Marquee", ["Select", "EllipseSelect"]),
        ("PathSelectGroup", ["PathSelection", "DirectSelection"]),
        ("PenGroup", ["Pen", "FreeformPen", "CurvaturePen", "AddAnchor", "DeleteAnchor", "ConvertPoint"]),
        "Shapes",
        ("Type", ["Text", "TextV", "TextHMask", "TextVMask"]),
        ("EyedropperGroup", ["Eyedropper", "ColorSampler", "Ruler"]),
        ("Crop", ["Crop", "Perspective Crop", "Slice", "Frame"]),
        ("Nav", ["Hand", "Zoom", "RotateView"]),
        ("LassoGroup", ["Lasso", "PolygonalLasso", "MagneticLasso"]),
        ("WandGroup", ["MagicWand", "QuickSelection", "ObjectSelection"]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setFixedWidth(62)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._buttons: dict[str, QWidget] = {}
        self._groups: dict[str, QToolButton] = {}
        self._group_tools: dict[str, list[str]] = {}
        self._tool_to_group: dict[str, str] = {}
        self._group_active_tool: dict[str, str] = {}

        for item in self._LAYOUT:
            if isinstance(item, tuple):
                group_id, tool_names = item
                btn = self._make_group_button(group_id, tool_names)
                layout.addWidget(btn)
                continue

            tool_name = item
            td = self._TOOL_DEFS[tool_name]
            btn = QPushButton()
            _apply_icon(btn, td)
            btn.setObjectName("toolBtn")
            btn.setToolTip(self._make_tip(td.tr_key, td.shortcut))
            btn.setCheckable(False)
            btn.setFixedSize(46, 38)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, n=tool_name: self._on_click(n))
            layout.addWidget(btn)
            self._buttons[tool_name] = btn

        layout.addStretch()
        self.set_active("Brush")

    @staticmethod
    def _make_tip(key: str, shortcut: str) -> str:
        label = tr(key)
        return f"{label}  [{shortcut}]" if shortcut else label

    def retheme(self):
        """Re-render all icons in the current theme's text color."""
        for tool_name, w in self._buttons.items():
            td = self._TOOL_DEFS.get(tool_name)
            if td:
                _apply_icon(w, td)
        for gid, gbtn in self._groups.items():
            active_tool = self._group_active_tool.get(gid)
            td = self._TOOL_DEFS.get(active_tool) if active_tool else None
            if td:
                _apply_icon(gbtn, td)
        self.retranslate()  # rebuilds dropdown menus (and their icons)

    def retranslate(self):
        """Update localization for context menus and tooltips."""
        for tool_name, w in self._buttons.items():
            td = self._TOOL_DEFS.get(tool_name)
            if isinstance(w, QPushButton) and td:
                w.setToolTip(self._make_tip(td.tr_key, td.shortcut))

        for gid, gbtn in self._groups.items():
            active_tool = self._group_active_tool.get(gid)
            td = self._TOOL_DEFS.get(active_tool) if active_tool else None
            if td:
                gbtn.setToolTip(self._make_tip(td.tr_key, td.shortcut))
            
            menu = gbtn.menu()
            if menu:
                menu.clear()
                for tname in self._group_tools.get(gid, []):
                    tdef = self._TOOL_DEFS[tname]
                    ico = _tool_icon(tdef)
                    if not ico.isNull():
                        act = menu.addAction(ico, tr(tdef.tr_key))
                    else:
                        act = menu.addAction(tr(tdef.tr_key))
                    act.setData(tname)
                    act.triggered.connect(lambda checked=False, n=tname: self._on_click(n))

    def set_active(self, tool_name: str):
        # Single tools
        for name, w in self._buttons.items():
            if isinstance(w, QPushButton):
                w.setProperty("active", name == tool_name)
                w.style().unpolish(w)
                w.style().polish(w)

        # Tools in dropdown groups
        gid = self._tool_to_group.get(tool_name)
        for group_id, gbtn in self._groups.items():
            gbtn.setProperty("active", group_id == gid)
            gbtn.style().unpolish(gbtn)
            gbtn.style().polish(gbtn)

        if gid:
            self._group_active_tool[gid] = tool_name
            td = self._TOOL_DEFS.get(tool_name)
            if td:
                _apply_icon(self._groups[gid], td)
                self._groups[gid].setToolTip(self._make_tip(td.tr_key, td.shortcut))

    def _on_click(self, name: str):
        self.set_active(name)
        self.tool_selected.emit(name)

    def _make_group_button(self, group_id: str, tool_names: list[str]) -> QToolButton:
        default_tool = tool_names[0]
        self._group_tools[group_id] = list(tool_names)
        for t in tool_names:
            self._tool_to_group[t] = group_id
        self._group_active_tool[group_id] = default_tool

        td = self._TOOL_DEFS[default_tool]
        btn = QToolButton()
        btn.setObjectName("toolBtn")
        _apply_icon(btn, td)
        btn.setToolTip(self._make_tip(td.tr_key, td.shortcut))
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        btn.setFixedSize(46, 38)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, b=btn: b.menu().exec(b.mapToGlobal(pos)))

        # Create group dropdown menu
        menu = QMenu(btn)
        for tname in tool_names:
            tdef = self._TOOL_DEFS[tname]
            ico = _tool_icon(tdef)
            if not ico.isNull():
                act = menu.addAction(ico, tr(tdef.tr_key))
            else:
                act = menu.addAction(tr(tdef.tr_key))
            act.setData(tname)
            act.triggered.connect(lambda checked=False, n=tname: self._on_click(n))
        btn.setMenu(menu)

        btn.clicked.connect(lambda checked=False, gid=group_id: self._on_click(self._group_active_tool.get(gid, default_tool)))

        self._groups[group_id] = btn
        return btn