"""Font lists show typefaces, not Qt's weight/width aliases
(core/font_catalog.py), with a separate style list (ui/font_picker.py), and
the chosen style reaches the text (CharStyle.style -> qfont)."""
import pytest
from PyQt6.QtGui import QFontDatabase, QFontInfo

from core.font_catalog import FontCatalog, font_catalog
from core.text_engine import qfont
from core.text_model import CharStyle, TextData


def _family_with_styles(min_styles=3):
    cat = font_catalog()
    for f in ("Noto Sans", "DejaVu Sans", "Liberation Sans", "Cantarell"):
        if f in cat.families() and len(cat.styles(f)) >= min_styles:
            return f
    for f in cat.families():
        if len(cat.styles(f)) >= min_styles:
            return f
    pytest.skip("no font family with several styles here")


def test_catalog_hides_aliases(qapp):
    cat = font_catalog()
    qt = [f for f in QFontDatabase.families() if not f.startswith(".")]
    assert len(cat.families()) <= len(qt)
    assert not any(cat.is_alias(f) for f in cat.families())
    for alias, (family, style) in list(cat._aliases.items())[:200]:
        assert family in cat.families() or cat.is_alias(family) is False
        assert alias not in cat.families()


def test_heuristic_alias_rule(qapp):
    known = {"Foo Sans", "Foo Sans Light", "Foo Sans Mono"}
    styles = {"Foo Sans": ["Regular", "Light", "Semi Bold"], "Foo Sans Light": ["Regular"],
              "Foo Sans Mono": ["Regular"]}
    assert FontCatalog._alias_of("Foo Sans Light", known, styles) == ("Foo Sans", "Light")
    assert FontCatalog._alias_of("Foo Sans Mono", known, styles) is None          # a typeface of its own
    known.add("Foo Sans SemiBold")
    assert FontCatalog._alias_of("Foo Sans SemiBold", known, styles) == ("Foo Sans", "Semi Bold")


def test_styles_are_ordered_and_have_a_plain_default(qapp):
    family = _family_with_styles()
    cat = font_catalog()
    styles = cat.styles(family)
    assert len(styles) == len(set(styles))
    default = cat.default_style(family)
    assert default in styles
    assert not QFontDatabase.italic(family, default)


def test_aliases_resolve_to_a_real_style(qapp):
    cat = font_catalog()
    if not cat._aliases:
        pytest.skip("no aliased fonts here")
    alias, (family, style) = next(iter(cat._aliases.items()))
    assert cat.resolve(alias) == (family, style)
    assert cat.resolve(family) == (family, "")


def test_qfont_uses_the_style_and_bold_on_top(qapp):
    family = _family_with_styles()
    cat = font_catalog()
    light = [s for s in cat.styles(family) if QFontDatabase.weight(family, s) < 400
             and not QFontDatabase.italic(family, s)]
    if not light:
        pytest.skip("no light style")
    st = light[-1]
    assert QFontInfo(qfont(CharStyle(family=family, style=st))).styleName() == st
    bold = QFontInfo(qfont(CharStyle(family=family, style=st, bold=True)))
    assert bold.weight() >= 600


def test_style_is_stored_and_shown_in_options(qapp):
    d = TextData.from_options({"font_family": "Sans Serif", "font_style": "Bold"}, 0, 0)
    assert d.runs[0][1].style == "Bold"
    back = TextData.from_dict(d.to_dict())
    assert back.runs[0][1].style == "Bold"
    assert back.options_at(0)["font_style"] == "Bold"


# ── pickers ──────────────────────────────────────────────────────────────────

def test_font_choice_emits_family_then_plain_style(qapp):
    from ui.font_picker import FontChoice
    family = _family_with_styles()
    seen = []
    fc = FontChoice(lambda k, v: seen.append((k, v)))
    fc.family_combo._choose(family)
    assert seen == [("font_family", family), ("font_style", "")]
    styles = font_catalog().styles(family)
    assert [fc.style_combo.itemText(i) for i in range(fc.style_combo.count())] == styles
    seen.clear()
    fc.style_combo.style_chosen.emit(styles[-1])
    assert seen == [("font_family", family), ("font_style", styles[-1])]


def test_font_choice_shows_an_old_alias_as_family_and_style(qapp):
    from ui.font_picker import FontChoice
    cat = font_catalog()
    if not cat._aliases:
        pytest.skip("no aliased fonts here")
    alias, (family, style) = next(iter(cat._aliases.items()))
    fc = FontChoice(lambda k, v: None)
    fc.show(alias)
    assert fc.family() == family
    assert fc.style_combo.current_style() == style


def test_typing_part_of_a_name_and_unknown_text(qapp):
    from ui.font_picker import FontFamilyCombo
    combo = FontFamilyCombo()
    family = _family_with_styles()
    got = []
    combo.family_chosen.connect(got.append)
    combo._choose(family.lower())                    # case-insensitive
    assert got == [family]
    combo._choose("no such font at all")
    assert combo.family() == family and combo.currentText() == family


def test_text_options_bar_has_the_style_list(main_window):
    page = main_window._opts_bar.page_for("Text")
    family = _family_with_styles()
    page.update_from_opts({"font_family": family, "font_style": ""})
    assert page._font.family() == family
    assert page._font.style_combo.count() == len(font_catalog().styles(family))


# ── symbol fonts (Webdings) ──────────────────────────────────────────────────

def _symbol_font():
    """A symbol-encoded font that maps Latin letters to pictures (Webdings,
    Wingdings…) — Qt also marks fonts of scripts it doesn't know as Symbol."""
    from PyQt6.QtGui import QFont, QRawFont
    for f in ("Webdings", "Wingdings", "Wingdings 2", "Symbol"):
        if f in QFontDatabase.families() and QRawFont.fromFont(QFont(f)).supportsCharacter(ord("A")):
            return f
    pytest.skip("no Webdings-like font installed")


def test_symbol_font_falls_back_for_missing_letters(qapp):
    """Real bug: Cyrillic typed in Webdings came out as empty boxes — Qt
    doesn't fall back for symbol fonts."""
    from core.text_engine import FALLBACK_FAMILY, _runs_in
    family = _symbol_font()
    d = TextData.from_dict({"text": "Hi Привет", "font_family": family, "font_size": 20,
                            "text_color": "#ff112233"})
    runs = list(_runs_in(d, 0, len(d.text)))
    families = {d.text[lo:hi].strip(): st.family for lo, hi, st in runs if d.text[lo:hi].strip()}
    assert families.get("Привет") == FALLBACK_FAMILY
    assert all(st.color == "#ff112233" for _, _, st in runs)        # same style otherwise


def test_symbol_font_shows_a_sample_in_the_list(qapp):
    from ui.font_picker import _FontPreviewDelegate
    own_name, sample = _FontPreviewDelegate._preview(_symbol_font())
    assert not own_name and sample


def test_fonts_of_unknown_scripts_show_their_own_glyphs(qapp):
    from PyQt6.QtGui import QFont, QRawFont
    from ui.font_picker import _FontPreviewDelegate
    for f in ("Noto Sans Adlam", "Noto Sans Brahmi", "Noto Sans Cuneiform"):
        if f in QFontDatabase.families():
            own_name, sample = _FontPreviewDelegate._preview(f)
            raw = QRawFont.fromFont(QFont(f))
            assert not own_name and sample and all(raw.supportsCharacter(ord(c)) for c in sample)
            return
    pytest.skip("no font of a script Qt doesn't know")
