"""Shared lifecycle of the tools that lift pixels off the active layer,
reshape them on the canvas and bake the result on commit — Move, Warp,
Puppet Warp, Perspective Warp.

A transform session is: first press lifts the content (the selected piece,
cut out of the layer — or the whole layer, which is hidden meanwhile);
drags reshape a preview; then exactly one of
  * `apply_transform(doc)`  — bake into the layer,
  * `cancel_transform(doc)` — put everything back,
ends it. While it runs the window can take a clean history snapshot of the
pre-transform document via `with tool.original_state(doc): ...`.

Subclasses implement the shape of the transform (`_bake`, overlays,
mouse handling) and hook their own extra state into `_clear_tool_state`.
"""
import math
from contextlib import contextmanager

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPolygonF, QTransform

from tools.base_tool import BaseTool


def bake_transform(img: QImage, offset: QPoint, t: QTransform) -> tuple[QImage, QPoint]:
    """`img` placed at document `offset`, mapped through document-space
    transform `t` — returns the resampled image and its new offset."""
    if t.isIdentity():
        return img, QPoint(offset)
    doc_t = QTransform().translate(offset.x(), offset.y()) * t
    mapped = doc_t.mapRect(QRectF(0, 0, img.width(), img.height()))
    w, h = int(math.ceil(mapped.width())), int(math.ceil(mapped.height()))
    if w <= 0 or h <= 0:
        return img, QPoint(offset)
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setTransform(doc_t * QTransform().translate(-mapped.left(), -mapped.top()))
    p.drawImage(0, 0, img)
    p.end()
    return out, QPoint(int(mapped.left()), int(mapped.top()))


class TransformTool(BaseTool):
    PIXEL_OP = "transform"
    # Clicking picks the topmost layer under the cursor first (the Move
    # options' "Auto-select layer" checkbox).
    AUTO_SELECT = False
    # Groups and artboards can be the target (their children follow).
    MOVES_CONTAINERS = False

    def __init__(self):
        super().__init__()
        self._reset_state()

    # ------------------------------------------------------------ session
    def _clear_session(self):
        self._doc = None
        self._target_layer = None
        self._layer_backup = None       # layer.image before the session
        self._offset_backup = None
        self._original_img = None       # the lifted pixels
        self._original_offset = None    # their document-space position
        self._sel_origin = None         # the selection they were cut with
        self._is_floating = False       # a selected piece, not the whole layer
        self._bounds = QRectF()
        self._linked_children = []      # [{"layer", "backup_offset"}], moved along

    def _clear_tool_state(self):
        """Subclass hook: drop the tool's own per-session state."""

    def _reset_state(self):
        self.is_transforming = False
        self._clear_session()
        self._clear_tool_state()

    @property
    def document(self):
        """The document the running session belongs to (None when idle)."""
        return self._doc if self.is_transforming else None

    @property
    def is_floating(self) -> bool:
        return self.is_transforming and self._is_floating

    def _auto_select(self, pos, doc, opts):
        if self.is_transforming or not (self.AUTO_SELECT and opts.get("move_auto_select", False)):
            return
        for i in range(len(doc.layers) - 1, -1, -1):
            layer = doc.layers[i]
            if layer.visible and not layer.locked and layer.hit_test(pos):
                doc.active_layer_index = i
                return

    def _can_transform(self, layer, doc) -> bool:
        if layer is None or layer.locked:
            return False
        has_sel = doc.selection is not None and not doc.selection.isEmpty()
        if getattr(layer, "lock_position", False) and not has_sel:
            return False
        if getattr(layer, "lock_pixels", False) and has_sel:
            return False
        return self.MOVES_CONTAINERS or not layer.is_container

    def _begin(self, layer, doc) -> bool:
        """Lift the content to transform. False (nothing started) when the
        selection misses the layer."""
        self._doc = doc
        self._target_layer = layer
        self._layer_backup = layer.image.copy()
        self._offset_backup = QPoint(layer.offset)
        sel = doc.selection
        if sel is not None and not sel.isEmpty() and not layer.is_container:
            from tools.tool_utils import cut_floating_selection
            img, offset, sel_origin, ok = cut_floating_selection(layer, sel)
            if not ok:
                self._reset_state()
                return False
            self._is_floating = True
            self._bounds = sel.boundingRect()
            self._original_img, self._original_offset, self._sel_origin = img, offset, sel_origin
        else:
            self._is_floating = False
            self._lift_layer(layer, doc)
        self.is_transforming = True
        return True

    def _lift_layer(self, layer, doc):
        """Whole-layer session: take the opaque part, hide the layer."""
        from core.document import Document
        br = Document._nontransparent_bounds(layer.image)
        if br.isEmpty():
            br = QRect(0, 0, layer.width() or 100, layer.height() or 100)
        self._bounds = QRectF(br).translated(QPointF(layer.offset))
        self._original_img = layer.image.copy(br)
        self._original_offset = layer.offset + br.topLeft()
        self._hide_layer(layer)

    @staticmethod
    def _hide_layer(layer):
        layer.image = QImage(1, 1, QImage.Format.Format_ARGB32)
        layer.image.fill(Qt.GlobalColor.transparent)

    # ------------------------------------------------------------ geometry hooks
    def _restore_extra(self, layer):
        """Undo live per-kind geometry (artboard / frame rects) — Move only."""

    def _reapply_extra(self, layer):
        """Re-apply what `_restore_extra` undid."""

    def _set_children_offset(self, delta: QPoint | None):
        """Linked children follow the move by `delta`; None = back home."""
        for kid in self._linked_children:
            kid["layer"].offset = kid["backup_offset"] + delta if delta is not None else kid["backup_offset"]

    # ------------------------------------------------------------ end of session
    @contextmanager
    def original_state(self, doc):
        """The document as it was before the session, for the duration of
        the block (a history snapshot), then back to the live session."""
        layer = self._target_layer
        if not self.is_transforming or layer is None or self._layer_backup is None:
            yield
            return
        live = (layer.image, layer.offset, doc.selection,
                [(k["layer"], QPoint(k["layer"].offset)) for k in self._linked_children])
        self._set_children_offset(None)
        self._restore_extra(layer)
        layer.image, layer.offset = self._layer_backup, self._offset_backup
        if self._sel_origin is not None:
            doc.selection = self._sel_origin
        try:
            yield
        finally:
            layer.image, layer.offset, doc.selection = live[0], live[1], live[2]
            self._reapply_extra(layer)
            for kid, offset in live[3]:
                kid.offset = offset

    def apply_transform(self, doc):
        if not self.is_transforming:
            return
        if self._target_layer is not None:
            self._bake(doc, self._target_layer)
        if self._is_floating:
            self._after_floating_bake(doc)
        self._reset_state()

    def _bake(self, doc, layer):
        raise NotImplementedError

    def _after_floating_bake(self, doc):
        doc.selection = None

    def _place(self, layer, img: QImage, offset: QPoint):
        """Put the baked result into the layer: a floating piece is drawn
        back over the (cut) layer, a whole-layer result replaces it."""
        if self._is_floating:
            p = QPainter(layer.image)
            p.drawImage(offset - layer.offset, img)
            p.end()
        else:
            layer.image = img
            layer.offset = QPoint(offset)

    def cancel_transform(self, doc):
        if not self.is_transforming:
            return
        layer = self._target_layer
        if layer is not None and self._layer_backup is not None:
            layer.image = self._layer_backup
            layer.offset = self._offset_backup
            self._restore_extra(layer)
            if self._sel_origin is not None:
                doc.selection = self._sel_origin
        self._set_children_offset(None)
        self._reset_state()

    def needs_history_push(self):
        # The window snapshots the session as one step on commit.
        return False


class MeshWarpTool(TransformTool):
    """Warp and Puppet Warp: a mesh over the lifted pixels whose vertices
    come from `_calc_grid`; previewed and baked as textured triangles."""

    _PROXY_MAX = 600   # longest side of the low-res copy shown while dragging

    def _clear_tool_state(self):
        self._patches = []
        self._fast_mode = False
        self._proxy_img = None
        self._drag_idx = None

    def _begin(self, layer, doc) -> bool:
        if not super()._begin(layer, doc):
            return False
        img = self._original_img
        longest = max(img.width(), img.height())
        if longest > self._PROXY_MAX:
            k = self._PROXY_MAX / longest
            self._proxy_img = img.scaled(int(img.width() * k), int(img.height() * k),
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.FastTransformation)
        else:
            self._proxy_img = img
        return True

    def _calc_grid(self, steps_u: int, steps_v: int):
        """(xs, ys) document positions of a steps_v × steps_u vertex grid."""
        raise NotImplementedError

    def _update_preview(self, fast=False):
        if self._original_img is None:
            return
        self._fast_mode = fast
        steps = 8 if fast else 16
        xs, ys = self._calc_grid(steps + 1, steps + 1)
        src = self._proxy_img if fast else self._original_img
        w, h = src.width(), src.height()
        patches = []
        for i in range(steps):
            for j in range(steps):
                u0, v0, u1, v1 = j / steps, i / steps, (j + 1) / steps, (i + 1) / steps
                patches.append((
                    QPointF(u0 * w, v0 * h), QPointF(u1 * w, v0 * h),
                    QPointF(u1 * w, v1 * h), QPointF(u0 * w, v1 * h),
                    QPointF(xs[i, j], ys[i, j]), QPointF(xs[i, j + 1], ys[i, j + 1]),
                    QPointF(xs[i + 1, j + 1], ys[i + 1, j + 1]), QPointF(xs[i + 1, j], ys[i + 1, j]),
                ))
        self._patches = patches

    def on_release(self, pos, doc, fg, bg, opts):
        if self._drag_idx is not None:
            self._drag_idx = None
            self._update_preview(fast=False)

    def floating_preview(self):
        if self.is_transforming and self._patches:
            src = self._proxy_img if self._fast_mode else self._original_img
            return ("warp", src, self._patches, self._fast_mode)
        return None

    def _bake(self, doc, layer):
        self._update_preview(fast=False)
        if not self._patches:
            return
        xs, ys = self._calc_grid(11, 11)
        min_x, max_x, min_y, max_y = np.min(xs), np.max(xs), np.min(ys), np.max(ys)
        out_w = int(math.ceil(max_x - min_x)) + 2
        out_h = int(math.ceil(max_y - min_y)) + 2
        if out_w <= 0 or out_h <= 0:
            return
        out = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.translate(-min_x, -min_y)
        self.draw_warp_patches(p, self._original_img, self._patches, fast=False)
        p.end()
        self._place(layer, out, QPoint(int(min_x), int(min_y)))

    @staticmethod
    def draw_warp_patches(painter: QPainter, src_img: QImage, patches: list, fast: bool):
        # Geometry antialiasing off: it leaves transparent seams between triangles.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not fast)
        for s0, s1, s2, s3, d0, d1, d2, d3 in patches:
            for src, dst in (((s0, s1, s2), (d0, d1, d2)), ((s0, s2, s3), (d0, d2, d3))):
                ts = _triangle_basis(src)
                inv_ts, ok = ts.inverted()
                if not ok:
                    continue
                painter.save()
                painter.setTransform(inv_ts * _triangle_basis(dst), combine=True)
                path = QPainterPath()
                path.addPolygon(QPolygonF(list(src)))
                painter.setClipPath(path)
                xs = [q.x() for q in src]
                ys = [q.y() for q in src]
                adj = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-1, -1, 1, 1)
                painter.drawImage(adj, src_img, adj)
                painter.restore()

    def cursor(self):
        return Qt.CursorShape.CrossCursor if self.is_transforming else Qt.CursorShape.ArrowCursor


def _triangle_basis(tri) -> QTransform:
    a, b, c = tri
    return QTransform(b.x() - a.x(), b.y() - a.y(), 0,
                      c.x() - a.x(), c.y() - a.y(), 0,
                      a.x(), a.y(), 1)
