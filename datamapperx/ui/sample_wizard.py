"""Set up a profile from a sample log, without writing a regular expression.

The person picks one example file. The app works out the layout (Excel columns, serial number cell, or the
standard test-log patterns), shows exactly which parts of the sample it reads, and lets them correct it:
for Excel by choosing columns by their headings, for text logs by selecting text in the sample and pressing
what it is.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from ..config import APP_TITLE, EXCEL_FILE_EXTENSIONS, TEXT_FILE_EXTENSIONS
from ..parsing import extract_sn_from_text, read_text_file
from ..patterns import (
    RULE_FOR_BLANK,
    RULES,
    TemplateError,
    compile_template,
    sn_regex_from_example,
    template_from_marks,
)
from ..profiles import PATTERN_FIELDS, patterns_from_profile, text_profile_from_patterns, validate_profile
from ..sampling import (
    Detection,
    FolderCheck,
    Highlight,
    Preview,
    WorkbookSketch,
    annotate_text,
    check_files,
    detect_excel,
    detect_text,
    is_excel,
    preview_profile,
    sibling_files,
)
from ..utils import looks_like_cell_coordinate, parse_positive_int
from .dialogs import Dialog
from .tasks import TaskRunner
from .widgets import UndoableEntry

logger = logging.getLogger(__name__)

NONE_LABEL = "(none)"
MAX_VIEW_LINES = 1500
MAX_ANNOTATED_LINES = 20000
REFRESH_MS = 280
FOLDER_CHECK_FILES = 8

# Colours for the parts of the sample that the profile reads, per theme.
ROLE_COLORS = {
    "light": {
        "block": "#eaf2fc", "measure": "#edf7ef", "component": "#b9d7fa", "measured": "#b4e5c6",
        "unit": "#dccbf5", "min": "#ffd9a0", "max": "#ffc0c7", "serial": "#fff09a",
    },
    "dark": {
        "block": "#1f2f43", "measure": "#1f3328", "component": "#2a5d94", "measured": "#27663f",
        "unit": "#59447f", "min": "#80571a", "max": "#80333c", "serial": "#7d6d1a",
    },
}
LEGEND = (("component", "Component"), ("measured", "Measured value"), ("unit", "Unit"),
          ("min", "Lower limit"), ("max", "Upper limit"), ("serial", "Serial number"))
MARK_BUTTONS = (("Component", "Component"), ("Measured value", "Measured"), ("Unit", "Unit"),
                ("Lower limit", "Min"), ("Upper limit", "Max"), ("Ignore", "Any"))
RULE_ROWS = (
    ("block", "Component line"),
    ("measure", "Measurement line"),
    ("lim2", "Limits, style A (optional)"),
    ("lim3", "Limits, style B (optional)"),
)
EXCEL_COLUMNS = (
    ("col_component", "component_col", "Component / test name", True),
    ("col_measured", "measure_col", "Measured value", True),
    ("col_min", "min_col", "Lower limit", False),
    ("col_max", "max_col", "Upper limit", False),
    ("col_unit", "unit_col", "Unit", False),
)


class SampleWizard(Dialog):
    """``on_done(name, profile)`` runs when the person accepts the settings."""

    def __init__(
        self,
        parent: tk.Misc,
        on_done: Callable[[str, dict[str, Any]], None],
        *,
        initial: dict[str, Any] | None = None,
        initial_name: str = "",
        sample: Path | None = None,
    ) -> None:
        super().__init__(parent, "Set up from a sample log", modal=True, min_size=(940, 620))
        self.on_done = on_done
        self._initial = initial
        self._name = initial_name
        self.sample: Path | None = None
        self.siblings: list[Path] = []
        self.kind = ""
        self.sketch: WorkbookSketch | None = None
        self.detection: Detection | None = None
        self._lines: list[str] = []
        self._annotated_text = ""
        self._extensions = ",".join(TEXT_FILE_EXTENSIONS)
        self._marks: dict[str, tuple[int, list[tuple[int, int, str]]]] = {}
        self._last_rule = ""
        self._generation = 0
        self._refresh_job: str | None = None
        self._loading = False
        self._tasks = TaskRunner(self)

        names = (
            "sample", "findings", "problem", "status", "folder_status", "block", "measure", "lim2", "lim3",
            "sn_example", "sn_mode", "sn_sheet", "sn_cell", "sn_value", "data_sheet", "row_start",
            *(var for var, *_ in EXCEL_COLUMNS),
        )
        self.vars: dict[str, tk.StringVar] = {name: tk.StringVar() for name in names}
        self.vars["sn_mode"].set("cell")
        self.vars["row_start"].set("2")
        self.skip_empty = tk.BooleanVar(value=True)
        self.rule_status = {key: tk.StringVar() for key, _title in RULE_ROWS}
        self.rule_status["sn_example"] = tk.StringVar()
        self._rule_labels: dict[str, ttk.Label] = {}

        self._build()
        for name, var in self.vars.items():
            if name not in {"sample", "findings", "problem", "status", "folder_status", "sn_value"}:
                var.trace_add("write", self._on_change)
        self.skip_empty.trace_add("write", self._on_change)
        for name in ("data_sheet", "row_start"):
            self.vars[name].trace_add("write", self._on_table_change)
        self.present(width=1040, height=min(860, max(620, self.winfo_screenheight() - 90)))

        if sample is not None:
            self.after_idle(lambda: self.load_sample(sample))
        else:
            self.after(120, self.choose_sample)

    # ------------------------------------------------------------------ layout
    def _surface(self, parent: tk.Misc, **grid: Any) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Surface.TFrame", padding=14)
        frame.grid(**grid)
        return frame

    def _build(self) -> None:
        outer = self.outer = ttk.Frame(self, padding=(18, 14, 18, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        top = self._surface(outer, row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="1   Choose one example log", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.vars["sample"], style="SurfaceMuted.TLabel", wraplength=860, justify="left").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.choose_button = ttk.Button(top, text="Choose file…", command=self.choose_sample)
        self.choose_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.findings = ttk.Label(top, textvariable=self.vars["findings"], style="SurfaceHint.TLabel", wraplength=940, justify="left")
        self.findings.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.workspace = self._surface(outer, row=1, column=0, sticky="nsew", pady=(0, 10))
        self.workspace.columnconfigure(0, weight=1)
        self.workspace.rowconfigure(1, weight=1)
        ttk.Label(self.workspace, text="2   Tell the app where the data is", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.placeholder = ttk.Label(
            self.workspace, style="SurfaceHint.TLabel", justify="center", anchor="center",
            text="Pick an example log file first. The app will look at it and fill in the settings for you.",
        )
        self.placeholder.grid(row=1, column=0, sticky="nsew")
        self.text_panel = self._build_text_panel(self.workspace)
        self.excel_panel = self._build_excel_panel(self.workspace)

        result = self.result = ttk.Frame(outer, style="Surface.TFrame")
        result.columnconfigure(0, weight=1)
        ttk.Label(result, text="3   Check what will be read", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.status_label = ttk.Label(result, textvariable=self.vars["status"], style="SurfaceMuted.TLabel", wraplength=940, justify="left")
        self.status_label.grid(row=1, column=0, sticky="w", pady=(4, 6))
        table = ttk.Frame(result, style="Surface.TFrame")
        table.grid(row=2, column=0, sticky="ew")
        table.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(table, columns=("measured", "min", "max", "unit"), height=5, selectmode="none")
        self.table.heading("#0", text="Component", anchor="w")
        for column, title, width in (("measured", "Measured", 120), ("min", "Min", 112), ("max", "Max", 112), ("unit", "Unit", 56)):
            self.table.heading(column, text=title, anchor="w")
            self.table.column(column, width=width, minwidth=60, stretch=False, anchor="w")
        self.table.column("#0", width=220, minwidth=120, stretch=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.folder_label = ttk.Label(result, textvariable=self.vars["folder_status"], style="SurfaceHint.TLabel", wraplength=940, justify="left")
        self.folder_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.problem_label = ttk.Label(footer, textvariable=self.vars["problem"], style="Bad.TLabel", wraplength=700, justify="left")
        self.problem_label.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Cancel", command=self.close).grid(row=0, column=1, padx=(8, 8))
        self.accept_button = ttk.Button(footer, text="Use these settings", style="Accent.TButton", command=self.accept, state="disabled")
        self.accept_button.grid(row=0, column=2)

    # ---- text logs
    def _build_text_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Surface.TFrame")
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(0, weight=1)

        rules = ttk.Frame(panel, style="Surface.TFrame")
        rules.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        rules.columnconfigure(0, weight=1)
        def heading(row: int, title: str, key: str) -> None:
            ttk.Label(rules, text=title, style="Surface.TLabel").grid(row=row, column=0, sticky="w")
            status = ttk.Label(rules, textvariable=self.rule_status[key], style="SurfaceHint.TLabel")
            status.grid(row=row, column=0, columnspan=2, sticky="e")
            self._rule_labels[key] = status

        row = 0
        heading(row, "Serial number looks like", "sn_example")
        row += 1
        sn_row = ttk.Frame(rules, style="Surface.TFrame")
        sn_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 10))
        sn_row.columnconfigure(0, weight=1)
        self.sn_entry = UndoableEntry(sn_row, textvariable=self.vars["sn_example"], width=32)
        self.sn_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(sn_row, text="Use selection", style="Compact.TButton", command=self._mark_serial).grid(row=0, column=1)

        self.rule_entries: dict[str, UndoableEntry] = {}
        for key, title in RULE_ROWS:
            row += 1
            heading(row, title, key)
            row += 1
            entry = UndoableEntry(rules, textvariable=self.vars[key], width=32, font=("Consolas", 10))
            entry.grid(row=row, column=0, sticky="ew", pady=(3, 10))
            entry.bind("<Key>", lambda _e, k=key: self._marks.pop(k, None), add="+")
            self.rule_entries[key] = entry
            ttk.Button(rules, text="×", width=3, style="Compact.TButton", command=lambda k=key: self._clear_rule(k)).grid(
                row=row, column=1, padx=(6, 0), pady=(3, 10)
            )
        row += 1
        ttk.Label(
            rules, style="SurfaceHint.TLabel", wraplength=340, justify="left",
            text="A pattern is text from the log with the parts that change replaced by blanks: [Component], "
                 "[Measured], [Unit], [Min], [Max], or [Any] for a part to skip.",
        ).grid(row=row, column=0, columnspan=2, sticky="w")

        right = self.text_right = ttk.Frame(panel, style="Surface.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        ttk.Label(
            right, style="Surface.TLabel", wraplength=560, justify="left",
            text="Select the part of a line that changes, then press what it is:",
        ).grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(right, style="Surface.TFrame")
        buttons.grid(row=1, column=0, sticky="w", pady=(6, 6))
        for column, (label, blank) in enumerate(MARK_BUTTONS):
            ttk.Button(buttons, text=label, style="Compact.TButton", command=lambda b=blank: self._mark(b)).grid(
                row=0, column=column, padx=(0 if column == 0 else 4, 0)
            )
        view = ttk.Frame(right, style="Surface.TFrame")
        view.grid(row=2, column=0, sticky="nsew")
        view.columnconfigure(0, weight=1)
        view.rowconfigure(0, weight=1)
        colors = ROLE_COLORS[self.palette.mode]
        self.viewer = tk.Text(
            view, wrap="none", height=12, width=60, relief="flat", borderwidth=0, padx=8, pady=6,
            font=("Consolas", 10), bg=self.palette.surface, fg=self.palette.fg, insertbackground=self.palette.fg,
            highlightthickness=1, highlightbackground=self.palette.line, highlightcolor=self.palette.accent,
            exportselection=False, selectbackground=self.palette.accent,
            selectforeground="#ffffff" if self.palette.mode == "light" else "#0b1a2a",
            inactiveselectbackground=self.palette.accent, cursor="xterm",
        )
        yscroll = ttk.Scrollbar(view, orient="vertical", command=self.viewer.yview)
        xscroll = ttk.Scrollbar(view, orient="horizontal", command=self.viewer.xview)
        self.viewer.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.viewer.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        for role in ("block", "measure", "component", "measured", "unit", "min", "max", "serial"):
            self.viewer.tag_configure(role, background=colors[role])
        self.viewer.tag_raise("sel")
        self.viewer.configure(state="disabled")
        self.viewer.bind("<Button-1>", lambda _e: self.viewer.focus_set(), add="+")

        legend = ttk.Frame(right, style="Surface.TFrame")
        legend.grid(row=3, column=0, sticky="w", pady=(6, 0))
        for column, (role, label) in enumerate(LEGEND):
            tk.Label(legend, text=f" {label} ", bg=colors[role], fg=self.palette.fg, font=("Segoe UI", 9), padx=2).grid(
                row=0, column=column, padx=(0 if column == 0 else 5, 0)
            )
        return panel

    # ---- Excel workbooks
    def _build_excel_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Surface.TFrame")
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(3, weight=1)
        v = self.vars

        ttk.Label(panel, text="Where is the serial number?", style="Surface.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        cell_row = ttk.Frame(panel, style="Surface.TFrame")
        cell_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 2))
        ttk.Radiobutton(cell_row, text="In a cell", style="Surface.TRadiobutton", variable=v["sn_mode"], value="cell").grid(row=0, column=0, padx=(0, 10))
        ttk.Label(cell_row, text="Sheet", style="Surface.TLabel").grid(row=0, column=1, padx=(0, 6))
        self.sn_sheet_combo = ttk.Combobox(cell_row, textvariable=v["sn_sheet"], state="readonly", width=16)
        self.sn_sheet_combo.grid(row=0, column=2, padx=(0, 10))
        ttk.Label(cell_row, text="Cell", style="Surface.TLabel").grid(row=0, column=3, padx=(0, 6))
        UndoableEntry(cell_row, textvariable=v["sn_cell"], width=7).grid(row=0, column=4, padx=(0, 10))
        ttk.Label(cell_row, textvariable=v["sn_value"], style="SurfaceMuted.TLabel").grid(row=0, column=5)
        name_row = ttk.Frame(panel, style="Surface.TFrame")
        name_row.grid(row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Radiobutton(name_row, text="In the file name, looking like", style="Surface.TRadiobutton", variable=v["sn_mode"], value="example").grid(row=0, column=0, padx=(0, 10))
        UndoableEntry(name_row, textvariable=v["sn_example"], width=26).grid(row=0, column=1, padx=(0, 10))

        ttk.Separator(panel, style="Surface.TSeparator").grid(row=3, column=0, columnspan=4, sticky="ew", pady=8)

        ttk.Label(panel, text="Where is the table of results?", style="Surface.TLabel").grid(row=4, column=0, columnspan=4, sticky="w")
        table_row = ttk.Frame(panel, style="Surface.TFrame")
        table_row.grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 8))
        ttk.Label(table_row, text="Sheet", style="Surface.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.data_sheet_combo = ttk.Combobox(table_row, textvariable=v["data_sheet"], state="readonly", width=18)
        self.data_sheet_combo.grid(row=0, column=1, padx=(0, 18))
        ttk.Label(table_row, text="Data starts on row", style="Surface.TLabel").grid(row=0, column=2, padx=(0, 6))
        ttk.Spinbox(table_row, from_=1, to=999, width=5, textvariable=v["row_start"]).grid(row=0, column=3, padx=(0, 12))
        ttk.Label(table_row, text="The row above it should hold the column headings.", style="SurfaceHint.TLabel").grid(row=0, column=4)

        self.column_combos: dict[str, ttk.Combobox] = {}
        for index, (var, _key, title, _required) in enumerate(EXCEL_COLUMNS):
            row, base = 6 + index // 2, (index % 2) * 2
            ttk.Label(panel, text=title, style="Surface.TLabel").grid(row=row, column=base, sticky="w", pady=3, padx=(0, 10))
            combo = ttk.Combobox(panel, textvariable=v[var], state="readonly", width=34)
            combo.grid(row=row, column=base + 1, sticky="ew", pady=3, padx=(0, 18))
            self.column_combos[var] = combo
        ttk.Checkbutton(
            panel, text="Ignore heading rows that have no result", variable=self.skip_empty, style="Surface.TCheckbutton"
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(6, 0))
        return panel

    # ------------------------------------------------------------------ choosing and loading the sample
    def choose_sample(self) -> None:
        excel_types = " ".join(f"*{e}" for e in EXCEL_FILE_EXTENSIONS)
        text_types = " ".join(f"*{e}" for e in TEXT_FILE_EXTENSIONS)
        chosen = filedialog.askopenfilename(
            parent=self, title="Choose one example log",
            filetypes=[("Log files", f"{text_types} {excel_types}"), ("All files", "*.*")],
        )
        if chosen:
            self.load_sample(Path(chosen))

    def load_sample(self, path: Path) -> None:
        self._loading = True
        try:
            siblings = sibling_files(path)
            if is_excel(path):
                sketch = WorkbookSketch.load(path)
                detection = detect_excel(path, siblings, sketch)
                kind, lines = "excel", []
            else:
                text = read_text_file(path)
                detection = detect_text(path, siblings)
                kind, sketch, lines = "text", None, text.splitlines()
        except (ValueError, OSError) as exc:
            self._loading = False
            self.vars["findings"].set(f"Could not open that file: {str(exc).splitlines()[0]}")
            return

        self.sample, self.siblings, self.kind, self.sketch, self.detection = path, siblings, kind, sketch, detection
        self._lines = lines
        self._annotated_text = "\n".join(lines[:MAX_ANNOTATED_LINES])
        self._marks.clear()
        self.vars["sample"].set(f"{path.name}    in    {path.parent}")
        self._extensions = str(detection.profile.get("file_extensions") or path.suffix.lower())
        self.placeholder.grid_remove()
        self.text_panel.grid_remove()
        self.excel_panel.grid_remove()

        base = detection.profile
        custom_rules: list[str] = []
        if self._initial and self._initial.get("type", "text") == kind:
            base = self._initial
            self._extensions = str(base.get("file_extensions") or self._extensions)
            if kind == "text":
                custom_rules = patterns_from_profile(base)[1]
        if kind == "excel":
            self.excel_panel.grid(row=1, column=0, sticky="nsew")
            self._show_excel(base)
        else:
            self.text_panel.grid(row=1, column=0, sticky="nsew")
            self._show_text(base)
        self._place_result()

        notes = list(detection.notes) if base is detection.profile else ["Your saved settings are loaded."]
        if custom_rules:
            names = ", ".join(title for key, title in RULE_ROWS if key in custom_rules)
            notes.append(f"{names}: written as a regular expression, which cannot be shown here. It is replaced if you save.")
        self.vars["findings"].set("  ".join([*notes, *detection.warnings]))
        self.findings.configure(style="SurfaceWarn.TLabel" if detection.warnings or custom_rules else "SurfaceHint.TLabel")
        self._loading = False
        self.accept_button.configure(state="normal")
        self._refresh()

    def _place_result(self) -> None:
        """Text logs have the sample on screen, so the result goes right under it; Excel forms put it below."""
        if self.kind == "text":
            self.result.configure(padding=0)
            self.result.grid(in_=self.text_right, row=4, column=0, sticky="ew", pady=(10, 0))
            self.table.configure(height=4)
        else:
            self.result.configure(padding=14)
            self.result.grid(in_=self.outer, row=2, column=0, sticky="ew", pady=(0, 10))
            self.table.configure(height=3)

    def _show_text(self, profile: dict[str, Any]) -> None:
        patterns, _custom = patterns_from_profile(profile)
        for key in PATTERN_FIELDS:
            self.vars[key].set(patterns.get(key, ""))
        self.vars["sn_example"].set(str(profile.get("sn_example") or self._derive_example(profile)))
        self._render_viewer()

    def _show_excel(self, profile: dict[str, Any]) -> None:
        assert self.sketch is not None
        names = self.sketch.names
        for combo in (self.sn_sheet_combo, self.data_sheet_combo):
            combo.configure(values=names)
        data_sheet = str(profile.get("data_sheet") or "")
        self.vars["data_sheet"].set(data_sheet if data_sheet in names else (names[1] if len(names) > 1 else names[0]))
        self.vars["row_start"].set(str(profile.get("row_start") or "2"))
        self._fill_columns(profile)
        self.skip_empty.set(profile.get("skip_empty_rows", True) is not False)

        rule = str(profile.get("sn_regex") or "").strip()
        sn_sheet = str(profile.get("sn_sheet") or "")
        self.vars["sn_sheet"].set(sn_sheet if sn_sheet in names else next((n for n in names if n != self.vars["data_sheet"].get()), names[0]))
        if looks_like_cell_coordinate(rule):
            self.vars["sn_mode"].set("cell")
            self.vars["sn_cell"].set(rule.upper())
            self.vars["sn_example"].set(str(profile.get("sn_example") or ""))
        else:
            self.vars["sn_mode"].set("example")
            self.vars["sn_cell"].set("")
            self.vars["sn_example"].set(str(profile.get("sn_example") or self._derive_example(profile)))

    def _derive_example(self, profile: dict[str, Any]) -> str:
        """An example serial number for a profile that stores only a pattern: what that pattern finds in the sample."""
        rule = str(profile.get("sn_regex") or "").strip()
        if not rule or self.sample is None or looks_like_cell_coordinate(rule):
            return ""
        try:
            return extract_sn_from_text(self.sample.name, rule) or extract_sn_from_text(self._annotated_text, rule)
        except ValueError:
            return ""

    # ------------------------------------------------------------------ Excel columns
    def _fill_columns(self, profile: dict[str, Any] | None = None) -> None:
        """List the sheet's columns by heading. ``profile`` selects columns from saved letters; otherwise keep the current ones."""
        if self.sketch is None:
            return
        try:
            row_start = parse_positive_int(self.vars["row_start"].get(), "Row")
        except ValueError:
            return
        choices = self.sketch.columns(self.vars["data_sheet"].get(), row_start)
        by_letter = {c.letter: c.label for c in choices}
        labels = [c.label for c in choices]
        for var, key, _title, required in EXCEL_COLUMNS:
            combo = self.column_combos[var]
            combo.configure(values=labels if required else [NONE_LABEL, *labels])
            current = str(profile.get(key) or "").upper() if profile is not None else self._letter(var)
            self.vars[var].set(by_letter.get(current, "" if required else NONE_LABEL))

    def _letter(self, var: str) -> str:
        value = self.vars[var].get()
        return "" if not value or value == NONE_LABEL else value.split()[0].upper()

    # ------------------------------------------------------------------ the sample viewer (text logs)
    def _render_viewer(self) -> None:
        shown = self._lines[:MAX_VIEW_LINES]
        self.viewer.configure(state="normal")
        self.viewer.delete("1.0", tk.END)
        self.viewer.insert("1.0", "\n".join(shown))
        if len(self._lines) > MAX_VIEW_LINES:
            self.viewer.insert(tk.END, f"\n… showing the first {MAX_VIEW_LINES} of {len(self._lines)} lines")
        self.viewer.configure(state="disabled")

    def _paint(self, marks: list[Highlight]) -> None:
        for role in ("block", "measure", "component", "measured", "unit", "min", "max", "serial"):
            self.viewer.tag_remove(role, "1.0", tk.END)
        for mark in marks:
            if mark.line < MAX_VIEW_LINES:
                self.viewer.tag_add(mark.role, f"{mark.line + 1}.{mark.start}", f"{mark.line + 1}.{mark.end}")
        self.viewer.tag_raise("sel")

    def _selection(self) -> tuple[int, int, int]:
        """(line index, start, end) of the selected text, trimmed; raises ``TemplateError`` when it cannot be used."""
        try:
            first, last = self.viewer.index("sel.first"), self.viewer.index("sel.last")
        except tk.TclError:
            raise TemplateError("Select some text in the sample first.") from None
        line1, col1 = (int(n) for n in first.split("."))
        line2, col2 = (int(n) for n in last.split("."))
        if line1 > min(len(self._lines), MAX_VIEW_LINES):
            raise TemplateError("Select text from the log, not from this note.")
        text = self._lines[line1 - 1]
        if line2 == line1 + 1 and col2 == 0:
            col2 = len(text)
        elif line2 != line1:
            raise TemplateError("Select text within a single line.")
        chosen = text[col1:col2]
        col1 += len(chosen) - len(chosen.lstrip())
        col2 -= len(chosen) - len(chosen.rstrip())
        if col2 <= col1:
            raise TemplateError("Select some text in the sample first.")
        return line1 - 1, col1, col2

    def _limits_key(self, line_index: int) -> str:
        for key in ("lim2", "lim3"):
            state = self._marks.get(key)
            if state and state[0] == line_index:
                return key
        return next((k for k in ("lim2", "lim3") if not self.vars[k].get().strip()), "lim2")

    def _mark(self, blank: str) -> None:
        try:
            line_index, start, end = self._selection()
            line = self._lines[line_index]
            rule = RULE_FOR_BLANK.get(blank) or self._last_rule
            if not rule:
                raise TemplateError("Mark a component or a measured value first, then use Ignore for parts that change.")
            key = {"block": "block", "measure": "measure", "limits": self._limits_key(line_index)}[rule]
            source, marks = self._marks.get(key, (line_index, []))
            if source != line_index:
                marks = []
            marks = [m for m in marks if m[2] != blank or blank == "Any"]
            marks = [m for m in marks if m[1] <= start or m[0] >= end]
            marks.append((start, end, blank))
            self.vars[key].set(template_from_marks(line, marks, rule))
        except TemplateError as exc:
            self.vars["problem"].set(str(exc))
            return
        self._marks[key] = (line_index, marks)
        self._last_rule = rule
        self.vars["problem"].set("")

    def _mark_serial(self) -> None:
        try:
            line_index, start, end = self._selection()
        except TemplateError as exc:
            self.vars["problem"].set(str(exc))
            return
        self.vars["sn_example"].set(self._lines[line_index][start:end])
        self.vars["problem"].set("")

    def _clear_rule(self, key: str) -> None:
        self._marks.pop(key, None)
        self.vars[key].set("")

    # ------------------------------------------------------------------ building the profile from the form
    def collect_profile(self) -> dict[str, Any]:
        """The profile described by the form. Raises ``TemplateError`` with a message for the person."""
        return self._collect_excel() if self.kind == "excel" else self._collect_text()

    def _collect_text(self) -> dict[str, Any]:
        patterns = {key: self.vars[key].get().strip() for key in PATTERN_FIELDS}
        if not patterns["block"] or not patterns["measure"]:
            raise TemplateError(
                "Fill in the component line and the measurement line: select text in the sample and press a button."
            )
        profile = text_profile_from_patterns(patterns, self.vars["sn_example"].get(), self._extensions)
        validate_profile(profile)
        return profile

    def _collect_excel(self) -> dict[str, Any]:
        v = self.vars
        if not self._letter("col_component"):
            raise TemplateError("Choose the column that holds the test or component name.")
        if not self._letter("col_measured"):
            raise TemplateError("Choose the column that holds the measured value.")
        try:
            row_start = parse_positive_int(v["row_start"].get(), "Data start row")
        except ValueError as exc:
            raise TemplateError(str(exc)) from None

        profile: dict[str, Any] = {
            "type": "excel", "file_extensions": self._extensions or ",".join(EXCEL_FILE_EXTENSIONS),
            "sn_sheet": v["sn_sheet"].get(), "data_sheet": v["data_sheet"].get(), "row_start": str(row_start),
            "component_col": self._letter("col_component"), "measure_col": self._letter("col_measured"),
            "min_col": self._letter("col_min"), "max_col": self._letter("col_max"), "unit_col": self._letter("col_unit"),
            "skip_empty_rows": bool(self.skip_empty.get()),
        }
        if v["sn_mode"].get() == "cell":
            cell = v["sn_cell"].get().strip().upper()
            if not looks_like_cell_coordinate(cell):
                raise TemplateError("Type the cell that holds the serial number, for example B1.")
            profile["sn_regex"] = cell
        else:
            example = v["sn_example"].get().strip()
            try:
                profile["sn_regex"] = sn_regex_from_example(example)
            except TemplateError as exc:
                raise TemplateError(f"Serial number: {exc}") from None
            profile["sn_example"] = example
        validate_profile(profile)
        return profile

    # ------------------------------------------------------------------ live feedback
    def _on_change(self, *_args: object) -> None:
        if self._loading or self.sample is None:
            return
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(REFRESH_MS, self._refresh)

    def _on_table_change(self, *_args: object) -> None:
        if not self._loading and self.sample is not None:
            self._fill_columns()

    def _set_label(self, label: ttk.Label, var: tk.StringVar, text: str, kind: str) -> None:
        var.set(text)
        label.configure(style={"ok": "SurfaceOk.TLabel", "bad": "SurfaceBad.TLabel"}.get(kind, "SurfaceHint.TLabel"))

    def _refresh(self) -> None:
        self._refresh_job = None
        if self.sample is None:
            return
        self._generation += 1
        generation = self._generation

        if self.kind == "excel":
            self._refresh_excel_hints()
        else:
            problem = self._refresh_text_hints()
            if problem:
                self._show_problem(problem)
                return
        try:
            profile = self.collect_profile()
        except ValueError as exc:
            self._show_problem(str(exc))
            return
        self.vars["problem"].set("")
        self.vars["status"].set("Reading the sample…")
        sample, siblings = self.sample, self.siblings[:FOLDER_CHECK_FILES]

        def work(_report: Callable[..., None]) -> tuple[Preview, FolderCheck | None]:
            preview = preview_profile(sample, profile, limit=40)
            return preview, check_files(siblings, profile) if siblings and not preview.error else None

        self._tasks.run(
            work,
            on_success=lambda result: self._show_result(generation, *result),
            on_error=lambda exc: self._show_problem(f"Could not read the sample: {exc}"),
        )

    def _refresh_excel_hints(self) -> None:
        assert self.sketch is not None
        v = self.vars
        if v["sn_mode"].get() == "cell":
            value = self.sketch.cell(v["sn_sheet"].get(), v["sn_cell"].get())
            v["sn_value"].set(f"→ {value}" if value else "→ (empty cell)")
        else:
            v["sn_value"].set("")

    def _refresh_text_hints(self) -> str:
        """Tell each rule what it matched and return a problem message when a pattern cannot be used."""
        patterns = {key: self.vars[key].get().strip() for key in PATTERN_FIELDS}
        problem = ""
        for key, (_regex_key, rule) in PATTERN_FIELDS.items():
            try:
                compile_template(patterns[key], rule)
            except TemplateError as exc:
                self._set_label(self._rule_labels[key], self.rule_status[key], "cannot use this pattern", "bad")
                problem = problem or f"{RULES[rule].title.capitalize()}: {exc}"
            else:
                self._set_label(self._rule_labels[key], self.rule_status[key], "", "hint")
        if problem:
            return problem

        sn_example = self.vars["sn_example"].get().strip()
        if sn_example:
            try:
                sn_regex_from_example(sn_example)
                self._set_label(self._rule_labels["sn_example"], self.rule_status["sn_example"], "", "hint")
            except TemplateError as exc:
                self._set_label(self._rule_labels["sn_example"], self.rule_status["sn_example"], "cannot use this", "bad")
                return f"Serial number: {exc}"
        else:
            self._set_label(self._rule_labels["sn_example"], self.rule_status["sn_example"], "optional", "hint")

        counts: dict[str, int] = {}
        try:
            full = text_profile_from_patterns(patterns, sn_example, self._extensions)
            marks = annotate_text(self._annotated_text, full)
            self._paint(marks)
            counts["block"] = sum(1 for m in marks if m.role == "block")
            counts["measure"] = sum(1 for m in marks if m.role == "measure")
            for key in ("lim2", "lim3"):
                if patterns[key]:
                    only = text_profile_from_patterns({**patterns, **{k: "" for k in ("lim2", "lim3") if k != key}}, sn_example, self._extensions)
                    counts[key] = len({m.line for m in annotate_text(self._annotated_text, only) if m.role in ("min", "max")})
        except ValueError as exc:
            return str(exc)
        for key in PATTERN_FIELDS:
            if not patterns[key]:
                self.rule_status[key].set("")
                continue
            found = counts.get(key, 0)
            if found:
                self._set_label(self._rule_labels[key], self.rule_status[key], f"found on {found:,} lines", "ok")
            else:
                self._set_label(self._rule_labels[key], self.rule_status[key], "not found in the sample", "bad")
        return ""

    def _show_problem(self, message: str) -> None:
        self.vars["problem"].set(message)
        self.vars["status"].set("")
        self.vars["folder_status"].set("")
        self.table.delete(*self.table.get_children())

    def _show_result(self, generation: int, preview: Preview, folder: FolderCheck | None) -> None:
        if generation != self._generation or not self.winfo_exists():
            return
        self.table.delete(*self.table.get_children())
        if preview.error:
            self.vars["status"].set(preview.error.splitlines()[0])
            self.status_label.configure(style="SurfaceBad.TLabel")
            self.vars["folder_status"].set("")
            return
        for row in preview.rows:
            self.table.insert("", tk.END, text=row.component, values=(row.measured, row.min_value, row.max_value, row.unit))

        parts = []
        if preview.sn:
            parts.append(f"Serial number {preview.sn}")
        else:
            parts.append("No serial number found")
        parts.append(f"{preview.total:,} components read")
        if preview.duplicates:
            parts.append(f"{preview.duplicates} appear more than once in this file")
        self.vars["status"].set("  ·  ".join(parts))
        good = bool(preview.sn) and preview.total > 0
        self.status_label.configure(style="SurfaceOk.TLabel" if good else "SurfaceBad.TLabel")

        if folder is None:
            self.vars["folder_status"].set("")
        elif folder.all_ok:
            others = "The other file" if folder.tried == 1 else f"The other {folder.tried} files"
            self.vars["folder_status"].set(f"{others} in this folder can be read with these settings too.")
            self.folder_label.configure(style="SurfaceOk.TLabel")
        else:
            problems = "; ".join(folder.problems[:2])
            unreadable, total = folder.tried - folder.readable, folder.tried
            self.vars["folder_status"].set(
                f"{unreadable} of {total} other {'file' if total == 1 else 'files'} in this folder cannot be read: {problems}"
            )
            self.folder_label.configure(style="SurfaceWarn.TLabel")

    # ------------------------------------------------------------------ finishing
    def accept(self) -> None:
        try:
            profile = self.collect_profile()
        except ValueError as exc:
            self.vars["problem"].set(str(exc))
            return
        name = self._name or (self.detection.suggested_name if self.detection else "") or APP_TITLE
        callback = self.on_done
        self.close()
        callback(name, profile)
