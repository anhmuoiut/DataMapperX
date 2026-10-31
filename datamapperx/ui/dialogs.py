"""Simple dialogs and the base class the other dialogs build on."""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

from .._version import __version__
from ..config import APP_DEVELOPER_LINE, APP_TITLE, GITHUB_REPO
from ..grr import DEFAULT_QUICK_CRITERIA, QUICK_LABELS, QUICK_METRICS, validate_quick_criteria
from ..paths import resource_path, user_data_dir
from ..statistics.models import Criterion
from .theme import Palette, set_dark_titlebar
from .widgets import ReadOnlyText

logger = logging.getLogger(__name__)


def set_window_icon(window: tk.Wm) -> None:
    icon = resource_path("assets", "DataMapperX.ico")
    if icon.exists():
        try:
            window.iconbitmap(default=str(icon))
        except tk.TclError:
            logger.debug("Could not apply icon %s", icon, exc_info=True)


def open_path(path: Path) -> None:
    """Open a file or folder with the OS default handler."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(path)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        logger.warning("Could not open %s: %s", path, exc)


class Dialog(tk.Toplevel):
    """Themed, centred dialog. Build the widgets, then call ``present()``."""

    def __init__(self, parent: tk.Misc, title: str, *, modal: bool = True, min_size: tuple[int, int] | None = None):
        super().__init__(parent)
        self.withdraw()  # avoid flashing at the top-left corner while the widgets are built
        self.parent = parent
        self.palette: Palette = parent.palette  # type: ignore[attr-defined]
        self._modal = modal
        self.title(title)
        set_window_icon(self)
        self.transient(parent)
        self.configure(bg=self.palette.bg)
        if min_size:
            self.minsize(*min_size)
        self.bind("<Escape>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)

    def present(self, width: int | None = None, height: int | None = None) -> None:
        self.update_idletasks()
        w = width or self.winfo_reqwidth()
        h = height or self.winfo_reqheight()
        px, py = self.parent.winfo_rootx(), self.parent.winfo_rooty()
        pw, ph = self.parent.winfo_width(), self.parent.winfo_height()
        x = max(0, px + (pw - w) // 2)
        y = max(0, py + (ph - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        set_dark_titlebar(self, self.palette.mode == "dark")
        if self._modal:
            self.grab_set()
        self.focus_set()

    def close(self) -> None:
        self.destroy()


class ExportDoneDialog(Dialog):
    def __init__(self, parent: tk.Misc, output: Path):
        super().__init__(parent, "Export complete")
        self.output = output
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Excel exported successfully", style="Title.TLabel", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(body, text=str(output), style="Muted.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(6, 16))
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Open file", style="Accent.TButton", command=self._open_file).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Open folder", command=self._open_folder).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="left")
        self.present(width=520)

    def _open_file(self) -> None:
        open_path(self.output)
        self.close()

    def _open_folder(self) -> None:
        open_path(self.output.parent)
        self.close()


class ReportDialog(Dialog):
    def __init__(self, parent: tk.Misc, title: str, heading: str, content: str):
        super().__init__(parent, title, min_size=(520, 320))
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text=heading, font=("Segoe UI Semibold", 12)).grid(row=0, column=0, sticky="w", pady=(0, 8))
        text = ReadOnlyText(body, self.palette, height=14, width=76)
        text.grid(row=1, column=0, sticky="nsew")
        text.set_text(content)
        ttk.Button(body, text="Close", style="Accent.TButton", command=self.close).grid(row=2, column=0, sticky="e", pady=(12, 0))
        self.present(width=680, height=460)


class AboutDialog(Dialog):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, f"About {APP_TITLE}")
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"Version {__version__}", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(2, 0))
        ttk.Label(body, text=APP_DEVELOPER_LINE, style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        ttk.Label(
            body,
            text="Collects measurements from test logs (text or Excel) and exports them as one Excel workbook.",
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(body, text=f"Your data folder:\n{user_data_dir()}", style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(16, 0), fill="x")
        ttk.Button(buttons, text="GitHub page", command=lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}")).pack(side="left")
        ttk.Button(buttons, text="Open data folder", command=lambda: open_path(user_data_dir())).pack(side="left", padx=8)
        ttk.Button(buttons, text="Close", style="Accent.TButton", command=self.close).pack(side="right")
        self.present(width=480)


class GrrCriteriaDialog(Dialog):
    """The criteria of the GRR Quick Check: for each metric whether it decides, and its limits. Nothing changes until Apply."""

    def __init__(self, parent: tk.Misc, criteria, on_apply):
        super().__init__(parent, "Quick Check criteria")
        self.on_apply = on_apply
        self.vars: dict[str, tuple[tk.BooleanVar, tk.StringVar, tk.StringVar]] = {}
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        for column, text in ((0, "Metric"), (1, "PASS up to"), (2, "FAIL above")):
            ttk.Label(body, text=text, style="Muted.TLabel").grid(row=0, column=column, sticky="w", padx=(0, 12))
        for row, criterion in enumerate(criteria, start=1):
            enabled = tk.BooleanVar(value=criterion.enabled)
            low, high = (tk.StringVar(value=f"{limit:g}") for limit in (criterion.pass_limit, criterion.fail_limit))
            self.vars[criterion.metric] = (enabled, low, high)
            ttk.Checkbutton(body, text=QUICK_LABELS[criterion.metric], variable=enabled).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            if criterion.metric == "ndc":
                cell = ttk.Frame(body)
                cell.grid(row=row, column=1, columnspan=2, sticky="w")
                ttk.Label(cell, text="minimum").pack(side="left", padx=(0, 6))
                ttk.Entry(cell, textvariable=low, width=6).pack(side="left")
                continue
            for column, variable in ((1, low), (2, high)):
                cell = ttk.Frame(body)
                cell.grid(row=row, column=column, sticky="w", padx=(0, 12))
                ttk.Entry(cell, textvariable=variable, width=6).pack(side="left")
                ttk.Label(cell, text="%").pack(side="left", padx=(4, 0))
        ttk.Label(body, text="A metric that is not used stays in the table, without colour, and does not decide the Result. "
                  "The Result is the worst of the metrics used.", style="Muted.TLabel", wraplength=380, justify="left").grid(
            row=len(self.vars) + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var, style="Bad.TLabel", wraplength=380, justify="left").grid(
            row=len(self.vars) + 2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=len(self.vars) + 3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Reset to defaults", command=self.reset).pack(side="left")
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=self.apply).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=(0, 8))
        self.present()

    def reset(self) -> None:
        for criterion in DEFAULT_QUICK_CRITERIA:
            enabled, low, high = self.vars[criterion.metric]
            enabled.set(criterion.enabled)
            low.set(f"{criterion.pass_limit:g}")
            high.set(f"{criterion.fail_limit:g}")
        self.error_var.set("")

    def apply(self) -> None:
        try:
            criteria = []
            for metric in QUICK_METRICS:
                enabled, low, high = self.vars[metric]
                try:
                    limits = (float(low.get()),) * 2 if metric == "ndc" else (float(low.get()), float(high.get()))
                except ValueError:
                    raise ValueError(f"{QUICK_LABELS[metric]}: enter numbers.") from None
                criteria.append(Criterion(metric, enabled.get(), *limits))
            validate_quick_criteria(criteria)
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.on_apply(tuple(criteria))
        self.close()
