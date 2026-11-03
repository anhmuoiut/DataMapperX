"""The main DataMapperX window. It opens on the Dashboard, whose two cards lead into Data Mapping (Select, then Review Data) and
Validation & Reports (with a RawData.xlsx imported); a button in the navigation leads back, and nothing is cleared by moving between them.

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
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
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
from ..palette import DARK
from ..paths import is_frozen, log_path, resource_path, user_data_dir
from ..profiles import get_profile_extensions, load_profiles
from ..reporting import describe_empty_scan, full_report, summarize_scan
from ..scanner import scan_folder
from ..settings import Settings, load_settings, save_settings
from ..utils import parse_positive_int
from ..workflow import (
    SELECTED_EMPTY_TEXT,
    available_view,
    limit_overview,
    limit_panel,
    limit_texts,
    move_items,
    preview_table,
    selected_info,
)
from .dashboard import DashboardPage
from .dialogs import AboutDialog, ExportDoneDialog, GrrCriteriaDialog, ReportDialog, label, open_path
from .duplicate_dialog import DuplicateDialog
from .pcb_background import PcbBackground
from .tasks import TaskRunner
from .theme import apply_theme, make_palette, resolve_mode, stylesheet
from .widgets import (
    ActionTable,
    Card,
    CompactPage,
    CountTile,
    DataTable,
    ElidedLabel,
    FlowRow,
    NarrowPage,
    StepBar,
    WheelGuardedComboBox,
    make_badge,
    make_button,
    repolish,
    set_badge,
)

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
    ("Ctrl+E", "Go to Review Data, then export RawData.xlsx"),
    ("Double-click / Enter", "Add or remove the highlighted component"),
    ("Ctrl+A", "Select every component in a list"),
    ("Delete", "Remove the highlighted selected components"),
    ("Alt+Up  /  Alt+Down", "Move the highlighted selected components up or down"),
)
VERDICT_CHIPS = {"ok": "ok", "warn": "warn", "bad": "bad"}
ACTION_ROW_HEIGHT = 30  # the rows of the Available and Selected lists: a little taller than a data table's (28), for the + and ×
REVIEW_ROW_HEIGHT = 28  # and of the short tables beside the data of the Review: as a data table's
QUALITY_MIN_WIDTH = 430  # the Pre-check card never gets narrower, so its table has no sideways scroll bar (the design: 410)
GRR_NAME_WIDTH = 230  # the widest the Test column of the Pre-check gets: a longer name is cut short (its tooltip has it all)
REVIEW_COMPACT_BELOW = 480  # page height, in pixels, under which the Review gives up the lines that only explain (the smallest
#                             window, 680 tall, leaves it about 530: still roomy; only a screen smaller than that is not)
VALUE_FILTER_TIP = "Show only components with numeric MIN and MAX limits."
MAPPING_NARROW_BELOW = 1150  # page widths under which the lists get more of the width and Source keeps only what it needs
MAPPING_STRETCH = (27, 68, 35)  # Source : Available : Selected, the design's 270 : 680 : 350
MAPPING_STRETCH_NARROW = (24, 56, 40)  # the Selected list has its number, ↑ ↓ and × beside every name: it needs more of a narrow page
DASHBOARD_STATUS = "Choose a starting point."
PCB_ANIMATED = True  # the circuit board the Dashboard stands on: False leaves it still, drawn once, with nothing running


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
        self.workspace = "dashboard"  # where the program opens; "mapping" (the two steps) or "validation" once a workflow is chosen
        self.workflow_route = "logs"
        self._analysis_after_mapping = False
        self.validation = None  # built the first time it is opened
        self._excel_state = None  # what the Analyze by Excel File dialog was left with (an ExcelState), once it has been opened
        self.access_dialog: AccessDialog | None = None
        self._cancel = threading.Event()
        self._data_serial = 0  # moves whenever the scanned data (or the choice among duplicates) changes
        self._scan_serial = 0  # moves with every new scan (or reset), never for a duplicate choice
        self._scan_description = ""
        self._review_row = 0  # the preview row whose values the limits panel shows
        self._preview_page = 0
        self._preview_rows: list[ExportRow] = []
        self._preview_components: tuple[str, ...] = ()
        self._grr_results: list[GrrResult] = []
        self._grr_note = False  # whether the Pre-check has a note on the test it shows
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
        root.addWidget(self._build_nav())
        self.content = QStackedWidget()
        root.addWidget(self.content, 1)
        self.setCentralWidget(central)
        self._build_status_bar()
        self._chrome_dark = False  # see _update_canvas
        self.canvas = PcbBackground(self, bands=self._canvas_bands, animated=PCB_ANIMATED)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_review)
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.timeout.connect(self._recheck_access)

        self._ensure_page("dashboard")  # first, so that it is the page on show; Data Mapping is built behind it, as it always was
        self._ensure_page("select")
        self._bind_shortcuts()
        self._restore_inputs()
        self._setup_geometry()
        self._update_profile_hint()
        self._refresh_lists()
        self._update_switch()
        self.nav_bar.hide()  # the Dashboard has no navigation of its own: its two cards are the way in
        self.set_status(DASHBOARD_STATUS)
        self._update_canvas()
        self.search.textChanged.connect(lambda _text: self._refresh_available(reset_view=True))
        self.repeats_edit.textChanged.connect(lambda _text: (self._schedule_preview(), self._notify_validation()))

        if self._enforce_access:
            from .. import access

            now = time.time()
            access.begin(self.settings, now)
            block = access.current_block(self.settings, now)
            if block:  # a copy that was told to stop stays stopped, even before the network answers
                QTimer.singleShot(150, self, lambda: self._apply_access(block))  # with the window as context: gone with it
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
        self.header = header = QWidget()
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
        pixmap = self._brand.get("dark" if self.workspace == "dashboard" else self.palette_tokens.mode)  # the Dashboard is dark
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

    def _build_nav(self) -> QWidget:
        self.nav_bar = QWidget()
        nav = QHBoxLayout(self.nav_bar)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(8)
        self.home_button = make_button("⌂  Dashboard", lambda: self._show_workspace("dashboard"))
        self.home_button.setProperty("glyphs", True)  # the house is not in the interface font
        self.home_button.setToolTip("Back to the Dashboard. Your scan, your data and your results stay as they are.")
        self.mapping_switch = make_button("Data Mapping", lambda: self._show_workspace("mapping"))
        self.validation_switch = make_button("Validation & Reports", lambda: self._show_workspace("validation"))
        nav.addWidget(self.home_button)
        for button in (self.mapping_switch, self.validation_switch):
            button.setParent(self.nav_bar)
            button.hide()  # compatibility handles; the V6 workflow steps are the visible navigation
        self.workflow_breadcrumb = ElidedLabel("Map test logs", "muted")
        nav.addWidget(self.workflow_breadcrumb, 1)
        self.step_bar = StepBar(("Mapping", "Review & Pre-check", "Analyze", "Results", "Report"), self.palette_tokens, compact=True)
        self.step_bar.clicked.connect(self._on_step_clicked)
        nav.addWidget(self.step_bar)
        return self.nav_bar

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)
        self.status_label = ElidedLabel("Ready. Choose a profile and a folder, then scan.", "muted")
        self.status_label.setContentsMargins(10, 0, 0, 0)
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
            page = {"dashboard": self._build_dashboard, "select": self._build_select, "review": self._build_review,
                    "validation": self._build_validation}[name]()
            self._pages[name] = page
            self.content.addWidget(page)
        return page

    def warm_up(self) -> None:
        """Build the other pages while the user reads the first one, so that going there later is instant."""
        QTimer.singleShot(0, self, lambda: self._ensure_page("review"))  # the window is the timers' context: if it is closed and
        QTimer.singleShot(120, self, lambda: self._ensure_page("validation"))  # deleted first, they never run on what is left

    def _build_dashboard(self) -> QWidget:
        self.dashboard = DashboardPage(self.palette_tokens)
        self.dashboard.map_requested.connect(self.start_mapping)
        self.dashboard.rawdata_requested.connect(self.start_excel_analysis)
        return self.dashboard

    @staticmethod
    def _page_header(title: str) -> tuple[QWidget, QHBoxLayout]:
        """One line: the title of a screen, and at the right its state and its way back."""
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(12)
        row.addWidget(label(title, "pageTitle"))
        row.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        row.addLayout(actions)
        row.setAlignment(actions, Qt.AlignmentFlag.AlignVCenter)  # a badge is a pill, not as tall as the title beside it
        return header, actions

    def _build_select(self) -> QWidget:
        page = NarrowPage(MAPPING_NARROW_BELOW)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(6)
        header, actions = self._page_header("Select measurements")
        self.scan_badge = make_badge()
        actions.addWidget(self.scan_badge)
        outer.addWidget(header)
        layout = QHBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(self._build_source(), MAPPING_STRETCH[0])  # the proportions of the design, about 270 : 680 : 350 pixels at 1360
        layout.addWidget(self._build_available(), MAPPING_STRETCH[1])
        layout.addWidget(self._build_selected(), MAPPING_STRETCH[2])
        outer.addLayout(layout, 1)

        def share(narrow: bool) -> None:
            for index, factor in enumerate(MAPPING_STRETCH_NARROW if narrow else MAPPING_STRETCH):
                layout.setStretch(index, factor)

        page.narrow_changed.connect(share)
        self._busy_widgets += [self.manage_button, self.browse_button, self.scan_button, self.reset_button, self.expected_edit,
                               self.repeats_edit, self.folder_edit, self.search, self.value_filter, self.profile_box]
        height = max(button.sizeHint().height() for button in (self.add_all_button, self.add_button, self.review_button))
        for button in (self.add_all_button, self.add_button, self.review_button):
            button.setMinimumHeight(height)  # the filled button is taller than the others: the two footers are one height, and level
        self._update_scan_badge()
        return page

    def _update_scan_badge(self) -> None:
        """What the scan found, in a word, beside the title of the screen."""
        result = self.scan_result
        if result is None:
            set_badge(self.scan_badge, "No scan yet")
        elif not result.grouped:
            set_badge(self.scan_badge, "No usable data", "bad")
        elif result.cancelled:
            set_badge(self.scan_badge, "Scan cancelled", "warn")
        else:
            set_badge(self.scan_badge, "Scan completed", "ok")

    def _build_source(self) -> Card:
        card = Card("01 · Source", scrolls=True, dense=True)  # with large text on a small screen it scrolls instead of overlapping
        profile = QVBoxLayout()  # a caption sits close above what it names: the pairs read as pairs, the card's gaps separate them
        profile.setSpacing(3)
        head = QHBoxLayout()
        head.addWidget(label("Log profile"), 1)
        self.manage_button = make_button("Manage…", self.manage_profiles)
        head.addWidget(self.manage_button)
        profile.addLayout(head)
        self.profile_box = WheelGuardedComboBox()
        self.profile_box.addItems(list(self.profiles))
        self.profile_box.activated.connect(lambda _index: self._on_profile_changed())
        profile.addWidget(self.profile_box)
        card.body.addLayout(profile)
        folder = QVBoxLayout()
        folder.setSpacing(3)
        folder.addWidget(label("Source folder"))
        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder that holds the logs")
        self.folder_edit.returnPressed.connect(self.scan_logs)
        self.browse_button = make_button("Browse…", self.pick_folder)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(self.browse_button)
        folder.addLayout(row)
        card.body.addLayout(folder)
        counts = QHBoxLayout()  # Expected samples and Files per sample side by side
        counts.setSpacing(8)
        self.expected_edit, self.repeats_edit = QLineEdit(), QLineEdit()
        for caption, edit in (("Expected samples", self.expected_edit), ("Files per sample", self.repeats_edit)):
            pair = QVBoxLayout()
            pair.setSpacing(3)
            pair.addWidget(label(caption, "muted"))
            pair.addWidget(edit)
            counts.addLayout(pair, 1)
        card.body.addLayout(counts)

        self.scan_button = make_button("Scan logs", self.scan_logs, primary=True)
        self.cancel_button = make_button("Cancel", self._cancel_scan)
        self.cancel_button.setEnabled(False)
        self.reset_button = make_button("Reset", self.reset_workflow)
        for button in (self.cancel_button, self.reset_button):
            button.setMinimumWidth(58)  # a style's 80-pixel minimum would make the Source column wider than it needs to be
        buttons = QHBoxLayout()  # the scan and what belongs to it on one row
        buttons.setSpacing(6)
        buttons.addWidget(self.scan_button, 3)
        buttons.addWidget(self.cancel_button, 2)
        buttons.addWidget(self.reset_button, 2)
        card.body.addLayout(buttons)

        strip = QFrame()  # the three figures of the scan on one quiet strip
        strip.setObjectName("metricStrip")
        tiles = QHBoxLayout(strip)
        tiles.setContentsMargins(10, 5, 10, 5)
        self.samples_value, self.files_value, self.components_value = (label("–", "metric") for _ in range(3))
        for value, caption in ((self.samples_value, "Samples"), (self.files_value, "Files"), (self.components_value, "Fields")):
            tile = QVBoxLayout()
            tile.setSpacing(0)
            tile.addWidget(value)
            tile.addWidget(label(caption, "muted"))
            tiles.addLayout(tile)
        card.body.addWidget(strip)
        self.verdict = label("No scan yet.", "muted", wrap=True)
        card.body.addWidget(self.verdict)
        self.details_button = make_button("View scan details", self._show_scan_details)
        self.details_button.setEnabled(False)
        card.body.addWidget(self.details_button)
        card.body.addStretch(1)
        self.version_label = ElidedLabel(f"Version {__version__}  ·  {APP_CREDIT}", "muted")  # never what fixes the column's width
        card.body.addWidget(self.version_label)
        return card

    def _build_available(self) -> Card:
        """The title and the Value filter on one line; the search; the table; and the count with the ways to add under it."""
        card = Card("02 · Available Measurements", head=True, dense=True, short_title="02 · Available")
        self.value_filter = QCheckBox("Value")  # a display filter only: it changes what is listed, never what is selected
        self.value_filter.setToolTip(VALUE_FILTER_TIP)
        self._style_value_filter()
        self.value_filter.toggled.connect(lambda _on: self._refresh_available(reset_view=True))
        self.available_info = label("", "muted")  # "39 available", or "3 of 39 shown" while filtering
        card.head.addWidget(self.value_filter, 0, Qt.AlignmentFlag.AlignVCenter)
        card.head.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search measurements…")
        self.search.setClearButtonEnabled(True)
        self.available_list = ActionTable(self.palette_tokens, kind="add", name_heading="Component", value_headings=("Min", "Max"),
                                          row_height=ACTION_ROW_HEIGHT, row_lines=True)
        self.available_list.action.connect(self._add_at)
        self.available_list.activated_rows.connect(lambda _rows: self.add_components())
        self.available_list.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        self.add_all_button = make_button("Add all shown", self.add_all_shown)
        self.add_button = make_button("Add →", self.add_components)
        card.body.addWidget(self.search)
        card.body.addWidget(self.available_list, 1)
        footer = QHBoxLayout()  # level with the Selected panel's: its count, ↑ ↓ and the way on
        footer.setSpacing(6)
        footer.addWidget(self.available_info)
        footer.addStretch(1)
        footer.addWidget(self.add_all_button)
        footer.addWidget(self.add_button)
        card.body.addLayout(footer)
        return card

    def _build_selected(self) -> Card:
        """The title; Clear selection, level with the search of the list beside it; the names, each with its number and ×; and under
        them the count, one ↑ ↓ pair for the highlighted row, and the way on."""
        card = Card("03 · Selected Measurements", dense=True, short_title="03 · Selected")
        card.title.setMinimumHeight(self.value_filter.sizeHint().height())  # as tall as the Available title line: the two titles are level
        self.selected_list = ActionTable(self.palette_tokens, kind="remove", name_heading="Component", numbered=True,
                                         row_height=ACTION_ROW_HEIGHT, row_lines=True, reorder=True, show_header=False)
        self.selected_list.action.connect(self._remove_at)
        self.selected_list.move_keys.connect(self.move_selected)  # Alt+Up / Alt+Down: the same as ↑ ↓ below the list
        self.selected_list.activated_rows.connect(lambda _rows: self.remove_components())
        self.selected_list.delete_pressed.connect(self.remove_components)
        self.selected_list.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        self.selected_info = ElidedLabel("", "muted")  # "6 selected"; it gives way to the buttons beside it in a narrow window
        self.move_up_button = make_button("↑", lambda: self.move_selected(-1))
        self.move_down_button = make_button("↓", lambda: self.move_selected(1))
        for button, name in ((self.move_up_button, "up"), (self.move_down_button, "down")):
            button.setFixedWidth(32)
            button.setToolTip(f"Move the highlighted measurement {name}")
            button.setAccessibleName(f"Move {name}")
        self.clear_button = make_button("Clear selection", self.clear_selected)
        self.review_button = make_button("Review Data  →", lambda: self._show_step("review"), primary=True)
        self.selected_list.viewport().setToolTip("Order here is the column order of RawData.xlsx.")
        slot = QWidget()  # as tall as the search above the list beside it, so that the two lists start level
        slot_row = QHBoxLayout(slot)
        slot_row.setContentsMargins(0, 0, 0, 0)
        slot_row.addStretch(1)
        slot_row.addWidget(self.clear_button)
        slot.setMinimumHeight(self.search.sizeHint().height())
        card.body.addWidget(slot)
        card.body.addWidget(self.selected_list, 1)
        footer = QHBoxLayout()  # level with the footer of the Available list
        footer.setSpacing(6)
        footer.addWidget(self.selected_info)
        footer.addWidget(self.move_up_button)
        footer.addWidget(self.move_down_button)
        footer.addStretch(1)
        footer.addWidget(self.review_button)
        card.body.addLayout(footer)
        return card

    def _build_review(self) -> QWidget:
        """Step 2, Review Data: the data as they will be exported beside the checks of them, and the two ways on: Export RawData.xlsx
        and Continue to Analysis. Neither needs the other."""
        page = CompactPage(REVIEW_COMPACT_BELOW)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(6)
        header, actions = self._page_header("Review Data")
        self.back_button = make_button("←  Edit selection", lambda: self._show_step("select"))
        self.review_badge = make_badge()
        actions.addWidget(self.back_button)
        actions.addWidget(self.review_badge)
        outer.addWidget(header)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        columns.addWidget(self._build_preview_card(), 8)  # the data first: 1.6 : 1 (the design: 1.55 : 1)
        columns.addWidget(self._build_quality_card(), 5)
        outer.addLayout(columns, 1)

        self.validate_button = make_button("Continue to Analysis  →", lambda: self._show_workspace("validation"), primary=True)
        self.export_button = make_button("Export RawData.xlsx…", self.export_excel)
        self.export_button.setAccessibleName("Export RawData.xlsx")
        self.validate_button.setAccessibleName("Continue to Analysis")
        self.export_button.setToolTip("Save the selected measurements as RawData.xlsx. No analysis needed.")
        self.validate_button.setToolTip("Analyze this dataset directly. No export needed.")
        self.export_button.setMinimumHeight(self.validate_button.sizeHint().height())  # the filled button is the taller: one height
        choices = QHBoxLayout()  # the bottom action row: both ways on, side by side
        choices.setSpacing(10)
        choices.addStretch(1)
        choices.addWidget(self.export_button)
        choices.addWidget(self.validate_button)
        outer.addLayout(choices)
        page.compact_changed.connect(self._review_compact)
        self._busy_widgets += [self.back_button, self.validate_button, self.export_button]
        self._pages["review"] = page  # the actions below look for it
        self._update_actions()
        return page

    def _review_compact(self, compact: bool) -> None:
        """A short window: the lines that only explain make room for the tables."""
        self._sync_review_extras()

    def _sync_review_extras(self) -> None:
        """Which of the lines around the tables are shown. A line that carries something of its own is always shown (a preview cut
        short, a note on how a test was judged); one that only explains gives its place to the tables when the window is short, and
        one that only says what the badge beside the title already says is left out."""
        if "review" not in self._pages:
            return
        compact = self._pages["review"].compact
        self.preview_info.setVisible(self.preview_info.text().rstrip(".") != self.review_count.text())  # "30 rows." under "30 rows"
        self.grr_detail.setVisible(not compact or self._grr_note)

    def _build_preview_card(self) -> Card:
        """The data as they will be exported, as large as the window allows: the title, the count and the columns' pager in one line,
        then the table."""
        card = Card("Data Preview", badge=True, dense=True)
        card.title.setToolTip("Same rows and column order as your Excel file. Click a row to compare its values with the limits.")
        self.review_count = card.badge  # "30 rows"
        self.pager_prev = make_button("‹", lambda: self._page_preview(-1))
        self.pager_next = make_button("›", lambda: self._page_preview(1))
        for button in (self.pager_prev, self.pager_next):
            button.setFixedWidth(32)
        self.pager_label = label("", "muted")
        self.pager = [self.pager_prev, self.pager_label, self.pager_next]
        for widget in self.pager:
            card.head.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
            widget.setVisible(False)
        card.head.setSpacing(6)
        self.legend_row = QWidget()  # what the tints of a row mean: there only while a row has one
        legend = QHBoxLayout(self.legend_row)
        legend.setContentsMargins(0, 0, 0, 0)
        self.legend_chips = {}
        for tag, kind, text in (("missing", "warn", "A value is missing"), ("invalid", "bad", "Sample has the wrong number of files")):
            chip = QLabel(text)
            chip.setProperty("chip", kind)
            self.legend_chips[tag] = chip
            legend.addWidget(chip)
        legend.addStretch(1)
        self.legend_row.hide()
        card.body.addWidget(self.legend_row)
        self.preview_grid = DataTable(self.palette_tokens, row_lines=True, elide_middle=True)
        self.preview_grid.rowSelected.connect(self._on_preview_select)
        self.preview_grid.activated.connect(lambda _row: self.side_tabs.setCurrentWidget(self.limits_page))
        card.body.addWidget(self.preview_grid, 1)
        self.preview_info = label("", "micro", wrap=True)
        card.body.addWidget(self.preview_info)
        return card

    def _show_legend(self, tags: list[str]) -> None:
        """A key to the tints only for the tints there are on the page."""
        for tag, chip in self.legend_chips.items():
            chip.setVisible(tag in tags)
        self.legend_row.setVisible(any(tag in tags for tag in self.legend_chips))

    def _build_quality_card(self) -> Card:
        """The Pre-check and the Limits in the panel at the right: a titled card as in the design, with the Criteria button in the line
        of the tabs (it is the Pre-check's, so it is there only on that tab)."""
        card = Card("Data quality & settings", dense=True)
        card.setMinimumWidth(QUALITY_MIN_WIDTH)
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("reviewTabs")
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.tabBar().setDrawBase(False)  # the tabs are pills of their own: no line under them
        self.grr_page = self._build_grr_review()
        self.side_tabs.addTab(self.grr_page, "GR&&R pre-check")  # && is how a tab shows a single &
        self.side_tabs.setTabToolTip(0, "Total Gage R&R · Screening: a quick check of the selected tests")
        self.limits_page = QWidget()
        limits = QVBoxLayout(self.limits_page)
        limits.setContentsMargins(0, 6, 0, 0)
        limits.setSpacing(5)
        self.limits_title = label("Limits", "heading")
        limits.addWidget(self.limits_title)
        self.limits_grid = DataTable(self.palette_tokens, row_height=REVIEW_ROW_HEIGHT, row_lines=True, elide_middle=True)
        limits.addWidget(self.limits_grid, 1)
        limits.addWidget(label("▲ above max   ▼ below min", "micro"))
        self.side_tabs.addTab(self.limits_page, "Limits (LSL / USL)")
        self.side_tabs.setCornerWidget(self.grr_criteria_button, Qt.Corner.TopRightCorner)
        self.side_tabs.currentChanged.connect(self._sync_criteria_button)
        bar = self.side_tabs.tabBar()
        bar.setUsesScrollButtons(False)  # the tabs and Criteria always fit: the card is never narrower than they are
        bar.ensurePolished()
        self.grr_criteria_button.ensurePolished()
        card.setMinimumWidth(max(QUALITY_MIN_WIDTH, bar.sizeHint().width() + self.grr_criteria_button.sizeHint().width() + 8 + 26))
        card.body.addWidget(self.side_tabs, 1)
        return card

    def _sync_criteria_button(self, _index: int = 0) -> None:
        self.grr_criteria_button.setVisible(self.side_tabs.currentWidget() is self.grr_page)  # the criteria are the Pre-check's

    def _build_grr_review(self) -> QWidget:
        from ..grr import quick_criteria_from_json

        self.grr_criteria = quick_criteria_from_json(self.settings.quick_check_criteria)
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 6, 0, 0)
        column.setSpacing(5)
        self.grr_criteria_button = make_button("Criteria…", self._edit_grr_criteria)
        column.addWidget(FlowRow(label("Total Gage R&R · Screening", "subhead")))
        counts = QHBoxLayout()
        counts.setSpacing(6)
        self.grr_counts = {"PASS": CountTile("PASS", "ok"), "CONDITION": CountTile("CONDITION", "warn"), "FAIL": CountTile("FAIL", "bad")}
        for tile in self.grr_counts.values():
            counts.addWidget(tile, 1)
        column.addLayout(counts)
        self.grr_grid = DataTable(self.palette_tokens, row_height=REVIEW_ROW_HEIGHT, row_lines=True, elide_middle=True)
        self.grr_grid.rowSelected.connect(self._on_grr_select)
        column.addWidget(self.grr_grid, 1)
        self.grr_summary = label("", "micro", wrap=True)
        self.grr_detail = label("Select a test to see its Study Var and calculation notes.", "micro", wrap=True)
        column.addWidget(self.grr_summary)
        column.addWidget(self.grr_detail)
        return page

    def _build_validation(self) -> QWidget:
        from .validation_workspace import ValidationWorkspace  # pulls in the statistics and the report modules

        self.validation = ValidationWorkspace(self.palette_tokens, settings=self.settings, source=self._mapping_source,
                                              save_settings=lambda: save_settings(self.settings), parent=self.content)
        self.validation.tabs.tabBar().hide()
        self.validation.tabs.currentChanged.connect(self._update_steps)
        self.validation.navigation_changed.connect(self._update_steps)
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
        if self.is_busy:
            return
        if self.workflow_route == "logs" and index < 2:
            self._show_step("select" if index == 0 else "review")
            return
        tab_index = index - 1 if self.workflow_route == "logs" else index + 1
        page = self._ensure_page("validation")
        if not page.tabs.isTabEnabled(tab_index):
            return
        self._show_workspace("validation")
        page.tabs.setCurrentIndex(tab_index)
        self._update_steps()

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
            self.set_status("Check your data, then export or continue to analysis.")
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
        """Bring one of the three places to the front: "dashboard", "mapping" or "validation". Nothing is closed, cleared or reset
        by moving between them: each keeps what it holds until its own Reset, a new scan or a new import replaces it."""
        if name == self.workspace:
            return
        if name == "dashboard":
            self.nav_bar.hide()
            self.content.setCurrentWidget(self._pages["dashboard"])
            self.workspace = "dashboard"
            self.set_status(DASHBOARD_STATUS)
        elif name == "validation":
            if self.is_busy:
                return
            page = self._ensure_page("validation")
            self._analysis_after_mapping = self.workflow_route == "logs" and self.workspace == "mapping"
            self.nav_bar.show()
            self.step_bar.show()
            self.content.setCurrentWidget(page)
            self.workspace = "validation"
            self.validation.on_show()
            self.set_status("Analysis works on a copy of the data.")
        else:
            self.workflow_route = "logs"
            self.nav_bar.show()
            self.step_bar.show()
            self.content.setCurrentWidget(self._pages["review"] if self.step == "review" else self._pages["select"])
            self.workspace = "mapping"
            self._update_steps()
            if self.step == "review":
                self.set_status("Check your data, then export or continue to analysis.")
            else:
                self.set_status("Ready." if self.scan_result else "Ready. Choose a profile and a folder, then scan.")
        self._update_canvas()
        self._update_switch()
        self._update_steps()

    # ------------------------------------------------------------------ the Dashboard's two starting points
    def start_mapping(self) -> None:
        """Map Test Logfiles: Data Mapping exactly as it is, with whatever the user already scanned and chose."""
        self.workflow_route = "logs"
        self._show_workspace("mapping")
        self._update_steps()

    def start_excel_analysis(self) -> None:
        """Analyze by Excel File: the dialog in which the person chooses the type of analysis and a workbook, sees whether the file may
        be analysed, and continues. What was chosen stays for the next time the card is used."""
        from .excel_analysis_dialog import ExcelAnalysisDialog, ExcelState

        if self.is_busy:
            return
        if self._excel_state is None:
            self._excel_state = ExcelState()
        ExcelAnalysisDialog(self, self._excel_state, self._continue_excel_analysis).present()

    def _continue_excel_analysis(self, state) -> None:
        """The file was checked and the person pressed Continue: its data are the study's, and the Analysis tab opens (nothing runs).
        The data that are already open are not read again: that takes a new file, or Check again followed by Continue."""
        validation = self._ensure_page("validation")
        imported, attribute = state.report.imported, state.category == "attribute"
        self.workflow_route = "raw"
        self._show_workspace("validation")
        if attribute and not (validation.source_var.get() == "ratings" and validation.ratings is imported):
            validation.open_ratings(imported, then_setup=True)
        elif not attribute and not (validation.source_var.get() == "file" and validation.imported is imported
                                    and validation.method_var.get() == state.method):
            validation.open_import(imported, state.path, method=state.method, then_setup=True)
        self._update_steps()

    def _update_switch(self) -> None:
        for button, name in ((self.mapping_switch, "mapping"), (self.validation_switch, "validation")):
            button.setProperty("primary", self.workspace == name)
            repolish(button)

    def _update_steps(self, *_args) -> None:
        validation = self.validation
        if self._analysis_after_mapping and validation is not None and not validation.preparing \
                and validation.tabs.isTabEnabled(validation.tabs.indexOf(validation.setup_tab)):
            self._analysis_after_mapping = False
            validation.tabs.setCurrentWidget(validation.setup_tab)
        logs = self.workflow_route == "logs"
        titles = ("Mapping", "Review & Pre-check", "Analyze", "Results", "Report") if logs else ("Configure", "Results", "Report")
        self.step_bar.set_titles(titles)
        self.workflow_breadcrumb.setText("Map test logs" if logs else "Analyze by Excel File")
        count = len(self.selected_components)
        has_data = bool(self.scan_result and self.scan_result.grouped)
        ready = has_data and count > 0
        blocked = ready and bool(self._wrong_samples())
        later = "Fix the file count first" if blocked else "Check the values, then export or analyze"
        if self.workspace == "validation" and validation is not None:
            current = max(1, validation.tabs.currentIndex()) + (1 if logs else -1)
        else:
            current = 1 if self.step == "review" else 0
        for index in range(len(titles)):
            if logs and index < 2:
                enabled = index == 0 or ready
                caption = "Folder, profile & components" if index == 0 else later if ready else "Scan, then select components"
            else:
                tab = index - 1 if logs else index + 1
                enabled = validation is not None and validation.tabs.isTabEnabled(tab)
                caption = "Configure and run analysis" if tab == 1 else "Run analysis first" if not enabled else titles[index]
            state = "current" if index == current else "complete" if index < current else "ready" if enabled else "locked"
            if logs and index == 1 and index > current and blocked:
                state = "warn"
            self.step_bar.set_step(index, state, caption)

    def _update_actions(self) -> None:
        """Reflect what is actionable and keep the running task's inputs stable."""
        if not hasattr(self, "selected_list"):
            return
        ready = not self.is_busy
        has_data = bool(self.scan_result and self.scan_result.grouped)
        highlighted = self.selected_list.selected_rows()
        controls = [
            (self.add_button, ready and bool(self.available_list.selected_rows())),
            (self.add_all_button, ready and bool(self.available_list.items())),
            (self.clear_button, ready and bool(self.selected_components)),
            (self.move_up_button, ready and bool(highlighted) and highlighted[0] > 0),  # nowhere to go from the first place
            (self.move_down_button, ready and bool(highlighted) and highlighted[-1] < len(self.selected_components) - 1),
            (self.review_button, ready and has_data and bool(self.selected_components)),
        ]
        if hasattr(self, "export_button"):
            controls += [(self.export_button, ready and has_data and bool(self.selected_components) and not self._wrong_samples()),
                         (self.back_button, ready)]  # Continue to Analysis does not depend on the data being fit to export
        for button, enabled in controls:
            button.setEnabled(enabled)
        self.available_list.setEnabled(ready)
        self.selected_list.setEnabled(ready)
        self._refresh_review_summary()
        self._update_steps()

    # ================================================================== theme
    def _style_value_filter(self) -> None:
        """Fusion draws the edge of a check box a shade darker than the window colour: in the dark theme that is the colour of the card
        itself, and an unchecked box cannot be seen. This one check box gets a lighter window colour there (its edge is then about 4:1
        against the card); in the light theme, and for every other widget, nothing changes."""
        palette = QPalette()
        if self.palette_tokens.mode == "dark":
            palette.setColor(QPalette.ColorRole.Window, QColor(self.palette_tokens.muted))
        self.value_filter.setPalette(palette)

    def _canvas_bands(self) -> tuple[int, int]:
        """What lies above and below the pages (the header, the status line): the circuit is drawn only in the space between."""
        top = self.content.mapTo(self, QPoint(0, 0)).y()
        return top, max(self.height() - top - self.content.height(), 0)

    def _update_canvas(self) -> None:
        """The Dashboard stands on the circuit board, which fills the window, behind the header and the status line too. In the light
        theme those two wear the dark theme's colours while it is on show, so that they sit on the board and not on a bar of their own.
        Nothing else changes: the other places hide the board, and the header and status line are as they always were."""
        on_dashboard = self.workspace == "dashboard"
        self.canvas.setVisible(on_dashboard)
        dark = on_dashboard and self.palette_tokens.mode == "light"
        if dark != self._chrome_dark:
            self._chrome_dark = dark
            for part in (self.header, self.statusBar()):
                part.setPalette(make_palette(DARK) if dark else QPalette())
                # a label with no colour of its own (the title) takes it from the application's palette, whatever the widget's is
                part.setStyleSheet(stylesheet(DARK) + f"QLabel {{ color: {DARK.fg}; }}" if dark else "")
        self._update_brand_logo()

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
        self._style_value_filter()
        self.dashboard.set_palette(self.palette_tokens)
        if self.validation is not None:
            self.validation.set_palette(self.palette_tokens)
        self._update_theme_button()
        self._update_canvas()
        save_settings(self.settings)

    # ================================================================== helpers
    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self.is_busy = busy
        for widget in [*self._busy_widgets, self.validation_switch, self.home_button]:
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
            self.profile_box.setToolTip("")
            return
        kind = "Excel log" if profile.get("type") == "excel" else "Text log"
        self.profile_box.setToolTip(f"{kind}  ·  files: {', '.join(get_profile_extensions(profile))}")  # what the profile reads: on hover

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
        self._grr_key = None
        self._review_row = self._preview_page = 0
        self.reviewed_duplicates = set()
        self._update_scan_badge()

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
        self._grr_key = None
        self._review_row = 0
        self.selected_components = []
        self.reviewed_duplicates = set()
        for value in (self.samples_value, self.files_value, self.components_value):
            value.setText("–")
        self.verdict.setText("No scan yet.")
        self.verdict.setProperty("chip", None)
        self.verdict.setProperty("role", "muted")
        repolish(self.verdict)
        self._update_scan_badge()
        self.details_button.setEnabled(False)
        self.search.setText("")
        self.value_filter.setChecked(False)
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
        view = available_view(components, self.selected_components, self.search.text(), numeric_only=self.value_filter.isChecked(),
                              limits=self.limits)
        self.available_list.set_items(view.items, values=[limit_texts(self.limits, c) for c in view.items], empty_text=view.empty_text)
        if reset_view:
            self.available_list.reset_view()
        self.available_info.setText(view.info)
        self.available_info.setVisible(bool(view.info))  # nothing to count before a scan
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
        self._grr_key = None  # the chosen occurrences change values
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
        """The ↑ ↓ below the list and Alt+↑ / Alt+↓: the highlighted components a place up or down, and they stay highlighted."""
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
        self._refresh_grr()
        self._update_actions()

    def _refresh_review_summary(self) -> None:
        """The state of the data beside the title. Read from what is already known: the scan, the choice and the file count;
        nothing is worked out again."""
        if not hasattr(self, "review_badge"):
            return
        if not self._review_ready():
            set_badge(self.review_badge, "Nothing to review")
        elif self._wrong_samples():
            set_badge(self.review_badge, "File count needs fixing", "warn")
        else:
            set_badge(self.review_badge, "Dataset ready", "ok")

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
                                        empty_text="Calculating the GRR pre-check…", stretch=0, max_width=GRR_NAME_WIDTH)
                self.grr_summary.setText("")
                for tile in self.grr_counts.values():
                    tile.set_count(None)
                return
            self._grr_results = summarize_grr(result.grouped, components, repeats) if result and result.grouped else []
            self._grr_key = key
        rows, tags = [], {}
        tally = dict.fromkeys(self.grr_counts, 0)  # how many tests are PASS, CONDITION and FAIL, for the tiles above the table
        for index, entry in enumerate(self._grr_results):
            status = quick_check(entry, self.grr_criteria)
            cells = [f"{value:.2f}" if value is not None else "N/A" for value in (entry.percent_study_var, entry.percent_tolerance)]
            cells.append(str(entry.ndc) if entry.ndc is not None else "N/A")
            for column, each in enumerate((status.study, status.tolerance, status.ndc, status.overall), start=1):
                tags[index, column] = levels[each]
            rows.append((entry.component, *cells, words[status.overall]))
            if words[status.overall] in tally:
                tally[words[status.overall]] += 1
        for name, tile in self.grr_counts.items():
            tile.set_count(tally[name] if rows else None)
        self.grr_grid.set_table(["Test", "%Study Var", "%SV/Tol", "NDC", "Result"], rows, aligns=["w", "e", "e", "center", "center"],
                                empty_text="Select tests to calculate their GRR pre-check.", cell_tags=tags, stretch=0,
                                max_width=GRR_NAME_WIDTH)
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
        facts = [entry.component, f"{entry.parts} samples × {repeat_text} repeats"]  # on one line: the name, the design, the Study Var
        if entry.study_var is not None:
            variation = f"{entry.study_var:.2e}" if 0 < abs(entry.study_var) < 0.01 else f"{entry.study_var:.2f}"
            facts.append(f"Study Var (6 × SD): {variation} {entry.unit}".rstrip())
        lines = ["  ·  ".join(facts)]
        if entry.note:
            lines.append(entry.note)
        self.grr_detail.setText("\n".join(lines))
        self._grr_note = bool(entry.note)  # how this test was judged is never left out of a short window
        self._sync_review_extras()

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
        self._show_legend(table.tags)
        self._sync_review_extras()
        set_badge(self.review_count, table.count_text.strip("()"))  # "(30 rows)" is "30 rows" on a badge
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
            self.limits_grid.set_table(headings, limit_overview(components, self.limits), aligns=aligns, stretch=0, max_width=260)
            return
        row = self._preview_rows[self._review_row]
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

        self._pending[name] = key
        self.tasks.run(lambda _report: work(), on_success=done, on_error=failed)

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
