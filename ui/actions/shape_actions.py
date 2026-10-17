from dataclasses import replace

from PyQt6.QtGui import QColor

from core.app_logging import get_logger
from core.gradient_model import Gradient
from core.locale import tr

logger = get_logger("shape_actions")


def _hex(c) -> str:
    return QColor(c).name(QColor.NameFormat.HexArgb)


# Options-bar key -> how it edits an existing shape. Appearance edits
# (fill/stroke) apply to both kinds of vector layer — ShapesTool shapes and
# Pen paths share ShapeAppearance; geometry edits only make sense for a
# parametric shape. Deliberately absent: "shape_type" — like Illustrator/
# Photoshop, a shape's primitive kind is a creation-time choice.
_APPEARANCE_EDITS = {
    "shape_color":          lambda a, v: replace(a, fill_color=QColor(v), stroke_color=QColor(v)),
    "shape_fill_color":     lambda a, v: replace(a, fill_color=QColor(v)),
    "shape_fill":           lambda a, v: replace(a, fill_enabled=bool(v)),
    "shape_fill_type":      lambda a, v: replace(a, fill_type=v),
    # The whole gradient (stops, style, angle, scale, reverse) as one
    # Gradient.to_dict() — the editor and its popup always send all of it.
    "shape_gradient":       lambda a, v: replace(a, gradient=Gradient.from_dict(v)),
    "shape_gradient_live":  lambda a, v: replace(a, gradient=Gradient.from_dict(v)),
    "shape_stroke":         lambda a, v: replace(a, stroke_enabled=bool(v)),
    "shape_stroke_width":   lambda a, v: replace(a, stroke_width=max(0.0, float(v))),
    "shape_stroke_color":   lambda a, v: replace(a, stroke_color=QColor(v)),
    "shape_stroke_style":   lambda a, v: replace(a, stroke_style=v),
    "shape_stroke_align":   lambda a, v: replace(a, stroke_align=v),
    "shape_stroke_cap":     lambda a, v: replace(a, stroke_cap=v),
    "shape_stroke_join":    lambda a, v: replace(a, stroke_join=v),
}

_GEOMETRY_EDITS = {
    "shape_sides":         lambda p, v: replace(p, sides=int(v)),
    "shape_corner_radius": lambda p, v: replace(p, corner_radii=(float(v),) * 4),
    "shape_corner_radii":  lambda p, v: replace(p, corner_radii=tuple(float(x) for x in v)),
    "shape_star_points":   lambda p, v: replace(p, star_points=int(v)),
    "shape_star_inner":    lambda p, v: replace(p, star_inner=float(v) / 100.0),
}


class ShapeActionsMixin:
    """When the Shapes tool is active and the active layer is a shape (or a
    Pen path) layer, options-bar edits re-render that existing layer live
    instead of only taking effect on the *next* shape drawn — the same idea
    as _apply_text_styles editing a text layer's already-placed text."""

    def _apply_shape_option_live(self, key: str, value) -> bool:
        if key not in _APPEARANCE_EDITS and key not in _GEOMETRY_EDITS and key != "shape_angle":
            return False
        from tools.shapes_tool import ShapesTool
        if not isinstance(self._canvas.active_tool, ShapesTool):
            return False
        doc = self._document
        layer = doc.get_active_layer() if doc else None
        if layer is None or not hasattr(layer, "has_vector_geometry") or not layer.has_vector_geometry():
            return False

        spec = layer.shape_spec()
        if key in _APPEARANCE_EDITS:
            new_appearance = _APPEARANCE_EDITS[key](layer.appearance(), value)
            if spec is not None:
                new_sd = replace(spec, appearance=new_appearance).to_dict(base=layer.shape_data)
                if key == "shape_color":
                    new_sd["fg"] = new_sd["bg"] = QColor(value).name()
                changed = new_sd != layer.shape_data
                apply = lambda: setattr(layer, "shape_data", new_sd)
            else:
                new_ps = dict(layer.path_style, **new_appearance.to_path_style())
                changed = new_ps != layer.path_style
                apply = lambda: setattr(layer, "path_style", new_ps)
        else:
            if spec is None:
                return False
            if key == "shape_angle":
                new_spec = spec.with_geometry(angle=float(value))
            else:
                new_spec = replace(spec, params=_GEOMETRY_EDITS[key](spec.params, value))
            new_sd = new_spec.to_dict(base=layer.shape_data)
            changed = new_sd != layer.shape_data
            apply = lambda: setattr(layer, "shape_data", new_sd)

        if not changed:
            return True
        self._open_shape_edit_history_session(layer, key)
        apply()
        layer.rebake_thumbnail()

        overlay = getattr(self._canvas, "_shape_overlay", None)
        if overlay is not None:
            item = overlay._items.get(layer.layer_id)
            if item is not None:
                item.sync_from_layer()
        self._canvas_refresh()
        return True

    def _sync_shape_options_from_layer(self, layer):
        """Pushes the just-selected shape's own properties into the
        options bar, so editing starts from that shape's real values
        instead of whatever was left over from the last shape drawn."""
        from tools.shapes_tool import ShapesTool
        if not isinstance(getattr(self._canvas, "active_tool", None), ShapesTool):
            return
        if layer is None or not hasattr(layer, "has_vector_geometry") or not layer.has_vector_geometry():
            return
        page = self._opts_bar._pages.get("Shapes") if hasattr(self, "_opts_bar") else None
        if page is None or not hasattr(page, "update_from_opts"):
            return
        a = layer.appearance()
        opts = {
            "shape_fill":           a.fill_enabled,
            "shape_fill_type":      a.fill_type,
            "shape_fill_color":     QColor(a.fill_color),
            "shape_gradient":       a.gradient.to_dict(),
            "shape_stroke":         a.stroke_enabled,
            "shape_stroke_width":   int(round(a.stroke_width)),
            "shape_stroke_color":   QColor(a.stroke_color),
            "shape_stroke_style":   a.stroke_style,
            "shape_stroke_align":   a.stroke_align,
            "shape_stroke_cap":     a.stroke_cap,
            "shape_stroke_join":    a.stroke_join,
        }
        spec = layer.shape_spec()
        if spec is not None:
            p = spec.params
            opts.update({
                "shape_type":         spec.shape,
                "shape_sides":        p.sides,
                "shape_angle":        int(round(spec.angle)) % 360,
                "shape_corner_radii": [int(round(v)) for v in p.corner_radii],
                "shape_star_points":  p.star_points,
                "shape_star_inner":   int(round(p.star_inner * 100)),
            })
        page.update_from_opts(opts)

    def _open_shape_edit_history_session(self, layer, key: str, description: str | None = None):
        """Coalesces a burst of rapid options-bar edits (a slider drag fires
        many valueChanged signals) into a single undo step, the same effect
        ShapeLayerItem's handle drags get from press/release — but options-
        bar controls give us no such start/end signal, so a short idle
        timeout stands in for "the drag ended"."""
        from PyQt6.QtCore import QTimer

        # The gradient editor streams "shape_gradient_live" while it's open
        # and one final "shape_gradient" on OK/Cancel: all of it is one
        # undo step, and the session stays open as long as the dialog does.
        hold = key.endswith("_live")
        key = key[:-5] if hold else key
        timeout = 24 * 3600 * 1000 if hold else 600
        session = getattr(self, "_shape_edit_session", None)
        if session == (layer.layer_id, key):
            self._shape_edit_history_timer.start(timeout)
            return

        self._push_history(description or tr("history.edit_shape"))
        self._shape_edit_session = (layer.layer_id, key)

        if not hasattr(self, "_shape_edit_history_timer"):
            self._shape_edit_history_timer = QTimer(self)
            self._shape_edit_history_timer.setSingleShot(True)
            self._shape_edit_history_timer.timeout.connect(
                lambda: setattr(self, "_shape_edit_session", None))
        self._shape_edit_history_timer.start(timeout)
