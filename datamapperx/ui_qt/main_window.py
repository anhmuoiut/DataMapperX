"""The Qt main window: Select, Review & Export, and a Validation & Reports preview.

What each list, table, chip and note says is decided in ``datamapperx.workflow``; scanning, exporting, statistics and
settings are the application's own modules. This file is only layout, signals and the busy state.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .._version import __version__
from ..config import APP_CREDIT, APP_TITLE, DEFAULT_OUTPUT_FILE
from ..exporter import generate_excel, summarize_limits
from ..models import ScanResult
from ..paths import resource_path
from ..profiles import load_profiles
from ..reporting import describe_empty_scan, summarize_scan
from ..review import ReviewSummary, summarize_review
from ..scanner import scan_folder
from ..settings import Settings, load_settings, save_settings
from ..utils import parse_positive_int
from ..workflow import (
    NO_ROW_CHOSEN_TEXT,
    SELECTED_EMPTY_TEXT,
    available_view,
    check_chips,
    limit_overview,
    limit_panel,
    limit_texts,
    move_items,
    preview_table,
    selected_info,
)
from ..workspace_data import MappingSource
from .analysis_page import AnalysisPage
from .tasks import TaskRunner
from .theme import apply_theme, resolve_mode
from .widgets import ActionTable, Card, ChipRow, DataTable, StepBar, make_button, repolish

logger = logging.getLogger(__name__)

STEPS = ("Select", "Review & Export", "Validation & Reports")
SCAN_WORKERS = 4  # files read in parallel: enough for slow drives, few enough to leave the UI thread its share of the GIL
SELECT, REVIEW, ANALYSIS = range(3)


def _label(text: str = "", role: str = "") -> QLabel:
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    return label


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, *, settings: Settings | None = None) -> None:
        super().__init__()
        self.app = app
        self.settings = settings or load_settings()
        self.profiles = load_profiles()
        self.palette_tokens = apply_theme(app, self.settings.theme)
        self.tasks = TaskRunner(self)

        self.scan_result: ScanResult | None = None
        self.limits: dict = {}
        self.selected: list[str] = []
        self._cancel = threading.Event()
        self._busy = False
        self._scan_serial = self._data_serial = 0
        self._scan_description = ""
        self._preview_page, self._review_row, self._preview_rows = 0, 0, []
        self._summary: ReviewSummary | None = None
        self._summary_key: tuple | None = None

        self.setWindowTitle(f"{APP_TITLE} (Qt preview)")
        self.setMinimumSize(1000, 680)
        self.resize(1180, 760)
        icon = resource_path("assets", "DataMapperX.png")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 6)
        root.setSpacing(8)
        root.addLayout(self._build_header())
        self.steps = StepBar(STEPS)
        self.steps.clicked.connect(self._on_step_clicked)
        root.addWidget(self.steps)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_select())
        self.pages.addWidget(self._build_review())
        self.analysis = AnalysisPage(self.palette_tokens, self.tasks)
        self.analysis.message.connect(self.set_status)
        self.pages.addWidget(self.analysis)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self._build_status_bar()
        self._bind_shortcuts()
        self._restore_inputs()
        self._refresh_lists()
        self._show_step(SELECT)

    # ================================================================== layout
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        titles.addWidget(title)
        titles.addWidget(_label("Collect measurements from test logs into one Excel workbook.", "muted"))
        row.addLayout(titles)
        row.addStretch(1)
        self.theme_button = make_button("", self._toggle_theme)
        row.addWidget(self.theme_button)
        self._update_theme_button()
        return row

    def _build_select(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_source(), 2)
        layout.addWidget(self._build_available(), 4)
        layout.addWidget(self._build_selected(), 3)
        return page

    def _build_source(self) -> Card:
        card = Card("Source")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.profile_box = QComboBox()
        self.profile_box.addItems(list(self.profiles))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder that holds the logs")
        self.expected_edit, self.repeats_edit = QLineEdit(), QLineEdit()
        for edit in (self.expected_edit, self.repeats_edit):
            edit.setMaximumWidth(70)
        grid.addWidget(_label("Profile", "muted"), 0, 0)
        grid.addWidget(self.profile_box, 0, 1, 1, 2)
        grid.addWidget(_label("Folder", "muted"), 1, 0)
        grid.addWidget(self.folder_edit, 1, 1)
        grid.addWidget(make_button("Browse…", self.pick_folder), 1, 2)
        grid.addWidget(_label("Samples", "muted"), 2, 0)
        counts = QHBoxLayout()
        counts.addWidget(self.expected_edit)
        counts.addWidget(_label("files each", "muted"))
        counts.addWidget(self.repeats_edit)
        counts.addStretch(1)
        grid.addLayout(counts, 2, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)

        buttons = QHBoxLayout()
        self.scan_button = make_button("Scan logs", self.scan_logs, primary=True)
        self.cancel_button = make_button("Cancel", self._cancel_scan)
        self.cancel_button.setVisible(False)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        card.body.addWidget(self.progress)

        tiles = QHBoxLayout()
        self.samples_value, self.files_value, self.components_value = (_label("–", "metric") for _ in range(3))
        for value, caption in ((self.samples_value, "Samples"), (self.files_value, "Files"), (self.components_value, "Components")):
            tile = QVBoxLayout()
            tile.setSpacing(0)
            tile.addWidget(value)
            tile.addWidget(_label(caption, "muted"))
            tiles.addLayout(tile)
        card.body.addLayout(tiles)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        card.body.addWidget(self.verdict)
        card.body.addStretch(1)
        card.body.addWidget(_label(f"{APP_TITLE} {__version__}  ·  {APP_CREDIT}", "muted"))
        return card

    def _build_available(self) -> Card:
        card = Card("Available components")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search components…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._refresh_available())
        self.available = ActionTable(self.palette_tokens, kind="add", name_heading="Component", value_headings=("Min", "Max"))
        self.available.action.connect(self._add_at)
        self.available.activated_rows.connect(lambda rows: self._add([self.available.items()[r] for r in rows]))
        self.available_info = _label("", "muted")
        buttons = QHBoxLayout()
        buttons.addWidget(self.available_info, 1)
        buttons.addWidget(make_button("Add selected →", lambda: self._add(
            [self.available.items()[r] for r in self.available.selected_rows()])))
        buttons.addWidget(make_button("Add all shown", lambda: self._add(self.available.items())))
        card.body.addWidget(self.search)
        card.body.addWidget(self.available, 1)
        card.body.addLayout(buttons)
        return card

    def _build_selected(self) -> Card:
        card = Card("Selected for export")
        self.selected_table = ActionTable(self.palette_tokens, kind="remove", name_heading="Component", numbered=True)
        self.selected_table.action.connect(self._remove_at)
        self.selected_table.delete_pressed.connect(self.remove_selected)
        self.selected_info = _label("", "muted")
        buttons = QHBoxLayout()
        buttons.addWidget(self.selected_info, 1)
        buttons.addWidget(make_button("↑", lambda: self.move_selected(-1)))
        buttons.addWidget(make_button("↓", lambda: self.move_selected(1)))
        buttons.addWidget(make_button("Clear", self.clear_selected))
        self.review_button = make_button("Review & Export →", lambda: self._show_step(REVIEW), primary=True)
        card.body.addWidget(self.selected_table, 1)
        card.body.addLayout(buttons)
        card.body.addWidget(self.review_button, 0, Qt.AlignmentFlag.AlignRight)
        return card

    def _build_review(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        split = QSplitter(Qt.Orientation.Horizontal)

        data = Card("Data preview")
        self.preview = DataTable(self.palette_tokens)
        self.preview.rowSelected.connect(self._on_preview_select)
        pager = QHBoxLayout()
        self.pager_prev, self.pager_next = make_button("‹", lambda: self._page_preview(-1)), make_button("›", lambda: self._page_preview(1))
        self.pager_label = _label("", "muted")
        self.preview_note = _label("", "muted")
        pager.addWidget(self.preview_note, 1)
        pager.addWidget(self.pager_prev)
        pager.addWidget(self.pager_label)
        pager.addWidget(self.pager_next)
        data.body.addWidget(self.preview, 1)
        data.body.addLayout(pager)

        limits = Card("Limits")
        self.limits_row = _label(NO_ROW_CHOSEN_TEXT, "muted")
        self.limits_row.setWordWrap(True)
        self.limits_table = DataTable(self.palette_tokens)
        limits.body.addWidget(self.limits_row)
        limits.body.addWidget(self.limits_table, 1)
        split.addWidget(data)
        split.addWidget(limits)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([560, 600])
        layout.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.chips = ChipRow()
        bottom.addWidget(self.chips, 1)
        bottom.addWidget(make_button("← Back", lambda: self._show_step(SELECT)))
        self.export_button = make_button("Export Excel…", self.export_excel, primary=True)
        bottom.addWidget(self.export_button)
        bottom.addWidget(make_button("Validation & Reports →", lambda: self._show_step(ANALYSIS)))
        layout.addLayout(bottom)
        return page

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_label = QLabel("Ready. Choose a profile and a folder, then scan.")
        self.status_label.setContentsMargins(8, 0, 0, 0)
        bar.addWidget(self.status_label, 1)

    def _bind_shortcuts(self) -> None:
        for keys, slot in (("Ctrl+O", self.pick_folder), ("Ctrl+Return", self.scan_logs), ("F5", self.scan_logs),
                           ("Esc", self._cancel_scan), ("Ctrl+E", self._export_shortcut)):
            QShortcut(QKeySequence(keys), self, activated=slot)

    # ================================================================== state and settings
    def _restore_inputs(self) -> None:
        s = self.settings
        if s.last_profile in self.profiles:
            self.profile_box.setCurrentText(s.last_profile)
        self.folder_edit.setText(s.last_folder)
        self.expected_edit.setText(s.expected_samples)
        self.repeats_edit.setText(s.repeats)

    def _remember_inputs(self) -> None:
        s = self.settings
        s.last_profile, s.last_folder = self.profile_box.currentText(), self.folder_edit.text().strip()
        s.expected_samples, s.repeats = self.expected_edit.text().strip(), self.repeats_edit.text().strip()
        save_settings(s)

    def closeEvent(self, event) -> None:
        self._cancel.set()
        self._remember_inputs()
        super().closeEvent(event)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _optional_int(self, edit: QLineEdit) -> int | None:
        try:
            return parse_positive_int(edit.text(), "value")
        except ValueError:
            return None

    def _read_counts(self) -> tuple[int, int] | None:
        try:
            return (parse_positive_int(self.expected_edit.text(), "Expected samples"),
                    parse_positive_int(self.repeats_edit.text(), "Files per sample"))
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return None

    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self._busy = busy
        self.scan_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy and cancellable)
        self.export_button.setEnabled(not busy)
        self.review_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)  # indeterminate until the first progress report

    # ================================================================== theme
    def _update_theme_button(self) -> None:
        self.theme_button.setText("Light mode" if self.palette_tokens.mode == "dark" else "Dark mode")

    def _toggle_theme(self) -> None:
        self.settings.theme = "light" if self.palette_tokens.mode == "dark" else "dark"
        self.palette_tokens = apply_theme(self.app, resolve_mode(self.settings.theme))
        for table in (self.available, self.selected_table, self.preview, self.limits_table):
            table.set_palette(self.palette_tokens)
        self.analysis.set_palette(self.palette_tokens)
        self._update_theme_button()
        save_settings(self.settings)

    # ================================================================== steps
    def _review_ready(self) -> bool:
        return bool(self.scan_result and self.scan_result.grouped and self.selected)

    def _on_step_clicked(self, index: int) -> None:
        if not self._busy:
            self._show_step(index)

    def _show_step(self, step: int) -> None:
        if step != SELECT and not self._review_ready():
            step = SELECT
        self.pages.setCurrentIndex(step)
        if step == REVIEW:
            self._refresh_review()
        elif step == ANALYSIS:
            self.analysis.set_source(self._mapping_source())
        self.steps.set_state(step, [True, self._review_ready(), self._review_ready()])

    def _export_shortcut(self) -> None:
        if self.pages.currentIndex() == REVIEW:
            self.export_excel()
        else:
            self._show_step(REVIEW)

    def _mapping_source(self) -> MappingSource | None:
        result = self.scan_result
        if result is None or not result.grouped or not self.selected:
            return None
        return MappingSource(result.grouped, tuple(self.selected), self._optional_int(self.repeats_edit),
                             self._data_serial, self._scan_description, self._scan_serial)

    # ================================================================== scanning
    def pick_folder(self) -> None:
        start = self.folder_edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder that holds the logs", start if Path(start).is_dir() else "")
        if folder:
            self.folder_edit.setText(folder)

    def _cancel_scan(self) -> None:
        if self._busy:
            self._cancel.set()
            self.set_status("Cancelling…")

    def scan_logs(self) -> None:
        if self._busy:
            return
        text = self.folder_edit.text().strip()
        if not text:
            QMessageBox.warning(self, APP_TITLE, "Please choose a folder first.")
            return
        folder = Path(text)
        if not folder.is_dir():
            QMessageBox.critical(self, APP_TITLE, f"Folder path is not valid:\n{text}")
            return
        counts = self._read_counts()
        profile_name = self.profile_box.currentText()
        if counts is None or profile_name not in self.profiles:
            return
        expected, repeats = counts
        profile = dict(self.profiles[profile_name])  # a snapshot: later edits must not change this scan
        self._remember_inputs()
        self._cancel.clear()
        self._show_step(SELECT)
        self._set_busy(True, cancellable=True)
        self.set_status("Looking for log files…")
        self.tasks.run(
            lambda report: scan_folder(folder, profile, self._cancel, progress=report, max_workers=SCAN_WORKERS),
            on_progress=self._on_scan_progress,
            on_success=lambda result: self._on_scan_done(result, folder, profile_name, profile, expected, repeats),
            on_error=self._on_scan_error,
        )

    def _on_scan_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.set_status(f"Scanning {done:,} of {total:,} files…")

    def _on_scan_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.set_status("Scan failed.")
        QMessageBox.critical(self, APP_TITLE, str(exc))

    def _on_scan_done(self, result: ScanResult, folder: Path, profile_name: str, profile: dict, expected: int, repeats: int) -> None:
        self._set_busy(False)
        self.scan_result = result
        self._scan_serial += 1
        self._data_serial += 1
        self._scan_description = f"Data Mapping scan of {folder} (profile {profile_name})"
        self.limits = summarize_limits(result.grouped, result.components)
        self._summary_key, self._review_row, self._preview_page = None, 0, 0
        remembered = self.selected or self.settings.component_sets.get(profile_name, [])
        known = set(result.components)
        self.selected = [c for c in remembered if c in known]

        self.samples_value.setText(f"{result.total_sns} / {expected}")
        self.files_value.setText(f"{result.total_files:,}")
        self.components_value.setText(f"{len(result.components):,}")
        self._refresh_lists()
        if not result.grouped:
            self._set_verdict("bad", "No usable data found. " + describe_empty_scan(folder, profile_name, profile, result).splitlines()[0])
            self.set_status("Scan finished: nothing usable found.")
        else:
            summary = summarize_scan(result, expected, repeats)
            self._set_verdict(summary.level, summary.headline + (": " + " ".join(summary.issues[:2]) if summary.issues else ""))
            self.set_status(f"Scan complete: {result.total_sns} samples, {result.total_files} files, {len(result.components)} components.")
        self._show_step(SELECT)

    def _set_verdict(self, level: str, text: str) -> None:
        self.verdict.setText(text)
        self.verdict.setProperty("chip", {"ok": "ok", "warn": "warn", "bad": "bad"}.get(level, "info"))
        repolish(self.verdict)

    # ================================================================== component lists
    def _refresh_available(self) -> None:
        components = self.scan_result.components if self.scan_result else []
        view = available_view(components, self.selected, self.search.text())
        self.available.set_items(view.items, values=[limit_texts(self.limits, c) for c in view.items], empty_text=view.empty_text)
        self.available_info.setText(view.info)

    def _refresh_selected(self) -> None:
        self.selected_table.set_items(self.selected, empty_text=SELECTED_EMPTY_TEXT)
        self.selected_info.setText(selected_info(len(self.selected)))

    def _refresh_lists(self) -> None:
        self._refresh_available()
        self._refresh_selected()
        self.steps.set_state(self.pages.currentIndex(), [True, self._review_ready(), self._review_ready()])

    def _selection_changed(self) -> None:
        profile = self.profile_box.currentText()
        if profile:
            self.settings.component_sets[profile] = list(self.selected)
        self._data_serial += 1
        self._refresh_lists()
        if self.pages.currentIndex() == REVIEW:
            self._refresh_review()

    def _add(self, names: list[str]) -> None:
        if self._busy:
            return
        added = [n for n in dict.fromkeys(names) if n not in self.selected]  # each name once, in the order given
        if added:
            self.selected.extend(added)
            self._selection_changed()

    def _add_at(self, row: int) -> None:
        items = self.available.items()
        if 0 <= row < len(items):
            self._add([items[row]])

    def _remove_at(self, row: int) -> None:
        if not self._busy and 0 <= row < len(self.selected):
            del self.selected[row]
            self._selection_changed()

    def remove_selected(self) -> None:
        rows = self.selected_table.selected_rows()
        for row in reversed(rows):
            del self.selected[row]
        if rows:
            self._selection_changed()

    def clear_selected(self) -> None:
        if self.selected and not self._busy:
            self.selected = []
            self._selection_changed()

    def move_selected(self, direction: int) -> None:
        rows = self.selected_table.selected_rows()
        if not self._busy and move_items(self.selected, rows, direction):
            self._selection_changed()
            self.selected_table.select_rows([r + direction for r in rows])

    # ================================================================== review (step 2)
    def _refresh_review(self) -> None:
        result, components = self.scan_result, list(self.selected)
        table = preview_table(result, components, self._preview_page, self._optional_int(self.repeats_edit))
        self._preview_page, self._preview_rows = table.page, table.export_rows
        self.preview.set_table(table.headings, table.rows, table.tags, aligns=["center", "w", "w", *["e"] * len(table.page_components)],
                               empty_text=table.empty_text)
        self.preview_note.setText(table.note)
        last = table.first + len(table.page_components)
        self.pager_label.setText(f"Columns {table.first + 1}–{last} of {len(components)}" if components else "")
        self.pager_prev.setEnabled(table.page > 0)
        self.pager_next.setEnabled(table.page < table.pages - 1)
        self.pager_label.setVisible(table.pages > 1)
        self.pager_prev.setVisible(table.pages > 1)
        self.pager_next.setVisible(table.pages > 1)
        if self._preview_rows:
            self._review_row = max(0, min(self._review_row, len(self._preview_rows) - 1))
            self.preview.select_row(self._review_row, notify=False)
        self._refresh_limits()
        self._refresh_checks()

    def _page_preview(self, step: int) -> None:
        self._preview_page = max(0, self._preview_page + step)
        self._refresh_review()

    def _on_preview_select(self, row: int) -> None:
        if row >= 0 and row != self._review_row:
            self._review_row = row
            self._refresh_limits()

    def _refresh_limits(self) -> None:
        components = self.selected
        headings, aligns = ["Component", "Value", "Min", "Max", "Unit"], ["w", "e", "e", "e", "w"]
        if not 0 <= self._review_row < len(self._preview_rows):
            self.limits_row.setText(NO_ROW_CHOSEN_TEXT)
            self.limits_table.set_table(headings, limit_overview(components, self.limits), aligns=aligns, stretch=0, max_width=260)
            return
        row = self._preview_rows[self._review_row]
        self.limits_row.setText(f"Row {row.index}   ·   {row.sn}   ·   {row.filename}")
        rows, tags = limit_panel(row, components, self.limits)
        self.limits_table.set_table(headings, rows, tags, aligns=aligns, stretch=0, max_width=260)

    def _review_summary(self) -> ReviewSummary | None:
        result = self.scan_result
        if result is None or not result.grouped or not self.selected:
            return None
        key = (id(result), tuple(self.selected))
        if key != self._summary_key:
            self._summary, self._summary_key = summarize_review(result.grouped, self.selected, self.limits), key
        return self._summary

    def _refresh_checks(self) -> None:
        result, summary = self.scan_result, self._review_summary()
        if result is None or summary is None:
            self.chips.set_chips([])
            return
        expected, repeats = self._optional_int(self.expected_edit), self._optional_int(self.repeats_edit)
        wrong = result.sns_with_wrong_repeat_count(repeats) if repeats is not None else []
        self.chips.set_chips(check_chips(result, summary, expected=expected, repeats=repeats, wrong=wrong))

    # ================================================================== export
    def export_excel(self) -> None:
        result = self.scan_result
        if self._busy or result is None or not result.grouped or not self.selected:
            QMessageBox.warning(self, APP_TITLE, "Scan a folder and select at least one component first.")
            return
        counts = self._read_counts()
        if counts is None:
            return
        expected, repeats = counts
        if result.total_sns != expected and QMessageBox.question(
                self, APP_TITLE, f"Expected {expected} samples, but found {result.total_sns}.\n\nDo you still want to export?"
        ) != QMessageBox.StandardButton.Yes:
            return
        wrong = result.sns_with_wrong_repeat_count(repeats)
        if wrong:
            QMessageBox.critical(self, APP_TITLE, f"Some samples do not have exactly {repeats} files:\n\n" + "\n".join(wrong[:20]))
            return
        start = self.settings.last_export_dir
        initial = str(Path(start) / DEFAULT_OUTPUT_FILE) if start and Path(start).is_dir() else DEFAULT_OUTPUT_FILE
        output, _ = QFileDialog.getSaveFileName(self, "Save the Excel file", initial, "Excel workbook (*.xlsx)")
        if not output:
            return
        path, grouped, components = Path(output), dict(result.grouped), list(self.selected)
        self._set_busy(True)
        self.set_status("Creating the Excel file…")
        self.tasks.run(
            lambda _report: generate_excel(grouped, components, path, repeats),
            on_success=lambda _result: self._on_export_done(path),
            on_error=self._on_export_error,
        )

    def _on_export_done(self, path: Path) -> None:
        self._set_busy(False)
        self.settings.last_export_dir = str(path.parent)
        self.set_status(f"Saved: {path}")

    def _on_export_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.set_status("Export failed.")
        QMessageBox.critical(self, APP_TITLE, str(exc))


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow(app)
    window.show()
    return app.exec()
