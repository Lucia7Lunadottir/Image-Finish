"""Overlay rendering functions extracted from CanvasWidget._paint_canvas_content().

Each function takes a QPainter and the relevant state, draws one overlay,
and returns. All functions call painter.save()/restore() internally."""

import math

from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QPainterPath,
                         QPolygonF, QTransform)

from core.app_logging import get_logger
from ui import theme

logger = get_logger("overlays")


def draw_grid(painter, *, doc, pan, zoom):
    if not getattr(doc, "show_grid", False):
        return
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    painter.setPen(QPen(QColor(128, 128, 128, 100), 1.0 / zoom, Qt.PenStyle.DotLine))
    gs = max(5, getattr(doc, "grid_size", 50))
    for x in range(0, doc.width, gs):
        painter.drawLine(QPointF(x, 0), QPointF(x, doc.height))
    for y in range(0, doc.height, gs):
        painter.drawLine(QPointF(0, y), QPointF(doc.width, y))
    painter.restore()


def draw_rulers(painter, *, width, height, pan, zoom):
    from ui.canvas_guides import RULER_SIZE as R
    w, h = width, height
    painter.fillRect(0, 0, w, R, QColor(theme.MANTLE))
    painter.fillRect(0, 0, R, h, QColor(theme.MANTLE))
    painter.fillRect(0, 0, R, R, QColor(theme.CRUST))

    painter.setPen(QColor(theme.SUBTEXT))
    font = painter.font()
    font.setPointSize(8)
    painter.setFont(font)
    
    start_x = - (pan.x() / zoom)
    end_x = start_x + w / zoom
    step = 100
    if zoom > 2: step = 10
    elif zoom > 0.5: step = 50
    elif zoom < 0.2: step = 500
    
    first_x = int(start_x // step) * step
    for x in range(first_x, int(end_x) + step, step):
        wx = int(x * zoom + pan.x())
        if wx > R:
            painter.drawLine(wx, R - 6, wx, R)
            painter.drawText(wx + 2, R - 2, str(x))
            
    start_y = - (pan.y() / zoom)
    end_y = start_y + h / zoom
    first_y = int(start_y // step) * step
    for y in range(first_y, int(end_y) + step, step):
        wy = int(y * zoom + pan.y())
        if wy > R:
            painter.drawLine(R - 6, wy, R, wy)
            painter.save()
            painter.translate(R - 2, wy + 2)
            painter.rotate(-90)
            painter.drawText(0, 0, str(y))
            painter.restore()


def draw_artboard_frames(painter, *, doc, pan, zoom):
    """Each artboard's outline and its name above it."""
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    for layer in doc.artboards():
        ar = layer.artboard_rect
        painter.setPen(QPen(QColor(120, 120, 120), max(1.0, 1.0 / zoom)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(ar)
        painter.setPen(QColor(200, 200, 200))
        font = painter.font()
        font.setPointSizeF(max(10.0, 12.0 / zoom))
        painter.setFont(font)
        painter.drawText(ar.left(), ar.top() - max(4, int(4 / zoom)), layer.name)
    painter.restore()


def draw_guides(painter, *, doc, pan, zoom, dragging_guide):
    if not getattr(doc, "show_guides", False):
        return
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    pw = 1.0 / zoom
    painter.setPen(QPen(QColor(0, 255, 255, 200), pw))
    for gx in getattr(doc, "guides_v", []):
        painter.drawLine(QPointF(gx, -10000), QPointF(gx, 10000))
    for gy in getattr(doc, "guides_h", []):
        painter.drawLine(QPointF(-10000, gy), QPointF(10000, gy))
    if dragging_guide:
        gtype, val, _ = dragging_guide
        painter.setPen(QPen(QColor(0, 255, 255, 255), pw))
        if gtype == 'v':
            painter.drawLine(QPointF(val, -10000), QPointF(val, 10000))
        else:
            painter.drawLine(QPointF(-10000, val), QPointF(10000, val))
    painter.restore()


def draw_slices(painter, *, doc, pan, zoom):
    if not getattr(doc, "show_slices", True):
        return
    slices = getattr(doc, "slices", [])
    if not slices:
        return
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    pw = 1.0 / zoom
    pen1 = QPen(QColor(0, 150, 255, 200), pw)
    pen1.setCosmetic(True)
    painter.setPen(pen1)
    font = painter.font()
    font.setPointSizeF(max(8.0, 10.0 / zoom))
    painter.setFont(font)
    for i, r in enumerate(slices):
        painter.setBrush(QColor(0, 150, 255, 20))
        painter.drawRect(r)
        badge_rect = QRectF(r.left(), r.top(), 24 / zoom, 16 / zoom)
        painter.fillRect(badge_rect, QColor(0, 150, 255, 200))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(i + 1))

        pen2 = QPen(QColor(0, 150, 255, 200), pw)
        pen2.setCosmetic(True)
        painter.setPen(pen2)
    painter.restore()


def draw_symmetry_axes(painter, *, doc, pan, zoom, tool_opts, brush_tool):
    from core.brush_symmetry import BrushSymmetry
    sym = BrushSymmetry.from_opts(tool_opts, doc.width, doc.height)
    if not brush_tool or not sym.active:
        return
    mirror_x, mirror_y = sym.mirror_x, sym.mirror_y
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    pw = 1.0 / zoom
    pen1 = QPen(QColor(0, 0, 0, 100), 3)
    pen1.setCosmetic(True)
    pen2 = QPen(QColor(100, 200, 255, 180), 1)
    pen2.setCosmetic(True)
    pen2.setStyle(Qt.PenStyle.DashLine)
    w, h = doc.width, doc.height
    sym_x, sym_y = sym.cx, sym.cy
    if mirror_x:
        painter.setPen(pen1); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
        painter.setPen(pen2); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
    if mirror_y:
        painter.setPen(pen1); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
        painter.setPen(pen2); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
    
    # Важно: drawEllipse рисует в координатах документа (которые сейчас отмасштабированы).
    # Чтобы радиус маркера на экране ВСЕГДА был, например, 6 пикселей,
    # его геометрию в координатах документа нужно скорректировать на zoom.
    r_handle = 8.0 / zoom 
    
    # Для обводки маркера тоже используем косметическое перо фиксированной толщины
    pen_handle = QPen(QColor(0, 0, 0, 150), 2.0)
    pen_handle.setCosmetic(True)
    
    painter.setPen(pen_handle)
    painter.setBrush(QColor(100, 200, 255, 200))
    painter.drawEllipse(QPointF(sym_x, sym_y), r_handle, r_handle)

    painter.restore()


def draw_selection(painter, *, doc, pan, zoom, march_offset):
    sel = doc.selection
    in_qm = getattr(doc, "quick_mask_layer", None) is not None
    if not sel or sel.isEmpty() or in_qm:
        return
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    
    painter.setBrush(Qt.BrushStyle.NoBrush)
    
    # First pen (black ants)
    pen = QPen(QColor(0, 0, 0, 160), 1.5)
    pen.setCosmetic(True)  # Keep selection border size pixel-perfect on screen
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setDashOffset(march_offset)
    painter.setPen(pen)
    painter.drawPath(sel)
    
    # Second pen (white background ants)
    pen2 = QPen(QColor(255, 255, 255, 220), 1.0)
    pen2.setCosmetic(True)  # Keep selection border size pixel-perfect on screen
    pen2.setStyle(Qt.PenStyle.DashLine)
    pen2.setDashOffset(march_offset + 4)
    painter.setPen(pen2)
    painter.drawPath(sel)
    
    painter.restore()


def draw_subtract_drag(painter, *, active_tool, pan, zoom, SelectTool):
    if active_tool and hasattr(active_tool, "sub_drag_path"):
        try:
            sub_p = active_tool.sub_drag_path()
            if sub_p:
                painter.save()
                painter.translate(pan)
                painter.scale(zoom, zoom)
                pen = QPen(QColor(220, 60, 60), 1.0)
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(sub_p)
                painter.restore()
        except Exception:
            logger.debug("Overlay draw failed", exc_info=True)
    elif isinstance(active_tool, SelectTool):
        try:
            sub_r = active_tool.sub_drag_rect()
            if sub_r:
                painter.save()
                painter.translate(pan)
                painter.scale(zoom, zoom)
                pen = QPen(QColor(220, 60, 60), 1.0)
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(sub_r)
                painter.restore()
        except Exception:
            logger.debug("Overlay draw failed", exc_info=True)


def draw_lasso_preview(painter, *, active_tool, pan, zoom, is_mouse_in):
    if not active_tool or not hasattr(active_tool, "lasso_preview"):
        return
    try:
        preview_data = active_tool.lasso_preview()
        if not preview_data:
            return
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen1 = QPen(QColor(0, 0, 0), 1.0)
        pen1.setCosmetic(True)
        pen2 = QPen(QColor(255, 255, 255), 1.0)
        pen2.setCosmetic(True)
        pen2.setStyle(Qt.PenStyle.DashLine)
        
        points = preview_data[0] if isinstance(preview_data, tuple) else preview_data
        current_pos = preview_data[1] if isinstance(preview_data, tuple) else None
        if len(points) > 0:
            poly = QPolygonF(points)
            painter.setPen(pen1)
            painter.drawPolyline(poly)
            painter.setPen(pen2)
            painter.drawPolyline(poly)
            if current_pos and is_mouse_in:
                painter.setPen(pen1)
                painter.drawLine(points[-1], current_pos)
                painter.setPen(pen2)
                painter.drawLine(points[-1], current_pos)
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_transform_preview(painter, *, active_tool, pan, zoom):
    if not active_tool or not hasattr(active_tool, "floating_preview"):
        return
    try:
        fp = active_tool.floating_preview()
        if not fp:
            return
        if len(fp) == 4 and fp[0] == "transform":
            _, img, tl, transform = fp
            painter.save()
            painter.translate(pan)
            painter.scale(zoom, zoom)
            painter.setTransform(QTransform().translate(tl.x(), tl.y()) * transform, combine=True)
            painter.drawImage(0, 0, img)
            painter.restore()
        elif len(fp) == 2 and fp[0] == "live":
            _, layer = fp
            painter.save()
            painter.translate(pan)
            painter.scale(zoom, zoom)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setOpacity(layer.opacity)
            layer.paint_content(painter)
            painter.restore()
        elif len(fp) == 4 and fp[0] == "warp":
            _, src_img, patches, fast = fp
            painter.save()
            painter.translate(pan)
            painter.scale(zoom, zoom)
            from tools.warp_tool import WarpTool
            WarpTool.draw_warp_patches(painter, src_img, patches, fast)
            painter.restore()
        else:
            img, tl = fp
            painter.save()
            painter.translate(pan)
            painter.scale(zoom, zoom)
            painter.drawImage(tl, img)
            painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_brush_stroke(painter, *, active_tool, tool_opts, pan, zoom):
    if not active_tool or not hasattr(active_tool, "stroke_preview"):
        return
    try:
        sp = active_tool.stroke_preview()
        if not sp:
            return
        img, tl, op = sp
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        if hasattr(active_tool, "stroke_composition_mode"):
            painter.setCompositionMode(active_tool.stroke_composition_mode(tool_opts))
        painter.setOpacity(max(0.0, min(1.0, float(op))))
        painter.drawImage(tl, img)
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_crop_preview(painter, *, active_tool, tool_opts, pan, zoom, doc, CropTool):
    if not isinstance(active_tool, CropTool) or not active_tool.pending_rect:
        return
    try:
        cr = active_tool.pending_rect
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)

        path = QPainterPath()
        path.addRect(QRectF(0, 0, doc.width, doc.height))
        path.addRect(QRectF(cr))
        path.setFillRule(Qt.FillRule.OddEvenFill)
        painter.fillPath(path, QColor(0, 0, 0, 100))

        border_pen = QPen(QColor(255, 200, 0), 1.5)
        border_pen.setCosmetic(True)

        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(cr)

        overlay = tool_opts.get("crop_overlay", "thirds")
        if overlay != "none":
            # Using cosmetic pen for helper lines
            grid_pen = QPen(QColor(255, 255, 255, 150), 1.0, Qt.PenStyle.DashLine)
            grid_pen.setCosmetic(True)
            painter.setPen(grid_pen)
            w, h = cr.width(), cr.height()
            if overlay == "thirds":
                painter.drawLine(QPointF(cr.left(), cr.top() + h / 3), QPointF(cr.right(), cr.top() + h / 3))
                painter.drawLine(QPointF(cr.left(), cr.top() + h * 2 / 3), QPointF(cr.right(), cr.top() + h * 2 / 3))
                painter.drawLine(QPointF(cr.left() + w / 3, cr.top()), QPointF(cr.left() + w / 3, cr.top() + h))
                painter.drawLine(QPointF(cr.left() + w * 2 / 3, cr.top()), QPointF(cr.left() + w * 2 / 3, cr.top() + h))
            elif overlay == "grid":
                for i in range(1, 5):
                    painter.drawLine(QPointF(cr.left(), cr.top() + h * i / 5), QPointF(cr.right(), cr.top() + h * i / 5))
                    painter.drawLine(QPointF(cr.left() + w * i / 5, cr.top()), QPointF(cr.left() + w * i / 5, cr.top() + h))
            elif overlay == "diagonal":
                painter.drawLine(cr.topLeft(), cr.bottomRight())
                painter.drawLine(cr.topRight(), cr.bottomLeft())

        # Configure cosmetic handles pen
        handle_pen = QPen(QColor(0, 0, 0), 1.0)
        handle_pen.setCosmetic(True)
        
        pts = [cr.topLeft(), QPointF(cr.center().x(), cr.top()), cr.topRight(),
               QPointF(cr.right(), cr.center().y()), cr.bottomRight(),
               QPointF(cr.center().x(), doc.height if math.isclose(cr.bottom(), doc.height) else cr.bottom()),
               cr.bottomLeft(), QPointF(cr.left(), cr.center().y())]
               
        for pt in pts:
            painter.save()
            
            # Map the raw geometric point to screen widget coordinates directly
            screen_pos = painter.combinedTransform().map(pt)
            
            # Switch to pure screen space to completely prevent scale/zoom distortions[cite: 2]
            painter.setTransform(QTransform())
            painter.setBrush(QColor(255, 255, 255))
            painter.setPen(handle_pen)
            
            # Sub-pixel math alignment to fix the X-axis shifting caused by painter.scale() rounding
            cx = math.floor(screen_pos.x()) + 0.5
            cy = round(screen_pos.y())
            
            # Set fixed size in screen pixels (4.0 means 8x8 pixels handle box)
            s_pixels = 4.0 
            handle_rect = QRectF(
                cx - s_pixels,
                cy - s_pixels,
                s_pixels * 2.0,
                s_pixels * 2.0
            )
            
            painter.drawRect(handle_rect)
            painter.restore()
            
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_perspective_crop(painter, *, active_tool, tool_opts, pan, zoom, doc, PerspectiveCropTool):
    if not isinstance(active_tool, PerspectiveCropTool):
        return
    try:
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)

        if active_tool.pending_quad:
            quad = active_tool.pending_quad
            path = QPainterPath()
            path.addRect(QRectF(0, 0, doc.width, doc.height))
            path.addPolygon(QPolygonF([QPointF(p) for p in quad]))
            path.setFillRule(Qt.FillRule.OddEvenFill)
            painter.fillPath(path, QColor(0, 0, 0, 100))

            quad_pen = QPen(QColor(255, 200, 0), 1.5)
            quad_pen.setCosmetic(True)
            painter.setPen(quad_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(quad)

            overlay = tool_opts.get("crop_overlay", "thirds")
            if overlay != "none" and len(quad) == 4:
                grid_pen = QPen(QColor(255, 255, 255, 150), 1.0, Qt.PenStyle.DashLine)
                grid_pen.setCosmetic(True)
                painter.setPen(grid_pen)
                pts = [QPointF(quad[i]) for i in range(4)]
                p0, p1, p2, p3 = pts

                def lerp(a, b, t):
                    return a + (b - a) * t

                if overlay == "thirds":
                    for t in (1 / 3, 2 / 3):
                        painter.drawLine(lerp(p0, p3, t), lerp(p1, p2, t))
                        painter.drawLine(lerp(p0, p1, t), lerp(p3, p2, t))
                elif overlay == "grid":
                    for t in (1 / 5, 2 / 5, 3 / 5, 4 / 5):
                        painter.drawLine(lerp(p0, p3, t), lerp(p1, p2, t))
                        painter.drawLine(lerp(p0, p1, t), lerp(p3, p2, t))
                elif overlay == "diagonal":
                    painter.drawLine(p0, p2)
                    painter.drawLine(p1, p3)

        if active_tool.points:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            circle_pen = QPen(QColor(255, 255, 255), 1.5)
            circle_pen.setCosmetic(True)
            
            pts = active_tool.points
            
            # 1. Draw connecting dashed lines first (with cosmetic pen)
            line_pen = QPen(QColor(255, 255, 255), 1.0, Qt.PenStyle.DashLine)
            line_pen.setCosmetic(True)
            painter.setPen(line_pen)
            for i in range(len(pts)):
                if i > 0 and not active_tool.pending_quad:
                    painter.drawLine(pts[i - 1], pts[i])
            
            # 2. Draw circles in pure screen space to keep sizes unified
            for p in pts:
                painter.save()
                screen_pos = painter.combinedTransform().map(QPointF(p))
                
                # Switch to pure screen space
                painter.setTransform(QTransform())
                painter.setBrush(QColor(255, 255, 255, 180))
                painter.setPen(circle_pen)
                
                # Unified radius in screen pixels
                r_pixels = 5.0
                painter.drawEllipse(screen_pos, r_pixels, r_pixels)
                painter.restore()
                
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_shapes_preview(painter, *, active_tool, tool_opts, fg_color, pan, zoom, ShapesTool):
    """The new-shape creation drag, rendered through the same ShapeSpec as
    the finished layer (fill, stroke style, alignment, radii — everything
    the options bar sets), so what you drag is exactly what you get."""
    if not isinstance(active_tool, ShapesTool):
        return
    try:
        sd = active_tool.preview_shape_data(tool_opts, fg_color)
        if not sd:
            return
        from core.shape_model import ShapeSpec
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        spec = ShapeSpec.from_dict(sd)
        spec.paint(painter)
        if tool_opts.get("shape_path_op", "new") != "new":
            # A path operation doesn't add pixels of its own — show the
            # outline it will combine with the selected shape.
            from PyQt6.QtGui import QPen as _QPen
            pen = _QPen(QColor(122, 162, 247), 0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(spec.outline())
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_gradient_preview(painter, *, active_tool, pan, zoom, GradientTool):
    if not isinstance(active_tool, GradientTool):
        return
    try:
        pg = active_tool.preview_gradient()
        if not pg:
            return
        p0, p1 = pg
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        
        pen = QPen(QColor(255, 255, 255, 200), 1.5)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(p0, p1)
        
        painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
        
        marker_pen = QPen(QColor(0, 0, 0, 160), 1.0)
        marker_pen.setCosmetic(True)
        painter.setPen(marker_pen)
        
        r = 3.0 / zoom
        painter.drawEllipse(QPointF(p0), r, r)
        painter.drawEllipse(QPointF(p1), r, r)
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_artboard_preview(painter, *, active_tool, pan, zoom):
    if not hasattr(active_tool, "artboard_preview"):
        return
    try:
        ar = active_tool.artboard_preview()
        if not ar:
            return
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        
        pen = QPen(QColor(100, 160, 255), 2.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255, 50))
        painter.drawRect(ar)
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_clone_stamp(painter, *, active_tool, pan, zoom):
    crosshair = getattr(active_tool, "_crosshair_pos", None)
    if crosshair is None:
        return
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    
    pen1 = QPen(QColor(0, 0, 0, 180), 3.0)
    pen1.setCosmetic(True)
    pen2 = QPen(QColor(255, 255, 255), 1.0)
    pen2.setCosmetic(True)
    
    r = 6.0 / zoom
    painter.setPen(pen1)
    painter.drawLine(QPointF(crosshair.x() - r, crosshair.y()), QPointF(crosshair.x() + r, crosshair.y()))
    painter.drawLine(QPointF(crosshair.x(), crosshair.y() - r), QPointF(crosshair.x(), crosshair.y() + r))
    painter.setPen(pen2)
    painter.drawLine(QPointF(crosshair.x() - r, crosshair.y()), QPointF(crosshair.x() + r, crosshair.y()))
    painter.drawLine(QPointF(crosshair.x(), crosshair.y() - r), QPointF(crosshair.x(), crosshair.y() + r))
    painter.restore()


def draw_measurements(painter, *, active_tool, pan, zoom, composite_cache, to_widget_fn):
    try:
        from tools.measure_tools import ColorSamplerTool, RulerTool
    except ImportError:
        return

    if isinstance(active_tool, ColorSamplerTool):
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        
        pen1 = QPen(QColor(0, 0, 0, 180), 3.0)
        pen1.setCosmetic(True)
        pen2 = QPen(QColor(255, 255, 255), 1.0)
        pen2.setCosmetic(True)
        
        r = 6.0 / zoom
        for pt in active_tool.markers:
            painter.setPen(pen1)
            painter.drawLine(QPointF(pt.x() - r, pt.y()), QPointF(pt.x() + r, pt.y()))
            painter.drawLine(QPointF(pt.x(), pt.y() - r), QPointF(pt.x(), pt.y() + r))
            painter.setPen(pen2)
            painter.drawLine(QPointF(pt.x() - r, pt.y()), QPointF(pt.x() + r, pt.y()))
            painter.drawLine(QPointF(pt.x(), pt.y() - r), QPointF(pt.x(), pt.y() + r))
        painter.restore()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for i, pt in enumerate(active_tool.markers):
            c = QColor(0, 0, 0, 0)
            if composite_cache and 0 <= pt.x() < composite_cache.width() and 0 <= pt.y() < composite_cache.height():
                c = composite_cache.pixelColor(pt)
            text = f" #{i + 1} R:{c.red()} G:{c.green()} B:{c.blue()} "
            wp = to_widget_fn(pt)
            tr_rect = painter.fontMetrics().boundingRect(text)
            tr_rect.moveTopLeft(QPoint(int(wp.x()) + 10, int(wp.y()) + 10))
            tr_rect.adjust(-4, -2, 4, 2)
            painter.fillRect(tr_rect, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(tr_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
    elif isinstance(active_tool, RulerTool):
        lines = active_tool.get_lines()
        if lines:
            painter.save()
            painter.translate(pan)
            painter.scale(zoom, zoom)
            
            pen1 = QPen(QColor(0, 0, 0, 180), 3.0)
            pen1.setCosmetic(True)
            pen2 = QPen(QColor(255, 255, 255), 1.0)
            pen2.setCosmetic(True)
            
            r = 3.0 / zoom
            for p1, p2 in lines:
                painter.setPen(pen1)
                painter.drawLine(p1, p2)
                painter.setPen(pen2)
                painter.drawLine(p1, p2)
                painter.drawEllipse(QPointF(p1), r, r)
                painter.drawEllipse(QPointF(p2), r, r)
            painter.restore()
            painter.save()
            for p1, p2 in lines:
                dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                if dx == 0 and dy == 0:
                    continue
                angle = math.degrees(math.atan2(-dy, dx))
                if angle < 0:
                    angle += 360
                text = f" L: {math.hypot(dx, dy):.1f} px   A: {angle:.1f}\u00b0 "
                wp = to_widget_fn(QPoint(int((p1.x() + p2.x()) / 2), int((p1.y() + p2.y()) / 2)))
                tr_rect = painter.fontMetrics().boundingRect(text)
                tr_rect.moveTopLeft(QPoint(int(wp.x()) + 10, int(wp.y()) + 10))
                tr_rect.adjust(-4, -2, 4, 2)
                painter.fillRect(tr_rect, QColor(0, 0, 0, 180))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(tr_rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()