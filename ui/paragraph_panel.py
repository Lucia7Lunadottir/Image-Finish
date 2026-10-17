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


def _align_icon(kind: str):
    """Four-line paragraph glyph showing the alignment (theme text color)."""
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    pm = QPixmap(18, 14)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setPen(QPen(QColor(theme.TEXT), 2))
    for i, w in enumerate((16, 10, 14, 8)):
        if kind == "justify":
            w = 16 if i < 3 else 8
        x = {"left": 1, "center": 1 + (16 - w) / 2, "right": 17 - w, "justify": 1}[kind]
        y = 2 + i * 3.4
        p.drawLine(int(x), int(y), int(x + w), int(y))
    p.end()
    return QIcon(pm)


def _make_sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    theme.apply_style(f, lambda: f"color:{theme.SURFACE0};background:{theme.SURFACE0};max-height:1px;margin:4px 0;")
    return f


class ParagraphPanel(QWidget):
    """Paragraph formatting: alignment, left/right/first-line indents and
    space before/after paragraphs. These used to be removed for lack of a
    layout model; core/text_engine.py now lays text out in paragraphs (and
    wraps paragraph text in its box), so they act on real geometry. Values
    go out as option keys (text_align, para_*) and reach the text through
    ui/actions/text_actions.py — the open editor or the selected layer."""

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
        self._align_lbl = align_lbl = QLabel(tr("para.align"))
        theme.apply_style(align_lbl, LABEL_STYLE)
        layout.addWidget(align_lbl)

        align_row = QWidget()
        align_lo = QHBoxLayout(align_row)
        align_lo.setContentsMargins(0, 0, 0, 0)
        align_lo.setSpacing(4)

        self._btn_left    = QToolButton(); self._btn_left.setIcon(_align_icon("left"))
        self._btn_center  = QToolButton(); self._btn_center.setIcon(_align_icon("center"))
        self._btn_right   = QToolButton(); self._btn_right.setIcon(_align_icon("right"))
        self._btn_justify = QToolButton(); self._btn_justify.setIcon(_align_icon("justify"))

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
        layout.addWidget(_make_sep())

        # ---------- Indents and spacing (points) ----------
        from PyQt6.QtWidgets import QGridLayout, QDoubleSpinBox
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        self._spins = {}
        self._spin_labels = []
        for row, (key, opt) in enumerate((("para.indent_l", "para_indent_left"),
                                          ("para.indent_r", "para_indent_right"),
                                          ("para.indent_first", "para_indent_first"),
                                          ("para.before", "para_space_before"),
                                          ("para.after", "para_space_after"))):
            lbl = QLabel(tr(key))
            theme.apply_style(lbl, LABEL_STYLE)
            self._spin_labels.append((lbl, key))
            sp = QDoubleSpinBox()
            sp.setRange(-1000 if opt == "para_indent_first" else 0, 1000)
            sp.setDecimals(1)
            sp.setSuffix(" pt")
            sp.setFixedWidth(84)
            sp.valueChanged.connect(lambda v, o=opt: self.option_changed.emit(o, v))
            grid.addWidget(lbl, row, 0)
            grid.addWidget(sp, row, 1)
            self._spins[opt] = sp
        grid.setColumnStretch(2, 1)
        layout.addWidget(grid_w)

        layout.addStretch(1)
        self.retranslate()

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
        for opt, sp in self._spins.items():
            sp.blockSignals(True)
            sp.setValue(float(opts.get(opt, 0.0)))
            sp.blockSignals(False)

    def retranslate(self):
        self._header_lbl.setText(tr("para.title"))
        self._align_lbl.setText(tr("para.align"))
        for key, btn in self._align_btns.items():
            btn.setToolTip(tr(f"para.align.{key}"))
        for lbl, key in self._spin_labels:
            lbl.setText(tr(key))
