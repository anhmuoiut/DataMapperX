"""Validation & Reports preview: run the statistics on the scan, list the results and draw their charts.

It uses the application's own pipeline unchanged: ``MappingSource`` -> ``Dataset`` -> ``Study`` -> statistics ->
``evaluate`` (statistics only, no criteria), then the same ``summary_rows`` and ``charts_for_result`` the tkinter window
and the PDF / Excel reports use. Only the drawing is new.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..palette import Palette
from ..stat_charts import charts_for_result
from ..stat_reports import display_number, summary_rows
from ..statistics import StatisticalOptions, Study
from ..workspace_data import MappingSource, build_mapping_dataset
from .tasks import TaskRunner
from .widgets import Card, ChartPanel, DataTable, make_button

METHODS = {"Variable Gage R&R": "grr", "Process Capability (Cp/Cpk)": "capability"}
LEFT_OUT = {"Mean", "Min", "Max", "Decision Metric"}  # in the details and the reports, not in the summary table


class AnalysisPage(QWidget):
    message = Signal(str)

    def __init__(self, palette: Palette, tasks: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tasks, self._source, self._results, self._busy = tasks, None, [], False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        controls = Card("Analysis")
        row = QHBoxLayout()
        self.method = QComboBox()
        self.method.addItems(list(METHODS))
        self.run_button = make_button("Run analysis", self.run, primary=True)
        self.status = QLabel("Choose the method, then run the analysis on the components you selected.")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        row.addWidget(QLabel("Method"))
        row.addWidget(self.method)
        row.addWidget(self.run_button)
        row.addWidget(self.status, 1)
        controls.body.addLayout(row)
        outer.addWidget(controls)

        split = QSplitter(Qt.Orientation.Vertical)
        results = Card("Results")
        self.table = DataTable(palette)
        self.table.rowSelected.connect(self._select)
        results.body.addWidget(self.table)
        charts = Card("Charts")
        self.charts = ChartPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.charts)
        charts.body.addWidget(scroll)
        split.addWidget(results)
        split.addWidget(charts)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([180, 420])
        outer.addWidget(split, 1)
        self._clear("")

    # ------------------------------------------------------------------ data from the window
    def set_source(self, source: MappingSource | None) -> None:
        if source is not None and self._source is not None and source.key == self._source.key and source.scan == self._source.scan:
            return  # unchanged; keep what is on screen
        self._source = source
        self._clear("" if source else "Scan logs and choose test items first.")

    def set_palette(self, palette: Palette) -> None:
        self.table.set_palette(palette)

    def _clear(self, note: str) -> None:
        self._results = []
        self.table.set_table(["Test Item"], [], empty_text="No results yet.")
        self.charts.set_specs([])
        if note:
            self.status.setText(note)

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        source = self._source
        if self._busy or source is None or not source.components:
            self.status.setText("Scan logs and choose test items first.")
            return
        method = METHODS[self.method.currentText()]
        options = StatisticalOptions(method=method, assign_trials=method == "grr",
                                     expected_repeats=source.expected_repeats if method == "grr" else None)

        def work(_report):
            study = Study(build_mapping_dataset(source, {}, "worksheet"), options=options)
            return study, study.plan_statistics().execute()

        def done(outcome):
            study, result_set = outcome
            evaluated = study.evaluate(study.adopt(result_set), judge=False)  # statistics only, no criteria
            self._busy = False
            self.run_button.setEnabled(True)
            self._show(list(evaluated.results))

        def failed(exc):
            self._busy = False
            self.run_button.setEnabled(True)
            self.status.setText(str(exc))

        self._busy = True
        self.run_button.setEnabled(False)
        self.status.setText("Analysing…")
        self.tasks.run(work, on_success=done, on_error=failed)

    def _show(self, results: list) -> None:
        self._results = results
        headers, rows = summary_rows(results, judged=False)
        keep = [i for i, h in enumerate(headers) if h not in LEFT_OUT and (h != "System" or any(r.system for r in results))]
        shown = [[display_number(row[k], 2) for k in keep] for row in rows]
        self.table.set_table([headers[k] for k in keep], shown, aligns=["w"] + ["e"] * (len(keep) - 1), stretch=0)
        self.status.setText(f"{len(results)} item/system groups analysed (statistics only).")
        self.message.emit(f"Analysed {len(results)} test items.")
        if results:
            self.table.select_row(0)

    def _select(self, row: int) -> None:
        if 0 <= row < len(self._results):
            self.charts.set_specs(charts_for_result(self._results[row]))

    @property
    def results(self) -> list:
        return list(self._results)
