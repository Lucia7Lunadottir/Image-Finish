"""Font families as a person sees them: one entry per typeface, its weights
and widths as styles — the way Photoshop lists fonts (family + style).

Qt's QFontDatabase.families() also lists every *alias* fontconfig knows:
a face of "Noto Kufi Arabic" in the Black weight is listed both as that
family's "Black" style and as a family of its own, "Noto Kufi Arabic
Black" — on a typical Linux system ~1900 "families" for ~350 typefaces.
Which names are aliases comes from fontconfig itself: `fc-list` gives each
face its family names paired with style names, the first pair being the
typographic family ("Noto Sans Arabic,Noto Sans Arabic Cond Light" /
"Condensed Light,Regular"); the later family names (legacy weight/width
families, localized names) are aliases. For fonts fontconfig doesn't know
(the app's own fonts/ folder) a family is taken as an alias when it is
another family's name plus one of that family's styles ("DejaVu Sans" +
"Condensed"). Real separate typefaces ("Noto Sans Mono", "Arial Black"
where Arial has no Black style) stay.

`resolve()` maps an alias (as stored in older documents) to its family and
style, so the pickers show it properly; the alias itself still renders."""
from __future__ import annotations

import re
import shutil
import subprocess

from PyQt6.QtGui import QFontDatabase

_WIDTHS = ("ultracondensed", "extracondensed", "condensed", "semicondensed", "",
           "semiexpanded", "expanded", "extraexpanded", "ultraexpanded")
# Width keyword -> QFont stretch (percent).
STRETCH = {"ultracondensed": 50, "extracondensed": 62, "condensed": 75, "semicondensed": 87,
           "semiexpanded": 112, "expanded": 125, "extraexpanded": 150, "ultraexpanded": 200}
_REGULAR = ("regular", "normal", "book", "roman", "обычный", "standard", "medium")


def _norm(text: str) -> str:
    return re.sub(r"[\s_-]+", "", text).lower()


def style_width(style: str) -> str:
    """The width keyword in a style name ("Condensed Bold" -> "condensed")."""
    n = _norm(style)
    for w in sorted((w for w in _WIDTHS if w), key=len, reverse=True):
        if w in n:
            return w
    return ""


class FontCatalog:
    def __init__(self):
        self._families: list[str] = []
        self._aliases: dict[str, tuple[str, str]] = {}
        self._styles: dict[str, list[str]] = {}
        self._build()

    # ── building ────────────────────────────────────────────────────
    def _build(self):
        names = [f for f in QFontDatabase.families() if not f.startswith(".")]
        known = set(names)
        styles = {f: QFontDatabase.styles(f) for f in names}
        fc_aliases, fc_families = self._fontconfig_aliases()
        for alias, target in fc_aliases.items():
            if (alias in known and target[0] in known and alias != target[0]
                    and alias not in fc_families):
                self._aliases[alias] = target
        for name in names:
            # fontconfig's own typographic families are never aliases.
            if name in self._aliases or name in fc_families:
                continue
            alias = self._alias_of(name, known, styles)
            if alias is not None:
                self._aliases[name] = alias
        self._families = sorted((f for f in names if f not in self._aliases), key=str.casefold)
        self._styles = {f: self._ordered(f, styles.get(f, [])) for f in self._families}

    @staticmethod
    def _fontconfig_aliases() -> tuple[dict, set]:
        """({secondary family name: (typographic family, style)},
        {typographic family names}) from fontconfig."""
        exe = shutil.which("fc-list")
        if not exe:
            return {}, set()
        try:
            out = subprocess.run([exe, "--format", "%{family}|%{style}\n"], capture_output=True,
                                 text=True, timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return {}, set()
        aliases, typographic = {}, set()
        for line in out.splitlines():
            fams, _, stys = line.partition("|")
            families = [f.strip() for f in re.split(r"(?<!\\),", fams) if f.strip()]
            styles = [st.strip() for st in re.split(r"(?<!\\),", stys) if st.strip()]
            if not families:
                continue
            typographic.add(families[0].replace("\\,", ","))
            if len(families) < 2:
                continue
            family, style = families[0], (styles[0] if styles else "")
            for i, other in enumerate(families[1:], 1):
                other = other.replace("\\,", ",")
                if other == family:
                    continue
                # An alias name covers several faces (its own Regular, Bold,
                # Italic…): it stands for the face that is plain under it.
                legacy = _norm(styles[i]) if i < len(styles) else ""
                if other not in aliases or legacy in _REGULAR:
                    aliases[other] = (family, style)
        return aliases, typographic

    @staticmethod
    def _alias_of(name: str, known: set, styles: dict):
        """(family, style) when `name` = an existing family + one of its
        styles; the longest matching family wins."""
        words = name.split(" ")
        for cut in range(len(words) - 1, 0, -1):
            base = " ".join(words[:cut])
            if base not in known:
                continue
            suffix = _norm(" ".join(words[cut:]))
            for st in styles.get(base, []):
                if _norm(st) == suffix:
                    return base, st
        return None

    @staticmethod
    def _ordered(family: str, styles: list[str]) -> list[str]:
        """Narrow to wide, then light to heavy, upright before italic."""
        def key(st):
            width = style_width(st)
            return (_WIDTHS.index(width), QFontDatabase.italic(family, st),
                    QFontDatabase.weight(family, st), st)
        return sorted(dict.fromkeys(styles), key=key)

    # ── queries ─────────────────────────────────────────────────────
    def families(self) -> list[str]:
        return list(self._families)

    def styles(self, family: str) -> list[str]:
        family, _ = self.resolve(family)
        if family not in self._styles:
            self._styles[family] = self._ordered(family, QFontDatabase.styles(family))
        return list(self._styles[family])

    def default_style(self, family: str) -> str:
        """The family's plain style (Regular / Normal / Book / …)."""
        styles = self.styles(family)
        for st in styles:
            if _norm(st) in _REGULAR and not style_width(st):
                return st
        upright = [s for s in styles if not QFontDatabase.italic(family, s) and not style_width(s)]
        return (upright or styles or [""])[0]

    def resolve(self, name: str) -> tuple[str, str]:
        """(family, style) for a family name or an alias of one; style ""
        when `name` is a family itself."""
        return self._aliases.get(name, (name, ""))

    def is_alias(self, name: str) -> bool:
        return name in self._aliases


_catalog: FontCatalog | None = None


def font_catalog() -> FontCatalog:
    """The shared catalog (built on first use, after the app's own fonts
    from fonts/ are registered). `reset_font_catalog()` after adding fonts."""
    global _catalog
    if _catalog is None:
        _catalog = FontCatalog()
    return _catalog


def reset_font_catalog() -> None:
    global _catalog
    _catalog = None
