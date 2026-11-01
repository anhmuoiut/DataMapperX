"""The dialog that maps the columns of a ratings table, names its categories, and shows the data as they will be analysed.

It only draws and collects: what the choices mean, and what they make of the file, is decided in ``statistics/ratings.py``.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

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
from .dialogs import Dialog

NONE = "(none)"  # the choice of a column the file does not have
PREVIEW_LIMIT = 100
PREVIEW_COLUMNS = (("item", "Test Item", 150, "w"), ("sample", "Sample ID", 130, "w"), ("appraiser", "Appraiser", 90, "w"),
                   ("trial", "Trial", 50, "center"), ("rating", "Rating", 100, "w"), ("standard", "Standard", 100, "w"))


class RatingsImportDialog(Dialog):
    """Choose what each column holds, rename categories if wanted, check the preview, then Import."""

    def __init__(self, parent, table: RatingsTable, on_done: Callable[[ImportedRatings], None]):
        super().__init__(parent, "Import ratings", min_size=(800, 620))
        self.table, self.on_done = table, on_done
        self.imported: ImportedRatings | None = None
        self.columns = {name: tk.StringVar() for name in FIELDS}
        self.assign_var = tk.BooleanVar(value=True)
        self.sheet_var = tk.StringVar(value=table.sheet)
        self.summary_var = tk.StringVar()
        self.message_var = tk.StringVar()
        self.names: dict[str, tk.StringVar] = {}  # a label of the file -> the category the user typed for it
        self.typed: dict[str, str] = {}  # what was typed, kept when the list of labels is rebuilt
        self._label_key: tuple[str, ...] | None = None
        self._quiet = False  # no refresh while the dialog sets several things at once

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        head = ttk.Frame(body)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(head, text=table.name, font=("Segoe UI Semibold", 10)).pack(side="left")
        self.sheet_box = ttk.Combobox(head, textvariable=self.sheet_var, values=list(table.sheets), state="readonly", width=20)
        if len(table.sheets) > 1:
            ttk.Label(head, text="Sheet").pack(side="left", padx=(16, 4))
            self.sheet_box.pack(side="left")
            self.sheet_box.bind("<<ComboboxSelected>>", self._sheet_changed)

        grid = ttk.Frame(body)
        grid.grid(row=1, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        self.boxes: dict[str, ttk.Combobox] = {}
        for index, name in enumerate(FIELDS):
            row, column = index % 3, 0 if index < 3 else 2
            text = FIELD_NAMES[name] + (" *" if name in REQUIRED else "")
            ttk.Label(grid, text=text).grid(row=row, column=column, sticky="w", padx=(0 if column == 0 else 16, 8), pady=3)
            box = ttk.Combobox(grid, textvariable=self.columns[name], state="readonly", width=22)
            box.grid(row=row, column=column + 1, sticky="ew", pady=3)
            self.boxes[name] = box
        self.trial_check = ttk.Checkbutton(body, text="No Trial column: number the ratings of each sample 1, 2, 3… in the order of the rows",
                                           variable=self.assign_var)
        self.trial_check.grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.labels_frame = ttk.Frame(body)
        self.labels_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        preview = ttk.Frame(body)
        preview.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.preview = ttk.Treeview(preview, columns=[key for key, *_ in PREVIEW_COLUMNS], show="headings", selectmode="browse", height=8)
        for key, title, width, anchor in PREVIEW_COLUMNS:
            self.preview.heading(key, text=title, anchor=anchor)
            self.preview.column(key, width=width, minwidth=40, anchor=anchor, stretch=key == "item")
        self.preview.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.preview.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=scroll.set)

        ttk.Label(body, textvariable=self.summary_var, font=("Segoe UI Semibold", 10)).grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.message = ttk.Label(body, textvariable=self.message_var, foreground=self.palette.warn, wraplength=740, justify="left")
        self.message.grid(row=6, column=0, sticky="w")
        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="left", padx=(0, 8))
        self.import_button = ttk.Button(buttons, text="Import", style="Accent.TButton", command=self._accept)
        self.import_button.pack(side="left")

        self._quiet = True
        self._load_columns()
        self._quiet = False
        for variable in (*self.columns.values(), self.assign_var):
            variable.trace_add("write", self._refresh)
        self._refresh()
        self.present(width=860, height=700)

    # ------------------------------------------------------------------ the file
    def _load_columns(self) -> None:
        """Offer the headers of the table, and start from the mapping its names suggest."""
        choices = [NONE, *self.table.headers]
        suggestion = suggest_mapping(self.table.headers)
        for name in FIELDS:
            self.boxes[name].configure(values=choices)
            self.columns[name].set(suggestion[name] or NONE)

    def _sheet_changed(self, _event=None) -> None:
        try:
            table = read_ratings_table(self.table.path, self.sheet_var.get())
        except (RatingsFormatError, OSError, ValueError) as exc:
            self.sheet_var.set(self.table.sheet)
            self.message_var.set(str(exc))
            return
        self.table, self.typed, self._label_key = table, {}, None
        self._quiet = True
        self._load_columns()
        self._quiet = False
        self._refresh()

    # ------------------------------------------------------------------ what is chosen
    def _chosen(self) -> dict[str, str]:
        return {name: ("" if variable.get() == NONE else variable.get()) for name, variable in self.columns.items()}

    def _mapping(self) -> RatingsMapping:
        pairs = category_mapping({label: variable.get() for label, variable in self.names.items()})
        return RatingsMapping(**self._chosen(), assign_trials=self.assign_var.get(), categories=pairs)

    def _fill_labels(self, mapping: RatingsMapping) -> None:
        """One row for each label of the Rating (and Standard) column, to rename it as a category; none when there are too many."""
        counts = label_counts(self.table, mapping) if mapping.rating in self.table.headers else []
        key = tuple(label for label, _ in counts)
        if key == self._label_key:
            return
        for label, variable in self.names.items():
            self.typed[label] = variable.get()
        self._label_key = key
        self.names = {}
        for child in self.labels_frame.winfo_children():
            child.destroy()
        if not counts:
            return
        ttk.Label(self.labels_frame, text="Categories", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", columnspan=8)
        if len(counts) > MAX_LABELS:
            ttk.Label(self.labels_frame, foreground=self.palette.warn, text=f"{len(counts)} different labels: that is too many for "
                      "categories. Check that the Rating column is the one that holds PASS, FAIL and the like.").grid(row=1, column=0, sticky="w", columnspan=8)
            return
        ttk.Label(self.labels_frame, text="The labels of the file are used as they are. Type a name to count a label as another category.",
                  foreground=self.palette.muted).grid(row=1, column=0, sticky="w", columnspan=8)
        for position, (label, count) in enumerate(counts):
            row, column = 2 + position // 4, position % 4 * 2
            cell = ttk.Frame(self.labels_frame)
            cell.grid(row=row, column=column, sticky="w", padx=(0, 16), pady=2)
            ttk.Label(cell, text=f"{label} ({count})", width=14).pack(side="left")
            variable = tk.StringVar(value=self.typed.get(label, label))
            variable.trace_add("write", self._refresh)
            ttk.Entry(cell, textvariable=variable, width=10).pack(side="left")
            self.names[label] = variable

    # ------------------------------------------------------------------ the preview
    def _refresh(self, *_) -> None:
        if self._quiet:
            return
        self._fill_labels(self._mapping())
        mapping = self._mapping()
        self.trial_check.configure(state="disabled" if mapping.trial else "normal")
        self.preview.delete(*self.preview.get_children())
        try:
            imported = build_ratings(self.table, mapping)
        except RatingsFormatError as exc:
            self.imported = None
            self.summary_var.set("")
            self.message_var.set(str(exc))
            self.import_button.configure(state="disabled")
            return
        self.imported = imported
        for index, row in enumerate(imported.dataset.observations[:PREVIEW_LIMIT]):
            self.preview.insert("", "end", iid=str(index), values=(row.test_item, row.sample_id, row.operator or "1", row.trial,
                                                                    row.value, row.standard))
        shown = min(PREVIEW_LIMIT, imported.ratings)
        noun = "appraiser" if imported.appraisers == 1 else "appraisers"
        self.summary_var.set(f"{imported.samples} samples · {imported.appraisers} {noun} · {imported.trials} trials per sample · "
                             f"{len(imported.categories)} categories: {', '.join(imported.categories[:6])}"
                             + (" …" if len(imported.categories) > 6 else ""))
        notes = list(imported.warnings)
        if shown < imported.ratings:
            notes.append(f"Showing the first {shown} of {imported.ratings} ratings.")
        self.message_var.set("  ".join(notes))
        self.import_button.configure(state="normal")

    def _accept(self) -> None:
        if self.imported is None:
            return
        self.on_done(self.imported)
        self.close()
