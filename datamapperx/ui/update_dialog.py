"""Release notes + download/install progress for an available update."""

from __future__ import annotations

import logging
import threading
import webbrowser
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .. import updater
from .._version import __version__
from ..config import APP_TITLE
from .dialogs import Dialog
from .widgets import ReadOnlyText

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


class UpdateDialog(Dialog):
    def __init__(self, app: MainWindow, info: updater.UpdateInfo, *, mandatory: bool):
        super().__init__(app, "Update required" if mandatory else "Update available", min_size=(520, 380))
        self.app = app
        self.info = info
        self.mandatory = mandatory
        self._cancel = threading.Event()
        self._downloading = False

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        heading = "This version is no longer supported" if mandatory else f"{APP_TITLE} {info.version} is available"
        ttk.Label(body, text=heading, font=("Segoe UI Semibold", 14)).grid(row=0, column=0, sticky="w")
        detail = f"You are running {__version__}."
        if mandatory:
            detail += f" Version {info.version} is required to continue."
        if info.published_at:
            detail += f"  Released {info.published_at[:10]}."
        ttk.Label(body, text=detail, style="Muted.TLabel", wraplength=500, justify="left").grid(row=1, column=0, sticky="w", pady=(2, 10))

        notes = ReadOnlyText(body, self.palette, height=9, width=64)
        notes.grid(row=2, column=0, sticky="nsew")
        notes.set_markdown(info.notes or "No release notes were provided.")

        # Download progress (hidden until the user presses Update now).
        self.progress_frame = ttk.Frame(body)
        self.progress_frame.columnconfigure(0, weight=1)
        self.progress_label = ttk.Label(self.progress_frame, text="")
        self.progress_label.grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate", maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.progress_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.progress_frame.grid_remove()

        self.buttons = ttk.Frame(body)
        self.buttons.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self.update_button = ttk.Button(self.buttons, text="Update now", style="Accent.TButton", command=self._update_now)
        self.update_button.pack(side="right")
        if mandatory:
            self.exit_button = ttk.Button(self.buttons, text=f"Exit {APP_TITLE}", command=self._exit_app)
            self.exit_button.pack(side="right", padx=(0, 8))
        else:
            self.later_button = ttk.Button(self.buttons, text="Later", command=self.close)
            self.later_button.pack(side="right", padx=(0, 8))
            self.skip_button = ttk.Button(self.buttons, text="Skip this version", command=self._skip)
            self.skip_button.pack(side="left")

        self.present(width=580, height=470)

    # ------------------------------------------------------------------ actions
    def _skip(self) -> None:
        self.app.skip_update(self.info.version)
        self.destroy()

    def _exit_app(self) -> None:
        self.destroy()
        self.app.destroy()

    def close(self) -> None:
        if self._downloading:
            self._cancel.set()
            return
        if self.mandatory:
            self._exit_app()
        else:
            self.destroy()

    def _set_idle(self) -> None:
        self._downloading = False
        self.progress_frame.grid_remove()
        for widget in self.buttons.winfo_children():
            widget.configure(state="normal")

    def _update_now(self) -> None:
        if self.app.is_busy:
            messagebox.showinfo(APP_TITLE, "Please wait for the current scan or export to finish, then update.", parent=self)
            return

        if not updater.can_self_update():
            webbrowser.open(f"{updater.RELEASES_URL}/latest")
            messagebox.showinfo(
                APP_TITLE,
                "This copy cannot update itself (it is not an installed .exe, or its folder is read-only).\n\n"
                "The download page has been opened. Replace DataMapperX.exe with the new file.",
                parent=self,
            )
            if self.mandatory:
                self._exit_app()
            return

        self._downloading = True
        self._cancel.clear()
        for widget in self.buttons.winfo_children():
            widget.configure(state="disabled")
        self.progress_frame.grid()
        self.progress_label.configure(text="Downloading…")
        self.progress_bar.configure(value=0)

        destination = updater.staging_path()
        self.app.tasks.run(
            lambda report: updater.download_update(self.info, destination, progress=report, cancel_event=self._cancel),
            on_progress=self._on_progress,
            on_success=lambda _result: self._on_downloaded(destination),
            on_error=self._on_failed,
        )

    def _on_progress(self, done: int, total: int) -> None:
        if not self.winfo_exists():
            return
        if total:
            self.progress_bar.configure(value=done * 100 / total)
            self.progress_label.configure(text=f"Downloading… {done / 1_048_576:.1f} of {total / 1_048_576:.1f} MB")
        else:
            self.progress_label.configure(text=f"Downloading… {done / 1_048_576:.1f} MB")

    def _on_downloaded(self, destination) -> None:
        if not self.winfo_exists():
            return
        self.progress_label.configure(text="Installing…")
        self.progress_bar.configure(value=100)
        self.update_idletasks()
        try:
            updater.install_update(destination)
        except updater.UpdateError as exc:
            logger.error("Install failed: %s", exc)
            self._set_idle()
            messagebox.showerror(APP_TITLE, f"The update could not be installed.\n\n{exc}", parent=self)
            return
        # The new version is starting; leave so the old one releases its files.
        self.destroy()
        self.app.destroy()

    def _on_failed(self, exc: BaseException) -> None:
        if not self.winfo_exists():
            return
        self._set_idle()
        if isinstance(exc, updater.UpdateCancelled):
            return
        logger.error("Update download failed: %s", exc)
        if messagebox.askyesno(
            APP_TITLE,
            f"The update could not be downloaded.\n\n{exc}\n\nOpen the download page in your browser instead?",
            parent=self,
        ):
            webbrowser.open(f"{updater.RELEASES_URL}/latest")
