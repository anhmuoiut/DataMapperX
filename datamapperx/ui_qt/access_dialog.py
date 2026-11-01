"""Shown when the program may not be used: switched off by its owner, or too long without being able to check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import access
from .dialogs import Dialog, label
from .widgets import make_button

if TYPE_CHECKING:
    from .main_window import MainWindow


class AccessDialog(Dialog):
    """Modal, and the only ways out are to check again or to leave the program."""

    def __init__(self, app: MainWindow, block: access.Block, detail: str = "") -> None:
        super().__init__(app, block.title, size=(540, 240), min_size=(500, 220))
        self.app = app
        self.heading = label("", "title", wrap=True)
        self.message = label("", wrap=True)
        self.detail = label("", "muted", wrap=True)
        for widget in (self.heading, self.message, self.detail):
            self.layout_root.addWidget(widget)
        self.layout_root.addStretch(1)
        self.check_button = make_button("Check again", self._check_again, primary=True)
        self.exit_button = make_button("Exit", self.close)
        self.button_row(self.exit_button, self.check_button)
        self.show_block(block, detail)

    def show_block(self, block: access.Block, detail: str = "") -> None:
        """Show a (new) verdict; also used when a second check comes back with a different answer."""
        self.setWindowTitle(block.title)
        self.heading.setText(block.heading)
        self.message.setText(block.message)
        self.detail.setText(detail)
        self.check_button.setEnabled(True)

    def _check_again(self) -> None:
        self.check_button.setEnabled(False)
        self.detail.setText("Checking…")
        self.app.verify_access()

    def done(self, result: int) -> None:
        if self.app.access_dialog is self:  # closed by the user, not taken away because the answer changed
            self.app.access_dialog = None
            self.app.exit_app()
        super().done(result)

    def withdraw(self) -> None:
        """The owner switched the program back on: go away without leaving the program."""
        if self.app.access_dialog is self:
            self.app.access_dialog = None
        self.close()

