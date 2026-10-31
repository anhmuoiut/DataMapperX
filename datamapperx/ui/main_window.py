"""The main DataMapperX window: Data Mapping (Select, then Review & Export) and, beside it, Validation & Reports."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import access, updater
from .._version import __version__
from ..config import (
    APP_CREDIT,
    APP_TITLE,
    DEFAULT_OUTPUT_FILE,
)
from ..exporter import ExportRow, generate_excel, summarize_limits
from ..grr import GrrResult, summarize_grr
from ..models import ScanResult
from ..paths import is_frozen, log_path, resource_path, user_data_dir
from ..profiles import get_profile_extensions, load_profiles
from ..reporting import describe_empty_scan, full_report, summarize_scan
from ..review import ReviewSummary, summarize_review
from ..sampling import suggest_profile
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
from .access_dialog import AccessDialog
from .controls import ActionList, ChipRow, Column, DataGrid, StepBar
from .dialogs import AboutDialog, ExportDoneDialog, ReportDialog, open_path, set_window_icon
from .duplicate_dialog import DuplicateDialog
from .profile_dialog import ProfileManager
from .tasks import TaskRunner
from .theme import Palette, apply_theme, resolve_mode, work_area
from .update_dialog import UpdateDialog
from .validation_workspace import MappingSource, ValidationWorkspace

logger = logging.getLogger(__name__)

CARD_PADDING = 12

SHORTCUTS = (
    ("Ctrl+O", "Choose the source folder"),
    ("Ctrl+Enter  /  F5", "Scan logs"),
    ("Esc", "Cancel a running scan"),
    ("Ctrl+E", "Go to Review & Export, then export to Excel"),
    ("Double-click / Enter", "Add or remove the highlighted component"),
    ("Ctrl+A", "Select every component in a list"),
    ("Delete", "Remove the highlighted selected components"),
)


ENFORCE_ACCESS_ENV = "DATAMAPPERX_ENFORCE_ACCESS"  # set it to run the owner's off switch from a source checkout too


class MainWindow(tk.Tk):
    def __init__(self, *, background_checks: bool = True) -> None:
        """``background_checks=False`` keeps the window off the network (tests and the build's self-test)."""
        super().__init__()
        self.withdraw()
        self.settings: Settings = load_settings()
        self.profiles = load_profiles()
        self.tasks = TaskRunner(self)

        self.scan_result: ScanResult | None = None
        self.limits: dict[str, dict[str, str]] = {}  # min / max / unit of every scanned component, as in the Excel file
        self.selected_components: list[str] = []
        self.reviewed_duplicates: set[str] = set()
        self.is_busy = False
        self._cancel = threading.Event()
        self.step = "select"  # "select" or "review"
        self.workspace = "mapping"  # "mapping" (the two steps) or "validation"
        self.validation: ValidationWorkspace | None = None  # built the first time it is opened
        self._data_serial = 0  # moves whenever the scanned data (or the choice among duplicates) changes
        self._scan_serial = 0  # moves with every new scan (or reset), never for a duplicate choice
        self._scan_description = ""
        self._review_built = False  # the review page is built when first needed, so the window opens sooner
        self._review_row = 0  # the preview row whose values the limits panel shows
        self._preview_rows: list[ExportRow] = []
        self._preview_components: tuple[str, ...] = ()
        self._limit_components: tuple[str, ...] | None = None
        self._limit_columns: list[Column] = []
        self._swatches: list[tuple[tk.Frame, str]] = []
        self._summary: ReviewSummary | None = None
        self._summary_key: tuple | None = None
        self._grr_results: list[GrrResult] = []
        self._grr_key: tuple | None = None
        self._preview_job: str | None = None
        self._preview_page = 0
        self._progress_determinate = False
        self._update_info: updater.UpdateInfo | None = None
        self._access_dialog: AccessDialog | None = None
        # The owner's off switch applies to the program people were given, not to a developer's source checkout.
        self._enforce_access = background_checks and (is_frozen() or bool(os.environ.get(ENFORCE_ACCESS_ENV)))

        self.title(APP_TITLE)
        set_window_icon(self)
        self.palette: Palette = apply_theme(self, self.settings.theme)
        self._setup_geometry()

        self.folder_var = tk.StringVar(value=self.settings.last_folder)
        self.status_var = tk.StringVar(value="Ready. Choose a profile and a folder, then scan.")
        self.profile_var = tk.StringVar()
        self.expected_var = tk.StringVar(value=self.settings.expected_samples)
        self.repeats_var = tk.StringVar(value=self.settings.repeats)
        self.search_var = tk.StringVar()
        self.dark_var = tk.BooleanVar(value=resolve_mode(self.settings.theme) == "dark")
        self.auto_update_var = tk.BooleanVar(value=self.settings.check_updates)
        self.hint_var = tk.StringVar()
        self.samples_var = tk.StringVar(value="–")
        self.files_var = tk.StringVar(value="–")
        self.components_var = tk.StringVar(value="–")
        self.verdict_var = tk.StringVar(value="No scan yet.")
        self.available_info_var = tk.StringVar()
        self.selected_info_var = tk.StringVar()
        self.preview_info_var = tk.StringVar()
        self.pager_var = tk.StringVar()
        self.review_count_var = tk.StringVar()
        self.review_row_var = tk.StringVar()
        self.limits_title_var = tk.StringVar(value="Limits")
        self.theme_text_var = tk.StringVar(value=self._theme_button_text())

        if self.settings.last_profile in self.profiles:
            self.profile_var.set(self.settings.last_profile)
        elif self.profiles:
            self.profile_var.set(next(iter(self.profiles)))

        self._build_ui()
        self._bind_shortcuts()
        self._update_profile_hint()
        self._refresh_lists()

        self.search_var.trace_add("write", lambda *_: self._refresh_available(reset_view=True))
        self.repeats_var.trace_add("write", lambda *_: (self._schedule_preview(), self._notify_validation()))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.report_callback_exception = self._on_callback_error  # type: ignore[method-assign]

        self.after_idle(self._ensure_review_page)  # once the window is on screen
        self.deiconify()
        if self._enforce_access:
            now = time.time()
            access.begin(self.settings, now)
            block = access.current_block(self.settings, now)
            if block:  # a copy that was told to stop stays stopped, even before the network answers
                self.after(150, lambda: self._apply_access(block))
        if background_checks:
            self.after(1500, self._start_checks)
        self.after(5000, updater.cleanup_update_leftovers)

    # ------------------------------------------------------------------ window basics
    def _setup_geometry(self) -> None:
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.settings.geometry or "")
        restored = tuple(int(value) for value in match.groups()) if match else None
        anchor = (restored[2] + 80, restored[3] + 40) if restored else None
        left, top, right, bottom = work_area(self, anchor)
        # Reserve native window borders/title bar; the monitor work area already excludes the taskbar.
        max_width, max_height = max(1, right - left - 24), max(1, bottom - top - 48)
        min_width, min_height = min(1000, max_width), min(680, max_height)
        self.minsize(min_width, min_height)
        if restored:
            width, height, x, y = restored
        else:
            width = min(1360, max(1000, int((right - left) * 0.88)))
            height = min(880, max(680, int((bottom - top) * 0.86)))
            x, y = left + (right - left - width) // 2, top + 16
        width = max(min_width, min(width, max_width))
        height = max(min_height, min(height, max_height))
        x = max(left + 8, min(x, right - width - 16))
        y = max(top + 8, min(y, bottom - height - 40))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_close(self) -> None:
        # A scan still running would keep the (windowless) process alive until it finished reading every file.
        self._cancel.set()
        self._remember_inputs()
        self.settings.geometry = self.geometry()
        save_settings(self.settings)
        self.destroy()

    def _on_callback_error(self, exc_type, exc_value, exc_tb) -> None:
        logger.error("Unhandled error in UI callback", exc_info=(exc_type, exc_value, exc_tb))
        messagebox.showerror(
            APP_TITLE,
            f"Something unexpected went wrong:\n\n{exc_value}\n\nDetails were written to:\n{log_path()}",
            parent=self,
        )

    def _remember_inputs(self) -> None:
        s = self.settings
        s.last_folder = self.folder_var.get().strip()
        s.last_profile = self.profile_var.get()
        s.expected_samples = self.expected_var.get().strip() or s.expected_samples
        s.repeats = self.repeats_var.get().strip() or s.repeats
        s.check_updates = bool(self.auto_update_var.get())

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-o>", lambda _e: self._in_mapping(self.pick_folder))
        self.bind("<Control-Return>", lambda _e: self._in_mapping(self.scan_logs))
        self.bind("<F5>", lambda _e: self._in_mapping(self.scan_logs))
        self.bind("<Control-e>", lambda _e: self._export_shortcut())
        self.bind("<Escape>", lambda _e: self._cancel_scan() if self.is_busy else None)

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

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._build_header()
        self._build_banner()
        nav = ttk.Frame(self)
        nav.grid(row=2, column=0, sticky="ew", padx=18, pady=(2, 8))
        nav.columnconfigure(1, weight=1)
        switch = ttk.Frame(nav)
        switch.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.mapping_switch = ttk.Button(switch, text="Data Mapping", command=lambda: self._show_workspace("mapping"))
        self.mapping_switch.pack(side="left", padx=(0, 6))
        self.validation_switch = ttk.Button(switch, text="Validation & Reports", command=lambda: self._show_workspace("validation"))
        self.validation_switch.pack(side="left")
        self.step_bar = StepBar(nav, self.palette, ("Select", "Review & Export"), self._on_step_clicked)
        self.step_bar.grid(row=0, column=1, sticky="ew")

        self.content_frame = ttk.Frame(self)
        self.content_frame.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 0))
        self.content_frame.rowconfigure(0, weight=1)
        self.content_frame.columnconfigure(0, weight=1)

        # Step 1: the Source card and the two component lists.
        self.select_page = ttk.Frame(self.content_frame)
        self.select_page.grid(row=0, column=0, sticky="nsew")
        self.select_page.rowconfigure(0, weight=1)
        self.select_page.columnconfigure(0, minsize=300)
        self.select_page.columnconfigure(1, weight=1)
        self._build_workspace(self.select_page)
        lists = ttk.Frame(self.select_page)
        lists.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        lists.rowconfigure(0, weight=1)
        lists.columnconfigure(0, weight=1, uniform="lists")
        lists.columnconfigure(1, weight=1, uniform="lists")
        self._build_available(lists)
        self._build_selected(lists)
        self._busy_widgets.append(self.validation_switch)

        # Step 2 is built the first time it is needed (see _ensure_review_page).
        self.review_page = ttk.Frame(self.content_frame)
        self.review_page.grid(row=0, column=0, sticky="nsew")
        self.review_page.grid_remove()
        # Validation & Reports is built the first time it is opened (see _ensure_validation_page).
        self.validation_page = ttk.Frame(self.content_frame)
        self.validation_page.grid(row=0, column=0, sticky="nsew")
        self.validation_page.rowconfigure(0, weight=1)
        self.validation_page.columnconfigure(0, weight=1)
        self.validation_page.grid_remove()
        self._build_statusbar()
        self._update_steps()
        self._update_switch()

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(20, 10, 20, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self._icon_image = None
        icon = resource_path("assets", "DataMapperX.png")
        if icon.exists():
            try:
                image = tk.PhotoImage(file=str(icon))
                self._icon_image = image.subsample(max(1, image.height() // 32))
                ttk.Label(header, image=self._icon_image).grid(row=0, column=0, rowspan=2, padx=(0, 12))
            except tk.TclError:
                logger.debug("Could not load header icon", exc_info=True)
        self._brand_logos = self._load_brand_logos()
        self._brand_label = ttk.Label(header)
        self._brand_label.place(relx=0.5, rely=0.5, anchor="center")  # centred on the window, not on the free gap
        self._update_brand_logo()
        ttk.Label(header, text=APP_TITLE, style="Brand.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="TE - Solar Edge", style="Subtitle.TLabel").grid(row=1, column=1, sticky="w")
        right = ttk.Frame(header)
        right.grid(row=0, column=2, rowspan=2, sticky="e")
        self.theme_button = ttk.Button(right, textvariable=self.theme_text_var, command=self._toggle_theme)
        self.theme_button.pack(side="left", padx=(0, 8))
        menu_button = ttk.Menubutton(right, text="Help")
        menu = tk.Menu(menu_button, tearoff=False)
        menu.add_command(label="Check for updates…", command=lambda: self._check_for_update(manual=True))
        menu.add_checkbutton(label="Tell me about new versions", variable=self.auto_update_var, command=self._remember_inputs)
        menu.add_separator()
        menu.add_command(label="Keyboard shortcuts", command=self._show_shortcuts)
        menu.add_command(label="Open data folder", command=lambda: open_path(user_data_dir()))
        menu.add_command(label="Open log file", command=lambda: open_path(log_path()))
        menu.add_separator()
        menu.add_command(label=f"About {APP_TITLE}", command=lambda: AboutDialog(self))
        menu_button.configure(menu=menu)
        menu_button.pack(side="left")
        self.help_button = menu_button

    def _load_brand_logos(self) -> dict[str, tk.PhotoImage]:
        """The company logo, one picture per theme (white letters on dark). Missing files simply mean no logo."""
        height = 76 if self.winfo_fpixels("1i") / 96 >= 1.5 else 38  # a larger picture on high-DPI screens
        logos: dict[str, tk.PhotoImage] = {}
        for mode in ("light", "dark"):
            path = resource_path("assets", f"Jabil-Logo-{mode}-{height}.png")
            if path.exists():
                try:
                    logos[mode] = tk.PhotoImage(file=str(path))
                except tk.TclError:
                    logger.debug("Could not load %s", path, exc_info=True)
        return logos

    def _update_brand_logo(self) -> None:
        image = self._brand_logos.get(self.palette.mode)
        if image is None:
            self._brand_label.place_forget()
        else:
            self._brand_label.configure(image=image)
            self._brand_label.place(relx=0.5, rely=0.5, anchor="center")

    def _build_banner(self) -> None:
        self.banner = ttk.Frame(self, style="Banner.TFrame", padding=(16, 8))
        self.banner.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        self.banner.columnconfigure(0, weight=1)
        self.banner_label = ttk.Label(self.banner, style="Banner.TLabel", wraplength=480)
        self.banner_label.grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(self.banner, style="Banner.TFrame")
        buttons.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ttk.Button(buttons, text="Update now", style="Accent.TButton", command=self._open_update_dialog).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Skip this version", command=lambda: self.skip_update(self._update_info.version if self._update_info else "")).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="×", width=3, style="Icon.TButton", command=self.hide_update_banner).pack(side="left")
        self.banner.grid_remove()

    def _card(self, parent: tk.Misc, title: str, column: int, padx: tuple[int, int]) -> ttk.Frame:
        card = ttk.Frame(parent, style="Surface.TFrame", padding=CARD_PADDING)
        card.grid(row=0, column=column, sticky="nsew", padx=padx, pady=(0, 6))
        ttk.Label(card, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        return card

    def _build_workspace(self, parent: tk.Misc) -> None:
        card = self.source_card = self._card(parent, "01  Source", 0, (0, 0))
        card.columnconfigure(0, weight=1)
        head = ttk.Frame(card, style="Surface.TFrame")
        head.grid(row=1, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Log profile", style="Surface.TLabel").grid(row=0, column=0, sticky="w")
        self.manage_button = ttk.Button(head, text="Manage…", command=self.manage_profiles)
        self.manage_button.grid(row=0, column=1, sticky="e")
        self.profile_combo = ttk.Combobox(card, width=24, textvariable=self.profile_var, values=list(self.profiles), state="readonly")
        self.profile_combo.grid(row=2, column=0, sticky="ew", pady=(4, 3))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_profile_changed())
        self.hint_label = ttk.Label(card, textvariable=self.hint_var, style="SurfaceHint.TLabel", wraplength=270, justify="left")
        self.hint_label.grid(row=3, column=0, sticky="w", pady=(0, 8))
        ttk.Label(card, text="Source folder", style="Surface.TLabel").grid(row=4, column=0, sticky="w")
        folder_row = ttk.Frame(card, style="Surface.TFrame")
        folder_row.grid(row=5, column=0, sticky="ew", pady=(4, 8))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, width=18, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.folder_entry.bind("<Return>", lambda _e: self.scan_logs())
        self.browse_button = ttk.Button(folder_row, text="Browse…", command=self.pick_folder)
        self.browse_button.grid(row=0, column=1)
        counts = ttk.Frame(card, style="Surface.TFrame")
        counts.grid(row=6, column=0, sticky="ew")
        counts.columnconfigure(0, weight=1, uniform="counts")
        counts.columnconfigure(1, weight=1, uniform="counts")
        ttk.Label(counts, text="Expected samples", style="SurfaceHint.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(counts, text="Files per sample", style="SurfaceHint.TLabel").grid(row=0, column=1, sticky="w")
        self.expected_spin = ttk.Spinbox(counts, from_=1, to=9999, width=7, textvariable=self.expected_var)
        self.expected_spin.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 0))
        self.repeats_spin = ttk.Spinbox(counts, from_=1, to=999, width=7, textvariable=self.repeats_var)
        self.repeats_spin.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        actions = ttk.Frame(card, style="Surface.TFrame")
        actions.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.scan_button = ttk.Button(actions, text="Scan logs", style="Accent.TButton", command=self.scan_logs)
        self.scan_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel_scan, state="disabled")
        self.cancel_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.reset_button = ttk.Button(actions, text="Reset", command=self.reset_workflow)
        self.reset_button.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        ttk.Separator(card, style="Surface.TSeparator").grid(row=8, column=0, sticky="ew", pady=9)
        stats = ttk.Frame(card, style="Surface.TFrame")
        stats.grid(row=9, column=0, sticky="ew")
        for col, (caption, var) in enumerate((("Samples", self.samples_var), ("Files", self.files_var), ("Fields", self.components_var))):
            stats.columnconfigure(col, weight=1, uniform="stats")
            block = ttk.Frame(stats, style="Surface.TFrame")
            block.grid(row=0, column=col, sticky="w")
            ttk.Label(block, textvariable=var, style="Metric.TLabel").pack(anchor="w")
            ttk.Label(block, text=caption, style="MetricCaption.TLabel").pack(anchor="w")
        self.verdict_label = ttk.Label(card, textvariable=self.verdict_var, style="SurfaceMuted.TLabel", wraplength=270, justify="left")
        self.verdict_label.grid(row=10, column=0, sticky="ew", pady=(8, 6))
        self.details_button = ttk.Button(card, text="View scan details", command=self._show_scan_details, state="disabled")
        self.details_button.grid(row=11, column=0, sticky="ew")
        card.rowconfigure(12, weight=1)
        ttk.Separator(card, style="Surface.TSeparator").grid(row=13, column=0, sticky="ew", pady=(8, 6))
        about = ttk.Frame(card, style="Surface.TFrame")  # bottom left: version, then who made it, on one line
        about.grid(row=14, column=0, sticky="w")
        self.version_label = ttk.Label(about, text=f"Version {__version__}", style="SurfaceHint.TLabel")
        self.version_label.pack(side="left")
        ttk.Label(about, text="·", style="SurfaceHint.TLabel").pack(side="left", padx=6)
        self.credit_label = ttk.Label(about, text=APP_CREDIT, style="SurfaceHint.TLabel")
        self.credit_label.pack(side="left")
        self._busy_widgets: list[ttk.Widget] = [
            self.manage_button, self.browse_button, self.scan_button, self.reset_button,
            self.expected_spin, self.repeats_spin, self.folder_entry,
        ]

    def _build_available(self, parent: tk.Misc) -> None:
        card = self._card(parent, "02  Available components", 0, (0, 6))
        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(card, width=18, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.search_hint = ttk.Label(self.search_entry, text="Search components…", style="EntryHint.TLabel")
        self.search_hint.place(x=10, rely=0.5, anchor="w")
        self.search_hint.bind("<Button-1>", lambda _e: self.search_entry.focus_set())
        self.available_list = ActionList(
            card, self.palette, action="add", on_action=self._add_at, on_activate=self.add_components,
            on_select=self._update_actions, name_heading="Component", value_headings=("Min", "Max"),
        )
        self.available_list.grid(row=2, column=0, sticky="nsew")
        footer = ttk.Frame(card, style="Surface.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, textvariable=self.available_info_var, style="SurfaceHint.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.add_all_button = ttk.Button(footer, text="Add all shown", command=self.add_all_shown)
        self.add_all_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.add_button = ttk.Button(footer, text="Add →", command=self.add_components)
        self.add_button.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        self._busy_widgets.append(self.search_entry)

    def _build_selected(self, parent: tk.Misc) -> None:
        card = self._card(parent, "Selected for export", 1, (6, 0))
        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Top to bottom = Excel column order", style="SurfaceHint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.selected_list = ActionList(
            card, self.palette, action="remove", on_action=self._remove_at, on_activate=self.remove_components,
            on_delete=self.remove_components, on_select=self._update_actions, numbered=True,
        )
        self.selected_list.grid(row=2, column=0, sticky="nsew")
        footer = ttk.Frame(card, style="Surface.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.selected_info_var, style="SurfaceHint.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        buttons = ttk.Frame(footer, style="Surface.TFrame")
        buttons.grid(row=1, column=0, sticky="ew")
        buttons.columnconfigure(2, weight=1)
        self.move_up_button = ttk.Button(buttons, text="↑", width=3, style="Icon.TButton", command=lambda: self.move_selected(-1))
        self.move_up_button.grid(row=0, column=0, padx=(0, 4))
        self.move_down_button = ttk.Button(buttons, text="↓", width=3, style="Icon.TButton", command=lambda: self.move_selected(1))
        self.move_down_button.grid(row=0, column=1)
        self.clear_button = ttk.Button(buttons, text="Clear", command=self.clear_selected)
        self.clear_button.grid(row=0, column=3, sticky="e")
        self.review_button = ttk.Button(footer, text="Review & Export  →", style="Accent.TButton", command=lambda: self._show_step("review"))
        self.review_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_review(self, page: ttk.Frame) -> None:
        """Step 2: the data as it will be exported, the limits beside it, and the checks with the Export button."""
        outer_page = page
        outer_page.rowconfigure(0, weight=1)
        outer_page.columnconfigure(0, weight=1)
        page = ttk.Frame(outer_page)
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, minsize=480)

        card = ttk.Frame(page, style="Surface.TFrame", padding=CARD_PADDING)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        card.rowconfigure(3, weight=1)
        card.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(card, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Review your data", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, textvariable=self.review_count_var, style="SurfaceMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.pager = ttk.Frame(toolbar, style="Surface.TFrame")
        self.pager.grid(row=0, column=2, padx=(12, 0))
        self.pager_prev = ttk.Button(self.pager, text="‹", width=3, style="Icon.TButton", command=lambda: self._page_preview(-1))
        self.pager_prev.pack(side="left")
        ttk.Label(self.pager, textvariable=self.pager_var, style="SurfaceHint.TLabel").pack(side="left", padx=10)
        self.pager_next = ttk.Button(self.pager, text="›", width=3, style="Icon.TButton", command=lambda: self._page_preview(1))
        self.pager_next.pack(side="left")
        self.pager.grid_remove()
        self.preview_hint = ttk.Label(
            card, style="SurfaceHint.TLabel", wraplength=500, justify="left",
            text="Same rows and column order as your Excel file. Click a row to compare its values with the limits.",
        )
        self.preview_hint.grid(row=1, column=0, sticky="w", pady=(4, 6))
        legend = ttk.Frame(card, style="Surface.TFrame")
        legend.grid(row=2, column=0, sticky="w", pady=(0, 8))
        for column, (level, text) in enumerate((("warn", "A value is missing"), ("bad", "Sample has the wrong number of files"))):
            swatch = tk.Frame(legend, width=12, height=12, highlightthickness=1)
            swatch.grid(row=0, column=column * 2, padx=(0 if column == 0 else 16, 6))
            ttk.Label(legend, text=text, style="SurfaceHint.TLabel").grid(row=0, column=column * 2 + 1)
            self._swatches.append((swatch, level))
        self.preview_grid = DataGrid(
            card, self.palette, on_select=self._on_preview_select,
            on_activate=lambda _index: self.review_side_tabs.select(self.limits_page),
        )
        self.preview_grid.grid(row=3, column=0, sticky="nsew")
        self.preview_info_label = ttk.Label(card, textvariable=self.preview_info_var, style="SurfaceHint.TLabel", wraplength=500, justify="left")
        self.preview_info_label.grid(row=4, column=0, sticky="w", pady=(8, 0))
        card.bind("<Configure>", lambda event: (
            self.preview_hint.configure(wraplength=max(180, event.width - 32)),
            self.preview_info_label.configure(wraplength=max(180, event.width - 32)),
        ))

        self.review_side_tabs = ttk.Notebook(page)
        self.review_side_tabs.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        self.grr_page = ttk.Frame(self.review_side_tabs, style="Surface.TFrame", padding=CARD_PADDING)
        self.review_side_tabs.add(self.grr_page, text="GRR pre-check")
        self._build_grr_review(self.grr_page)

        side = ttk.Frame(self.review_side_tabs, style="Surface.TFrame", padding=CARD_PADDING)
        self.limits_page = side
        self.review_side_tabs.add(side, text="Limits")
        side.rowconfigure(2, weight=1)
        side.columnconfigure(0, weight=1)
        ttk.Label(side, textvariable=self.limits_title_var, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(side, textvariable=self.review_row_var, style="Pick.TLabel").grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.limits_grid = DataGrid(side, self.palette, font_size=9, row_height=26, padding=8)
        self.limits_grid.grid(row=2, column=0, sticky="nsew")
        self.limits_hint = ttk.Label(
            side, style="SurfaceHint.TLabel", wraplength=380, justify="left",
            text="▲ above max   ▼ below min   – nothing there. Min, max and unit are the limits the Excel file lists "
                 "beside the data.",
        )
        self.limits_hint.grid(row=3, column=0, sticky="w", pady=(8, 0))
        side.bind("<Configure>", lambda event: self.limits_hint.configure(wraplength=max(180, event.width - 32)))

        bar = ttk.Frame(outer_page, style="Surface.TFrame", padding=(14, 10))
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        bar.columnconfigure(0, weight=1)
        self.check_chips = ChipRow(bar, self.palette)
        self.check_chips.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        buttons = ttk.Frame(bar, style="Surface.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.back_button = ttk.Button(buttons, text="←  Back", command=lambda: self._show_step("select"))
        self.back_button.pack(side="left", padx=(0, 8))
        self.validate_button = ttk.Button(buttons, text="Validation & Reports  →", command=lambda: self._show_workspace("validation"))
        self.validate_button.pack(side="left", padx=(0, 8))
        self.export_button = ttk.Button(buttons, text="Export Excel…", style="Accent.TButton", command=self.export_excel)
        self.export_button.pack(side="left")
        self._busy_widgets += [self.back_button, self.validate_button, self.export_button]

    def _build_grr_review(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        ttk.Label(page, text="Total Gage R&R", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        method = ttk.Label(
            page, style="SurfaceHint.TLabel", justify="left", wraplength=430,
            text="A quick check before you export: one-way ANOVA by SN, 6 × SD, each file a repeat, one operator/fixture.\n"
                 "The colours compare the figures with reference thresholds. They are not a statistical conclusion; "
                 "Minitab reports the figures without a verdict.",
        )
        method.grid(row=1, column=0, sticky="w", pady=(6, 8))
        legend = ttk.Frame(page, style="Surface.TFrame")
        legend.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.grr_legend_tiles = []
        for column, (level, title, bounds) in enumerate((
            ("pass", "PASS", "≤10%\nNDC ≥5"),
            ("caution", "CONDITION", ">10% to 30%\nNDC: —"),
            ("fail", "FAIL", ">30%\nNDC <5"),
        )):
            legend.columnconfigure(column, weight=1, uniform="grr_status")
            tile = tk.Frame(legend, highlightthickness=1, padx=4, pady=5)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0))
            title_label = tk.Label(tile, text=title, font=("Segoe UI Semibold", 9))
            title_label.pack(fill="x")
            bounds_label = tk.Label(tile, text=bounds, font=("Segoe UI", 9), justify="center")
            bounds_label.pack(fill="x")
            self.grr_legend_tiles.append((tile, title_label, bounds_label, level))
        self.grr_grid = DataGrid(page, self.palette, font_size=9, row_height=30, padding=8, on_select=self._on_grr_select)
        self.grr_grid.grid(row=3, column=0, sticky="nsew")
        self.grr_summary_var = tk.StringVar()
        summary = ttk.Label(page, textvariable=self.grr_summary_var, style="SurfaceHint.TLabel", justify="left", wraplength=430)
        summary.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.grr_detail_var = tk.StringVar(value="Select a test to see its Study Var and calculation notes.")
        detail = ttk.Label(page, textvariable=self.grr_detail_var, style="SurfaceHint.TLabel", justify="left", wraplength=430)
        detail.grid(row=5, column=0, sticky="w", pady=(8, 0))
        page.bind("<Configure>", lambda event: [
            label.configure(wraplength=max(180, event.width - 32)) for label in (method, summary, detail)
        ])

    def _ensure_review_page(self) -> None:
        """Build step 2 the first time it is needed (shortly after start-up, or when something asks for it)."""
        if self._review_built:
            return
        self._review_built = True
        self._build_review(self.review_page)
        self._apply_tag_colors()
        self._update_actions()

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(20, 8, 20, 10))
        bar.grid(row=4, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(bar, textvariable=self.status_var, style="Hint.TLabel", wraplength=780, justify="left")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, length=160, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.progress.grid_remove()
        bar.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(250, event.width - 230)))

    # ------------------------------------------------------------------ steps
    def _review_ready(self) -> bool:
        return bool(self.scan_result and self.scan_result.grouped and self.selected_components)

    def _wrong_samples(self) -> list[str]:
        """Samples that do not have the expected number of files (the export refuses to run while there are any)."""
        repeats = self._optional_int(self.repeats_var)
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
            self._ensure_review_page()
            self.select_page.grid_remove()
            self.review_page.grid()
            self.step = "review"
            self._refresh_review()
            self.review_side_tabs.select(self.grr_page)
            self.preview_grid.focus_body()
            self.set_status("Preview your data, then export Excel. Validation & Reports is optional and works on a copy of the data.")
        else:
            if self._review_built:
                self.review_page.grid_remove()
            self.select_page.grid()
            self.step = "select"
            self._update_steps()

    def _mapping_source(self) -> MappingSource | None:
        """What Validation & Reports may analyse: the scan and the components chosen in Data Mapping."""
        result = self.scan_result
        if result is None or not result.grouped or not self.selected_components:
            return None
        return MappingSource(result.grouped, tuple(self.selected_components), self._optional_int(self.repeats_var),
                             self._data_serial, self._scan_description, self._scan_serial)

    def _data_changed(self) -> None:
        """The scanned data, the chosen components or the choice among duplicates changed."""
        self._data_serial += 1
        self._notify_validation()

    def _notify_validation(self) -> None:
        if self.validation is not None:
            self.validation.source_changed()

    def _ensure_validation_page(self) -> None:
        if self.validation is None:
            self.validation = ValidationWorkspace(self.validation_page, self.palette, settings=self.settings,
                                                  save_settings=lambda: save_settings(self.settings), source=self._mapping_source)
            self.validation.grid(row=0, column=0, sticky="nsew")
            self.validation.set_palette(self.palette)

    def _show_workspace(self, name: str) -> None:
        if name == self.workspace:
            return
        if name == "validation":
            if self.is_busy:
                return
            self._ensure_validation_page()
            self.select_page.grid_remove()
            if self._review_built:
                self.review_page.grid_remove()
            self.step_bar.grid_remove()
            self.validation_page.grid()
            self.workspace = "validation"
            self.validation.on_show()
            self.set_status("Validation & Reports works on a copy of the data. Data Mapping and the Excel export are not affected.")
        else:
            self.validation_page.grid_remove()
            self.step_bar.grid()
            (self.review_page if self.step == "review" and self._review_built else self.select_page).grid()
            self.workspace = "mapping"
            self._update_steps()
            self.set_status("Ready." if self.step == "select" else "Preview your data, then export Excel.")
        self._update_switch()

    def _update_switch(self) -> None:
        self.mapping_switch.configure(style="Accent.TButton" if self.workspace == "mapping" else "TButton")
        self.validation_switch.configure(style="Accent.TButton" if self.workspace == "validation" else "TButton")

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
        ready = not self.is_busy
        has_data = bool(self.scan_result and self.scan_result.grouped)
        selected = self.selected_list.selected_indices()
        controls = [
            (self.add_button, ready and bool(self.available_list.selected_items())),
            (self.add_all_button, ready and bool(self.available_list.items())),
            (self.clear_button, ready and bool(self.selected_components)),
            (self.move_up_button, ready and bool(selected) and selected[0] > 0),
            (self.move_down_button, ready and bool(selected) and selected[-1] < len(self.selected_components) - 1),
            (self.review_button, ready and has_data and bool(self.selected_components)),
        ]
        if self._review_built:
            controls += [
                (self.export_button, ready and has_data and bool(self.selected_components) and not self._wrong_samples()),
                (self.back_button, ready),
            ]
        for button, enabled in controls:
            button.configure(state="normal" if enabled else "disabled")
        self.available_list.set_enabled(ready)
        self.selected_list.set_enabled(ready)
        self._update_steps()

    def _apply_tag_colors(self) -> None:
        if not self._review_built:
            return
        p = self.palette
        self.preview_grid.set_palette(p)
        self.limits_grid.set_palette(p)
        self.grr_grid.set_palette(p)
        legend_colors = {
            "pass": (p.ok_bg, p.ok_line, p.ok), "caution": (p.warn_bg, p.warn_line, p.warn),
            "fail": (p.bad_bg, p.bad_line, p.danger),
        }
        for tile, title, bounds, level in self.grr_legend_tiles:
            fill, line, ink = legend_colors[level]
            tile.configure(bg=fill, highlightbackground=line)
            for label in (title, bounds):
                label.configure(bg=fill, fg=ink)
        for swatch, level in self._swatches:
            fill, line = (p.warn_bg, p.warn_line) if level == "warn" else (p.bad_bg, p.bad_line)
            swatch.configure(bg=fill, highlightbackground=line)
        self.check_chips.set_palette(p)

    # ------------------------------------------------------------------ theme
    def _theme_button_text(self) -> str:
        return "☀  Light mode" if resolve_mode(self.settings.theme) == "dark" else "☾  Dark mode"

    def _toggle_theme(self) -> None:
        self.dark_var.set(not self.dark_var.get())
        self._on_theme_toggle()

    def _on_theme_toggle(self) -> None:
        self.settings.theme = "dark" if self.dark_var.get() else "light"
        self.palette = apply_theme(self, self.settings.theme)
        self.theme_text_var.set(self._theme_button_text())
        self._apply_tag_colors()
        if self.validation is not None:
            self.validation.set_palette(self.palette)
        self._update_brand_logo()
        self.step_bar.set_palette(self.palette)
        self.available_list.set_palette(self.palette)
        self.selected_list.set_palette(self.palette)
        save_settings(self.settings)

    # ------------------------------------------------------------------ helpers
    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        for widget in self._busy_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.profile_combo.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy and cancellable else "disabled")
        self._update_actions()

        if busy:
            self._progress_determinate = False
            self.progress.configure(mode="indeterminate", value=0)
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.progress.grid_remove()

    def _optional_int(self, var: tk.StringVar) -> int | None:
        try:
            return parse_positive_int(var.get(), "value")
        except ValueError:
            return None

    def _read_counts(self) -> tuple[int, int] | None:
        try:
            expected = parse_positive_int(self.expected_var.get(), "Expected samples")
            repeats = parse_positive_int(self.repeats_var.get(), "Files per sample")
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self)
            return None
        return expected, repeats

    def _update_profile_hint(self) -> None:
        profile = self.profiles.get(self.profile_var.get())
        if not profile:
            self.hint_var.set("")
            return
        kind = "Excel log" if profile.get("type") == "excel" else "Text log"
        self.hint_var.set(f"{kind}  ·  files: {', '.join(get_profile_extensions(profile))}")

    # ------------------------------------------------------------------ profiles
    def manage_profiles(self) -> None:
        ProfileManager(self, self.profiles, self._on_profiles_changed)

    def _on_profiles_changed(self, saved_name: str | None) -> None:
        self.profile_combo.configure(values=list(self.profiles))
        current = self.profile_var.get()
        if saved_name:
            if saved_name == current and self.scan_result is not None:
                self._clear_results("Profile edited. Scan again to apply the changes.")
            self.profile_var.set(saved_name)
        elif current not in self.profiles:
            self.profile_var.set(next(iter(self.profiles), ""))
            self._clear_results("Profile deleted.")
        self._update_profile_hint()

    def _on_profile_changed(self) -> None:
        self._update_profile_hint()
        self._clear_results(f"Profile changed to '{self.profile_var.get()}'. Choose a folder and scan.")

    # ------------------------------------------------------------------ scan
    def pick_folder(self) -> None:
        if self.is_busy:
            return
        start = self.folder_var.get().strip()
        folder = filedialog.askdirectory(
            title="Select the folder that contains the log files",
            initialdir=start if start and Path(start).is_dir() else None,
            parent=self,
        )
        if folder:
            self.folder_var.set(folder)

    def _cancel_scan(self) -> None:
        self._cancel.set()
        self.set_status("Cancelling…")

    def scan_logs(self) -> None:
        if self.is_busy:
            return
        folder_text = self.folder_var.get().strip()
        if not folder_text:
            messagebox.showwarning(APP_TITLE, "Please choose a folder first.", parent=self)
            return
        folder = Path(folder_text)
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, f"Folder path is not valid:\n{folder_text}", parent=self)
            return
        counts = self._read_counts()
        if counts is None:
            return
        profile_name = self.profile_var.get()
        if profile_name not in self.profiles:
            messagebox.showerror(APP_TITLE, f"Selected profile was not found:\n{profile_name or '(blank)'}", parent=self)
            return

        expected, repeats = counts
        profile = dict(self.profiles[profile_name])  # snapshot: later edits must not affect this scan
        self._remember_inputs()
        self._cancel.clear()
        self._show_step("select")  # a new scan starts from the first step (the review of the old data no longer applies)
        self._set_busy(True, cancellable=True)
        self.set_status("Looking for log files…")

        self.tasks.run(
            lambda report: scan_folder(folder, profile, self._cancel, progress=report),
            on_progress=self._on_scan_progress,
            on_success=lambda result: self._on_scan_done(result, folder, profile_name, profile, expected, repeats),
            on_error=self._on_scan_error,
        )

    def _on_scan_progress(self, done: int, total: int) -> None:
        if total and not self._progress_determinate:
            self._progress_determinate = True
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=total)
        if self._progress_determinate:
            self.progress.configure(value=done, maximum=max(total, 1))
            self.set_status(f"Scanning {done:,} of {total:,} files…")

    def _on_scan_error(self, exc: BaseException) -> None:
        logger.error("Scan failed: %s", exc, exc_info=exc)
        self._set_busy(False)
        self.set_status("Scan failed.")
        messagebox.showerror(APP_TITLE, str(exc), parent=self)

    def _on_scan_done(self, result: ScanResult, folder: Path, profile_name: str, profile: dict,
                      expected: int, repeats: int) -> None:
        self._set_busy(False)
        self.scan_result = result
        self._scan_serial += 1
        self._scan_description = f"Data Mapping scan of {folder} (profile {profile_name})"
        self.limits = summarize_limits(result.grouped, result.components)  # the Min / Max columns and the limits panel
        self._summary_key = None
        self._grr_key = None
        self._review_row = 0
        self._preview_page = 0
        self.reviewed_duplicates = set()

        # Keep what the user had selected, or restore their choice from last time for this profile.
        remembered = self.selected_components or self.settings.component_sets.get(profile_name, [])
        known = set(result.components)
        self.selected_components = [c for c in remembered if c in known]

        self.samples_var.set(f"{result.total_sns} / {expected}")
        self.files_var.set(f"{result.total_files:,}")
        self.components_var.set(f"{len(result.components):,}")
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
                if messagebox.askyesno(APP_TITLE, question, parent=self):
                    self.profile_var.set(better)
                    self._on_profile_changed()
                    self.scan_logs()
                return
            (messagebox.showerror if result.parse_warnings else messagebox.showwarning)(APP_TITLE, text, parent=self)
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
        others = {name: profile for name, profile in self.profiles.items() if name != current}
        try:
            return suggest_profile(folder, others)
        except Exception:
            logger.debug("Could not look for a better profile", exc_info=True)
            return None

    def _set_verdict(self, level: str, text: str, *, details: bool) -> None:
        self.verdict_var.set(("✓  " if level == "ok" else "⚠  ") + text)
        self.verdict_label.configure(style={"ok": "SurfaceOk.TLabel", "warn": "SurfaceWarn.TLabel", "bad": "SurfaceBad.TLabel"}[level])
        self.details_button.configure(state="normal" if details else "disabled")

    def _show_scan_details(self) -> None:
        if self.scan_result is None:
            return
        counts = self._read_counts()
        if counts:
            ReportDialog(self, "Scan details", "What the scan found", full_report(self.scan_result, *counts))

    def _clear_results(self, status: str) -> None:
        self.scan_result = None
        self._scan_serial += 1
        self.limits = {}
        self._summary_key = None
        self._grr_key = None
        self._review_row = 0
        self.selected_components = []
        self.reviewed_duplicates = set()
        for var in (self.samples_var, self.files_var, self.components_var):
            var.set("–")
        self.verdict_var.set("No scan yet.")
        self.verdict_label.configure(style="SurfaceMuted.TLabel")
        self.details_button.configure(state="disabled")
        self.search_var.set("")
        self._show_step("select")
        self._refresh_lists()
        if self._review_built:
            self._refresh_preview()
            self._refresh_grr()
        self._data_changed()
        self.set_status(status)

    def reset_workflow(self) -> None:
        if self.is_busy:
            return
        self.folder_var.set("")
        self._clear_results("Ready. Choose a profile and a folder, then scan.")

    # ------------------------------------------------------------------ component lists
    def _limit_texts(self, component: str) -> tuple[str, str]:
        return limit_texts(self.limits, component)

    def _refresh_available(self, *, reset_view: bool = False) -> None:
        components = self.scan_result.components if self.scan_result else []
        view = available_view(components, self.selected_components, self.search_var.get())
        self.available_list.set_items(view.items, empty_text=view.empty_text, values=[self._limit_texts(c) for c in view.items])
        if reset_view:
            self.available_list.reset_view()
        if view.filtering:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=10, rely=0.5, anchor="w")
        self.available_info_var.set(view.info)
        self._update_actions()

    def _refresh_selected(self) -> None:
        self.selected_list.set_items(self.selected_components, empty_text=SELECTED_EMPTY_TEXT)
        self.selected_info_var.set(selected_info(len(self.selected_components)))
        self._update_actions()

    def _refresh_lists(self) -> None:
        self._refresh_available()
        self._refresh_selected()

    def _selection_changed(self) -> None:
        profile = self.profile_var.get()
        if profile:
            self.settings.component_sets[profile] = list(self.selected_components)
        self._refresh_lists()
        self._schedule_preview()
        self._notify_validation()

    def add_components(self) -> None:
        self._add(self.available_list.selected_items())

    def add_all_shown(self) -> None:
        self._add(self.available_list.items())

    def _add_at(self, index: int) -> None:
        """The + button at the end of an available row."""
        items = self.available_list.items()
        if 0 <= index < len(items):
            self._add([items[index]])

    def _remove_at(self, index: int) -> None:
        """The × button at the end of a selected row."""
        if self.is_busy or not 0 <= index < len(self.selected_components):
            return
        del self.selected_components[index]
        self._selection_changed()

    def _add(self, names: list[str]) -> None:
        if self.is_busy:
            return
        added = [n for n in names if n not in self.selected_components]
        if not added:
            return
        self.selected_components.extend(added)
        self._selection_changed()

        if self.scan_result:
            pending = {g.component for g in self.scan_result.duplicate_groups if g.component in added}
            pending -= self.reviewed_duplicates
            if pending:
                groups = [g for g in self.scan_result.duplicate_groups if g.component in pending]
                DuplicateDialog(self, groups, self._on_duplicates_reviewed)

    def _on_duplicates_reviewed(self, reviewed: set[str], applied: bool) -> None:
        self.reviewed_duplicates |= reviewed
        self._summary_key = None  # the chosen occurrences change values
        self._grr_key = None
        self._data_changed()
        self.set_status(
            f"Duplicate choices applied for {len(reviewed)} component name(s)." if applied
            else f"Default duplicate choices kept for {len(reviewed)} component name(s)."
        )
        self._schedule_preview()

    def remove_components(self) -> None:
        if self.is_busy:
            return
        indices = self.selected_list.selected_indices()
        for index in reversed(indices):
            del self.selected_components[index]
        if indices:
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
        indices = self.selected_list.selected_indices()
        if not move_items(self.selected_components, indices, direction):
            return
        self._selection_changed()
        self.selected_list.select_indices([i + direction for i in indices])

    # ------------------------------------------------------------------ review (step 2)
    def _schedule_preview(self) -> None:
        """Redraw the review a moment from now (a burst of changes becomes one redraw). Only while it is on screen."""
        if self.step != "review" or not self._review_built:
            return
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(120, self._refresh_review)

    def _refresh_review(self) -> None:
        self._ensure_review_page()
        self._refresh_preview()
        self._refresh_checks()
        self._refresh_grr()
        self._update_actions()

    def _refresh_grr(self) -> None:
        """Assess each selected test over every SN and repeat, independently of the preview row limit."""
        result = self.scan_result
        components = tuple(self.selected_components)
        repeats = self._optional_int(self.repeats_var)
        key = (id(result), components, repeats)
        if key != self._grr_key:
            self._grr_results = summarize_grr(result.grouped, components, repeats) if result and result.grouped else []
            self._grr_key = key
        rows = []
        tags: dict[tuple[int, int], str] = {}
        levels = {"PASS": "pass", "CAUTION": "caution", "FAIL": "fail", "NOT EVALUATED": "neutral"}
        for index, entry in enumerate(self._grr_results):
            cells = []
            for column, (value, status) in enumerate((
                (entry.percent_study_var, entry.study_status), (entry.percent_tolerance, entry.tolerance_status),
            ), start=1):
                cells.append(f"{value:.2f}" if value is not None else "N/A")
                tags[index, column] = levels[status]
            cells.append(str(entry.ndc) if entry.ndc is not None else "N/A")
            tags[index, 3] = levels[entry.ndc_status]
            rows.append((entry.component, *cells))
        self.grr_grid.set_table(
            [Column("Test", width=self.grr_grid.scaled(140), stretch=True), Column("%Study Var", "e"),
             Column("%SV/Tol", "e"), Column("NDC", "center")],
            rows, cell_tags=tags, empty_text="Select tests to calculate their GRR pre-check.",
        )
        self.grr_summary_var.set(f"{len(rows)} test item{'s' if len(rows) != 1 else ''}" if rows else "")
        if rows:
            selected = self.grr_grid.selected_index()
            selected = selected if selected is not None else 0
            self.grr_grid.select(selected, notify=False)
            self._on_grr_select(selected)
        else:
            self.grr_detail_var.set("Select a test to see its Study Var and calculation notes.")

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
        self.grr_detail_var.set("\n".join(lines))

    def _update_pager(self, first: int, shown: int, total: int, pages: int) -> None:
        if pages <= 1:
            self.pager.grid_remove()
            return
        self.pager_var.set(f"Columns {first + 1}–{first + shown} of {total}")
        self.pager_prev.configure(state="normal" if self._preview_page > 0 else "disabled")
        self.pager_next.configure(state="normal" if self._preview_page < pages - 1 else "disabled")
        self.pager.grid()

    def _page_preview(self, step: int) -> None:
        self._preview_page = max(0, self._preview_page + step)
        self._schedule_preview()

    def _refresh_preview(self) -> None:
        """The table of rows (one page of columns) and, beside it, the limits for the chosen row."""
        self._ensure_review_page()
        self._preview_job = None
        result = self.scan_result
        components = list(self.selected_components)
        self._preview_components = tuple(components)

        # One page of columns at a time keeps the table readable; the export always has every column.
        table = preview_table(result, components, self._preview_page, self._optional_int(self.repeats_var))
        self._preview_page = table.page
        self._preview_rows = table.export_rows
        self._update_pager(table.first, len(table.page_components), len(components), table.pages)
        columns = [Column("No.", "center"), Column("Serial number"), Column("File"), *(Column(name, "e") for name in table.page_components)]
        self.preview_grid.set_table(columns, table.rows, table.tags if table.rows else None, empty_text=table.empty_text)
        self.preview_info_var.set(table.note)
        self.review_count_var.set(table.count_text)
        if not table.rows and (result is None or not result.grouped):
            self._refresh_limits()
            return

        shown = len(self._preview_rows)
        if self._preview_rows:  # keep the row you were looking at, or start with the first
            self._review_row = max(0, min(self._review_row, shown - 1))
            self.preview_grid.select(self._review_row, notify=False)
        self._refresh_limits()

    def _on_preview_select(self, index: int) -> None:
        if index != self._review_row:
            self._review_row = index
            self._refresh_limits()
        self.review_side_tabs.select(self.limits_page)

    def _refresh_limits(self) -> None:
        """The limits panel: every selected component with the chosen row's value, judged against its limits."""
        components = self._preview_components
        if components != self._limit_components:  # a different selection
            self._limit_components = components
            self.limits_title_var.set(f"Limits ({len(components)})" if components else "Limits")
            self._limit_columns = self._limit_column_layout(components)
        if not 0 <= self._review_row < len(self._preview_rows):  # no row to compare: just the limits
            self.review_row_var.set(NO_ROW_CHOSEN_TEXT)
            self.limits_grid.set_table(self._limit_columns, limit_overview(components, self.limits))
            return
        row = self._preview_rows[self._review_row]
        self.review_row_var.set(f"Row {row.index}   ·   {row.sn}   ·   {row.filename}")
        rows, tags = limit_panel(row, components, self.limits)
        self.limits_grid.set_table(self._limit_columns, rows, tags)

    def _limit_column_layout(self, components: tuple[str, ...]) -> list[Column]:
        """Wide enough for the longest limit and a value of the same size, so no number is ever cut off."""
        grid = self.limits_grid
        info = [self.limits.get(c, {}) for c in components]
        lows, highs = [i.get("min", "") for i in info], [i.get("max", "") for i in info]
        longest_number = max([*lows, *highs, "+000.0000E+00"], key=len)  # a value can have more digits than its limits
        return [
            Column("Component", "w", width=grid.scaled(80), stretch=True),  # the room left over; long names end in …
            Column("Value", "e", width=grid.width_for("Value", [longest_number + " ▲"]) + grid.scaled(10)),  # room for ▲ / ▼
            Column("Min", "e", width=grid.width_for("Min", lows)),
            Column("Max", "e", width=grid.width_for("Max", highs)),
            Column("Unit", "w", width=grid.width_for("Unit", [i.get("unit", "") for i in info])),
        ]

    def _review_summary(self) -> ReviewSummary | None:
        """Empty cells and out-of-limit rows over every row (not just the ones the table shows); kept until the data changes."""
        result = self.scan_result
        if result is None or not result.grouped or not self.selected_components:
            return None
        key = (id(result), tuple(self.selected_components))
        if key != self._summary_key:
            self._summary = summarize_review(result.grouped, self.selected_components, self.limits)
            self._summary_key = key
        return self._summary

    def _refresh_checks(self) -> None:
        """The chips beside the Export button: what to know before saving."""
        result = self.scan_result
        summary = self._review_summary()
        if result is None or summary is None:
            self.check_chips.set_chips([])
            return
        expected, repeats = self._optional_int(self.expected_var), self._optional_int(self.repeats_var)
        wrong = self._wrong_samples() if repeats is not None else []
        self.check_chips.set_chips(check_chips(result, summary, expected=expected, repeats=repeats, wrong=wrong))

    # ------------------------------------------------------------------ export
    def export_excel(self) -> None:
        if self.is_busy:
            return
        result = self.scan_result
        if result is None or not result.grouped:
            messagebox.showwarning(APP_TITLE, "Please scan a folder first.", parent=self)
            return
        if not self.selected_components:
            messagebox.showwarning(APP_TITLE, "Please select at least one component.", parent=self)
            return
        counts = self._read_counts()
        if counts is None:
            return
        expected, repeats = counts

        if result.total_sns != expected and not messagebox.askyesno(
            APP_TITLE,
            f"Expected {expected} samples, but found {result.total_sns}.\n\nDo you still want to export?",
            parent=self,
        ):
            return
        wrong = result.sns_with_wrong_repeat_count(repeats)
        if wrong:
            messagebox.showerror(
                APP_TITLE,
                f"Some samples do not have exactly {repeats} files:\n\n" + "\n".join(wrong[:20])
                + (f"\n… and {len(wrong) - 20} more" if len(wrong) > 20 else ""),
                parent=self,
            )
            return

        start = self.settings.last_export_dir
        output = filedialog.asksaveasfilename(
            title="Save the Excel file",
            defaultextension=".xlsx",
            initialfile=DEFAULT_OUTPUT_FILE,
            initialdir=start if start and Path(start).is_dir() else None,
            filetypes=[("Excel workbook", "*.xlsx")],
            parent=self,
        )
        if not output:
            return

        output_path = Path(output)
        grouped, components = dict(result.grouped), list(self.selected_components)
        self._set_busy(True)
        self.set_status("Creating the Excel file…")
        self.tasks.run(
            lambda _report: generate_excel(grouped, components, output_path, repeats),
            on_success=lambda _r: self._on_export_done(output_path),
            on_error=self._on_export_error,
        )

    def _on_export_done(self, output: Path) -> None:
        self._set_busy(False)
        self.settings.last_export_dir = str(output.parent)
        save_settings(self.settings)
        self.set_status(f"Exported: {output}")
        ExportDoneDialog(self, output)

    def _on_export_error(self, exc: BaseException) -> None:
        logger.error("Export failed: %s", exc, exc_info=exc)
        self._set_busy(False)
        self.set_status("Export failed.")
        messagebox.showerror(APP_TITLE, str(exc), parent=self)

    # ------------------------------------------------------------------ access (the owner's off switch)
    def _start_checks(self) -> None:
        """Runs a moment after start-up so the first paint is not competing with the network."""
        if self._enforce_access:
            self.verify_access(then=self._check_for_update)  # a copy that may not run is not offered an update
            self.after(access.RECHECK_MS, self._recheck_access)
        else:
            self._check_for_update()

    def _recheck_access(self) -> None:
        self.verify_access()
        self.after(access.RECHECK_MS, self._recheck_access)

    def verify_access(self, then: Callable[[], None] | None = None) -> None:
        """Read status.json in the background. ``then`` runs if the program may be used afterwards."""

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

    def _apply_access(self, block: access.Block | None, detail: str = "") -> None:
        dialog = self._access_dialog
        open_now = dialog is not None and bool(dialog.winfo_exists())
        if block is None:
            if open_now:
                dialog.destroy()  # type: ignore[union-attr]
            self._access_dialog = None
        elif open_now:
            dialog.show(block, detail)  # type: ignore[union-attr]
        else:
            logger.warning("This copy may not be used (%s)", block.kind)
            self._access_dialog = AccessDialog(self, block, detail)

    def exit_app(self) -> None:
        self._on_close()

    # ------------------------------------------------------------------ updates
    def _check_for_update(self, manual: bool = False) -> None:
        if manual:
            self.set_status("Checking for updates…")
        self.tasks.run(
            lambda _report: updater.check_for_update(),
            on_success=lambda info: self._on_update_checked(info, manual),
            on_error=lambda exc: self._on_update_check_failed(exc, manual),
        )

    def _on_update_checked(self, info: updater.UpdateInfo | None, manual: bool) -> None:
        if info is None:
            if manual:
                self.set_status("You have the latest version.")
                messagebox.showinfo(APP_TITLE, f"{APP_TITLE} {__version__} is the latest version.", parent=self)
            return

        self._update_info = info
        if info.is_mandatory_for(__version__):
            UpdateDialog(self, info, mandatory=True)
            return
        if manual or (self.settings.check_updates and info.version != self.settings.skipped_version):
            self.banner_label.configure(text=f"Version {info.version} is available. You are running {__version__}.")
            self.banner.grid()
        if manual:
            self.set_status(f"Version {info.version} is available.")
            UpdateDialog(self, info, mandatory=False)

    def _on_update_check_failed(self, exc: BaseException, manual: bool) -> None:
        logger.info("Update check failed: %s", exc)
        if manual:
            self.set_status("Could not check for updates.")
            if messagebox.askyesno(
                APP_TITLE,
                f"Could not check for updates.\n\n{exc}\n\nOpen the releases page in your browser?",
                parent=self,
            ):
                webbrowser.open(f"{updater.RELEASES_URL}/latest")

    def _open_update_dialog(self) -> None:
        if self._update_info:
            UpdateDialog(self, self._update_info, mandatory=self._update_info.is_mandatory_for(__version__))

    def hide_update_banner(self) -> None:
        self.banner.grid_remove()

    def skip_update(self, version: str) -> None:
        if version:
            self.settings.skipped_version = version
            save_settings(self.settings)
        self.hide_update_banner()

    # ------------------------------------------------------------------ misc
    def _show_shortcuts(self) -> None:
        text = "\n".join(f"{keys:<24}{action}" for keys, action in SHORTCUTS)
        ReportDialog(self, "Keyboard shortcuts", "Keyboard shortcuts", text)
