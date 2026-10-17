"""Shared base of the filter-gallery dialogs (Filter > Noise, Stylize,
Sharpen, Pixelate, Other, Distort, Render, Blur Gallery and the specific
filters Camera Raw / Lens Correction / Liquify).

Each of those nine dialogs used to be its own copy of the same ~80-line
frame (canvas + right-hand panel + debounce timer + accept()), with one
`if self.mode == ...` branch per filter both for building the panel (create
every slider any mode might need, hide them all, re-show and re-range the
ones this mode uses) and for rendering — which read the sliders directly,
also during the final full-resolution pass on a worker thread.

Now a filter is a `FilterMode` subclass: its parameters are declared once
(`Slider`, `Choice`, ... — they build and read their own control) and
`apply(src, p, ctx)` is a pure function of the source pixels, the parameter
dict and a `FilterContext` captured on the GUI thread (colours, centre
point, the document's work path). `FilterGalleryDialog` is the one frame;
a gallery is a thin subclass naming its modes.

Parameters marked `spatial` are pixel distances: while the dialog works on
a downscaled live-preview proxy of a large image they are scaled down with
it, so the preview looks like the result (a 10 px blur on an 8K image used
to preview as a 50 px blur).
"""
from dataclasses import dataclass, field, replace

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QColor, QImage, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox,
                             QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from core.locale import tr
from ui import theme
from ui.base_dialog import BaseDialog
from ui.adjustments_dialog import _JumpSlider
from ui.preview_canvas_base import (DragCenterMixin, PreviewCanvasBase,
                                    init_live_preview_arrays, run_full_res_commit)


# ── parameter declarations ──────────────────────────────────────────────────
# Each knows how to build its control, read it and write it. `label` is a
# locale key (None = no caption row).

@dataclass(frozen=True)
class Slider:
    key: str
    label: str
    lo: int
    hi: int
    default: int
    spatial: bool = False

    def build(self, on_change):
        w = _JumpSlider(Qt.Orientation.Horizontal)
        w.setRange(self.lo, self.hi)
        w.setValue(self.default)
        w.valueChanged.connect(on_change)
        return w

    def read(self, w):
        return w.value()

    def write(self, w, v):
        w.setValue(v)


@dataclass(frozen=True)
class Spin(Slider):
    def build(self, on_change):
        w = QSpinBox()
        w.setRange(self.lo, self.hi)
        w.setValue(self.default)
        w.valueChanged.connect(on_change)
        return w


@dataclass(frozen=True)
class Choice:
    key: str
    label: str | None
    items: tuple          # ((label_key, data), ...); the first is the default
    spatial: bool = False

    def build(self, on_change):
        w = QComboBox()
        for label_key, data in self.items:
            w.addItem(tr(label_key), data)
        w.currentIndexChanged.connect(on_change)
        return w

    def read(self, w):
        return w.currentData()

    def write(self, w, v):
        i = w.findData(v)
        if i >= 0:
            w.setCurrentIndex(i)


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    default: bool = False
    spatial: bool = False

    def build(self, on_change):
        w = QCheckBox(tr(self.label))
        w.setChecked(self.default)
        w.toggled.connect(on_change)
        return w

    def read(self, w):
        return w.isChecked()

    def write(self, w, v):
        w.setChecked(bool(v))


@dataclass(frozen=True)
class Color:
    key: str
    label: str
    default: tuple = (255, 255, 255)
    spatial: bool = False

    def build(self, on_change):
        from core.adjustments._widgets import _ColorButton
        w = _ColorButton(QColor(*self.default))
        w.colorChanged.connect(on_change)
        return w

    def read(self, w):
        return QColor(w.color())

    def write(self, w, v):
        w.set_color(QColor(v))


@dataclass(frozen=True)
class Kernel3:
    """3x3 convolution matrix (Filter > Other > Custom); value: 9 ints, row-major."""
    key: str
    label: str | None = None
    spatial: bool = False

    def build(self, on_change):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        w.spins = []
        for i in range(3):
            for j in range(3):
                sp = QSpinBox()
                sp.setRange(-999, 999)
                sp.setValue(1 if i == 1 and j == 1 else 0)
                sp.valueChanged.connect(on_change)
                grid.addWidget(sp, i, j)
                w.spins.append(sp)
        return w

    def read(self, w):
        return tuple(sp.value() for sp in w.spins)

    def write(self, w, v):
        for sp, x in zip(w.spins, v):
            sp.setValue(x)


@dataclass(frozen=True)
class ImageFile:
    """A button that loads an image (Displace map); value: BGRA array or None."""
    key: str
    label: str
    spatial: bool = False

    def build(self, on_change):
        w = QPushButton(tr(self.label))
        w.array = None

        def load():
            from PyQt6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(w, tr(self.label), "", "Images (*.png *.jpg *.jpeg *.bmp)")
            if path:
                from core.pixel_buffer import qimage_argb_view
                img = QImage(path).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                w.array = qimage_argb_view(img, writable=False).copy()
                on_change()
        w.clicked.connect(load)
        return w

    def read(self, w):
        return w.array

    def write(self, w, v):
        w.array = v


# ── what a filter sees besides its parameters ───────────────────────────────

@dataclass(frozen=True)
class FilterContext:
    """Captured on the GUI thread; `apply` may run on a worker thread."""
    fg: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    bg: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    work_path: dict = field(default_factory=dict)
    cx: float = 0.0
    cy: float = 0.0
    orig_img: QImage | None = None    # the source as a QImage (QPainter-based filters)
    scale: float = 1.0                # source size / real layer size (live-preview proxy)
    seed: int = 0                     # per dialog: random filters repeat between preview and result

    def rng(self):
        return np.random.RandomState(self.seed)

    @classmethod
    def from_window(cls, win):
        canvas = getattr(win, "_canvas", None) if win is not None else None
        doc = getattr(win, "_document", None) if win is not None else None
        return cls(fg=QColor(getattr(canvas, "fg_color", QColor(0, 0, 0))),
                   bg=QColor(getattr(canvas, "bg_color", QColor(255, 255, 255))),
                   work_path=dict(getattr(doc, "work_path", None) or {}),
                   seed=int(np.random.randint(0, 2 ** 31 - 1)))

    def bgr(self, color: QColor, dtype=np.uint8):
        return np.array([color.blue(), color.green(), color.red()], dtype=dtype)


def scale_spatial(v, scale: float):
    """A pixel distance on the live-preview proxy: scaled, never to 0
    unless it was 0."""
    if scale >= 1.0 or not v:
        return v
    s = int(round(v * scale))
    return s if s else (1 if v > 0 else -1)


class FilterMode:
    """One filter. Subclasses set `key`, `title_key` and `params`, and
    implement `apply(src, p, ctx)` -> a new (H, W, 4) uint8 BGRA
    (premultiplied) array, or a QImage."""
    key = ""
    title_key = ""
    params: tuple = ()
    center = False            # has a draggable centre handle (ctx.cx/cy)
    allow_proxy = True        # may run on a downscaled live-preview proxy
    canvas_cls = None         # a PreviewCanvasBase subclass, for interactive filters

    def apply(self, src: np.ndarray, p: dict, ctx: FilterContext):
        raise NotImplementedError

    # Optional hooks for interactive filters.
    def on_open(self, dialog):
        pass

    def paint_overlay(self, painter, dialog, w, h):
        pass


def paint_center_rings(p, dialog, zoom):
    """The centre handle: a dot and a ring (Distort, Blur Gallery)."""
    cx, cy = dialog.cx, dialog.cy
    p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 1.5 / zoom)))
    p.setBrush(QColor(0, 0, 0, 100))
    cr = max(4.0, 6.0 / zoom)
    p.drawEllipse(QPointF(cx, cy), cr, cr)
    p.drawEllipse(QPointF(cx, cy), cr * 3, cr * 3)


class GalleryCanvas(DragCenterMixin, PreviewCanvasBase):
    """Preview canvas: drag the centre if the filter has one; the filter
    paints its own overlay."""

    def _center_active(self):
        return self.dialog.filter.center

    def _paint_overlay_in_image_space(self, p, w, h):
        self.dialog.filter.paint_overlay(p, self.dialog, w, h)

    def keyReleaseEvent(self, ev):
        super().keyReleaseEvent(ev)
        self.update()


# ── the dialog ──────────────────────────────────────────────────────────────

class FilterGalleryDialog(BaseDialog):
    """A gallery subclass sets MODES (mode key -> FilterMode subclass) and
    GALLERY_TITLE_KEY (None: the window title is the filter's own name)."""
    MODES: dict = {}
    GALLERY_TITLE_KEY: str | None = None
    CENTER_HIT_RADIUS = 20
    _DEBOUNCE_MS = 60

    def __init__(self, layer, mode, canvas_refresh, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.mode = mode
        self.filter = self.MODES[mode]()
        self.canvas_refresh = canvas_refresh

        title = tr(self.filter.title_key).replace('…', '')
        if self.GALLERY_TITLE_KEY:
            title = f"{tr(self.GALLERY_TITLE_KEY)} - {title}"
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1000, 700)

        self._full_width = max(1, layer.image.width())
        if self.filter.allow_proxy:
            init_live_preview_arrays(self, layer)
        else:
            # Interactive per-pixel state (Liquify's displacement map) is
            # tied 1:1 to the working resolution — no proxy.
            from core.pixel_buffer import qimage_argb_view
            self.orig_img = layer.image.copy()
            self.preview_img = layer.image.copy()
            self.orig_img_full = None
            self.orig_arr = qimage_argb_view(self.orig_img, writable=False)[:, :self.orig_img.width(), :].copy()
        self.cx = self.orig_img.width() / 2.0
        self.cy = self.orig_img.height() / 2.0
        self._ctx = FilterContext.from_window(parent)
        self._frozen = None
        self._controls: dict = {}

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._apply_effect)

        self._build_ui()
        self.filter.on_open(self)
        self._apply_effect()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        canvas_cls = self.filter.canvas_cls or GalleryCanvas
        self.canvas = canvas_cls(self)
        self.canvas._center_hit_radius = self.CENTER_HIT_RADIUS
        w, h = self.orig_img.width(), self.orig_img.height()
        self.canvas.zoom = min(700 / max(1, w), 600 / max(1, h))
        self.canvas._pan = QPointF(50, 50)
        root.addWidget(self.canvas, 1)

        props = QWidget()
        props.setFixedWidth(280)
        theme.apply_style(props, lambda: f"background: {theme.BASE}; border-left: 1px solid {theme.SURFACE0};")
        pl = QVBoxLayout(props)
        pl.setContentsMargins(15, 15, 15, 15)
        pl.setSpacing(15)

        for spec in self.filter.params:
            if spec.label and not isinstance(spec, Check):
                pl.addWidget(QLabel(tr(spec.label)))
            w = spec.build(self._on_change)
            self._controls[spec.key] = w
            pl.addWidget(w)
        if not self.filter.params:
            lbl = QLabel(tr("filter.no_params"))
            lbl.setWordWrap(True)
            theme.apply_style(lbl, lambda: f"color: {theme.SUBTEXT}; font-size: 12px; font-style: italic;")
            pl.addWidget(lbl)

        pl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        pl.addWidget(btns)
        root.addWidget(props)

    def _on_change(self, *_):
        self._timer.start()
        self.canvas.update()      # overlays follow their sliders immediately

    # Older name, still called by DragCenterMixin.
    _trigger_update = _on_change

    # ── parameters ────────────────────────────────────────────────────────
    def _params(self) -> dict:
        """Current control values (GUI thread)."""
        return {spec.key: spec.read(self._controls[spec.key]) for spec in self.filter.params}

    def _context(self) -> FilterContext:
        return replace(self._ctx, cx=self.cx, cy=self.cy, orig_img=self.orig_img,
                       scale=self.orig_img.width() / self._full_width)

    def _render_params(self, p: dict, scale: float) -> dict:
        if scale >= 1.0:
            return p
        return {spec.key: (scale_spatial(p[spec.key], scale) if spec.spatial else p[spec.key])
                for spec in self.filter.params}

    # ── rendering ─────────────────────────────────────────────────────────
    def _apply_effect(self):
        frozen = self._frozen
        p, ctx = frozen if frozen is not None else (self._params(), self._context())
        out = self.filter.apply(self.orig_arr, self._render_params(p, ctx.scale), ctx)
        if isinstance(out, QImage):
            self.preview_img = out
        else:
            h, w = out.shape[:2]
            out = np.ascontiguousarray(out)
            self.preview_img = QImage(out.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self.canvas.update()

    def accept(self):
        self._timer.stop()
        params = self._params()
        # run_full_res_commit swaps in the full-resolution source (and
        # rescales cx/cy) before its worker re-runs _apply_effect; the
        # context is taken after that swap, on this thread.
        def freeze():
            self._frozen = (params, self._context())
        if self.orig_img_full is None:
            freeze()
            self._apply_effect()
            self.layer.image = self.preview_img
            super().accept()
            return
        run_full_res_commit(self, self._apply_effect, scale_attrs=("cx", "cy"), pre_apply=freeze)
