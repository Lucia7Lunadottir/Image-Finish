import math

from core.app_logging import get_logger
from core.locale import tr
from ui import theme

logger = get_logger("canvas")

from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QBrush, QPen, QImage, QCursor, QInputDevice,
                         QRadialGradient, QPainterPath, QBitmap, QRegion, QTransform)

from tools.other_tools import (SelectTool, CropTool, ShapesTool,
                               HandTool, ZoomTool, RotateViewTool, GradientTool, PerspectiveCropTool)
from ui.overlay_renderers import (
    draw_grid, draw_guides, draw_slices, draw_symmetry_axes, draw_selection,
    draw_subtract_drag, draw_lasso_preview, draw_transform_preview,
    draw_brush_stroke, draw_crop_preview, draw_perspective_crop,
    draw_shapes_preview, draw_gradient_preview, draw_artboard_preview,
    draw_clone_stamp, draw_measurements,
)


# Plain color-painting tools where Alt has no other meaning yet — eligible
# for Photoshop-style "hold Alt = temporary eyedropper". CloneStamp/Patch/
# HealingBrush already use Alt to set their source point, and Select/Lasso/
# Move/PuppetWarp already use Alt for their own modifiers, so those are
# deliberately excluded.
_ALT_EYEDROPPER_TOOLS = {"Brush", "Pencil", "ColorReplacement", "MixerBrush", "PatternStamp"}



_sel_cursor_cache: dict = {}

def _make_sel_cursor(mode: str) -> QCursor:
    """Create a crosshair cursor with selection mode indicator: '' / '+' / '-' / 'x'."""
    if mode in _sel_cursor_cache:
        return _sel_cursor_cache[mode]

    SIZE = 24
    HOT  = SIZE // 2
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    mid = HOT
    gap = 4

    def _line(pen, x1, y1, x2, y2):
        p.setPen(pen)
        p.drawLine(x1, y1, x2, y2)

    white = QPen(Qt.GlobalColor.white, 2)
    black = QPen(Qt.GlobalColor.black, 1)

    for arm in [(mid, 0, mid, mid - gap),
                (mid, mid + gap, mid, SIZE - 1),
                (0, mid, mid - gap, mid),
                (mid + gap, mid, SIZE - 1, mid)]:
        _line(black, *arm)
        _line(white, *arm)

    bx, by = 15, 15
    bw = 7

    if mode == "add":
        cx, cy = bx + bw // 2, by + bw // 2
        for coords in [(cx, by, cx, by + bw), (bx, cy, bx + bw, cy)]:
            _line(black, *coords)
            _line(white, *coords)
    elif mode == "sub":
        cy = by + bw // 2
        _line(black, bx, cy, bx + bw, cy)
        _line(white, bx, cy, bx + bw, cy)
    elif mode == "intersect":
        for coords in [(bx, by, bx + bw, by + bw), (bx + bw, by, bx, by + bw)]:
            _line(black, *coords)
            _line(white, *coords)

    p.end()
    cur = QCursor(px, HOT, HOT)
    _sel_cursor_cache[mode] = cur
    return cur


class CanvasWidget(QOpenGLWidget):
    document_changed = pyqtSignal()
    pixels_changed   = pyqtSignal()
    color_picked     = pyqtSignal(QColor)
    tool_state_changed = pyqtSignal(object)
    cursor_info      = pyqtSignal(int, int, QColor)  # doc x, doc y, pixel color
    view_changed     = pyqtSignal()  # zoom/pan changed (status bar, navigator)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.document     = None
        self._active_tool = None
        self._alt_prev_tool = None  # tool stashed while the temporary Alt-eyedropper is active
        self._alt_picker = None     # the temporary EyedropperTool instance itself
        # Brush is always the first tool applied to a freshly opened document
        # (see MainWindow.__init__), so give this widget its blank-cursor +
        # circle-guide look right at construction time instead of waiting for
        # a later _update_cursor() call: setting it upfront, well before the
        # widget is ever shown, sidesteps whatever timing/staleness causes a
        # previously-shown widget's cursor (e.g. the Welcome screen's
        # PointingHandCursor thumbnails) to visually stick after this canvas
        # replaces it on screen.
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.view_channel = "RGB"

        self.fg_color = QColor(0, 0, 0)
        self.bg_color = QColor(255, 255, 255)
        self.tool_opts: dict = {
            "brush_size":     10,
            "brush_opacity":  1.0,
            "brush_hardness": 1.0,
            "brush_angle":    0.0,
            "brush_angle_random": False,
            "brush_mask":     "round",
            "brush_blend_mode": "SourceOver",
            "brush_pattern_scale": 100,
            "brush_mirror_x": False,
            "brush_mirror_y": False,
            "fill_tolerance": 32,
            "fill_contiguous": True,
            "font_size":        24,
            "font_family":      "Sans Serif",
            "font_bold":        False,
            "font_italic":      False,
            "font_underline":   False,
            "font_strikeout":   False,
            "text_color":       QColor(0, 0, 0),
            "text_stroke_w":    0,
            "text_stroke_color": QColor(0, 0, 0),
            "text_shadow":      False,
            "text_shadow_color": QColor(0, 0, 0, 160),
            "text_shadow_dx":   3,
            "text_shadow_dy":   3,
            "shape_type":     "rect",
            "shape_fill":     False,
            "shape_sides":    6,
            "shape_angle":    0,
            "shape_stroke":   True,
            "shape_stroke_width": 2,
            "shape_path_op":  "new",
            "effect_strength": 0.5,
            "crop_overlay":   "thirds",
        }

        self.zoom: float   = 1.0
        self._pan: QPointF = QPointF(0, 0)
        self._pan_last: QPointF | None = None
        self._panning: bool = False
        self._space:   bool = False

        self._view_rotation: float = 0.0
        self._rotating:      bool  = False
        self._rotate_last_angle: float = 0.0

        self._stroke_in_progress: bool = False
        self._pre_stroke_state = None

        self._mouse_pos: QPointF = QPointF(-100, -100)
        self._show_brush_cursor: bool = True
        self._is_mouse_in: bool = False

        self._composite_cache: QImage | None = None
        self._cache_dirty: bool = True
        self._display_cache: QImage | None = None
        self._last_view_channel: str = "RGB"
        self._last_composite_dirty_rect: QRect | None = None

        # Built lazily in initializeGL() once a GL context exists; .ready
        # stays False (silent CPU fallback) if shader setup fails on this
        # driver — see ui/gl_compositor.py.
        self._gl = None

        self._effect_bg_cache: QImage | None = None
        self._in_effect_stroke: bool = False

        # Screen-resolution render of the visible part of the document
        # (Document.render_view), shown instead of the magnified document-
        # resolution composite when zoomed in on a document with vector
        # layers — that's what keeps shapes sharp at any zoom. Keyed by
        # composite cacheKey + view, rebuilt after zoom/pan settles.
        self._hires_image: QImage | None = None
        self._hires_origin = QPointF()
        self._hires_key = None
        self._hires_render_ms = 0.0
        self._hires_failed = False
        self._hires_timer = QTimer(self)
        self._hires_timer.setSingleShot(True)
        self._hires_timer.timeout.connect(self._render_hires)

        self.show_rulers: bool = False
        self._dragging_guide = None

        self._march_offset: int = 0
        self._march_timer: QTimer | None = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._checker = self._build_checker()

        from ui.text_edit_session import TextEditSession
        self._text_session = TextEditSession(self)

        from ui.shape_scene_overlay import ShapeSceneOverlay
        self._shape_overlay = ShapeSceneOverlay(self)
        self.document_changed.connect(self._shape_overlay.refresh_items)

    @property
    def active_tool(self):
        return self._active_tool

    @active_tool.setter
    def active_tool(self, tool):
        self._active_tool = tool
        overlay = getattr(self, "_shape_overlay", None)
        if overlay is not None:
            overlay.set_interactive(getattr(tool, "name", None) == "Shapes")

    @staticmethod
    def _build_checker(tile: int = 16) -> QPixmap:
        pix = QPixmap(tile * 2, tile * 2)
        p = QPainter(pix)
        p.fillRect(0,    0,    tile, tile, QColor(180, 180, 180))
        p.fillRect(tile, 0,    tile, tile, QColor(220, 220, 220))
        p.fillRect(0,    tile, tile, tile, QColor(220, 220, 220))
        p.fillRect(tile, tile, tile, tile, QColor(180, 180, 180))
        p.end()
        return pix

    def set_document(self, doc):
        self.document = doc
        self._cache_dirty = True
        self._display_cache = None
        self._pre_stroke_state = None
        self._check_marching_ants()
        self._fit_to_window()
        self._hires_image = None
        self._hires_key = None
        self._shape_overlay.refresh_items()
        self.update()

    def invalidate_cache(self):
        self._cache_dirty = True
        self._display_cache = None
        self._check_marching_ants()
        self.update()

    def _recompute_composite(self):
        """Recompute the document composite, incrementally when the active
        tool can report the document-space rect it actually touched."""
        dirty = self.active_tool.get_dirty_rect() if self.active_tool else None
        # A tool's dirty rect (e.g. BrushTool's) deliberately survives past
        # its own on_release, for the eager recompute right after a stroke
        # commits. But if something ELSE invalidated the document cache
        # meanwhile without going through this tool at all — undo/redo,
        # switching layers, any _canvas_refresh() — get_composite() below
        # is about to do a full recompute regardless of `dirty`. Trusting
        # the tool's stale rect here would tell GLCompositor "only this
        # small rect changed" while actually everything did, leaving
        # un-erased leftovers on screen until something forces a full
        # re-upload. Once the doc-level cache is already gone, treat this
        # as a full recompute for GL purposes too.
        if dirty is not None and getattr(self.document, "_composite_cache_doc", None) is None:
            dirty = None
        # Exposed for GLCompositor: QImage.cacheKey() changes on *any* paint,
        # including an in-place dirty-rect patch (verified — even a 10x10
        # fillRect on an unrelated QImage changes it), so the GL texture
        # can't tell "unchanged" from "one small brush dab" from the cache
        # key alone. Remembering the same rect here lets it re-upload just
        # that sub-rectangle instead of the whole image — the difference
        # between a few KB and a full 8K frame (256MB+) per stroke sample.
        self._last_composite_dirty_rect = dirty
        if dirty is not None:
            self._composite_cache = self.document.get_composite(dirty_rect=dirty)
        else:
            self.document.invalidate_composite()
            self._composite_cache = self.document.get_composite()

    def _check_marching_ants(self):
        has_sel = (self.document and self.document.selection
                   and not self.document.selection.isEmpty()
                   and getattr(self.document, "quick_mask_layer", None) is None)
        if has_sel and self._march_timer is None:
            self._march_timer = QTimer(self)
            self._march_timer.timeout.connect(self._advance_march)
            self._march_timer.start(100)
        elif not has_sel and self._march_timer is not None:
            self._march_timer.stop()
            self._march_timer.deleteLater()
            self._march_timer = None

    def _advance_march(self):
        self._march_offset = (self._march_offset + 1) % 16
        self.update()

    def _start_effect_stroke(self):
        """Safely cache the background beneath the active layer for effects."""
        try:
            doc = self.document
            active = doc.get_active_layer() if doc else None

            if (active is None or
                    getattr(active, "blend_mode", "Normal") not in ("Normal", "SourceOver", "") or
                    getattr(active, "clipping", False)):
                self._effect_bg_cache = None
                self._in_effect_stroke = False
                return

            was_visible = active.visible
            active.visible = False
            self._effect_bg_cache = doc.get_composite()
            active.visible = was_visible

            self._in_effect_stroke = True
            if hasattr(self.active_tool, "_stroke_preview_active"):
                self.active_tool._stroke_preview_active = True
        except Exception as e:
            logger.exception("Effect cache safety catch")
            self._effect_bg_cache = None
            self._in_effect_stroke = False

    def reset_zoom(self):
        self._fit_to_window()
        self.update()

    def reset_rotation(self):
        self._view_rotation = 0.0
        self.update()

    def zoom_in(self):
        self._apply_zoom(1.25, self.rect().center())

    def zoom_out(self):
        self._apply_zoom(1 / 1.25, self.rect().center())

    def to_doc(self, widget_pos: QPointF) -> QPoint:
        if self._view_rotation:
            cx = self.width()  / 2
            cy = self.height() / 2
            dx = widget_pos.x() - cx
            dy = widget_pos.y() - cy
            a  = math.radians(-self._view_rotation)
            widget_pos = QPointF(
                dx * math.cos(a) - dy * math.sin(a) + cx,
                dx * math.sin(a) + dy * math.cos(a) + cy,
            )
        x = (widget_pos.x() - self._pan.x()) / self.zoom
        y = (widget_pos.y() - self._pan.y()) / self.zoom
        return QPoint(int(x), int(y))

    def to_widget(self, doc_pos: QPoint) -> QPointF:
        x = doc_pos.x() * self.zoom + self._pan.x()
        y = doc_pos.y() * self.zoom + self._pan.y()
        if self._view_rotation:
            cx = self.width() / 2
            cy = self.height() / 2
            dx = x - cx
            dy = y - cy
            a = math.radians(self._view_rotation)
            x = dx * math.cos(a) - dy * math.sin(a) + cx
            y = dx * math.sin(a) + dy * math.cos(a) + cy
        return QPointF(x, y)

    def text_session(self):
        """The on-canvas text editor (ui/text_edit_session.py)."""
        return self._text_session

    def _doc_rect_in_widget(self) -> QRect:
        if not self.document:
            return QRect()
        return QRect(
            int(self._pan.x()), int(self._pan.y()),
            int(self.document.width  * self.zoom),
            int(self.document.height * self.zoom),
        )

    def _fit_to_window(self):
        if not self.document or self.width() == 0 or self.height() == 0:
            return
        margin = 40
        sx = (self.width()  - margin * 2) / self.document.width
        sy = (self.height() - margin * 2) / self.document.height
        self.zoom = min(sx, sy, 1.0)
        self._pan = QPointF(
            (self.width()  - self.document.width  * self.zoom) / 2,
            (self.height() - self.document.height * self.zoom) / 2,
        )

    def _apply_zoom(self, factor: float, pivot):
        if isinstance(pivot, QPoint):
            pivot = QPointF(pivot)
        new_zoom = max(0.02, min(32.0, self.zoom * factor))
        scale = new_zoom / self.zoom
        self._pan = QPointF(
            pivot.x() - (pivot.x() - self._pan.x()) * scale,
            pivot.y() - (pivot.y() - self._pan.y()) * scale,
        )
        self.zoom = new_zoom
        self.update()
        self.view_changed.emit()

    def _draw_rulers(self, painter: QPainter):
        R = 20
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, R, QColor(theme.MANTLE))
        painter.fillRect(0, 0, R, h, QColor(theme.MANTLE))
        painter.fillRect(0, 0, R, R, QColor(theme.CRUST))

        painter.setPen(QColor(theme.SUBTEXT))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        start_x = - (self._pan.x() / self.zoom)
        end_x = start_x + w / self.zoom
        step = 100
        if self.zoom > 2: step = 10
        elif self.zoom > 0.5: step = 50
        elif self.zoom < 0.2: step = 500
        
        first_x = int(start_x // step) * step
        for x in range(first_x, int(end_x) + step, step):
            wx = int(x * self.zoom + self._pan.x())
            if wx > R:
                painter.drawLine(wx, R - 6, wx, R)
                painter.drawText(wx + 2, R - 2, str(x))
                
        start_y = - (self._pan.y() / self.zoom)
        end_y = start_y + h / self.zoom
        first_y = int(start_y // step) * step
        for y in range(first_y, int(end_y) + step, step):
            wy = int(y * self.zoom + self._pan.y())
            if wy > R:
                painter.drawLine(R - 6, wy, R, wy)
                painter.save()
                painter.translate(R - 2, wy + 2)
                painter.rotate(-90)
                painter.drawText(0, 0, str(y))
                painter.restore()

    def initializeGL(self):
        """Called by QOpenGLWidget once a GL context exists (and again if
        the context is ever recreated). Building GLCompositor here, rather
        than in __init__, is required — there is no current GL context yet
        at construction time."""
        from ui.gl_compositor import GLCompositor
        self._gl = GLCompositor()

    def paintGL(self):
        """Render the scene, guarded against internal script failures.

        Named paintGL(), not paintEvent(): QOpenGLWidget's own paintEvent()
        is what sets up the widget's backing FBO before calling this, and
        that setup is what beginNativePainting()/endNativePainting() below
        rely on — a hand-rolled paintEvent() override was tried and produced
        a blank frame instead (see ui/gl_compositor.py docstring)."""
        if self.document is not None:
            self._shape_overlay.sync_transform()
        try:
            painter = QPainter(self)
            if self.zoom > 0.9:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            else:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            painter.fillRect(self.rect(), QColor(theme.CRUST))

            if not self.document:
                painter.end()
                return

            if self._view_rotation:
                buf = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
                buf.fill(QColor(0, 0, 0, 0))
                bp = QPainter(buf)
                bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                # Offscreen QImage target: no GL context to draw into, so
                # this path always uses the CPU drawImage() fallback.
                self._paint_canvas_content(bp, gpu=False)
                bp.end()
                cx = self.width()  / 2
                cy = self.height() / 2
                painter.translate(cx, cy)
                painter.rotate(self._view_rotation)
                painter.translate(-cx, -cy)
                painter.drawImage(0, 0, buf)
                painter.resetTransform()
            else:
                self._paint_canvas_content(painter)
                
            # Draw artboard names
            painter.save()
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for layer in self.document.artboards():
                ar = layer.artboard_rect
                painter.setPen(QPen(QColor(120, 120, 120), max(1.0, 1.0/self.zoom)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(ar)
                painter.setPen(QColor(200, 200, 200))
                font = painter.font()
                font.setPointSizeF(max(10.0, 12.0/self.zoom))
                painter.setFont(font)
                painter.drawText(ar.left(), ar.top() - max(4, int(4/self.zoom)), layer.name)
            painter.restore()
                
            # Guarded rendering of custom tool overlays
            if self.active_tool and hasattr(self.active_tool, "draw_overlays"):
                try:
                    painter.save()
                    painter.translate(self._pan)
                    painter.scale(self.zoom, self.zoom)
                    
                    old_hovers = {}
                    if not getattr(self, "_is_mouse_in", True):
                        for attr in ["hover_pos", "_hover_pos", "current_pos", "_current_pos", "preview_end", "_preview_end"]:
                            if hasattr(self.active_tool, attr):
                                old_hovers[attr] = getattr(self.active_tool, attr)
                                setattr(self.active_tool, attr, None)
                                
                    self.active_tool.draw_overlays(painter, max(1.0, 1.0 / self.zoom), self.document)
                    
                    for attr, val in old_hovers.items():
                        setattr(self.active_tool, attr, val)
                        
                    painter.restore()
                except Exception as e:
                    logger.exception("Tool overlay rendering error in %s", getattr(self.active_tool, "name", "?"))

            if self._show_brush_cursor and not self._panning and not self._space:
                self._draw_brush_cursor(painter)

            if self.show_rulers:
                self._draw_rulers(painter)

            painter.end()
        except Exception as ce:
            logger.exception("Critical canvas paint loop failure")

    def _draw_composite_cpu(self, painter: QPainter, display_img: QImage):
        painter.save()
        painter.translate(self._pan)
        painter.scale(self.zoom, self.zoom)
        painter.drawImage(0, 0, display_img)
        painter.restore()

    # ── sharp vector display ────────────────────────────────────────────
    def _hires_view_key(self):
        return (round(self.zoom, 6), round(self._pan.x(), 3), round(self._pan.y(), 3),
                self.width(), self.height(), self.devicePixelRatioF())

    def _hires_wanted(self, channel: str) -> bool:
        if self._hires_failed or self.document is None or self._composite_cache is None:
            return False
        if channel != "RGB" or self._in_effect_stroke:
            return False
        if self.zoom * self.devicePixelRatioF() <= 1.0001:
            return False   # the document-resolution composite is already as sharp as the screen
        return self.document.has_vector_content()

    def _draw_hires(self, painter: QPainter, channel: str) -> bool:
        """Draws the screen-resolution render if it matches what's on
        screen now; otherwise schedules one and returns False (the caller
        draws the normal composite meanwhile)."""
        if not self._hires_wanted(channel):
            self._hires_image = None
            self._hires_key = None
            return False
        key = (self._composite_cache.cacheKey(), self._hires_view_key())
        if self._hires_image is not None and self._hires_key == key:
            painter.drawImage(self._hires_origin, self._hires_image)
            return True
        same_view = self._hires_key is not None and self._hires_key[1] == key[1]
        # Mid-gesture (brush stroke, drag) the composite changes every
        # frame — never render synchronously then; the debounced timer
        # below fires once the gesture pauses.
        from PyQt6.QtWidgets import QApplication
        interacting = QApplication.mouseButtons() != Qt.MouseButton.NoButton
        if same_view and not interacting and self._hires_render_ms < 60:
            # Only the content changed (a shape edit committed) and a render
            # is cheap: do it now, so the shape doesn't flash blurry first.
            self._render_hires()
            if self._hires_image is not None and self._hires_key == key:
                painter.drawImage(self._hires_origin, self._hires_image)
                return True
            return False
        self._hires_timer.start(90 if (interacting or not same_view) else 0)
        return False

    def _render_hires(self):
        if self.document is None or self._cache_dirty or self._composite_cache is None:
            return
        from PyQt6.QtWidgets import QApplication
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._hires_timer.start(90)   # still mid-gesture: try again shortly
            return
        if not self._hires_wanted(getattr(self, "view_channel", "RGB")):
            return
        import time
        region = self.rect().intersected(self._doc_rect_in_widget().adjusted(-1, -1, 1, 1))
        if region.isEmpty():
            return
        dpr = self.devicePixelRatioF()
        s = self.zoom * dpr
        transform = QTransform(s, 0, 0, s, (self._pan.x() - region.x()) * dpr,
                               (self._pan.y() - region.y()) * dpr)
        size = QSize(max(1, math.ceil(region.width() * dpr)), max(1, math.ceil(region.height() * dpr)))
        t0 = time.perf_counter()
        try:
            img = self.document.render_view(transform, size)
        except Exception:
            logger.exception("Screen-resolution render failed — falling back to the composite")
            self._hires_failed = True
            self._hires_image = None
            return
        self._hires_render_ms = (time.perf_counter() - t0) * 1000
        img.setDevicePixelRatio(dpr)
        self._hires_image = img
        self._hires_origin = QPointF(region.topLeft())
        self._hires_key = (self._composite_cache.cacheKey(), self._hires_view_key())
        self.update()

    def _paint_canvas_content(self, painter: QPainter, gpu: bool = True):
        """Internal layer-by-layer rendering of cached images and vectors.

        `gpu` gates only the final composite blit (the one call that used
        to be a plain painter.drawImage() of the whole document every
        frame): True draws it as a GPU texture via GLCompositor when one is
        available on this widget, False (offscreen-buffer callers, GL init
        failure) always uses the original CPU drawImage() path."""
        dr = self._doc_rect_in_widget()
        from core.layer import ArtboardLayer
        has_artboards = any(isinstance(l, ArtboardLayer) for l in self.document.layers)

        if not has_artboards:
            painter.save()
            painter.setClipRect(dr)
            painter.translate(self._pan)
            painter.scale(self.zoom, self.zoom)
            painter.fillRect(0, 0, self.document.width, self.document.height, QBrush(self._checker))
            painter.restore()

        if self._cache_dirty or self._composite_cache is None:
            if self._in_effect_stroke and self._effect_bg_cache is not None:
                self._composite_cache = self._effect_bg_cache
            else:
                self._recompute_composite()
            self._cache_dirty = False
            self._display_cache = None
            
        current_ch = getattr(self, "view_channel", "RGB")
        if self._display_cache is None or getattr(self, "_last_view_channel", "RGB") != current_ch:
            self._last_view_channel = current_ch
            if current_ch == "RGB" or self._composite_cache is None:
                self._display_cache = self._composite_cache
            else:
                import numpy as np
                from core.pixel_buffer import qimage_argb_view
                comp = self._composite_cache
                w, h = comp.width(), comp.height()
                arr = qimage_argb_view(comp, writable=False)[:, :w]
                
                B = arr[..., 0].astype(np.float32)
                G = arr[..., 1].astype(np.float32)
                R = arr[..., 2].astype(np.float32)
                
                if current_ch.startswith("alpha_"):
                    idx = int(current_ch.split("_")[1])
                    if hasattr(self.document, "alpha_channels") and 0 <= idx < len(self.document.alpha_channels):
                        alpha_path = self.document.alpha_channels[idx]["path"]
                        from core.pixel_buffer import path_mask
                        gray_u8 = path_mask(alpha_path, w, h)
                    else:
                        gray_u8 = np.zeros((h, w), dtype=np.uint8)
                else:
                    if current_ch == "R": gray = R
                    elif current_ch == "G": gray = G
                    elif current_ch == "B": gray = B
                    else:
                        C_c = 1.0 - R / 255.0
                        M_c = 1.0 - G / 255.0
                        Y_c = 1.0 - B / 255.0
                        K_c = np.minimum(C_c, np.minimum(M_c, Y_c))
                        
                        if current_ch == "K":
                            gray = K_c * 255.0
                        else:
                            safe_K = np.where(K_c >= 0.999, 1.0, 1.0 - K_c)
                            if current_ch == "C": gray = np.where(K_c >= 0.999, 0.0, (C_c - K_c) / safe_K) * 255.0
                            elif current_ch == "M": gray = np.where(K_c >= 0.999, 0.0, (M_c - K_c) / safe_K) * 255.0
                            elif current_ch == "Y": gray = np.where(K_c >= 0.999, 0.0, (Y_c - K_c) / safe_K) * 255.0
                            
                    gray_u8 = np.clip(gray, 0, 255).astype(np.uint8)
                
                disp_arr = np.empty((h, w, 4), dtype=np.uint8)
                disp_arr[..., 0] = gray_u8
                disp_arr[..., 1] = gray_u8
                disp_arr[..., 2] = gray_u8
                disp_arr[..., 3] = 255 if current_ch.startswith("alpha_") else arr[..., 3]
                
                new_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
                qimage_argb_view(new_img, writable=True)[:, :w, :] = disp_arr
                self._display_cache = new_img

        display_img = self._display_cache

        if self._draw_hires(painter, current_ch):
            pass
        elif gpu and self._gl is not None and self._gl.ready:
            try:
                painter.beginNativePainting()
                try:
                    # Only trust the dirty rect when `display_img` really is
                    # `self._composite_cache` patched in place (plain RGB
                    # view) — the per-channel view above always builds a
                    # brand-new QImage from scratch, so re-uploading just a
                    # sub-rect of *that* would leave the rest of the GPU
                    # texture showing stale content from a previous, wholly
                    # different image.
                    dirty = (self._last_composite_dirty_rect
                            if display_img is self._composite_cache else None)
                    self._gl.draw(display_img, self._pan.x(), self._pan.y(), self.zoom,
                                  self.width(), self.height(), self.devicePixelRatioF(),
                                  dirty_rect=dirty)
                finally:
                    painter.endNativePainting()
            except Exception:
                logger.exception("GPU composite draw failed — disabling for this session")
                self._gl.ready = False
                self._draw_composite_cpu(painter, display_img)
        else:
            self._draw_composite_cpu(painter, display_img)

        # Overlays (each function handles its own save/restore)
        _pan, _zoom = self._pan, self.zoom
        _doc, _tool = self.document, self.active_tool
        _opts = self.tool_opts
        _tname = getattr(_tool, "name", "")

        draw_grid(painter, doc=_doc, pan=_pan, zoom=_zoom)
        draw_guides(painter, doc=_doc, pan=_pan, zoom=_zoom,
                    dragging_guide=getattr(self, "_dragging_guide", None))
        draw_slices(painter, doc=_doc, pan=_pan, zoom=_zoom)

        if not has_artboards:
            painter.setPen(QPen(QColor(80, 80, 100), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(dr.adjusted(0, 0, -1, -1))

        draw_symmetry_axes(painter, doc=_doc, pan=_pan, zoom=_zoom,
                           tool_opts=_opts, brush_tool=getattr(_tool, "BRUSH_CURSOR", False))
        draw_selection(painter, doc=_doc, pan=_pan, zoom=_zoom,
                       march_offset=self._march_offset)
        draw_subtract_drag(painter, active_tool=_tool, pan=_pan, zoom=_zoom,
                           SelectTool=SelectTool)
        draw_lasso_preview(painter, active_tool=_tool, pan=_pan, zoom=_zoom,
                           is_mouse_in=getattr(self, "_is_mouse_in", True))
        draw_transform_preview(painter, active_tool=_tool, pan=_pan, zoom=_zoom)
        draw_brush_stroke(painter, active_tool=_tool, tool_opts=_opts,
                          pan=_pan, zoom=_zoom)
        draw_crop_preview(painter, active_tool=_tool, tool_opts=_opts,
                          pan=_pan, zoom=_zoom, doc=_doc, CropTool=CropTool)
        draw_perspective_crop(painter, active_tool=_tool, tool_opts=_opts,
                              pan=_pan, zoom=_zoom, doc=_doc,
                              PerspectiveCropTool=PerspectiveCropTool)
        draw_shapes_preview(painter, active_tool=_tool, tool_opts=_opts,
                            fg_color=self.fg_color, pan=_pan, zoom=_zoom,
                            ShapesTool=ShapesTool)
        draw_gradient_preview(painter, active_tool=_tool, pan=_pan, zoom=_zoom,
                              GradientTool=GradientTool)
        draw_artboard_preview(painter, active_tool=_tool, pan=_pan, zoom=_zoom)
        draw_clone_stamp(painter, active_tool=_tool, pan=_pan, zoom=_zoom)
        draw_measurements(painter, active_tool=_tool, pan=_pan, zoom=_zoom,
                          composite_cache=self._composite_cache,
                          to_widget_fn=self.to_widget)
        try:
            self._text_session.paint(painter)
        except Exception:
            logger.exception("Text editor overlay paint failed")

    def _update_brush_region(self, pos: QPointF):
        mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
        mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
        if mirror_x or mirror_y:
            self._prev_brush_wp = QPointF(pos)
            self.update()
            return

        brush_sz = int(self.tool_opts.get("brush_size", 10))
        w_size   = max(4, int(brush_sz * self.zoom))
        margin   = w_size // 2 + 6

        prv = getattr(self, "_prev_brush_wp", None) or pos
        self._prev_brush_wp = QPointF(pos)

        x1 = int(min(pos.x(), prv.x())) - margin
        y1 = int(min(pos.y(), prv.y())) - margin
        x2 = int(max(pos.x(), prv.x())) + margin
        y2 = int(max(pos.y(), prv.y())) + margin
        self.update(QRect(x1, y1, x2 - x1, y2 - y1))


    def _draw_brush_cursor(self, painter: QPainter):
        try:
            size   = int(self.tool_opts.get("brush_size", 10))
            mask   = self.tool_opts.get("brush_mask", "round")
            hard   = float(self.tool_opts.get("brush_hardness", 1.0))
            angle  = float(self.tool_opts.get("brush_angle", 0.0))

            if getattr(self.active_tool, "name", "") == "BackgroundEraser":
                mask = "round"
                hard = 1.0
                angle = 0.0
                
            mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
            mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
            cx_pct = float(self.tool_opts.get("brush_mirror_cx", 0.5))
            cy_pct = float(self.tool_opts.get("brush_mirror_cy", 0.5))
            doc_pos = self.to_doc(self._mouse_pos)
            w, h = self.document.width, self.document.height
            sym_x = w * cx_pct
            sym_y = h * cy_pct
            
            # Keep track of whether the cursor center is mirrored: (x, y, is_mirror)
            centers = [(int(self._mouse_pos.x()), int(self._mouse_pos.y()), False)]
            mirrors = []
            if mirror_x: mirrors.append(QPoint(int(2 * sym_x - doc_pos.x()), doc_pos.y()))
            if mirror_y: mirrors.append(QPoint(doc_pos.x(), int(2 * sym_y - doc_pos.y())))
            if mirror_x and mirror_y: mirrors.append(QPoint(int(2 * sym_x - doc_pos.x()), int(2 * sym_y - doc_pos.y())))
            
            for m in mirrors:
                wp = self.to_widget(m)
                centers.append((int(wp.x()), int(wp.y()), True))

            alt_pressed = bool(self.tool_opts.get("_alt", False))
            if getattr(self.active_tool, "name", "") == "CloneStamp" and alt_pressed:
                for ctx, cty, is_mirror in centers:
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    if is_mirror:
                        painter.setPen(QPen(QColor(100, 0, 0, 80), 3))
                        painter.drawEllipse(QPointF(ctx, cty), 8, 8)
                        painter.setPen(QPen(QColor(255, 150, 150, 120), 1.5))
                    else:
                        painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
                        painter.drawEllipse(QPointF(ctx, cty), 8, 8)
                        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
                    painter.drawEllipse(QPointF(ctx, cty), 8, 8)
                    painter.drawLine(ctx-12, cty, ctx+12, cty)
                    painter.drawLine(ctx, cty-12, ctx, cty+12)
                    painter.restore()
                return

            actual_mask = mask
            if isinstance(actual_mask, QPixmap):
                actual_mask = actual_mask.toImage()
            elif isinstance(actual_mask, str):
                if actual_mask == "scatter":
                    from tools.brush_tool import _make_brush_stamp
                    actual_mask = _make_brush_stamp(size, hard, "scatter")
                elif actual_mask not in ("round", "square"):
                    tmp = QImage(actual_mask)
                    if not tmp.isNull():
                        actual_mask = tmp

            w_size = max(2, int(size * self.zoom))
            r = w_size / 2.0

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Default pens for the real cursor
            outer_pen_real = QPen(QColor(0, 0, 0, 160), 1.5)
            inner_pen_real = QPen(QColor(255, 255, 255, 200), 1)

            # Reddish and more transparent pens for mirrored cursors
            outer_pen_mirror = QPen(QColor(120, 0, 0, 70), 1.5)
            inner_pen_mirror = QPen(QColor(255, 120, 120, 110), 1)

            if isinstance(actual_mask, QImage) and not actual_mask.isNull():
                cache_key = (id(mask) if not isinstance(mask, str) else mask, w_size)
                if getattr(self, "_custom_cursor_cache_key", None) == cache_key:
                    path = self._custom_cursor_cache_path
                else:
                    scaled_img = actual_mask.scaled(w_size, w_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    if not scaled_img.hasAlphaChannel():
                        mask_img = scaled_img.createHeuristicMask()
                    else:
                        mask_img = scaled_img.createAlphaMask()
                        
                    bitmap = QBitmap.fromImage(mask_img)
                    region = QRegion(bitmap)
                    path = QPainterPath()
                    path.addRegion(region)
                    path = path.simplified()
                    self._custom_cursor_cache_key = cache_key
                    self._custom_cursor_cache_path = path

                br = path.boundingRect()
                for ctx, cty, is_mirror in centers:
                    c_path = QPainterPath(path)
                    c_path.translate(ctx - br.center().x(), cty - br.center().y())
                    painter.save()
                    if angle != 0.0:
                        painter.translate(ctx, cty)
                        painter.rotate(angle)
                        painter.translate(-ctx, -cty)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    
                    # Apply reddish transparent colors if mirrored
                    painter.setPen(outer_pen_mirror if is_mirror else outer_pen_real)
                    painter.drawPath(c_path)
                    painter.setPen(inner_pen_mirror if is_mirror else inner_pen_real)
                    painter.drawPath(c_path)
                    painter.restore()
            else:
                for ctx, cty, is_mirror in centers:
                    painter.save()
                    if angle != 0.0:
                        painter.translate(ctx, cty)
                        painter.rotate(angle)
                        painter.translate(-ctx, -cty)
                    
                    if hard < 0.8 and actual_mask != "square":
                        grad = QRadialGradient(ctx, cty, r)
                        if is_mirror:
                            # Reddish transparent gradient for mirror preview
                            grad.setColorAt(0,    QColor(255, 100, 100, 80))
                            grad.setColorAt(hard, QColor(255, 50, 50, 40))
                            grad.setColorAt(1,    QColor(255, 0, 0, 0))
                        else:
                            grad.setColorAt(0,   QColor(255, 255, 255, 100))
                            grad.setColorAt(hard, QColor(255, 255, 255, 80))
                            grad.setColorAt(1,   QColor(255, 255, 255, 0))
                        painter.setBrush(grad)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(QPoint(ctx, cty), int(r), int(r))

                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    current_outer = outer_pen_mirror if is_mirror else outer_pen_real
                    current_inner = inner_pen_mirror if is_mirror else inner_pen_real

                    if actual_mask == "square":
                        rect = QRect(int(ctx - r), int(cty - r), w_size, w_size)
                        painter.setPen(current_outer); painter.drawRect(rect.adjusted(1, 1, -1, -1))
                        painter.setPen(current_inner); painter.drawRect(rect)
                    else:
                        painter.setPen(current_outer); painter.drawEllipse(QPoint(ctx, cty), int(r) + 1, int(r) + 1)
                        painter.setPen(current_inner); painter.drawEllipse(QPoint(ctx, cty), int(r), int(r))
                    painter.restore()

            if w_size > 16:
                for ctx, cty, is_mirror in centers:
                    # Adjust center crosshair transparency/color for mirror cursors
                    cross_color = QColor(255, 150, 150, 100) if is_mirror else QColor(255, 255, 255, 180)
                    painter.setPen(QPen(cross_color, 1))
                    painter.drawLine(ctx - 3, cty, ctx + 3, cty)
                    painter.drawLine(ctx, cty - 3, ctx, cty + 3)

            painter.restore()
        except Exception:
            logger.debug("Brush cursor overlay failed", exc_info=True)

    def _emit_tool_state(self):
        if hasattr(self.active_tool, "get_transform_params"):
            self.tool_state_changed.emit(self.active_tool.get_transform_params())
        else:
            self.tool_state_changed.emit(None)

    def tabletEvent(self, ev):
        self.tool_opts["_pressure"] = ev.pressure()
        ev.ignore()

    def mousePressEvent(self, ev):
        """A press goes to the first handler that takes it: guides, panning,
        the view tools, the brush-symmetry centre — or else the active tool
        (a stroke). Errors are isolated so a failing tool can't kill input."""
        if not self.document:
            return
        try:
            if self._press_guides(ev):
                return
            self._store_press_modifiers(ev)
            if self._press_pan_or_view_tool(ev):
                return
            if ev.button() == Qt.MouseButton.LeftButton and self.active_tool:
                if not self._press_active_tool(ev):
                    return
            self._emit_tool_state()
        except Exception:
            logger.exception("Critical mouse press error")
            self._stroke_in_progress = False

    def _press_guides(self, ev) -> bool:
        """Drag a new guide out of a ruler, or (Move tool) pick up an existing one."""
        if getattr(self, "show_rulers", False):
            R = 20
            pos = ev.position()
            if pos.x() < R and pos.y() > R:
                self._dragging_guide = ('v', self.to_doc(pos).x(), None)
                self.setCursor(Qt.CursorShape.SplitHCursor)
                return True
            if pos.y() < R and pos.x() > R:
                self._dragging_guide = ('h', self.to_doc(pos).y(), None)
                self.setCursor(Qt.CursorShape.SplitVCursor)
                return True

        if getattr(self.active_tool, "name", "") != "Move" or self._space:
            return False
        doc_pos = self.to_doc(ev.position())
        snap = 5 / max(0.01, self.zoom)
        hit_v = hit_h = None
        if getattr(self.document, "show_guides", False):
            for i, gx in enumerate(getattr(self.document, "guides_v", [])):
                if abs(gx - doc_pos.x()) < snap: hit_v = (i, gx)
            for i, gy in enumerate(getattr(self.document, "guides_h", [])):
                if abs(gy - doc_pos.y()) < snap: hit_h = (i, gy)
        if hit_v:
            self._dragging_guide = ('v', hit_v[1], hit_v[0])
            if hasattr(self.document, "guides_v"): self.document.guides_v.pop(hit_v[0])
            self.setCursor(Qt.CursorShape.SplitHCursor)
        elif hit_h:
            self._dragging_guide = ('h', hit_h[1], hit_h[0])
            if hasattr(self.document, "guides_h"): self.document.guides_h.pop(hit_h[0])
            self.setCursor(Qt.CursorShape.SplitVCursor)
        else:
            return False
        self.update()
        return True

    def _store_press_modifiers(self, ev):
        mods = ev.modifiers()
        self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
        self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)
        self.tool_opts["_zoom"]  = self.zoom

    def _press_pan_or_view_tool(self, ev) -> bool:
        """Middle button / Space+left pans; Hand, Zoom and Rotate View act
        on the view instead of the document."""
        if ev.button() == Qt.MouseButton.MiddleButton or (self._space and ev.button() == Qt.MouseButton.LeftButton):
            self._start_pan(ev)
            return True
        if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
            self.tool_opts["_pressure"] = 1.0
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        if isinstance(self.active_tool, HandTool):
            self._start_pan(ev)
            return True
        if isinstance(self.active_tool, ZoomTool):
            alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._apply_zoom(1 / 1.25 if alt else 1.25, ev.position())
            return True
        if isinstance(self.active_tool, RotateViewTool):
            self._rotating = True
            cx, cy = self.width() / 2, self.height() / 2
            self._rotate_last_angle = math.degrees(math.atan2(ev.position().y() - cy, ev.position().x() - cx))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        return False

    def _start_pan(self, ev):
        self._panning = True
        self._pan_last = ev.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _press_symmetry_center(self, ev) -> bool:
        """Brush symmetry: Ctrl+click moves the mirror centre, a click on it
        starts dragging it. True if the press was that."""
        mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
        mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
        if not (mirror_x or mirror_y):
            return False
        doc_pos = self.to_doc(ev.position())
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._dragging_sym_center = True
            new_cx = max(0.0, min(1.0, doc_pos.x() / max(1, self.document.width)))
            new_cy = max(0.0, min(1.0, doc_pos.y() / max(1, self.document.height)))
            self.tool_opts["brush_mirror_cx"] = new_cx
            self.tool_opts["brush_mirror_cy"] = new_cy
            self.tool_state_changed.emit({"brush_mirror_cx": new_cx, "brush_mirror_cy": new_cy})
            self.update()
            return True
        sym_x = self.document.width * float(self.tool_opts.get("brush_mirror_cx", 0.5))
        sym_y = self.document.height * float(self.tool_opts.get("brush_mirror_cy", 0.5))
        if math.hypot(doc_pos.x() - sym_x, doc_pos.y() - sym_y) <= 15 / max(0.01, self.zoom):
            self._dragging_sym_center = True
            return True
        return False

    def _press_active_tool(self, ev) -> bool:
        """Start a stroke with the active tool: pixel gate, undo snapshot,
        the tool's own on_press. False if the press ended before the tool
        (rasterize prompt / refusal, brush-symmetry centre)."""
        tool = self.active_tool
        tool_name = getattr(tool, "name", "")
        layer = self.document.get_active_layer()

        op = getattr(tool, "PIXEL_OP", None)
        win = self.window()
        if layer is not None and op is not None and hasattr(win, "_rasterize_layer"):
            from ui.actions.pixel_target import pixel_layer_for_edit
            # A rasterize prompt (or refusal) ends this press: the stroke
            # starts with the next click, on the new layer.
            if pixel_layer_for_edit(win, op) is not layer:
                return False

        if tool.BRUSH_CURSOR and self._press_symmetry_center(ev):
            return False

        self._stroke_in_progress = True
        if tool.needs_history_push():
            self._pre_stroke_state = self._history_state_for(tool_name)
        old_layer_idx = self.document.active_layer_index
        doc_pos = self.to_doc(ev.position())

        if getattr(tool, "needs_background_composite", False):
            self._start_effect_stroke()

        try:
            tool.on_press(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
        except Exception:
            logger.exception("Tool %s failed in on_press", tool_name)
            if hasattr(win, "_status"):
                from ui.toolbar import ToolBar
                win._status.showMessage(tr("err.tool_failed", tool=ToolBar.tool_title(tool_name)), 4000)
            self._stroke_in_progress = False
            self._pre_stroke_state = None

        self._cache_dirty = True
        self._check_marching_ants()
        self.update()

        if getattr(tool, "needs_immediate_commit", False) and self._stroke_in_progress:
            self._stroke_in_progress = False
            self.document_changed.emit()
        elif self.document.active_layer_index != old_layer_idx:
            self.document_changed.emit()
        return True

    def _history_state_for(self, tool_name: str):
        """Undo snapshot taken before a stroke (pixels are shared
        copy-on-write, see Document.snapshot_layers)."""
        from core.history import HistoryState, clone_work_path
        from ui.toolbar import ToolBar
        doc = self.document
        return HistoryState(
            description=ToolBar.tool_title(tool_name),
            layers_snapshot=doc.snapshot_layers(),
            active_layer_index=doc.active_layer_index,
            doc_width=doc.width,
            doc_height=doc.height,
            selection_snapshot=QPainterPath(doc.selection) if doc.selection else None,
            work_path_snapshot=clone_work_path(getattr(doc, "work_path", None)),
            alpha_channels_snapshot=list(getattr(doc, "alpha_channels", [])),
            color_mode_snapshot=getattr(doc, "color_mode", "RGB"),
            bit_depth_snapshot=getattr(doc, "bit_depth", 8))

    def mouseMoveEvent(self, ev):
        """Handles mouse move for brush strokes and deformations."""
        try:
            mods = ev.modifiers()
            self.tool_opts["_shift"] = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.tool_opts["_ctrl"]  = bool(mods & Qt.KeyboardModifier.ControlModifier)
            self.tool_opts["_alt"]   = bool(mods & Qt.KeyboardModifier.AltModifier)
            self.tool_opts["_zoom"]  = self.zoom
            
            if hasattr(ev, "device") and ev.device().type() == QInputDevice.DeviceType.Mouse:
                self.tool_opts["_pressure"] = 1.0

            self._mouse_pos = ev.position()

            if self._stroke_in_progress and not (ev.buttons() & Qt.MouseButton.LeftButton):
                doc_pos = self.to_doc(ev.position())
                if self.active_tool:
                    try: self.active_tool.on_release(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception:
                        logger.exception("Tool %s failed in on_release", getattr(self.active_tool, "name", "?"))
                self._stroke_in_progress = False
                self._prev_brush_wp = None
                if self._in_effect_stroke and self.active_tool and hasattr(self.active_tool, "_stroke_preview_active"):
                    self.active_tool._stroke_preview_active = False
                self._in_effect_stroke = False
                self._effect_bg_cache = None
                # Eager composite so paintEvent is instant
                self._recompute_composite()
                self._cache_dirty = False
                self._display_cache = None
                self._check_marching_ants()
                self.update()
                self.document_changed.emit()

            if getattr(self, "_dragging_sym_center", False):
                doc_pos = self.to_doc(ev.position())
                new_cx = max(0.0, min(1.0, doc_pos.x() / max(1, self.document.width)))
                new_cy = max(0.0, min(1.0, doc_pos.y() / max(1, self.document.height)))
                self.tool_opts["brush_mirror_cx"] = new_cx
                self.tool_opts["brush_mirror_cy"] = new_cy
                self.tool_state_changed.emit({"brush_mirror_cx": new_cx, "brush_mirror_cy": new_cy})
                self.update()
                return

            if getattr(self, "_dragging_guide", None) is not None:
                doc_pos = self.to_doc(ev.position())
                gtype, _, orig_idx = self._dragging_guide
                self._dragging_guide = (gtype, doc_pos.x() if gtype == 'v' else doc_pos.y(), orig_idx)
                self.update()
                return

            if self._panning and self._pan_last is not None:
                delta = ev.position() - self._pan_last
                self._pan += delta
                self._pan_last = ev.position()
                self.update()
                return

            if self._rotating:
                cx = self.width()  / 2
                cy = self.height() / 2
                curr = math.degrees(math.atan2(ev.position().y() - cy, ev.position().x() - cx))
                delta = curr - self._rotate_last_angle
                if delta >  180: delta -= 360
                if delta < -180: delta += 360
                self._view_rotation += delta
                self._rotate_last_angle = curr
                self.update()
                return

            if self._show_brush_cursor:
                self._update_brush_region(ev.position())
            elif isinstance(self.active_tool, (SelectTool, ShapesTool, RotateViewTool, GradientTool)) or (
                    self.active_tool and hasattr(self.active_tool, "sub_drag_path")):
                self.update()

            if (ev.buttons() & Qt.MouseButton.LeftButton and self._stroke_in_progress and self.active_tool):
                doc_pos = self.to_doc(ev.position())
                
                # Safe tool move handler
                try:
                    self.active_tool.on_move(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                except Exception as move_ex:
                    logger.exception("Tool %s failed in on_move", getattr(self.active_tool, "name", "?"))
                    if hasattr(self.window(), "_status"):
                        self.window()._status.showMessage("Tool move step failed", 1000)

                if getattr(self.active_tool, "modifies_canvas_on_move", False):
                    is_brush_preview = (
                        self._stroke_in_progress and
                        hasattr(self.active_tool, "stroke_preview") and
                        not getattr(self.active_tool, "needs_background_composite", False) and
                        not getattr(self.active_tool, "needs_composite_refresh", False)
                    )
                    is_effect_optimized = self._stroke_in_progress and self._in_effect_stroke
                    if not is_brush_preview and not is_effect_optimized:
                        self._cache_dirty = True

                if self._stroke_in_progress and hasattr(self.active_tool, "stroke_preview"):
                    self._update_brush_region(ev.position())
                else:
                    self.update()
                self.pixels_changed.emit()
                
                self._move_counter = getattr(self, "_move_counter", 0) + 1
            else:
                if self.active_tool and hasattr(self.active_tool, "on_hover"):
                    try:
                        doc_pos = self.to_doc(ev.position())
                        self.active_tool.on_hover(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception:
                        logger.debug("Tool %s failed in on_hover", getattr(self.active_tool, "name", "?"), exc_info=True)
                    self._update_cursor()
            self._emit_tool_state()

            if self.document:
                dp = self.to_doc(ev.position())
                cx, cy = dp.x(), dp.y()
                if 0 <= cx < self.document.width and 0 <= cy < self.document.height:
                    layer = self.document.get_active_layer()
                    if layer and 0 <= cx < layer.image.width() and 0 <= cy < layer.image.height():
                        color = layer.image.pixelColor(cx, cy)
                    else:
                        color = QColor(0, 0, 0, 0)
                    self.cursor_info.emit(cx, cy, color)
        except Exception as global_move_ex:
            logger.exception("Critical mouse move error")

    def mouseReleaseEvent(self, ev):
        """Handles mouse release to finalize strokes."""
        try:
            if getattr(self, "_dragging_sym_center", False) and ev.button() == Qt.MouseButton.LeftButton:
                self._dragging_sym_center = False
                self._update_cursor()
                return
                
            if getattr(self, "_dragging_guide", None) is not None:
                gtype, val, _ = self._dragging_guide
                wx, wy = self.to_widget(QPoint(int(val), 0)).x(), self.to_widget(QPoint(0, int(val))).y()
                R = 20 if self.show_rulers else 0
                if gtype == 'v' and wx > R:
                    if not hasattr(self.document, "guides_v"): self.document.guides_v = []
                    self.document.guides_v.append(val)
                elif gtype == 'h' and wy > R:
                    if not hasattr(self.document, "guides_h"): self.document.guides_h = []
                    self.document.guides_h.append(val)
                self._dragging_guide = None
                self._update_cursor()
                self.update()
                return
                
            if ev.button() == Qt.MouseButton.MiddleButton or (self._panning and ev.button() == Qt.MouseButton.LeftButton):
                self._panning = False
                self._pan_last = None
                self._update_cursor()
                return

            if self._rotating and ev.button() == Qt.MouseButton.LeftButton:
                self._rotating = False
                self._update_cursor()
                return

            if ev.button() == Qt.MouseButton.LeftButton and self._stroke_in_progress:
                doc_pos = self.to_doc(ev.position())
                tool_name = getattr(self.active_tool, "name", "")

                # Safe tool release handler
                if self.active_tool:
                    try:
                        self.active_tool.on_release(doc_pos, self.document, self.fg_color, self.bg_color, self.tool_opts)
                    except Exception as rel_ex:
                        logger.exception("Tool %s failed in on_release", tool_name)
                        if hasattr(self.window(), "_status"):
                            self.window()._status.showMessage("Tool release failed", 4000)

                self._stroke_in_progress = False
                self._prev_brush_wp = None
                if self._in_effect_stroke and self.active_tool and hasattr(self.active_tool, "_stroke_preview_active"):
                    self.active_tool._stroke_preview_active = False
                self._in_effect_stroke = False
                self._effect_bg_cache = None

                # Eagerly recompute the composite now (stroke already applied to
                # the layer in on_release above). This keeps paintEvent cheap,
                # and if the tool can report the touched rect, only that rect
                # is blitted into the existing cache instead of a full redraw.
                self._recompute_composite()
                self._cache_dirty = False
                self._display_cache = None

                self._check_marching_ants()
                self.update()
                self.document_changed.emit()
            self._emit_tool_state()
        except Exception as global_release_ex:
            logger.exception("Critical mouse release error")
            self._stroke_in_progress = False

    def enterEvent(self, ev):
        self._is_mouse_in = True
        self._update_cursor()

    def leaveEvent(self, ev):
        try:
            self._is_mouse_in = False
            self._show_brush_cursor = False
            if self.active_tool and hasattr(self.active_tool, "on_leave"):
                self.active_tool.on_leave()
            if self.active_tool:
                for attr in ["_hover_pos", "_current_mouse_pos", "_mouse_pos", "hover_pos", "current_pos", "_current_pos", "_preview_end", "preview_end", "_last_pos"]:
                    if hasattr(self.active_tool, attr):
                        setattr(self.active_tool, attr, None)
            self.update()
        except Exception:
            logger.debug("leaveEvent cleanup failed", exc_info=True)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self._apply_zoom(factor, ev.position())
        else:
            super().wheelEvent(ev)

    def _start_alt_eyedropper(self):
        if (self._alt_prev_tool is not None or self._stroke_in_progress
                or self.active_tool is None
                or getattr(self.active_tool, "name", None) not in _ALT_EYEDROPPER_TOOLS):
            return
        from tools.eyedropper_tool import EyedropperTool
        mw = self.window()
        picker = EyedropperTool()
        if hasattr(mw, "_color_panel") and hasattr(mw, "_on_fg_changed"):
            picker.color_picked_callback = lambda c: (mw._color_panel.set_fg(c), mw._on_fg_changed(c))
        else:
            picker.color_picked_callback = lambda c: setattr(self, "fg_color", c)
        self._alt_prev_tool = self.active_tool
        self._alt_picker = picker
        self.active_tool = picker
        self._update_cursor()
        self.update()

    def _stop_alt_eyedropper(self):
        if self._alt_prev_tool is None:
            return
        prev, self._alt_prev_tool = self._alt_prev_tool, None
        # Only restore if nothing else changed the active tool in the
        # meantime (e.g. the user clicked a different tool on the toolbar
        # while Alt was still held).
        if self.active_tool is self._alt_picker:
            self.active_tool = prev
        self._alt_picker = None
        self._update_cursor()
        self.update()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Control: self.tool_opts["_ctrl"] = True
        if k == Qt.Key.Key_Shift: self.tool_opts["_shift"] = True
        if k == Qt.Key.Key_Alt: self.tool_opts["_alt"] = True
        if k == Qt.Key.Key_Alt and not ev.isAutoRepeat():
            self._start_alt_eyedropper()

        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self._update_cursor()
        elif k == Qt.Key.Key_Plus or k == Qt.Key.Key_Equal:
            self.zoom_in()
        elif k == Qt.Key.Key_Minus:
            self.zoom_out()
        elif k == Qt.Key.Key_0:
            self.reset_zoom()
        elif k == Qt.Key.Key_BracketLeft:
            new_size = max(1, self.tool_opts.get("brush_size", 10) - 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        elif k == Qt.Key.Key_BracketRight:
            new_size = min(500, self.tool_opts.get("brush_size", 10) + 2)
            self.tool_opts["brush_size"] = new_size
            self.update()
        elif k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            self._update_cursor()
            super().keyPressEvent(ev)
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Control: self.tool_opts["_ctrl"] = False
        if k == Qt.Key.Key_Shift: self.tool_opts["_shift"] = False
        if k == Qt.Key.Key_Alt: self.tool_opts["_alt"] = False
        if k == Qt.Key.Key_Alt and not ev.isAutoRepeat():
            self._stop_alt_eyedropper()

        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self._update_cursor()
        elif k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            self._update_cursor()
            super().keyReleaseEvent(ev)
        else:
            super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pan == QPointF(0, 0):
            self._fit_to_window()

    def _update_cursor(self):
        try:
            if getattr(self, "_panning", False) or getattr(self, "_space", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor if getattr(self, "_panning", False) else Qt.CursorShape.OpenHandCursor)
                return
                
            if getattr(self, "_rotating", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
                
            if getattr(self, "_dragging_sym_center", False):
                self._show_brush_cursor = False
                self.setCursor(Qt.CursorShape.CrossCursor)
                return

            tool_name = getattr(self.active_tool, "name", "") if self.active_tool else ""
            # The temporary Alt-eyedropper keeps the brush's own blank-cursor
            # + circle-guide look instead of switching to a real CrossCursor:
            # some window managers only redraw the system cursor icon on the
            # next mouse-originated event, so a setCursor() driven purely by
            # keyPressEvent/keyReleaseEvent can visually stick (old shape
            # bleeds through, stacking with the newly (correctly) repainted
            # brush-circle overlay). Keeping the cursor shape unchanged across
            # the whole Alt hold/release avoids relying on that redraw at all.
            is_alt_picker = self.active_tool is not None and self.active_tool is getattr(self, "_alt_picker", None)
            if getattr(self.active_tool, "BRUSH_CURSOR", False) or is_alt_picker:
                mirror_x = bool(self.tool_opts.get("brush_mirror_x", False))
                mirror_y = bool(self.tool_opts.get("brush_mirror_y", False))
                is_hovering_sym = False
                ctrl_pressed = bool(self.tool_opts.get("_ctrl", False))
                
                if (mirror_x or mirror_y) and self.document:
                    if ctrl_pressed:
                        self._show_brush_cursor = False
                        self.setCursor(Qt.CursorShape.CrossCursor)
                        return

                    cx_pct = float(self.tool_opts.get("brush_mirror_cx", 0.5))
                    cy_pct = float(self.tool_opts.get("brush_mirror_cy", 0.5))
                    sym_x = self.document.width * cx_pct
                    sym_y = self.document.height * cy_pct
                    doc_pos = self.to_doc(self._mouse_pos)
                    hit_radius = 15 / max(0.01, self.zoom)
                    if math.hypot(doc_pos.x() - sym_x, doc_pos.y() - sym_y) <= hit_radius:
                        is_hovering_sym = True
                if is_hovering_sym:
                    self._show_brush_cursor = False
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self._show_brush_cursor = True
                    self.setCursor(Qt.CursorShape.BlankCursor)
            elif getattr(self.active_tool, "SELECTION_CURSOR", False):
                self._show_brush_cursor = False
                ctrl = bool(self.tool_opts.get("_ctrl", False))
                alt  = bool(self.tool_opts.get("_alt",  False))
                if ctrl and alt: mode = "intersect"
                elif ctrl: mode = "add"
                elif alt: mode = "sub"
                else: mode = "new"
                self.setCursor(_make_sel_cursor(mode))
            else:
                self._show_brush_cursor = False
                if self.active_tool:
                    self.setCursor(QCursor(self.active_tool.cursor()))
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            self.setCursor(Qt.CursorShape.ArrowCursor)