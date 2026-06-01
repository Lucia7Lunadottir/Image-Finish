import os
import urllib.request

# Путь к папке ресурсов интерфейса
ICON_DIR = os.path.join("assets", "icons")
os.makedirs(ICON_DIR, exist_ok=True)

# Полный маппинг для ВСЕХ инструментов вашего проекта на основе структуры файлов в tools/
ICONS = {
    # move_tool.py и artboard_tool.py
    "move.svg": "https://unpkg.com/lucide-static@latest/icons/move.svg",
    "artboard.svg": "https://unpkg.com/lucide-static@latest/icons/presentation.svg",
    
    # select_tool.py (Инструменты выделения областей и выбора контуров)
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
    
    # crop_tool.py, perspective_crop_tool.py и slice_tool.py
    "crop.svg": "https://unpkg.com/lucide-static@latest/icons/crop.svg",
    "crop-perspective.svg": "https://unpkg.com/lucide-static@latest/icons/grid-3x3.svg",
    "slice.svg": "https://unpkg.com/lucide-static@latest/icons/grid-2x2.svg",
    
    # frame_tool.py
    "frame.svg": "https://unpkg.com/lucide-static@latest/icons/frame.svg",
    
    # eyedropper_tool.py и measure_tools.py
    "eyedropper.svg": "https://unpkg.com/lucide-static@latest/icons/pipette.svg",
    "measure-ruler.svg": "https://unpkg.com/lucide-static@latest/icons/ruler.svg",
    
    # patch_tool.py (Точечная кисть, Лечащая кисть, Заплатка)
    "patch-spot.svg": "https://unpkg.com/lucide-static@latest/icons/bandage.svg",
    "patch-healing.svg": "https://unpkg.com/lucide-static@latest/icons/heart-pulse.svg",
    
    # brush_tool.py, eraser_tool.py и advanced_erasers.py
    "brush.svg": "https://unpkg.com/lucide-static@latest/icons/brush.svg",
    "pencil.svg": "https://unpkg.com/lucide-static@latest/icons/pencil.svg",
    "history-brush.svg": "https://unpkg.com/lucide-static@latest/icons/history.svg",
    "eraser.svg": "https://unpkg.com/lucide-static@latest/icons/eraser.svg",
    "eraser-background.svg": "https://unpkg.com/lucide-static@latest/icons/scissors-line-dashed.svg",
    
    # gradient_tool.py и fill_tool.py
    "gradient.svg": "https://unpkg.com/lucide-static@latest/icons/blend.svg",
    "paint-bucket.svg": "https://unpkg.com/lucide-static@latest/icons/paint-bucket.svg",
    
    # effect_tools.py (Размытие, Резкость, Палец, Осветлитель, Затемнитель, Губка)
    "effect-blur.svg": "https://unpkg.com/lucide-static@latest/icons/droplet.svg",
    "effect-sharpen.svg": "https://unpkg.com/lucide-static@latest/icons/triangle.svg",
    "effect-smudge.svg": "https://unpkg.com/lucide-static@latest/icons/fingerprint.svg",
    "effect-dodge.svg": "https://unpkg.com/lucide-static@latest/icons/sun.svg",
    "effect-burn.svg": "https://unpkg.com/lucide-static@latest/icons/moon.svg",
    "effect-sponge.svg": "https://unpkg.com/lucide-static@latest/icons/wind.svg",
    
    # pen_tool.py и text_tool.py
    "pen.svg": "https://unpkg.com/lucide-static@latest/icons/pen-tool.svg",
    "text.svg": "https://unpkg.com/lucide-static@latest/icons/type.svg",
    
    # shapes_tool.py (Геометрические фигуры / Векторы)
    "shape-rect.svg": "https://unpkg.com/lucide-static@latest/icons/square.svg",
    "shape-ellipse.svg": "https://unpkg.com/lucide-static@latest/icons/circle.svg",
    "shape-poly.svg": "https://unpkg.com/lucide-static@latest/icons/hexagon.svg",
    "shape-line.svg": "https://unpkg.com/lucide-static@latest/icons/minus.svg",
    
    # nav_tools.py (Навигация по холсту)
    "nav-hand.svg": "https://unpkg.com/lucide-static@latest/icons/hand.svg",
    "nav-rotate.svg": "https://unpkg.com/lucide-static@latest/icons/refresh-cw.svg",
    "nav-zoom.svg": "https://unpkg.com/lucide-static@latest/icons/search.svg",
    
    # warp_tool.py, perspective_warp_tool.py, puppet_warp_tool.py (Деформации)
    "warp.svg": "https://unpkg.com/lucide-static@latest/icons/grip.svg",
    "warp-perspective.svg": "https://unpkg.com/lucide-static@latest/icons/boxes.svg",
    "warp-puppet.svg": "https://unpkg.com/lucide-static@latest/icons/git-commit.svg",
    
    # other_tools.py
    "other.svg": "https://unpkg.com/lucide-static@latest/icons/ellipsis.svg"
}

print(f"Запуск скачивания профессиональной базы иконок ({len(ICONS)} шт.) для Photoshop-аналога...")
for filename, url in ICONS.items():
    target_path = os.path.join(ICON_DIR, filename)
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"✓ Скачано успешно: {filename}")
    except Exception as e:
        print(f"✗ Ошибка при скачивании {filename}: {e}")

print(f"\nВсе готово! {len(ICONS)} иконок находятся в папке: assets/icons/")