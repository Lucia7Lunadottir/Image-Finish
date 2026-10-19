import math
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QImage, QTransform, QPen, QPolygonF
from tools.transform_base import TransformTool, bake_transform


class MoveTool(TransformTool):
    """Free transform: move, scale, rotate, skew/distort (Ctrl) by the
    bounding-box handles, or numerically from the options bar."""
    CONTEXT_MENU = "move"
    name = "Move"
    icon = "✋"
    shortcut = "V"
    modifies_canvas_on_move = True
    # Moves shapes, text and groups as they are — no rasterizing.
    PIXEL_OP = None
    AUTO_SELECT = True
    MOVES_CONTAINERS = True

    def __init__(self):
        self._hover_mode = None
        super().__init__()

    def _clear_tool_state(self):
        self._mode = None
        self._start_pos = None
        self._original_rect = None     # per-kind geometry rect (artboard, frame)
        self._total_transform = QTransform()
        self._base_transform = QTransform()
        self._start_poly = []
        self._smart_guides = []
        self._snap_targets = []

    def _reset_state(self):
        if getattr(self, "_target_layer", None) is not None:
            self._target_layer._live_edit_hidden = False
            self._target_layer._move_preview_source = None
        super()._reset_state()

    def _begin(self, layer, doc) -> bool:
        # VectorLayer renders shape_data/path_style live, regardless of what's
        # in .image, so hiding .image (_hide_layer) doesn't hide those layers;
        # the layer is told to contribute nothing to the composite for the
        # duration of the drag instead (_reset_state clears it).
        layer._live_edit_hidden = True
        if self._previews_in_composite(layer):
            layer._move_preview_source = lambda: self._total_transform
        if getattr(doc, "snap_to_layers", True):
            self._snap_targets = [r for r in (l.snap_rect() for l in doc.layers
                                              if l is not layer and l.visible)
                                  if not r.isEmpty()]
        if layer.is_container:
            self._linked_children = [{"layer": kid, "backup_offset": QPoint(kid.offset)}
                                     for kid in doc.descendants(layer)]
        link_id = getattr(layer, "link_id", None)
        if link_id:
            for l in doc.layers:
                if (l is not layer and getattr(l, "link_id", None) == link_id
                        and not any(k["layer"] is l for k in self._linked_children)):
                    self._linked_children.append({"layer": l, "backup_offset": QPoint(l.offset)})
        return super()._begin(layer, doc)

    def _lift_layer(self, layer, doc):
        if layer.is_container:
            self._bounds = layer.move_tool_container_bounds(self._linked_children)
            self._original_img = QImage(1, 1, QImage.Format.Format_ARGB32)
        else:
            self._bounds = layer.move_tool_bounds()
            self._original_img = layer.image.copy()
            self._hide_layer(layer)
        self._original_rect = self._bounds.toRect()
        self._original_offset = QPoint(layer.offset)

    def _restore_extra(self, layer):
        if self._original_rect is not None:
            layer.move_tool_cancel_extra(self._original_rect)

    def _reapply_extra(self, layer):
        if self._original_rect is not None:
            layer.move_tool_set_params_extra(self._total_transform, self._original_rect)

    def _after_floating_bake(self, doc):
        pass   # the selection already follows the piece; it stays

    def sharp_while_dragging(self) -> bool:
        layer = getattr(self, "_target_layer", None)
        return self.is_transforming and layer is not None and self._previews_in_composite(layer)

    @staticmethod
    def _previews_in_composite(layer) -> bool:
        """Shapes, Pen paths and text: the drag shows the layer re-rendered
        with the drag applied (the same geometry the commit computes), in
        its place in the layer stack and with its layer styles — not its
        baked bitmap stretched on top of everything."""
        return (not layer.is_container and hasattr(layer, "move_preview")
                and layer.has_live_content())

    def _get_handle_hit(self, pos: QPointF, opts: dict):
        if self._bounds.isEmpty(): return 'move'
        orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
        poly = self._total_transform.map(orig_poly)
        pts = [QPointF(poly[i]) for i in range(4)]
        handles = {
            'tl': pts[0],
            't':  (pts[0] + pts[1]) / 2.0,
            'tr': pts[1],
            'r':  (pts[1] + pts[2]) / 2.0,
            'br': pts[2],
            'b':  (pts[2] + pts[3]) / 2.0,
            'bl': pts[3],
            'l':  (pts[3] + pts[0]) / 2.0,
        }

        # Get the current zoom factor from options to calculate accurate screen distances
        current_zoom = max(0.01, opts.get("_zoom", 1.0))
        
        # Define accurate click distances in screen pixels directly
        # hit_dist_screen defines how close the mouse cursor needs to be to hit a handle square
        # rot_dist_screen defines the outer zone for the rotation cursor trigger
        hit_dist_screen = 14.0 
        rot_dist_screen = 28.0
        
        # Convert screen distances back to canvas coordinates to match the 'pos' parameter
        hit_dist = hit_dist_screen / current_zoom
        rot_dist = rot_dist_screen / current_zoom
        
        min_d = float('inf')
        best_h = None
        for name, pt in handles.items():
            d = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
            if d < min_d:
                min_d = d
                best_h = name
                
        if min_d <= hit_dist: return best_h
        if poly.containsPoint(pos, Qt.FillRule.OddEvenFill): return 'move'
        if min_d <= rot_dist: return 'rotate'
        return 'move'

    def on_press(self, pos, doc, fg, bg, opts):
        self._auto_select(pos, doc, opts)
        layer = doc.get_active_layer()
        if not self._can_transform(layer, doc):
            return
        if not self.is_transforming and not self._begin(layer, doc):
            return
        self._base_transform = QTransform(self._total_transform)
        self._start_pos = QPointF(pos)
        orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
        mapped = self._base_transform.map(orig_poly)
        self._start_poly = [QPointF(mapped[i]) for i in range(4)]
        self._mode = self._get_handle_hit(QPointF(pos), opts)

    def on_move(self, pos, doc, fg, bg, opts):
        if not self._mode or not self.is_transforming: return
        layer = self._target_layer
        if not layer: return
        
        pos_f = QPointF(pos)
        delta = pos_f - self._start_pos
        pts = [QPointF(p) for p in self._start_poly]
        
        ctrl = opts.get("_ctrl", False)
        shift = opts.get("_shift", False)
        alt = opts.get("_alt", False)

        corner_indices = {'tl': 0, 'tr': 1, 'br': 2, 'bl': 3}
        if (getattr(layer, "_move_tool_uniform_scale_only", False)
                and self._mode in corner_indices and not ctrl):
            # Locks aspect ratio, same as Shift, in the plain (non-Ctrl)
            # corner-drag branch below. The Ctrl-held branch's own "shift"
            # means something different there (constrain to one edge's
            # direction, not lock aspect) — deliberately left alone, out
            # of scope for "forbid free stretching" on the primary drag.
            shift = True

        edge_indices = {'t': (0,1), 'r': (1,2), 'b': (2,3), 'l': (3,0)}
        
        if self._mode == 'move':
            dx, dy = delta.x(), delta.y()
            orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
            br = self._base_transform.map(orig_poly).boundingRect()
            new_br = br.translated(dx, dy)
            
            self._smart_guides = []
            
            if not opts.get("_ctrl", False) and getattr(doc, "snap_enabled", True):
                snap_threshold = 8 / max(0.01, opts.get("_zoom", 1.0))
                best_dx, best_dy = dx, dy
                min_dx, min_dy = float('inf'), float('inf')
                
                txs, tys = [], []
                if getattr(doc, "snap_to_bounds", True):
                    txs.extend([0, doc.width / 2.0, doc.width]); tys.extend([0, doc.height / 2.0, doc.height])
                if getattr(doc, "snap_to_guides", True) and getattr(doc, "show_guides", True):
                    txs.extend(getattr(doc, "guides_v", [])); tys.extend(getattr(doc, "guides_h", []))
                if getattr(doc, "snap_to_grid", False) and getattr(doc, "show_grid", False):
                    gs = getattr(doc, "grid_size", 50)
                    gx1, gx2 = int(new_br.left() // gs), int(new_br.right() // gs) + 1
                    gy1, gy2 = int(new_br.top() // gs), int(new_br.bottom() // gs) + 1
                    txs.extend([i * gs for i in range(gx1, gx2+1)])
                    tys.extend([i * gs for i in range(gy1, gy2+1)])
                if getattr(doc, "snap_to_layers", True) and hasattr(self, "_snap_targets"):
                    for lr in self._snap_targets:
                        txs.extend([lr.left(), lr.center().x(), lr.right()])
                        tys.extend([lr.top(), lr.center().y(), lr.bottom()])
                            
                txs = list(set(txs)); tys = list(set(tys))
                pxs = [new_br.left(), new_br.center().x(), new_br.right()]
                pys = [new_br.top(), new_br.center().y(), new_br.bottom()]
                
                snapped_x, snapped_y = None, None
                for tx in txs:
                    for px in pxs:
                        if abs(tx - px) < snap_threshold and abs(tx - px) < min_dx:
                            min_dx, best_dx, snapped_x = abs(tx - px), dx + (tx - px), tx
                for ty in tys:
                    for py in pys:
                        if abs(ty - py) < snap_threshold and abs(ty - py) < min_dy:
                            min_dy, best_dy, snapped_y = abs(ty - py), dy + (ty - py), ty
                            
                delta = QPointF(best_dx, best_dy)
                if snapped_x is not None: self._smart_guides.append(('v', snapped_x))
                if snapped_y is not None: self._smart_guides.append(('h', snapped_y))
                
            for i in range(4): pts[i] = self._start_poly[i] + delta
            
        elif self._mode == 'rotate':
            center = self._base_transform.map(self._bounds.center())
            a1 = math.atan2(self._start_pos.y() - center.y(), self._start_pos.x() - center.x())
            a2 = math.atan2(pos_f.y() - center.y(), pos_f.x() - center.x())
            da = math.degrees(a2 - a1)
            if shift:
                da = round(da / 15.0) * 15.0
            t = QTransform().translate(center.x(), center.y()).rotate(da).translate(-center.x(), -center.y())
            pts = [t.map(p) for p in self._start_poly]
            
        elif ctrl:
            if self._mode in corner_indices:
                idx = corner_indices[self._mode]
                opp_idx = (idx + 2) % 4
                
                if alt and shift:
                    e1 = pts[(idx+1)%4] - pts[idx]
                    e2 = pts[(idx+3)%4] - pts[idx]
                    l1 = math.hypot(e1.x(), e1.y())
                    l2 = math.hypot(e2.x(), e2.y())
                    n1 = QPointF(e1.x()/l1, e1.y()/l1) if l1 else QPointF(1,0)
                    n2 = QPointF(e2.x()/l2, e2.y()/l2) if l2 else QPointF(0,1)
                    
                    dot1 = abs(delta.x()*n1.x() + delta.y()*n1.y())
                    dot2 = abs(delta.x()*n2.x() + delta.y()*n2.y())
                    if dot1 > dot2:
                        proj = delta.x()*n1.x() + delta.y()*n1.y()
                        n = n1
                        opp_adj = (idx+1)%4
                    else:
                        proj = delta.x()*n2.x() + delta.y()*n2.y()
                        n = n2
                        opp_adj = (idx+3)%4
                        
                    move_vec = QPointF(n.x()*proj, n.y()*proj)
                    pts[idx] = pts[idx] + move_vec
                    pts[opp_adj] = pts[opp_adj] - move_vec

                elif shift:
                    e1 = pts[(idx+1)%4] - pts[idx]
                    e2 = pts[(idx+3)%4] - pts[idx]
                    l1 = math.hypot(e1.x(), e1.y())
                    l2 = math.hypot(e2.x(), e2.y())
                    n1 = QPointF(e1.x()/l1, e1.y()/l1) if l1 else QPointF(1,0)
                    n2 = QPointF(e2.x()/l2, e2.y()/l2) if l2 else QPointF(0,1)
                    
                    dot1 = abs(delta.x()*n1.x() + delta.y()*n1.y())
                    dot2 = abs(delta.x()*n2.x() + delta.y()*n2.y())
                    if dot1 > dot2:
                        proj = delta.x()*n1.x() + delta.y()*n1.y()
                        n = n1
                    else:
                        proj = delta.x()*n2.x() + delta.y()*n2.y()
                        n = n2
                        
                    move_vec = QPointF(n.x()*proj, n.y()*proj)
                    pts[idx] = pts[idx] + move_vec

                elif alt:
                    pts[idx] = pts[idx] + delta
                    pts[opp_idx] = pts[opp_idx] - delta
                else:
                    pts[idx] = pts[idx] + delta
                    
            elif self._mode in edge_indices:
                i1, i2 = edge_indices[self._mode]
                opp1, opp2 = (i1+2)%4, (i2+2)%4
                
                if shift:
                    edge_vec = pts[i2] - pts[i1]
                    l = math.hypot(edge_vec.x(), edge_vec.y())
                    n = QPointF(edge_vec.x()/l, edge_vec.y()/l) if l else QPointF(1,0)
                    proj = delta.x()*n.x() + delta.y()*n.y()
                    move_vec = QPointF(n.x()*proj, n.y()*proj)
                else:
                    move_vec = delta
                    
                if alt:
                    pts[i1] = pts[i1] + move_vec
                    pts[i2] = pts[i2] + move_vec
                    pts[opp1] = pts[opp1] - move_vec
                    pts[opp2] = pts[opp2] - move_vec
                else:
                    pts[i1] = pts[i1] + move_vec
                    pts[i2] = pts[i2] + move_vec
                    
        else:
            inv_base, ok = self._base_transform.inverted()
            if ok:
                local_pos = inv_base.map(pos_f)
                
                b = self._bounds
                local_pts = {
                    'tl': b.topLeft(), 't': QPointF(b.center().x(), b.top()), 'tr': b.topRight(),
                    'r':  QPointF(b.right(), b.center().y()), 'br': b.bottomRight(),
                    'b':  QPointF(b.center().x(), b.bottom()), 'bl': b.bottomLeft(),
                    'l':  QPointF(b.left(), b.center().y())
                }
                anchors = {
                    'br': ('tl', 'br'), 'tl': ('br', 'tl'),
                    'tr': ('bl', 'tr'), 'bl': ('tr', 'bl'),
                    'r':  ('l', 'r'),   'l':  ('r', 'l'),
                    'b':  ('t', 'b'),   't':  ('b', 't'),
                }
                
                if self._mode in anchors:
                    anchor_name, drag_name = anchors[self._mode]
                    anchor_pt = local_pts[anchor_name]
                    drag_pt = local_pts[drag_name]
                    
                    if alt:
                        anchor_pt = b.center()
            
                    v_orig_x = drag_pt.x() - anchor_pt.x()
                    v_orig_y = drag_pt.y() - anchor_pt.y()
                    v_cur_x = local_pos.x() - anchor_pt.x()
                    v_cur_y = local_pos.y() - anchor_pt.y()
            
                    sx = v_cur_x / v_orig_x if abs(v_orig_x) > 0.001 else 1.0
                    sy = v_cur_y / v_orig_y if abs(v_orig_y) > 0.001 else 1.0
            
                    uniform = getattr(layer, "_move_tool_uniform_scale_only", False)
                    if self._mode in ('r', 'l'):
                        sy = sx if uniform else 1.0
                    if self._mode in ('t', 'b'):
                        sx = sy if uniform else 1.0
                    
                    if shift and self._mode in corner_indices:
                        s = max(abs(sx), abs(sy))
                        sx = s * (1 if sx >= 0 else -1)
                        sy = s * (1 if sy >= 0 else -1)
                
                    scale_t = QTransform().translate(anchor_pt.x(), anchor_pt.y()).scale(sx, sy).translate(-anchor_pt.x(), -anchor_pt.y())
                    new_local_poly = scale_t.map(QPolygonF([b.topLeft(), b.topRight(), b.bottomRight(), b.bottomLeft()]))
                pts = [self._base_transform.map(QPointF(new_local_poly[i])) for i in range(4)]

        orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
        new_poly = QPolygonF(pts)
        
        final_t = QTransform()
        ok = QTransform.quadToQuad(orig_poly, new_poly, final_t)
        if ok:
            self._total_transform = final_t
            
            # Same per-kind geometry as the numeric Transform panel
            # (set_transform_params): artboard / frame rects follow the drag.
            handled = layer.move_tool_set_params_extra(final_t, self._original_rect)
            if not handled and self._is_floating and self._sel_origin:
                doc.selection = final_t.map(self._sel_origin)
                
            if self._mode == 'move':
                self._set_children_offset(QPoint(int(final_t.dx()), int(final_t.dy())))

    def on_hover(self, pos: QPoint, doc, fg, bg, opts):
        if self.is_transforming:
            self._hover_mode = self._get_handle_hit(QPointF(pos), opts)
        else:
            self._hover_mode = None

    def on_release(self, pos, doc, fg, bg, opts):
        self._mode = None
        self._start_poly = []
        self._base_transform = QTransform()

    def floating_preview(self):
        if not self.is_transforming:
            return None
        layer = self._target_layer
        if layer is not None and self._previews_in_composite(layer):
            return None             # the layer itself composites as moved
        if self._original_img is not None:
            return ("transform", self._original_img, self._original_offset, self._total_transform)
        return None

    def draw_overlays(self, painter: QPainter, pw: float, doc):
        if not self.is_transforming: return
        
        # 1. Draw smart guides if active
        if hasattr(self, "_smart_guides") and self._smart_guides:
            painter.save()
            # Set smart guides pen as cosmetic so they don't scale up or down
            guide_pen = QPen(QColor(255, 0, 255, 200), 1.0)
            guide_pen.setCosmetic(True)
            painter.setPen(guide_pen)
            for gtype, val in self._smart_guides:
                if gtype == 'v': painter.drawLine(QPointF(val, -10000), QPointF(val, 10000))
                elif gtype == 'h': painter.drawLine(QPointF(-10000, val), QPointF(10000, val))
            painter.restore()
            
        orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
        poly = self._total_transform.map(orig_poly)
        pts = [QPointF(poly[i]) for i in range(4)]
            
        painter.save()
        
        # 2. Configure cosmetic pens for the bounding box
        outer_pen = QPen(QColor(0, 0, 0, 180), 1.0)
        outer_pen.setCosmetic(True)
        painter.setPen(outer_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)
        
        inner_pen = QPen(QColor(255, 255, 255, 200), 1.0, Qt.PenStyle.DashLine)
        inner_pen.setCosmetic(True)
        painter.setPen(inner_pen)
        painter.drawPolygon(poly)
        
        # 3. Draw transform handles with uniform screen size
        painter.setBrush(QColor(255, 255, 255))
        
        handle_border_pen = QPen(QColor(0, 0, 0), 1.0)
        handle_border_pen.setCosmetic(True)
        painter.setPen(handle_border_pen)
        
        handles = [
            pts[0], (pts[0]+pts[1])/2, pts[1], (pts[1]+pts[2])/2,
            pts[2], (pts[2]+pts[3])/2, pts[3], (pts[3]+pts[0])/2
        ]
        
        for pt in handles:
            # 1. Save the current painter state before geometry resetting
            painter.save()
            
            # 2. Get the exact screen (widget) coordinates for the handle center
            # combinedTransform combines pan, zoom and total_transform matrices
            screen_pos = painter.combinedTransform().map(pt)
            
            # 3. Completely reset the painter matrix to screen pixel space
            painter.setTransform(QTransform())
            
            # 4. Set the fixed size in actual screen pixels (e.g. 7x7 pixels window)
            s_pixels = 5
            handle_rect = QRectF(
                screen_pos.x() - s_pixels,
                screen_pos.y() - s_pixels,
                s_pixels * 2.0,
                s_pixels * 2.0
            )
            
            # 5. Draw the handle in pure screen space
            painter.drawRect(handle_rect)
            
            # 6. Restore the painter transformation for the next points
            painter.restore()
            
        painter.restore()

    def _bake(self, doc, layer):
        final_t = self._total_transform
        self._set_children_offset(QPoint(int(final_t.dx()), int(final_t.dy())))
        if layer.move_tool_apply_extra(doc, final_t, self._original_rect, self._original_img):
            return
        img, offset = bake_transform(self._original_img, self._original_offset, final_t)
        self._place(layer, img, offset)

    def get_transform_params(self):
        if not self.is_transforming: return None
        from core.layer import decompose_transform
        t = self._total_transform
        scale_x, scale_y, angle_deg = decompose_transform(t)

        orig_poly = QPolygonF([self._bounds.topLeft(), self._bounds.topRight(), self._bounds.bottomRight(), self._bounds.bottomLeft()])
        poly = t.map(orig_poly)
        cx = sum(p.x() for p in poly) / 4.0
        cy = sum(p.y() for p in poly) / 4.0

        return {'x': cx, 'y': cy, 'w': scale_x * 100.0, 'h': scale_y * 100.0, 'angle': angle_deg}
        
    def set_transform_params(self, doc, params: dict):
        if not self.is_transforming: return
        cx, cy = params.get('x', self._bounds.center().x()), params.get('y', self._bounds.center().y())
        w_pct, h_pct = params.get('w', 100.0) / 100.0, params.get('h', 100.0) / 100.0
        if getattr(self._target_layer, "_move_tool_uniform_scale_only", False):
            # Text scales by font size: one factor — whichever field the
            # user actually changed.
            k = w_pct if abs(w_pct - 1.0) >= abs(h_pct - 1.0) else h_pct
            w_pct = h_pct = k
        angle = params.get('angle', 0.0)
        
        t = QTransform()
        t.translate(cx, cy)
        t.rotate(angle)
        t.scale(w_pct, h_pct)
        t.translate(-self._bounds.center().x(), -self._bounds.center().y())
        self._set_total(doc, t)

    @property
    def can_flip(self) -> bool:
        """Text scales by font size only — it has no mirrored form."""
        return not getattr(self._target_layer, "_move_tool_uniform_scale_only", False)

    def rotate_by(self, doc, degrees: float):
        """Rotate the open transform about its centre (Rotate 90°/180°)."""
        self._compose(doc, QTransform().rotate(degrees))

    def flip(self, doc, horizontal: bool):
        if self.can_flip:
            self._compose(doc, QTransform().scale(-1, 1) if horizontal else QTransform().scale(1, -1))

    def _compose(self, doc, local: QTransform):
        if not self.is_transforming:
            return
        c = self._total_transform.map(self._bounds.center())
        about = QTransform().translate(-c.x(), -c.y()) * local * QTransform().translate(c.x(), c.y())
        self._set_total(doc, self._total_transform * about)

    def _set_total(self, doc, t: QTransform):
        """The transform the session now shows, with everything that
        follows it live: kind geometry, the selection outline, children."""
        self._total_transform = t
        handled = self._target_layer.move_tool_set_params_extra(t, self._original_rect)
        if not handled and self._is_floating and self._sel_origin:
            doc.selection = t.map(self._sel_origin)
        self._set_children_offset(QPoint(int(t.dx()), int(t.dy())))

    def cursor(self):
        if not self.is_transforming: return Qt.CursorShape.SizeAllCursor
        m = getattr(self, "_hover_mode", None)
        if m == 'rotate': return Qt.CursorShape.CrossCursor
        if m in ('tl', 'br'): return Qt.CursorShape.SizeFDiagCursor
        if m in ('tr', 'bl'): return Qt.CursorShape.SizeBDiagCursor
        if m in ('l', 'r'): return Qt.CursorShape.SizeHorCursor
        if m in ('t', 'b'): return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeAllCursor
