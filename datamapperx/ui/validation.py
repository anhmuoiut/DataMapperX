"""Dialogs of the Validation & Reports workspace: file assignments and customer criteria."""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

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
from .dialogs import Dialog

if TYPE_CHECKING:
    from .validation_workspace import ValidationWorkspace


class AssignmentDialog(Dialog):
    """Explicit file-level study identities, without editing parsed/raw data."""

    FIELDS = ("sample_id", "trial", "tester", "operator", "slot", "subgroup", "timestamp")

    def __init__(self, panel: ValidationWorkspace):
        super().__init__(panel._dialog_parent(), "File assignments", min_size=(650, 400))
        self.panel = panel
        self.pending = {source: dict(values) for source, values in panel.assignments.items()}
        self.records = [r for records in panel.grouped.values() for r in records]
        self.defaults = {str(row.source): row for row in normalize_records(
            panel.grouped, panel.components[:1],
        )}
        self.variables = {field: tk.StringVar() for field in self.FIELDS}
        self.current = None
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="Select each logfile and explicitly assign study identities. Apply saves only analysis metadata.", wraplength=700).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.files = tk.Listbox(body, exportselection=False)
        self.files.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.files.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.files.configure(yscrollcommand=scroll.set)
        for record in self.records:
            self.files.insert("end", f"{record.sn} · {record.filename}")
        editor = ttk.Frame(body)
        editor.grid(row=1, column=2, sticky="ns")
        for row, field in enumerate(self.FIELDS):
            ttk.Label(editor, text=field.replace("_", " ").title()).grid(row=row * 2, column=0, sticky="w")
            ttk.Entry(editor, textvariable=self.variables[field], width=26).grid(row=row * 2 + 1, column=0, pady=(0, 8))
        ttk.Button(editor, text="Save file assignments", command=self.save_current).grid(row=14, column=0, pady=4)
        ttk.Button(body, text="Apply", command=self.apply, style="Accent.TButton").grid(row=2, column=2, sticky="e", pady=(10, 0))
        self.files.bind("<<ListboxSelect>>", self.select)
        self.present(width=850, height=580)

    def save_current(self):
        if self.current is not None:
            source = str(self.records[self.current].path)
            default = self.defaults.get(source)
            changes = {k: v.get().strip() for k, v in self.variables.items()
                       if v.get().strip() != str(getattr(default, k, ""))}
            if changes:
                self.pending[source] = changes
            else:
                self.pending.pop(source, None)

    def select(self, *_):
        selected = self.files.curselection()
        if not selected:
            return
        self.save_current()
        self.current = selected[0]
        record = self.records[self.current]
        # Show the identities the logs give, so that untouched ones are retained.
        mapped = self.defaults.get(str(record.path))
        saved = self.pending.get(str(record.path), {})
        for field, variable in self.variables.items():
            variable.set(saved.get(field, str(getattr(mapped, field, "")) if mapped else (record.sn if field == "sample_id" else "")))

    def apply(self):
        self.save_current()
        self.panel.assignments = self.pending
        self.panel.data_edited()
        self.close()


DATE_FORMAT = "%d-%m-%Y"  # DD-MM-YYYY, as the date of study is printed


class DatePickerDialog(Dialog):
    """A month calendar to choose a day from; ``on_pick`` receives the chosen date."""

    def __init__(self, parent: tk.Misc, current: date, on_pick):
        super().__init__(parent, "Choose a date")
        self.on_pick, self.selected = on_pick, current
        self.shown = current.replace(day=1)
        body = ttk.Frame(self, padding=12)
        body.pack()
        header = ttk.Frame(body)
        header.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 6))
        for text, step, side in (("«", -12, "left"), ("‹", -1, "left"), ("»", 12, "right"), ("›", 1, "right")):
            ttk.Button(header, text=text, width=3, command=lambda step=step: self._move(step)).pack(side=side, padx=1)
        self.month_label = ttk.Label(header, anchor="center", font=("Segoe UI Semibold", 11))
        self.month_label.pack(side="left", fill="x", expand=True)
        for column, name in enumerate(calendar.day_abbr):
            ttk.Label(body, text=name[:2], style="Muted.TLabel", anchor="center").grid(row=1, column=column, padx=1)
        self.days = ttk.Frame(body)
        self.days.grid(row=2, column=0, columnspan=7)
        footer = ttk.Frame(body)
        footer.grid(row=3, column=0, columnspan=7, sticky="ew", pady=(8, 0))
        ttk.Button(footer, text="Today", command=lambda: self.pick(date.today())).pack(side="left")
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self._render()
        self.present()

    def _move(self, months: int) -> None:
        index = self.shown.year * 12 + self.shown.month - 1 + months
        self.shown = date(index // 12, index % 12 + 1, 1) if 1 <= index // 12 <= 9998 else self.shown
        self._render()

    def _render(self) -> None:
        self.month_label.configure(text=f"{calendar.month_name[self.shown.month]} {self.shown.year}")
        for widget in self.days.winfo_children():
            widget.destroy()
        for row, week in enumerate(calendar.Calendar().monthdayscalendar(self.shown.year, self.shown.month)):
            for column, number in enumerate(week):
                if number:
                    day = self.shown.replace(day=number)
                    ttk.Button(self.days, text=str(number), width=3, command=lambda day=day: self.pick(day),
                               style="Accent.TButton" if day == self.selected else "TButton").grid(row=row, column=column, padx=1, pady=1)

    def pick(self, day: date) -> None:
        self.on_pick(day)
        self.close()


class CustomersDialog(Dialog):
    """Per-customer Gage R&R acceptance: which metrics apply, and the PASS / CONDITIONAL PASS / FAIL limits of each."""

    NAMES = {"percent_tolerance": "%SV/Tol", "percent_study_var": "%Study Var", "ndc": "NDC"}

    def __init__(self, panel: ValidationWorkspace):
        super().__init__(panel._dialog_parent(), "Customer acceptance criteria (optional)", min_size=(780, 430))
        self.panel = panel
        self.working = {name: tuple(criteria) for name, criteria in panel.customers.items()}  # edited copy, saved on request
        self.current = panel.profile_var.get() if panel.profile_var.get() in self.working else DEFAULT_CUSTOMER
        self.customer_var = tk.StringVar(value=self.current)
        self.new_var = tk.StringVar()
        self.apply_vars = {m: tk.BooleanVar() for m in CRITERION_METRICS}
        self.pass_vars = {m: tk.StringVar() for m in CRITERION_METRICS}
        self.fail_vars = {m: tk.StringVar() for m in CRITERION_METRICS}
        self.bands = {m: tk.StringVar() for m in CRITERION_METRICS}
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(4, weight=1)
        ttk.Label(body, text="Customer").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.combo = ttk.Combobox(body, textvariable=self.customer_var, values=list(self.working), state="readonly", width=22)
        self.combo.grid(row=0, column=1, columnspan=2, sticky="w", pady=(0, 6))
        self.combo.bind("<<ComboboxSelected>>", self._switch)
        self.delete_button = ttk.Button(body, text="Delete", command=self.delete_customer)
        self.delete_button.grid(row=0, column=3, padx=6, pady=(0, 6))
        self.reset_button = ttk.Button(body, text="Reset to default", command=self.reset_customer)
        self.reset_button.grid(row=0, column=4, sticky="w", pady=(0, 6))
        ttk.Label(body, text="New customer").grid(row=1, column=0, sticky="w")
        ttk.Entry(body, textvariable=self.new_var, width=24).grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Button(body, text="Add (copy of selected)", command=self.add_customer).grid(row=1, column=3, columnspan=2, sticky="w", padx=6)
        for column, text in enumerate(("Apply", "Metric", "PASS", "FAIL", "Result bands")):
            ttk.Label(body, text=text, style="Section.TLabel").grid(row=2, column=column, sticky="w", padx=(0, 14), pady=(16, 4))
        for row, metric in enumerate(CRITERION_METRICS, start=3):
            ndc = metric == "ndc"
            ttk.Checkbutton(body, variable=self.apply_vars[metric]).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Label(body, text=self.NAMES[metric]).grid(row=row, column=1, sticky="w", padx=(0, 14))
            for column, (var, caption) in enumerate(((self.pass_vars[metric], "at least" if ndc else "below"),
                                                     (self.fail_vars[metric], "below" if ndc else "above")), start=2):
                cell = ttk.Frame(body)
                cell.grid(row=row, column=column, sticky="w", padx=(0, 14))
                ttk.Label(cell, text=caption, style="Hint.TLabel").pack(side="left", padx=(0, 4))
                ttk.Entry(cell, textvariable=var, width=7).pack(side="left")
                ttk.Label(cell, text="" if ndc else "%", style="Hint.TLabel").pack(side="left", padx=(2, 0))
                var.trace_add("write", lambda *_, m=metric: self._refresh_band(m))
            ttk.Label(body, textvariable=self.bands[metric]).grid(row=row, column=4, sticky="w")
        ttk.Label(body, wraplength=720, style="Hint.TLabel", text=(
            "The overall result is the worst of the applied metrics: any FAIL gives FAIL, otherwise any CONDITIONAL PASS gives "
            "CONDITIONAL PASS, otherwise PASS. Values between the PASS and FAIL limits are CONDITIONAL PASS. A metric that is not "
            "applied does not decide, but if it would FAIL on its own limits the result is flagged for review. Criteria are an optional "
            "layer on top of the statistics: they never change a calculated value. The built-in customers are starting points "
            "taken from Jabil's work instruction for reference (SolarEdge and Zebra: %SV/Tol only; SES: NDC and %SV/Tol; Jabil: "
            "all three); edit them or add your own.")
                  ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(14, 0))
        actions = ttk.Frame(body)
        actions.grid(row=7, column=0, columnspan=5, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(actions, text="Save and use", command=self.save, style="Accent.TButton").pack(side="right", padx=(0, 8))
        self._load(self.current)
        self.present(width=800)

    # -- form <-> working copy
    def _load(self, name):
        self.current = name
        by_metric = {c.metric: c for c in self.working[name]}
        for metric in CRITERION_METRICS:
            c = by_metric.get(metric) or Criterion(metric, False, *DEFAULT_LIMITS[metric])
            self.apply_vars[metric].set(c.enabled)
            self.pass_vars[metric].set(f"{c.pass_limit:g}")
            self.fail_vars[metric].set(f"{c.fail_limit:g}")
        builtin = name in BUILTIN_CUSTOMERS
        self.delete_button.configure(state="disabled" if builtin else "normal")
        self.reset_button.configure(state="normal" if builtin else "disabled")

    def _read(self):
        criteria = []
        for metric in CRITERION_METRICS:
            try:
                limits = (float(self.pass_vars[metric].get()), float(self.fail_vars[metric].get()))
            except ValueError:
                raise ValueError(f"{self.NAMES[metric]}: enter the PASS and FAIL limits as numbers.") from None
            criteria.append(Criterion(metric, self.apply_vars[metric].get(), *limits))
        criteria = tuple(criteria)
        validate_criteria(criteria)
        return criteria

    def _store(self):
        """Keep the form in the working copy. A bad value is reported and the form stays where it is."""
        try:
            self.working[self.current] = self._read()
        except ValueError as exc:
            messagebox.showwarning("Invalid criteria", str(exc), parent=self)
            return False
        return True

    def _refresh_band(self, metric):
        try:
            text = describe_criterion(Criterion(metric, True, float(self.pass_vars[metric].get()), float(self.fail_vars[metric].get())))
            self.bands[metric].set(text.split(": ", 1)[1])
        except (ValueError, KeyError):
            self.bands[metric].set("enter numbers")

    # -- actions
    def _switch(self, *_):
        target = self.customer_var.get()
        if target == self.current:
            return
        if self._store():
            self._load(target)
        else:
            self.customer_var.set(self.current)

    def add_customer(self):
        name = " ".join(self.new_var.get().split())
        if not name or len(name) > 40:
            messagebox.showwarning("New customer", "Enter a customer name of up to 40 characters.", parent=self)
        elif name.casefold() in {n.casefold() for n in self.working}:
            messagebox.showwarning("New customer", f"'{name}' already exists.", parent=self)
        elif self._store():
            self.working[name] = self.working[self.current]
            self.combo.configure(values=list(self.working))
            self.customer_var.set(name)
            self.new_var.set("")
            self._load(name)

    def delete_customer(self):
        if self.current in BUILTIN_CUSTOMERS:
            return
        del self.working[self.current]
        self.combo.configure(values=list(self.working))
        self.customer_var.set(DEFAULT_CUSTOMER)
        self._load(DEFAULT_CUSTOMER)

    def reset_customer(self):
        if self.current in BUILTIN_CUSTOMERS:
            self.working[self.current] = BUILTIN_CUSTOMERS[self.current]
            self._load(self.current)

    def save(self):
        if self._store():
            self.panel.set_customers(self.working, selected=self.current)
            self.close()
