"""Lays out and paints a TextData (core/text_model.py).

Layout uses QTextLayout against a fixed 96-dpi paint device, so a layer
looks identical on every machine regardless of screen DPI, and points
convert to pixels exactly as the previous renderer did (24 pt = 32 px).

The result is geometry, not pixels: glyph outlines as QPainterPaths in
the text's local coordinates (origin = TextData.x/y before rotation).
Painting happens in device space (like shapes, core/shape_model.py), so
text stays sharp at any zoom and the same code serves the layer render,
the thumbnail bake, the on-canvas editor and MoveTool's preview.

Two layouts share one interface (`TextLayoutResult`): horizontal text
(paragraphs → wrapped/aligned lines) and vertical text (columns of
upright characters, right to left — the CJK convention Photoshop uses).
The editor only talks to that interface: caret geometry, hit-testing,
selection rectangles and line navigation.
"""
import math

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                         QPainterPathStroker, QTextCharFormat, QTextLayout, QTextOption, QTransform)

from core.text_model import CharStyle, TextData

PT_TO_PX = 96.0 / 72.0
_UNBOUNDED = 1.0e7

_device = None


def layout_device() -> QImage:
    global _device
    if _device is None:
        _device = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        _device.setDotsPerMeterX(3780)   # 96 dpi
        _device.setDotsPerMeterY(3780)
    return _device


def qfont(style: CharStyle) -> QFont:
    f = QFont(style.family)
    f.setPointSizeF(max(0.5, style.size))
    f.setBold(style.bold)
    f.setItalic(style.italic)
    f.setUnderline(False)        # decorations are drawn as geometry, see _decorations
    f.setStrikeOut(False)
    if style.caps == "all":
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    elif style.caps == "small":
        f.setCapitalization(QFont.Capitalization.SmallCaps)
    if style.tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                           style.tracking / 1000.0 * style.size * PT_TO_PX)
    f.setKerning(True)
    return f


def _char_format(style: CharStyle) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFont(qfont(style))
    return fmt


def text_transform(data: TextData) -> QTransform:
    """Local text coordinates -> document coordinates."""
    return QTransform().translate(data.x, data.y).rotate(data.angle)


class GlyphPiece:
    """Outline of a stretch of glyphs sharing one style."""
    __slots__ = ("path", "style")

    def __init__(self, path: QPainterPath, style: CharStyle):
        self.path = path
        self.style = style


class TextLayoutResult:
    """Common interface of a laid-out text (see module docstring)."""

    vertical = False

    def __init__(self, data: TextData):
        self.data = data
        self.pieces: list[GlyphPiece] = []

    # geometry
    def bounds(self) -> QRectF:
        raise NotImplementedError

    def outline(self) -> QPainterPath:
        path = QPainterPath()
        for p in self.pieces:
            path.addPath(p.path)
        return path

    def ink_bounds(self) -> QRectF:
        r = self.outline().boundingRect()
        return r if not r.isEmpty() else self.bounds()

    def apply_warp(self, warp) -> None:
        """Warp Text: bend the glyph outlines within the text's frame. Only
        the outlines change — carets, hit-testing and selection stay on
        the unwarped layout (the editor shows the text unwarped)."""
        frame = self.bounds()
        if frame.width() <= 0 or frame.height() <= 0:
            return
        self.pieces = [GlyphPiece(warp.map_path(p.path, frame), p.style) for p in self.pieces]

    # editing
    def caret_line(self, pos: int) -> QLineF:
        raise NotImplementedError

    def hit(self, pt: QPointF) -> int:
        raise NotImplementedError

    def selection_rects(self, a: int, b: int) -> list:
        raise NotImplementedError

    def line_range(self, pos: int) -> tuple:
        raise NotImplementedError

    def move_line(self, pos: int, step: int, hint: float | None) -> tuple:
        """Caret one line forward/back in reading order (down for horizontal,
        left for vertical), keeping `hint` — the cross-axis caret coordinate
        the move started from. Returns (new_pos, hint)."""
        raise NotImplementedError


def _paragraphs(text: str):
    """(start, paragraph text) for each newline-separated paragraph."""
    out, start = [], 0
    for part in text.split("\n"):
        out.append((start, part))
        start += len(part) + 1
    return out


def _runs_in(data: TextData, a: int, b: int):
    for s, e, style in data.iter_runs():
        lo, hi = max(s, a), min(e, b)
        if lo < hi:
            yield lo, hi, style


def _glyph_path(run, dx: float, dy: float) -> tuple:
    """Outline of a QGlyphRun, plus its baseline span (x0, x1, y)."""
    raw = run.rawFont()
    idxs = run.glyphIndexes()
    poss = run.positions()
    path = QPainterPath()
    if not idxs:
        return path, None
    for gi, p in zip(idxs, poss):
        path.addPath(raw.pathForGlyph(gi).translated(p.x() + dx, p.y() + dy))
    adv = raw.advancesForGlyphIndexes(idxs)
    x0 = poss[0].x() + dx
    x1 = poss[-1].x() + dx + (adv[-1].x() if adv else 0)
    return path, (x0, x1, poss[0].y() + dy, raw)


def _decorations(path: QPainterPath, style: CharStyle, span, vertical: bool = False):
    if span is None or not (style.underline or style.strikeout):
        return
    x0, x1, base, raw = span
    t = max(1.0, raw.lineThickness())
    if style.underline:
        path.addRect(QRectF(x0, base + raw.underlinePosition(), x1 - x0, t))
    if style.strikeout:
        path.addRect(QRectF(x0, base - raw.xHeight() / 2 - t / 2, x1 - x0, t))


# ── horizontal ─────────────────────────────────────────────────────────────

class _Line:
    __slots__ = ("layout", "qline", "para_start", "dx", "top", "height", "start", "end", "para_end",
                 "indent", "indent_right", "align")

    def __init__(self, layout, qline, para_start, para_end):
        self.layout = layout
        self.qline = qline
        self.para_start = para_start
        self.para_end = para_end
        self.start = para_start + qline.textStart()
        self.end = self.start + qline.textLength()
        self.dx = 0.0
        self.indent = 0.0
        self.indent_right = 0.0
        self.align = "left"
        self.top = 0.0
        self.height = qline.height()

    def x_of(self, pos: int) -> float:
        x = self.qline.cursorToX(pos - self.para_start)
        return (x[0] if isinstance(x, tuple) else x) + self.dx


class HorizontalLayout(TextLayoutResult):

    def __init__(self, data: TextData):
        super().__init__(data)
        self.lines: list[_Line] = []
        self._layouts = []
        y = 0.0
        for pi, (para_start, ptext) in enumerate(_paragraphs(data.text)):
            para = data.paragraphs[pi]   # each paragraph has its own settings
            ind_l, ind_r = para.indent_left * PT_TO_PX, para.indent_right * PT_TO_PX
            ind_first = para.indent_first * PT_TO_PX
            wrap_width = max(10.0, data.box[0] - ind_l - ind_r) if data.box else _UNBOUNDED
            leading = para.leading or 1.0
            if pi:
                y += para.space_before * PT_TO_PX
            para_end = para_start + len(ptext)
            base = data.style_at(para_start + 1 if ptext else para_start)
            tl = QTextLayout(ptext, qfont(base), layout_device())
            formats = []
            for lo, hi, style in _runs_in(data, para_start, para_end):
                fr = QTextLayout.FormatRange()
                fr.start, fr.length, fr.format = lo - para_start, hi - lo, _char_format(style)
                formats.append(fr)
            tl.setFormats(formats)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if data.box
                            else QTextOption.WrapMode.NoWrap)
            if para.align == "justify" and data.box:
                opt.setAlignment(Qt.AlignmentFlag.AlignJustify)
            tl.setTextOption(opt)
            tl.beginLayout()
            para_lines = []
            while True:
                ql = tl.createLine()
                if not ql.isValid():
                    break
                first = not para_lines
                ql.setLineWidth(max(10.0, wrap_width - (ind_first if first else 0.0)))
                ql.setPosition(QPointF(0, y))
                ln = _Line(tl, ql, para_start, para_end)
                ln.top = y
                ln.indent = ind_l + (ind_first if first else 0.0)
                ln.indent_right = ind_r
                ln.align = para.align
                para_lines.append(ln)
                y += ql.height() * leading
            tl.endLayout()
            y += para.space_after * PT_TO_PX
            self._layouts.append(tl)
            self.lines.extend(para_lines)

        natural = [ln.qline.naturalTextWidth() for ln in self.lines]
        self.width = data.box[0] if data.box else max(
            (w + ln.indent + ln.indent_right for ln, w in zip(self.lines, natural)), default=0.0)
        for ln, w in zip(self.lines, natural):
            room = self.width - ln.indent_right - ln.indent - w   # free space on this line
            ln.dx = ln.indent
            if ln.align == "center":
                ln.dx += room / 2
            elif ln.align == "right":
                ln.dx += room
        self.height = (self.lines[-1].top + self.lines[-1].height) if self.lines else 0.0

        # glyph outlines, per style run, per line
        for ln in self.lines:
            for lo, hi, style in _runs_in(self.data, ln.start, ln.end):
                shift = -style.baseline_shift * PT_TO_PX
                for run in ln.layout.glyphRuns(lo - ln.para_start, hi - lo):
                    path, span = _glyph_path(run, ln.dx, shift)
                    _decorations(path, style, span)
                    if not path.isEmpty():
                        self.pieces.append(GlyphPiece(path, style))

    def bounds(self) -> QRectF:
        if self.data.box:
            return QRectF(0, 0, self.data.box[0], self.data.box[1])
        return QRectF(0, 0, max(self.width, 1.0), max(self.height, 1.0))

    def _line_for(self, pos: int) -> _Line:
        for ln in self.lines:
            if ln.para_start <= pos <= ln.para_end and ln.start <= pos <= ln.end:
                # A wrap point belongs to the next line, except at the
                # paragraph's very end.
                if pos == ln.end and pos != ln.para_end:
                    continue
                return ln
        return self.lines[-1]

    def caret_line(self, pos):
        ln = self._line_for(pos)
        x = ln.x_of(pos)
        return QLineF(x, ln.top, x, ln.top + ln.height)

    def hit(self, pt):
        ln = min(self.lines, key=lambda l: 0 if l.top <= pt.y() < l.top + l.height
                 else min(abs(pt.y() - l.top), abs(pt.y() - l.top - l.height)))
        local = ln.qline.xToCursor(pt.x() - ln.dx)
        pos = ln.para_start + local
        return max(ln.start, min(pos, ln.end))

    def selection_rects(self, a, b):
        a, b = min(a, b), max(a, b)
        out = []
        for ln in self.lines:
            s, e = max(a, ln.start), min(b, ln.end)
            beyond = b > ln.end and a <= ln.end  # selection runs past this line's end
            if s > e or (s == e and not beyond):
                continue
            x1, x2 = ln.x_of(s), ln.x_of(e)
            if beyond:
                x2 += ln.height * 0.25
            out.append(QRectF(min(x1, x2), ln.top, abs(x2 - x1), ln.height))
        return out

    def line_range(self, pos):
        ln = self._line_for(pos)
        return ln.start, ln.end

    def move_line(self, pos, step, hint):
        ln = self._line_for(pos)
        i = self.lines.index(ln) + step
        if hint is None:
            hint = ln.x_of(pos)
        if i < 0:
            return 0, hint
        if i >= len(self.lines):
            return len(self.data.text), hint
        target = self.lines[i]
        return self.hit(QPointF(hint, target.top + target.height / 2)), hint


# ── vertical ───────────────────────────────────────────────────────────────

class _Cell:
    __slots__ = ("pos", "top", "height")

    def __init__(self, pos, top, height):
        self.pos, self.top, self.height = pos, top, height


class _Column:
    __slots__ = ("x", "width", "cells", "start", "end", "align")

    def __init__(self, start, align: str = "left"):
        self.align = align   # vertical text: left/center/right = top/middle/bottom
        self.x = 0.0
        self.width = 0.0
        self.cells: list[_Cell] = []
        self.start = start
        self.end = start

    def bottom(self) -> float:
        return self.cells[-1].top + self.cells[-1].height if self.cells else 0.0


class VerticalLayout(TextLayoutResult):
    """Columns of upright characters, first column at the origin and the
    following ones to its left. A column is one paragraph, wrapped at the
    box height for paragraph text."""

    vertical = True

    def __init__(self, data: TextData):
        super().__init__(data)
        self.columns: list[_Column] = []
        limit = data.box[1] if data.box else _UNBOUNDED
        glyphs = []   # (column, cell, path, style)
        for pi, (para_start, ptext) in enumerate(_paragraphs(data.text)):
            para = data.paragraphs[pi]
            leading = para.leading or 1.0
            col = _Column(para_start, para.align)
            self.columns.append(col)
            base = data.style_at(para_start + 1 if ptext else para_start)
            col.width = base.size * PT_TO_PX * leading
            y = 0.0
            for i, ch in enumerate(ptext):
                pos = para_start + i
                style = data.style_at(pos + 1)
                em = style.size * PT_TO_PX
                cell_h = em * (1.0 + style.tracking / 1000.0)
                if y + cell_h > limit and col.cells:
                    col.end = pos
                    col = _Column(pos, para.align)
                    self.columns.append(col)
                    col.width = em * leading
                    y = 0.0
                col.width = max(col.width, em * leading)
                cell = _Cell(pos, y, cell_h)
                col.cells.append(cell)
                if ch.strip():
                    glyphs.append((col, cell, self._glyph(ch, style), style))
                y += cell_h
            col.end = para_start + len(ptext)

        x = data.box[0] if data.box else 0.0
        for i, col in enumerate(self.columns):
            if data.box:
                x -= col.width
                col.x = x
            else:
                col.x = -sum(c.width for c in self.columns[1:i + 1])
        self.length = max((c.bottom() for c in self.columns), default=0.0)
        span = data.box[1] if data.box else self.length
        for col in self.columns:
            off = 0.0
            if col.align == "center":
                off = (span - col.bottom()) / 2
            elif col.align == "right":
                off = span - col.bottom()
            for c in col.cells:
                c.top += off

        for col, cell, (path, adv, asc, desc), style in glyphs:
            gx = col.x + (col.width - adv) / 2
            gy = cell.top + (cell.height - (asc + desc)) / 2 + asc
            shift = style.baseline_shift * PT_TO_PX    # vertical text: shift moves right
            p = path.translated(gx + shift, gy)
            t = max(1.0, style.size * PT_TO_PX / 16)
            if style.underline:
                p.addRect(QRectF(col.x + col.width - t, cell.top, t, cell.height))
            if style.strikeout:
                p.addRect(QRectF(col.x + col.width / 2 - t / 2, cell.top, t, cell.height))
            self.pieces.append(GlyphPiece(p, style))

    @staticmethod
    def _glyph(ch: str, style: CharStyle):
        tl = QTextLayout(ch, qfont(style), layout_device())
        tl.beginLayout()
        ql = tl.createLine()
        ql.setLineWidth(_UNBOUNDED)
        tl.endLayout()
        path = QPainterPath()
        adv = ql.naturalTextWidth()
        for run in tl.glyphRuns():
            p, _ = _glyph_path(run, 0, -ql.ascent())   # baseline at y = 0
            path.addPath(p)
        return path, adv, ql.ascent(), ql.descent()

    def bounds(self) -> QRectF:
        if self.data.box:
            return QRectF(0, 0, self.data.box[0], self.data.box[1])
        left = min((c.x for c in self.columns), default=0.0)
        right = max((c.x + c.width for c in self.columns), default=1.0)
        return QRectF(left, 0, max(1.0, right - left), max(1.0, self.length))

    def _column_for(self, pos):
        for col in self.columns:
            if col.start <= pos <= col.end:
                if pos == col.end and col is not self.columns[-1]:
                    nxt = self.columns[self.columns.index(col) + 1]
                    if nxt.start == pos:      # wrap point belongs to the next column
                        continue
                return col
        return self.columns[-1]

    def _y_of(self, col, pos):
        for c in col.cells:
            if c.pos == pos:
                return c.top
        if col.cells:
            return col.cells[-1].top + col.cells[-1].height
        return 0.0

    def caret_line(self, pos):
        col = self._column_for(pos)
        y = self._y_of(col, pos)
        return QLineF(col.x, y, col.x + col.width, y)

    def hit(self, pt):
        col = min(self.columns, key=lambda c: 0 if c.x <= pt.x() < c.x + c.width
                  else min(abs(pt.x() - c.x), abs(pt.x() - c.x - c.width)))
        for c in col.cells:
            if pt.y() < c.top + c.height / 2:
                return c.pos
        return col.end

    def selection_rects(self, a, b):
        a, b = min(a, b), max(a, b)
        out = []
        for col in self.columns:
            cells = [c for c in col.cells if a <= c.pos < b]
            if cells:
                out.append(QRectF(col.x, cells[0].top, col.width,
                                  cells[-1].top + cells[-1].height - cells[0].top))
        return out

    def line_range(self, pos):
        col = self._column_for(pos)
        return col.start, col.end

    def move_line(self, pos, step, hint):
        col = self._column_for(pos)
        i = self.columns.index(col) + step
        if hint is None:
            hint = self._y_of(col, pos)
        if i < 0:
            return 0, hint
        if i >= len(self.columns):
            return len(self.data.text), hint
        target = self.columns[i]
        return self.hit(QPointF(target.x + target.width / 2, hint + 0.01)), hint


def layout_text(data: TextData, warped: bool = True) -> TextLayoutResult:
    """`warped=False`: ignore Warp Text (the text editor edits the plain
    layout, so its caret and selection match the glyphs)."""
    layout = VerticalLayout(data) if data.vertical else HorizontalLayout(data)
    if warped and data.warp.is_active():
        layout.apply_warp(data.warp)
    return layout


# ── painting ───────────────────────────────────────────────────────────────

def effects_padding(data: TextData) -> float:
    e = data.effects
    pad = 2.0
    if e.stroke_width > 0:
        pad += e.stroke_width
    if e.shadow:
        pad += max(abs(e.shadow_dx), abs(e.shadow_dy))
    return pad


def paint_text(painter: QPainter, data: TextData, layout: TextLayoutResult | None = None) -> None:
    """Shadow, stroke, then fill — painted in device space through the
    painter's current transform (which maps local text coordinates)."""
    layout = layout or layout_text(data)
    if not layout.pieces:
        return
    to_dev = painter.transform()
    scale = math.sqrt(abs(to_dev.determinant())) or 1.0
    e = data.effects
    painter.save()
    painter.setTransform(QTransform())
    if e.shadow:
        shadow = QPainterPath()
        for p in layout.pieces:
            shadow.addPath(p.path.translated(e.shadow_dx, e.shadow_dy))
        painter.fillPath(to_dev.map(shadow), QBrush(QColor(e.shadow_color)))
    if e.stroke_width > 0:
        stroker = QPainterPathStroker()
        stroker.setWidth(e.stroke_width * 2 * scale)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.fillPath(stroker.createStroke(to_dev.map(layout.outline())),
                         QBrush(QColor(e.stroke_color)))
    by_color: dict[str, QPainterPath] = {}
    for p in layout.pieces:
        by_color.setdefault(p.style.color, QPainterPath()).addPath(p.path)
    for color, path in by_color.items():
        path.setFillRule(Qt.FillRule.WindingFill)
        painter.fillPath(to_dev.map(path), QBrush(QColor(color)))
    painter.restore()


def text_outline_in_document(data: TextData) -> QPainterPath:
    """Glyph outlines in document coordinates (type-mask selections)."""
    return text_transform(data).map(layout_text(data).outline())
