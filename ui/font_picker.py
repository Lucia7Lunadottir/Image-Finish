"""Font pickers built on core/font_catalog.py: one entry per typeface
(not Qt's ~1900 weight/width aliases) and a separate style list —
Photoshop's "font family" + "font style" pair.

FontFamilyCombo replaces QFontComboBox: same look (each name drawn in its
own font), typing filters by any part of the name. FontStyleCombo lists the
chosen family's styles, narrow to wide and light to heavy."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QCompleter, QStyledItemDelegate, QStyleOptionViewItem

from core.font_catalog import font_catalog


class _FontPreviewDelegate(QStyledItemDelegate):
    """Draws each family name in that family (like QFontComboBox) — only
    when painting, i.e. for the rows on screen. Sizes are measured in the
    normal font: measuring in each family would load every font on the
    system just to lay the list out (seconds per combo)."""

    _cache: dict = {}

    @classmethod
    def _preview(cls, name: str) -> tuple[bool, str]:
        """(can the family draw its own name, a sample of its glyphs when
        it can't) — symbol fonts (Webdings) and fonts of other scripts
        get their name in the list's font plus a sample, as in Photoshop."""
        if name not in cls._cache:
            from PyQt6.QtGui import QFontDatabase, QRawFont
            ws = QFontDatabase.writingSystems(name)
            raw = QRawFont.fromFont(QFont(name))
            symbol = QFontDatabase.WritingSystem.Symbol in ws
            own_name = (not symbol and raw.isValid()
                        and all(raw.supportsCharacter(ord(c)) for c in name if c.isalnum()))
            sample = cls._sample(raw, ws) if not own_name else ""
            cls._cache[name] = (own_name, sample)
        return cls._cache[name]

    @staticmethod
    def _sample(raw, ws) -> str:
        """A few glyphs the font really has: letters of a symbol-encoded
        font (Webdings), emoji, Qt's sample of the font's script — or, for
        scripts Qt doesn't know, the first characters found in the font."""
        import unicodedata
        from PyQt6.QtGui import QFontDatabase
        latin = "".join(c for c in "abcdefghABCDEFGH" if raw.supportsCharacter(ord(c)))
        if len(latin) >= 3:
            return latin[:6]
        if raw.supportsCharacter(0x1F600):
            return "😀🎨🌸"
        W = QFontDatabase.WritingSystem
        for w in ws:
            if w not in (W.Latin, W.Cyrillic, W.Any, W.Symbol):
                text = QFontDatabase.writingSystemSample(w)
                if text and all(raw.supportsCharacter(ord(c)) for c in text if not c.isspace()):
                    return text[:8]
        letters, other = [], []
        for cp in range(0x00A1, 0x30000):           # letters first, else any marks
            if 0xD800 <= cp <= 0xDFFF or not raw.supportsCharacter(cp):
                continue
            kind = unicodedata.category(chr(cp))[0]
            if kind == "L":
                letters.append(chr(cp))
                if len(letters) == 5:
                    break
            elif kind not in "CZM" and len(other) < 5:
                other.append(chr(cp))
        return "".join(letters or other)

    @staticmethod
    def _sized(name: str, base: QFont) -> QFont:
        f = QFont(name)
        if base.pixelSize() > 0:
            f.setPixelSize(round(base.pixelSize() * 1.15))
        else:
            f.setPointSizeF(max(base.pointSizeF(), 8.0) * 1.15)
        return f

    def paint(self, painter, option, index):
        # A copy: the view hands every row the same option object, so
        # changing it in place made each row's font bigger than the last.
        option = QStyleOptionViewItem(option)
        name = index.data(Qt.ItemDataRole.DisplayRole)
        own_name, sample = self._preview(name) if name else (True, "")
        if name and own_name:
            option.font = self._sized(name, option.font)
        painter.save()
        painter.setClipRect(option.rect)                 # tall fonts stay in their row
        if sample:
            sample_font = self._sized(name, option.font)
            from PyQt6.QtGui import QFontMetricsF
            width = QFontMetricsF(sample_font).horizontalAdvance(sample) + 12
            name_opt = QStyleOptionViewItem(option)
            name_opt.rect = option.rect.adjusted(0, 0, -int(width), 0)
            super().paint(painter, name_opt, index)
            painter.setFont(sample_font)
            painter.setPen(option.palette.color(
                option.palette.ColorRole.HighlightedText if option.state & option.state.State_Selected
                else option.palette.ColorRole.Text))
            painter.drawText(option.rect.adjusted(0, 0, -6, 0),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, sample)
        else:
            super().paint(painter, option, index)
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)        # measured in the list's own font
        return QSize(hint.width(), round(hint.height() * 1.5))


class FontFamilyCombo(QComboBox):
    family_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Don't scan ~350 names for the widest one on first show.
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(14)
        self.setMaxVisibleItems(18)
        self.setItemDelegate(_FontPreviewDelegate(self))
        families = font_catalog().families()
        self.addItems(families)
        completer = QCompleter(families, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.popup().setItemDelegate(_FontPreviewDelegate(completer.popup()))
        self.setCompleter(completer)
        self.activated.connect(lambda i: self._choose(self.itemText(i)))
        completer.activated[str].connect(self._choose)
        self.lineEdit().editingFinished.connect(lambda: self._choose(self.currentText()))
        self._family = ""

    def _choose(self, name: str):
        family, _ = font_catalog().resolve(name.strip())
        if not family or self.findText(family, Qt.MatchFlag.MatchFixedString) < 0:
            self.set_family(self._family)            # unknown text: back to the current font
            return
        family = self.itemText(self.findText(family, Qt.MatchFlag.MatchFixedString))
        if family != self._family:
            self.set_family(family)
            self.family_chosen.emit(family)

    def family(self) -> str:
        return self._family

    def set_family(self, name: str):
        """Show `name` (an alias shows as its family) without emitting."""
        family, _ = font_catalog().resolve(name)
        self._family = family
        self.blockSignals(True)
        i = self.findText(family, Qt.MatchFlag.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)
        else:
            self.setEditText(family)
        self.blockSignals(False)


class FontStyleCombo(QComboBox):
    style_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setMinimumContentsLength(8)
        self.activated.connect(lambda i: self.style_chosen.emit(self.itemText(i)))

    def current_style(self) -> str:
        return self.currentText()

    def set_family(self, family: str, style: str = ""):
        """The styles of `family` (an alias resolves to its family and,
        when no style is given, to its own style), `style` selected —
        default: the family's plain style. Doesn't emit."""
        cat = font_catalog()
        fam, alias_style = cat.resolve(family)
        style = style or alias_style or cat.default_style(fam)
        self.blockSignals(True)
        self.clear()
        self.addItems(cat.styles(fam))
        i = self.findText(style)
        self.setCurrentIndex(i if i >= 0 else 0)
        self.setEnabled(self.count() > 1)
        self.blockSignals(False)


class FontChoice:
    """A FontFamilyCombo + FontStyleCombo pair wired to the `font_family`
    / `font_style` option keys through `emit(key, value)` — the same in
    the Text options bar, the Character panel and the text dialog.
    Choosing a family resets the style to the family's plain one."""

    def __init__(self, emit):
        self._emit = emit
        self.family_combo = FontFamilyCombo()
        self.style_combo = FontStyleCombo()
        self.family_combo.family_chosen.connect(self._on_family)
        self.style_combo.style_chosen.connect(self._on_style)
        self.show("Sans Serif", "")

    def _on_family(self, family: str):
        self.style_combo.set_family(family)
        self._emit("font_family", family)
        self._emit("font_style", "")

    def _on_style(self, style: str):
        self._emit("font_family", self.family_combo.family())   # an old alias -> its family
        self._emit("font_style", style)

    def show(self, family: str, style: str = ""):
        """Model -> widgets, without emitting."""
        self.family_combo.set_family(family)
        self.style_combo.set_family(family, style)

    def family(self) -> str:
        return self.family_combo.family()

    def style(self) -> str:
        """The chosen style, "" when it's the family's plain one."""
        from core.font_catalog import font_catalog
        st = self.style_combo.current_style()
        return "" if st == font_catalog().default_style(self.family()) else st
