"""Validation & Reports: a workspace of its own, with four tabs (Data, Analysis Setup, Results, Report).

It never changes what Data Mapping scanned or exported. Its data is a snapshot: the Data Mapping results copied into an
immutable ``Dataset`` (or a RawData.xlsx read from disk). Everything the numbers depend on lives in a ``Study``; a
result computed from an earlier state of the study is shown as stale and cannot be reported.

What the statistics are, what the tables say and what the reports print is decided by the core (``datamapperx.statistics``,
``datamapperx.stat_reports``). This file keeps the settings, drives a ``Study`` and shows the answers.
"""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..method_guide import method_guide
from ..models import LogRecord
from ..palette import Palette
from ..stat_charts import agreement_chart_note, plain_number
from ..stat_reports import (
    ALL_SECTIONS,
    CONDITION_TITLES,
    attribute_details,
    capability_details,
    detail_cell,
    export_statistical_report,
    grr_details,
    item_label,
    report_charts,
    report_context,
    review_note,
    session_text,
    summary_line,
    summary_number,
    summary_rows,
)
from ..statistics import (
    Dataset,
    DesignError,
    EvaluationSettings,
    ImportedData,
    ResultSet,
    StatisticalOptions,
    Study,
    StudyInfo,
    apply_design,
    auto_within_method,
    customers_to_json,
    import_rawdata_xlsx,
    merge_customers,
)
from ..statistics.checks import (
    CRITICAL,
    attribute_status_label,
    describe_layouts,
    findings,
    layout_of,
    needs_attention,
    result_checks,
    status_label,
)
from ..statistics.evaluation import combine_config, validate_evaluation_settings
from ..statistics.ratings import (
    ImportedRatings,
    attribute_settings,
    attribute_summary,
    attribute_warnings,
    read_ratings_table,
)
from ..statistics.study import validate_statistical_options
from ..workspace_data import MappingSource, build_mapping_dataset, int_field, reorder_dataset
from .dialogs import ReportDialog, label, open_path
from .tasks import TaskRunner
from .variables import Var, bind_check, bind_combo, bind_edit, bind_label, bind_radios, bind_spin
from .widgets import ChartPanel, DataTable, make_button, repolish

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 300
WIDE_RESULTS = 1100  # pixels of the Results tab from which the table and the charts sit side by side
_UNSET = object()
NO_CRITERIA = "None (statistics only)"
STATUSES = ("All results", "PASS", "CONDITIONAL PASS", "FAIL", "N/A")
WITHIN_CHOICES = {"auto": "Automatic (from the subgroup size)",
                  "individuals": "Average moving range, length 2 (subgroup size 1)",
                  "pooled": "Pooled standard deviation (subgroups of 2 or more)"}
METHOD_NAMES = {"grr": "Variable Gage R&R", "capability": "Process Capability (Cp/Cpk)", "attribute": "Attribute Agreement"}
PLAN_TITLES = {"grr": "Variable Gage R&R", "capability": "Process Capability", "attribute": "Attribute Agreement"}
CONFIDENCE_LEVELS = ("90%", "95%", "99%")
ATTRIBUTE_RESULTS_READY = False  # stays False until the Attribute Results, Details and Checks have been seen working in the window
ATTRIBUTE_REPORTS_READY = False  # stays False until its PDF and Excel report have been opened and checked in their own programs
ATTRIBUTE_PREVIEW_ENV = "DATAMAPPERX_ATTRIBUTE_RESULTS"  # set to 1 to run Attribute Agreement before it is released, to check it
ATTRIBUTE_REPORTS_ENV = "DATAMAPPERX_ATTRIBUTE_REPORTS"  # set to 1 to generate its PDF and Excel report before they are released
ATTRIBUTE_PENDING = "Attribute Agreement can be set up here. Its results are still being checked, so it cannot be run yet."
ATTRIBUTE_REPORT_PENDING = "Reports for Attribute Agreement are not available yet."
SORT_KEYS = {"Cpk": "cpk", "Ppk": "ppk", "%SV/Tol": "percent_tolerance", "%Study Var": "percent_study_var", "NDC": "ndc",
             "Within %": "within_percent", "vs Standard %": "standard_percent", "Kappa": "kappa_within"}  # the sort choice -> its metric
ORDERS = {"worksheet": "Worksheet order", "filename": "File name order",
          "filetime": "File time order (when each log file was saved)", "timestamp": "Timestamp order (File assignments)",
          "confirmed": "Rows are in measurement order (I confirm)"}
CHECK_TOPICS = {"Amount of data": "Sample Size", "Distinct categories": "NDC"}  # how the Checks tab names a check
GRR_COLUMNS = 7  # the most columns of the tables of the Details: the ANOVA table has 6, Assessment Disagreement 7
WARNING_MARK = "  ‼"  # after a Test Item whose data checks need a look: it says nothing about the acceptance result
CHART_SCALES = (("auto", "Auto"), ("full", "Full Limits"))  # the horizontal scale of a capability histogram
FILE_ORDERS = ("worksheet", "confirmed")  # a RawData.xlsx has no files of its own to order by
STUDY_FACTORS = (1, 2, 3, 4, 5, 6)  # Study Variation = k x SD; 6 is the usual choice (+/- 3 sigma)
PREVIEW_COLUMNS = ("test_item", "sample", "operator", "trial", "value", "lsl", "usl", "unit", "source", "standard")  # all kept with each row
PREVIEW_TITLES = {"test_item": "Test Item", "sample": "Sample ID", "operator": "Operator", "trial": "Trial", "value": "Value",
                  "lsl": "LSL", "usl": "USL", "unit": "Unit", "source": "Source", "standard": "Standard"}
DISPLAY_COLUMNS = ("test_item", "sample", "trial", "value", "lsl", "usl", "unit")  # the ones the table shows
ATTRIBUTE_COLUMNS = ("test_item", "sample", "operator", "trial", "value", "standard")  # ratings have no limits or unit
ALL_ITEMS = "All Test Items"
SECTION_NAMES = {"charts": "Charts", "observations": "Observations used (Excel only)"}
DATE_FORMAT = "%d-%m-%Y"  # DD-MM-YYYY, as the date of study is printed


def attribute_runnable() -> bool:
    """Whether Attribute Agreement may be run: when it is released, or when it is being checked on purpose."""
    return ATTRIBUTE_RESULTS_READY or os.environ.get(ATTRIBUTE_PREVIEW_ENV) == "1"


def attribute_reportable() -> bool:
    """Whether its PDF and Excel report may be generated: when they are released, or when they are being checked on purpose."""
    return ATTRIBUTE_REPORTS_READY or os.environ.get(ATTRIBUTE_REPORTS_ENV) == "1"


def _row(*widgets: QWidget | int, spacing: int = 8) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for item in widgets:
        if isinstance(item, int):
            row.addStretch(item)
        else:
            row.addWidget(item)
    return row


class ValidationWorkspace(QWidget):
    """Data → Analysis Setup → Results → Report, with Run analysis always at hand (Quick Analysis)."""

    def __init__(self, palette: Palette, *, settings=None, save_settings: Callable[[], None] | None = None,
                 source: Callable[[], MappingSource | None] = lambda: None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_tokens = palette
        self.settings = settings
        self._save_settings = save_settings or (lambda: None)
        self._provider = source
        self.tasks = TaskRunner(self)
        self.customers = merge_customers(settings.customer_criteria if settings else {})

        # what the study is made of
        self.study: Study | None = None
        self.dataset: Dataset | None = None
        self.imported: ImportedData | None = None
        self.ratings: ImportedRatings | None = None  # a ratings table (CSV or XLSX) imported for Attribute Agreement
        self.mapping_source: MappingSource | None = None
        self.grouped: Mapping[str, Sequence[LogRecord]] = {}
        self.components: tuple[str, ...] = ()
        self.expected_repeats: int | None = None
        self.assignments: dict[str, dict[str, str]] = {}
        self._checks: dict[str, tuple[list, list]] = {}  # label -> (data checks, guidelines)
        self._ready_message = ""
        self.result_set: ResultSet | None = None
        self.evaluated = None
        self._judge_state: tuple | None = None
        self._date_chosen = False  # the date of study stays as chosen; until then it is today
        self._auto_within_cache: tuple | None = None
        self.setup_error = ""
        self.last_report: Path | None = None
        self._source_key: object = _UNSET  # nothing has been looked at yet
        self._scan: int | None = None
        self._dataset_generation = 0
        self._visible: list = []
        self._charts: list = []
        self._marked: set[int] = set()  # the rows of the table with a warning mark
        self._scaled = False  # the chart shown is a capability histogram, whose horizontal scale can be chosen
        self._advanced_open = False  # Details: whether the user left Advanced Details open
        self._filter_sync = False
        self.preparing = False
        self.running = False
        self.export_busy = False

        self._make_variables()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 6)
        outer.setSpacing(6)
        self._build(outer)
        self._apply_method_layout()
        self._apply_judge_layout()
        self._apply_source_layout()
        self._wire()
        self._refresh_state()

    # ------------------------------------------------------------------ variables
    def _make_variables(self) -> None:
        self.source_var = Var("mapping")
        self.order_var = Var(ORDERS["worksheet"])
        self.item_filter_var = Var(ALL_ITEMS)
        self.method_var = Var("grr")
        self.study_factor_var = Var("6")
        self.assign_var = Var(True)
        self.repeats_var = Var("")
        self.profile_var = Var(NO_CRITERIA)
        self.within_var = Var(WITHIN_CHOICES["auto"])
        self.judge_var = Var(False)
        self.subgroup_var = Var(False)
        self.index_var = Var("cpk")
        self.threshold_var = Var("1.33")
        self.precision_var = Var("2")
        self.search_var = Var("")
        self.filter_var = Var(STATUSES[0])
        self.sort_var = Var("Test Item")
        self.gage_var = Var("")
        self.date_var = Var(date.today().strftime(DATE_FORMAT))  # the date of study: today unless chosen
        self.by_var = Var("")
        self.comments_var = Var("")
        self.sections = {name: Var(name == "charts") for name in ALL_SECTIONS}
        self.message_var = Var("Choose the data, then press Run analysis.")
        self.dataset_var = Var("No data yet.")
        self.hint_var = Var("")
        self.file_var = Var("No file chosen.")
        self.preview_note_var = Var("")
        self.plan_var = Var("")
        self.plan_title_var = Var("")
        self.within_hint_var = Var("")
        self.stale_var = Var("")
        self.summary_var = Var("")
        self.notes_var = Var("")
        self.selected_var = Var("")
        self.chart_scale_var = Var(CHART_SCALES[0][0])
        self.ndc_var = Var("")
        self.tables_note_var = Var("")  # the one line under the tables of an Attribute Agreement item
        self.confidence_var = Var(CONFIDENCE_LEVELS[1])  # Attribute Agreement: 95 %
        self.agreement_var = Var("90")  # its minimum percent agreement, used only when acceptance is on
        self.all_columns_var = Var(False)  # Gage R&R Details: the essential columns, or all of them
        self.review_var = Var("")
        self.coverage_var = Var("")
        self.report_var = Var("")

    def _wire(self) -> None:
        setup = (self.method_var, self.study_factor_var, self.assign_var, self.repeats_var, self.profile_var, self.within_var,
                 self.subgroup_var, self.index_var, self.threshold_var, self.judge_var, self.confidence_var, self.agreement_var)
        for variable in setup:
            variable.trace(self._settings_changed)
        self.method_var.trace(self._apply_method_layout)
        self.judge_var.trace(self._apply_judge_layout)
        self.source_var.trace(self._source_kind_changed)
        self.order_var.trace(self.data_edited)
        self.item_filter_var.trace(lambda: None if self._filter_sync else self._refresh_data_view())
        for variable in (self.filter_var, self.search_var, self.sort_var, self.precision_var):
            variable.trace(self._refresh_table)
        for variable in (self.gage_var, self.date_var, self.by_var, self.comments_var):
            variable.trace(self._info_changed)
        self.all_columns_var.trace(lambda: self._show_details(self.selected_result()))
        self.chart_scale_var.trace(self._draw_chart)

    # ------------------------------------------------------------------ construction
    def _build(self, outer: QVBoxLayout) -> None:
        strip = QHBoxLayout()
        strip.setSpacing(10)
        self.run_button = make_button("Run analysis", self.run_analysis, primary=True)
        self.message_label = label("", "muted", wrap=True)
        bind_label(self.message_label, self.message_var)
        strip.addWidget(self.run_button)
        strip.addWidget(self.message_label, 1)
        strip.addWidget(label("Decimals", "muted"))
        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(2, 8)
        bind_spin(self.precision_spin, self.precision_var)
        strip.addWidget(self.precision_spin)
        self.about_button = make_button("About the method", self.show_about)
        strip.addWidget(self.about_button)
        outer.addLayout(strip)

        self.stale_banner = QFrame()
        self.stale_banner.setObjectName("banner")
        banner = QHBoxLayout(self.stale_banner)
        banner.setContentsMargins(12, 6, 12, 6)
        self.stale_label = QLabel()
        self.stale_label.setWordWrap(True)
        bind_label(self.stale_label, self.stale_var)
        banner.addWidget(self.stale_label, 1)
        self.update_button = make_button("Update results", self.run_analysis, primary=True)
        banner.addWidget(self.update_button)
        self.stale_banner.hide()
        outer.addWidget(self.stale_banner)

        self.tabs = QTabWidget()
        self.data_tab, self.setup_tab, self.results_tab, self.report_tab = (QWidget() for _ in range(4))
        for tab, title in ((self.data_tab, "Data"), (self.setup_tab, "Analysis"), (self.results_tab, "Results"), (self.report_tab, "Report")):
            self.tabs.addTab(tab, title)
        self._build_data()
        self._build_setup()
        self._build_results()
        self._build_report()
        outer.addWidget(self.tabs, 1)

    def _build_data(self) -> None:
        layout = QVBoxLayout(self.data_tab)
        layout.setContentsMargins(12, 12, 12, 8)
        top = QHBoxLayout()
        top.setSpacing(16)
        group = QButtonGroup(self)
        self.source_radios = {
            "mapping": QRadioButton("Use Data Mapping results"), "file": QRadioButton("Import RawData.xlsx"),
            "ratings": QRadioButton("Import ratings (CSV/XLSX)")}
        for button in self.source_radios.values():
            top.addWidget(button)
        bind_radios(self.source_radios, self.source_var, group)
        self.mapping_controls = QWidget()
        mapping_row = QHBoxLayout(self.mapping_controls)
        mapping_row.setContentsMargins(0, 0, 0, 0)
        self.assignments_button = make_button("File assignments…", self.open_assignments)
        mapping_row.addWidget(self.assignments_button)
        self.file_controls = QWidget()
        file_row = QHBoxLayout(self.file_controls)
        file_row.setContentsMargins(0, 0, 0, 0)
        self.file_button = make_button("Choose file…", self.choose_file)
        self.file_label = label("", "muted")
        bind_label(self.file_label, self.file_var)
        file_row.addWidget(self.file_button)
        file_row.addWidget(self.file_label)
        top.addWidget(self.mapping_controls)
        top.addWidget(self.file_controls)
        top.addStretch(1)
        self.settings_button = QToolButton()
        self.settings_button.setText("Settings ▼")
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.order_menu = QMenu(self.settings_button)  # the order of the readings; filled by _apply_source_layout
        self.order_group = QActionGroup(self.order_menu)
        self.settings_button.setMenu(self.order_menu)
        top.addWidget(self.settings_button)
        layout.addLayout(top)

        self.dataset_label = label("", "heading")
        bind_label(self.dataset_label, self.dataset_var)
        layout.addWidget(self.dataset_label)
        self.hint_label = label("", "warn", wrap=True)
        bind_label(self.hint_label, self.hint_var, hide_empty=True)
        layout.addWidget(self.hint_label)
        chooser = QHBoxLayout()
        chooser.addWidget(label("Test Item", "muted"))
        self.item_filter = QComboBox()
        self.item_filter.setMinimumWidth(300)
        self.item_filter.addItem(ALL_ITEMS)
        bind_combo(self.item_filter, self.item_filter_var)
        chooser.addWidget(self.item_filter)
        chooser.addStretch(1)
        layout.addLayout(chooser)
        self.preview = DataTable(self.palette_tokens)
        self.preview.set_table([PREVIEW_TITLES[c] for c in PREVIEW_COLUMNS], [], aligns=["w", "w", "w", "center", "e", "e", "e", "center", "w", "w"],
                               stretch=0)
        self._show_preview_columns(DISPLAY_COLUMNS)
        layout.addWidget(self.preview, 1)
        self.preview_note = label("", "muted", wrap=True)
        bind_label(self.preview_note, self.preview_note_var)
        layout.addWidget(self.preview_note)

    def _show_preview_columns(self, shown: Sequence[str]) -> None:
        for index, key in enumerate(PREVIEW_COLUMNS):
            self.preview.setColumnHidden(index, key not in shown)

    def _build_setup(self) -> None:
        layout = QVBoxLayout(self.setup_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)
        layout.addWidget(label("Plan", "heading"))
        self.plan_title = label("", "heading")
        bind_label(self.plan_title, self.plan_title_var)
        self.plan_label = label("", "muted")  # e.g. 8 Test Items · 10 Samples
        bind_label(self.plan_label, self.plan_var)
        layout.addWidget(self.plan_title)
        layout.addWidget(self.plan_label)
        layout.addSpacing(8)
        layout.addWidget(label("Study purpose", "heading"))
        group = QButtonGroup(self)
        self.method_radios = {"grr": QRadioButton("MSA – Variable Gage R&R"),
                              "capability": QRadioButton("Process Capability – Cp/Cpk, Pp/Ppk"),
                              "attribute": QRadioButton("Attribute Agreement – PASS/FAIL ratings")}
        for button in self.method_radios.values():
            layout.addWidget(button)
        bind_radios(self.method_radios, self.method_var, group)

        # Gage R&R
        self.grr_setup = QWidget()
        grr = QGridLayout(self.grr_setup)
        grr.setContentsMargins(0, 10, 0, 0)
        grr.setColumnStretch(1, 1)
        grr.setVerticalSpacing(8)
        self.study_factor_combo = QComboBox()
        self.study_factor_combo.addItems([str(k) for k in STUDY_FACTORS])
        bind_combo(self.study_factor_combo, self.study_factor_var)
        grr.addWidget(label("Study variation (k)"), 0, 0)
        grr.addLayout(_row(self.study_factor_combo, label("Study Var = k × SD. The usual choice is 6 (±3σ).", "muted"), 1), 0, 1)
        self.assign_check = QCheckBox("Label the repeated readings of a sample as trials 1, 2, 3… when the data have no Trial")
        bind_check(self.assign_check, self.assign_var)
        grr.addWidget(self.assign_check, 1, 0, 1, 2)
        grr.addWidget(label("Only to organise the data in rows. It is not taken as the order of measurement.", "muted"), 2, 1)
        self.repeats_edit = QLineEdit()
        self.repeats_edit.setMaximumWidth(60)
        bind_edit(self.repeats_edit, self.repeats_var)
        grr.addWidget(label("Readings per sample"), 3, 0)
        grr.addLayout(_row(self.repeats_edit, label("optional: samples with another count are flagged", "muted"), 1), 3, 1)
        self.customer_combo = QComboBox()
        self.customer_combo.setMinimumWidth(180)
        self.customer_combo.addItems([NO_CRITERIA, *self.customers])
        bind_combo(self.customer_combo, self.profile_var)
        self.criteria_button = make_button("Customers…", self.open_customers)
        grr.addWidget(label("Acceptance criteria"), 4, 0)
        grr.addLayout(_row(self.customer_combo, self.criteria_button, label("optional: adds PASS / FAIL, never changes a figure", "muted"),
                           1), 4, 1)
        layout.addWidget(self.grr_setup)

        # Process capability
        self.cap_setup = QWidget()
        cap = QVBoxLayout(self.cap_setup)
        cap.setContentsMargins(0, 10, 0, 0)
        self.subgroup_check = QCheckBox("Group readings by Sample ID")
        bind_check(self.subgroup_check, self.subgroup_var)
        self.judge_check = QCheckBox("Enable acceptance criteria")
        bind_check(self.judge_check, self.judge_var)
        cap.addWidget(self.subgroup_check)
        cap.addWidget(self.judge_check)
        self.criteria_row = QWidget()
        criteria = QHBoxLayout(self.criteria_row)
        criteria.setContentsMargins(24, 0, 0, 0)
        index_group = QButtonGroup(self)
        self.index_radios = {"cpk": QRadioButton("Cpk (Within)"), "ppk": QRadioButton("Ppk (Overall)")}
        for button in self.index_radios.values():
            criteria.addWidget(button)
        bind_radios(self.index_radios, self.index_var, index_group)
        criteria.addWidget(label("must exceed", "muted"))
        self.threshold_edit = QLineEdit()
        self.threshold_edit.setMaximumWidth(70)
        bind_edit(self.threshold_edit, self.threshold_var)
        criteria.addWidget(self.threshold_edit)
        criteria.addStretch(1)
        cap.addWidget(self.criteria_row)
        self.advanced_button = make_button("Advanced Settings ►", self._toggle_advanced)
        cap.addWidget(self.advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        advanced = QHBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addWidget(label("Within sigma"))
        self.within_combo = QComboBox()
        self.within_combo.addItems(list(WITHIN_CHOICES.values()))
        self.within_combo.setMinimumWidth(380)
        bind_combo(self.within_combo, self.within_var)
        advanced.addWidget(self.within_combo)
        self.within_hint = label("", "muted")
        bind_label(self.within_hint, self.within_hint_var)
        advanced.addWidget(self.within_hint)
        advanced.addStretch(1)
        self.advanced.hide()
        cap.addWidget(self.advanced)
        layout.addWidget(self.cap_setup)

        # Attribute Agreement
        self.attr_setup = QWidget()
        attr = QVBoxLayout(self.attr_setup)
        attr.setContentsMargins(0, 10, 0, 0)
        self.confidence_combo = QComboBox()
        self.confidence_combo.addItems(CONFIDENCE_LEVELS)
        bind_combo(self.confidence_combo, self.confidence_var)
        attr.addLayout(_row(label("Confidence level"), self.confidence_combo, label("for the interval of each percent agreement", "muted"), 1))
        self.attr_judge_check = QCheckBox("Enable acceptance criteria")
        bind_check(self.attr_judge_check, self.judge_var)
        attr.addWidget(self.attr_judge_check)
        self.agreement_row = QWidget()
        agreement = QHBoxLayout(self.agreement_row)
        agreement.setContentsMargins(24, 0, 0, 0)
        agreement.addWidget(label("Minimum agreement", "muted"))
        self.agreement_edit = QLineEdit()
        self.agreement_edit.setMaximumWidth(60)
        bind_edit(self.agreement_edit, self.agreement_var)
        agreement.addWidget(self.agreement_edit)
        agreement.addWidget(label("% for Within Appraisers and vs Standard, each on its own", "muted"))
        agreement.addStretch(1)
        attr.addWidget(self.agreement_row)
        layout.addWidget(self.attr_setup)
        layout.addStretch(1)

    def _build_results(self) -> None:
        layout = QVBoxLayout(self.results_tab)
        layout.setContentsMargins(12, 12, 12, 8)
        head = QHBoxLayout()
        self.summary_label = label("", "heading")
        bind_label(self.summary_label, self.summary_var)
        head.addWidget(self.summary_label)
        self.notes_bar = QWidget()
        notes = QHBoxLayout(self.notes_bar)
        notes.setContentsMargins(16, 0, 0, 0)
        self.notes_label = label("", "warn", wrap=True)
        bind_label(self.notes_label, self.notes_var)
        self.notes_button = make_button("Read the notes…", self.show_notes)
        notes.addWidget(self.notes_label, 1)
        notes.addWidget(self.notes_button)
        self.notes_bar.hide()
        head.addWidget(self.notes_bar, 1)
        layout.addLayout(head)

        # Two panes: above each other, or side by side when the window is wide enough
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.table_page = QWidget()
        table = QVBoxLayout(self.table_page)
        table.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        filters.addWidget(label("Search", "muted"))
        self.search_edit = QLineEdit()
        bind_edit(self.search_edit, self.search_var)
        filters.addWidget(self.search_edit, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(STATUSES)
        bind_combo(self.filter_combo, self.filter_var)
        self.filter_combo.hide()
        filters.addWidget(self.filter_combo)
        self.sort_combo = QComboBox()
        filters.addWidget(self.sort_combo)
        table.addLayout(filters)
        self.table = DataTable(self.palette_tokens)
        self.table.rowSelected.connect(self._select_result)
        self.table.cellPressed.connect(self._table_click)
        self.table.cellHover.connect(self._table_hover)
        table.addWidget(self.table, 1)
        self.review_label = label("", "warn", wrap=True)
        bind_label(self.review_label, self.review_var, hide_empty=True)
        table.addWidget(self.review_label)

        self.right_pane = QWidget()
        right = QVBoxLayout(self.right_pane)
        right.setContentsMargins(0, 0, 0, 0)
        self.selected_label = label("", "heading")
        bind_label(self.selected_label, self.selected_var, hide_empty=True)
        right.addWidget(self.selected_label)
        self.result_tabs = QTabWidget()
        right.addWidget(self.result_tabs, 1)
        self.split.addWidget(self.table_page)
        self.split.addWidget(self.right_pane)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 3)
        layout.addWidget(self.split, 1)

        # Charts
        chart_page = QWidget()
        charts = QVBoxLayout(chart_page)
        charts.setContentsMargins(4, 4, 4, 4)
        self.chart_tools = QWidget()  # only for a capability histogram
        tools = QHBoxLayout(self.chart_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addStretch(1)
        self.chart_scale_buttons = {}
        scale_group = QButtonGroup(self)
        for value, text in CHART_SCALES:
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            tools.addWidget(button)
            self.chart_scale_buttons[value] = button
        bind_radios(self.chart_scale_buttons, self.chart_scale_var, scale_group)
        self.chart_tools.hide()
        charts.addWidget(self.chart_tools)
        self.chart_panel = ChartPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.chart_panel)
        charts.addWidget(scroll, 1)
        self.result_tabs.addTab(chart_page, "Charts")

        # Details: an item that could not be analysed says why; Capability is a tree of figures; Gage R&R and Attribute are tables
        self.details_stack = QStackedWidget()
        self.session = ReadOnlyTextView()
        self.details = QTreeWidget()  # a capability item: its figures as a table
        self.details.setHeaderLabels(["Metric", "Value"])
        self.details.setRootIsDecorated(True)
        self.details.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.details.setColumnWidth(0, 260)
        self.details.itemClicked.connect(self._details_click)
        self.details.itemExpanded.connect(lambda _item: self._remember_advanced())
        self.details.itemCollapsed.connect(lambda _item: self._remember_advanced())
        self.grr_frame = QWidget()  # a Gage R&R item: its tables, NDC above them
        grr = QVBoxLayout(self.grr_frame)
        grr.setContentsMargins(0, 0, 0, 0)
        self.grr_headline = QWidget()  # NDC and the column choice: Gage R&R only
        headline = QHBoxLayout(self.grr_headline)
        headline.setContentsMargins(0, 0, 0, 0)
        headline.addWidget(label("Number of Distinct Categories (NDC)"))
        self.ndc_label = label("", "heading")
        bind_label(self.ndc_label, self.ndc_var)
        headline.addWidget(self.ndc_label)
        headline.addStretch(1)
        self.all_columns_check = QCheckBox("All columns")
        bind_check(self.all_columns_check, self.all_columns_var)
        headline.addWidget(self.all_columns_check)
        grr.addWidget(self.grr_headline)
        self.grr_tree = DataTable(self.palette_tokens)
        self.grr_tree.horizontalHeader().hide()
        self.grr_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        grr.addWidget(self.grr_tree, 1)
        self.tables_note = label("", "muted", wrap=True)
        bind_label(self.tables_note, self.tables_note_var, hide_empty=True)
        grr.addWidget(self.tables_note)
        for page in (self.session, self.details, self.grr_frame):
            self.details_stack.addWidget(page)
        self.result_tabs.addTab(self.details_stack, "Details")

        # Checks: Check | Result | Status, a section for the data and one for the guidelines
        self.checks_page = QWidget()
        checks = QVBoxLayout(self.checks_page)
        checks.setContentsMargins(4, 4, 4, 4)
        self.checks_tree = QTreeWidget()
        self.checks_tree.setHeaderLabels(["Check", "Result", "Status"])
        self.checks_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.checks_tree.setColumnWidth(0, 150)
        self.checks_tree.header().setStretchLastSection(False)
        self.checks_tree.header().setSectionResizeMode(1, self.checks_tree.header().ResizeMode.Stretch)
        checks.addWidget(self.checks_tree, 1)
        self.notes_link = make_button("Notes on this analysis…", self.show_notes)  # what the report says about the readings
        self.notes_link.hide()
        checks.addWidget(self.notes_link, 0, Qt.AlignmentFlag.AlignLeft)
        self.result_tabs.addTab(self.checks_page, "Checks")
        self.sort_combo.currentTextChanged.connect(lambda text: self.sort_var.set(text) if text else None)

    def _build_report(self) -> None:
        layout = QVBoxLayout(self.report_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        columns = QHBoxLayout()
        columns.setSpacing(40)
        left = QGridLayout()
        left.setVerticalSpacing(8)
        left.addWidget(label("Study information (optional)", "heading"), 0, 0, 1, 2)
        self.info_entries: dict[str, QLineEdit] = {}
        fields = (("Gage name", self.gage_var), ("Date of study", self.date_var), ("Reported by", self.by_var), ("Misc", self.comments_var))
        for row, (title, variable) in enumerate(fields, start=1):
            left.addWidget(label(title), row, 0)
            entry = QLineEdit()
            entry.setMinimumWidth(280)
            bind_edit(entry, variable)
            if variable is self.date_var:  # chosen from a calendar, never typed
                entry.setReadOnly(True)
                entry.setMaximumWidth(130)
                self.date_button = make_button("Choose date…", self.choose_date)
                left.addLayout(_row(entry, self.date_button, 1), row, 1)
            else:
                left.addWidget(entry, row, 1)
            self.info_entries[title] = entry
        left.addWidget(label("Shown with each item when entered. The date of study is today unless you choose another day "
                             "(DD-MM-YYYY).", "muted", wrap=True), len(fields) + 1, 0, 1, 2)
        left.setRowStretch(len(fields) + 2, 1)
        columns.addLayout(left)

        right = QVBoxLayout()
        right.addWidget(label("Include", "heading"))
        self.section_checks = {}
        for name in ALL_SECTIONS:
            check = QCheckBox(SECTION_NAMES[name])
            bind_check(check, self.sections[name])
            right.addWidget(check)
            self.section_checks[name] = check
        items = QHBoxLayout()
        self.coverage_label = label("", "heading")
        bind_label(self.coverage_label, self.coverage_var)
        items.addWidget(self.coverage_label, 1)
        items.addWidget(make_button("None", lambda: self._select_items(False)))
        items.addWidget(make_button("All", lambda: self._select_items(True)))
        right.addLayout(items)
        self.item_list = QListWidget()
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.item_list.setMinimumWidth(320)
        self.item_list.itemSelectionChanged.connect(self._update_coverage)
        right.addWidget(self.item_list, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

        actions = QHBoxLayout()
        self.pdf_button = make_button("Generate PDF…", lambda: self.generate_report(".pdf"), primary=True)
        self.excel_button = make_button("Generate Excel…", lambda: self.generate_report(".xlsx"))
        self.report_label = label("", "muted", wrap=True)
        bind_label(self.report_label, self.report_var)
        self.open_button = make_button("Open", self.open_report)
        self.open_button.setEnabled(False)
        actions.addWidget(self.pdf_button)
        actions.addWidget(self.excel_button)
        actions.addWidget(self.report_label, 1)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)

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

    def _dialog_parent(self) -> QWidget:
        return self.window()

    def _order_key(self) -> str:
        label_text = self.order_var.get()
        return next((key for key, text in ORDERS.items() if text == label_text), "worksheet")

    def set_customers(self, customers, selected=None) -> None:
        """Adopt the customers edited in the dialog and keep them for next time."""
        self.customers = dict(customers)
        if self.settings is not None:
            self.settings.customer_criteria = customers_to_json(self.customers)
            self._save_settings()
        self.customer_combo.blockSignals(True)
        self.customer_combo.clear()
        self.customer_combo.addItems([NO_CRITERIA, *self.customers])
        self.customer_combo.blockSignals(False)
        target = selected or self.profile_var.get()
        previous = self.profile_var.get()
        self.profile_var.set(target if target in self.customers else NO_CRITERIA)
        bind_index = self.customer_combo.findText(self.profile_var.get())
        self.customer_combo.setCurrentIndex(bind_index)
        if self.profile_var.get() == previous:
            self._settings_changed()  # the same customer with new limits

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        for table in (self.preview, self.table, self.grr_tree):
            table.set_palette(palette)
        self._show_details(self.selected_result())
        self._show_checks(self.selected_result())
        self._draw_chart()

    # ------------------------------------------------------------------ layout switches
    def _apply_method_layout(self) -> None:
        method = self.method_var.get()
        for name, frame in (("grr", self.grr_setup), ("capability", self.cap_setup), ("attribute", self.attr_setup)):
            frame.setVisible(method == name)
        choices = {"capability": ("Test Item", "Cpk", "Ppk"), "attribute": ("Test Item", "Within %", "vs Standard %", "Kappa")}.get(
            method, ("Test Item", "%SV/Tol", "%Study Var", "NDC"))
        current = self.sort_var.get() if self.sort_var.get() in choices else "Test Item"
        self.sort_combo.blockSignals(True)
        self.sort_combo.clear()
        self.sort_combo.addItems(choices)
        self.sort_combo.setCurrentText(current)
        self.sort_combo.blockSignals(False)
        if self.sort_var.get() != current:
            self.sort_var.set(current)
        attribute = method == "attribute"  # ratings have a Rating and a Standard, no limits or unit
        self._show_preview_columns(ATTRIBUTE_COLUMNS if attribute else DISPLAY_COLUMNS)
        titles = {**PREVIEW_TITLES, "value": "Rating" if attribute else "Value", "operator": "Appraiser" if attribute else "Operator"}
        self.preview.table_model.set_headings([titles[c] for c in PREVIEW_COLUMNS])

    def _toggle_advanced(self) -> None:
        opened = self.advanced.isHidden()
        self.advanced.setVisible(opened)
        self.advanced_button.setText("Advanced Settings ▼" if opened else "Advanced Settings ►")

    def _apply_judge_layout(self) -> None:
        for row in (self.criteria_row, self.agreement_row):  # the threshold of the method on screen; the other one is hidden with its frame
            row.setVisible(bool(self.judge_var.get()))

    def _apply_source_layout(self) -> None:
        """What belongs to the chosen source: File assignments only for Data Mapping results that exist; the choice file for an import."""
        mapping = self.source_var.get() == "mapping"
        self.mapping_controls.setVisible(mapping and bool(self.grouped))
        self.file_controls.setVisible(not mapping)
        self.file_button.setText("Import ratings…" if self.source_var.get() == "ratings" else "Choose file…")
        keys = list(ORDERS) if mapping else list(FILE_ORDERS)
        if self._order_key() not in keys:
            self.order_var.set(ORDERS["worksheet"])
        self.order_menu.clear()
        for action in list(self.order_group.actions()):
            self.order_group.removeAction(action)
        self.order_menu.addAction("Order of the readings").setEnabled(False)
        for key in keys:
            action = QAction(ORDERS[key], self.order_menu, checkable=True)
            action.setChecked(ORDERS[key] == self.order_var.get())
            action.triggered.connect(lambda _checked=False, text=ORDERS[key]: self.order_var.set(text))
            self.order_group.addAction(action)
            self.order_menu.addAction(action)

    def _source_kind_changed(self) -> None:
        self._apply_source_layout()
        self._prepare_dataset()

    # ------------------------------------------------------------------ the data
    def source_changed(self) -> None:
        """Data Mapping's results changed (a scan, a selection, a duplicate choice). Picked up now if on screen, else on show."""
        if self.isVisible():
            self.on_show()

    def on_show(self) -> None:
        """Compare Data Mapping's current results with the snapshot (cheap) and take a new one only if they differ."""
        if not self._date_chosen:
            self.date_var.set(date.today().strftime(DATE_FORMAT))  # the date of study is today, also when the program stays open overnight
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
            self._apply_source_layout()
            if source.scan != self._scan:  # a new scan is a new study: nothing of the old files carries over
                self._scan = source.scan
                self.assignments.clear()
                self.repeats_var.set(str(source.expected_repeats) if source.expected_repeats else "")
                self.study = self.result_set = self.evaluated = None
                self.profile_var.set(NO_CRITERIA)
                self.judge_var.set(False)
                self._fill_items()
                self._refresh_table()
        if self.source_var.get() == "mapping":
            self._prepare_dataset()

    def choose_ratings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self._dialog_parent(), "Choose a ratings table", "",
                                              "CSV or Excel (*.csv *.xlsx *.txt *.tsv);;All files (*.*)")
        if not path:
            return
        name = Path(path).name
        self.message_var.set(f"Reading {name}…")
        self.preparing = True
        self._refresh_state()

        def failed(exc):
            self.preparing = False
            self.message_var.set(f"Could not read {name}: {exc}")
            self._refresh_state()

        def loaded(table):
            from .ratings_import import RatingsImportDialog

            self.preparing = False
            self.message_var.set("Choose the columns of the ratings, then press Import.")
            self._refresh_state()
            RatingsImportDialog(self._dialog_parent(), table, self._ratings_ready).present()

        self.tasks.run(lambda _report: read_ratings_table(path), on_success=loaded, on_error=failed)

    def _ratings_ready(self, imported: ImportedRatings) -> None:
        """The user imported a ratings table: Attribute Agreement is its method, and its dataset is the study's data."""
        self.ratings = imported
        self.file_var.set(str(imported.record.get("file", "")))
        self._ready_message = (f"Imported {imported.ratings} ratings of {imported.samples} samples. "
                               "Press Run analysis, or set up the study first.")
        if self.method_var.get() != "attribute":
            self.method_var.set("attribute")
        if self.source_var.get() != "ratings":
            self.source_var.set("ratings")  # prepares the dataset
        else:
            self._prepare_dataset()

    def choose_file(self) -> None:
        if self.source_var.get() == "ratings":
            return self.choose_ratings()
        path, _ = QFileDialog.getOpenFileName(self._dialog_parent(), "Choose a RawData.xlsx", "", "Excel workbook (*.xlsx);;All files (*.*)")
        if path:
            self.open_file(Path(path))
        return None

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

    def open_assignments(self) -> None:
        from .validation_dialogs import AssignmentDialog

        AssignmentDialog(self).present()

    def open_customers(self) -> None:
        from .validation_dialogs import CustomersDialog

        CustomersDialog(self).present()

    def data_edited(self) -> None:
        """File assignments or the order changed: take a new snapshot."""
        if self.mapping_source is not None or self.imported is not None or self.ratings is not None:
            self._prepare_dataset()

    def _prepare_dataset(self) -> None:
        self._dataset_generation += 1
        generation, order = self._dataset_generation, self._order_key()
        if self.source_var.get() == "mapping":
            source = self.mapping_source
            if source is None or not source.components:
                self._clear_dataset("No Data Mapping results yet. Scan logs and choose test items in Data Mapping, or import a RawData.xlsx.")
                return
            assignments = {k: dict(v) for k, v in self.assignments.items()}

            def work(_report):
                return build_mapping_dataset(source, assignments, order)
        else:
            ratings = self.source_var.get() == "ratings"
            imported = self.ratings if ratings else self.imported
            if imported is None:
                self._clear_dataset("Import a ratings table (CSV or XLSX) to analyse." if ratings else "Choose a RawData.xlsx to analyse.")
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
        self.preview.table_model.set_rows([])
        self._fill_item_filter([])
        self.preview_note_var.set("")
        self._apply_source_layout()
        self.setup_error = ""
        self.message_var.set(message)
        self._refresh_table()
        self._fill_items()
        self._refresh_state()

    def _mapping_record(self) -> dict:
        record = {"source": self.source_var.get(), "components": list(self.components) if self.source_var.get() == "mapping" else [],
                  "assignments": {k: dict(v) for k, v in self.assignments.items()},
                  "order": self._order_key(), "file": self.file_var.get() if self.source_var.get() == "file" else ""}
        if self.source_var.get() == "ratings" and self.ratings is not None:
            record["ratings"] = self.ratings.record  # which column holds what, and the categories: part of what the results depend on
        return record

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
        self.message_var.set(self._ready_message or "Ready. Press Run analysis, or set up the study first.")
        self._ready_message = ""
        self._settings_changed()  # shows the data as they will be analysed, with the design applied

    def _refresh_data_view(self) -> None:
        """The data tab: a four-figure summary, warnings only when there is something to fix, and the readings as the analysis sees them."""
        dataset, study = self.dataset, self.study
        if dataset is None or study is None:
            return
        source = self.source_var.get()
        carried = self.imported if source == "file" else self.ratings if source == "ratings" else None  # what the import said
        rows, warnings = dataset.observations, list(carried.warnings) if carried else []
        try:
            rows = study.analysis_observations()
        except DesignError as exc:
            warnings.append(f"The study design cannot be applied to these data: {exc}")
        else:
            if study.options.method == "grr":
                warnings += describe_layouts(rows, only_unbalanced=True)
                if not study.options.assign_trials and any(not str(row.trial).strip() for row in rows):
                    warnings.append("These readings have no Trial. Turn on trial labelling in the Analysis tab, or give each file its "
                                    "trial in File assignments.")
            elif study.options.method == "attribute":
                warnings += attribute_warnings(rows)
            elif dataset.order_basis == "worksheet":
                warnings.append("The readings are in worksheet order, which is not a verified order of measurement. Capability depends "
                                "on that order: choose another in Settings.")
        attribute = study.options.method == "attribute"
        self.dataset_var.set(attribute_summary(rows) if attribute else self._summary(rows))
        self.hint_var.set("  ".join(warnings))
        items = list(dict.fromkeys(str(row.test_item) for row in rows))
        self._fill_item_filter(items)
        chosen = self.item_filter_var.get()
        listed = [entry for entry in self._with_trials(rows) if chosen == ALL_ITEMS or str(entry[0].test_item) == chosen]
        shown_rows, tags = [], []
        for row, trial, inferred in listed[:PREVIEW_ROWS]:
            shown_rows.append((row.test_item, row.sample_id, row.operator or ("1" if attribute else ""), trial, self._cell(row.value),
                               self._cell(row.lsl), self._cell(row.usl), row.unit, row.source, row.standard))
            tags.append("inferred" if inferred else "")
        self.preview.table_model.set_rows(shown_rows, tags)
        self.preview.fit_columns(stretch=0, max_width=300)
        shown = len(shown_rows)
        note = f"Showing the first {shown} of {len(listed)} readings." if shown < len(listed) else f"{len(listed)} readings."
        if any(inferred for _, _, inferred in listed[:shown]):
            note += " Trial numbers in grey are counted from the row order of each sample; they are not the order of measurement."
        self.preview_note_var.set(note)

    @staticmethod
    def _cell(value) -> str:
        """A reading as the table shows it: at least six significant digits, written out in full. The data keep their own value."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            whole = len(str(int(abs(number)))) if math.isfinite(number) else 0  # a large reading keeps its integer digits and 3 more
            return plain_number(number, max(6, whole + 3))
        return "" if value is None else str(value)

    @staticmethod
    def _summary(rows: Sequence) -> str:
        systems: dict = defaultdict(list)
        for row in rows:
            systems[(row.test_item, row.tester, row.slot)].append(row)
        layouts = [layout_of(group) for group in systems.values()]
        fewest, most = min((one.fewest for one in layouts), default=0), max((one.most for one in layouts), default=0)
        trials = str(most) if fewest == most else f"{fewest}–{most}"
        return (f"Test Items {len({row.test_item for row in rows})}  ·  Samples {len({row.sample_id for row in rows})}  ·  "
                f"Total Readings {len(rows)}  ·  Trials per Sample {trials}")

    def _fill_item_filter(self, items: Sequence[str]) -> None:
        self._filter_sync = True  # rebuilding the list is not a choice to redraw for: the table is being redrawn anyway
        try:
            current = self.item_filter_var.get()
            self.item_filter.blockSignals(True)
            self.item_filter.clear()
            self.item_filter.addItems([ALL_ITEMS, *items])
            self.item_filter.blockSignals(False)
            self.item_filter_var.set(current if current in (ALL_ITEMS, *items) else ALL_ITEMS)
            self.item_filter.setCurrentText(self.item_filter_var.get())
        finally:
            self._filter_sync = False

    def _with_trials(self, rows: Sequence) -> list[tuple]:
        """(row, Trial to show, whether it is inferred). Where the data have no Trial the analysis counts the readings of a sample
        in row order; the worksheet shows those counts too, marked as inferred: they are not the order of measurement."""
        study = self.study
        if study is None or study.options.method != "grr" or not study.options.assign_trials:
            return [(row, row.trial, False) for row in rows]
        with_trial = {(row.test_item, row.tester, row.slot) for row in rows if str(row.trial).strip()}
        counts: dict = defaultdict(int)
        shown = []
        for row in rows:
            system = (row.test_item, row.tester, row.slot)
            if system in with_trial:
                shown.append((row, row.trial, False))
                continue
            key = (system, str(row.sample_id).strip(), str(row.operator).strip())
            counts[key] += 1
            shown.append((row, str(counts[key]), True))
        return shown

    # ------------------------------------------------------------------ the study
    def _within_key(self) -> str:
        text = self.within_var.get()
        return next((key for key, name in WITHIN_CHOICES.items() if name == text), "auto")

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
            try:
                factor = int(self.study_factor_var.get())
            except ValueError:
                factor = 0
            if factor not in STUDY_FACTORS:
                raise ValueError("Study variation (k) must be a whole number from 1 to 6.")
            design = {}  # one tester: the study estimates repeatability only
            options = StatisticalOptions(method="grr", study_factor=float(factor),
                                         expected_repeats=int_field(self.repeats_var.get(), "Readings per sample", 2),
                                         assign_trials=self.assign_var.get())
        elif method == "attribute":
            design = {}  # the ratings are analysed as they are
            level, _minimum = attribute_settings(self.confidence_var.get(), self.judge_var.get(), self.agreement_var.get())
            options = StatisticalOptions(method="attribute", confidence=level)
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
        if method == "attribute":
            _level, minimum = attribute_settings(self.confidence_var.get(), True, self.agreement_var.get())
            return EvaluationSettings(agreement_min=minimum)
        try:
            threshold = float(self.threshold_var.get())
        except ValueError:
            raise ValueError(f"{self.index_var.get().capitalize()} must exceed: enter a number such as 1.33.") from None
        return EvaluationSettings(cpk_threshold=threshold, decision_metric=self.index_var.get())

    def _settings_changed(self) -> None:
        study = self.study
        if study is None:
            self._refresh_state()
            return
        try:
            options, design, evaluation, judge = self._read_setup()
        except ValueError as exc:
            self.setup_error = str(exc)
            self._refresh_data_view()
            self._refresh_state()
            return
        self.setup_error = ""
        changed = (evaluation, judge) != (study.evaluation, self._judge_state)
        study.options, study.design, study.evaluation = options, design, evaluation
        self._judge_state = judge
        study.mapping = self._mapping_record()
        self._refresh_data_view()
        if self.result_set is not None and changed:
            self._evaluate()  # new criteria for the same numbers
        self._refresh_state()

    def choose_date(self) -> None:
        from .validation_dialogs import DatePickerDialog

        try:
            current = datetime.strptime(self.date_var.get(), DATE_FORMAT).date()
        except ValueError:
            current = date.today()
        DatePickerDialog(self._dialog_parent(), current, self._date_picked).present()

    def _date_picked(self, day: date) -> None:
        self._date_chosen = True
        self.date_var.set(day.strftime(DATE_FORMAT))

    def _info_changed(self) -> None:
        if self.study is not None:
            self.study.info = StudyInfo(self.gage_var.get().strip(), self.date_var.get().strip(), self.by_var.get().strip(),
                                        self.comments_var.get().strip())

    def _plan_text(self) -> str:
        """The data of the study in one line: 8 Test Items · 10 Samples."""
        if self.study is None or self.dataset is None:
            return ""
        items, samples = len(self.dataset.items), len({o.sample_id for o in self.dataset.observations})
        line = f"{items} Test Item{'s' if items != 1 else ''} · {samples} Sample{'s' if samples != 1 else ''}"
        if self.study.options.method == "attribute":
            appraisers = len({o.operator for o in self.dataset.observations})
            line += f" · {appraisers} Appraiser{'s' if appraisers != 1 else ''}"
        return line

    def _within_text(self) -> str:
        """Which within sigma is in use (it may be chosen from the subgroup size), shown with the advanced settings."""
        if self.study is None or self.study.options.method != "capability":
            return ""
        used = "average moving range" if self.study.options.within_method == "individuals" else "pooled standard deviation"
        return f"In use: {used}"

    # ------------------------------------------------------------------ running
    def run_analysis(self) -> None:
        study = self.study
        if study is None or self.busy:
            return
        if self.method_var.get() == "attribute" and not attribute_runnable():
            self.message_var.set(ATTRIBUTE_PENDING)
            return
        self._settings_changed()
        if self.setup_error:
            self.message_var.set(self.setup_error)
            self.tabs.setCurrentWidget(self.setup_tab)
            return
        try:
            plan = study.plan_statistics()  # the study is read here, on this thread
        except ValueError as exc:
            self.message_var.set(str(exc))
            self.tabs.setCurrentWidget(self.setup_tab)
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
            self.tabs.setCurrentWidget(self.results_tab)
            return None

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
        self._checks = self._compute_checks()
        self._fill_items()
        self._refresh_table()

    def _compute_checks(self) -> dict[str, tuple[list, list]]:
        """The data checks and guidelines of every result (screening aids: they change no figure and are not reported)."""
        if self.evaluated is None or self.study is None:
            return {}
        dataset = self.study.dataset
        known, note = dataset.order_basis == "acquisition", self._order_note(dataset)
        return {result.label: result_checks(result, order_known=known, order_note=note) for result in self.evaluated.results}

    @staticmethod
    def _order_note(dataset) -> str:
        if dataset.order_basis != "acquisition":
            return " On the Data tab, choose File time order, or confirm that the rows are in measurement order."
        if "log file was saved" in dataset.description:
            return " Order of the readings: the time each log file was saved, taken as the order of measurement."
        if "sorted by timestamp" in dataset.description:
            return " Order of the readings: the timestamps you assigned."
        return " Order of the readings: as you confirmed."

    def show_notes(self) -> None:
        if self.evaluated is None:
            return
        lines = []
        for item_name, message in self._problems():
            lines += [f"Not analysed: {item_name}", message, ""]
        for condition in self.evaluated.record.validation.conditions:
            kind = "Warning" if condition.severity.value == "warning" else "Information"
            lines += [f"{CONDITION_TITLES.get(condition.code, condition.code)} ({kind})", condition.message, ""]
        if self.evaluated.record.method == "capability":
            lines += ["Screening in this program", "The Checks tab (Results) does screen stability (I and MR chart tests) and normality "
                      "(Anderson-Darling) on the readings. Those checks are an aid: they are not printed in the report, so the "
                      "notes above stand in the report as they are.", ""]
        lines.append("These notes do not block a result or a report; the report prints them.")
        ReportDialog(self._dialog_parent(), "Notes on this analysis", "What to keep in mind when reading the results",
                     "\n".join(lines)).present()

    # ------------------------------------------------------------------ what is enabled and said
    def _refresh_state(self) -> None:
        has_data = self.dataset is not None and self.study is not None
        has_result = self.result_set is not None and self.evaluated is not None
        stale = self.stale
        pending = ATTRIBUTE_PENDING if self.method_var.get() == "attribute" and not attribute_runnable() else ""
        blocked = self.setup_error or pending
        self.run_button.setEnabled(has_data and not blocked and not self.busy)
        for tab, enabled in ((self.setup_tab, has_data), (self.results_tab, has_result), (self.report_tab, has_result)):
            self.tabs.setTabEnabled(self.tabs.indexOf(tab), enabled)
        if blocked:
            self.message_var.set(blocked)
        self.plan_var.set(self._plan_text())
        self.plan_title_var.set(PLAN_TITLES[self.method_var.get()] if self.dataset is not None else "")
        self.within_hint_var.set(self._within_text())
        if stale and not self.running:
            self.stale_var.set("The data or the study settings changed since these results were computed. They are shown for reference "
                               "only and cannot be reported. Update the results to continue.")
            self.stale_banner.show()
        else:
            self.stale_banner.hide()
        self.update_button.setEnabled(has_data and not blocked and not self.busy)
        withheld = has_result and self.evaluated.record.method == "attribute" and not attribute_reportable()
        reportable = has_result and not stale and not self.busy and not withheld
        for button in (self.pdf_button, self.excel_button):
            button.setEnabled(reportable)
        self._refresh_notes()
        if withheld:
            self.report_var.set(ATTRIBUTE_REPORT_PENDING)
        elif has_result and stale and not self.report_var.get().startswith("Saved"):
            self.report_var.set("Update the results before generating a report.")
        elif (has_result and not stale and self.report_var.get().startswith("Update the results")) or \
                self.report_var.get() == ATTRIBUTE_REPORT_PENDING:
            self.report_var.set("")

    def _problems(self) -> list[tuple[str, str]]:
        """(test item, message) for every item that could not be analysed: what has to be fixed in the data or the settings."""
        if self.result_set is None:
            return []
        return [(stat.label, issue.message) for stat in self.result_set.statistics for issue in stat.issues if issue.severity == "error"]

    def _refresh_notes(self) -> None:
        failed = {item_name for item_name, _ in self._problems()}
        if failed:  # what has to be fixed; every other note is on the Checks tab
            self.notes_var.set(f"{len(failed)} item{'s' if len(failed) != 1 else ''} could not be analysed. Read the notes to see what to fix.")
            self.notes_bar.show()
        else:
            self.notes_var.set("")
            self.notes_bar.hide()

    # ------------------------------------------------------------------ results
    def _refresh_table(self) -> None:
        evaluated = self.evaluated
        results = list(evaluated.results) if evaluated else []
        if not results:
            self.table.table_model.set_rows([])
            self._visible, self._charts = [], []
            self.summary_var.set("")
            self.selected_var.set("")
            self.review_var.set("")
            self.chart_panel.set_specs([])
            self._marked = set()
            self._show_details(None)
            self._show_checks(None)
            return
        judged = evaluated.record.judged
        self.summary_var.set(summary_line(results, judged, sum(1 for result in results if self._needs_review(result))))
        self.filter_combo.setVisible(judged)  # filtering by result needs criteria
        flagged = [r for r in results if r.details.get("acceptance_conflicts")]
        if flagged:
            names = ", ".join(dict.fromkeys(review_note(r) for r in flagged))
            self.review_var.set(
                f"Review needed: {len(flagged)} of {len(results)} results are acceptable for the applied criteria, but a metric that "
                f"is not applied would fail on its own limits ({names}; see the Review column). The measurement system may not "
                "distinguish the sampled parts, or the tolerance is much wider than the process spread.")
        else:
            self.review_var.set("")
        query, wanted = self.search_var.get().casefold(), self.filter_var.get() if judged else STATUSES[0]
        self._visible = [r for r in results if query in r.label.casefold() and (wanted == STATUSES[0] or r.status == wanted)]
        metric = SORT_KEYS.get(self.sort_var.get())
        self._visible.sort(key=lambda r: (r.metrics.get(metric) is None, r.metrics.get(metric) or 0) if metric else (r.test_item, r.system))
        if not self._visible:
            self.table.table_model.set_rows([])
            self._charts = []
            self.chart_panel.set_specs([])
            return
        all_headers, all_rows = summary_rows(self._visible, judged)
        left_out = {"Mean", "Min", "Max", "Decision Metric"} | (set() if any(r.system for r in self._visible) else {"System"})
        keep = [i for i, h in enumerate(all_headers) if h not in left_out]  # the rest is in Calculation details and the report
        headers = [all_headers[i] for i in keep]
        status_column = next((i for i, h in enumerate(headers) if h in ("Result", "Acceptance Result")), None)
        precision = self._precision()
        self._marked, shown, tags = set(), [], []
        for i, row in enumerate(all_rows):
            values = [summary_number(row[k], all_headers[k], precision, self._visible[i].method) for k in keep]
            if self._needs_review(self._visible[i]):
                values[0] += WARNING_MARK
                self._marked.add(i)
            if status_column is not None:
                values[status_column] = self._visible[i].status
            shown.append(values)
            tags.append(values[status_column] if status_column is not None else "")
        aligns = ["w" if i == 0 or i == status_column or heading == "Review" else "e" for i, heading in enumerate(headers)]
        self.table.set_table(headers, shown, tags, aligns=aligns, stretch=0)
        self.table.select_row(0)

    def _precision(self) -> int:
        try:
            return max(2, min(8, int(self.precision_var.get())))
        except ValueError:
            return 2

    def selected_result(self):
        index = self.table.currentIndex()  # already moved when the row signal arrives; the selection model is not yet
        row = index.row() if index.isValid() else None
        return self._visible[row] if row is not None and row < len(self._visible) else None

    def _select_result(self, *_args) -> None:
        result = self.selected_result()
        self._charts = report_charts(result, titled=True) if result else []
        self._scaled = result is not None and result.method == "capability"
        self.chart_tools.setVisible(self._scaled)
        self._draw_chart()
        self.selected_var.set(item_label(result) if result else "")
        self._show_details(result)
        self._show_checks(result)

    def _table_click(self, row: int, column: int, x: int) -> None:
        if column == 0 and self._on_mark(row, x):
            self.table.select_row(row)
            self.result_tabs.setCurrentWidget(self.checks_page)

    def _table_hover(self, row: int, column: int, x: int) -> None:
        hot = column == 0 and self._on_mark(row, x)
        self.table.viewport().setCursor(QCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor))

    def _needs_review(self, result) -> bool:
        """Does a data check, or a guideline about the amount of data, ask for a look at this item? (The AIAG bands do not.)
        An item that could not be analysed is counted as that, not here; one that was analysed but has a Critical finding (an
        unusable Standard) is."""
        checks, guidelines = self._checks.get(result.label, ([], []))
        return needs_attention([*checks, *guidelines]) or (result.valid and any(check.status == CRITICAL for check in checks))

    def _on_mark(self, row: int, x: int) -> bool:
        """Is the pointer on the warning mark that ends the Test Item of this row?"""
        if row not in self._marked or row >= self.table.table_model.rowCount():
            return False
        metrics = self.table.fontMetrics()
        text = self.table.table_model.row_text(row)[0]
        start = 6 + metrics.horizontalAdvance(text.removesuffix(WARNING_MARK))  # the cell's left padding, then the name
        return start <= x <= 6 + metrics.horizontalAdvance(text) + 12

    def _show_details(self, result) -> None:
        """The figures of the item as tables: Process Capability in groups, Gage R&R as its ANOVA table, Variance Components
        and Gage Evaluation. An item that could not be analysed says why, as text."""
        shown = result.method if result is not None and result.valid else ""
        if not shown:
            self.details_stack.setCurrentWidget(self.session)
            self.session.set_text(session_text(result, self._precision()) if result else "")
            return
        if shown == "grr":
            self.details_stack.setCurrentWidget(self.grr_frame)
            self._fill_grr_details(result)
            return
        if shown == "attribute":
            self.details_stack.setCurrentWidget(self.grr_frame)
            self._fill_attribute_details(result)
            return
        self.details_stack.setCurrentWidget(self.details)
        self.details.clear()
        bold = QFont(self.details.font())
        bold.setBold(True)
        for group, rows in capability_details(result, self._precision()):
            advanced = group == "Advanced Details"
            parent = QTreeWidgetItem(self.details, [group])
            parent.setFont(0, bold)
            parent.setBackground(0, QBrush(QColor(self.palette_tokens.soft)))
            parent.setBackground(1, QBrush(QColor(self.palette_tokens.soft)))
            for metric, value in rows:
                child = QTreeWidgetItem(parent, [metric, value])
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            parent.setExpanded(self._advanced_open if advanced else True)
            if advanced:
                parent.setData(0, Qt.ItemDataRole.UserRole, "advanced")
        self.details.resizeColumnToContents(1)

    def _insert_tables(self, tables) -> None:
        """A title row, the column names in the columns they name, then the figures, for each table."""
        rows, tags = [], []
        blank = ("",) * (GRR_COLUMNS - 1)
        for table in tables:
            rows.append((table.title, *blank))
            tags.append("section")
            rows.append(tuple(table.headers) + ("",) * (GRR_COLUMNS - len(table.headers)))
            tags.append("head")
            for row in table.rows:
                rows.append(tuple(row) + ("",) * (GRR_COLUMNS - len(row)))
                tags.append("")
        self.grr_tree.table_model.set_table([""] * GRR_COLUMNS, rows, tags, ["w", *["e"] * (GRR_COLUMNS - 1)])
        self.grr_tree.fit_columns(stretch=0, max_width=260)

    def _fill_grr_details(self, result) -> None:
        self.ndc_var.set(detail_cell(result.metrics.get("ndc"), "int"))
        self.grr_headline.show()
        self.tables_note_var.set("")
        self._insert_tables(grr_details(result, self._precision(), self.all_columns_var.get()))

    def _fill_attribute_details(self, result) -> None:
        tables, notes = attribute_details(result, self._precision())
        self.grr_headline.hide()
        self._insert_tables(tables)
        self.tables_note_var.set("  ".join(notes))

    def _details_click(self, item, _column: int) -> None:
        """A group opens and closes by its name as well as by its arrow."""
        if item.childCount():
            item.setExpanded(not item.isExpanded())

    def _remember_advanced(self) -> None:
        for index in range(self.details.topLevelItemCount()):
            item = self.details.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == "advanced":
                self._advanced_open = item.isExpanded()

    def _show_checks(self, result) -> None:
        """Check | Result | Status. First what the checks found in the data (nothing is listed for a check that passed), then the
        guidelines: published figures to compare with. A guideline is OK or Review, never a verdict. The longer explanations are
        in About the method."""
        tree = self.checks_tree
        tree.clear()
        attribute = result is not None and result.method == "attribute"
        tree.setHeaderLabels(["Check", "Finding" if attribute else "Result", "Status"])
        if result is None:
            self.notes_link.hide()
            return
        checks, guidelines = self._checks.get(result.label, ([], []))
        if attribute:
            self._show_attribute_checks(checks)
            return
        issues, limitations = findings(checks)
        section = self._group_item("Data Checks")
        if not issues and not limitations:
            self._status_item(section, "All checks", "No data issues detected.", "OK")
        for check in (*issues, *limitations):
            self._check_row(section, check, False)
        if guidelines:
            section = self._group_item("Guidelines (reference only)")
            for check in guidelines:
                self._check_row(section, check, True)
        tree.expandAll()
        notes = self.evaluated is not None and (self.evaluated.record.validation.conditions or self._problems())
        self.notes_link.setVisible(bool(notes))

    def _show_attribute_checks(self, checks) -> None:
        """Check | Finding | Status for an Attribute Agreement item: Critical (cannot be calculated), Review (a statistic is limited)
        or Info (an optional design choice). The findings are everything there is to say, so there is no link to more notes."""
        section = self._group_item("Data Checks")
        if not checks:
            self._status_item(section, "All checks", "No data issues detected.", "OK")
        for check in checks:
            self._check_row(section, check, False, attribute=True)
        self.checks_tree.expandAll()
        self.notes_link.hide()

    def _group_item(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.checks_tree, [title])
        font = QFont(self.checks_tree.font())
        font.setBold(True)
        item.setFont(0, font)
        for column in range(3):
            item.setBackground(column, QBrush(QColor(self.palette_tokens.soft)))
        return item

    def _status_item(self, parent: QTreeWidgetItem, topic: str, finding: str, status: str) -> None:
        item = QTreeWidgetItem(parent, [topic, finding, status])
        p = self.palette_tokens
        ink = {"Critical": p.danger, "Issue": p.danger, "Review": p.warn}.get(status, p.muted)  # a guideline is never a verdict colour
        item.setForeground(2, QBrush(QColor(ink)))

    def _check_row(self, parent: QTreeWidgetItem, check, guideline: bool, attribute: bool = False) -> None:
        status = attribute_status_label(check) if attribute else status_label(check, guideline)
        self._status_item(parent, CHECK_TOPICS.get(check.topic, check.topic), check.short.removesuffix("."), status)

    def _draw_chart(self) -> None:
        selected = self.selected_result()
        note = agreement_chart_note(selected) if selected is not None and selected.method == "attribute" else ""
        self.chart_panel.set_specs(self._charts, x_scale=self.chart_scale_var.get() if self._scaled else None,
                                   note=note if not self._charts else "", muted=self.palette_tokens.muted)

    # ------------------------------------------------------------------ explanations
    def _config(self):
        if self.study is None:
            return None
        return combine_config(self.study.options, self.study.evaluation)

    def show_about(self) -> None:
        from ..statistics import AnalysisConfig
        from .method_dialog import MethodDialog

        config = self._config() or AnalysisConfig(method=self.method_var.get())
        result = self.selected_result()  # the values of the selected item end the guide
        MethodDialog(self._dialog_parent(), method_guide(config, result if result is not None and result.method == config.method else None)
                     ).present()

    # ------------------------------------------------------------------ report
    def _fill_items(self) -> None:
        self.item_list.clear()
        self.item_list.addItems([result.label for result in self.results])
        self._select_items(True)

    def _select_items(self, everything: bool) -> None:
        if everything:
            self.item_list.selectAll()
        else:
            self.item_list.clearSelection()
        self._update_coverage()

    def included(self) -> list[str]:
        return [item.text() for item in self.item_list.selectedItems()]

    def _update_coverage(self) -> None:
        total, chosen = self.item_list.count(), len(self.item_list.selectedItems())
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
        if self.study is not None and self.study.options.method == "attribute" and not attribute_reportable():
            self.report_var.set(ATTRIBUTE_REPORT_PENDING)
            return
        if self.stale:
            self.report_var.set("Update the results before generating a report.")
            return
        try:
            context, included = self._context()
        except Exception as exc:
            self.report_var.set(str(exc))
            return
        method_name = METHOD_NAMES[self.study.options.method]
        initial = f"{self.study.options.method}_report{suffix}"
        path, _ = QFileDialog.getSaveFileName(self._dialog_parent(), "Generate report", initial,
                                              "PDF report (*.pdf)" if suffix == ".pdf" else "Excel report (*.xlsx)")
        if not path:
            return
        results = self._report_results(included)
        decimals = self._precision()
        gage = self.gage_var.get().strip()
        title = (f"{gage}: {method_name}" if gage else method_name) + (" (partial report)" if context.partial else "")
        self.export_busy = True
        self.report_var.set("Generating the report…")
        self._refresh_state()

        def finished(destination):
            self.export_busy = False
            self.last_report = Path(destination)
            self.open_button.setEnabled(True)
            self.report_var.set(f"Saved: {destination}")
            self._refresh_state()

        def failed(exc):
            self.export_busy = False
            self.report_var.set("Report generation failed.")
            self._refresh_state()
            QMessageBox.critical(self._dialog_parent(), "Report export failed", str(exc))

        self.tasks.run(lambda _report: export_statistical_report(Path(path), results, decimals=decimals, title=title, context=context),
                       on_success=finished, on_error=failed)

    def open_report(self) -> None:
        if self.last_report is not None:
            open_path(self.last_report)

    def sizeHint(self) -> QSize:
        return QSize(1100, 640)

    def resizeEvent(self, event) -> None:
        """A wide window puts the table beside the charts, each with the full height; a narrower one puts the table above."""
        super().resizeEvent(event)
        wide = self.width() >= WIDE_RESULTS
        orientation = Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical
        if self.split.orientation() != orientation:
            self.split.setOrientation(orientation)
            self.split.setSizes([380, 700] if wide else [170, 440])
        self.selected_label.setVisible(wide and bool(self.selected_var.get()))


class ReadOnlyTextView(QWidget):
    """The text of an item that could not be analysed: why, in monospace."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .widgets import ReadOnlyText

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text = ReadOnlyText(monospace=True)
        layout.addWidget(self.text)

    def set_text(self, content: str) -> None:
        self.text.set_text(content)

    def toPlainText(self) -> str:
        return self.text.toPlainText()


__all__ = ["MappingSource", "QCheckBox", "QPushButton", "ValidationWorkspace", "build_mapping_dataset", "reorder_dataset", "repolish"]
