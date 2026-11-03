"""What the tests of "Analyze by Excel File" do with its dialog: open it, choose a type, method and file, wait for the check."""
from __future__ import annotations

from datamapperx.ui.excel_analysis_dialog import ExcelAnalysisDialog

from .support import pump


def open_dialog(window, dialogs) -> ExcelAnalysisDialog:
    window.start_excel_analysis()
    return dialogs[-1]


def checked(app, dialog) -> None:
    pump(app, lambda: not dialog._checking)


def choose(app, dialog, picks, path, category: str = "attribute", method: str | None = None) -> None:
    """Choose the type (and for numeric measurements the method) and then the file, as the person does, and wait for the check."""
    dialog.cards[category].clicked.emit()
    if method:
        dialog.method_buttons[method].setChecked(True)
    picks.open = str(path)
    dialog.choose_button.click()
    checked(app, dialog)


def lines(dialog) -> list[str]:
    return dialog.findings.toPlainText().splitlines()
