"""The base class of the dialogs and the simple dialogs: export done, a text report, About, and the Quick Check criteria.

Every dialog is created with the window (or another dialog) as its parent and deletes itself when it closes: the parent
owns it, so its lifetime is Qt's and the GUI thread's, never the garbage collector's (docs/qt-widget-ownership.md).
"""

from __future__ import annotations

import logging
import os
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .._version import __version__
from ..config import APP_DEVELOPER_LINE, APP_TITLE, GITHUB_REPO
from ..paths import user_data_dir
from .widgets import ReadOnlyText, make_button

logger = logging.getLogger(__name__)


def open_path(path: Path) -> None:
    """Open a file or folder with the OS default handler."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            import subprocess

            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
    except Exception as exc:
        logger.warning("Could not open %s: %s", path, exc)


def label(text: str = "", role: str = "", *, wrap: bool = False, parent: QWidget | None = None) -> QLabel:
    """A label with a style role from the stylesheet (``muted``, ``title``, ``heading``, ``bad``...)."""
    widget = QLabel(text, parent)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


class Dialog(QDialog):
    """A themed, centred dialog that belongs to its parent and deletes itself when closed. Build it, then ``present()``."""

    def __init__(self, parent: QWidget, title: str, *, modal: bool = True, size: tuple[int, int] | None = None,
                 min_size: tuple[int, int] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(modal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.palette_tokens = parent.palette_tokens  # type: ignore[attr-defined]  # the window and every dialog carry the tokens
        if min_size:
            self.setMinimumSize(*min_size)
        if size:
            self.resize(*size)
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(20, 18, 20, 16)
        self.layout_root.setSpacing(10)

    def present(self) -> None:
        """Show it without blocking: modal to its window, or free-standing when it was made non-modal."""
        if self.isModal():
            self.open()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def button_row(self, *buttons, stretch_left: bool = True) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        if stretch_left:
            row.addStretch(1)
        for button in buttons:
            row.addWidget(button)
        self.layout_root.addLayout(row)
        return row


class ExportDoneDialog(Dialog):
    def __init__(self, parent: QWidget, output: Path) -> None:
        super().__init__(parent, "Export complete", size=(520, 170))
        self.output = output
        self.layout_root.addWidget(label("Excel exported successfully", "title"))
        self.layout_root.addWidget(label(str(output), "muted", wrap=True))
        self.layout_root.addStretch(1)
        self.open_file_button = make_button("Open file", self._open_file, primary=True)
        self.open_folder_button = make_button("Open folder", self._open_folder)
        self.close_button = make_button("Close", self.close)
        self.button_row(self.open_file_button, self.open_folder_button, self.close_button)

    def _open_file(self) -> None:
        open_path(self.output)
        self.close()

    def _open_folder(self) -> None:
        open_path(self.output.parent)
        self.close()


class ReportDialog(Dialog):
    """A heading and a block of selectable text, for the scan details, the keyboard shortcuts and the like."""

    def __init__(self, parent: QWidget, title: str, heading: str, content: str, *, monospace: bool = False) -> None:
        super().__init__(parent, title, size=(680, 460), min_size=(520, 320))
        self.layout_root.addWidget(label(heading, "heading"))
        self.text = ReadOnlyText(monospace=monospace)
        self.text.set_text(content)
        self.layout_root.addWidget(self.text, 1)
        self.button_row(make_button("Close", self.close, primary=True))


class AboutDialog(Dialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, f"About {APP_TITLE}", size=(480, 300))
        self.layout_root.addWidget(label(APP_TITLE, "title"))
        self.layout_root.addWidget(label(f"Version {__version__}", "heading"))
        self.layout_root.addWidget(label(APP_DEVELOPER_LINE, "muted"))
        self.layout_root.addWidget(label("Collects measurements from test logs (text or Excel) and exports them as one Excel "
                                         "workbook.", wrap=True))
        self.layout_root.addWidget(label(f"Your data folder:\n{user_data_dir()}", "muted", wrap=True))
        self.layout_root.addStretch(1)
        row = self.button_row(stretch_left=False)
        row.addWidget(make_button("GitHub page", lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}")))
        row.addWidget(make_button("Open data folder", lambda: open_path(user_data_dir())))
        row.addStretch(1)
        row.addWidget(make_button("Close", self.close, primary=True))


class GrrCriteriaDialog(Dialog):
    """The criteria of the GRR pre-check: for each metric whether it decides, and its limits. Nothing changes until Apply."""

    def __init__(self, parent: QWidget, criteria, on_apply) -> None:
        super().__init__(parent, "Quick Check criteria", min_size=(540, 400))
        from ..grr import QUICK_LABELS

        self.on_apply = on_apply
        self.fields: dict[str, tuple[QCheckBox, QLineEdit, QLineEdit | None]] = {}
        self.layout_root.addWidget(label("GR&R Pre-check · Quick Check criteria", "title"))
        self.layout_root.addWidget(label("Used to colour the preliminary screening table. This does not change formal GR&R calculations.",
                                         "muted", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        for column, text in ((0, "Metric"), (1, "PASS up to"), (2, "FAIL above")):
            grid.addWidget(label(text, "muted"), 0, column)
        for row, criterion in enumerate(criteria, start=1):
            enabled = QCheckBox(QUICK_LABELS[criterion.metric])
            enabled.setChecked(criterion.enabled)
            low = QLineEdit(f"{criterion.pass_limit:g}")
            low.setMaximumWidth(70)
            grid.addWidget(enabled, row, 0)
            if criterion.metric == "ndc":
                cell = QHBoxLayout()
                cell.addWidget(label("minimum", "muted"))
                cell.addWidget(low)
                cell.addStretch(1)
                grid.addLayout(cell, row, 1, 1, 2)
                high = None
            else:
                high = QLineEdit(f"{criterion.fail_limit:g}")
                high.setMaximumWidth(70)
                for column, edit in ((1, low), (2, high)):
                    cell = QHBoxLayout()
                    cell.addWidget(edit)
                    cell.addWidget(label("%", "muted"))
                    cell.addStretch(1)
                    grid.addLayout(cell, row, column)
            self.fields[criterion.metric] = (enabled, low, high)
        self.layout_root.addLayout(grid)
        self.layout_root.addWidget(label("A value up to PASS is PASS; above PASS and up to FAIL is CONDITION; above FAIL is FAIL. An NDC "
                                         "below the minimum is FAIL. A figure that cannot be judged is N/A and never counts as a PASS. "
                                         "The Result is the worst of the metrics used. A metric that is not used stays in the table, "
                                         "without colour, and does not decide the Result.", "note", wrap=True))
        self.error = label("", "bad", wrap=True)
        self.layout_root.addWidget(self.error)
        self.layout_root.addStretch(1)
        row = self.button_row(stretch_left=False)
        row.addWidget(make_button("Reset to defaults", self.reset))
        row.addStretch(1)
        row.addWidget(make_button("Cancel", self.close))
        row.addWidget(make_button("Apply criteria", self.apply, primary=True))

    def reset(self) -> None:
        from ..grr import DEFAULT_QUICK_CRITERIA

        for criterion in DEFAULT_QUICK_CRITERIA:
            enabled, low, high = self.fields[criterion.metric]
            enabled.setChecked(criterion.enabled)
            low.setText(f"{criterion.pass_limit:g}")
            if high is not None:
                high.setText(f"{criterion.fail_limit:g}")
        self.error.setText("")

    def apply(self) -> None:
        from ..grr import QUICK_LABELS, QUICK_METRICS, validate_quick_criteria
        from ..statistics.models import Criterion

        try:
            criteria = []
            for metric in QUICK_METRICS:
                enabled, low, high = self.fields[metric]
                try:
                    limits = (float(low.text()),) * 2 if high is None else (float(low.text()), float(high.text()))
                except ValueError:
                    raise ValueError(f"{QUICK_LABELS[metric]}: enter numbers.") from None
                criteria.append(Criterion(metric, enabled.isChecked(), *limits))
            validate_quick_criteria(criteria)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.on_apply(tuple(criteria))
        self.close()
