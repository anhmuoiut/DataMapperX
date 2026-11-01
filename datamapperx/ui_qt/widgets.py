"""The reusable widgets: Card, StepBar, ChipRow, DataTable, ActionTable and ChartPanel."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QPainter,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..palette import Palette
from ..stat_charts import MIN_CELL_WIDTH, ChartSpec, agreement_extra_height, chart_primitives
from .models import TableModel
from .theme import SYMBOL_FONT

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
        self.title = QLabel(title, self)  # parented before it is shown: a parentless label shown here would open as a window
        self.title.setObjectName("cardTitle")
        self.title.setHidden(not title)
        outer.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)


class StepBar(QWidget):
    """Numbered steps side by side, painted in one go. A step is ``current`` (filled), ``complete`` (green), ``ready``
    (outlined), ``warn`` (outlined in amber) or ``locked`` (grey; a click on it does nothing)."""

    clicked = Signal(int)

    def __init__(self, titles: Sequence[str], palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._titles = [str(t) for t in titles]
        self._state = ["ready"] * len(self._titles)
        self._caption = [""] * len(self._titles)
        self._palette = palette
        self._focus = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(54)

    def set_step(self, index: int, state: str, caption: str) -> None:
        if (state, caption) != (self._state[index], self._caption[index]):
            self._state[index], self._caption[index] = state, caption
            self.update()

    def state(self, index: int) -> str:
        return self._state[index]

    def caption(self, index: int) -> str:
        return self._caption[index]

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def click(self, index: int) -> None:
        if self._state[index] != "locked":
            self.clicked.emit(index)

    def _cells(self) -> list[QRectF]:
        gap, count = 26.0, len(self._titles)
        width = (self.width() - 2 - gap * (count - 1)) / max(count, 1)
        return [QRectF(1 + i * (width + gap), 1, width, self.height() - 2) for i in range(count)]

    def _colors(self, state: str) -> dict[str, str]:
        p = self._palette
        return {
            "current": {"bg": p.accent, "line": p.accent, "ink": p.on_accent, "badge": p.on_accent, "badge_text": p.accent},
            "complete": {"bg": p.ok_bg, "line": p.ok_line, "ink": p.ok, "badge": p.ok, "badge_text": p.surface},
            "ready": {"bg": p.surface, "line": p.accent, "ink": p.accent, "badge": p.surface, "badge_text": p.accent},
            "warn": {"bg": p.surface, "line": p.warn_line, "ink": p.warn, "badge": p.surface, "badge_text": p.warn},
            "locked": {"bg": p.soft, "line": p.line, "ink": p.muted, "badge": p.soft, "badge_text": p.muted},
        }[state]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        title_font, caption_font = QFont(self.font()), QFont(self.font())
        symbol_font = QFont(title_font)
        symbol_font.setFamily(SYMBOL_FONT)  # the check mark is not in the interface font: name the font that has it
        title_font.setBold(True)
        title_font.setPointSizeF(self.font().pointSizeF() + 1)
        caption_font.setPointSizeF(max(7.0, self.font().pointSizeF() - 0.5))
        for index, cell in enumerate(self._cells()):
            c = self._colors(self._state[index])
            painter.setBrush(QColor(c["bg"]))
            focused = self.hasFocus() and index == self._focus
            painter.setPen(QPen(QColor(self._palette.fg if focused else c["line"]), 1.4))
            painter.drawRoundedRect(cell.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
            size = 28.0
            badge = QRectF(cell.left() + 12, cell.center().y() - size / 2, size, size)
            painter.setBrush(QColor(c["badge"]))
            painter.setPen(QPen(QColor(c["badge_text"] if self._state[index] == "current" else c["ink"]), 2))
            painter.drawEllipse(badge.adjusted(1, 1, -1, -1))
            painter.setPen(QColor(c["badge_text"]))
            painter.setFont(symbol_font if self._state[index] == "complete" else title_font)
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "✓" if self._state[index] == "complete" else str(index + 1))
            left, room = badge.right() + 10, cell.right() - badge.right() - 20
            painter.setPen(QColor(c["ink"]))
            painter.setFont(title_font)
            painter.drawText(QRectF(left, cell.top() + 7, room, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             painter.fontMetrics().elidedText(self._titles[index], Qt.TextElideMode.ElideRight, int(room)))
            painter.setFont(caption_font)
            painter.drawText(QRectF(left, cell.top() + 27, room, 18), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             painter.fontMetrics().elidedText(self._caption[index], Qt.TextElideMode.ElideRight, int(room)))
        painter.end()

    def mousePressEvent(self, event) -> None:
        for index, cell in enumerate(self._cells()):
            if cell.contains(event.position()):
                self._focus = index
                self.click(index)
                return

    def mouseMoveEvent(self, event) -> None:
        hot = any(cell.contains(event.position()) and self._state[i] != "locked" for i, cell in enumerate(self._cells()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._focus = max(0, min(len(self._titles) - 1, self._focus + (1 if key == Qt.Key.Key_Right else -1)))
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.click(self._focus)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()


class FlowLayout(QLayout):
    """Items left to right, wrapping to the next line when the width is used up (so chips never run off the window)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._space, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line = max(line, hint.height())
        return y + line - rect.y()


class ChipRow(QWidget):
    """A row of small coloured notes: (kind, text) with kind ``ok``, ``warn``, ``bad`` or ``info``. It wraps when narrow and is
    only rebuilt when the chips change."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = FlowLayout(self)
        self._chips: list[tuple[str, str]] = []
        sizing = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sizing.setHeightForWidth(True)
        self.setSizePolicy(sizing)

    def chips(self) -> list[tuple[str, str]]:
        return list(self._chips)

    def set_chips(self, chips: Sequence[tuple[str, str]]) -> None:
        chips = [(kind, text) for kind, text in chips]
        if chips == self._chips:
            return
        self._chips = chips
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for kind, text in chips:
            label = QLabel(text, self)
            label.setProperty("chip", kind)
            self._flow.addWidget(label)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._flow.heightForWidth(width)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 26)


class ReadOnlyText(QTextBrowser):
    """Selectable, scrollable, read-only text for reports and release notes (plain, or the small Markdown of release notes)."""

    def __init__(self, parent: QWidget | None = None, *, monospace: bool = False) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        if monospace:
            font = QFont("Consolas")
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setPointSizeF(self.font().pointSizeF())
            self.setFont(font)
            self.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)

    def set_text(self, content: str) -> None:
        self.setPlainText(content)

    def set_markdown(self, content: str) -> None:
        """The small Markdown subset of release notes: headings, bullets, and plain lines (bold and code are shown plain)."""
        self.clear()
        cursor = self.textCursor()
        for number, line in enumerate(content.splitlines()):
            stripped = line.strip()
            plain = re.sub(r"`([^`]*)`", r"\1", re.sub(r"\*\*(.+?)\*\*", r"\1", stripped))
            block, char = QTextBlockFormat(), QTextCharFormat()
            if number:
                cursor.insertBlock()
            if stripped.startswith("#"):
                char.setFontWeight(QFont.Weight.DemiBold)
                char.setFontPointSize(self.font().pointSizeF() + 1)
                block.setTopMargin(8)
                block.setBottomMargin(2)
                text = plain.lstrip("#").strip()
            elif stripped.startswith(("- ", "* ")):
                block.setLeftMargin(28)
                block.setTextIndent(-16)
                text = "•  " + plain[2:]
            else:
                text = plain
            cursor.setBlockFormat(block)
            cursor.setCharFormat(char)
            cursor.insertText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)


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
    activated = Signal(int)  # double-click or Enter on a row
    cellPressed = Signal(int, int, int)  # row, column and the x of the pointer inside the cell, for text with a part to click
    cellHover = Signal(int, int, int)

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
        self.doubleClicked.connect(lambda index: self.activated.emit(index.row()))
        self.setMouseTracking(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.activated.emit(self.currentIndex().row())
        else:
            super().keyPressEvent(event)

    def _cell_at(self, event) -> tuple[int, int, int]:
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            return -1, -1, 0
        return index.row(), index.column(), event.position().toPoint().x() - self.visualRect(index).left()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.cellPressed.emit(*self._cell_at(event))

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self.cellHover.emit(*self._cell_at(event))

    def reset_view(self) -> None:
        self.scrollToTop()
        self.horizontalScrollBar().setValue(0)

    # what is on show, for the window's own checks and for tests
    def rows(self) -> list[tuple[str, ...]]:
        return list(self.table_model.rows)

    def headings(self) -> list[str]:
        return self.table_model.headings

    def tags(self) -> list[str]:
        return self.table_model.tags

    def cell_tags(self) -> dict[tuple[int, int], str]:
        return self.table_model.cell_tags

    def selected_index(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else None

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

    def selected_items(self) -> list[str]:
        items = self.items()
        return [items[row] for row in self.selected_rows() if row < len(items)]

    def reset_view(self) -> None:
        self.scrollToTop()

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

    The charts are laid out in "report points" (their text is sized in points), so they are drawn at that scale and the painter
    enlarges the result. The grid follows the width: charts side by side only while each gets ``MIN_CELL_WIDTH``, and an
    agreement panel with many appraisers grows taller instead of squeezing its plot away. ``x_scale`` is the horizontal scale of
    a capability histogram (``"auto"`` or ``"full"``). When an analysed item has no panel, ``note`` says which one it would need.
    """

    CELL_HEIGHT = 300
    MIN_HEIGHT = 210

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs: list[ChartSpec] = []
        self._cache: dict[tuple, list] = {}
        self._x_scale: str | None = None
        self._note = ""
        self._muted = "#526174"
        self._row_heights: list[float] = []
        self._columns_used = 1

    def set_specs(self, specs: Sequence[ChartSpec], x_scale: str | None = None, note: str = "", muted: str | None = None) -> None:
        self._specs, self._x_scale, self._note = list(specs), x_scale, note
        if muted:
            self._muted = muted
        self._cache.clear()
        self._relayout()
        self.update()

    def specs(self) -> list[ChartSpec]:
        return list(self._specs)

    def _columns(self) -> int:
        wanted = 1 if len(self._specs) <= 1 else 2
        return max(1, min(wanted, int(self.width() // MIN_CELL_WIDTH) or 1, len(self._specs) or 1))

    def _layout(self) -> tuple[int, float, list[float]]:
        """(columns, width of a cell, height of each row of cells), in report points."""
        columns = self._columns()
        cell_w = max(240.0, self.width() / CHART_SCALE / columns)
        rows = math.ceil(len(self._specs) / columns) if self._specs else 0
        base = max(self.MIN_HEIGHT / CHART_SCALE, self.CELL_HEIGHT / CHART_SCALE)
        heights = []
        for row in range(rows):
            extra = max((agreement_extra_height(spec, cell_w - 8, base - 6) for spec in self._specs[row * columns:(row + 1) * columns]),
                        default=0.0)
            heights.append(base + extra)
        return columns, cell_w, heights

    def _relayout(self) -> None:
        columns, _cell_w, heights = self._layout()
        self._columns_used, self._row_heights = columns, heights
        needed = int(sum(heights) * CHART_SCALE) if heights else (90 if self._note else 0)
        self.setMinimumHeight(needed)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        previous = (self._columns_used, tuple(self._row_heights))
        self._relayout()
        if (self._columns_used, tuple(self._row_heights)) != previous:
            self._cache.clear()

    def _primitives(self, index: int, width: float, height: float):
        key = (index, round(width), round(height), self._x_scale)
        if key not in self._cache:
            self._cache[key] = chart_primitives(self._specs[index], width, height, self._x_scale, True, 1.0)
        return self._cache[key]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))  # charts are drawn for print, so they stay on white in dark mode
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._note and not self._specs:
            painter.setPen(QColor(self._muted))
            painter.drawText(self.rect().adjusted(16, 16, -16, -16), int(Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), self._note)
            painter.end()
            return
        painter.scale(CHART_SCALE, CHART_SCALE)
        columns, cell_w, heights = self._layout()
        top = 0.0
        for row, height in enumerate(heights):
            for column in range(columns):
                index = row * columns + column
                if index < len(self._specs):
                    paint_primitives(painter, self._primitives(index, cell_w - 8, height - 6), column * cell_w + 4, top, self.font())
            top += height
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


__all__ = ["ActionTable", "Card", "ChartPanel", "ChipRow", "DataTable", "FlowLayout", "ReadOnlyText", "StepBar", "make_button",
           "paint_primitives", "repolish"]
