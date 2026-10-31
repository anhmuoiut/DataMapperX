"""One read-only table model for every table in the window.

Cells are turned into text once, when the table is set; ``data()`` then only returns what Qt asks for, and only for the
rows that are on screen. Row tags (``invalid``, ``missing``, ``out``, ``gap``) and cell tags (``pass``, ``caution``,
``fail``) tint the background, as they do in the tkinter grid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from ..palette import Palette

_Index = QModelIndex | QPersistentModelIndex

ALIGN = {"w": int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
         "e": int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
         "center": int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)}


def tints(p: Palette) -> dict[str, QColor]:
    bad, warn, ok = QColor(p.bad_bg), QColor(p.warn_bg), QColor(p.ok_bg)
    return {"invalid": bad, "out": bad, "fail": bad, "missing": warn, "gap": warn, "caution": warn, "pass": ok}


class TableModel(QAbstractTableModel):
    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self._tints = tints(palette)
        self._headings: tuple[str, ...] = ()
        self._rows: list[tuple[str, ...]] = []
        self._tags: Sequence[str] = ()
        self._cell_tags: Mapping[tuple[int, int], str] = {}
        self._aligns: tuple[int, ...] = ()

    # ------------------------------------------------------------------ what the view asks
    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headings)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._aligns[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:  # the whole text of a cell that is cut short
            return self._rows[index.row()][index.column()] or None
        if role == Qt.ItemDataRole.BackgroundRole:
            tag = self._cell_tags.get((index.row(), index.column())) or (self._tags[index.row()] if self._tags else "")
            return self._tints.get(tag)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headings[section]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.TextAlignmentRole:
            return self._aligns[section]
        return None

    # ------------------------------------------------------------------ what the window sets
    def set_table(self, headings: Sequence[str], rows: Sequence[Sequence[object]], tags: Sequence[str] | None = None,
                  aligns: Sequence[str] | None = None, cell_tags: Mapping[tuple[int, int], str] | None = None) -> None:
        self.beginResetModel()
        self._headings = tuple(headings)
        self._rows = [tuple("" if value is None else str(value) for value in row) for row in rows]
        self._tags = list(tags) if tags is not None else []
        self._cell_tags = dict(cell_tags) if cell_tags else {}
        self._aligns = tuple(ALIGN[a] for a in (aligns or ["w"] * len(self._headings)))
        self.endResetModel()

    def set_palette(self, palette: Palette) -> None:
        self._tints = tints(palette)
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self._headings) - 1),
                                  [Qt.ItemDataRole.BackgroundRole])

    def row_text(self, row: int) -> tuple[str, ...]:
        return self._rows[row]

    @property
    def rows(self) -> list[tuple[str, ...]]:
        return self._rows

    @property
    def tags(self) -> list[str]:
        return list(self._tags)
