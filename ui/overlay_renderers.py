"""Overlay rendering functions extracted from CanvasWidget._paint_canvas_content().

Each function takes a QPainter and the relevant state, draws one overlay,
and returns. All functions call painter.save()/restore() internally."""

import math

from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QPainterPath,
                         QPolygon, QPolygonF, QTransform)

from core.app_logging import get_logger

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
    painter.setPen(QPen(QColor(0, 150, 255, 200), pw))
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
        painter.setPen(QPen(QColor(0, 150, 255, 200), pw))
    painter.restore()


def draw_symmetry_axes(painter, *, doc, pan, zoom, tool_opts, tool_name, brush_tools):
    mirror_x = bool(tool_opts.get("brush_mirror_x", False))
    mirror_y = bool(tool_opts.get("brush_mirror_y", False))
    if tool_name not in brush_tools or not (mirror_x or mirror_y):
        return
    cx_pct = float(tool_opts.get("brush_mirror_cx", 0.5))
    cy_pct = float(tool_opts.get("brush_mirror_cy", 0.5))
    painter.save()
    painter.translate(pan)
    painter.scale(zoom, zoom)
    pw = 1.0 / zoom
    pen1 = QPen(QColor(0, 0, 0, 100), pw * 3)
    pen2 = QPen(QColor(100, 200, 255, 180), pw)
    pen2.setStyle(Qt.PenStyle.DashLine)
    w, h = doc.width, doc.height
    sym_x = w * cx_pct
    sym_y = h * cy_pct
    if mirror_x:
        painter.setPen(pen1); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
        painter.setPen(pen2); painter.drawLine(QPointF(sym_x, 0), QPointF(sym_x, h))
    if mirror_y:
        painter.setPen(pen1); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
        painter.setPen(pen2); painter.drawLine(QPointF(0, sym_y), QPointF(w, sym_y))
    r_handle = max(4.0, 6.0 / zoom)
    painter.setPen(QPen(QColor(0, 0, 0, 150), max(1.0, 2.0 / zoom)))
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
    pw = 1.0 / zoom
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(QColor(0, 0, 0, 160), pw * 1.5)
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setDashOffset(march_offset)
    painter.setPen(pen)
    painter.drawPath(sel)
    pen2 = QPen(QColor(255, 255, 255, 220), pw)
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
                pw = 1.0 / zoom
                pen = QPen(QColor(220, 60, 60), pw)
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
                pw = 1.0 / zoom
                pen = QPen(QColor(220, 60, 60), pw)
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
        pw = 1.0 / zoom
        pen1 = QPen(QColor(0, 0, 0), pw)
        pen2 = QPen(QColor(255, 255, 255), pw)
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

        painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / zoom)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(cr)

        overlay = tool_opts.get("crop_overlay", "thirds")
        if overlay != "none":
            painter.setPen(QPen(QColor(255, 255, 255, 150), 1.0 / zoom, Qt.PenStyle.DashLine))
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

        painter.setBrush(QColor(255, 255, 255))
        pw = 1.0 / zoom
        painter.setPen(QPen(QColor(0, 0, 0), pw))
        s = 3 * pw
        pts = [cr.topLeft(), QPointF(cr.center().x(), cr.top()), cr.topRight(),
               QPointF(cr.right(), cr.center().y()), cr.bottomRight(),
               QPointF(cr.center().x(), cr.bottom()), cr.bottomLeft(),
               QPointF(cr.left(), cr.center().y())]
        for pt in pts:
            painter.drawRect(QRectF(pt.x() - s, pt.y() - s, s * 2, s * 2))
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

            painter.setPen(QPen(QColor(255, 200, 0), max(1, 1 / zoom)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(quad)

            overlay = tool_opts.get("crop_overlay", "thirds")
            if overlay != "none" and len(quad) == 4:
                painter.setPen(QPen(QColor(255, 255, 255, 150), 1.0 / zoom, Qt.PenStyle.DashLine))
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
            pen = QPen(QColor(255, 255, 255), max(1.0, 1.5 / zoom))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 255, 255, 180))
            pts = active_tool.points
            r = max(4.0, 6.0 / zoom)
            for i, p in enumerate(pts):
                painter.drawEllipse(QPointF(p), r, r)
                if i > 0 and not active_tool.pending_quad:
                    painter.drawLine(pts[i - 1], pts[i])
        painter.restore()
    except Exception:
        logger.debug("Overlay draw failed", exc_info=True)


def draw_shapes_preview(painter, *, active_tool, tool_opts, fg_color, pan, zoom, ShapesTool):
    if not isinstance(active_tool, ShapesTool):
        return
    try:
        ps = active_tool.preview_shape()
        if not ps:
            return
        painter.save()
        painter.translate(pan)
        painter.scale(zoom, zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        stroke = max(1, int(tool_opts.get("brush_size", 3)))
        shape_color = tool_opts.get("shape_color", fg_color)
        pen = QPen(shape_color, stroke)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        shape = ps["shape"]
        rect = ps["rect"]
        angle = ps.get("angle", 0)
        if angle and shape != "line":
            cx, cy = rect.center().x(), rect.center().y()
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.translate(-cx, -cy)
        if shape.startswith("custom:"):
            custom_path = ShapesTool._load_custom_shape(shape[7:])
            if custom_path and not custom_path.isEmpty():
                br = custom_path.boundingRect()
                if not br.isEmpty():
                    sx = rect.width() / br.width()
                    sy = rect.height() / br.height()
                    painter.save()
                    painter.setTransform(
                        QTransform().translate(rect.left(), rect.top())
                        .scale(sx, sy).translate(-br.left(), -br.top()), combine=True)
                    painter.drawPath(custom_path)
                    painter.restore()
        elif shape == "ellipse":
            painter.drawEllipse(rect)
        elif shape == "triangle":
            painter.drawPolygon(QPolygon([
                QPoint(rect.center().x(), rect.top()),
                QPoint(rect.left(), rect.bottom()),
                QPoint(rect.right(), rect.bottom()),
            ]))
        elif shape == "polygon":
            painter.drawPolygon(ShapesTool._polygon_points(rect, ps["sides"]))
        elif shape == "line":
            painter.drawLine(ps["start"], ps["end"])
        elif shape == "star":
            painter.drawPolygon(ShapesTool._star_points(rect))
        elif shape == "arrow":
            painter.drawPath(ShapesTool._arrow_path(rect))
        elif shape == "cross":
            painter.drawPath(ShapesTool._cross_path(rect))
        else:
            painter.drawRect(rect)
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
        pw = 1.0 / zoom
        pen = QPen(QColor(255, 255, 255, 200), pw * 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(p0, p1)
        painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
        painter.setPen(QPen(QColor(0, 0, 0, 160), pw))
        r = pw * 3
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
        painter.setPen(QPen(QColor(100, 160, 255), max(1.5, 2.0 / zoom)))
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
    pw = 1.0 / zoom
    pen1 = QPen(QColor(0, 0, 0, 180), pw * 3)
    pen2 = QPen(QColor(255, 255, 255, 220), pw)
    r = 6 * pw
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
        pw = 1.0 / zoom
        for pt in active_tool.markers:
            painter.setPen(QPen(QColor(0, 0, 0, 180), pw * 3))
            painter.drawLine(QPointF(pt.x() - 6 * pw, pt.y()), QPointF(pt.x() + 6 * pw, pt.y()))
            painter.drawLine(QPointF(pt.x(), pt.y() - 6 * pw), QPointF(pt.x(), pt.y() + 6 * pw))
            painter.setPen(QPen(QColor(255, 255, 255), pw))
            painter.drawLine(QPointF(pt.x() - 6 * pw, pt.y()), QPointF(pt.x() + 6 * pw, pt.y()))
            painter.drawLine(QPointF(pt.x(), pt.y() - 6 * pw), QPointF(pt.x(), pt.y() + 6 * pw))
        painter.restore()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for i, pt in enumerate(active_tool.markers):
            c = QColor(0, 0, 0, 0)
            if composite_cache and 0 <= pt.x() < composite_cache.width() and 0 <= pt.y() < composite_cache.height():
                c = QColor(composite_cache.pixel(pt))
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
            pw = 1.0 / zoom
            for p1, p2 in lines:
                painter.setPen(QPen(QColor(0, 0, 0, 180), pw * 3))
                painter.drawLine(p1, p2)
                painter.setPen(QPen(QColor(255, 255, 255), pw))
                painter.drawLine(p1, p2)
                painter.drawEllipse(QPointF(p1), 3 * pw, 3 * pw)
                painter.drawEllipse(QPointF(p2), 3 * pw, 3 * pw)
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
