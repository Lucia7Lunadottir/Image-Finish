"""Single source of truth for laying out a text layer's content.

Before this module, `tools/text_tool.py` had four independent
reimplementations of the same per-line font-metrics math
(`_render_text`, `_text_bounding_rect`, `_text_path_h`, and their
`_vertical` twins) — none of them aware of alignment, letter-spacing or
line-height, because there was nowhere for that logic to live without
copying it a fifth time. `TextLayout` is that one place: it is built once
from a `text_data`-shaped opts dict, and callers ask it for a bounding
box, a glyph outline path, or a fully-styled render (fill + stroke +
shadow) — horizontal and vertical text share this same class, branching
internally, instead of being parallel code paths.
"""

from PyQt6.QtCore import Qt, QRect, QPointF
from PyQt6.QtGui import QFont, QFontMetrics, QPainterPath, QColor, QPainter, QBrush, QPen


def _build_font(opts: dict) -> QFont:
    font = QFont(opts.get("font_family", "Sans Serif"),
                 int(opts.get("font_size", 24)))
    font.setBold(bool(opts.get("font_bold", False)))
    font.setItalic(bool(opts.get("font_italic", False)))
    font.setUnderline(bool(opts.get("font_underline", False)))
    font.setStrikeOut(bool(opts.get("font_strikeout", False)))
    tracking = float(opts.get("font_tracking", 0))
    if tracking:
        # Tracking is in thousandths of an em, the same convention
        # Photoshop's Character panel uses (and the panel's -500..500
        # spin range matches) — scale relative to this font's own size
        # rather than a fixed pixel amount, so tracking looks consistent
        # across font sizes.
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                              tracking / 1000.0 * font.pointSizeF())
    return font


class TextLayout:
    """Computed once per render/hit-test from a text_data-shaped dict.
    `vertical=True` switches to the column-per-line, char-per-row layout
    used by the vertical type tools; every other concern (alignment
    keying off `opts["text_align"]`, leading via `opts["text_leading"]`)
    only makes sense for horizontal text and is a no-op otherwise."""

    def __init__(self, text: str, opts: dict, vertical: bool = False):
        self.text = text
        self.opts = opts
        self.vertical = vertical
        self.font = _build_font(opts)
        self.metrics = QFontMetrics(self.font)
        self.align = opts.get("text_align", "left")
        self.leading = float(opts.get("text_leading", 1.0)) or 1.0

        if vertical:
            self.cols = text.split("\n")
            self.col_w = self.metrics.maxWidth() + 4
            self.char_h = self.metrics.height()
        else:
            self.lines = text.split("\n")
            self.line_h = self.metrics.lineSpacing() * self.leading
            self._line_w = [self.metrics.horizontalAdvance(l) for l in self.lines]
            self.max_w = max(self._line_w, default=0)

    # ------------------------------------------------------------ geometry
    def bounding_rect(self, x: int = 0, y: int = 0, padding: int = 0) -> QRect:
        if self.vertical:
            max_rows = max((len(c) for c in self.cols), default=0)
            w = self.col_w * max(1, len(self.cols))
            h = self.char_h * max(1, max_rows)
        else:
            w = self.max_w
            h = self.metrics.ascent() + self.metrics.descent() + \
                self.line_h * (len(self.lines) - 1)
        return QRect(x - padding, y - padding,
                    int(round(w)) + padding * 2, int(round(h)) + padding * 2)

    def _line_x_offset(self, line_w: float) -> float:
        if self.align == "center":
            return (self.max_w - line_w) / 2.0
        if self.align == "right":
            return self.max_w - line_w
        return 0.0

    # ------------------------------------------------------------- shaping
    def to_qpainter_path(self, x: int = 0, y: int = 0) -> QPainterPath:
        """Glyph outlines only — no fill/stroke/shadow applied. Used both
        for the styled render below and standalone (type-mask selection
        shape, `HorizontalTypeMaskTool`/`VerticalTypeMaskTool`)."""
        path = QPainterPath()
        if self.vertical:
            for ci, col_text in enumerate(self.cols):
                cx = x + ci * self.col_w
                for ri, ch in enumerate(col_text):
                    if ch.strip():
                        cy = y + self.metrics.ascent() + ri * self.char_h
                        path.addText(cx, cy, self.font, ch)
            return path

        baseline = self.metrics.ascent()
        is_justify = self.align == "justify"
        for i, line in enumerate(self.lines):
            if not line:
                continue
            ly = y + baseline + i * self.line_h
            is_last = i == len(self.lines) - 1
            if is_justify and not is_last and " " in line:
                self._add_justified_line(path, line, x, ly)
            else:
                lx = x + (0.0 if is_justify else self._line_x_offset(self._line_w[i]))
                path.addText(lx, ly, self.font, line)
        return path

    def _add_justified_line(self, path: QPainterPath, line: str, x: float, ly: float):
        words = line.split(" ")
        natural_w = self.metrics.horizontalAdvance(line)
        extra = max(0.0, self.max_w - natural_w)
        gap_extra = extra / (len(words) - 1) if len(words) > 1 else 0.0
        space_w = self.metrics.horizontalAdvance(" ")
        cx = x
        for i, word in enumerate(words):
            path.addText(cx, ly, self.font, word)
            cx += self.metrics.horizontalAdvance(word)
            if i < len(words) - 1:
                cx += space_w + gap_extra

    # -------------------------------------------------------------- render
    def draw(self, image, x: int, y: int, clip_path=None):
        """Full styled render (shadow, stroke, fill) — the exact same
        code path used for the live edit preview and the final bake, so
        the two can never visually disagree."""
        opts = self.opts
        text_color   = opts.get("text_color",       QColor(0, 0, 0))
        stroke_w     = int(opts.get("text_stroke_w",   0))
        stroke_color = opts.get("text_stroke_color", QColor(0, 0, 0))
        shadow       = bool(opts.get("text_shadow",  False))
        shadow_color = opts.get("text_shadow_color", QColor(0, 0, 0, 160))
        sdx          = int(opts.get("text_shadow_dx", 3))
        sdy          = int(opts.get("text_shadow_dy", 3))
        angle        = float(opts.get("text_angle", 0.0))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if clip_path and not clip_path.isEmpty():
            painter.setClipPath(clip_path)
        if angle and not self.vertical:
            painter.translate(x, y)
            painter.rotate(angle)
            painter.translate(-x, -y)
        if shadow:
            painter.fillPath(self.to_qpainter_path(x + sdx, y + sdy), QBrush(shadow_color))
        main_path = self.to_qpainter_path(x, y)
        if stroke_w > 0:
            pen = QPen(stroke_color, stroke_w * 2,
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(main_path, pen)
        painter.fillPath(main_path, QBrush(text_color))
        painter.end()
