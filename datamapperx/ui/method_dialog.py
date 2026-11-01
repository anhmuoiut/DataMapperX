"""The "About the method" dialog: the calculation sequence of the selected analysis, in collapsible groups of formulas."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..method_guide import Formula, Guide, Section
from .dialogs import Dialog, label
from .math_view import MathView
from .widgets import make_button


class ClickableHeading(QFrame):
    """A heading that opens and closes its group when clicked."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._label = label("", "heading")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setText(self, text: str) -> None:
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()


class MethodDialog(Dialog):
    def __init__(self, parent: QWidget, guide: Guide) -> None:
        super().__init__(parent, "About the method", size=(780, 700), min_size=(560, 420))
        self.guide = guide
        self.sections: dict[str, tuple[QWidget, ClickableHeading]] = {}
        self.opened: dict[str, bool] = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page = QWidget()
        self.page_layout = QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(10, 8, 10, 8)
        scroll.setWidget(self.page)
        self.layout_root.addWidget(scroll, 1)
        self._build(guide)
        self.page_layout.addStretch(1)
        self.button_row(make_button("Close", self.close, primary=True))

    # ------------------------------------------------------------------ content
    def _build(self, guide: Guide) -> None:
        self.page_layout.addWidget(label(guide.title, "title"))
        self.page_layout.addWidget(label(f"Method: {guide.method}", "muted"))
        self.page_layout.addWidget(label(guide.summary, wrap=True))
        for section in guide.sections:
            self._section(section)

    def _section(self, section: Section) -> None:
        header = ClickableHeading()
        header.clicked.connect(lambda title=section.title: self.toggle(title))
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(14, 2, 0, 0)
        for formula in section.formulas:
            self._formula(inner, formula)
        for note in section.notes:
            inner.addWidget(label(f"•  {note}", wrap=True))
        if section.values:
            self._values(inner, section.values)
        self.page_layout.addSpacing(8)
        self.page_layout.addWidget(header)
        self.page_layout.addWidget(body)
        self.sections[section.title] = (body, header)
        self.opened[section.title] = section.opened
        self.toggle(section.title, section.opened)

    def toggle(self, title: str, opened: bool | None = None) -> None:
        """Open or close a group of formulas (``opened`` None flips it)."""
        body, header = self.sections[title]
        self.opened[title] = opened = (not self.opened[title]) if opened is None else opened
        header.setText(f"{'▼' if opened else '►'}  {title}")
        body.setVisible(opened)

    def _formula(self, layout, formula: Formula) -> None:
        block = QVBoxLayout()
        block.setSpacing(2)
        name = label(formula.name)
        name.setStyleSheet("font-weight: 600;")
        block.addWidget(name)
        for line in formula.lines:
            row = QHBoxLayout()
            row.setContentsMargins(14, 0, 0, 0)
            row.addWidget(MathView(line, self.palette_tokens))
            row.addStretch(1)
            block.addLayout(row)
        block.addWidget(label(formula.explanation, wrap=True))
        if formula.variables:
            grid = QGridLayout()
            grid.setContentsMargins(14, 3, 0, 0)
            grid.addWidget(label("where", "muted"), 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            for row, (symbol, meaning) in enumerate(formula.variables):
                grid.addWidget(MathView(symbol, self.palette_tokens, size=13), row, 1, Qt.AlignmentFlag.AlignRight)
                grid.addWidget(label(meaning, "muted"), row, 2)
            grid.setColumnStretch(3, 1)
            block.addLayout(grid)
        layout.addSpacing(6)
        layout.addLayout(block)

    def _values(self, layout, values: tuple[tuple[str, str], ...]) -> None:
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        for row, (symbol, value) in enumerate(values):
            if not symbol:
                grid.addWidget(label(value, wrap=True), row, 0, 1, 3)
                continue
            grid.addWidget(MathView(symbol, self.palette_tokens, size=13), row, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label("="), row, 1)
            grid.addWidget(label(value), row, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
