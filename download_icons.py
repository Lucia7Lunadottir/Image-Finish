import os
import urllib.request

# Path to the UI assets directory
ICON_DIR = os.path.join("assets", "icons")
os.makedirs(ICON_DIR, exist_ok=True)

# Complete mapping of ALL project tools based on the file structure in tools/
ICONS = {
    # move_tool.py and artboard_tool.py
    "move.svg": "https://unpkg.com/lucide-static@latest/icons/move.svg",
    "artboard.svg": "https://unpkg.com/lucide-static@latest/icons/presentation.svg",
    
    # select_tool.py (Region selection and path selection tools)
    "marquee-rect.svg": "https://unpkg.com/lucide-static@latest/icons/square-dashed.svg",
    "marquee-ellipse.svg": "https://unpkg.com/lucide-static@latest/icons/circle-dashed.svg",
    "path-selection.svg": "https://unpkg.com/lucide-static@latest/icons/mouse-pointer.svg",
    "direct-selection.svg": "https://unpkg.com/lucide-static@latest/icons/mouse-pointer-2.svg",
    
    # lasso_tools.py
    "lasso.svg": "https://unpkg.com/lucide-static@latest/icons/lasso.svg",
    "lasso-polygonal.svg": "https://unpkg.com/lucide-static@latest/icons/pentagon.svg",
    "lasso-magnetic.svg": "https://unpkg.com/lucide-static@latest/icons/magnet.svg",
    
    # magic_wand_tool.py
    "wand.svg": "https://unpkg.com/lucide-static@latest/icons/wand-2.svg",
    "brush-selection.svg": "https://unpkg.com/lucide-static@latest/icons/sparkles.svg",
    "box-selection.svg": "https://unpkg.com/lucide-static@latest/icons/box.svg",
    
    # crop_tool.py, perspective_crop_tool.py and slice_tool.py
    "crop.svg": "https://unpkg.com/lucide-static@latest/icons/crop.svg",
    "crop-perspective.svg": "https://unpkg.com/lucide-static@latest/icons/grid-3x3.svg",
    "slice.svg": "https://unpkg.com/lucide-static@latest/icons/grid-2x2.svg",
    
    # frame_tool.py
    "frame.svg": "https://unpkg.com/lucide-static@latest/icons/frame.svg",
    
    # eyedropper_tool.py and measure_tools.py
    "eyedropper.svg": "https://unpkg.com/lucide-static@latest/icons/pipette.svg",
    "measure-ruler.svg": "https://unpkg.com/lucide-static@latest/icons/ruler.svg",
    
    # patch_tool.py (Spot brush, Healing brush, Patch)
    "patch-spot.svg": "https://unpkg.com/lucide-static@latest/icons/bandage.svg",
    "patch-healing.svg": "https://unpkg.com/lucide-static@latest/icons/heart-pulse.svg",
    
    # brush_tool.py, eraser_tool.py and advanced_erasers.py
    "brush.svg": "https://unpkg.com/lucide-static@latest/icons/brush.svg",
    "pencil.svg": "https://unpkg.com/lucide-static@latest/icons/pencil.svg",
    "history-brush.svg": "https://unpkg.com/lucide-static@latest/icons/history.svg",
    "eraser.svg": "https://unpkg.com/lucide-static@latest/icons/eraser.svg",
    "eraser-background.svg": "https://unpkg.com/lucide-static@latest/icons/scissors-line-dashed.svg",
    
    # gradient_tool.py and fill_tool.py
    "gradient.svg": "https://unpkg.com/lucide-static@latest/icons/blend.svg",
    "paint-bucket.svg": "https://unpkg.com/lucide-static@latest/icons/paint-bucket.svg",
    
    # effect_tools.py (Blur, Sharpen, Smudge, Dodge, Burn, Sponge)
    "effect-blur.svg": "https://unpkg.com/lucide-static@latest/icons/droplet.svg",
    "effect-sharpen.svg": "https://unpkg.com/lucide-static@latest/icons/triangle.svg",
    "effect-smudge.svg": "https://unpkg.com/lucide-static@latest/icons/fingerprint.svg",
    "effect-dodge.svg": "https://unpkg.com/lucide-static@latest/icons/sun.svg",
    "effect-burn.svg": "https://unpkg.com/lucide-static@latest/icons/moon.svg",
    "effect-sponge.svg": "https://unpkg.com/lucide-static@latest/icons/wind.svg",
    
    # pen_tool.py and text_tool.py
    "pen.svg": "https://unpkg.com/lucide-static@latest/icons/pen-tool.svg",
    "text.svg": "https://unpkg.com/lucide-static@latest/icons/type.svg",
    
    # shapes_tool.py (Geometric shapes / Vectors)
    "shape-rect.svg": "https://unpkg.com/lucide-static@latest/icons/square.svg",
    "shape-ellipse.svg": "https://unpkg.com/lucide-static@latest/icons/circle.svg",
    "shape-poly.svg": "https://unpkg.com/lucide-static@latest/icons/hexagon.svg",
    "shape-line.svg": "https://unpkg.com/lucide-static@latest/icons/minus.svg",
    
    # nav_tools.py (Canvas navigation)
    "nav-hand.svg": "https://unpkg.com/lucide-static@latest/icons/hand.svg",
    "nav-rotate.svg": "https://unpkg.com/lucide-static@latest/icons/refresh-cw.svg",
    "nav-zoom.svg": "https://unpkg.com/lucide-static@latest/icons/search.svg",
    
    # warp_tool.py, perspective_warp_tool.py, puppet_warp_tool.py (Warps)
    "warp.svg": "https://unpkg.com/lucide-static@latest/icons/grip.svg",
    "warp-perspective.svg": "https://unpkg.com/lucide-static@latest/icons/boxes.svg",
    "warp-puppet.svg": "https://unpkg.com/lucide-static@latest/icons/git-commit.svg",
    
    # other_tools.py
    "other.svg": "https://unpkg.com/lucide-static@latest/icons/ellipsis.svg"
}

print(f"Starting download of professional icon set ({len(ICONS)} icons)...")
for filename, url in ICONS.items():
    target_path = os.path.join(ICON_DIR, filename)
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"OK: {filename}")
    except Exception as e:
        print(f"FAIL: {filename}: {e}")

print(f"\nDone! {len(ICONS)} icons saved to: assets/icons/")