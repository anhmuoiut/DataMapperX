"""The dialog of the Dashboard's "Analyze by Excel File": choose an analysis type (and, for numeric measurements, the method), download
its template or choose a workbook, see whether the file may be analysed, and continue to the analysis.

It only draws, asks for files and runs the checks off the UI thread: what a file is checked for, and what the template holds, is
decided in ``datamapperx/excel_intake.py``. What was chosen is kept in an ``ExcelState`` that the main window holds, so that the
dialog opens the next time as it was left.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPalette
from PySide6.QtWidgets import QComboBox, QFileDialog, QFrame, QHBoxLayout, QRadioButton, QVBoxLayout, QWidget

from ..excel_intake import (
    ATTRIBUTE_SHEET,
    ATTRIBUTE_TEMPLATE,
    EXAMPLES_SHEET,
    INSTRUCTIONS_SHEET,
    OBSERVATIONS_SHEET,
    STATUS_TEXT,
    VARIABLE_TEMPLATE,
    Finding,
    IntakeReport,
    mapping_from_record,
    validate_attribute,
    validate_variable,
    write_attribute_template,
    write_variable_template,
)
from ..statistics.ratings import ImportedRatings, RatingsMapping, read_ratings_table
from .dialogs import Dialog, label
from .tasks import TaskRunner
from .widgets import ElidedLabel, ReadOnlyText, make_badge, make_button, repolish, set_badge

CATEGORIES = (("attribute", "Attribute", "Pass / Fail evaluation"), ("variable", "Variable / Cpk", "Numeric measurements"))
METHODS = (("grr", "Variable GR&&R"), ("capability", "Cpk"))  # the keys of the analysis; && is how a button shows a single &
BADGES = {"ready": "ok", "warnings": "warn", "invalid": "bad"}  # the kinds of set_badge
LEVELS = {"error": "Error", "warning": "Warning", "info": "Note"}
TEMPLATES = {"attribute": (ATTRIBUTE_TEMPLATE, write_attribute_template), "variable": (VARIABLE_TEMPLATE, write_variable_template)}
CHECKS = {"attribute": lambda path, sheet, mapping, method: validate_attribute(path, sheet, mapping),
          "variable": lambda path, sheet, mapping, method: validate_variable(path, method)}  # one layout: no sheet to choose, no columns to map
NOT_DATA = (INSTRUCTIONS_SHEET, EXAMPLES_SHEET)  # the sheets of a template that are never offered as the data
SUBTITLE = "Choose an analysis type, download a template, or upload your existing Excel file."


@dataclass
class ExcelState:
    """What the dialog keeps between openings: the type and method, the file and its sheet, how the columns of ratings were mapped, and
    what was found in the file."""
    category: str | None = None
    method: str | None = None  # "grr" or "capability" for numeric measurements; chosen by the person, never assumed
    path: str = ""
    sheet: str | None = None
    mapping: RatingsMapping | None = None
    report: IntakeReport | None = None

    def clear(self) -> None:
        """Forget everything, in place: the main window holds this very object, and the dialog opens blank the next time."""
        self.category = self.method = self.sheet = self.mapping = self.report = None
        self.path = ""


def unavailable(category: str) -> str:
    """Why an analysis type cannot be used yet (empty when it can). An analysis the program does not run is never offered."""
    if category == "attribute":
        from .validation_workspace import attribute_runnable

        return "" if attribute_runnable() else "Attribute Agreement has not been released yet."
    return ""


class _ChoiceCard(QFrame):
    """One of the analysis types: a title and a line, the whole card is the button (a click, or Enter / Space with the keyboard)."""

    clicked = Signal()

    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("choiceCard")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(body)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 10)
        column.setSpacing(2)
        self.title, self.body = label(title, "choice"), label(body, "cardBody")
        for widget in (self.title, self.body):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # a click on any part is a click on the card
            column.addWidget(widget)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        repolish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class ExcelAnalysisDialog(Dialog):
    def __init__(self, parent: QWidget, state: ExcelState, on_continue: Callable[[ExcelState], None]) -> None:
        super().__init__(parent, "Analyze by Excel File", size=(660, 540), min_size=(600, 480))
        self.state, self.on_continue = state, on_continue
        self.tasks = TaskRunner(self)
        self._generation = 0  # moves with every check: the answer of an older one is thrown away
        self._checking = False

        head = QHBoxLayout()
        head.addWidget(label("Analyze by Excel File", "title"))
        head.addStretch(1)
        self.reset_button = make_button("↺  Reset", self._reset)
        self.reset_button.setProperty("glyphs", True)  # the arrow is not in the interface font
        self.reset_button.setAccessibleName("Reset")
        self.reset_button.setToolTip("Forget the type, the file and what was found, and start again. "
                                     "Data that are already open in the analysis stay as they are.")
        head.addWidget(self.reset_button)
        self.layout_root.addLayout(head)
        self.layout_root.addWidget(label(SUBTITLE, "muted", wrap=True))
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.cards: dict[str, _ChoiceCard] = {}
        for key, title, body in CATEGORIES:
            card = _ChoiceCard(title, body)
            reason = unavailable(key)
            card.setEnabled(not reason)
            card.setToolTip(reason)
            card.clicked.connect(lambda key=key: self._select(key))
            cards.addWidget(card, 1)
            self.cards[key] = card
        self.layout_root.addLayout(cards)

        self.method_row = QWidget()  # numeric measurements are Gage R&R or Cpk: their data are laid out differently, so the person says
        row = QHBoxLayout(self.method_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(label("Analysis", "muted"))
        self.method_buttons: dict[str, QRadioButton] = {}
        palette = QPalette()
        if self.palette_tokens.mode == "dark":  # as the Value check box: Fusion draws an unchecked one a shade darker than the window
            palette.setColor(QPalette.ColorRole.Window, QColor(self.palette_tokens.muted))  # colour, which here is the dialog's own
        for key, text in METHODS:
            button = QRadioButton(text, self.method_row)
            button.setPalette(palette)
            button.toggled.connect(lambda checked, key=key: self._set_method(key) if checked else None)
            row.addWidget(button)
            self.method_buttons[key] = button
        row.addStretch(1)
        self.layout_root.addWidget(self.method_row)

        self.download_button = make_button("Download Template", self._download)
        self.choose_button = make_button("Choose Excel File…", self._choose, primary=True)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.download_button)
        row.addWidget(self.choose_button)
        row.addStretch(1)
        self.layout_root.addLayout(row)

        self.file_label = ElidedLabel("", "muted", mode=Qt.TextElideMode.ElideMiddle)  # a path can be longer than the dialog
        self.sheet_label = label("Sheet", "muted")
        self.sheet_box = QComboBox()
        self.sheet_box.setMinimumWidth(130)
        self.sheet_box.activated.connect(lambda _index: self._sheet_chosen())
        self.review_button = make_button("Review columns…", self._review)
        self.again_button = make_button("Check again", self._check)
        row = QHBoxLayout()
        row.setSpacing(8)
        for widget, stretch in ((self.file_label, 1), (self.sheet_label, 0), (self.sheet_box, 0), (self.review_button, 0),
                                (self.again_button, 0)):
            row.addWidget(widget, stretch)
        self.layout_root.addLayout(row)

        self.status = make_badge()  # the same pill as the state beside the title of the other screens
        self.summary = label("", "muted", wrap=True)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.status, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.summary, 1)
        self.layout_root.addLayout(row)
        self.findings = ReadOnlyText()
        self.layout_root.addWidget(self.findings, 1)
        self.layout_root.addStretch(0)  # takes the room while there is nothing to list (a file with no findings)
        self.note = label("", "muted", wrap=True)  # the template that was saved, or why it could not be
        self.layout_root.addWidget(self.note)
        self.continue_button = make_button("Continue to Analysis  →", self._continue, primary=True)
        self.continue_button.setAccessibleName("Continue to Analysis")
        self.button_row(make_button("Close", self.close), self.continue_button)
        self._render()

    def closeEvent(self, event) -> None:
        self.tasks.close()  # no worker may deliver into a dialog that is going away
        super().closeEvent(event)

    # ------------------------------------------------------------------ what is shown
    def _usable(self) -> bool:
        """Whether a file can be checked: the type is chosen, and for numeric measurements the method too."""
        state = self.state
        return state.category is not None and (state.category != "variable" or state.method is not None)

    def _render(self) -> None:
        state, report = self.state, self.state.report
        free = not self._checking
        for key, card in self.cards.items():
            card.set_selected(key == state.category)
            card.setEnabled(free and not unavailable(key))
        self.method_row.setVisible(state.category == "variable")
        for key, button in self.method_buttons.items():
            button.blockSignals(True)  # the choice is the person's; showing it back is not a new choice
            button.setAutoExclusive(False)  # an exclusive radio button cannot be unchecked: a reset has to
            button.setChecked(state.method == key)
            button.setAutoExclusive(True)
            button.blockSignals(False)
            button.setEnabled(free)
        has_file = self._usable() and bool(state.path)
        self.reset_button.setEnabled(state.category is not None or bool(state.path))
        self.download_button.setEnabled(free and state.category is not None)
        self.choose_button.setEnabled(free and self._usable())
        self.again_button.setEnabled(free and has_file)
        self.again_button.setVisible(has_file)  # nothing to check again before there is a file
        self.review_button.setVisible(has_file and state.category == "attribute")  # the RawData layout has no columns to map
        self.review_button.setEnabled(free and has_file)
        self.continue_button.setEnabled(free and report is not None and report.ready)
        self.file_label.setText(state.path)
        shown = report is not None and not self._checking
        sheets = [name for name in report.sheets if name not in NOT_DATA] if shown else []
        self.sheet_label.setVisible(bool(sheets))
        self.sheet_box.setVisible(bool(sheets))
        self.sheet_box.blockSignals(True)
        self.sheet_box.clear()
        self.sheet_box.addItems(sheets)
        self.sheet_box.setCurrentText(report.sheet if shown else "")
        self.sheet_box.blockSignals(False)
        self.sheet_box.setEnabled(free)
        set_badge(self.status, STATUS_TEXT[report.status] if shown else "", BADGES[report.status] if shown else "neutral")
        counts = [f"{report.count(kind)} {noun}{'' if report.count(kind) == 1 else 's'}" for kind, noun in
                  (("error", "error"), ("warning", "warning")) if shown and report.count(kind)]
        self.summary.setText(f"Checking {Path(state.path).name}…" if self._checking else
                             "  ·  ".join(([report.summary] if shown and report.summary else []) + counts))
        self.findings.set_text("\n".join(self._line(finding) for finding in report.findings) if shown else "")
        self.findings.setVisible(bool(self.findings.toPlainText()))  # nothing to list: no empty box

    @staticmethod
    def _line(finding: Finding) -> str:
        return f"{LEVELS[finding.severity]} | {finding}"

    def _say(self, text: str) -> None:
        self.note.setText(text)

    # ------------------------------------------------------------------ what is asked
    def _restart(self) -> None:
        """What was found belongs to the type, method and sheet it was found for: choosing another starts again (with the same file)."""
        self.state.sheet, self.state.mapping, self.state.report = None, None, None
        self._say("")
        if self.state.path and self._usable():
            self._check()
        else:
            self._render()

    def _reset(self) -> None:
        """Start again whenever the old file and choices are not wanted. A check still reading is forgotten (its answer is thrown
        away); the data already open in the analysis are not touched, they are replaced only by continuing with another file."""
        self._generation += 1
        self._checking = False
        self.state.clear()
        self._say("")
        self._render()

    def _select(self, key: str) -> None:
        if key == self.state.category or unavailable(key):
            return
        self.state.category = key
        self._restart()

    def _set_method(self, key: str) -> None:
        if key != self.state.method:
            self.state.method = key
            self._restart()

    def _sheet_chosen(self) -> None:
        self.state.sheet, self.state.mapping = self.sheet_box.currentText() or None, None
        self._check()

    def _download(self) -> None:
        name, write = TEMPLATES[self.state.category]
        path, _ = QFileDialog.getSaveFileName(self, "Save the template", name, "Excel workbook (*.xlsx)")
        if not path:
            return
        path = path if path.lower().endswith(".xlsx") else path + ".xlsx"
        self._say(f"Saving {Path(path).name}…")
        self.tasks.run(lambda _report: write(path), on_success=lambda saved: self._say(f"Template saved: {saved}"),
                       on_error=lambda exc: self._say(f"The template could not be saved: {exc}"))

    def _choose(self) -> None:
        start = str(Path(self.state.path).parent) if self.state.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose an Excel file", start, "Excel workbook (*.xlsx)")
        if path:
            self.state.path, self.state.sheet, self.state.mapping = path, None, None
            self._check()

    def _check(self) -> None:
        """Read and check the file on a worker; the dialog shows what was found when the answer comes."""
        state = self.state
        if not self._usable() or not state.path:
            return
        self._generation += 1
        generation, path, sheet, mapping, method = self._generation, state.path, state.sheet, state.mapping, state.method
        check = CHECKS[state.category]
        state.report, self._checking = None, True
        self._say("")
        self._render()

        def finish(report: IntakeReport) -> None:
            if generation == self._generation:
                state.report, self._checking = report, False
                self._render()

        self.tasks.run(lambda _report: check(path, sheet, mapping, method), on_success=finish,
                       on_error=lambda exc: finish(IntakeReport(path, (Finding("error", f"The file could not be checked: {exc}"),))))

    def _review(self) -> None:
        """The column dialog of the ratings import: map the columns, count labels as categories, then check the file again."""
        path = self.state.path
        sheet = self.state.sheet or (self.state.report.sheet if self.state.report else "")

        def opened(table) -> None:
            from .ratings_import import RatingsImportDialog

            RatingsImportDialog(self, table, self._reviewed).present()

        self.tasks.run(lambda _report: read_ratings_table(path, sheet or ATTRIBUTE_SHEET, (OBSERVATIONS_SHEET,)), on_success=opened,
                       on_error=lambda exc: self._say(f"The file could not be read: {exc}"))

    def _reviewed(self, imported: ImportedRatings) -> None:
        self.state.sheet, self.state.mapping = imported.record["sheet"], mapping_from_record(imported.record)
        self._check()

    def _continue(self) -> None:
        if self.state.report is not None and self.state.report.ready:
            self.close()
            self.on_continue(self.state)
