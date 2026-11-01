"""Release notes + download/install progress for an available update."""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QProgressBar
from shiboken6 import isValid

from .. import updater
from .._version import __version__
from ..config import APP_TITLE
from .dialogs import Dialog, label
from .widgets import ReadOnlyText, make_button

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


class UpdateDialog(Dialog):
    def __init__(self, app: MainWindow, info: updater.UpdateInfo, *, mandatory: bool) -> None:
        super().__init__(app, "Update required" if mandatory else "Update available", size=(580, 470), min_size=(520, 380))
        self.app, self.info, self.mandatory = app, info, mandatory
        self._cancel = threading.Event()
        self._downloading = False

        heading = "This version is no longer supported" if mandatory else f"{APP_TITLE} {info.version} is available"
        detail = f"You are running {__version__}."
        if mandatory:
            detail += f" Version {info.version} is required to continue."
        if info.published_at:
            detail += f"  Released {info.published_at[:10]}."
        self.layout_root.addWidget(label(heading, "title", wrap=True))
        self.layout_root.addWidget(label(detail, "muted", wrap=True))
        self.notes = ReadOnlyText()
        self.notes.set_markdown(info.notes or "No release notes were provided.")
        self.layout_root.addWidget(self.notes, 1)

        self.progress_label = label("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_label.hide()
        self.progress_bar.hide()
        self.layout_root.addWidget(self.progress_label)
        self.layout_root.addWidget(self.progress_bar)

        self.update_button = make_button("Update now", self._update_now, primary=True)
        self.buttons = [self.update_button]
        row = self.button_row(stretch_left=False)
        if mandatory:
            self.exit_button = make_button(f"Exit {APP_TITLE}", self._exit_app)
            self.buttons.append(self.exit_button)
            row.addStretch(1)
            row.addWidget(self.exit_button)
        else:
            self.skip_button = make_button("Skip this version", self._skip)
            self.later_button = make_button("Later", self.close)
            self.buttons += [self.skip_button, self.later_button]
            row.addWidget(self.skip_button)
            row.addStretch(1)
            row.addWidget(self.later_button)
        row.addWidget(self.update_button)

    # ------------------------------------------------------------------ actions
    def _skip(self) -> None:
        self.app.skip_update(self.info.version)
        self.close()

    def _exit_app(self) -> None:
        self.mandatory = False  # so that closing the dialog does not ask to exit a second time
        self.close()
        self.app.exit_app()

    def done(self, result: int) -> None:
        if self._downloading:  # closing during the download cancels it, and the dialog stays until it has stopped
            self._cancel.set()
            return
        if self.mandatory:
            self.mandatory = False
            self.app.exit_app()
        super().done(result)

    def _set_idle(self) -> None:
        self._downloading = False
        self.progress_label.hide()
        self.progress_bar.hide()
        for button in self.buttons:
            button.setEnabled(True)

    def _update_now(self) -> None:
        if self.app.is_busy:
            QMessageBox.information(self, APP_TITLE, "Please wait for the current scan or export to finish, then update.")
            return

        if not updater.can_self_update():
            webbrowser.open(f"{updater.RELEASES_URL}/latest")
            QMessageBox.information(
                self, APP_TITLE,
                "This copy cannot update itself (it is not an installed .exe, or its folder is read-only).\n\n"
                "The download page has been opened. Replace DataMapperX.exe with the new file.")
            if self.mandatory:
                self._exit_app()
            return

        self._downloading = True
        self._cancel.clear()
        for button in self.buttons:
            button.setEnabled(False)
        self.progress_label.setText("Downloading…")
        self.progress_bar.setValue(0)
        self.progress_label.show()
        self.progress_bar.show()

        destination = updater.staging_path()
        cancel = self._cancel
        self.app.tasks.run(
            lambda report: updater.download_update(self.info, destination, progress=report, cancel_event=cancel),
            on_progress=self._on_progress,
            on_success=lambda _result: self._on_downloaded(destination),
            on_error=self._on_failed,
        )

    def _on_progress(self, done: int, total: int) -> None:
        if not isValid(self):
            return
        if total:
            self.progress_bar.setValue(int(done * 100 / total))
            self.progress_label.setText(f"Downloading… {done / 1_048_576:.1f} of {total / 1_048_576:.1f} MB")
        else:
            self.progress_label.setText(f"Downloading… {done / 1_048_576:.1f} MB")

    def _on_downloaded(self, destination) -> None:
        if not isValid(self):
            return
        self.progress_label.setText("Installing…")
        self.progress_bar.setValue(100)
        try:
            updater.install_update(destination)
        except updater.UpdateError as exc:
            logger.error("Install failed: %s", exc)
            self._set_idle()
            QMessageBox.critical(self, APP_TITLE, f"The update could not be installed.\n\n{exc}")
            return
        # The new version is starting; leave so the old one releases its files.
        self._downloading = False
        self.mandatory = False
        self.close()
        self.app.exit_app()

    def _on_failed(self, exc: BaseException) -> None:
        if not isValid(self):
            return
        self._set_idle()
        if isinstance(exc, updater.UpdateCancelled):
            return
        logger.error("Update download failed: %s", exc)
        if QMessageBox.question(
            self, APP_TITLE,
            f"The update could not be downloaded.\n\n{exc}\n\nOpen the download page in your browser instead?",
        ) == QMessageBox.StandardButton.Yes:
            webbrowser.open(f"{updater.RELEASES_URL}/latest")
