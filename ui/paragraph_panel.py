from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QToolButton, QButtonGroup, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal
from core.locale import tr

from ui import theme

def LABEL_STYLE():
    return (f"color:{theme.SUBTEXT};font-size:11px;background:transparent;")
def HEADER_STYLE():
    return (
    f"color:{theme.MUTED};font-size:10px;font-weight:bold;letter-spacing:1px;"
                    "background:transparent;padding:8px 0 4px 0;"
    )
def ALIGN_BTN_STYLE():
    return (
    f"QToolButton{{background:{theme.SURFACE0};color:{theme.TEXT};border:none;"
                       "padding:4px 10px;border-radius:4px;font-size:13px;font-weight:bold;}"
                       f"QToolButton:checked{{background:{theme.ACCENT};color:{theme.BASE};}}"
                       f"QToolButton:hover:!checked{{background:{theme.SURFACE1};}}"
    )


def _make_sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    theme.apply_style(f, lambda: f"color:{theme.SURFACE0};background:{theme.SURFACE0};max-height:1px;margin:4px 0;")
    return f


class ParagraphPanel(QWidget):
    """Paragraph-level text formatting. Deliberately just alignment: this
    app's text layers are single click-to-place blocks, not InDesign-style
    reflowing paragraph boxes, so indents / space-before / space-after
    controls that used to live here had no layout model to act on and did
    nothing — removed rather than left as decoration. Alignment is real:
    `option_changed("text_align", ...)`
    reaches `text_data` via `TextTool._snap_opts` and is applied by
    `core.text_layout.TextLayout`."""

    option_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)

        # ---------- Header ----------
        self._header_lbl = QLabel("PARAGRAPH")
        theme.apply_style(self._header_lbl, HEADER_STYLE)
        layout.addWidget(self._header_lbl)
        layout.addWidget(_make_sep())

        # ---------- Alignment ----------
        align_lbl = QLabel("Alignment:")
        theme.apply_style(align_lbl, LABEL_STYLE)
        layout.addWidget(align_lbl)

        align_row = QWidget()
        align_lo = QHBoxLayout(align_row)
        align_lo.setContentsMargins(0, 0, 0, 0)
        align_lo.setSpacing(4)

        self._btn_left    = QToolButton(); self._btn_left.setText("≡ L")
        self._btn_center  = QToolButton(); self._btn_center.setText("≡ C")
        self._btn_right   = QToolButton(); self._btn_right.setText("≡ R")
        self._btn_justify = QToolButton(); self._btn_justify.setText("≡ J")

        self._align_btns = {
            "left":    self._btn_left,
            "center":  self._btn_center,
            "right":   self._btn_right,
            "justify": self._btn_justify,
        }

        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)

        for key, btn in self._align_btns.items():
            btn.setCheckable(True)
            theme.apply_style(btn, ALIGN_BTN_STYLE)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setFixedHeight(28)
            self._align_group.addButton(btn)
            align_lo.addWidget(btn)
            # Use default-argument capture to avoid closure-over-loop-variable
            btn.clicked.connect(lambda checked, k=key: self.option_changed.emit("text_align", k))

        self._btn_left.setChecked(True)
        layout.addWidget(align_row)

        layout.addStretch(1)

    # ---------------------------------------------------------------- Public

    def refresh(self, canvas):
        if canvas is None:
            return
        opts = getattr(canvas, "tool_opts", {})

        align = opts.get("text_align", "left")
        btn = self._align_btns.get(align)
        if btn:
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def retranslate(self):
        self._header_lbl.setText(
            tr("para.title") if tr("para.title") != "para.title" else "PARAGRAPH"
        )
