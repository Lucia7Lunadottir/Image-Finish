"""A text layer's content as data: the string, per-character styling (as
style runs), paragraph settings, layer-wide effects and placement.

`TextData` is what a TextLayer's `text_data` dict parses into (and is
written back as). Editing operations — insert, delete, restyle a range —
live here too, so the on-canvas editor (ui/text_edit_session.py) only
deals with cursors and input, never with run bookkeeping.

Sizes are in points, laid out on a fixed 96-dpi device (core/text_engine.py),
which is how the previous renderer turned points into pixels — existing
documents keep their exact size.
"""
from dataclasses import dataclass, field, replace, fields

from PyQt6.QtGui import QColor

CAPS = ("normal", "all", "small")
ALIGNS = ("left", "center", "right", "justify")


def _hex(c) -> str:
    return QColor(c).name(QColor.NameFormat.HexArgb)


@dataclass(frozen=True)
class CharStyle:
    family: str = "Sans Serif"
    size: float = 24.0             # points
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    color: str = "#ff000000"       # #AARRGGBB (hex keeps the dataclass hashable/comparable)
    tracking: float = 0.0          # 1/1000 em, like Photoshop's Character panel
    baseline_shift: float = 0.0    # points, positive = up
    caps: str = "normal"

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "CharStyle":
        known = {f.name for f in fields(cls)}
        kw = {k: v for k, v in (d or {}).items() if k in known}
        if "color" in kw:
            kw["color"] = _hex(kw["color"])
        if kw.get("caps") not in CAPS:
            kw.pop("caps", None)
        return cls(**kw)


# tool_opts / panel keys -> CharStyle field, and back.
CHAR_OPTION_KEYS = {
    "font_family": "family", "font_size": "size", "font_bold": "bold",
    "font_italic": "italic", "font_underline": "underline", "font_strikeout": "strikeout",
    "text_color": "color", "font_tracking": "tracking",
    "font_baseline_shift": "baseline_shift", "font_caps": "caps",
}
PARAGRAPH_OPTION_KEYS = {
    "text_align": "align", "text_leading": "leading",
    "para_indent_left": "indent_left", "para_indent_right": "indent_right",
    "para_indent_first": "indent_first", "para_space_before": "space_before",
    "para_space_after": "space_after",
}
EFFECT_OPTION_KEYS = {
    "text_stroke_w": "stroke_width", "text_stroke_color": "stroke_color",
    "text_shadow": "shadow", "text_shadow_color": "shadow_color",
    "text_shadow_dx": "shadow_dx", "text_shadow_dy": "shadow_dy",
}


def _coerce(field_name: str, value):
    if field_name in ("color", "stroke_color", "shadow_color"):
        return _hex(value)
    if field_name in ("size", "tracking", "baseline_shift", "leading", "stroke_width",
                      "shadow_dx", "shadow_dy", "indent_left", "indent_right", "indent_first",
                      "space_before", "space_after"):
        return float(value)
    if field_name in ("bold", "italic", "underline", "strikeout", "shadow"):
        return bool(value)
    return value


@dataclass(frozen=True)
class ParagraphStyle:
    align: str = "left"
    leading: float = 1.0           # multiple of the natural line height
    indent_left: float = 0.0       # points
    indent_right: float = 0.0
    indent_first: float = 0.0      # extra indent of each paragraph's first line
    space_before: float = 0.0      # points between paragraphs
    space_after: float = 0.0


@dataclass(frozen=True)
class TextEffects:
    stroke_width: float = 0.0
    stroke_color: str = "#ff000000"
    shadow: bool = False
    shadow_color: str = "#a0000000"
    shadow_dx: float = 3.0
    shadow_dy: float = 3.0


def _paragraph_from_dict(p: dict) -> ParagraphStyle:
    return ParagraphStyle(
        align=p.get("align", "left") if p.get("align") in ALIGNS else "left",
        leading=float(p.get("leading", 1.0) or 1.0),
        **{k: float(p[k]) for k in ("indent_left", "indent_right", "indent_first",
                                    "space_before", "space_after") if k in p})


@dataclass
class TextData:
    text: str = ""
    # Style runs: [(length, CharStyle)], lengths summing to len(text).
    # Always at least one run, even for empty text — it's the style new
    # typing gets.
    runs: list = field(default_factory=lambda: [(0, CharStyle())])
    # One ParagraphStyle per newline-separated paragraph (Photoshop keeps
    # alignment/indents/spacing per paragraph), kept in step with the text
    # by insert/delete.
    paragraphs: list = field(default_factory=lambda: [ParagraphStyle()])
    effects: TextEffects = field(default_factory=TextEffects)
    x: float = 0.0                 # document position of the text's local origin
    y: float = 0.0
    angle: float = 0.0             # rotation (degrees) around (x, y)
    vertical: bool = False
    box: tuple | None = None       # (w, h) for paragraph (area) text; None = point text

    def __post_init__(self):
        # Constructed directly (tests, legacy data) the runs/paragraphs may
        # not match the text yet — make the invariants hold from the start.
        self._normalize()

    # ── serialization ───────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "version": 2,
            "text": self.text,
            "runs": [[n, s.to_dict()] for n, s in self.runs],
            "paragraphs": [{f.name: getattr(ps, f.name) for f in fields(ParagraphStyle)}
                           for ps in self.paragraphs],
            "effects": {f.name: getattr(self.effects, f.name) for f in fields(TextEffects)},
            "x": self.x, "y": self.y, "angle": self.angle,
            "vertical": self.vertical,
            "box": list(self.box) if self.box else None,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "TextData":
        d = d or {}
        if d.get("version") == 2:
            runs = [(int(n), CharStyle.from_dict(s)) for n, s in d.get("runs") or []]
            # "paragraphs" (per paragraph) or the first version's single
            # layer-wide "paragraph".
            paras = d.get("paragraphs") or [d.get("paragraph") or {}]
            e = d.get("effects") or {}
            known_e = {f.name for f in fields(TextEffects)}
            data = cls(
                text=d.get("text", ""),
                runs=runs or [(len(d.get("text", "")), CharStyle())],
                paragraphs=[_paragraph_from_dict(p) for p in paras],
                effects=TextEffects(**{k: _coerce(k, v) for k, v in e.items() if k in known_e}),
                x=float(d.get("x", 0)), y=float(d.get("y", 0)), angle=float(d.get("angle", 0) or 0),
                vertical=bool(d.get("vertical", False)),
                box=tuple(d["box"]) if d.get("box") else None,
            )
            data._normalize()
            return data
        return cls._from_legacy(d)

    @classmethod
    def _from_legacy(cls, d: dict) -> "TextData":
        """Pre-2026-10 text_data: one style for the whole layer, flat keys."""
        def col(v, default):
            if v is None:
                return default
            return _hex(v)
        style = CharStyle(
            family=d.get("font_family", "Sans Serif"), size=float(d.get("font_size", 24)),
            bold=bool(d.get("font_bold", False)), italic=bool(d.get("font_italic", False)),
            underline=bool(d.get("font_underline", False)), strikeout=bool(d.get("font_strikeout", False)),
            color=col(d.get("text_color"), "#ff000000"), tracking=float(d.get("font_tracking", 0) or 0),
        )
        text = d.get("text", "")
        return cls(
            text=text, runs=[(len(text), style)],
            paragraphs=[ParagraphStyle(align=d.get("text_align", "left") if d.get("text_align") in ALIGNS else "left",
                                       leading=float(d.get("text_leading", 1.0) or 1.0))] * (text.count("\n") + 1),
            effects=TextEffects(
                stroke_width=float(d.get("text_stroke_w", 0) or 0),
                stroke_color=col(d.get("text_stroke_color"), "#ff000000"),
                shadow=bool(d.get("text_shadow", False)),
                shadow_color=col(d.get("text_shadow_color"), "#a0000000"),
                shadow_dx=float(d.get("text_shadow_dx", 3)), shadow_dy=float(d.get("text_shadow_dy", 3)),
            ),
            x=float(d.get("x", 0)), y=float(d.get("y", 0)),
            angle=float(d.get("text_angle", 0) or 0), vertical=bool(d.get("vertical", False)),
        )

    @classmethod
    def from_options(cls, opts: dict, x: float, y: float, vertical: bool = False,
                     box=None) -> "TextData":
        """A brand-new, empty text layer styled from the Text tool options."""
        base = cls._from_legacy({k: v for k, v in opts.items()})
        para = replace(base.paragraphs[0], **{f: float(opts[k]) for k, f in PARAGRAPH_OPTION_KEYS.items()
                                              if k in opts and f not in ("align", "leading")})
        style = base.runs[0][1]
        extra = {}
        if "font_baseline_shift" in opts:
            extra["baseline_shift"] = float(opts["font_baseline_shift"])
        if opts.get("font_caps") in CAPS:
            extra["caps"] = opts["font_caps"]
        return cls(text="", runs=[(0, replace(style, **extra))], paragraphs=[para],
                   effects=base.effects, x=float(x), y=float(y), vertical=vertical,
                   box=tuple(box) if box else None)

    def copy(self) -> "TextData":
        return replace(self, runs=list(self.runs), paragraphs=list(self.paragraphs))

    # ── paragraphs ──────────────────────────────────────────────────
    @property
    def paragraph(self) -> ParagraphStyle:
        """The first paragraph's style (defaults shown for a whole layer)."""
        return self.paragraphs[0]

    def paragraph_index(self, pos: int) -> int:
        return self.text.count("\n", 0, max(0, min(pos, len(self.text))))

    def restyle_paragraphs(self, a: int, b: int, **changes):
        """Paragraph changes apply to every paragraph [a, b] touches (the
        caret's own paragraph when a == b), like Photoshop."""
        lo, hi = self.paragraph_index(min(a, b)), self.paragraph_index(max(a, b))
        for i in range(lo, hi + 1):
            self.paragraphs[i] = replace(self.paragraphs[i], **changes)

    def restyle_all_paragraphs(self, **changes):
        self.paragraphs = [replace(p, **changes) for p in self.paragraphs]

    def _sync_paragraphs(self):
        need = self.text.count("\n") + 1
        if not self.paragraphs:
            self.paragraphs = [ParagraphStyle()]
        if len(self.paragraphs) < need:
            self.paragraphs = self.paragraphs + [self.paragraphs[-1]] * (need - len(self.paragraphs))
        elif len(self.paragraphs) > need:
            self.paragraphs = self.paragraphs[:need]

    # ── runs ────────────────────────────────────────────────────────
    def _normalize(self):
        """Merge equal neighbours, drop empty runs (keeping one), and make
        the run lengths add up to the text length."""
        out = []
        for n, s in self.runs:
            if n <= 0:
                continue
            if out and out[-1][1] == s:
                out[-1] = (out[-1][0] + n, s)
            else:
                out.append((n, s))
        total = sum(n for n, _ in out)
        if total < len(self.text):
            last = out[-1][1] if out else (self.runs[0][1] if self.runs else CharStyle())
            out.append((len(self.text) - total, last))
        elif total > len(self.text):
            excess = total - len(self.text)
            while excess and out:
                n, s = out[-1]
                take = min(n, excess)
                excess -= take
                if n - take:
                    out[-1] = (n - take, s)
                else:
                    out.pop()
        if not out:
            out = [(0, self.runs[0][1] if self.runs else CharStyle())]
        self.runs = out
        self._sync_paragraphs()

    def style_at(self, pos: int) -> CharStyle:
        """Style of the character *before* `pos` (what typing at `pos`
        continues), or of the first character at the very start."""
        if not self.runs:
            return CharStyle()
        target = max(0, pos - 1) if pos > 0 else 0
        acc = 0
        for n, s in self.runs:
            if target < acc + n:
                return s
            acc += n
        return self.runs[-1][1]

    def styles_in(self, a: int, b: int) -> list:
        """Distinct styles covering [a, b)."""
        if a >= b:
            return [self.style_at(a)]
        out, acc = [], 0
        for n, s in self.runs:
            if acc < b and acc + n > a and s not in out:
                out.append(s)
            acc += n
        return out or [self.style_at(a)]

    def iter_runs(self):
        """(start, end, style) for each run."""
        acc = 0
        for n, s in self.runs:
            yield acc, acc + n, s
            acc += n

    def _split_at(self, pos: int):
        runs, acc = [], 0
        for n, s in self.runs:
            if acc < pos < acc + n:
                runs.append((pos - acc, s))
                runs.append((acc + n - pos, s))
            else:
                runs.append((n, s))
            acc += n
        self.runs = runs

    # ── editing ─────────────────────────────────────────────────────
    def insert(self, pos: int, s: str, style: CharStyle | None = None):
        if not s:
            return
        pos = max(0, min(len(self.text), pos))
        style = style or self.style_at(pos)
        pi = self.paragraph_index(pos)
        new_breaks = s.count("\n")
        if new_breaks:   # a split paragraph keeps its style on both halves
            self.paragraphs[pi + 1:pi + 1] = [self.paragraphs[pi]] * new_breaks
        self.text = self.text[:pos] + s + self.text[pos:]
        self._split_at(pos)
        runs, acc, done = [], 0, False
        for n, st in self.runs:
            if not done and acc == pos:
                runs.append((len(s), style))
                done = True
            runs.append((n, st))
            acc += n
        if not done:
            runs.append((len(s), style))
        self.runs = runs
        self._normalize()

    def delete(self, a: int, b: int):
        a, b = max(0, min(a, b)), min(len(self.text), max(a, b))
        if a == b:
            return
        keep_style = self.style_at(a + 1)
        removed_breaks = self.text.count("\n", a, b)
        if removed_breaks:   # merged paragraphs take the first one's style
            pi = self.paragraph_index(a)
            del self.paragraphs[pi + 1:pi + 1 + removed_breaks]
        self.text = self.text[:a] + self.text[b:]
        runs, acc = [], 0
        for n, s in self.runs:
            lo, hi = acc, acc + n
            cut = max(0, min(hi, b) - max(lo, a))
            if n - cut:
                runs.append((n - cut, s))
            acc = hi
        self.runs = runs or [(0, keep_style)]
        self._normalize()
        if not self.text:
            self.runs = [(0, keep_style)]

    def restyle(self, a: int, b: int, **changes):
        """Apply CharStyle field changes to [a, b)."""
        a, b = max(0, min(a, b)), min(len(self.text), max(a, b))
        if a >= b:
            return
        self._split_at(a)
        self._split_at(b)
        runs, acc = [], 0
        for n, s in self.runs:
            if a <= acc and acc + n <= b:
                s = replace(s, **changes)
            runs.append((n, s))
            acc += n
        self.runs = runs
        self._normalize()

    def restyle_all(self, **changes):
        if not self.text:
            self.runs = [(0, replace(self.runs[0][1], **changes))]
        else:
            self.restyle(0, len(self.text), **changes)

    def scale_sizes(self, k: float):
        """Uniform scale of everything size-like (MoveTool resize)."""
        self.runs = [(n, replace(s, size=max(0.5, s.size * k), baseline_shift=s.baseline_shift * k))
                     for n, s in self.runs]
        e = self.effects
        self.effects = replace(e, stroke_width=e.stroke_width * k,
                               shadow_dx=e.shadow_dx * k, shadow_dy=e.shadow_dy * k)
        if self.box:
            self.box = (self.box[0] * k, self.box[1] * k)

    # ── option keys (panels / options bar) ──────────────────────────
    def options_at(self, a: int, b: int | None = None) -> dict:
        """Options-bar/panel values describing [a, b) (or the caret at a):
        the first style's values, like Photoshop shows for mixed text."""
        s = self.styles_in(a, b if b is not None else a)[0]
        opts = {key: getattr(s, f) for key, f in CHAR_OPTION_KEYS.items()}
        opts["text_color"] = QColor(s.color)
        para = self.paragraphs[self.paragraph_index(a)]
        opts.update({key: getattr(para, f) for key, f in PARAGRAPH_OPTION_KEYS.items()})
        for key, f in EFFECT_OPTION_KEYS.items():
            v = getattr(self.effects, f)
            opts[key] = QColor(v) if f.endswith("color") else v
        return opts
