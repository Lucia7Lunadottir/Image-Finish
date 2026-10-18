"""Every tool of the app, declared once.

A tool is one `ToolSpec` line in `TOOL_GROUPS`: its class, toolbar icon,
shortcut, translated title and options-bar page. Everything that lists
tools — the window's tool instances (`build_tools`), the toolbar buttons
and fly-out groups (ui/toolbar.py), the options-bar pages
(ui/tool_options_bar.py), history step names (`tool_title`) — reads it
from here.

Adding a tool: write the class (tools/), add a `ToolSpec` to a group (or a
one-tool group for its own button), give it an options page (an existing
`OptionsPage` to share it, or a new one), add the `tool.<key>` string to
locales/, and an SVG to assets/icons/ (or a drawn icon in ui/tool_icons.py).
"""
from dataclasses import dataclass, field
from typing import Callable

from core.locale import tr

from tools.advanced_erasers import BackgroundEraserTool, MagicEraserTool
from tools.artboard_tool import ArtboardTool
from tools.brush_tool import (BrushTool, CloneStampTool, ColorReplacementTool, EraserTool,
                              HistoryBrushTool, MixerBrushTool, PatternStampTool, PencilTool)
from tools.effect_tools import BlurTool, BurnTool, DodgeTool, SharpenTool, SmudgeTool, SpongeTool
from tools.fill_tool import FillTool
from tools.frame_tool import FrameTool
from tools.lasso_tools import LassoTool, MagneticLassoTool, PolygonalLassoTool
from tools.magic_wand_tool import MagicWandTool, ObjectSelectionTool, QuickSelectionTool
from tools.measure_tools import ColorSamplerTool, RulerTool
from tools.other_tools import (CropTool, EllipticalSelectTool, EyedropperTool, GradientTool,
                               HandTool, HorizontalTypeMaskTool, MoveTool, PerspectiveCropTool,
                               RotateViewTool, SelectTool, ShapesTool, TextTool,
                               VerticalTypeMaskTool, VerticalTypeTool, ZoomTool)
from tools.patch_tool import HealingBrushTool, PatchTool, RedEyeTool, SpotHealingTool
from tools.pen_tool import (AddAnchorPointTool, ConvertPointTool, CurvaturePenTool,
                            DeleteAnchorPointTool, DirectSelectionTool, FreeformPenTool,
                            PathSelectionTool, PenTool)
from tools.perspective_warp_tool import PerspectiveWarpTool
from tools.puppet_warp_tool import PuppetWarpTool
from tools.slice_tool import SliceTool
from tools.warp_tool import WarpTool

from ui.tool_options.bg_eraser_options import BackgroundEraserOptions
from ui.tool_options.brush_options import BrushOptions
from ui.tool_options.crop_options import CropOptions
from ui.tool_options.effect_options import EffectOptions, SpongeOptions
from ui.tool_options.empty_options import EmptyOptions
from ui.tool_options.fill_options import FillOptions
from ui.tool_options.frame_options import FrameOptions
from ui.tool_options.gradient_options import GradientOptions
from ui.tool_options.magnetic_lasso_options import MagneticLassoOptions
from ui.tool_options.measure_options import ColorSamplerOptions, RulerOptions
from ui.tool_options.move_options import MoveOptions
from ui.tool_options.patch_options import PatchOptions, RedEyeOptions, SpotHealingOptions
from ui.tool_options.pattern_stamp_options import PatternStampOptions
from ui.tool_options.pen_options import PenOptions
from ui.tool_options.perspective_crop_options import PerspectiveCropOptions
from ui.tool_options.rotate_view_options import RotateViewOptions
from ui.tool_options.select_options import SelectOptions
from ui.tool_options.shapes_options import ShapesOptions
from ui.tool_options.slice_options import SliceOptions
from ui.tool_options.text_options import TextOptions


@dataclass(frozen=True, eq=False)
class OptionsPage:
    """One options-bar page. Tools that name the same OptionsPage object
    share one widget (all brush-like tools show the Brush page)."""
    make: Callable[[], object]


@dataclass(frozen=True)
class ToolSpec:
    name: str                  # id: history, settings, `_tools[...]`
    make: Callable[[], object]  # the tool class (or a factory)
    icon_file: str             # SVG in assets/icons/ (drawn fallback: ui/tool_icons.py)
    shortcut: str
    tr_key: str
    options: OptionsPage

    @property
    def title(self) -> str:
        return tr(self.tr_key)


@dataclass(frozen=True)
class ToolGroup:
    """One toolbar button: a single tool, or a fly-out of several (the
    first one is the default)."""
    id: str
    tools: tuple[ToolSpec, ...] = field(default_factory=tuple)


# ── options pages ──────────────────────────────────────────────────────────
BRUSH = OptionsPage(BrushOptions)
FILL = OptionsPage(FillOptions)              # also Magic Eraser / Magic Wand: Tolerance
SELECT = OptionsPage(SelectOptions)
BG_ERASER = OptionsPage(BackgroundEraserOptions)
PEN = OptionsPage(PenOptions)
TEXT = OptionsPage(TextOptions)


def _page(cls, *args, **kwargs) -> OptionsPage:
    return OptionsPage(lambda: cls(*args, **kwargs))


T = ToolSpec

TOOL_GROUPS: tuple[ToolGroup, ...] = (
    ToolGroup("MoveGroup", (
        T("Move", MoveTool, "move.svg", "V", "tool.move",
          _page(MoveOptions, "opts.move_hint", numeric=True)),
        T("Artboard", ArtboardTool, "artboard.svg", "V", "tool.artboard",
          _page(EmptyOptions, "tool.artboard")),
        T("Warp", WarpTool, "warp.svg", "V", "tool.warp",
          _page(MoveOptions, "opts.warp_hint")),
        T("PuppetWarp", PuppetWarpTool, "warp-puppet.svg", "V", "tool.puppet_warp",
          _page(MoveOptions, "opts.puppet_warp_hint")),
        T("PerspectiveWarp", PerspectiveWarpTool, "warp-perspective.svg", "V", "tool.perspective_warp",
          _page(MoveOptions, "opts.perspective_warp_hint")),
    )),
    ToolGroup("HealingGroup", (
        T("SpotHealing", SpotHealingTool, "patch-spot.svg", "J", "tool.spot_healing",
          _page(SpotHealingOptions, "opts.spot_healing_hint")),
        T("HealingBrush", HealingBrushTool, "patch-healing.svg", "J", "tool.healing_brush",
          _page(SpotHealingOptions, "opts.healing_brush_hint")),
        T("Patch", PatchTool, "patch-spot.svg", "J", "tool.patch", _page(PatchOptions)),
        T("RedEye", RedEyeTool, "other.svg", "J", "tool.red_eye", _page(RedEyeOptions)),
        T("CloneStamp", CloneStampTool, "patch-healing.svg", "S", "tool.clone_stamp", BRUSH),
        T("PatternStamp", PatternStampTool, "patch-healing.svg", "S", "tool.pattern_stamp",
          _page(PatternStampOptions)),
    )),
    ToolGroup("BrushGroup", (
        T("Brush", BrushTool, "brush.svg", "B", "tool.brush", BRUSH),
        T("Pencil", PencilTool, "pencil.svg", "B", "tool.pencil", BRUSH),
        T("ColorReplacement", ColorReplacementTool, "brush.svg", "B", "tool.color_replacement", BRUSH),
        T("MixerBrush", MixerBrushTool, "brush.svg", "B", "tool.mixer_brush", BRUSH),
        T("HistoryBrush", HistoryBrushTool, "history-brush.svg", "Y", "tool.history_brush", BRUSH),
    )),
    ToolGroup("EraserGroup", (
        T("Eraser", EraserTool, "eraser.svg", "E", "tool.eraser", BRUSH),
        T("BackgroundEraser", BackgroundEraserTool, "eraser-background.svg", "E", "tool.bg_eraser",
          BG_ERASER),
        T("MagicEraser", MagicEraserTool, "eraser-background.svg", "E", "tool.magic_eraser", FILL),
    )),
    ToolGroup("Fill", (
        T("Fill", FillTool, "paint-bucket.svg", "K", "tool.fill", FILL),
    )),
    ToolGroup("Gradient", (
        T("Gradient", GradientTool, "gradient.svg", "G", "tool.gradient", _page(GradientOptions)),
    )),
    ToolGroup("Effects", (
        T("Blur", BlurTool, "effect-blur.svg", "R", "tool.blur",
          _page(EffectOptions, "opts.effect.blur", show_hardness=True)),
        T("Sharpen", SharpenTool, "effect-sharpen.svg", "Y", "tool.sharpen",
          _page(EffectOptions, "opts.effect.sharpen", show_hardness=True)),
        T("Smudge", SmudgeTool, "effect-smudge.svg", "W", "tool.smudge",
          _page(EffectOptions, "opts.effect.smudge", show_hardness=True)),
    )),
    ToolGroup("ToningGroup", (
        T("Dodge", DodgeTool, "effect-dodge.svg", "O", "tool.dodge",
          _page(EffectOptions, "opts.effect.dodge")),
        T("Burn", BurnTool, "effect-burn.svg", "O", "tool.burn",
          _page(EffectOptions, "opts.effect.burn")),
        T("Sponge", SpongeTool, "effect-sponge.svg", "O", "tool.sponge", _page(SpongeOptions)),
    )),
    ToolGroup("Marquee", (
        T("Select", SelectTool, "marquee-rect.svg", "M", "tool.select", SELECT),
        T("EllipseSelect", EllipticalSelectTool, "marquee-ellipse.svg", "", "tool.ellipse_select",
          SELECT),
    )),
    ToolGroup("PathSelectGroup", (
        T("PathSelection", PathSelectionTool, "path-selection.svg", "A", "tool.path_selection", PEN),
        T("DirectSelection", DirectSelectionTool, "direct-selection.svg", "A",
          "tool.direct_selection", PEN),
    )),
    ToolGroup("PenGroup", (
        T("Pen", PenTool, "pen.svg", "P", "tool.pen", PEN),
        T("FreeformPen", FreeformPenTool, "pen.svg", "P", "tool.freeform_pen", PEN),
        T("CurvaturePen", CurvaturePenTool, "pen.svg", "P", "tool.curvature_pen", PEN),
        T("AddAnchor", AddAnchorPointTool, "pen.svg", "", "tool.add_anchor", PEN),
        T("DeleteAnchor", DeleteAnchorPointTool, "pen.svg", "", "tool.delete_anchor", PEN),
        T("ConvertPoint", ConvertPointTool, "direct-selection.svg", "", "tool.convert_point", PEN),
    )),
    ToolGroup("Shapes", (
        T("Shapes", ShapesTool, "shape-rect.svg", "U", "tool.shapes", _page(ShapesOptions)),
    )),
    ToolGroup("Type", (
        T("Text", TextTool, "text.svg", "T", "tool.text", TEXT),
        T("TextV", VerticalTypeTool, "text.svg", "", "tool.text_v", TEXT),
        T("TextHMask", HorizontalTypeMaskTool, "text.svg", "", "tool.text_h_mask", TEXT),
        T("TextVMask", VerticalTypeMaskTool, "text.svg", "", "tool.text_v_mask", TEXT),
    )),
    ToolGroup("EyedropperGroup", (
        T("Eyedropper", EyedropperTool, "eyedropper.svg", "I", "tool.eyedropper",
          _page(EmptyOptions, "tool.eyedropper")),
        T("ColorSampler", ColorSamplerTool, "eyedropper.svg", "I", "tool.color_sampler",
          _page(ColorSamplerOptions)),
        T("Ruler", RulerTool, "measure-ruler.svg", "I", "tool.ruler", _page(RulerOptions)),
    )),
    ToolGroup("Crop", (
        T("Crop", CropTool, "crop.svg", "C", "tool.crop", _page(CropOptions)),
        T("Perspective Crop", PerspectiveCropTool, "crop-perspective.svg", "", "tool.perspective_crop",
          _page(PerspectiveCropOptions)),
        T("Slice", SliceTool, "slice.svg", "C", "tool.slice", _page(SliceOptions)),
        T("Frame", FrameTool, "frame.svg", "K", "tool.frame", _page(FrameOptions)),
    )),
    ToolGroup("Nav", (
        T("Hand", HandTool, "nav-hand.svg", "H", "tool.hand", _page(EmptyOptions, "opts.hand_hint")),
        T("Zoom", ZoomTool, "nav-zoom.svg", "Z", "tool.zoom", _page(EmptyOptions, "opts.zoom_hint")),
        T("RotateView", RotateViewTool, "nav-rotate.svg", "", "tool.rotate_view",
          _page(RotateViewOptions)),
    )),
    ToolGroup("LassoGroup", (
        T("Lasso", LassoTool, "lasso.svg", "L", "tool.lasso", SELECT),
        T("PolygonalLasso", PolygonalLassoTool, "lasso-polygonal.svg", "", "tool.poly_lasso", SELECT),
        T("MagneticLasso", MagneticLassoTool, "lasso-magnetic.svg", "", "tool.mag_lasso",
          _page(MagneticLassoOptions)),
    )),
    ToolGroup("WandGroup", (
        T("MagicWand", MagicWandTool, "wand.svg", "W", "tool.magic_wand", FILL),
        T("QuickSelection", QuickSelectionTool, "brush-selection.svg", "W", "tool.quick_selection",
          BG_ERASER),
        T("ObjectSelection", ObjectSelectionTool, "box-selection.svg", "W", "tool.object_selection",
          SELECT),
    )),
)

del T

TOOLS: dict[str, ToolSpec] = {spec.name: spec for group in TOOL_GROUPS for spec in group.tools}


def tool_title(name: str) -> str:
    """The translated name of a tool (history steps, messages)."""
    spec = TOOLS.get(name)
    return spec.title if spec else name


def build_tools(window) -> dict:
    """One instance of every tool, attached to the window that owns them."""
    tools = {}
    for spec in TOOLS.values():
        tool = spec.make()
        tool.attach(window)
        tools[spec.name] = tool
    return tools
