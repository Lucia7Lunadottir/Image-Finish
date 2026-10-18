import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy, QToolButton, QMenu
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QByteArray
from PyQt6.QtGui import QIcon, QPixmap

from core.locale import tr
from ui import theme
from ui.tool_catalog import TOOL_GROUPS, TOOLS, ToolSpec

from core.app_logging import get_logger

logger = get_logger("toolbar")


# IMPORTANT: Compute absolute path to project root.
# __file__ points to ui/toolbar.py. 
# First dirname goes up to ui/, second — to project root (where assets lives).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def _tool_icon(td: ToolSpec) -> QIcon:
    """Icon fallback chain: SVG file -> drawn built-in icon -> null."""
    ico = _load_recolored_icon(td.icon_file)
    if not ico.isNull():
        return ico
    from ui.tool_icons import get_tool_icon
    return get_tool_icon(td.name)


def _apply_icon(btn, td: ToolSpec, size: int = 22) -> None:
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

        for group in TOOL_GROUPS:
            if len(group.tools) > 1:
                layout.addWidget(self._make_group_button(group.id, [t.name for t in group.tools]))
                continue

            td = group.tools[0]
            tool_name = td.name
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
            td = TOOLS.get(tool_name)
            if td:
                _apply_icon(w, td)
        for gid, gbtn in self._groups.items():
            active_tool = self._group_active_tool.get(gid)
            td = TOOLS.get(active_tool) if active_tool else None
            if td:
                _apply_icon(gbtn, td)
        self.retranslate()  # rebuilds dropdown menus (and their icons)

    def retranslate(self):
        """Update localization for context menus and tooltips."""
        for tool_name, w in self._buttons.items():
            td = TOOLS.get(tool_name)
            if isinstance(w, QPushButton) and td:
                w.setToolTip(self._make_tip(td.tr_key, td.shortcut))

        for gid, gbtn in self._groups.items():
            active_tool = self._group_active_tool.get(gid)
            td = TOOLS.get(active_tool) if active_tool else None
            if td:
                gbtn.setToolTip(self._make_tip(td.tr_key, td.shortcut))
            
            menu = gbtn.menu()
            if menu:
                menu.clear()
                for tname in self._group_tools.get(gid, []):
                    tdef = TOOLS[tname]
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
            td = TOOLS.get(tool_name)
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

        td = TOOLS[default_tool]
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
            tdef = TOOLS[tname]
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