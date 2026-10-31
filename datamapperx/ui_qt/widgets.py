"""The reusable widgets: Card, StepBar, ChipRow, DataTable, ActionTable and ChartPanel."""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..palette import Palette
from ..stat_charts import ChartSpec, chart_primitives
from .models import TableModel

ROW_HEIGHT = 28
CHART_SCALE = 1.33  # the chart layout is in "report points", as in the PDF; this makes them legible on screen
_TEXT_BASE = 20  # text is laid out at this pixel size and scaled to the size the chart asks for, so 7.5 is exact


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property (state, chip kind) changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def make_button(text: str, slot=None, *, primary: bool = False) -> QPushButton:
    """A push button; ``primary`` is the filled look for the main action of a screen."""
    button = QPushButton(text.replace("&", "&&"))  # a single & would underline a key instead of being shown
    if primary:
        button.setProperty("primary", True)
    if slot is not None:
        button.clicked.connect(lambda _checked=False: slot())
    return button


# ----------------------------------------------------------------------------- containers
class Card(QFrame):
    """A titled surface. Put the content in ``body``."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.title.setVisible(bool(title))
        outer.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)


class StepBar(QWidget):
    """The steps along the top. A finished step can be clicked to go back; a step that is not ready is greyed out."""

    clicked = Signal(int)

    def __init__(self, titles: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._buttons: list[QPushButton] = []
        for index, title in enumerate(titles):
            button = QPushButton(f"{index + 1}  {title}".replace("&", "&&"))
            button.setProperty("step", "todo")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, i=index: self.clicked.emit(i))
            layout.addWidget(button)
            self._buttons.append(button)
        layout.addStretch(1)

    def set_state(self, current: int, ready: Sequence[bool]) -> None:
        for index, button in enumerate(self._buttons):
            button.setEnabled(index <= current or bool(ready[index]))
            button.setProperty("step", "current" if index == current else "done" if index < current else "todo")
            repolish(button)


class ChipRow(QWidget):
    """A row of small coloured notes: (kind, text) with kind ``ok``, ``warn``, ``bad`` or ``info``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)

    def set_chips(self, chips: Sequence[tuple[str, str]]) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for position, (kind, text) in enumerate(chips):
            label = QLabel(text)
            label.setProperty("chip", kind)
            self._layout.insertWidget(position, label)


# ----------------------------------------------------------------------------- tables
def _style_table(view: QTableView) -> None:
    view.setShowGrid(False)
    view.setAlternatingRowColors(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    view.horizontalHeader().setHighlightSections(False)
    view.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setFrameShape(QFrame.Shape.NoFrame)


class _EmptyText:
    """Draws a centred hint on an empty table."""

    def paint_empty(self, view: QTableView, text: str, colour: str) -> None:
        if view.model() is not None and view.model().rowCount() == 0 and text:
            painter = QPainter(view.viewport())
            painter.setPen(QColor(colour))
            painter.drawText(view.viewport().rect().adjusted(16, 16, -16, -16),
                             int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)


class DataTable(QTableView):
    """A read-only table of text that stays fast however many rows it has: only the visible rows are asked for."""

    rowSelected = Signal(int)

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_tokens = palette
        self.table_model = TableModel(palette, self)
        self.setModel(self.table_model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        _style_table(self)
        self.horizontalHeader().setStretchLastSection(False)
        self._empty_text = ""
        self._hint = _EmptyText()
        self._natural: list[int] = []
        self._stretch: int | None = None
        self.selectionModel().currentRowChanged.connect(lambda current, _previous: self.rowSelected.emit(current.row()))

    def set_table(self, headings: Sequence[str], rows: Sequence[Sequence[object]], tags: Sequence[str] | None = None,
                  aligns: Sequence[str] | None = None, empty_text: str = "", stretch: int | None = None,
                  cell_tags=None, max_width: int = 420) -> None:
        self._empty_text = empty_text
        self.table_model.set_table(headings, rows, tags, aligns, cell_tags)
        self.fit_columns(stretch, max_width=max_width)

    def fit_columns(self, stretch: int | None = None, sample_rows: int = 200, max_width: int = 420) -> None:
        """Each column as wide as its heading and its longest values (the first rows are enough), up to a limit.

        ``stretch`` names the column that takes the room left over when the table is wider than its columns; when it is
        narrower the table scrolls sideways, and no column is ever squeezed to nothing.
        """
        metrics, bold = self.fontMetrics(), QFont(self.font())
        bold.setBold(True)
        head_metrics = QFontMetricsF(bold)
        rows = self.table_model.rows[:sample_rows]
        header = self.horizontalHeader()
        self._natural = []
        for column in range(self.table_model.columnCount()):
            heading = str(self.table_model.headerData(column, Qt.Orientation.Horizontal) or "")
            widest = max([head_metrics.horizontalAdvance(heading)] + [metrics.horizontalAdvance(row[column]) for row in rows])
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self._natural.append(int(min(max_width, max(56, widest + 28))))
        self._stretch = stretch
        self._apply_widths()

    def _apply_widths(self) -> None:
        extra = 0
        if self._stretch is not None and self._natural:
            extra = max(0, self.viewport().width() - sum(self._natural))
        for column, width in enumerate(self._natural):
            self.setColumnWidth(column, width + (extra if column == self._stretch else 0))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_widths()

    def select_row(self, row: int | None, *, notify: bool = True) -> None:
        if row is None or not 0 <= row < self.table_model.rowCount():
            self.clearSelection()
            return
        selection = self.selectionModel()
        was_blocked = selection.blockSignals(not notify)
        self.selectRow(row)
        selection.blockSignals(was_blocked)
        self.scrollTo(self.model().index(row, 0))

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.table_model.set_palette(palette)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._hint.paint_empty(self, self._empty_text, self.palette_tokens.muted)


class _ButtonDelegate(QStyledItemDelegate):
    """Paints the + or × at the end of a row; it grows a filled background while the pointer is over it."""

    SIZE = 24

    def __init__(self, view: ActionTable) -> None:
        super().__init__(view)
        self._view = view

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)  # the row background / selection
        p = self._view.palette_tokens
        hot = bool(option.state & QStyle.StateFlag.State_MouseOver)
        add = self._view.kind == "add"
        box = QRect(0, 0, self.SIZE, self.SIZE)
        box.moveCenter(option.rect.center())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hot:
            painter.setBrush(QColor(p.accent if add else p.danger))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(box), 6, 6)
            glyph = QColor(p.on_accent if add else p.surface)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.accent if add else p.muted), 1))
            painter.drawRoundedRect(QRectF(box).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            glyph = QColor(p.accent if add else p.muted)
        painter.setPen(QPen(glyph, 1.6))
        c, r = QPointF(box.center()) + QPointF(0.5, 0.5), 5.0
        if add:
            painter.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
            painter.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        else:
            painter.drawLine(QPointF(c.x() - r * .7, c.y() - r * .7), QPointF(c.x() + r * .7, c.y() + r * .7))
            painter.drawLine(QPointF(c.x() - r * .7, c.y() + r * .7), QPointF(c.x() + r * .7, c.y() - r * .7))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(44, ROW_HEIGHT)


class ActionTable(QTableView):
    """A multi-select list of names with one button at the end of each row (``kind`` is ``"add"`` or ``"remove"``).

    Optional columns: the row number and right-aligned values with headings (Min, Max). A click on a button emits
    ``action(row)``; double-click or Enter emits ``activated_rows`` for the selected rows; Delete emits ``delete_pressed``.
    Qt reports a double-click on a button as a single click, so it never acts on two rows, and two quick clicks on
    different rows both count (a time-based guard would swallow the second).
    """

    action = Signal(int)
    activated_rows = Signal(list)
    delete_pressed = Signal()

    def __init__(self, palette: Palette, *, kind: str, name_heading: str, numbered: bool = False,
                 value_headings: Sequence[str] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if kind not in ("add", "remove"):
            raise ValueError(f"unknown kind {kind!r}")
        self.kind, self.palette_tokens, self._numbered = kind, palette, numbered
        self._headings = ([" No."] if numbered else []) + [name_heading, *value_headings, ""]
        self._aligns = (["center"] if numbered else []) + ["w", *["e"] * len(value_headings), "center"]
        self.table_model = TableModel(palette, self)
        self.setModel(self.table_model)
        self.table_model.set_table(self._headings, [], aligns=self._aligns)
        self._button_column = len(self._headings) - 1
        self.setItemDelegateForColumn(self._button_column, _ButtonDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        _style_table(self)
        self.setMouseTracking(True)
        self._empty_text, self._hint = "", _EmptyText()
        self.clicked.connect(self._clicked)
        self.doubleClicked.connect(self._double_clicked)
        self._fit()

    def _fit(self) -> None:
        header = self.horizontalHeader()
        name = 1 if self._numbered else 0
        for column in range(len(self._headings)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(name, QHeaderView.ResizeMode.Stretch)
        if self._numbered:
            self.setColumnWidth(0, 52)
        for column in range(name + 1, self._button_column):
            self.setColumnWidth(column, 84)
        self.setColumnWidth(self._button_column, 44)

    def set_items(self, items: Sequence[str], values: Sequence[Sequence[str]] | None = None, empty_text: str = "") -> None:
        rows = []
        for position, name in enumerate(items):
            rows.append(([str(position + 1)] if self._numbered else []) + [name, *(values[position] if values else ()), ""])
        self._empty_text = empty_text
        self.table_model.set_table(self._headings, rows, aligns=self._aligns)
        self._fit()

    def items(self) -> list[str]:
        name = 1 if self._numbered else 0
        return [row[name] for row in self.table_model.rows]

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def select_rows(self, rows: Sequence[int]) -> None:
        model, selection = self.model(), QItemSelection()
        for row in rows:
            if 0 <= row < model.rowCount():
                selection.select(model.index(row, 0), model.index(row, model.columnCount() - 1))
        self.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.table_model.set_palette(palette)
        self.viewport().update()

    def _clicked(self, index) -> None:
        if index.column() != self._button_column:
            return
        self.action.emit(index.row())

    def _double_clicked(self, index) -> None:
        if index.column() != self._button_column:
            self.activated_rows.emit(self.selected_rows())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated_rows.emit(self.selected_rows())
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._hint.paint_empty(self, self._empty_text, self.palette_tokens.muted)


# ----------------------------------------------------------------------------- charts
class ChartPanel(QWidget):
    """Every chart of an item in a grid, painted from the same primitives the PDF and Excel reports use.

    The primitives are laid out for a drawing measured in report points (the layout reserves room for text of those
    sizes), so they are drawn at that scale and the painter enlarges the result. Fonts of any width then fit.
    """

    CELL_HEIGHT = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs: list[ChartSpec] = []
        self._cache: dict[tuple[int, int, int], list] = {}

    def set_specs(self, specs: Sequence[ChartSpec]) -> None:
        self._specs = list(specs)
        self._cache.clear()
        rows = math.ceil(len(self._specs) / self._columns()) if self._specs else 1
        self.setMinimumHeight(rows * self.CELL_HEIGHT)
        self.update()

    def _columns(self) -> int:
        return 1 if len(self._specs) <= 1 else 2

    def _primitives(self, index: int, width: int, height: int):
        key = (index, width, height)
        if key not in self._cache:
            self._cache[key] = chart_primitives(self._specs[index], width, height)
        return self._cache[key]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))  # charts are drawn for print, so they stay on white in dark mode
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(CHART_SCALE, CHART_SCALE)
        columns = self._columns()
        cell_w, cell_h = max(240, int(self.width() / CHART_SCALE / columns)), int(self.CELL_HEIGHT / CHART_SCALE)
        for index in range(len(self._specs)):
            x, y = (index % columns) * cell_w + 3, (index // columns) * cell_h
            paint_primitives(painter, self._primitives(index, cell_w - 6, cell_h - 4), x, y, self.font())
        painter.end()


def paint_primitives(painter: QPainter, primitives, dx: float, dy: float, base_font: QFont) -> None:
    """Draw ``stat_charts.chart_primitives`` output: text, line, rect and circle, in top-left coordinates."""
    for kind, coords, style in primitives:
        colour = QColor(style.get("color", "#263746"))
        if kind == "text":
            _paint_text(painter, coords[0] + dx, coords[1] + dy, style, colour, base_font)
        elif kind == "line":
            pen = QPen(colour, style.get("width", 1))
            if style.get("dash"):
                pen.setDashPattern([5 / pen.widthF(), 3 / pen.widthF()])
            painter.setPen(pen)
            points = [QPointF(coords[i] + dx, coords[i + 1] + dy) for i in range(0, len(coords), 2)]
            painter.drawPolyline(points)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            rect = QRectF(coords[0] + dx, coords[1] + dy, coords[2] - coords[0], coords[3] - coords[1])
            painter.drawRect(rect) if kind == "rect" else painter.drawEllipse(rect)


def _paint_text(painter: QPainter, x: float, y: float, style: dict, colour: QColor, base_font: QFont) -> None:
    font = QFont(base_font)
    font.setPixelSize(_TEXT_BASE)
    font.setBold(bool(style.get("bold")))
    metrics = QFontMetricsF(font)
    text = style["text"]
    width = metrics.horizontalAdvance(text)
    left = {"w": 0.0, "e": -width, "center": -width / 2}[style.get("anchor", "w")]
    factor = style.get("size", 9) / _TEXT_BASE
    painter.save()
    painter.setFont(font)
    painter.setPen(colour)
    painter.translate(x, y)
    if style.get("angle"):
        painter.rotate(-style["angle"])  # tk's angle is counter-clockwise
    painter.scale(factor, factor)
    painter.drawText(QPointF(left, metrics.ascent() - metrics.height() / 2), text)
    painter.restore()


__all__ = ["ActionTable", "Card", "ChartPanel", "ChipRow", "DataTable", "StepBar", "make_button", "paint_primitives", "repolish"]
