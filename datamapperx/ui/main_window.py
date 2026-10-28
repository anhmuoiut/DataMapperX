"""The main DataMapperX window."""

from __future__ import annotations

import logging
import re
import threading
import tkinter as tk
import webbrowser
from itertools import islice
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import updater
from .._version import __version__
from ..config import (
    APP_DEVELOPER_LINE,
    APP_TITLE,
    DEFAULT_OUTPUT_FILE,
    MISSING_TEXT,
    PREVIEW_ROW_LIMIT,
)
from ..exporter import generate_excel, iter_export_rows
from ..models import ScanResult
from ..paths import log_path, resource_path, user_data_dir
from ..profiles import get_profile_extensions, load_profiles
from ..reporting import describe_empty_scan, full_report, summarize_scan
from ..scanner import scan_folder
from ..settings import Settings, load_settings, save_settings
from ..utils import parse_positive_int
from .dialogs import AboutDialog, ExportDoneDialog, ReportDialog, open_path, set_window_icon
from .duplicate_dialog import DuplicateDialog
from .profile_dialog import ProfileManager
from .tasks import TaskRunner
from .theme import Palette, apply_theme, resolve_mode
from .update_dialog import UpdateDialog
from .widgets import ItemList

logger = logging.getLogger(__name__)

SHORTCUTS = (
    ("Ctrl+O", "Choose the source folder"),
    ("Ctrl+Enter  /  F5", "Scan logs"),
    ("Esc", "Cancel a running scan"),
    ("Ctrl+E", "Export to Excel"),
    ("Double-click / Enter", "Add or remove the highlighted component"),
    ("Ctrl+A", "Select every component in a list"),
    ("Delete", "Remove the highlighted selected components"),
)


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.settings: Settings = load_settings()
        self.profiles = load_profiles()
        self.tasks = TaskRunner(self)

        self.scan_result: ScanResult | None = None
        self.selected_components: list[str] = []
        self.reviewed_duplicates: set[str] = set()
        self.is_busy = False
        self._cancel = threading.Event()
        self._preview_job: str | None = None
        self._progress_determinate = False
        self._update_info: updater.UpdateInfo | None = None
        self._scanned_profile_name = ""

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

        if self.settings.last_profile in self.profiles:
            self.profile_var.set(self.settings.last_profile)
        elif self.profiles:
            self.profile_var.set(next(iter(self.profiles)))

        self._build_ui()
        self._bind_shortcuts()
        self._update_profile_hint()
        self._refresh_lists()
        self._refresh_preview()

        self.search_var.trace_add("write", lambda *_: self._refresh_available())
        self.repeats_var.trace_add("write", lambda *_: self._schedule_preview())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.report_callback_exception = self._on_callback_error  # type: ignore[method-assign]

        self.deiconify()
        if self.settings.check_updates:
            self.after(1500, self._check_for_update)
        self.after(5000, updater.cleanup_update_leftovers)

    # ------------------------------------------------------------------ window basics
    def _setup_geometry(self) -> None:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1360, max(1000, int(screen_w * 0.88)))
        height = min(880, max(700, int(screen_h * 0.86)))
        self.minsize(min(1000, screen_w - 80), min(680, screen_h - 80))

        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.settings.geometry or "")
        if match:
            w, h, x, y = (int(g) for g in match.groups())
            on_screen = -50 <= x <= screen_w - 120 and -10 <= y <= screen_h - 120
            if on_screen and w >= 800 and h >= 560:
                self.geometry(f"{w}x{h}+{x}+{y}")
                return
        self.geometry(f"{width}x{height}")

    def _on_close(self) -> None:
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
        self.bind("<Control-o>", lambda _e: self.pick_folder())
        self.bind("<Control-Return>", lambda _e: self.scan_logs())
        self.bind("<F5>", lambda _e: self.scan_logs())
        self.bind("<Control-e>", lambda _e: self.export_excel())
        self.bind("<Escape>", lambda _e: self._cancel_scan() if self.is_busy else None)

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_header()
        self._build_banner()

        # Left: the workflow sidebar. Right: component pickers above the data preview.
        content = ttk.Frame(self)
        content.grid(row=2, column=0, sticky="nsew", padx=14, pady=(2, 0))
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=0, minsize=400)
        content.columnconfigure(1, weight=1)
        self._build_workspace(content)

        right = ttk.PanedWindow(content, orient=tk.VERTICAL)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        lists = ttk.Frame(right)
        preview = ttk.Frame(right)
        right.add(lists, weight=2)
        right.add(preview, weight=3)

        lists.rowconfigure(0, weight=1)
        lists.columnconfigure(0, weight=1, uniform="lists")
        lists.columnconfigure(1, weight=1, uniform="lists")
        self._build_available(lists)
        self._build_selected(lists)
        self._build_preview(preview)
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(18, 12, 18, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self._icon_image = None
        icon = resource_path("assets", "DataMapperX.png")
        if icon.exists():
            try:
                self._icon_image = tk.PhotoImage(file=str(icon))
                ttk.Label(header, image=self._icon_image).grid(row=0, column=0, rowspan=2, padx=(0, 12))
            except tk.TclError:
                logger.debug("Could not load header icon", exc_info=True)

        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text=APP_DEVELOPER_LINE, style="Muted.TLabel").grid(row=1, column=1, sticky="w")

        right = ttk.Frame(header)
        right.grid(row=0, column=2, rowspan=2, sticky="e")

        # Optional company logo; it is kept out of the public repository, so it only shows when present.
        self._brand_image = None
        brand = resource_path("assets", "Jabil_logo.png")
        if brand.exists():
            try:
                image = tk.PhotoImage(file=str(brand))
                self._brand_image = image.subsample(max(1, round(image.height() / 30)))
                # A white chip keeps the dark-blue logo legible in dark mode too.
                tk.Label(right, image=self._brand_image, bg="#ffffff", padx=8, pady=4, borderwidth=0).pack(
                    side="left", padx=(0, 18)
                )
            except tk.TclError:
                logger.debug("Could not load brand logo", exc_info=True)

        ttk.Label(right, text=f"v{__version__}", style="Muted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Checkbutton(right, text="Dark mode", style="Switch.TCheckbutton", variable=self.dark_var, command=self._on_theme_toggle).pack(side="left", padx=(0, 10))

        menu_button = ttk.Menubutton(right, text="Help")
        menu = tk.Menu(menu_button, tearoff=False)
        menu.add_command(label="Check for updates…", command=lambda: self._check_for_update(manual=True))
        menu.add_checkbutton(label="Check for updates at startup", variable=self.auto_update_var, command=self._remember_inputs)
        menu.add_separator()
        menu.add_command(label="Keyboard shortcuts", command=self._show_shortcuts)
        menu.add_command(label="Open data folder", command=lambda: open_path(user_data_dir()))
        menu.add_command(label="Open log file", command=lambda: open_path(log_path()))
        menu.add_separator()
        menu.add_command(label=f"About {APP_TITLE}", command=lambda: AboutDialog(self))
        menu_button.configure(menu=menu)
        menu_button.pack(side="left")

    def _build_banner(self) -> None:
        self.banner = ttk.Frame(self, style="Banner.TFrame", padding=(18, 8))
        self.banner.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.banner.columnconfigure(0, weight=1)
        self.banner_label = ttk.Label(self.banner, style="Banner.TLabel")
        self.banner_label.grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(self.banner, style="Banner.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        ttk.Button(buttons, text="Update now", style="Accent.TButton", command=self._open_update_dialog).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Skip this version", command=lambda: self.skip_update(self._update_info.version if self._update_info else "")).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="✕", width=3, command=self.hide_update_banner).pack(side="left")
        self.banner.grid_remove()

    def _card(self, parent: tk.Misc, title: str, column: int, padx: tuple[int, int]) -> ttk.LabelFrame:
        card = ttk.LabelFrame(parent, text=title, padding=12)
        card.grid(row=0, column=column, sticky="nsew", padx=padx, pady=(0, 6))
        return card

    def _build_workspace(self, parent: tk.Misc) -> None:
        card = self._card(parent, "1  Source", 0, (0, 0))
        card.columnconfigure(0, weight=1)

        head = ttk.Frame(card)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Profile").grid(row=0, column=0, sticky="w")
        self.manage_button = ttk.Button(head, text="Manage…", command=self.manage_profiles)
        self.manage_button.grid(row=0, column=1, sticky="e")

        self.profile_combo = ttk.Combobox(card, textvariable=self.profile_var, values=list(self.profiles), state="readonly")
        self.profile_combo.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_profile_changed())
        self.hint_label = ttk.Label(card, textvariable=self.hint_var, style="Hint.TLabel", wraplength=360, justify="left")
        self.hint_label.grid(row=2, column=0, sticky="w", pady=(0, 10))

        ttk.Label(card, text="Source folder").grid(row=3, column=0, sticky="w")
        folder_row = ttk.Frame(card)
        folder_row.grid(row=4, column=0, sticky="ew", pady=(4, 10))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.folder_entry.bind("<Return>", lambda _e: self.scan_logs())
        self.browse_button = ttk.Button(folder_row, text="Browse…", command=self.pick_folder)
        self.browse_button.grid(row=0, column=1)

        counts = ttk.Frame(card)
        counts.grid(row=5, column=0, sticky="ew")
        counts.columnconfigure(1, weight=1)
        counts.columnconfigure(3, weight=1)
        ttk.Label(counts, text="Expected samples").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.expected_spin = ttk.Spinbox(counts, from_=1, to=9999, width=6, textvariable=self.expected_var)
        self.expected_spin.grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Label(counts, text="Files per sample").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.repeats_spin = ttk.Spinbox(counts, from_=1, to=999, width=6, textvariable=self.repeats_var)
        self.repeats_spin.grid(row=0, column=3, sticky="w")

        actions = ttk.Frame(card)
        actions.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=2)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        self.scan_button = ttk.Button(actions, text="Scan logs", style="Accent.TButton", command=self.scan_logs)
        self.scan_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel_scan, state="disabled")
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.reset_button = ttk.Button(actions, text="Reset", command=self.reset_workflow)
        self.reset_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))

        ttk.Separator(card).grid(row=7, column=0, sticky="ew", pady=12)
        stats = ttk.Frame(card)
        stats.grid(row=8, column=0, sticky="ew")
        for col, (caption, var) in enumerate((("SAMPLES", self.samples_var), ("FILES", self.files_var), ("COMPONENTS", self.components_var))):
            stats.columnconfigure(col, weight=1, uniform="stats")
            block = ttk.Frame(stats)
            block.grid(row=0, column=col, sticky="w")
            ttk.Label(block, textvariable=var, style="Stat.TLabel").pack(anchor="w")
            ttk.Label(block, text=caption, style="StatCaption.TLabel").pack(anchor="w")

        verdict = ttk.Frame(card)
        verdict.grid(row=9, column=0, sticky="ew", pady=(10, 0))
        verdict.columnconfigure(0, weight=1)
        self.verdict_label = ttk.Label(verdict, textvariable=self.verdict_var, wraplength=250, justify="left")
        self.verdict_label.grid(row=0, column=0, sticky="w")
        self.details_button = ttk.Button(verdict, text="Details…", command=self._show_scan_details, state="disabled")
        self.details_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self._busy_widgets: list[ttk.Widget] = [
            self.manage_button, self.browse_button, self.scan_button, self.reset_button,
            self.expected_spin, self.repeats_spin, self.folder_entry,
        ]

    def _build_available(self, parent: tk.Misc) -> None:
        card = self._card(parent, "2  Available components", 0, (0, 5))
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(card, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.search_hint = ttk.Label(self.search_entry, text="Filter components…", style="EntryHint.TLabel")
        self.search_hint.place(x=10, rely=0.5, anchor="w")
        self.search_hint.bind("<Button-1>", lambda _e: self.search_entry.focus_set())
        self.available_list = ItemList(card, on_activate=self.add_components)
        self.available_list.grid(row=1, column=0, sticky="nsew")
        footer = ttk.Frame(card)
        footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.available_info_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Add all shown", command=self.add_all_shown).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(footer, text="Add  →", style="Accent.TButton", command=self.add_components).grid(row=0, column=2)

    def _build_selected(self, parent: tk.Misc) -> None:
        card = self._card(parent, "3  Selected components (export order)", 1, (5, 0))
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)
        self.selected_list = ItemList(card, on_activate=self.remove_components, on_delete=self.remove_components)
        self.selected_list.grid(row=0, column=0, sticky="nsew")
        footer = ttk.Frame(card)
        footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.selected_info_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="▲", width=3, command=lambda: self.move_selected(-1)).grid(row=0, column=1, padx=2)
        ttk.Button(footer, text="▼", width=3, command=lambda: self.move_selected(1)).grid(row=0, column=2, padx=2)
        ttk.Button(footer, text="Remove", command=self.remove_components).grid(row=0, column=3, padx=2)
        ttk.Button(footer, text="Clear", command=self.clear_selected).grid(row=0, column=4, padx=(2, 0))

    def _build_preview(self, parent: tk.Misc) -> None:
        card = ttk.LabelFrame(parent, text="4  Preview  (exactly what will be exported)", padding=12)
        card.pack(fill="both", expand=True, pady=(4, 6))
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(card)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, textvariable=self.preview_info_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        self.export_button = ttk.Button(toolbar, text="Export Excel…", style="Accent.TButton", command=self.export_excel)
        self.export_button.grid(row=0, column=1, sticky="e")
        self._busy_widgets.append(self.export_button)

        frame = ttk.Frame(card)
        frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.preview_tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.preview_tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self.preview_tree.xview)
        self.preview_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.preview_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self._apply_tag_colors()
        self.empty_label = ttk.Label(frame, style="Muted.TLabel", justify="center", font=("Segoe UI", 11))

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(18, 4, 18, 10))
        bar.grid(row=3, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, length=220, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.progress.grid_remove()

    def _apply_tag_colors(self) -> None:
        self.preview_tree.tag_configure("invalid", foreground=self.palette.danger)
        self.preview_tree.tag_configure("missing", foreground=self.palette.warn)

    # ------------------------------------------------------------------ theme
    def _on_theme_toggle(self) -> None:
        self.settings.theme = "dark" if self.dark_var.get() else "light"
        self.palette = apply_theme(self, self.settings.theme)
        self._apply_tag_colors()
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
        self._set_busy(True, cancellable=True)
        self.set_status("Looking for log files…")
        self.preview_tree.delete(*self.preview_tree.get_children())

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
        self._scanned_profile_name = profile_name
        self.reviewed_duplicates = set()

        # Keep what the user had selected, or restore their choice from last time for this profile.
        remembered = self.selected_components or self.settings.component_sets.get(profile_name, [])
        known = set(result.components)
        self.selected_components = [c for c in remembered if c in known]

        self.samples_var.set(f"{result.total_sns} / {expected}")
        self.files_var.set(f"{result.total_files:,}")
        self.components_var.set(f"{len(result.components):,}")
        self._refresh_lists()
        self._refresh_preview()

        if not result.grouped:
            self._set_verdict("bad", "No usable data found.", details=False)
            self.set_status("Scan finished: nothing usable found.")
            text = describe_empty_scan(folder, profile_name, profile, result)
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

    def _set_verdict(self, level: str, text: str, *, details: bool) -> None:
        self.verdict_var.set(("✓  " if level == "ok" else "⚠  ") + text)
        self.verdict_label.configure(style={"ok": "Ok.TLabel", "warn": "Warn.TLabel", "bad": "Bad.TLabel"}[level])
        self.details_button.configure(state="normal" if details else "disabled")

    def _show_scan_details(self) -> None:
        if self.scan_result is None:
            return
        counts = self._read_counts()
        if counts:
            ReportDialog(self, "Scan details", "What the scan found", full_report(self.scan_result, *counts))

    def _clear_results(self, status: str) -> None:
        self.scan_result = None
        self.selected_components = []
        self.reviewed_duplicates = set()
        for var in (self.samples_var, self.files_var, self.components_var):
            var.set("–")
        self.verdict_var.set("No scan yet.")
        self.verdict_label.configure(style="TLabel")
        self.details_button.configure(state="disabled")
        self.search_var.set("")
        self._refresh_lists()
        self._refresh_preview()
        self.set_status(status)

    def reset_workflow(self) -> None:
        self.folder_var.set("")
        self._clear_results("Ready. Choose a profile and a folder, then scan.")

    # ------------------------------------------------------------------ component lists
    def _refresh_available(self) -> None:
        components = self.scan_result.components if self.scan_result else []
        chosen = set(self.selected_components)
        keyword = self.search_var.get().strip().lower()
        remaining = [c for c in components if c not in chosen]
        shown = [c for c in remaining if keyword in c.lower()] if keyword else remaining
        if not components:
            empty = "Scan a folder to list\nits components here."
        elif not remaining:
            empty = "Every component is selected."
        else:
            empty = "No component matches the filter."
        self.available_list.set_items(shown, empty_text=empty)
        if keyword:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=10, rely=0.5, anchor="w")
        if not components:
            self.available_info_var.set("")
        elif keyword:
            self.available_info_var.set(f"{len(shown)} of {len(remaining)} shown")
        else:
            self.available_info_var.set(f"{len(remaining)} available")

    def _refresh_selected(self) -> None:
        self.selected_list.set_items(
            self.selected_components, empty_text="Double-click a component on the left,\nor select some and press Add →."
        )
        count = len(self.selected_components)
        self.selected_info_var.set(f"{count} selected" if count else "")

    def _refresh_lists(self) -> None:
        self._refresh_available()
        self._refresh_selected()

    def _selection_changed(self) -> None:
        profile = self.profile_var.get()
        if profile:
            self.settings.component_sets[profile] = list(self.selected_components)
        self._refresh_lists()
        self._schedule_preview()

    def add_components(self) -> None:
        self._add(self.available_list.selected_items())

    def add_all_shown(self) -> None:
        self._add(self.available_list.items())

    def _add(self, names: list[str]) -> None:
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
        self.set_status(
            f"Duplicate choices applied for {len(reviewed)} component name(s)." if applied
            else f"Default duplicate choices kept for {len(reviewed)} component name(s)."
        )
        self._schedule_preview()

    def remove_components(self) -> None:
        indices = self.selected_list.selected_indices()
        for index in reversed(indices):
            del self.selected_components[index]
        if indices:
            self._selection_changed()

    def clear_selected(self) -> None:
        if self.selected_components:
            self.selected_components = []
            self._selection_changed()

    def move_selected(self, direction: int) -> None:
        indices = self.selected_list.selected_indices()
        items = self.selected_components
        if not indices or (direction < 0 and indices[0] == 0) or (direction > 0 and indices[-1] == len(items) - 1):
            return
        for index in indices if direction < 0 else reversed(indices):
            items[index], items[index + direction] = items[index + direction], items[index]
        self._selection_changed()
        self.selected_list.select_indices([i + direction for i in indices])

    # ------------------------------------------------------------------ preview
    def _schedule_preview(self) -> None:
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(120, self._refresh_preview)

    def _show_empty(self, message: str) -> None:
        self.empty_label.configure(text=message)
        self.empty_label.place(relx=0.5, rely=0.42, anchor="center")

    def _refresh_preview(self) -> None:
        self._preview_job = None
        tree = self.preview_tree
        tree.delete(*tree.get_children())
        result = self.scan_result
        components = list(self.selected_components)

        columns = ["no", "sn", "file", *[f"c{i}" for i in range(len(components))]]
        tree.configure(columns=columns, displaycolumns=columns)
        tree.heading("no", text="No.")
        tree.column("no", width=56, minwidth=40, stretch=False, anchor="center")
        tree.heading("sn", text="Serial number")
        tree.column("sn", width=170, minwidth=100, stretch=False, anchor="w")
        tree.heading("file", text="File")
        tree.column("file", width=280, minwidth=120, stretch=not components, anchor="w")
        for i, name in enumerate(components):
            tree.heading(f"c{i}", text=name)
            tree.column(f"c{i}", width=max(100, min(220, len(name) * 8 + 28)), minwidth=70, stretch=False, anchor="e")

        if result is None or not result.grouped:
            self._show_empty("Scan a folder to see your data here.")
            self.preview_info_var.set("")
            return
        if not components:
            self._show_empty("Pick components in step 2 to see their values here.")
            self.preview_info_var.set(f"{result.total_files} files found")
        else:
            self.empty_label.place_forget()

        repeats = self._optional_int(self.repeats_var)
        wrong = set(result.sns_with_wrong_repeat_count(repeats)) if repeats else set()
        shown = 0
        any_missing = False
        for row in islice(iter_export_rows(result.grouped, components), PREVIEW_ROW_LIMIT):
            missing = bool(components) and MISSING_TEXT in row.values
            any_missing = any_missing or missing
            tags = ("invalid",) if row.sn in wrong else ("missing",) if missing else ()
            tree.insert("", tk.END, values=(row.index, row.sn, row.filename, *row.values), tags=tags)
            shown += 1

        if components:
            note = f"Showing {shown} of {result.total_files} rows." if shown < result.total_files else f"{shown} rows."
            if wrong:
                note += "  Red: sample has the wrong number of files."
            if any_missing:
                note += "  Amber: a value is missing."
            self.preview_info_var.set(note)

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
        if manual or info.version != self.settings.skipped_version:
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
