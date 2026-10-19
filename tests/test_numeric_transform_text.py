"""The options bar's numeric Transform fields on a text layer (the bar
used to refuse text): W/H scale the text by font size, X/Y move it,
the angle turns it — through the real panel widgets and Apply."""
import pytest
from PyQt6.QtGui import QColor

from core.document import Document
from core.layer import TextLayer


@pytest.fixture()
def text_transform(main_window, mocked_dialogs):
    w = main_window
    w._add_tab(Document(300, 200), "t")
    layer = w._document.add_layer(name="T", layer_cls=TextLayer)
    layer.text_data = {"text": "Hi", "x": 60, "y": 80, "font_size": 24, "color": "#ff000000"}
    layer.rebake_thumbnail()
    w._document.active_layer_index = w._document.layers.index(layer)
    w._free_transform()
    page = w._opts_bar.page_for("Move")
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()                    # the overflow re-fit is deferred
    unit = page._tf_widget.parentWidget()
    # The fields are offered: in the row, or (narrow window) under "»".
    assert not page._tf_widget.isHidden() and not unit.isHidden()
    return w, page


def _text(w):
    return w._document.get_active_layer().data()


def _size(w):
    return _text(w).runs[0][1].size


def test_width_field_scales_text_by_font_size(text_transform):
    w, page = text_transform
    page._sp_w.setValue(200)
    assert page._sp_h.value() == 200                # linked
    page._apply_btn.click()
    assert _size(w) == pytest.approx(48)


def test_angle_field_rotates_text(text_transform):
    w, page = text_transform
    page._sp_a.setValue(30)
    page._apply_btn.click()
    assert _text(w).angle == pytest.approx(30)
    assert _size(w) == pytest.approx(24)


def test_x_field_moves_text(text_transform):
    w, page = text_transform
    x0 = _text(w).x
    page._sp_x.setValue(page._sp_x.value() + 25)
    page._apply_btn.click()
    assert _text(w).x == pytest.approx(x0 + 25, abs=0.1)   # the field has one decimal


def test_unlinked_width_still_scales_uniformly(text_transform):
    w, page = text_transform
    page._btn_link.setChecked(False)
    page._sp_w.setValue(150)
    page._apply_btn.click()
    assert _size(w) == pytest.approx(36)
