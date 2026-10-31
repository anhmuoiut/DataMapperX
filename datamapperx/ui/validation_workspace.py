"""Validation & Reports: a workspace of its own, with four tabs (Data, Analysis Setup, Results, Report).

It never changes what Data Mapping scanned or exported. Its data is a snapshot: the Data Mapping results copied into an
immutable ``Dataset`` (or a RawData.xlsx read from disk). Everything the numbers depend on lives in a ``Study``; a
result computed from an earlier state of the study is shown as stale and cannot be reported.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..models import LogRecord
from ..stat_charts import draw_tk_charts
from ..stat_reports import (
    ALL_SECTIONS,
    CONDITION_TITLES,
    METHOD_TITLES,
    display_number,
    export_statistical_report,
    report_charts,
    report_context,
    review_note,
    session_text,
    summary_rows,
)
from ..statistics import (
    Dataset,
    EvaluationSettings,
    ImportedData,
    ResultSet,
    StatisticalOptions,
    Study,
    StudyInfo,
    apply_design,
    auto_within_method,
    customers_to_json,
    describe_design,
    explain_method,
    import_rawdata_xlsx,
    merge_customers,
)
from ..statistics.evaluation import combine_config, validate_evaluation_settings
from ..statistics.study import validate_statistical_options
from ..workspace_data import MappingSource, build_mapping_dataset, int_field, reorder_dataset
from .dialogs import ReportDialog, open_path
from .tasks import TaskRunner
from .theme import Palette
from .validation import AssignmentDialog, CustomersDialog, MappingDialog
from .widgets import ReadOnlyText

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 300
_UNSET = object()
NO_CRITERIA = "None (statistics only)"
SHORT_NOTES = {"acquisition_order": "order of the readings", "repeated_measurements": "repeated readings",
               "process_stability": "stability", "normality": "distribution"}
STATUSES = ("All results", "PASS", "CONDITIONAL PASS", "FAIL", "N/A")
WITHIN_CHOICES = {"auto": "Automatic (from the subgroup size)",
                  "individuals": "Average moving range, length 2 (subgroup size 1)",
                  "pooled": "Pooled standard deviation (subgroups of 2 or more)"}
METHOD_NAMES = {"grr": "Variable Gage R&R", "capability": "Process Capability (Cp/Cpk)"}
ORDERS = {"worksheet": "Worksheet order", "filename": "File name order", "timestamp": "Timestamp order (File assignments)",
          "confirmed": "Rows are in measurement order (I confirm)"}
FILE_ORDERS = ("worksheet", "confirmed")  # a RawData.xlsx has no files of its own to order by
OPERATOR_ORDERS = {"by_operator": "by operator  (A, A, B, B)", "by_pass": "by pass  (A, B, A, B)"}
SECTION_NAMES = {"charts": "Charts", "observations": "Observations used (Excel only)"}


class ValidationWorkspace(ttk.Frame):
    """Data → Analysis Setup → Results → Report, with Run analysis always at hand (Quick Analysis)."""

    def __init__(self, parent, palette: Palette, *, settings=None, save_settings: Callable[[], None] | None = None,
                 source: Callable[[], MappingSource | None] = lambda: None):
        super().__init__(parent, style="Surface.TFrame", padding=12)
        self.palette = palette
        self.settings = settings
        self._save_settings = save_settings or (lambda: None)
        self._provider = source
        self.tasks = TaskRunner(self)
        self.customers = merge_customers(settings.customer_criteria if settings else {})

        # what the study is made of
        self.study: Study | None = None
        self.dataset: Dataset | None = None
        self.imported: ImportedData | None = None
        self.mapping_source: MappingSource | None = None
        self.grouped: Mapping[str, Sequence[LogRecord]] = {}
        self.components: tuple[str, ...] = ()
        self.expected_repeats: int | None = None
        self.field_mapping: dict[str, str] = {}
        self.assignments: dict[str, dict[str, str]] = {}
        self.result_set: ResultSet | None = None
        self.evaluated = None
        self._judge_state: tuple | None = None
        self._sash_placed = False
        self._auto_within_cache: tuple | None = None
        self.setup_error = ""
        self.last_report: Path | None = None
        self._source_key: object = _UNSET  # nothing has been looked at yet
        self._scan: int | None = None
        self._dataset_generation = 0
        self._visible: list = []
        self._charts: list = []
        self.preparing = False
        self.running = False
        self.export_busy = False

        self._make_variables()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build()
        self._apply_method_layout()
        self._apply_judge_layout()
        self._apply_source_layout()
        self._wire()
        self._refresh_state()

    # ------------------------------------------------------------------ variables
    def _make_variables(self) -> None:
        self.source_var = tk.StringVar(value="mapping")
        self.order_var = tk.StringVar(value=ORDERS["worksheet"])
        self.method_var = tk.StringVar(value="grr")
        self.operators_var = tk.StringVar()
        self.operator_order_var = tk.StringVar(value="by_operator")
        self.nest_var = tk.BooleanVar(value=False)
        self.assign_var = tk.BooleanVar(value=True)
        self.repeats_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=NO_CRITERIA)
        self.within_var = tk.StringVar(value=WITHIN_CHOICES["auto"])
        self.judge_var = tk.BooleanVar(value=False)
        self.subgroup_var = tk.BooleanVar(value=False)
        self.index_var = tk.StringVar(value="cpk")
        self.threshold_var = tk.StringVar(value="1.33")
        self.precision_var = tk.StringVar(value="2")
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value=STATUSES[0])
        self.sort_var = tk.StringVar(value="Test Item")
        self.gage_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.by_var = tk.StringVar()
        self.comments_var = tk.StringVar()
        self.sections = {name: tk.BooleanVar(value=name == "charts") for name in ALL_SECTIONS}
        self.message_var = tk.StringVar(value="Choose the data, then press Run analysis.")
        self.dataset_var = tk.StringVar(value="No data yet.")
        self.hint_var = tk.StringVar()
        self.file_var = tk.StringVar(value="No file chosen.")
        self.preview_note_var = tk.StringVar()
        self.plan_var = tk.StringVar()
        self.stale_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.notes_var = tk.StringVar()
        self.review_var = tk.StringVar()
        self.coverage_var = tk.StringVar()
        self.report_var = tk.StringVar()

    def _wire(self) -> None:
        setup = (self.method_var, self.operators_var, self.operator_order_var, self.nest_var, self.assign_var, self.repeats_var,
                 self.profile_var, self.within_var, self.subgroup_var, self.index_var, self.threshold_var, self.judge_var)
        for variable in setup:
            variable.trace_add("write", self._settings_changed)
        self.method_var.trace_add("write", lambda *_: self._apply_method_layout())
        self.judge_var.trace_add("write", lambda *_: self._apply_judge_layout())
        self.source_var.trace_add("write", lambda *_: self._source_kind_changed())
        self.order_var.trace_add("write", lambda *_: self.data_edited())
        for variable in (self.filter_var, self.search_var, self.sort_var, self.precision_var):
            variable.trace_add("write", lambda *_: self._refresh_table())
        for variable in (self.gage_var, self.date_var, self.by_var, self.comments_var):
            variable.trace_add("write", lambda *_: self._info_changed())

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        strip = ttk.Frame(self, style="Surface.TFrame")
        strip.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        strip.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(strip, text="Run analysis", style="Accent.TButton", command=self.run_analysis)
        self.run_button.grid(row=0, column=0)
        self.message_label = ttk.Label(strip, textvariable=self.message_var, style="SurfaceHint.TLabel", wraplength=700, justify="left")
        self.message_label.grid(row=0, column=1, sticky="w", padx=(12, 0))
        strip.bind("<Configure>", lambda e: self.message_label.configure(wraplength=max(200, e.width - 160)))

        self.stale_banner = ttk.Frame(self, style="Banner.TFrame", padding=(12, 6))
        self.stale_banner.columnconfigure(0, weight=1)
        self.stale_label = ttk.Label(self.stale_banner, textvariable=self.stale_var, style="Banner.TLabel", wraplength=700, justify="left")
        self.stale_label.grid(row=0, column=0, sticky="w")
        self.update_button = ttk.Button(self.stale_banner, text="Update results", style="Accent.TButton", command=self.run_analysis)
        self.update_button.grid(row=0, column=1, padx=(12, 0))
        self.stale_banner.bind("<Configure>", lambda e: self.stale_label.configure(wraplength=max(200, e.width - 200)))

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        self.data_tab = self._tab("Data")
        self.setup_tab = self._tab("Analysis")
        self.results_tab = self._tab("Results")
        self.report_tab = self._tab("Report")
        self._build_data()
        self._build_setup()
        self._build_results()
        self._build_report()

    def _tab(self, title: str) -> ttk.Frame:
        frame = ttk.Frame(self.tabs, style="Surface.TFrame", padding=12)
        frame.columnconfigure(0, weight=1)
        self.tabs.add(frame, text=title)
        return frame

    def _build_data(self) -> None:
        tab = self.data_tab
        tab.rowconfigure(5, weight=1)
        kinds = ttk.Frame(tab, style="Surface.TFrame")
        kinds.grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(kinds, text="Use Data Mapping results", variable=self.source_var, value="mapping",
                        style="Surface.TRadiobutton").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(kinds, text="Import a RawData.xlsx", variable=self.source_var, value="file",
                        style="Surface.TRadiobutton").pack(side="left")

        self.mapping_controls = ttk.Frame(tab, style="Surface.TFrame")
        self.mapping_controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.mapping_button = ttk.Button(self.mapping_controls, text="Field mapping…", command=lambda: MappingDialog(self))
        self.mapping_button.pack(side="left")
        self.assignments_button = ttk.Button(self.mapping_controls, text="File assignments…", command=lambda: AssignmentDialog(self))
        self.assignments_button.pack(side="left", padx=6)
        self.file_controls = ttk.Frame(tab, style="Surface.TFrame")
        self.file_controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.file_button = ttk.Button(self.file_controls, text="Choose file…", command=self.choose_file)
        self.file_button.pack(side="left")
        ttk.Label(self.file_controls, textvariable=self.file_var, style="SurfaceHint.TLabel").pack(side="left", padx=10)
        order = ttk.Frame(tab, style="Surface.TFrame")
        order.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(order, text="Order of the readings", style="SurfaceHint.TLabel").pack(side="left")
        self.order_combo = ttk.Combobox(order, textvariable=self.order_var, state="readonly", width=38,
                                        values=[ORDERS[key] for key in ORDERS])
        self.order_combo.pack(side="left", padx=8)
        ttk.Label(tab, textvariable=self.dataset_var, style="Section.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.hint_label = ttk.Label(tab, textvariable=self.hint_var, style="SurfaceHint.TLabel", wraplength=800, justify="left")
        self.hint_label.grid(row=4, column=0, sticky="w")
        self.hint_label.grid_remove()
        tab.bind("<Configure>", lambda e: self.hint_label.configure(wraplength=max(200, e.width - 40)))

        frame = ttk.Frame(tab, style="Surface.TFrame")
        frame.grid(row=5, column=0, sticky="nsew", pady=(6, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("test_item", "sample", "value", "lsl", "usl", "unit", "source")
        self.preview = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for column, (title, width, anchor) in zip(columns, (("Test Item", 200, "w"), ("Sample ID", 130, "w"), ("Value", 115, "e"),
                                                             ("LSL", 80, "e"), ("USL", 80, "e"), ("Unit", 60, "w"), ("Source", 260, "w")),
                                                  strict=True):
            self.preview.heading(column, text=title)
            self.preview.column(column, width=width, minwidth=50, anchor=anchor, stretch=column in ("test_item", "source"))
        self.preview.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.preview.yview)
        ys.grid(row=0, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=ys.set)
        ttk.Label(tab, textvariable=self.preview_note_var, style="SurfaceHint.TLabel").grid(row=6, column=0, sticky="w", pady=(4, 0))

    def _build_setup(self) -> None:
        tab = self.setup_tab
        ttk.Label(tab, text="Plan", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.plan_label = ttk.Label(tab, textvariable=self.plan_var, style="Surface.TLabel", wraplength=800, justify="left")
        self.plan_label.grid(row=1, column=0, sticky="w", pady=(0, 10))
        tab.bind("<Configure>", lambda e: self.plan_label.configure(wraplength=max(200, e.width - 40)))
        ttk.Label(tab, text="Study purpose", style="Section.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(tab, text="MSA: Variable Gage R&R. Is the measurement system good enough?", variable=self.method_var,
                        value="grr", style="Surface.TRadiobutton").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Radiobutton(tab, text="Process Capability: Cp/Cpk, Pp/Ppk. Does the process meet the specification?",
                        variable=self.method_var, value="capability", style="Surface.TRadiobutton").grid(row=4, column=0, sticky="w")

        self.grr_setup = ttk.Frame(tab, style="Surface.TFrame")
        self.cap_setup = ttk.Frame(tab, style="Surface.TFrame")
        for frame in (self.grr_setup, self.cap_setup):
            frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
            frame.columnconfigure(1, weight=1)

        def hint(parent, text, row, column=1, **grid):
            label = ttk.Label(parent, text=text, style="SurfaceHint.TLabel", justify="left")
            label.grid(row=row, column=column, sticky="w", **grid)
            return label

        grr = self.grr_setup
        ttk.Label(grr, text="Operators", style="Surface.TLabel").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 12))
        operators = ttk.Frame(grr, style="Surface.TFrame")
        operators.grid(row=0, column=1, sticky="w", pady=3)
        self.operators_entry = ttk.Entry(operators, textvariable=self.operators_var, width=34)
        self.operators_entry.pack(side="left")
        ttk.Label(operators, text="empty = one appraiser (repeatability only); or names separated by commas",
                  style="SurfaceHint.TLabel").pack(side="left", padx=8)
        ttk.Label(grr, text="Readings of a sample", style="Surface.TLabel").grid(row=1, column=0, sticky="w", pady=3, padx=(0, 12))
        self.operator_order_combo = ttk.Combobox(grr, state="readonly", width=26, values=list(OPERATOR_ORDERS.values()))
        self.operator_order_combo.set(OPERATOR_ORDERS["by_operator"])
        self.operator_order_combo.grid(row=1, column=1, sticky="w", pady=3)
        self.nest_check = ttk.Checkbutton(grr, text="Nest as Operator (each Slot is treated as an operator)", variable=self.nest_var,
                                          style="Surface.TCheckbutton")
        self.nest_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        hint(grr, "Reproducibility then reflects differences between nests, not people. Recorded in the report.", 3)
        ttk.Checkbutton(grr, text="Label the repeated readings of a sample as trials 1, 2, 3… when the data have no Trial",
                        variable=self.assign_var, style="Surface.TCheckbutton").grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        hint(grr, "Only to organise the data in rows. It is not taken as the order of measurement.", 5)
        ttk.Label(grr, text="Readings per sample", style="Surface.TLabel").grid(row=6, column=0, sticky="w", pady=(6, 3), padx=(0, 12))
        reading = ttk.Frame(grr, style="Surface.TFrame")
        reading.grid(row=6, column=1, sticky="w", pady=(6, 3))
        ttk.Entry(reading, textvariable=self.repeats_var, width=6).pack(side="left")
        ttk.Label(reading, text="optional: samples with another count are flagged", style="SurfaceHint.TLabel").pack(side="left", padx=8)
        ttk.Label(grr, text="Acceptance criteria", style="Surface.TLabel").grid(row=7, column=0, sticky="w", pady=3, padx=(0, 12))
        customer = ttk.Frame(grr, style="Surface.TFrame")
        customer.grid(row=7, column=1, sticky="w", pady=3)
        self.customer_combo = ttk.Combobox(customer, textvariable=self.profile_var, values=[NO_CRITERIA, *self.customers],
                                           state="readonly", width=22)
        self.customer_combo.pack(side="left")
        self.criteria_button = ttk.Button(customer, text="Customers…", command=lambda: CustomersDialog(self))
        self.criteria_button.pack(side="left", padx=8)
        ttk.Label(customer, text="optional: adds PASS / FAIL, never changes a figure", style="SurfaceHint.TLabel").pack(side="left")

        cap = self.cap_setup
        ttk.Checkbutton(cap, text="Use the Sample ID as the subgroup", variable=self.subgroup_var,
                        style="Surface.TCheckbutton").grid(row=0, column=0, columnspan=2, sticky="w", pady=(6, 0))
        hint(cap, "Only if the readings of one sample really are a rational subgroup of the process.", 1)
        ttk.Checkbutton(cap, text="Judge against a limit (optional)", variable=self.judge_var, style="Surface.TCheckbutton").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        index = ttk.Frame(cap, style="Surface.TFrame")
        index.grid(row=4, column=1, sticky="w", pady=(2, 3))
        self.index_widgets = [
            ttk.Radiobutton(index, text="Cpk (within)", variable=self.index_var, value="cpk", style="Surface.TRadiobutton"),
            ttk.Radiobutton(index, text="Ppk (overall)", variable=self.index_var, value="ppk", style="Surface.TRadiobutton"),
            ttk.Entry(index, textvariable=self.threshold_var, width=7)]
        self.index_widgets[0].pack(side="left")
        self.index_widgets[1].pack(side="left", padx=10)
        ttk.Label(index, text="must exceed", style="SurfaceHint.TLabel").pack(side="left", padx=(8, 4))
        self.index_widgets[2].pack(side="left")
        self.advanced_button = ttk.Button(cap, text="Advanced options ▸", command=self._toggle_advanced)
        self.advanced_button.grid(row=5, column=0, sticky="w", pady=(12, 0))
        self.advanced = ttk.Frame(cap, style="Surface.TFrame")
        self.advanced.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(self.advanced, text="Within sigma", style="Surface.TLabel").pack(side="left", padx=(0, 12))
        ttk.Combobox(self.advanced, textvariable=self.within_var, values=list(WITHIN_CHOICES.values()), state="readonly",
                     width=48).pack(side="left")
        self.advanced.grid_remove()
        self.operator_order_combo.bind("<<ComboboxSelected>>", self._operator_order_picked)

    def _build_results(self) -> None:
        tab = self.results_tab
        tab.rowconfigure(2, weight=1)
        self.notes_bar = ttk.Frame(tab, style="Surface.TFrame")
        self.notes_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.notes_bar.columnconfigure(0, weight=1)
        self.notes_label = ttk.Label(self.notes_bar, textvariable=self.notes_var, style="Surface.TLabel",
                                     foreground=self.palette.warn, wraplength=700, justify="left")
        self.notes_label.grid(row=0, column=0, sticky="w")
        self.notes_button = ttk.Button(self.notes_bar, text="Read the notes…", command=self.show_notes)
        self.notes_button.grid(row=0, column=1, padx=(12, 0))
        self.notes_bar.bind("<Configure>", lambda e: self.notes_label.configure(wraplength=max(200, e.width - 200)))
        self.notes_bar.grid_remove()

        head = ttk.Frame(tab, style="Surface.TFrame")
        head.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, textvariable=self.summary_var, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        filters = ttk.Frame(head, style="Surface.TFrame")
        filters.grid(row=0, column=1, sticky="e")
        ttk.Label(filters, text="Search", style="SurfaceHint.TLabel").pack(side="left", padx=(0, 4))
        ttk.Entry(filters, textvariable=self.search_var, width=14).pack(side="left")
        self.filter_combo = ttk.Combobox(filters, textvariable=self.filter_var, values=STATUSES, state="readonly", width=17)
        self.filter_combo.pack(side="left", padx=6)
        self.sort_combo = ttk.Combobox(filters, textvariable=self.sort_var, state="readonly", width=11,
                                       values=("Test Item", "%SV/Tol", "%Study Var", "NDC", "Cpk"))
        self.sort_combo.pack(side="left")

        split = self.split = ttk.PanedWindow(tab, orient="vertical")
        split.grid(row=2, column=0, sticky="nsew")
        split.bind("<Configure>", self._place_sash)
        table_page = ttk.Frame(split, style="Surface.TFrame")
        table_page.columnconfigure(0, weight=1)
        table_page.rowconfigure(0, weight=1)
        split.add(table_page, weight=1)
        self.table = ttk.Treeview(table_page, show="headings", selectmode="browse", height=3)
        self.table.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(table_page, orient="vertical", command=self.table.yview)
        ys.grid(row=0, column=1, sticky="ns")
        xs = ttk.Scrollbar(table_page, orient="horizontal", command=self.table.xview)
        xs.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.table.bind("<<TreeviewSelect>>", self._select_result)
        self.table.bind("<Double-1>", lambda _e: self.show_details())
        self.review_label = ttk.Label(table_page, textvariable=self.review_var, style="SurfaceHint.TLabel", wraplength=700, justify="left")
        self.review_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.review_label.grid_remove()
        table_page.bind("<Configure>", lambda e: self.review_label.configure(wraplength=max(200, e.width - 24)))

        self.result_tabs = ttk.Notebook(split)
        split.add(self.result_tabs, weight=3)
        chart_page = ttk.Frame(self.result_tabs, style="Surface.TFrame", padding=4)
        chart_page.columnconfigure(0, weight=1)
        chart_page.rowconfigure(0, weight=1)
        self.result_tabs.add(chart_page, text="Charts")
        self.chart_canvas = tk.Canvas(chart_page, bg="white", highlightthickness=0, height=200)
        self.chart_canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(chart_page, orient="vertical", command=self.chart_canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.chart_canvas.configure(yscrollcommand=scroll.set)
        self.chart_canvas.bind("<Configure>", lambda _e: self._draw_chart())
        self.chart_canvas.bind("<MouseWheel>", lambda e: self.chart_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        session_page = ttk.Frame(self.result_tabs, style="Surface.TFrame", padding=4)
        session_page.columnconfigure(0, weight=1)
        session_page.rowconfigure(0, weight=1)
        self.result_tabs.add(session_page, text="Details")
        self.session = ReadOnlyText(session_page, self.palette, height=8, width=60)
        self.session.text.configure(font=("Consolas", 10), wrap="none")
        self.session.grid(row=0, column=0, sticky="nsew")

        foot = ttk.Frame(tab, style="Surface.TFrame")
        foot.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.detail_button = ttk.Button(foot, text="Calculation details", command=self.show_details, state="disabled")
        self.detail_button.pack(side="left")
        self.about_button = ttk.Button(foot, text="About the method", command=self.show_about)
        self.about_button.pack(side="left", padx=6)
        self.issues_button = ttk.Button(foot, text="Data messages", command=self.show_issues, state="disabled")
        self.issues_button.pack(side="left")
        ttk.Spinbox(foot, from_=2, to=8, textvariable=self.precision_var, width=3).pack(side="right")
        ttk.Label(foot, text="Decimals shown", style="SurfaceHint.TLabel").pack(side="right", padx=(0, 6))

    def _place_sash(self, event) -> None:
        """The table keeps a few rows and the charts get the rest; the user can drag the divider afterwards."""
        if not self._sash_placed and event.height > 260:
            self._sash_placed = True
            self.split.sashpos(0, 150 if event.height > 380 else 120)

    def _build_report(self) -> None:
        tab = self.report_tab
        tab.columnconfigure(2, weight=1)
        tab.rowconfigure(2, weight=1)
        left = ttk.Frame(tab, style="Surface.TFrame")
        left.grid(row=0, column=0, sticky="nw", padx=(0, 40))
        ttk.Label(left, text="Study information (optional)", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.info_entries = {}
        fields = (("Gage name", self.gage_var), ("Date of study", self.date_var), ("Reported by", self.by_var), ("Misc", self.comments_var))
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(left, text=label, style="Surface.TLabel").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            entry = ttk.Entry(left, textvariable=variable, width=40)
            entry.grid(row=row, column=1, sticky="w", pady=3)
            self.info_entries[label] = entry
        ttk.Label(left, text="Shown with each item when entered. The report records the day it was made.", style="SurfaceHint.TLabel",
                  wraplength=360, justify="left").grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        right = ttk.Frame(tab, style="Surface.TFrame")
        right.grid(row=0, column=1, sticky="nw")
        ttk.Label(right, text="Include", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        checks = ttk.Frame(right, style="Surface.TFrame")
        checks.grid(row=1, column=0, sticky="w")
        for name in ALL_SECTIONS:
            ttk.Checkbutton(checks, text=SECTION_NAMES[name], variable=self.sections[name], style="Surface.TCheckbutton").pack(anchor="w")
        items = ttk.Frame(right, style="Surface.TFrame")
        items.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        items.columnconfigure(0, weight=1)
        ttk.Label(items, textvariable=self.coverage_var, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(items, text="None", width=6, command=lambda: self._select_items(False)).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(items, text="All", width=6, command=lambda: self._select_items(True)).grid(row=0, column=2)
        box = ttk.Frame(right, style="Surface.TFrame")
        box.grid(row=3, column=0, sticky="nw")
        self.item_list = tk.Listbox(box, selectmode="extended", exportselection=False, height=8, width=46, activestyle="none",
                                    relief="flat", highlightthickness=1)
        self.item_list.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.item_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.item_list.configure(yscrollcommand=scroll.set)
        self.item_list.bind("<<ListboxSelect>>", lambda _e: self._update_coverage())

        actions = ttk.Frame(tab, style="Surface.TFrame")
        actions.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.pdf_button = ttk.Button(actions, text="Generate PDF…", style="Accent.TButton", command=lambda: self.generate_report(".pdf"))
        self.pdf_button.grid(row=0, column=0)
        self.excel_button = ttk.Button(actions, text="Generate Excel…", command=lambda: self.generate_report(".xlsx"))
        self.excel_button.grid(row=0, column=1, padx=6)
        self.report_label = ttk.Label(actions, textvariable=self.report_var, style="SurfaceHint.TLabel", wraplength=500, justify="left")
        self.report_label.grid(row=0, column=2, sticky="w", padx=10)
        self.open_button = ttk.Button(actions, text="Open", command=self.open_report, state="disabled")
        self.open_button.grid(row=0, column=3)
        actions.bind("<Configure>", lambda e: self.report_label.configure(wraplength=max(160, e.width - 380)))

    # ------------------------------------------------------------------ small helpers
    @property
    def busy(self) -> bool:
        return self.preparing or self.running or self.export_busy

    @property
    def stale(self) -> bool:
        return bool(self.study and self.result_set and self.study.is_stale(self.result_set))

    @property
    def results(self) -> list:
        return list(self.evaluated.results) if self.evaluated else []

    def _dialog_parent(self):
        return self.winfo_toplevel()

    def _order_key(self) -> str:
        label = self.order_var.get()
        return next((key for key, text in ORDERS.items() if text == label), "worksheet")

    def _operator_order_picked(self, _event=None) -> None:
        picked = self.operator_order_combo.get()
        self.operator_order_var.set(next((key for key, text in OPERATOR_ORDERS.items() if text == picked), "by_operator"))

    def set_customers(self, customers, selected=None) -> None:
        """Adopt the customers edited in the dialog and keep them for next time."""
        self.customers = dict(customers)
        if self.settings is not None:
            self.settings.customer_criteria = customers_to_json(self.customers)
            self._save_settings()
        self.customer_combo.configure(values=[NO_CRITERIA, *self.customers])
        target = selected or self.profile_var.get()
        previous = self.profile_var.get()
        self.profile_var.set(target if target in self.customers else NO_CRITERIA)
        if self.profile_var.get() == previous:
            self._settings_changed()  # the same customer with new limits

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.notes_label.configure(foreground=palette.warn)
        self.review_label.configure(foreground=palette.warn)
        for status, color in (("PASS", palette.ok), ("CONDITIONAL PASS", palette.warn), ("FAIL", palette.danger), ("N/A", palette.muted)):
            self.table.tag_configure(status, foreground=color)
        self.session.text.configure(bg=palette.surface, fg=palette.fg, insertbackground=palette.fg,
                                    highlightbackground=palette.line, highlightcolor=palette.accent)
        self.item_list.configure(bg=palette.surface, fg=palette.fg, selectbackground=palette.accent,
                                 selectforeground=palette.on_accent, highlightbackground=palette.line, highlightcolor=palette.accent)

    # ------------------------------------------------------------------ layout switches
    def _apply_method_layout(self) -> None:
        capability = self.method_var.get() == "capability"
        (self.grr_setup.grid_remove if capability else self.grr_setup.grid)()
        (self.cap_setup.grid if capability else self.cap_setup.grid_remove)()
        self.sort_combo.configure(values=("Test Item", "Cpk", "Ppk") if capability else ("Test Item", "%SV/Tol", "%Study Var", "NDC"))
        if self.sort_var.get() not in self.sort_combo.cget("values"):
            self.sort_var.set("Test Item")

    def _toggle_advanced(self) -> None:
        if self.advanced.winfo_manager():
            self.advanced.grid_remove()
            self.advanced_button.configure(text="Advanced options ▸")
        else:
            self.advanced.grid()
            self.advanced_button.configure(text="Advanced options ▾")

    def _apply_judge_layout(self) -> None:
        for widget in self.index_widgets:
            widget.configure(state="normal" if self.judge_var.get() else "disabled")

    def _apply_source_layout(self) -> None:
        mapping = self.source_var.get() == "mapping"
        (self.mapping_controls.grid if mapping else self.mapping_controls.grid_remove)()
        (self.file_controls.grid_remove if mapping else self.file_controls.grid)()
        keys = list(ORDERS) if mapping else list(FILE_ORDERS)
        self.order_combo.configure(values=[ORDERS[key] for key in keys])
        if self._order_key() not in keys:
            self.order_var.set(ORDERS["worksheet"])

    def _source_kind_changed(self) -> None:
        self._apply_source_layout()
        self._prepare_dataset()

    # ------------------------------------------------------------------ the data
    def source_changed(self) -> None:
        """Data Mapping's results changed (a scan, a selection, a duplicate choice). Picked up now if on screen, else on show."""
        if self.winfo_ismapped():
            self.on_show()

    def on_show(self) -> None:
        """Compare Data Mapping's current results with the snapshot (cheap) and take a new one only if they differ."""
        source = self._provider()
        key = source.key if source else None
        if key == self._source_key:
            return
        self._source_key = key
        self.mapping_source = source
        if source is None:
            self.grouped, self.components, self.expected_repeats = {}, (), None
        else:
            self.grouped, self.components, self.expected_repeats = source.grouped, source.components, source.expected_repeats
            if source.scan != self._scan:  # a new scan is a new study: nothing of the old files carries over
                self._scan = source.scan
                self.field_mapping.clear()
                self.assignments.clear()
                self.repeats_var.set(str(source.expected_repeats) if source.expected_repeats else "")
                self.study = self.result_set = self.evaluated = None
                self.profile_var.set(NO_CRITERIA)
                self.judge_var.set(False)
                self._fill_items()
                self._refresh_table()
        if self.source_var.get() == "mapping":
            self._prepare_dataset()

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(parent=self._dialog_parent(), title="Choose a RawData.xlsx",
                                          filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")])
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        self.message_var.set(f"Reading {path.name}…")
        self.preparing = True
        self._refresh_state()

        def failed(exc):
            self.preparing = False
            self.message_var.set(f"Could not read {path.name}: {exc}")
            self._refresh_state()

        def loaded(imported):
            self.preparing = False
            self.imported = imported
            self.file_var.set(str(path))
            if self.source_var.get() != "file":
                self.source_var.set("file")  # prepares the dataset
            else:
                self._prepare_dataset()

        self.tasks.run(lambda _report: import_rawdata_xlsx(path), on_success=loaded, on_error=failed)

    def data_edited(self) -> None:
        """Field mapping, file assignments or the order changed: take a new snapshot."""
        if self.mapping_source is not None or self.imported is not None:
            self._prepare_dataset()

    def _prepare_dataset(self) -> None:
        self._dataset_generation += 1
        generation, order = self._dataset_generation, self._order_key()
        if self.source_var.get() == "mapping":
            source = self.mapping_source
            if source is None or not source.components:
                self._clear_dataset("No Data Mapping results yet. Scan logs and choose test items in Data Mapping, or import a RawData.xlsx.")
                return
            field_mapping, assignments = dict(self.field_mapping), {k: dict(v) for k, v in self.assignments.items()}

            def work(_report):
                return build_mapping_dataset(source, field_mapping, assignments, order)
        else:
            imported = self.imported
            if imported is None:
                self._clear_dataset("Choose a RawData.xlsx to analyse.")
                return

            def work(_report):
                return reorder_dataset(imported.dataset, order)

        def done(dataset):
            if generation == self._dataset_generation:
                self.preparing = False
                self._dataset_ready(dataset)

        def failed(exc):
            if generation == self._dataset_generation:
                self.preparing = False
                self._clear_dataset(str(exc))

        self.preparing = True
        self.message_var.set("Preparing the data…")
        self._refresh_state()
        self.tasks.run(work, on_success=done, on_error=failed)

    def _clear_dataset(self, message: str) -> None:
        self.preparing = False
        self.dataset = self.study = self.result_set = self.evaluated = None
        self.dataset_var.set("No data yet.")
        self.hint_var.set("")
        self.hint_label.grid_remove()
        self.preview.delete(*self.preview.get_children())
        self.preview_note_var.set("")
        self.setup_error = ""
        self.message_var.set(message)
        self._refresh_table()
        self._fill_items()
        self._refresh_state()

    def _mapping_record(self) -> dict:
        return {"source": self.source_var.get(), "components": list(self.components) if self.source_var.get() == "mapping" else [],
                "field_mapping": dict(self.field_mapping), "assignments": {k: dict(v) for k, v in self.assignments.items()},
                "order": self._order_key(), "file": self.file_var.get() if self.source_var.get() == "file" else ""}

    def _dataset_ready(self, dataset: Dataset) -> None:
        self.dataset = dataset
        if self.study is None:
            self.study = Study(dataset)
            self.profile_var.set(NO_CRITERIA)  # a new study is statistics only until the user chooses criteria
            self.judge_var.set(False)
        else:
            self.study.dataset = dataset
        self.study.mapping = self._mapping_record()
        self._info_changed()  # the information typed on the Report tab belongs to whichever study is current
        samples = len({o.sample_id for o in dataset.observations})
        order = {"worksheet": "worksheet order", "acquisition": "measurement order", "custom": "custom order"}[dataset.order_basis]
        self.dataset_var.set(f"{samples} samples · {len(dataset)} readings · {len(dataset.items)} test items · {order}")
        notes = list(self.imported.warnings) if self.source_var.get() == "file" and self.imported else []
        if dataset.order_basis == "worksheet":
            notes.append("Worksheet order is the order of the rows, not a verified order of measurement.")
        notes.append(f"Data fingerprint {dataset.fingerprint[:19]}")
        self.hint_var.set("  ".join(notes))
        self.hint_label.grid()
        self.preview.delete(*self.preview.get_children())
        for index, row in enumerate(dataset.observations[:PREVIEW_ROWS]):
            self.preview.insert("", "end", iid=str(index), values=(
                row.test_item, row.sample_id, display_number(row.value) if isinstance(row.value, float) else row.value,
                display_number(row.lsl) if isinstance(row.lsl, float) else row.lsl,
                display_number(row.usl) if isinstance(row.usl, float) else row.usl, row.unit, row.source))
        shown = min(PREVIEW_ROWS, len(dataset))
        self.preview_note_var.set(f"Showing the first {shown} of {len(dataset)} readings." if shown < len(dataset)
                                  else f"{len(dataset)} readings.")
        self.message_var.set("Ready. Press Run analysis, or set up the study first.")
        self._settings_changed()

    # ------------------------------------------------------------------ the study
    def _within_key(self) -> str:
        label = self.within_var.get()
        return next((key for key, text in WITHIN_CHOICES.items() if text == label), "auto")

    def _auto_within(self, design: dict) -> str:
        """Within sigma chosen from the subgroup size (cached: it is read on every change of a setting)."""
        key = (self.dataset.fingerprint if self.dataset else "", bool(design.get("subgroup_from_sample")))
        if self._auto_within_cache is None or self._auto_within_cache[0] != key:
            rows = apply_design(self.dataset.observations, design, "capability") if self.dataset else ()
            self._auto_within_cache = (key, auto_within_method(rows))
        return self._auto_within_cache[1]

    def _read_setup(self) -> tuple[StatisticalOptions, dict, EvaluationSettings, bool]:
        """The settings on screen. A ValueError says what to fix."""
        method = self.method_var.get()
        evaluation, judge = self._evaluation_for(method), self._judge_for(method)
        if method == "grr":
            names = [name.strip() for name in self.operators_var.get().split(",") if name.strip()]
            if len(names) == 1:
                raise ValueError("Enter at least two operator names, or leave Operators empty for one appraiser.")
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError("Operator names must be different.")
            if names and self.nest_var.get():
                raise ValueError("Choose either named operators or Nest as Operator, not both.")
            design = {"operators": names, "operator_order": self.operator_order_var.get(), "nest_as_operator": self.nest_var.get()}
            options = StatisticalOptions(method="grr", expected_repeats=int_field(self.repeats_var.get(), "Readings per sample", 2),
                                         assign_trials=self.assign_var.get())
        else:
            design = {"subgroup_from_sample": self.subgroup_var.get()}
            within = self._within_key()
            options = StatisticalOptions(method="capability", within_method=self._auto_within(design) if within == "auto" else within)
        validate_statistical_options(options)
        if judge:
            validate_evaluation_settings(evaluation, method)
        return options, design, evaluation, judge

    def _judge_for(self, method: str) -> bool:
        """Whether acceptance criteria are applied at all. They are an optional layer on top of the statistics."""
        return self.profile_var.get() in self.customers if method == "grr" else self.judge_var.get()

    def _evaluation_for(self, method: str) -> EvaluationSettings:
        """How results of ``method`` are judged, from the settings on screen. A ValueError says what to fix."""
        if not self._judge_for(method):
            return EvaluationSettings(decision_metric="cpk") if method == "capability" else EvaluationSettings()
        if method == "grr":
            customer = self.profile_var.get()
            return EvaluationSettings(profile=customer, criteria=self.customers[customer])
        try:
            threshold = float(self.threshold_var.get())
        except ValueError:
            raise ValueError(f"{self.index_var.get().capitalize()} must exceed: enter a number such as 1.33.") from None
        return EvaluationSettings(cpk_threshold=threshold, decision_metric=self.index_var.get())

    def _settings_changed(self, *_) -> None:
        study = self.study
        if study is None:
            self._refresh_state()
            return
        try:
            options, design, evaluation, judge = self._read_setup()
        except ValueError as exc:
            self.setup_error = str(exc)
            self._refresh_state()
            return
        self.setup_error = ""
        changed = (evaluation, judge) != (study.evaluation, self._judge_state)
        study.options, study.design, study.evaluation = options, design, evaluation
        self._judge_state = judge
        study.mapping = self._mapping_record()
        if self.result_set is not None and changed:
            self._evaluate()  # new criteria for the same numbers
        self._refresh_state()

    def _info_changed(self) -> None:
        if self.study is not None:
            self.study.info = StudyInfo(self.gage_var.get().strip(), self.date_var.get().strip(), self.by_var.get().strip(),
                                        self.comments_var.get().strip())

    def _plan_text(self) -> str:
        study = self.study
        if study is None or self.dataset is None:
            return ""
        samples = len({o.sample_id for o in self.dataset.observations})
        design = " ".join(describe_design(study.design, study.options.method))
        settings, capability = study.evaluation, study.options.method == "capability"
        if capability:
            within = ("average moving range (length 2)" if study.options.within_method == "individuals" else "pooled standard deviation of subgroups")
            if self._within_key() == "auto":
                within += " (chosen from the subgroup size)"
            design += f" Within sigma: {within}."
        if not self._judge_for(study.options.method):
            judged = "No acceptance criteria: statistics only."
        elif capability:
            judged = f"{settings.decision_metric.capitalize()} must exceed {settings.cpk_threshold:g}."
        else:
            judged = f"Customer criteria: {settings.profile}."
        return f"{METHOD_NAMES[study.options.method]}: {len(self.dataset.items)} test items, {samples} samples. {design} {judged}"

    # ------------------------------------------------------------------ running
    def run_analysis(self) -> None:
        study = self.study
        if study is None or self.busy:
            return
        self._settings_changed()
        if self.setup_error:
            self.message_var.set(self.setup_error)
            self.tabs.select(self.setup_tab)
            return
        try:
            plan = study.plan_statistics()  # the study is read here, on this thread
        except ValueError as exc:
            self.message_var.set(str(exc))
            self.tabs.select(self.setup_tab)
            return
        self.running = True
        self.message_var.set("Analysing…")
        self._refresh_state()

        def done(result_set):
            self.running = False
            if study is not self.study:
                return self._refresh_state()
            self.result_set = study.adopt(result_set)
            self._evaluate()
            self.message_var.set(f"{len(result_set.statistics)} item/system groups analysed.")
            self._refresh_state()
            self.tabs.select(self.results_tab)

        def failed(exc):
            self.running = False
            self.message_var.set(str(exc))
            self._refresh_state()

        self.tasks.run(lambda _report: plan.execute(), on_success=done, on_error=failed)

    def _evaluate(self) -> None:
        study, result_set = self.study, self.result_set
        if study is None or result_set is None:
            self.evaluated = None
            return
        method = result_set.options.method  # results of the method that is no longer on screen keep their own settings
        try:
            settings, judge = self._evaluation_for(method), self._judge_for(method)
        except ValueError:
            settings, judge = EvaluationSettings(decision_metric="cpk") if method == "capability" else EvaluationSettings(), False
        self.evaluated = study.evaluate(result_set, settings, judge=judge)
        self._fill_items()
        self._refresh_table()

    def show_notes(self) -> None:
        if self.evaluated is None:
            return
        lines = []
        for condition in self.evaluated.record.validation.conditions:
            kind = "Warning" if condition.severity.value == "warning" else "Information"
            lines += [f"{CONDITION_TITLES.get(condition.code, condition.code)} ({kind})", condition.message, ""]
        lines.append("These notes do not block a result or a report; the report prints them.")
        ReportDialog(self._dialog_parent(), "Notes on this analysis", "What to keep in mind when reading the results", "\n".join(lines))

    # ------------------------------------------------------------------ what is enabled and said
    def _refresh_state(self) -> None:
        has_data = self.dataset is not None and self.study is not None
        has_result = self.result_set is not None and self.evaluated is not None
        stale = self.stale
        self.run_button.configure(state="normal" if has_data and not self.setup_error and not self.busy else "disabled")
        for tab, enabled in ((self.setup_tab, has_data), (self.results_tab, has_result), (self.report_tab, has_result)):
            self.tabs.tab(tab, state="normal" if enabled else "disabled")
        if self.setup_error:
            self.message_var.set(self.setup_error)
        self.plan_var.set(self._plan_text())
        if stale and not self.running:
            self.stale_var.set("The data or the study settings changed since these results were computed. They are shown for reference "
                               "only and cannot be reported. Update the results to continue.")
            self.stale_banner.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        else:
            self.stale_banner.grid_remove()
        self.update_button.configure(state="normal" if has_data and not self.setup_error and not self.busy else "disabled")
        reportable = has_result and not stale and not self.busy
        for button in (self.pdf_button, self.excel_button):
            button.configure(state="normal" if reportable else "disabled")
        self.issues_button.configure(state="normal" if has_result else "disabled")
        self._refresh_notes()
        if has_result and stale and not self.report_var.get().startswith("Saved"):
            self.report_var.set("Update the results before generating a report.")
        elif has_result and not stale and self.report_var.get().startswith("Update the results"):
            self.report_var.set("")

    def _refresh_notes(self) -> None:
        conditions = self.evaluated.record.validation.conditions if self.evaluated else ()
        if not conditions:
            self.notes_bar.grid_remove()
            return
        important = [SHORT_NOTES.get(c.code, c.code) for c in conditions if c.severity.value == "warning"]
        if important:
            self.notes_var.set("Keep in mind: " + ", ".join(important) + ".")
            self.notes_label.configure(foreground=self.palette.warn)
        else:
            self.notes_var.set(f"{len(conditions)} note{'s' if len(conditions) != 1 else ''} on this analysis.")
            self.notes_label.configure(foreground=self.palette.muted)
        self.notes_bar.grid()

    # ------------------------------------------------------------------ results
    def _refresh_table(self) -> None:
        self.table.delete(*self.table.get_children())
        evaluated = self.evaluated
        results = list(evaluated.results) if evaluated else []
        if not results:
            self._visible, self._charts = [], []
            self.summary_var.set("")
            self.review_var.set("")
            self.review_label.grid_remove()
            self.detail_button.configure(state="disabled")
            self.chart_canvas.delete("all")
            self.session.set_text("")
            return
        judged = evaluated.record.judged
        if judged:
            counts: dict[str, int] = {}
            for result in results:
                counts[result.status] = counts.get(result.status, 0) + 1
            self.summary_var.set(f"{len(results)} items · " + " · ".join(f"{n} {status}" for status, n in counts.items()))
        else:
            self.summary_var.set(f"{len(results)} items · statistics only")
        if judged and not self.filter_combo.winfo_manager():
            self.filter_combo.pack(side="left", padx=6, before=self.sort_combo)  # filtering by result needs criteria
        elif not judged:
            self.filter_combo.pack_forget()
        flagged = [r for r in results if r.details.get("acceptance_conflicts")]
        if flagged:
            names = ", ".join(dict.fromkeys(review_note(r) for r in flagged))
            self.review_var.set(
                f"Review needed: {len(flagged)} of {len(results)} results are acceptable for the applied criteria, but a metric that "
                f"is not applied would fail on its own limits ({names}; see the Review column). The measurement system may not "
                "distinguish the sampled parts, or the tolerance is much wider than the process spread.")
            self.review_label.grid()
        else:
            self.review_var.set("")
            self.review_label.grid_remove()
        query, wanted = self.search_var.get().casefold(), self.filter_var.get() if judged else STATUSES[0]
        self._visible = [r for r in results if query in r.label.casefold() and (wanted == STATUSES[0] or r.status == wanted)]
        metric = {"Cpk": "cpk", "Ppk": "ppk", "%SV/Tol": "percent_tolerance", "%Study Var": "percent_study_var", "NDC": "ndc"}.get(self.sort_var.get())
        self._visible.sort(key=lambda r: (r.metrics.get(metric) is None, r.metrics.get(metric) or 0) if metric else (r.test_item, r.system))
        if not self._visible:
            self._charts = []
            self.detail_button.configure(state="disabled")
            self.chart_canvas.delete("all")
            return
        all_headers, all_rows = summary_rows(self._visible, judged)
        left_out = {"Mean", "Min", "Max", "Decision Metric"} | (set() if any(r.system for r in self._visible) else {"System"})
        keep = [i for i, h in enumerate(all_headers) if h not in left_out]  # the rest is in Calculation details and the report
        headers = [all_headers[i] for i in keep]
        self.table.configure(columns=tuple(str(i) for i in range(len(headers))))
        status_column = next((i for i, h in enumerate(headers) if h in ("Result", "Acceptance Result")), None)
        precision = self._precision()
        for i, heading in enumerate(headers):
            self.table.heading(str(i), text=heading)
            wide = 220 if i == 0 else 150 if heading in ("Review", "Acceptance Result", "Result") else 95
            self.table.column(str(i), width=wide, minwidth=70, stretch=i == 0, anchor="w" if i == 0 or heading == "Review" else "e")
        for i, row in enumerate(all_rows):
            values = [display_number(row[k], 2 if "%" in all_headers[k] else precision) for k in keep]
            tags = ()
            if status_column is not None:
                values[status_column] = self._visible[i].status
                tags = (values[status_column],)
            self.table.insert("", "end", iid=str(i), values=values, tags=tags)
        self.set_palette(self.palette)
        self.table.selection_set("0")
        self._select_result()

    def _precision(self) -> int:
        try:
            return max(2, min(8, int(self.precision_var.get())))
        except ValueError:
            return 2

    def selected_result(self):
        selected = self.table.selection()
        return self._visible[int(selected[0])] if selected and int(selected[0]) < len(self._visible) else None

    def _select_result(self, *_) -> None:
        result = self.selected_result()
        self.detail_button.configure(state="normal" if result else "disabled")
        self._charts = report_charts(result, titled=True) if result else []
        self._draw_chart()
        self.session.set_text(session_text(result, self._precision()) if result else "")

    def _draw_chart(self) -> None:
        draw_tk_charts(self.chart_canvas, self._charts, columns=1 if len(self._charts) == 1 else 2)

    # ------------------------------------------------------------------ explanations
    def _config(self):
        if self.study is None:
            return None
        return combine_config(self.study.options, self.study.evaluation)

    def show_about(self) -> None:
        from ..statistics import AnalysisConfig

        config = self._config() or AnalysisConfig(method=self.method_var.get())
        ReportDialog(self._dialog_parent(), "About the method", METHOD_NAMES[config.method], explain_method(config))

    def show_details(self) -> None:
        result = self.selected_result()
        if result is None:
            return
        lines = [f"Test Item: {result.test_item}", f"Measurement system: {result.system}",
                 f"Measurements: {result.n}; samples: {result.parts}; repetitions: {result.repeats}",
                 f"Mean: {result.mean!r}; Min: {result.minimum!r}; Max: {result.maximum!r}",
                 f"LSL: {result.lsl!r}; USL: {result.usl!r}", "", "INTERMEDIATE CALCULATIONS (full stored precision)"]
        lines.extend(f"{key}: {value!r}" for key, value in result.details.items())
        lines.extend(["", "FINAL METRICS"] + [f"{k}: {v!r}" for k, v in result.metrics.items()])
        if self.evaluated is not None and self.evaluated.record.judged:
            lines.extend(["", f"Decision metric: {result.decision_metric}; result: {result.status}"])
        lines.extend(["", f"Applied settings: {result.config!r}"])
        if self.study is not None and self.result_set is not None and self.evaluated is not None:
            record = self.evaluated.record
            lines.extend(["", "STUDY", f"Data: {self.study.dataset.description or 'not recorded'}",
                          f"Order of the readings: {self.study.dataset.order_basis}",
                          f"Design: {' '.join(describe_design(self.study.design, self.study.options.method))}",
                          "Acceptance criteria: " + (f"version {record.criteria_version}" if record.judged else "none (statistics only)")])
            lines.extend(f"Note: {CONDITION_TITLES.get(c.code, c.code)}: {c.message}" for c in record.validation.conditions)
            lines.extend(f"Method verification: {METHOD_TITLES.get(key, key)}: {status}" for key, status in self.result_set.method_verification)
        lines.extend(["", "DATASET MESSAGES"] + [i.message for i in result.issues])
        lines.extend(["", explain_method(result.config)])
        ReportDialog(self._dialog_parent(), "Calculation Details", result.test_item, "\n".join(lines))

    def show_issues(self) -> None:
        if not self.result_set:
            return
        lines = []
        for stat in self.result_set.statistics:
            lines.append(stat.label)
            lines.extend([f"{i.severity.upper()}: {i.message}" for i in stat.issues] or ["No dataset issues."])
            lines.append("")
        ReportDialog(self._dialog_parent(), "Data messages", "What the analysis found in the data", "\n".join(lines))

    # ------------------------------------------------------------------ report
    def _fill_items(self) -> None:
        self.item_list.delete(0, "end")
        for result in self.results:
            self.item_list.insert("end", result.label)
        self._select_items(True)

    def _select_items(self, everything: bool) -> None:
        if everything:
            self.item_list.selection_set(0, "end")
        else:
            self.item_list.selection_clear(0, "end")
        self._update_coverage()

    def included(self) -> list[str]:
        labels = [self.item_list.get(i) for i in self.item_list.curselection()]
        return labels

    def _update_coverage(self) -> None:
        total, chosen = self.item_list.size(), len(self.item_list.curselection())
        self.coverage_var.set("" if not total else f"Included {chosen} of {total} items")

    def _context(self):
        if self.study is None or self.result_set is None or self.evaluated is None:
            raise ValueError("Run an analysis first.")
        included = self.included()
        if not included:
            raise ValueError("Choose at least one item to include.")
        sections = [name for name, variable in self.sections.items() if variable.get()]
        return report_context(self.study, self.result_set, included=included, sections=sections), included

    def _report_results(self, included: Sequence[str]) -> list:
        chosen = set(included)
        return [r for r in self.results if r.label in chosen]

    def generate_report(self, suffix: str) -> None:
        if self.export_busy:
            return
        if self.stale:
            self.report_var.set("Update the results before generating a report.")
            return
        try:
            context, included = self._context()
        except Exception as exc:
            self.report_var.set(str(exc))
            return
        label = METHOD_NAMES[self.study.options.method]
        path = filedialog.asksaveasfilename(
            parent=self._dialog_parent(), title="Generate report", defaultextension=suffix,
            filetypes=[("PDF report", "*.pdf")] if suffix == ".pdf" else [("Excel report", "*.xlsx")],
            initialfile=f"{self.study.options.method}_report{suffix}")
        if not path:
            return
        results = self._report_results(included)
        decimals = self._precision()
        gage = self.gage_var.get().strip()
        title = (f"{gage}: {label}" if gage else label) + (" (partial report)" if context.partial else "")
        self.export_busy = True
        self.report_var.set("Generating the report…")
        self._refresh_state()

        def finished(destination):
            self.export_busy = False
            self.last_report = Path(destination)
            self.open_button.configure(state="normal")
            self.report_var.set(f"Saved: {destination}")
            self._refresh_state()

        def failed(exc):
            self.export_busy = False
            self.report_var.set("Report generation failed.")
            self._refresh_state()
            messagebox.showerror("Report export failed", str(exc), parent=self._dialog_parent())

        self.tasks.run(lambda _report: export_statistical_report(Path(path), results, decimals=decimals, title=title, context=context),
                       on_success=finished, on_error=failed)

    def open_report(self) -> None:
        if self.last_report is not None:
            open_path(self.last_report)


__all__ = ["MappingSource", "ValidationWorkspace", "build_mapping_dataset", "reorder_dataset"]
