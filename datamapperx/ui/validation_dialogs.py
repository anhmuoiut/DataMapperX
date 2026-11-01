"""Dialogs of the Validation & Reports workspace: file assignments, the calendar, and customer criteria."""

from __future__ import annotations

import calendar
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QWidget,
)

from ..statistics import (
    BUILTIN_CUSTOMERS,
    CRITERION_METRICS,
    DEFAULT_CUSTOMER,
    DEFAULT_LIMITS,
    Criterion,
    describe_criterion,
    normalize_records,
    validate_criteria,
)
from .dialogs import Dialog, label
from .widgets import make_button

if TYPE_CHECKING:
    from .validation_workspace import ValidationWorkspace


class AssignmentDialog(Dialog):
    """Explicit file-level study identities, without editing parsed/raw data."""

    FIELDS = ("sample_id", "trial", "tester", "operator", "slot", "subgroup", "timestamp")

    def __init__(self, panel: ValidationWorkspace) -> None:
        super().__init__(panel._dialog_parent(), "File assignments", size=(850, 580), min_size=(650, 400))
        self.panel = panel
        self.pending = {source: dict(values) for source, values in panel.assignments.items()}
        self.records = [r for records in panel.grouped.values() for r in records]
        self.defaults = {str(row.source): row for row in normalize_records(panel.grouped, panel.components[:1])}
        self.edits = {field: QLineEdit() for field in self.FIELDS}
        self.current: int | None = None
        self.layout_root.addWidget(label("Select each logfile and explicitly assign study identities. Apply saves only analysis "
                                         "metadata.", wrap=True))
        body = QHBoxLayout()
        self.files = QListWidget()
        self.files.addItems([f"{record.sn} · {record.filename}" for record in self.records])
        self.files.currentRowChanged.connect(self.select)
        body.addWidget(self.files, 1)
        editor = QGridLayout()
        for row, field in enumerate(self.FIELDS):
            editor.addWidget(label(field.replace("_", " ").title()), row * 2, 0)
            self.edits[field].setMinimumWidth(220)
            editor.addWidget(self.edits[field], row * 2 + 1, 0)
        editor.addWidget(make_button("Save file assignments", self.save_current), len(self.FIELDS) * 2, 0)
        editor.setRowStretch(len(self.FIELDS) * 2 + 1, 1)
        body.addLayout(editor)
        self.layout_root.addLayout(body, 1)
        self.button_row(make_button("Apply", self.apply, primary=True))

    def save_current(self) -> None:
        if self.current is not None and 0 <= self.current < len(self.records):
            source = str(self.records[self.current].path)
            default = self.defaults.get(source)
            changes = {k: edit.text().strip() for k, edit in self.edits.items() if edit.text().strip() != str(getattr(default, k, ""))}
            if changes:
                self.pending[source] = changes
            else:
                self.pending.pop(source, None)

    def select(self, row: int) -> None:
        if row < 0 or row >= len(self.records):
            return
        self.save_current()
        self.current = row
        record = self.records[row]
        # Show the identities the logs give, so that untouched ones are retained.
        mapped = self.defaults.get(str(record.path))
        saved = self.pending.get(str(record.path), {})
        for field, edit in self.edits.items():
            edit.setText(saved.get(field, str(getattr(mapped, field, "")) if mapped else (record.sn if field == "sample_id" else "")))

    def apply(self) -> None:
        self.save_current()
        self.panel.assignments = self.pending
        self.panel.data_edited()
        self.close()


class DatePickerDialog(Dialog):
    """A month calendar to choose a day from; ``on_pick`` receives the chosen date."""

    def __init__(self, parent: QWidget, current: date, on_pick) -> None:
        super().__init__(parent, "Choose a date")
        self.on_pick, self.selected = on_pick, current
        self.shown = current.replace(day=1)
        header = QHBoxLayout()
        header.setSpacing(2)
        for text, step in (("«", -12), ("‹", -1)):
            header.addWidget(self._step_button(text, step))
        self.month_label = label("", "heading")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.month_label, 1)
        for text, step in (("›", 1), ("»", 12)):
            header.addWidget(self._step_button(text, step))
        self.layout_root.addLayout(header)
        self.days = QGridLayout()
        self.days.setSpacing(2)
        self.layout_root.addLayout(self.days)
        footer = QHBoxLayout()
        footer.addWidget(make_button("Today", lambda: self.pick(date.today())))
        footer.addStretch(1)
        footer.addWidget(make_button("Cancel", self.close))
        self.layout_root.addLayout(footer)
        self._render()

    def _step_button(self, text: str, step: int) -> QPushButton:
        button = make_button(text, lambda: self._move(step))
        button.setFixedWidth(34)
        return button

    def _move(self, months: int) -> None:
        index = self.shown.year * 12 + self.shown.month - 1 + months
        self.shown = date(index // 12, index % 12 + 1, 1) if 1 <= index // 12 <= 9998 else self.shown
        self._render()

    def _render(self) -> None:
        self.month_label.setText(f"{calendar.month_name[self.shown.month]} {self.shown.year}")
        while self.days.count():
            item = self.days.takeAt(0)
            if item.widget():
                item.widget().hide()  # gone at once for the person; deleted when the event loop is next free
                item.widget().deleteLater()
        for column, name in enumerate(calendar.day_abbr):
            heading = label(name[:2], "muted")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.days.addWidget(heading, 0, column)
        for row, week in enumerate(calendar.Calendar().monthdayscalendar(self.shown.year, self.shown.month), start=1):
            for column, number in enumerate(week):
                if number:
                    day = self.shown.replace(day=number)
                    button = make_button(str(number), lambda day=day: self.pick(day), primary=day == self.selected)
                    button.setFixedWidth(38)
                    self.days.addWidget(button, row, column)

    def pick(self, day: date) -> None:
        self.on_pick(day)
        self.close()


class CustomersDialog(Dialog):
    """Per-customer Gage R&R acceptance: which metrics apply, and the PASS / CONDITIONAL PASS / FAIL limits of each."""

    NAMES = {"percent_tolerance": "%SV/Tol", "percent_study_var": "%Study Var", "ndc": "NDC"}

    def __init__(self, panel: ValidationWorkspace) -> None:
        super().__init__(panel._dialog_parent(), "Customer acceptance criteria (optional)", size=(800, 470), min_size=(780, 430))
        self.panel = panel
        self.working = {name: tuple(criteria) for name, criteria in panel.customers.items()}  # edited copy, saved on request
        self.current = panel.profile_var.get() if panel.profile_var.get() in self.working else DEFAULT_CUSTOMER
        self.combo = QComboBox()
        self.combo.addItems(list(self.working))
        self.combo.setCurrentText(self.current)
        self.combo.setMinimumWidth(200)
        self.combo.activated.connect(lambda _index: self._switch())
        self.delete_button = make_button("Delete", self.delete_customer)
        self.reset_button = make_button("Reset to default", self.reset_customer)
        self.new_edit = QLineEdit()
        self.new_edit.setMinimumWidth(200)
        self.apply_checks = {m: QCheckBox() for m in CRITERION_METRICS}
        self.pass_edits = {m: QLineEdit() for m in CRITERION_METRICS}
        self.fail_edits = {m: QLineEdit() for m in CRITERION_METRICS}
        self.bands = {m: label("") for m in CRITERION_METRICS}

        top = QGridLayout()
        top.setHorizontalSpacing(8)
        top.addWidget(label("Customer"), 0, 0)
        top.addWidget(self.combo, 0, 1)
        top.addWidget(self.delete_button, 0, 2)
        top.addWidget(self.reset_button, 0, 3)
        top.addWidget(label("New customer"), 1, 0)
        top.addWidget(self.new_edit, 1, 1)
        top.addWidget(make_button("Add (copy of selected)", self.add_customer), 1, 2, 1, 2)
        top.setColumnStretch(4, 1)
        self.layout_root.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for column, text in enumerate(("Apply", "Metric", "PASS", "FAIL", "Result bands")):
            grid.addWidget(label(text, "heading"), 0, column)
        for row, metric in enumerate(CRITERION_METRICS, start=1):
            ndc = metric == "ndc"
            grid.addWidget(self.apply_checks[metric], row, 0)
            grid.addWidget(label(self.NAMES[metric]), row, 1)
            for column, (edit, caption) in enumerate(((self.pass_edits[metric], "at least" if ndc else "below"),
                                                      (self.fail_edits[metric], "below" if ndc else "above")), start=2):
                edit.setMaximumWidth(70)
                cell = QHBoxLayout()
                cell.addWidget(label(caption, "muted"))
                cell.addWidget(edit)
                cell.addWidget(label("" if ndc else "%", "muted"))
                grid.addLayout(cell, row, column)
                edit.textChanged.connect(lambda _text, m=metric: self._refresh_band(m))
            grid.addWidget(self.bands[metric], row, 4)
        grid.setColumnStretch(4, 1)
        self.layout_root.addLayout(grid)
        self.layout_root.addWidget(label(
            "The overall result is the worst of the applied metrics: any FAIL gives FAIL, otherwise any CONDITIONAL PASS gives "
            "CONDITIONAL PASS, otherwise PASS. Values between the PASS and FAIL limits are CONDITIONAL PASS. A metric that is not "
            "applied does not decide, but if it would FAIL on its own limits the result is flagged for review. Criteria are an optional "
            "layer on top of the statistics: they never change a calculated value. The built-in customers are starting points "
            "taken from Jabil's work instruction for reference (SolarEdge and Zebra: %SV/Tol only; SES: NDC and %SV/Tol; Jabil: "
            "all three); edit them or add your own.", "muted", wrap=True))
        self.layout_root.addStretch(1)
        self.button_row(make_button("Cancel", self.close), make_button("Save and use", self.save, primary=True))
        self._load(self.current)

    # -- form <-> working copy
    def _load(self, name: str) -> None:
        self.current = name
        by_metric = {c.metric: c for c in self.working[name]}
        for metric in CRITERION_METRICS:
            c = by_metric.get(metric) or Criterion(metric, False, *DEFAULT_LIMITS[metric])
            self.apply_checks[metric].setChecked(c.enabled)
            self.pass_edits[metric].setText(f"{c.pass_limit:g}")
            self.fail_edits[metric].setText(f"{c.fail_limit:g}")
        builtin = name in BUILTIN_CUSTOMERS
        self.delete_button.setEnabled(not builtin)
        self.reset_button.setEnabled(builtin)

    def _read(self) -> tuple[Criterion, ...]:
        criteria = []
        for metric in CRITERION_METRICS:
            try:
                limits = (float(self.pass_edits[metric].text()), float(self.fail_edits[metric].text()))
            except ValueError:
                raise ValueError(f"{self.NAMES[metric]}: enter the PASS and FAIL limits as numbers.") from None
            criteria.append(Criterion(metric, self.apply_checks[metric].isChecked(), *limits))
        criteria = tuple(criteria)
        validate_criteria(criteria)
        return criteria

    def _store(self) -> bool:
        """Keep the form in the working copy. A bad value is reported and the form stays where it is."""
        try:
            self.working[self.current] = self._read()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid criteria", str(exc))
            return False
        return True

    def _refresh_band(self, metric: str) -> None:
        try:
            text = describe_criterion(Criterion(metric, True, float(self.pass_edits[metric].text()), float(self.fail_edits[metric].text())))
            self.bands[metric].setText(text.split(": ", 1)[1])
        except (ValueError, KeyError):
            self.bands[metric].setText("enter numbers")

    def _refill_combo(self, selected: str) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(list(self.working))
        self.combo.setCurrentText(selected)
        self.combo.blockSignals(False)

    # -- actions
    def _switch(self) -> None:
        target = self.combo.currentText()
        if target == self.current:
            return
        if self._store():
            self._load(target)
        else:
            self.combo.setCurrentText(self.current)

    def add_customer(self) -> None:
        name = " ".join(self.new_edit.text().split())
        if not name or len(name) > 40:
            QMessageBox.warning(self, "New customer", "Enter a customer name of up to 40 characters.")
        elif name.casefold() in {n.casefold() for n in self.working}:
            QMessageBox.warning(self, "New customer", f"'{name}' already exists.")
        elif self._store():
            self.working[name] = self.working[self.current]
            self._refill_combo(name)
            self.new_edit.setText("")
            self._load(name)

    def delete_customer(self) -> None:
        if self.current in BUILTIN_CUSTOMERS:
            return
        del self.working[self.current]
        self._refill_combo(DEFAULT_CUSTOMER)
        self._load(DEFAULT_CUSTOMER)

    def reset_customer(self) -> None:
        if self.current in BUILTIN_CUSTOMERS:
            self.working[self.current] = BUILTIN_CUSTOMERS[self.current]
            self._load(self.current)

    def save(self) -> None:
        if self._store():
            self.panel.set_customers(self.working, selected=self.current)
            self.close()
