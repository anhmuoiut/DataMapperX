"""The main DataMapperX window: Data Mapping (Select, then Review & Export) and, beside it, Validation & Reports.

What each list, table, chip and note says is decided in ``datamapperx.workflow``; scanning, exporting, statistics and
settings are the application's own modules. This file is layout, signals, the busy state, and the checks that run behind
the window (the owner's off switch and the update check). The Review page and the Validation page are built when they are
first needed, or a moment after the window is on screen, so the first paint pays only for the page it shows.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .._version import __version__
from ..config import APP_CREDIT, APP_TITLE, DEFAULT_OUTPUT_FILE
from ..exporter import ExportRow, summarize_limits
from ..models import ScanResult
from ..paths import is_frozen, log_path, resource_path, user_data_dir
from ..profiles import get_profile_extensions, load_profiles
from ..reporting import describe_empty_scan, full_report, summarize_scan
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
from .dialogs import AboutDialog, ExportDoneDialog, GrrCriteriaDialog, ReportDialog, label, open_path
from .duplicate_dialog import DuplicateDialog
from .tasks import TaskRunner
from .theme import apply_theme, resolve_mode
from .widgets import ActionTable, Card, ChipRow, DataTable, StepBar, make_button, repolish

if TYPE_CHECKING:
    from .. import updater
    from ..grr import GrrResult
    from .access_dialog import AccessDialog

logger = logging.getLogger(__name__)

BIG_REVIEW_CELLS = 20_000  # components x files from which the checks of the Review run in the background (1,200 x 120 took 2.5 s)
SCAN_WORKERS = 4  # files read in parallel: enough for slow drives, few enough to leave the UI thread its share of the GIL
ENFORCE_ACCESS_ENV = "DATAMAPPERX_ENFORCE_ACCESS"  # set it to run the owner's off switch from a source checkout too
SHORTCUTS = (
    ("Ctrl+O", "Choose the source folder"),
    ("Ctrl+Enter  /  F5", "Scan logs"),
    ("Esc", "Cancel a running scan"),
    ("Ctrl+E", "Go to Review & Export, then export to Excel"),
    ("Double-click / Enter", "Add or remove the highlighted component"),
    ("Ctrl+A", "Select every component in a list"),
    ("Delete", "Remove the highlighted selected components"),
)
VERDICT_CHIPS = {"ok": "ok", "warn": "warn", "bad": "bad"}


def parse_geometry(text: str) -> tuple[int, int, int, int] | None:
    """``"1200x800+40+30"`` (width, height, left, top), the form the window has always saved its place in."""
    match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", text or "")
    return tuple(int(value) for value in match.groups()) if match else None  # type: ignore[return-value]


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, *, settings: Settings | None = None, background_checks: bool = True) -> None:
        """``background_checks=False`` keeps the window off the network (tests and the build's self-test)."""
        super().__init__()
        self.app = app
        self.settings = settings or load_settings()
        self.profiles = load_profiles()
        self.palette_tokens = apply_theme(app, self.settings.theme)
        self.tasks = TaskRunner(self)

        self.scan_result: ScanResult | None = None
        self.limits: dict[str, dict[str, str]] = {}  # min / max / unit of every scanned component, as in the Excel file
        self.selected_components: list[str] = []
        self.reviewed_duplicates: set[str] = set()
        self.is_busy = False
        self.step = "select"  # "select" or "review"
        self.workspace = "mapping"  # "mapping" (the two steps) or "validation"
        self.validation = None  # built the first time it is opened
        self.access_dialog: AccessDialog | None = None
        self._cancel = threading.Event()
        self._data_serial = 0  # moves whenever the scanned data (or the choice among duplicates) changes
        self._scan_serial = 0  # moves with every new scan (or reset), never for a duplicate choice
        self._scan_description = ""
        self._review_row = 0  # the preview row whose values the limits panel shows
        self._preview_page = 0
        self._preview_rows: list[ExportRow] = []
        self._preview_components: tuple[str, ...] = ()
        self._summary: ReviewSummary | None = None
        self._summary_key: tuple | None = None
        self._grr_results: list[GrrResult] = []
        self._grr_key: tuple | None = None
        self._pending: dict[str, tuple] = {}  # what the background is working out for the Review, and for which data
        self.grr_criteria = None  # read with the review page, which is the only place that uses it
        self._update_info: updater.UpdateInfo | None = None
        self._pages: dict[str, QWidget] = {}
        self._busy_widgets: list[QWidget] = []
        # The owner's off switch applies to the program people were given, not to a developer's source checkout.
        self._enforce_access = background_checks and (is_frozen() or bool(os.environ.get(ENFORCE_ACCESS_ENV)))

        self.setWindowTitle(APP_TITLE)
        icon = resource_path("assets", "DataMapperX.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 8, 18, 0)
        root.setSpacing(6)
        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())
        root.addLayout(self._build_nav())
        self.content = QStackedWidget()
        root.addWidget(self.content, 1)
        self.setCentralWidget(central)
        self._build_status_bar()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_review)
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.timeout.connect(self._recheck_access)

        self._ensure_page("select")
        self._bind_shortcuts()
        self._restore_inputs()
        self._setup_geometry()
        self._update_profile_hint()
        self._refresh_lists()
        self._update_switch()
        self.search.textChanged.connect(lambda _text: self._refresh_available(reset_view=True))
        self.repeats_edit.textChanged.connect(lambda _text: (self._schedule_preview(), self._notify_validation()))

        if self._enforce_access:
            from .. import access

            now = time.time()
            access.begin(self.settings, now)
            block = access.current_block(self.settings, now)
            if block:  # a copy that was told to stop stays stopped, even before the network answers
                QTimer.singleShot(150, lambda: self._apply_access(block))
        if background_checks:
            QTimer.singleShot(1500, self._start_checks)
        QTimer.singleShot(5000, self._cleanup_update_leftovers)

    @staticmethod
    def _cleanup_update_leftovers() -> None:
        from .. import updater

        updater.cleanup_update_leftovers()

    # ================================================================== window basics
    def _setup_geometry(self) -> None:
        restored = parse_geometry(self.settings.geometry)
        probe = QPoint(restored[2] + 80, restored[3] + 40) if restored else None
        screen = (QGuiApplication.screenAt(probe) if probe else None) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        max_width, max_height = max(1, area.width() - 24), max(1, area.height() - 48)
        min_width, min_height = min(1000, max_width), min(680, max_height)
        self.setMinimumSize(min_width, min_height)
        if restored:
            width, height, x, y = restored
        else:
            width = min(1360, max(1000, int(area.width() * 0.88)))
            height = min(880, max(680, int(area.height() * 0.86)))
            x, y = area.left() + (area.width() - width) // 2, area.top() + 16
        width = max(min_width, min(width, max_width))
        height = max(min_height, min(height, max_height))
        x = max(area.left() + 8, min(x, area.right() - width - 16))
        y = max(area.top() + 8, min(y, area.bottom() - height - 40))
        self.resize(width, height)
        self.move(x, y)

    def geometry_text(self) -> str:
        return f"{self.width()}x{self.height()}+{self.x()}+{self.y()}"

    def closeEvent(self, event) -> None:
        # A scan still running would keep the (windowless) process alive until it finished reading every file.
        self._cancel.set()
        self._remember_inputs()
        self.settings.geometry = self.geometry_text()
        save_settings(self.settings)
        self.tasks.close()  # no worker may deliver into a window that is going away
        if self.validation is not None:
            self.validation.tasks.close()
        super().closeEvent(event)

    def exit_app(self) -> None:
        self.close()

    def _remember_inputs(self) -> None:
        s = self.settings
        s.last_folder = self.folder_edit.text().strip()
        s.last_profile = self.profile_box.currentText()
        s.expected_samples = self.expected_edit.text().strip() or s.expected_samples
        s.repeats = self.repeats_edit.text().strip() or s.repeats

    def _restore_inputs(self) -> None:
        s = self.settings
        if s.last_profile in self.profiles:
            self.profile_box.setCurrentText(s.last_profile)
        self.folder_edit.setText(s.last_folder)
        self.expected_edit.setText(s.expected_samples)
        self.repeats_edit.setText(s.repeats)

    def _bind_shortcuts(self) -> None:
        for keys, slot in (("Ctrl+O", lambda: self._in_mapping(self.pick_folder)),
                           ("Ctrl+Return", lambda: self._in_mapping(self.scan_logs)),
                           ("F5", lambda: self._in_mapping(self.scan_logs)),
                           ("Ctrl+E", self._export_shortcut),
                           ("Esc", lambda: self._cancel_scan() if self.is_busy else None)):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _export_shortcut(self) -> None:
        """Ctrl+E: from the first step go and review; from the review step export."""
        if self.is_busy:
            return
        self._in_mapping(lambda: self.export_excel() if self.step == "review" else self._show_step("review"))

    def _in_mapping(self, action: Callable[[], None]) -> None:
        """Shortcuts that belong to Data Mapping bring it back first, so nothing happens out of sight."""
        if self.workspace != "mapping":
            self._show_workspace("mapping")
        action()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    # ================================================================== layout
    def _build_header(self) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 4, 2, 0)
        left = QHBoxLayout()
        left.setSpacing(12)
        icon = resource_path("assets", "DataMapperX.png")
        if icon.exists():
            pixmap = QPixmap(str(icon))
            if not pixmap.isNull():
                mark = QLabel()
                mark.setPixmap(pixmap.scaledToHeight(32, Qt.TransformationMode.SmoothTransformation))
                left.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        titles.addWidget(title)
        titles.addWidget(label("TE - Solar Edge", "muted"))
        left.addLayout(titles)
        left.addStretch(1)
        row.addLayout(left, 1)
        self.brand_logo = QLabel()
        self._brand: dict[str, QPixmap] = {}
        for mode in ("light", "dark"):
            path = resource_path("assets", f"Jabil-Logo-{mode}-76.png")
            if path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    pixmap.setDevicePixelRatio(2.0)  # shipped at twice the size it shows, so a scaled screen stays sharp
                    self._brand[mode] = pixmap
        row.addWidget(self.brand_logo, 0, Qt.AlignmentFlag.AlignCenter)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        self.theme_button = make_button("", self._toggle_theme)
        self.theme_button.setProperty("glyphs", True)  # its sun and moon are not in the interface font
        right.addWidget(self.theme_button)
        self.help_button = QToolButton()
        self.help_button.setText("Help")
        self.help_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.help_button.setMenu(self._build_help_menu())
        right.addWidget(self.help_button)
        row.addLayout(right, 1)
        self._update_theme_button()
        self._update_brand_logo()
        return header

    def _build_help_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Check for updates…", lambda: self._check_for_update(manual=True))
        self.auto_update_action = QAction("Tell me about new versions", menu, checkable=True)
        self.auto_update_action.setChecked(self.settings.check_updates)
        self.auto_update_action.toggled.connect(self._auto_update_toggled)
        menu.addAction(self.auto_update_action)
        menu.addSeparator()
        menu.addAction("Keyboard shortcuts", self._show_shortcuts)
        menu.addAction("Open data folder", lambda: open_path(user_data_dir()))
        menu.addAction("Open log file", lambda: open_path(log_path()))
        menu.addSeparator()
        menu.addAction(f"About {APP_TITLE}", self._show_about)
        return menu

    def _show_about(self) -> None:
        AboutDialog(self).present()

    def _auto_update_toggled(self, checked: bool) -> None:
        self.settings.check_updates = bool(checked)
        save_settings(self.settings)

    def _update_brand_logo(self) -> None:
        pixmap = self._brand.get(self.palette_tokens.mode)
        self.brand_logo.setVisible(pixmap is not None)
        if pixmap is not None:
            self.brand_logo.setPixmap(pixmap)

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(16, 8, 12, 8)
        self.banner_label = QLabel()
        row.addWidget(self.banner_label, 1)
        row.addWidget(make_button("Update now", self._open_update_dialog, primary=True))
        row.addWidget(make_button("Skip this version", lambda: self.skip_update(self._update_info.version if self._update_info else "")))
        close = make_button("×", self.hide_update_banner)
        close.setFixedWidth(34)
        row.addWidget(close)
        self.banner.hide()
        return self.banner

    def _build_nav(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setSpacing(14)
        self.mapping_switch = make_button("Data Mapping", lambda: self._show_workspace("mapping"))
        self.validation_switch = make_button("Validation & Reports", lambda: self._show_workspace("validation"))
        nav.addWidget(self.mapping_switch)
        nav.addWidget(self.validation_switch)
        self.step_bar = StepBar(("Select", "Review & Export"), self.palette_tokens)
        self.step_bar.clicked.connect(self._on_step_clicked)
        nav.addWidget(self.step_bar, 1)
        return nav

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)
        self.status_label = QLabel("Ready. Choose a profile and a folder, then scan.")
        self.status_label.setContentsMargins(10, 0, 0, 0)
        self.status_label.setProperty("role", "muted")
        bar.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bar.addPermanentWidget(self.progress)

    # ------------------------------------------------------------------ pages (built when first shown)
    def _ensure_page(self, name: str) -> QWidget:
        page = self._pages.get(name)
        if page is None:
            page = {"select": self._build_select, "review": self._build_review, "validation": self._build_validation}[name]()
            self._pages[name] = page
            self.content.addWidget(page)
        return page

    def warm_up(self) -> None:
        """Build the other pages while the user reads the first one, so that going there later is instant."""
        QTimer.singleShot(0, lambda: self._ensure_page("review"))
        QTimer.singleShot(120, lambda: self._ensure_page("validation"))

    def _build_select(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(12)
        layout.addWidget(self._build_source(), 2)
        layout.addWidget(self._build_available(), 4)
        layout.addWidget(self._build_selected(), 3)
        self._busy_widgets += [self.manage_button, self.browse_button, self.scan_button, self.reset_button, self.expected_edit,
                               self.repeats_edit, self.folder_edit, self.search, self.profile_box]
        return page

    def _build_source(self) -> Card:
        card = Card("01  Source")
        head = QHBoxLayout()
        head.addWidget(label("Log profile"), 1)
        self.manage_button = make_button("Manage…", self.manage_profiles)
        head.addWidget(self.manage_button)
        card.body.addLayout(head)
        self.profile_box = QComboBox()
        self.profile_box.addItems(list(self.profiles))
        self.profile_box.activated.connect(lambda _index: self._on_profile_changed())
        card.body.addWidget(self.profile_box)
        self.hint_label = label("", "muted", wrap=True)
        card.body.addWidget(self.hint_label)
        card.body.addWidget(label("Source folder"))
        folder = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder that holds the logs")
        self.folder_edit.returnPressed.connect(self.scan_logs)
        self.browse_button = make_button("Browse…", self.pick_folder)
        folder.addWidget(self.folder_edit, 1)
        folder.addWidget(self.browse_button)
        card.body.addLayout(folder)
        counts = QGridLayout()
        counts.setHorizontalSpacing(8)
        self.expected_edit, self.repeats_edit = QLineEdit(), QLineEdit()
        counts.addWidget(label("Expected samples", "muted"), 0, 0)
        counts.addWidget(label("Files per sample", "muted"), 0, 1)
        counts.addWidget(self.expected_edit, 1, 0)
        counts.addWidget(self.repeats_edit, 1, 1)
        card.body.addLayout(counts)

        self.scan_button = make_button("Scan logs", self.scan_logs, primary=True)
        self.cancel_button = make_button("Cancel", self._cancel_scan)
        self.cancel_button.setEnabled(False)
        self.reset_button = make_button("Reset", self.reset_workflow)
        card.body.addWidget(self.scan_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button, 1)
        buttons.addWidget(self.reset_button, 1)
        card.body.addLayout(buttons)

        tiles = QHBoxLayout()
        self.samples_value, self.files_value, self.components_value = (label("–", "metric") for _ in range(3))
        for value, caption in ((self.samples_value, "Samples"), (self.files_value, "Files"), (self.components_value, "Fields")):
            tile = QVBoxLayout()
            tile.setSpacing(0)
            tile.addWidget(value)
            tile.addWidget(label(caption, "muted"))
            tiles.addLayout(tile)
        card.body.addLayout(tiles)
        self.verdict = label("No scan yet.", "muted", wrap=True)
        card.body.addWidget(self.verdict)
        self.details_button = make_button("View scan details", self._show_scan_details)
        self.details_button.setEnabled(False)
        card.body.addWidget(self.details_button)
        card.body.addStretch(1)
        self.version_label = label(f"Version {__version__}  ·  {APP_CREDIT}", "muted")
        card.body.addWidget(self.version_label)
        return card

    def _build_available(self) -> Card:
        card = Card("02  Available components")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search components…")
        self.search.setClearButtonEnabled(True)
        self.available_list = ActionTable(self.palette_tokens, kind="add", name_heading="Component", value_headings=("Min", "Max"))
        self.available_list.action.connect(self._add_at)
        self.available_list.activated_rows.connect(lambda _rows: self.add_components())
        self.available_list.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        self.available_info = label("", "muted")
        self.add_all_button = make_button("Add all shown", self.add_all_shown)
        self.add_button = make_button("Add →", self.add_components)
        card.body.addWidget(self.search)
        card.body.addWidget(self.available_list, 1)
        card.body.addWidget(self.available_info)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_all_button, 1)
        buttons.addWidget(self.add_button, 1)
        card.body.addLayout(buttons)
        return card

    def _build_selected(self) -> Card:
        card = Card("Selected for export")
        card.body.addWidget(label("Top to bottom = Excel column order", "muted"))
        self.selected_list = ActionTable(self.palette_tokens, kind="remove", name_heading="Component", numbered=True)
        self.selected_list.action.connect(self._remove_at)
        self.selected_list.activated_rows.connect(lambda _rows: self.remove_components())
        self.selected_list.delete_pressed.connect(self.remove_components)
        self.selected_list.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        self.selected_info = label("", "muted")
        self.move_up_button = make_button("↑", lambda: self.move_selected(-1))
        self.move_down_button = make_button("↓", lambda: self.move_selected(1))
        for button in (self.move_up_button, self.move_down_button):
            button.setFixedWidth(40)
        self.clear_button = make_button("Clear", self.clear_selected)
        self.review_button = make_button("Review & Export  →", lambda: self._show_step("review"), primary=True)
        card.body.addWidget(self.selected_list, 1)
        card.body.addWidget(self.selected_info)
        buttons = QHBoxLayout()
        buttons.addWidget(self.move_up_button)
        buttons.addWidget(self.move_down_button)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_button)
        card.body.addLayout(buttons)
        card.body.addWidget(self.review_button)
        return card

    def _build_review(self) -> QWidget:
        """Step 2: the data as it will be exported, the limits beside it, and the checks with the Export button."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 6)
        outer.setSpacing(8)
        columns = QHBoxLayout()
        columns.setSpacing(12)

        card = Card()
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("Review your data", "heading"))
        self.review_count = label("", "muted")
        toolbar.addWidget(self.review_count, 1)
        self.pager_prev = make_button("‹", lambda: self._page_preview(-1))
        self.pager_next = make_button("›", lambda: self._page_preview(1))
        for button in (self.pager_prev, self.pager_next):
            button.setFixedWidth(36)
        self.pager_label = label("", "muted")
        self.pager = [self.pager_prev, self.pager_label, self.pager_next]
        for widget in self.pager:
            toolbar.addWidget(widget)
            widget.setVisible(False)
        card.body.addLayout(toolbar)
        card.body.addWidget(label("Same rows and column order as your Excel file. Click a row to compare its values with the limits.",
                                  "muted", wrap=True))
        legend = QHBoxLayout()
        for kind, text in (("warn", "A value is missing"), ("bad", "Sample has the wrong number of files")):
            chip = QLabel(text)
            chip.setProperty("chip", kind)
            legend.addWidget(chip)
        legend.addStretch(1)
        card.body.addLayout(legend)
        self.preview_grid = DataTable(self.palette_tokens)
        self.preview_grid.rowSelected.connect(self._on_preview_select)
        self.preview_grid.activated.connect(lambda _row: self.side_tabs.setCurrentWidget(self.limits_page))
        card.body.addWidget(self.preview_grid, 1)
        self.preview_info = label("", "muted", wrap=True)
        card.body.addWidget(self.preview_info)
        columns.addWidget(card, 3)

        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.grr_page = self._build_grr_review()
        self.side_tabs.addTab(self.grr_page, "GRR pre-check")
        self.limits_page = Card()
        self.limits_title = label("Limits", "heading")
        self.limits_page.body.addWidget(self.limits_title)
        self.review_row_label = label(NO_ROW_CHOSEN_TEXT, "pick", wrap=True)
        self.limits_page.body.addWidget(self.review_row_label)
        self.limits_grid = DataTable(self.palette_tokens)
        self.limits_page.body.addWidget(self.limits_grid, 1)
        self.limits_page.body.addWidget(label("▲ above max   ▼ below min   – nothing there. Min, max and unit are the limits the "
                                              "Excel file lists beside the data.", "muted", wrap=True))
        self.side_tabs.addTab(self.limits_page, "Limits")
        columns.addWidget(self.side_tabs, 2)
        outer.addLayout(columns, 1)

        bar = Card()
        row = QHBoxLayout()
        self.check_chips = ChipRow()
        row.addWidget(self.check_chips, 1)
        self.back_button = make_button("←  Back", lambda: self._show_step("select"))
        self.validate_button = make_button("Validation & Reports  →", lambda: self._show_workspace("validation"))
        self.export_button = make_button("Export Excel…", self.export_excel, primary=True)
        for button in (self.back_button, self.validate_button, self.export_button):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.body.addLayout(row)
        outer.addWidget(bar)
        self._busy_widgets += [self.back_button, self.validate_button, self.export_button]
        self._pages["review"] = page  # the actions below look for it
        self._update_actions()
        return page

    def _build_grr_review(self) -> QWidget:
        from ..grr import quick_criteria_from_json

        self.grr_criteria = quick_criteria_from_json(self.settings.quick_check_criteria)
        card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Total Gage R&R", "heading"), 1)
        self.grr_criteria_button = make_button("Criteria…", self._edit_grr_criteria)
        head.addWidget(self.grr_criteria_button)
        card.body.addLayout(head)
        legend = QHBoxLayout()
        for kind, title in (("ok", "PASS"), ("warn", "CONDITION"), ("bad", "FAIL")):
            tile = QLabel(title)
            tile.setProperty("chip", kind)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            legend.addWidget(tile, 1)
        card.body.addLayout(legend)
        self.grr_grid = DataTable(self.palette_tokens)
        self.grr_grid.rowSelected.connect(self._on_grr_select)
        card.body.addWidget(self.grr_grid, 1)
        self.grr_summary = label("", "muted", wrap=True)
        self.grr_detail = label("Select a test to see its Study Var and calculation notes.", "muted", wrap=True)
        card.body.addWidget(self.grr_summary)
        card.body.addWidget(self.grr_detail)
        return card

    def _build_validation(self) -> QWidget:
        from .validation_workspace import ValidationWorkspace  # pulls in the statistics and the report modules

        self.validation = ValidationWorkspace(self.palette_tokens, settings=self.settings, source=self._mapping_source,
                                              save_settings=lambda: save_settings(self.settings), parent=self.content)
        return self.validation

    # ================================================================== steps and workspaces
    def _review_ready(self) -> bool:
        return bool(self.scan_result and self.scan_result.grouped and self.selected_components)

    def _wrong_samples(self) -> list[str]:
        """Samples that do not have the expected number of files (the export refuses to run while there are any)."""
        repeats = self._optional_int(self.repeats_edit)
        if self.scan_result is None or repeats is None:
            return []
        return self.scan_result.sns_with_wrong_repeat_count(repeats)

    def _on_step_clicked(self, index: int) -> None:
        if not self.is_busy:
            self._show_step("select" if index == 0 else "review")

    def _show_step(self, step: str) -> None:
        if self.workspace != "mapping":
            self._show_workspace("mapping")
        if step == "review":
            if not self._review_ready():
                self.set_status("Scan a folder and add at least one component first.")
                return
            self.content.setCurrentWidget(self._ensure_page("review"))
            self.step = "review"
            self._refresh_review()
            self.side_tabs.setCurrentWidget(self.grr_page)
            self.preview_grid.setFocus()
            self.set_status("Preview your data, then export Excel. Validation & Reports is optional and works on a copy of the data.")
        else:
            self.content.setCurrentWidget(self._pages["select"])
            self.step = "select"
            self._update_steps()

    def _mapping_source(self):
        """What Validation & Reports may analyse: the scan and the components chosen in Data Mapping."""
        from ..workspace_data import MappingSource

        result = self.scan_result
        if result is None or not result.grouped or not self.selected_components:
            return None
        return MappingSource(result.grouped, tuple(self.selected_components), self._optional_int(self.repeats_edit),
                             self._data_serial, self._scan_description, self._scan_serial)

    def _data_changed(self) -> None:
        """The scanned data, the chosen components or the choice among duplicates changed."""
        self._data_serial += 1
        self._notify_validation()

    def _notify_validation(self) -> None:
        if self.validation is not None:
            self.validation.source_changed()

    def _show_workspace(self, name: str) -> None:
        if name == self.workspace:
            return
        if name == "validation":
            if self.is_busy:
                return
            page = self._ensure_page("validation")
            self.step_bar.hide()
            self.content.setCurrentWidget(page)
            self.workspace = "validation"
            self.validation.on_show()
            self.set_status("Validation & Reports works on a copy of the data. Data Mapping and the Excel export are not affected.")
        else:
            self.step_bar.show()
            self.content.setCurrentWidget(self._pages["review"] if self.step == "review" else self._pages["select"])
            self.workspace = "mapping"
            self._update_steps()
            self.set_status("Ready." if self.step == "select" else "Preview your data, then export Excel.")
        self._update_switch()

    def _update_switch(self) -> None:
        for button, name in ((self.mapping_switch, "mapping"), (self.validation_switch, "validation")):
            button.setProperty("primary", self.workspace == name)
            repolish(button)

    def _update_steps(self) -> None:
        count = len(self.selected_components)
        has_data = bool(self.scan_result and self.scan_result.grouped)
        ready = has_data and count > 0
        blocked = ready and bool(self._wrong_samples())
        later = "Fix the file count first" if blocked else "Check the values, then save Excel"
        if self.step == "review":
            self.step_bar.set_step(0, "complete", f"{count} component{'s' if count != 1 else ''} selected")
            self.step_bar.set_step(1, "current", later)
        else:
            self.step_bar.set_step(0, "current", "Folder, profile & components")
            if not ready:
                self.step_bar.set_step(1, "locked", "Scan, then select components")
            else:
                self.step_bar.set_step(1, "warn" if blocked else "ready", later)

    def _update_actions(self) -> None:
        """Reflect what is actionable and keep the running task's inputs stable."""
        if not hasattr(self, "selected_list"):
            return
        ready = not self.is_busy
        has_data = bool(self.scan_result and self.scan_result.grouped)
        selected = self.selected_list.selected_rows()
        controls = [
            (self.add_button, ready and bool(self.available_list.selected_rows())),
            (self.add_all_button, ready and bool(self.available_list.items())),
            (self.clear_button, ready and bool(self.selected_components)),
            (self.move_up_button, ready and bool(selected) and selected[0] > 0),
            (self.move_down_button, ready and bool(selected) and selected[-1] < len(self.selected_components) - 1),
            (self.review_button, ready and has_data and bool(self.selected_components)),
        ]
        if hasattr(self, "export_button"):
            controls += [(self.export_button, ready and has_data and bool(self.selected_components) and not self._wrong_samples()),
                         (self.back_button, ready)]
        for button, enabled in controls:
            button.setEnabled(enabled)
        self.available_list.setEnabled(ready)
        self.selected_list.setEnabled(ready)
        self._update_steps()

    # ================================================================== theme
    def _update_theme_button(self) -> None:
        self.theme_button.setText("☀  Light mode" if self.palette_tokens.mode == "dark" else "☾  Dark mode")

    def _toggle_theme(self) -> None:
        self.settings.theme = "light" if self.palette_tokens.mode == "dark" else "dark"
        self.palette_tokens = apply_theme(self.app, resolve_mode(self.settings.theme))
        tables = [self.available_list, self.selected_list, *(getattr(self, name, None) for name in ("preview_grid", "limits_grid", "grr_grid"))]
        for table in tables:
            if table is not None:
                table.set_palette(self.palette_tokens)
        self.step_bar.set_palette(self.palette_tokens)
        if self.validation is not None:
            self.validation.set_palette(self.palette_tokens)
        self._update_theme_button()
        self._update_brand_logo()
        save_settings(self.settings)

    # ================================================================== helpers
    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self.is_busy = busy
        for widget in [*self._busy_widgets, self.validation_switch]:
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and cancellable)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)  # indeterminate until the first progress report
        self._update_actions()

    def _optional_int(self, edit: QLineEdit) -> int | None:
        try:
            return parse_positive_int(edit.text(), "value")
        except ValueError:
            return None

    def _read_counts(self) -> tuple[int, int] | None:
        try:
            expected = parse_positive_int(self.expected_edit.text(), "Expected samples")
            repeats = parse_positive_int(self.repeats_edit.text(), "Files per sample")
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return None
        return expected, repeats

    # ================================================================== profiles
    def _update_profile_hint(self) -> None:
        profile = self.profiles.get(self.profile_box.currentText())
        if not profile:
            self.hint_label.setText("")
            return
        kind = "Excel log" if profile.get("type") == "excel" else "Text log"
        self.hint_label.setText(f"{kind}  ·  files: {', '.join(get_profile_extensions(profile))}")

    def manage_profiles(self) -> None:
        from .profile_dialog import ProfileManager

        ProfileManager(self, self.profiles, self._on_profiles_changed).present()

    def _on_profiles_changed(self, saved_name: str | None) -> None:
        current = self.profile_box.currentText()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItems(list(self.profiles))
        self.profile_box.setCurrentText(current)
        self.profile_box.blockSignals(False)
        if saved_name:
            if saved_name == current and self.scan_result is not None:
                self._clear_results("Profile edited. Scan again to apply the changes.")
            self.profile_box.setCurrentText(saved_name)
        elif current not in self.profiles:
            self.profile_box.setCurrentText(next(iter(self.profiles), ""))
            self._clear_results("Profile deleted.")
        self._update_profile_hint()

    def _on_profile_changed(self) -> None:
        self._update_profile_hint()
        self._clear_results(f"Profile changed to '{self.profile_box.currentText()}'. Choose a folder and scan.")

    # ================================================================== scan
    def pick_folder(self) -> None:
        if self.is_busy:
            return
        start = self.folder_edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Select the folder that contains the log files",
                                                  start if start and Path(start).is_dir() else "")
        if folder:
            self.folder_edit.setText(folder)

    def _cancel_scan(self) -> None:
        if self.is_busy:
            self._cancel.set()
            self.set_status("Cancelling…")

    def scan_logs(self) -> None:
        if self.is_busy:
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
        if counts is None:
            return
        profile_name = self.profile_box.currentText()
        if profile_name not in self.profiles:
            QMessageBox.critical(self, APP_TITLE, f"Selected profile was not found:\n{profile_name or '(blank)'}")
            return
        expected, repeats = counts
        profile = dict(self.profiles[profile_name])  # a snapshot: later edits must not change this scan
        self._remember_inputs()
        self._cancel.clear()
        self._show_step("select")  # a new scan starts from the first step (the review of the old data no longer applies)
        self._set_busy(True, cancellable=True)
        self.set_status("Looking for log files…")
        cancel = self._cancel
        self.tasks.run(
            lambda report: scan_folder(folder, profile, cancel, progress=report, max_workers=SCAN_WORKERS),
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
        self._scan_description = f"Data Mapping scan of {folder} (profile {profile_name})"
        self.limits = summarize_limits(result.grouped, result.components)  # the Min / Max columns and the limits panel
        self._summary_key = self._grr_key = None
        self._review_row = self._preview_page = 0
        self.reviewed_duplicates = set()

        # Keep what the user had selected, or restore their choice from last time for this profile.
        remembered = self.selected_components or self.settings.component_sets.get(profile_name, [])
        known = set(result.components)
        self.selected_components = [c for c in remembered if c in known]

        self.samples_value.setText(f"{result.total_sns} / {expected}")
        self.files_value.setText(f"{result.total_files:,}")
        self.components_value.setText(f"{len(result.components):,}")
        self._refresh_lists()
        self.available_list.reset_view()
        self._data_changed()

        if not result.grouped:
            self._set_verdict("bad", "No usable data found.", details=False)
            self.set_status("Scan finished: nothing usable found.")
            text = describe_empty_scan(folder, profile_name, profile, result)
            better = None if result.cancelled else self._profile_that_reads(folder, profile_name)
            if better:
                question = f"{text}\n\nThe files in this folder look like '{better}'. Switch to that profile and scan again?"
                if QMessageBox.question(self, APP_TITLE, question) == QMessageBox.StandardButton.Yes:
                    self.profile_box.setCurrentText(better)
                    self._on_profile_changed()
                    self.scan_logs()
                return
            (QMessageBox.critical if result.parse_warnings else QMessageBox.warning)(self, APP_TITLE, text)
            return

        summary = summarize_scan(result, expected, repeats)
        if summary.issues:
            self._set_verdict(summary.level, f"{summary.headline}: " + " ".join(summary.issues[:2]), details=True)
        else:
            self._set_verdict("ok", summary.headline, details=False)
        restored = f" Restored {len(self.selected_components)} component(s) from last time." if self.selected_components else ""
        suffix = " (cancelled)" if result.cancelled else ""
        self.set_status(f"Scan complete{suffix}: {result.total_sns} samples, {result.total_files} files, "
                        f"{len(result.components)} components.{restored}")

    def _profile_that_reads(self, folder: Path, current: str) -> str | None:
        """Another profile that can read the files in ``folder``; never raises, because it only helps a failed scan."""
        from ..sampling import suggest_profile

        others = {name: profile for name, profile in self.profiles.items() if name != current}
        try:
            return suggest_profile(folder, others)
        except Exception:
            logger.debug("Could not look for a better profile", exc_info=True)
            return None

    def _set_verdict(self, level: str, text: str, *, details: bool) -> None:
        self.verdict.setText(("✓  " if level == "ok" else "⚠  ") + text)
        self.verdict.setProperty("role", "")
        self.verdict.setProperty("chip", VERDICT_CHIPS[level])
        repolish(self.verdict)
        self.details_button.setEnabled(details)

    def _show_scan_details(self) -> None:
        if self.scan_result is None:
            return
        counts = self._read_counts()
        if counts:
            ReportDialog(self, "Scan details", "What the scan found", full_report(self.scan_result, *counts)).present()

    def _clear_results(self, status: str) -> None:
        self.scan_result = None
        self._scan_serial += 1
        self.limits = {}
        self._summary_key = self._grr_key = None
        self._review_row = 0
        self.selected_components = []
        self.reviewed_duplicates = set()
        for value in (self.samples_value, self.files_value, self.components_value):
            value.setText("–")
        self.verdict.setText("No scan yet.")
        self.verdict.setProperty("chip", None)
        self.verdict.setProperty("role", "muted")
        repolish(self.verdict)
        self.details_button.setEnabled(False)
        self.search.setText("")
        self._show_step("select")
        self._refresh_lists()
        if "review" in self._pages:
            self._refresh_preview()
            self._refresh_grr()
        self._data_changed()
        self.set_status(status)

    def reset_workflow(self) -> None:
        if self.is_busy:
            return
        self.folder_edit.setText("")
        self._clear_results("Ready. Choose a profile and a folder, then scan.")

    # ================================================================== component lists
    def _refresh_available(self, *, reset_view: bool = False) -> None:
        components = self.scan_result.components if self.scan_result else []
        view = available_view(components, self.selected_components, self.search.text())
        self.available_list.set_items(view.items, values=[limit_texts(self.limits, c) for c in view.items], empty_text=view.empty_text)
        if reset_view:
            self.available_list.reset_view()
        self.available_info.setText(view.info)
        self._update_actions()

    def _refresh_selected(self) -> None:
        self.selected_list.set_items(self.selected_components, empty_text=SELECTED_EMPTY_TEXT)
        self.selected_info.setText(selected_info(len(self.selected_components)))
        self._update_actions()

    def _refresh_lists(self) -> None:
        self._refresh_available()
        self._refresh_selected()

    def _selection_changed(self) -> None:
        profile = self.profile_box.currentText()
        if profile:
            self.settings.component_sets[profile] = list(self.selected_components)
        self._refresh_lists()
        self._schedule_preview()
        self._notify_validation()

    def add_components(self) -> None:
        self._add(self.available_list.selected_items())

    def add_all_shown(self) -> None:
        self._add(self.available_list.items())

    def _add_at(self, row: int) -> None:
        """The + button at the end of an available row."""
        items = self.available_list.items()
        if 0 <= row < len(items):
            self._add([items[row]])

    def _remove_at(self, row: int) -> None:
        """The × button at the end of a selected row."""
        if self.is_busy or not 0 <= row < len(self.selected_components):
            return
        del self.selected_components[row]
        self._selection_changed()

    def _add(self, names: list[str]) -> None:
        if self.is_busy:
            return
        added = [n for n in dict.fromkeys(names) if n not in self.selected_components]  # each name once, in the order given
        if not added:
            return
        self.selected_components.extend(added)
        self._selection_changed()
        if self.scan_result:
            pending = {g.component for g in self.scan_result.duplicate_groups if g.component in added} - self.reviewed_duplicates
            if pending:
                groups = [g for g in self.scan_result.duplicate_groups if g.component in pending]
                DuplicateDialog(self, groups, self._on_duplicates_reviewed).present()

    def _on_duplicates_reviewed(self, reviewed: set[str], applied: bool) -> None:
        self.reviewed_duplicates |= reviewed
        self._summary_key = self._grr_key = None  # the chosen occurrences change values
        self._data_changed()
        self.set_status(
            f"Duplicate choices applied for {len(reviewed)} component name(s)." if applied
            else f"Default duplicate choices kept for {len(reviewed)} component name(s)."
        )
        self._schedule_preview()

    def remove_components(self) -> None:
        if self.is_busy:
            return
        rows = self.selected_list.selected_rows()
        for row in reversed(rows):
            del self.selected_components[row]
        if rows:
            self._selection_changed()

    def clear_selected(self) -> None:
        if self.is_busy:
            return
        if self.selected_components:
            self.selected_components = []
            self._selection_changed()

    def move_selected(self, direction: int) -> None:
        if self.is_busy:
            return
        rows = self.selected_list.selected_rows()
        if not move_items(self.selected_components, rows, direction):
            return
        self._selection_changed()
        self.selected_list.select_rows([r + direction for r in rows])

    # ================================================================== review (step 2)
    def _schedule_preview(self) -> None:
        """Redraw the review a moment from now (a burst of changes becomes one redraw). Only while it is on screen."""
        if self.step == "review" and "review" in self._pages:
            self._preview_timer.start(120)

    def _refresh_review(self) -> None:
        self._ensure_page("review")
        self._preview_timer.stop()
        self._refresh_preview()
        self._refresh_checks()
        self._refresh_grr()
        self._update_actions()

    def _edit_grr_criteria(self) -> None:
        GrrCriteriaDialog(self, self.grr_criteria, self._set_grr_criteria).present()

    def _set_grr_criteria(self, criteria) -> None:
        """New criteria: the statuses and colours are worked out again from the same figures, nothing is recalculated."""
        from ..grr import quick_criteria_to_json

        self.grr_criteria = criteria
        self.settings.quick_check_criteria = quick_criteria_to_json(criteria)
        save_settings(self.settings)
        self._refresh_grr()

    def _refresh_grr(self) -> None:
        """Assess each selected test over every SN and repeat, independently of the preview row limit."""
        if "review" not in self._pages:
            return
        from ..grr import CAUTION, FAIL, NOT_APPLIED, NOT_EVALUATED, PASS, QUICK_LABELS, quick_check, summarize_grr

        words = {PASS: "PASS", CAUTION: "CONDITION", FAIL: "FAIL", NOT_EVALUATED: "N/A", NOT_APPLIED: "—"}
        levels = {PASS: "pass", CAUTION: "caution", FAIL: "fail", NOT_EVALUATED: "neutral", NOT_APPLIED: "neutral"}
        result = self.scan_result
        components = tuple(self.selected_components)
        repeats = self._optional_int(self.repeats_edit)
        key = (id(result), components, repeats)
        if key != self._grr_key:
            if result and result.grouped and self._is_big():
                grouped = result.grouped
                self._background("grr", lambda: summarize_grr(grouped, components, repeats), lambda value: self._grr_done(key, value))
                self.grr_grid.set_table(["Test", "%Study Var", "%SV/Tol", "NDC", "Result"], [], aligns=["w", "e", "e", "center", "center"],
                                        empty_text="Calculating the GRR pre-check…", stretch=0)
                self.grr_summary.setText("")
                return
            self._grr_results = summarize_grr(result.grouped, components, repeats) if result and result.grouped else []
            self._grr_key = key
        rows, tags = [], {}
        for index, entry in enumerate(self._grr_results):
            status = quick_check(entry, self.grr_criteria)
            cells = [f"{value:.2f}" if value is not None else "N/A" for value in (entry.percent_study_var, entry.percent_tolerance)]
            cells.append(str(entry.ndc) if entry.ndc is not None else "N/A")
            for column, each in enumerate((status.study, status.tolerance, status.ndc, status.overall), start=1):
                tags[index, column] = levels[each]
            rows.append((entry.component, *cells, words[status.overall]))
        self.grr_grid.set_table(["Test", "%Study Var", "%SV/Tol", "NDC", "Result"], rows, aligns=["w", "e", "e", "center", "center"],
                                empty_text="Select tests to calculate their GRR pre-check.", cell_tags=tags, stretch=0)
        left_out = [QUICK_LABELS[c.metric] for c in self.grr_criteria if not c.enabled]
        count = f"{len(rows)} test item{'s' if len(rows) != 1 else ''}"
        self.grr_summary.setText(count + (f" · not applied: {', '.join(left_out)}" if left_out else "") if rows else "")
        if rows:
            selected = max(0, self.grr_grid.currentIndex().row())
            self.grr_grid.select_row(selected, notify=False)
            self._on_grr_select(selected)
        else:
            self.grr_detail.setText("Select a test to see its Study Var and calculation notes.")

    def _grr_done(self, key: tuple, results: list) -> None:
        self._grr_results, self._grr_key = results, key
        self._refresh_grr()

    def _on_grr_select(self, index: int) -> None:
        if not 0 <= index < len(self._grr_results):
            return
        entry = self._grr_results[index]
        repeat_text = str(entry.repeats) if entry.repeats is not None else "unequal"
        lines = [entry.component, f"{entry.parts} samples × {repeat_text} repeats"]
        if entry.study_var is not None:
            variation = f"{entry.study_var:.2e}" if 0 < abs(entry.study_var) < 0.01 else f"{entry.study_var:.2f}"
            lines.append(f"Study Var (6 × SD): {variation} {entry.unit}".rstrip())
        if entry.note:
            lines.append(entry.note)
        self.grr_detail.setText("\n".join(lines))

    def _update_pager(self, first: int, shown: int, total: int, pages: int) -> None:
        for widget in self.pager:
            widget.setVisible(pages > 1)
        if pages > 1:
            self.pager_label.setText(f"Columns {first + 1}–{first + shown} of {total}")
            self.pager_prev.setEnabled(self._preview_page > 0)
            self.pager_next.setEnabled(self._preview_page < pages - 1)

    def _page_preview(self, step: int) -> None:
        self._preview_page = max(0, self._preview_page + step)
        self._schedule_preview()

    def _refresh_preview(self) -> None:
        """The table of rows (one page of columns) and, beside it, the limits for the chosen row."""
        self._ensure_page("review")
        result = self.scan_result
        components = list(self.selected_components)
        self._preview_components = tuple(components)
        # One page of columns at a time keeps the table readable; the export always has every column.
        table = preview_table(result, components, self._preview_page, self._optional_int(self.repeats_edit))
        self._preview_page = table.page
        self._preview_rows = table.export_rows
        self._update_pager(table.first, len(table.page_components), len(components), table.pages)
        self.preview_grid.set_table(table.headings, table.rows, table.tags if table.rows else None,
                                    aligns=["center", "w", "w", *["e"] * len(table.page_components)], empty_text=table.empty_text)
        self.preview_info.setText(table.note)
        self.review_count.setText(table.count_text)
        if not table.rows and (result is None or not result.grouped):
            self._refresh_limits()
            return
        if self._preview_rows:  # keep the row you were looking at, or start with the first
            self._review_row = max(0, min(self._review_row, len(self._preview_rows) - 1))
            self.preview_grid.select_row(self._review_row, notify=False)
        self._refresh_limits()

    def _on_preview_select(self, row: int) -> None:
        if row < 0:
            return
        if row != self._review_row:
            self._review_row = row
            self._refresh_limits()
        self.side_tabs.setCurrentWidget(self.limits_page)

    def _refresh_limits(self) -> None:
        """The limits panel: every selected component with the chosen row's value, judged against its limits."""
        components = self._preview_components
        self.limits_title.setText(f"Limits ({len(components)})" if components else "Limits")
        headings, aligns = ["Component", "Value", "Min", "Max", "Unit"], ["w", "e", "e", "e", "w"]
        if not 0 <= self._review_row < len(self._preview_rows):  # no row to compare: just the limits
            self.review_row_label.setText(NO_ROW_CHOSEN_TEXT)
            self.limits_grid.set_table(headings, limit_overview(components, self.limits), aligns=aligns, stretch=0, max_width=260)
            return
        row = self._preview_rows[self._review_row]
        self.review_row_label.setText(f"Row {row.index}   ·   {row.sn}   ·   {row.filename}")
        rows, tags = limit_panel(row, components, self.limits)
        self.limits_grid.set_table(headings, rows, tags, aligns=aligns, stretch=0, max_width=260)

    def _is_big(self) -> bool:
        """Whether the checks of the Review are too much work for the moment between two clicks."""
        files = self.scan_result.total_files if self.scan_result else 0
        return len(self.selected_components) * files > BIG_REVIEW_CELLS

    def _background(self, name: str, work: Callable[[], object], apply: Callable[[object], None]) -> None:
        """Work something out on a worker thread for the data as they are now, and use the answer only if they still are."""
        key = (name, id(self.scan_result), tuple(self.selected_components), self._optional_int(self.repeats_edit), self._data_serial)
        if self._pending.get(name) == key:
            return  # already on its way

        def wanted() -> tuple:
            return (name, id(self.scan_result), tuple(self.selected_components), self._optional_int(self.repeats_edit), self._data_serial)

        def done(value) -> None:
            if self._pending.get(name) == key:
                del self._pending[name]
            if wanted() == key:
                apply(value)

        def failed(_exc: BaseException) -> None:  # the runner has logged it
            self._pending.pop(name, None)
            if wanted() == key:
                self.set_status(f"The {name} of the review could not be worked out. See the log.")
                if name == "summary":
                    self.check_chips.set_chips([("bad", "!  The data could not be checked")])

        self._pending[name] = key
        self.tasks.run(lambda _report: work(), on_success=done, on_error=failed)

    def _review_summary(self) -> ReviewSummary | None:
        """Empty cells and out-of-limit rows over every row (not just the ones the table shows); kept until the data change.
        None while a large selection is still being worked out in the background."""
        result = self.scan_result
        if result is None or not result.grouped or not self.selected_components:
            return None
        key = (id(result), tuple(self.selected_components))
        if key != self._summary_key:
            if self._is_big():
                grouped, components, limits = result.grouped, list(self.selected_components), dict(self.limits)
                self._background("summary", lambda: summarize_review(grouped, components, limits), lambda value: self._summary_done(key, value))
                return None
            self._summary = summarize_review(result.grouped, self.selected_components, self.limits)
            self._summary_key = key
        return self._summary

    def _summary_done(self, key: tuple, summary: ReviewSummary) -> None:
        self._summary, self._summary_key = summary, key
        self._refresh_checks()

    def _refresh_checks(self) -> None:
        """The chips beside the Export button: what to know before saving."""
        result, summary = self.scan_result, self._review_summary()
        if result is None or not result.grouped or not self.selected_components:
            self.check_chips.set_chips([])
            return
        if summary is None:  # a large selection: the answer arrives in a moment
            self.check_chips.set_chips([("info", "Checking the data…")])
            return
        expected, repeats = self._optional_int(self.expected_edit), self._optional_int(self.repeats_edit)
        wrong = self._wrong_samples() if repeats is not None else []
        self.check_chips.set_chips(check_chips(result, summary, expected=expected, repeats=repeats, wrong=wrong))

    # ================================================================== export
    def export_excel(self) -> None:
        if self.is_busy:
            return
        result = self.scan_result
        if result is None or not result.grouped:
            QMessageBox.warning(self, APP_TITLE, "Please scan a folder first.")
            return
        if not self.selected_components:
            QMessageBox.warning(self, APP_TITLE, "Please select at least one component.")
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
            QMessageBox.critical(
                self, APP_TITLE,
                f"Some samples do not have exactly {repeats} files:\n\n" + "\n".join(wrong[:20])
                + (f"\n… and {len(wrong) - 20} more" if len(wrong) > 20 else ""))
            return
        start = self.settings.last_export_dir
        initial = str(Path(start) / DEFAULT_OUTPUT_FILE) if start and Path(start).is_dir() else DEFAULT_OUTPUT_FILE
        output, _ = QFileDialog.getSaveFileName(self, "Save the Excel file", initial, "Excel workbook (*.xlsx)")
        if not output:
            return
        path, grouped, components = Path(output), dict(result.grouped), list(self.selected_components)
        self._set_busy(True)
        self.set_status("Creating the Excel file…")
        from ..exporter import generate_excel

        self.tasks.run(
            lambda _report: generate_excel(grouped, components, path, repeats),
            on_success=lambda _result: self._on_export_done(path),
            on_error=self._on_export_error,
        )

    def _on_export_done(self, path: Path) -> None:
        self._set_busy(False)
        self.settings.last_export_dir = str(path.parent)
        save_settings(self.settings)
        self.set_status(f"Exported: {path}")
        ExportDoneDialog(self, path).present()

    def _on_export_error(self, exc: BaseException) -> None:
        logger.error("Export failed: %s", exc, exc_info=exc)
        self._set_busy(False)
        self.set_status("Export failed.")
        QMessageBox.critical(self, APP_TITLE, str(exc))

    # ================================================================== access (the owner's off switch)
    def _start_checks(self) -> None:
        """Runs a moment after start-up so the first paint is not competing with the network."""
        from .. import access

        if self._enforce_access:
            self.verify_access(then=self._check_for_update)  # a copy that may not run is not offered an update
            self._recheck_timer.start(access.RECHECK_MS)
        else:
            self._check_for_update()

    def _recheck_access(self) -> None:
        from .. import access

        self.verify_access()
        self._recheck_timer.start(access.RECHECK_MS)

    def verify_access(self, then: Callable[[], None] | None = None) -> None:
        """Read status.json in the background. ``then`` runs if the program may be used afterwards."""
        from .. import access, updater

        def finish(block: access.Block | None, detail: str = "") -> None:
            save_settings(self.settings)
            self._apply_access(block, detail)
            if block is None and then is not None:
                then()

        def on_status(status: updater.Status) -> None:
            finish(access.record_status(self.settings, status, time.time()))

        def on_error(exc: BaseException) -> None:
            logger.info("Status check failed: %s", exc)
            # No answer is not permission: whatever was decided before still stands, until the grace period ends.
            finish(access.current_block(self.settings, time.time()), f"Could not check: {exc}")

        self.tasks.run(lambda _report: updater.fetch_status(), on_success=on_status, on_error=on_error)

    def _apply_access(self, block, detail: str = "") -> None:
        from .access_dialog import AccessDialog

        dialog = self.access_dialog
        if block is None:
            if dialog is not None:
                dialog.withdraw()
            self.access_dialog = None
        elif dialog is not None:
            dialog.show_block(block, detail)
        else:
            logger.warning("This copy may not be used (%s)", block.kind)
            self.access_dialog = AccessDialog(self, block, detail)
            self.access_dialog.present()

    # ================================================================== updates
    def _check_for_update(self, manual: bool = False) -> None:
        from .. import updater

        if manual:
            self.set_status("Checking for updates…")
        self.tasks.run(
            lambda _report: updater.check_for_update(),
            on_success=lambda info: self._on_update_checked(info, manual),
            on_error=lambda exc: self._on_update_check_failed(exc, manual),
        )

    def _on_update_checked(self, info: updater.UpdateInfo | None, manual: bool) -> None:
        from .update_dialog import UpdateDialog

        if info is None:
            if manual:
                self.set_status("You have the latest version.")
                QMessageBox.information(self, APP_TITLE, f"{APP_TITLE} {__version__} is the latest version.")
            return
        self._update_info = info
        if info.is_mandatory_for(__version__):
            UpdateDialog(self, info, mandatory=True).present()
            return
        if manual or (self.settings.check_updates and info.version != self.settings.skipped_version):
            self.banner_label.setText(f"Version {info.version} is available. You are running {__version__}.")
            self.banner.show()
        if manual:
            self.set_status(f"Version {info.version} is available.")
            UpdateDialog(self, info, mandatory=False).present()

    def _on_update_check_failed(self, exc: BaseException, manual: bool) -> None:
        from .. import updater

        logger.info("Update check failed: %s", exc)
        if manual:
            self.set_status("Could not check for updates.")
            if QMessageBox.question(self, APP_TITLE, f"Could not check for updates.\n\n{exc}\n\nOpen the releases page in your browser?"
                                    ) == QMessageBox.StandardButton.Yes:
                webbrowser.open(f"{updater.RELEASES_URL}/latest")

    def _open_update_dialog(self) -> None:
        from .update_dialog import UpdateDialog

        if self._update_info:
            UpdateDialog(self, self._update_info, mandatory=self._update_info.is_mandatory_for(__version__)).present()

    def hide_update_banner(self) -> None:
        self.banner.hide()

    def skip_update(self, version: str) -> None:
        if version:
            self.settings.skipped_version = version
            save_settings(self.settings)
        self.hide_update_banner()

    # ================================================================== misc
    def _show_shortcuts(self) -> None:
        text = "\n".join(f"{keys:<24}{action}" for keys, action in SHORTCUTS)
        ReportDialog(self, "Keyboard shortcuts", "Keyboard shortcuts", text, monospace=True).present()

    def sizeHint(self) -> QSize:
        return QSize(1180, 760)


def install_error_hook(window: MainWindow) -> None:
    """An error in a slot is logged and shown; the program goes on."""
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        logger.error("Unhandled error in UI callback", exc_info=(exc_type, exc_value, exc_tb))
        try:
            QMessageBox.critical(window, APP_TITLE,
                                 f"Something unexpected went wrong:\n\n{exc_value}\n\nDetails were written to:\n{log_path()}")
        except Exception:  # the window itself may be what is broken
            previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    """Open the window and run until it is closed. Returns the exit code."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_TITLE)
    icon = resource_path("assets", "DataMapperX.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow(app)
    install_error_hook(window)
    window.show()
    window.warm_up()
    return app.exec()


main = run
