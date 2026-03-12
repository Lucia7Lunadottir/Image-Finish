# LinuxShop 🎨

A modular PyQt6 image editor for Linux, inspired by Photoshop.

## Quick Start

```bash
pip install PyQt6
python main.py
```

## Architecture

```
linuxshop/
├── main.py                   ← Entry point
│
├── core/                     ← Pure data / logic (no UI)
│   ├── document.py           ← Document model (layers, size, selection)
│   ├── layer.py              ← Single layer (QImage + metadata)
│   └── history.py            ← Undo / redo stack
│
├── tools/                    ← Drawing & editing tools
│   ├── base_tool.py          ← Abstract BaseTool
│   ├── brush_tool.py         ← Paintbrush
│   ├── eraser_tool.py        ← Eraser
│   ├── fill_tool.py          ← Flood-fill bucket
│   └── other_tools.py        ← Select, Move, Eyedropper, Crop, Text, Shapes
│
├── ui/                       ← All Qt widgets
│   ├── main_window.py        ← MainWindow — assembles everything, wires signals
│   ├── canvas_widget.py      ← Drawing surface (zoom, pan, tool dispatch)
│   ├── toolbar.py            ← Left vertical tool selector
│   ├── tool_options_bar.py   ← Context-sensitive options (size, opacity, …)
│   ├── layers_panel.py       ← Layer list + controls
│   ├── color_panel.py        ← FG/BG swatches, colour picker, quick palette
│   └── styles.py             ← Dark-theme QSS stylesheet
│
└── utils/
    └── new_document_dialog.py  ← New / resize canvas dialog
```

## Key Features

| Feature | Detail |
|---|---|
| **Layers** | Add, delete, duplicate, reorder, hide, set opacity |
| **Tools** | Brush, Eraser, Fill (flood), Select, Move, Eyedropper, Crop, Text, Shapes |
| **History** | 40-step undo / redo (`Ctrl+Z` / `Ctrl+Shift+Z`) |
| **Zoom/Pan** | `Ctrl+scroll`, `+`/`-` keys, middle-mouse pan, Space+drag |
| **File I/O** | Open PNG/JPG/BMP, Save / Save As, Export flat PNG |
| **Edit** | Fill FG/BG, Flip H/V, Resize Canvas, Crop |

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `B` | Brush |
| `E` | Eraser |
| `G` | Fill |
| `M` | Marquee Select |
| `V` | Move |
| `I` | Eyedropper |
| `C` | Crop |
| `T` | Text |
| `U` | Shapes |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+N` | New document |
| `Ctrl+O` | Open |
| `Ctrl+S` | Save |
| `Ctrl+J` | Duplicate layer |
| `Delete` | Clear active layer |
| `Ctrl+D` | Deselect |
| `Return` | Apply crop |
| `+` / `-` | Zoom in / out |
| `0` | Fit to window |

## How to Extend

### Add a new tool
1. Create `tools/my_tool.py` extending `BaseTool`
2. Implement `on_press`, `on_move`, `on_release`
3. Add to `_build_tool_registry()` in `ui/main_window.py`
4. Add a button entry in `ui/toolbar.py`
5. Optionally add an options page in `ui/tool_options_bar.py`

### Add a new filter / effect
Add a menu action in `MainWindow._build_menu_bar()` and implement it
using `QPainter` or numpy operations on `layer.image`.
# ImageFinish
