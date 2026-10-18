"""Right-click menu on the canvas, as in Photoshop: what it offers depends
on the active tool.

A tool names its menu with `CONTEXT_MENU` (tools/base_tool.py); each name
maps to one `CanvasMenu` class here, which fills a QMenu from the window's
existing commands. An open transform (Move/Warp...) takes precedence over
the tool's own menu.

Adding a menu for a tool: set its `CONTEXT_MENU`, and if the name is new,
write a `CanvasMenu` subclass and register it in `_MENUS`.
"""
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QSlider, QSpinBox, QVBoxLayout,
                             QWidget, QWidgetAction)

from core.locale import tr


@dataclass
class MenuContext:
    win: object          # the MainWindow (its commands)
    canvas: object
    doc: object
    tool: object
    doc_pos: QPoint      # where the click was, in document coordinates

    @property
    def has_selection(self) -> bool:
        sel = self.doc.selection
        return sel is not None and not sel.isEmpty()


class CanvasMenu:
    """One kind of right-click menu."""

    def fill(self, menu: QMenu, ctx: MenuContext) -> None:
        raise NotImplementedError

    @staticmethod
    def _add(menu: QMenu, key: str, slot, enabled: bool = True):
        act = menu.addAction(tr(key))
        act.triggered.connect(lambda _=False: slot())
        act.setEnabled(enabled)
        return act


class TransformMenu(CanvasMenu):
    """While a transform is open: finish it, or turn/mirror it."""

    def fill(self, menu, ctx):
        w = ctx.win
        self._add(menu, "opts.apply", w._commit_transforms)
        self._add(menu, "opts.cancel", w._cancel_transform)
        if not hasattr(ctx.tool, "rotate_by"):    # mesh / perspective warps
            return
        menu.addSeparator()
        self._add(menu, "ctx.transform.rotate_180", lambda: w._transform_rotate(180))
        self._add(menu, "ctx.transform.rotate_cw", lambda: w._transform_rotate(90))
        self._add(menu, "ctx.transform.rotate_ccw", lambda: w._transform_rotate(-90))
        menu.addSeparator()
        can_flip = ctx.tool.can_flip
        self._add(menu, "ctx.transform.flip_h", lambda: w._transform_flip(True), can_flip)
        self._add(menu, "ctx.transform.flip_v", lambda: w._transform_flip(False), can_flip)


class SelectionMenu(CanvasMenu):
    """Marquee, Lasso and Magic Wand family."""

    def fill(self, menu, ctx):
        w = ctx.win
        if ctx.has_selection:
            self._add(menu, "menu.deselect", w._deselect)
            self._add(menu, "menu.inverse", w._inverse_selection)
            self._add(menu, "menu.modify.feather", lambda: w._modify_selection("feather"))
            self._add(menu, "menu.select_and_mask", w._select_and_mask)
            self._add(menu, "menu.save_selection", w._save_selection)
            menu.addSeparator()
            self._add(menu, "menu.layer_via_copy", w._layer_via_copy)
            self._add(menu, "menu.layer_via_cut", w._layer_via_cut)
        else:
            self._add(menu, "menu.select_all", w._select_all)
            self._add(menu, "menu.reselect", w._reselect,
                      getattr(w, "_last_selection", None) is not None)
            self._add(menu, "menu.select_subject", w._select_subject)
        self._add(menu, "menu.new_layer", w._add_layer)
        menu.addSeparator()
        self._add(menu, "menu.free_transform", w._free_transform)
        menu.addSeparator()
        self._add(menu, "menu.fill_fg", w._fill_fg)
        self._add(menu, "menu.fill_bg", w._fill_bg)


class MoveMenu(CanvasMenu):
    """The layers under the pointer, topmost first — picking one makes it
    active (Photoshop's Move-tool right click)."""

    def fill(self, menu, ctx):
        doc = ctx.doc
        for i in range(len(doc.layers) - 1, -1, -1):
            layer = doc.layers[i]
            if layer.visible and layer.hit_test(ctx.doc_pos):
                act = menu.addAction(layer.name)
                act.setCheckable(True)
                act.setChecked(i == doc.active_layer_index)
                act.triggered.connect(lambda _=False, idx=i: ctx.win._on_layer_selected_wrap(idx))
        if not menu.isEmpty():
            menu.addSeparator()
        self._add(menu, "menu.free_transform", ctx.win._free_transform)


class BrushMenu(CanvasMenu):
    """Size and hardness right under the pointer (Photoshop's brush picker)."""

    def fill(self, menu, ctx):
        action = QWidgetAction(menu)
        action.setDefaultWidget(BrushQuickPanel(ctx.win, ctx.canvas.tool_opts))
        menu.addAction(action)


class PathMenu(CanvasMenu):
    """Pen and path-selection tools: what to do with the work path."""

    def fill(self, menu, ctx):
        w = ctx.win
        wp = getattr(ctx.doc, "work_path", None) or {}
        has_path = bool(wp.get("nodes"))
        self._add(menu, "paths.make_sel", lambda: w._path_make_selection(wp), has_path)
        self._add(menu, "paths.fill", lambda: w._path_fill(wp), has_path)
        self._add(menu, "paths.stroke", lambda: w._path_stroke(wp), has_path)
        self._add(menu, "opts.pen.shape", lambda: w._on_opt_changed("pen_action", "shape"), has_path)
        menu.addSeparator()
        self._add(menu, "paths.delete", lambda: w._on_opt_changed("pen_action", "clear"), has_path)


class CropMenu(CanvasMenu):

    def fill(self, menu, ctx):
        w = ctx.win
        if hasattr(ctx.tool, "pending_quad"):
            pending = ctx.tool.pending_quad is not None
            self._add(menu, "menu.apply_perspective_crop", w._apply_perspective_crop, pending)
        else:
            pending = ctx.tool.pending_rect is not None
            self._add(menu, "menu.apply_crop", w._apply_crop, pending)
        self._add(menu, "opts.cancel", lambda: w._cancel_crop(ctx.tool), pending)


class ViewMenu(CanvasMenu):
    """Hand, Zoom, Rotate View."""

    def fill(self, menu, ctx):
        c = ctx.canvas
        self._add(menu, "menu.fit_window", c.reset_zoom)
        self._add(menu, "ctx.view.actual_size", c.zoom_actual_size)
        self._add(menu, "menu.zoom_in", c.zoom_in)
        self._add(menu, "menu.zoom_out", c.zoom_out)
        menu.addSeparator()
        self._add(menu, "ctx.view.reset_rotation", c.reset_rotation, bool(c._view_rotation))


_MENUS: dict[str, CanvasMenu] = {
    "selection": SelectionMenu(),
    "move": MoveMenu(),
    "brush": BrushMenu(),
    "path": PathMenu(),
    "crop": CropMenu(),
    "view": ViewMenu(),
}
_TRANSFORM = TransformMenu()


def build_canvas_menu(ctx: MenuContext, parent=None) -> QMenu | None:
    """The menu for a right click, or None when the tool offers none."""
    from tools.transform_base import TransformTool
    if isinstance(ctx.tool, TransformTool) and ctx.tool.is_transforming:
        kind = _TRANSFORM
    else:
        kind = _MENUS.get(getattr(ctx.tool, "CONTEXT_MENU", None))
    if kind is None:
        return None
    menu = QMenu(parent)
    kind.fill(menu, ctx)
    return menu if not menu.isEmpty() else None


class BrushQuickPanel(QWidget):
    """Size and hardness sliders writing through the window's option
    handler, so the options bar and every open document follow."""

    _SIZE_SLIDER_MAX = 500

    def __init__(self, win, opts: dict, parent=None):
        super().__init__(parent)
        self._win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self._size = self._row(lay, "opts.size", 1, 5000, int(opts.get("brush_size", 10)), "")
        self._hard = self._row(lay, "opts.hardness", 0, 100,
                               int(round(opts.get("brush_hardness", 1.0) * 100)), "%")
        self._size[1].valueChanged.connect(lambda v: self._set("brush_size", v))
        self._hard[1].valueChanged.connect(lambda v: self._set("brush_hardness", v / 100.0))

    def _row(self, lay, key, lo, hi, value, suffix):
        row = QHBoxLayout()
        row.addWidget(QLabel(tr(key)))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, min(hi, self._SIZE_SLIDER_MAX))
        slider.setMinimumWidth(160)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSuffix(suffix)
        spin.setValue(value)
        slider.setValue(value)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(lambda v: self._follow(slider, v))
        row.addWidget(slider)
        row.addWidget(spin)
        lay.addLayout(row)
        return slider, spin

    @staticmethod
    def _follow(slider, value):
        """The spin box goes past the slider's range; the slider just pins
        at its end without echoing that back into the spin box."""
        slider.blockSignals(True)
        slider.setValue(min(value, slider.maximum()))
        slider.blockSignals(False)

    def _set(self, key, value):
        self._win._on_opt_changed(key, value)
        page = self._win._opts_bar.page_for(self._win._active_tool_name)
        canvas = self._win._canvas
        if page is not None and hasattr(page, "update_from_opts") and canvas is not None:
            page.update_from_opts(canvas.tool_opts)
