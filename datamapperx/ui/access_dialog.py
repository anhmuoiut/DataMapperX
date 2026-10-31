"""Shown when the program may not be used: switched off by its owner, or too long without being able to check."""

from __future__ import annotations

from tkinter import ttk
from typing import TYPE_CHECKING

from .. import access
from .dialogs import Dialog

if TYPE_CHECKING:
    from .main_window import MainWindow

_WRAP = 450


class AccessDialog(Dialog):
    """Modal, and the only ways out are to check again or to leave the program."""

    def __init__(self, app: MainWindow, block: access.Block, detail: str = ""):
        super().__init__(app, block.title, min_size=(500, 220))
        self.app = app

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        self.heading = ttk.Label(body, font=("Segoe UI Semibold", 14), wraplength=_WRAP, justify="left")
        self.heading.grid(row=0, column=0, sticky="w")
        self.message = ttk.Label(body, wraplength=_WRAP, justify="left")
        self.message.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.detail = ttk.Label(body, style="Muted.TLabel", wraplength=_WRAP, justify="left")
        self.detail.grid(row=2, column=0, sticky="nw", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        self.check_button = ttk.Button(buttons, text="Check again", style="Accent.TButton", command=self._check_again)
        self.check_button.pack(side="right")
        self.exit_button = ttk.Button(buttons, text="Exit", command=self.close)
        self.exit_button.pack(side="right", padx=(0, 8))

        self.show(block, detail)
        self.present(width=540)

    def show(self, block: access.Block, detail: str = "") -> None:
        """Show a (new) verdict; also used when a second check comes back with a different answer."""
        self.title(block.title)
        self.heading.configure(text=block.heading)
        self.message.configure(text=block.message)
        self.detail.configure(text=detail)
        self.check_button.configure(state="normal")

    def _check_again(self) -> None:
        self.check_button.configure(state="disabled")
        self.detail.configure(text="Checking…")
        self.app.verify_access()

    def close(self) -> None:
        self.app.exit_app()
