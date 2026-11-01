"""The dialog that maps the columns of a ratings table, names its categories, and shows the data as they will be analysed.

It only draws and collects: what the choices mean, and what they make of the file, is decided in ``statistics/ratings.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QWidget

from ..statistics.ratings import (
    FIELD_NAMES,
    FIELDS,
    MAX_LABELS,
    REQUIRED,
    ImportedRatings,
    RatingsFormatError,
    RatingsMapping,
    RatingsTable,
    build_ratings,
    category_mapping,
    label_counts,
    read_ratings_table,
    suggest_mapping,
)
from .dialogs import Dialog, label
from .widgets import DataTable, make_button

NONE = "(none)"  # the choice of a column the file does not have
PREVIEW_LIMIT = 100
PREVIEW_HEADINGS = ("Test Item", "Sample ID", "Appraiser", "Trial", "Rating", "Standard")


class RatingsImportDialog(Dialog):
    """Choose what each column holds, rename categories if wanted, check the preview, then Import."""

    def __init__(self, parent: QWidget, table: RatingsTable, on_done: Callable[[ImportedRatings], None]) -> None:
        super().__init__(parent, "Import ratings", size=(860, 700), min_size=(800, 620))
        self.table, self.on_done = table, on_done
        self.imported: ImportedRatings | None = None
        self.names: dict[str, QLineEdit] = {}  # a label of the file -> the category the user typed for it
        self.typed: dict[str, str] = {}  # what was typed, kept when the list of labels is rebuilt
        self._label_key: tuple[str, ...] | None = None
        self._quiet = False  # no refresh while the dialog sets several things at once

        head = QHBoxLayout()
        head.addWidget(label(table.name, "heading"))
        head.addStretch(1)
        self.sheet_box = QComboBox()
        self.sheet_box.addItems(list(table.sheets))
        self.sheet_box.setCurrentText(table.sheet)
        if len(table.sheets) > 1:
            head.addWidget(label("Sheet"))
            head.addWidget(self.sheet_box)
            self.sheet_box.activated.connect(lambda _index: self._sheet_changed())
        self.layout_root.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.boxes: dict[str, QComboBox] = {}
        for index, name in enumerate(FIELDS):
            row, column = index % 3, 0 if index < 3 else 2
            grid.addWidget(label(FIELD_NAMES[name] + (" *" if name in REQUIRED else "")), row, column)
            box = QComboBox()
            box.setMinimumWidth(200)
            box.currentTextChanged.connect(self._refresh)
            grid.addWidget(box, row, column + 1)
            self.boxes[name] = box
        self.layout_root.addLayout(grid)
        self.trial_check = QCheckBox("No Trial column: number the ratings of each sample 1, 2, 3… in the order of the rows")
        self.trial_check.setChecked(True)
        self.trial_check.toggled.connect(self._refresh)
        self.layout_root.addWidget(self.trial_check)
        self.labels_frame = QWidget()
        self.labels_grid = QGridLayout(self.labels_frame)
        self.labels_grid.setContentsMargins(0, 6, 0, 0)
        self.layout_root.addWidget(self.labels_frame)

        self.preview = DataTable(self.palette_tokens)
        self.preview.set_table(PREVIEW_HEADINGS, [], aligns=["w", "w", "w", "center", "w", "w"], stretch=0)
        self.layout_root.addWidget(self.preview, 1)
        self.summary = label("", "heading")
        self.message = label("", "warn", wrap=True)
        self.layout_root.addWidget(self.summary)
        self.layout_root.addWidget(self.message)
        self.import_button = make_button("Import", self._accept, primary=True)
        self.button_row(make_button("Cancel", self.close), self.import_button)

        self._quiet = True
        self._load_columns()
        self._quiet = False
        self._refresh()

    # ------------------------------------------------------------------ the file
    def _load_columns(self) -> None:
        """Offer the headers of the table, and start from the mapping its names suggest."""
        choices = [NONE, *self.table.headers]
        suggestion = suggest_mapping(self.table.headers)
        for name in FIELDS:
            box = self.boxes[name]
            box.blockSignals(True)
            box.clear()
            box.addItems(choices)
            box.setCurrentText(suggestion[name] or NONE)
            box.blockSignals(False)

    def _sheet_changed(self) -> None:
        try:
            table = read_ratings_table(self.table.path, self.sheet_box.currentText())
        except (RatingsFormatError, OSError, ValueError) as exc:
            self.sheet_box.setCurrentText(self.table.sheet)
            self.message.setText(str(exc))
            return
        self.table, self.typed, self._label_key = table, {}, None
        self._quiet = True
        self._load_columns()
        self._quiet = False
        self._refresh()

    # ------------------------------------------------------------------ what is chosen
    def _chosen(self) -> dict[str, str]:
        return {name: ("" if box.currentText() == NONE else box.currentText()) for name, box in self.boxes.items()}

    def _mapping(self) -> RatingsMapping:
        pairs = category_mapping({name: edit.text() for name, edit in self.names.items()})
        return RatingsMapping(**self._chosen(), assign_trials=self.trial_check.isChecked(), categories=pairs)

    def _fill_labels(self, mapping: RatingsMapping) -> None:
        """One row for each label of the Rating (and Standard) column, to rename it as a category; none when there are too many."""
        counts = label_counts(self.table, mapping) if mapping.rating in self.table.headers else []
        key = tuple(name for name, _ in counts)
        if key == self._label_key:
            return
        for name, edit in self.names.items():
            self.typed[name] = edit.text()
        self._label_key = key
        self.names = {}
        while self.labels_grid.count():
            item = self.labels_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not counts:
            return
        self.labels_grid.addWidget(label("Categories", "heading"), 0, 0, 1, 8)
        if len(counts) > MAX_LABELS:
            self.labels_grid.addWidget(label(f"{len(counts)} different labels: that is too many for categories. Check that the Rating "
                                             "column is the one that holds PASS, FAIL and the like.", "warn", wrap=True), 1, 0, 1, 8)
            return
        self.labels_grid.addWidget(label("The labels of the file are used as they are. Type a name to count a label as another "
                                         "category.", "muted", wrap=True), 1, 0, 1, 8)
        for position, (name, count) in enumerate(counts):
            row, column = 2 + position // 4, position % 4 * 2
            self.labels_grid.addWidget(label(f"{name} ({count})"), row, column)
            edit = QLineEdit(self.typed.get(name, name))
            edit.setMaximumWidth(110)
            edit.textChanged.connect(self._refresh)
            self.labels_grid.addWidget(edit, row, column + 1)
            self.names[name] = edit

    # ------------------------------------------------------------------ the preview
    def _refresh(self, *_args) -> None:
        if self._quiet:
            return
        self._fill_labels(self._mapping())
        mapping = self._mapping()
        self.trial_check.setEnabled(not mapping.trial)
        try:
            imported = build_ratings(self.table, mapping)
        except RatingsFormatError as exc:
            self.imported = None
            self.preview.table_model.set_rows([])
            self.summary.setText("")
            self.message.setText(str(exc))
            self.import_button.setEnabled(False)
            return
        self.imported = imported
        self.preview.table_model.set_rows(
            [(row.test_item, row.sample_id, row.operator or "1", row.trial, row.value, row.standard)
             for row in imported.dataset.observations[:PREVIEW_LIMIT]])
        self.preview.fit_columns(stretch=0)
        shown = min(PREVIEW_LIMIT, imported.ratings)
        noun = "appraiser" if imported.appraisers == 1 else "appraisers"
        self.summary.setText(f"{imported.samples} samples · {imported.appraisers} {noun} · {imported.trials} trials per sample · "
                             f"{len(imported.categories)} categories: {', '.join(imported.categories[:6])}"
                             + (" …" if len(imported.categories) > 6 else ""))
        notes = list(imported.warnings)
        if shown < imported.ratings:
            notes.append(f"Showing the first {shown} of {imported.ratings} ratings.")
        self.message.setText("  ".join(notes))
        self.import_button.setEnabled(True)

    def _accept(self) -> None:
        if self.imported is None:
            return
        self.on_done(self.imported)
        self.close()
