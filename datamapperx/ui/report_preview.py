"""A native report preview, using the same tables and charts as PDF / Excel exports."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..palette import LIGHT
from ..stat_reports import (
    ReportContext,
    acceptance_table,
    attribute_tables,
    capability_tables,
    failure,
    format_value,
    grr_tables,
    info_rows,
    item_label,
    report_charts,
    summary_number,
    summary_rows,
)
from .theme import make_palette
from .widgets import ChartPanel, DataTable


class ReportPreview(QWidget):
    """Show the selected report contents; exported PDF pagination may differ."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results = []
        self._context = ReportContext()
        self._decimals = 2
        self._charts = True
        self._stale = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        tools = QHBoxLayout()
        self.coverage = QLabel(self)
        tools.addWidget(self.coverage)
        self.item_combo = QComboBox(self)
        self.item_combo.setMinimumContentsLength(12)
        self.item_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.item_combo.setAccessibleName("Preview measurement")
        self.item_combo.currentIndexChanged.connect(self._show_item)
        tools.addWidget(self.item_combo, 1)
        outer.addLayout(tools)
        self.notice = QLabel("Preview uses report values and charts. PDF pagination may differ.", self)
        self.notice.setProperty("role", "micro")
        self.notice.setWordWrap(True)
        outer.addWidget(self.notice)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.paper = QFrame(scroll)
        self.paper.setObjectName("reportPaper")
        self.paper.setPalette(make_palette(LIGHT))
        self.paper.setStyleSheet("""
            QFrame#reportPaper { background: white; border: 1px solid #d4dce6; border-radius: 4px; }
            QFrame#reportPaper QLabel { color: #28374b; background: transparent; }
            QFrame#reportPaper QLabel[reportHeading="true"] { color: #0760a6; font-weight: 700; }
            QFrame#reportPaper QTableView { background: white; color: #28374b; border: 1px solid #d4dce6;
                gridline-color: #d4dce6; selection-background-color: #eaf3ff; selection-color: #28374b; }
            QFrame#reportPaper QHeaderView::section { background: #edf3f9; color: #56677b; padding: 4px 8px; }
        """)
        self.paper_body = QVBoxLayout(self.paper)
        self.paper_body.setContentsMargins(22, 18, 22, 22)
        self.paper_body.setSpacing(9)
        scroll.setWidget(self.paper)
        outer.addWidget(scroll, 1)
        self.set_report([], None)

    def set_report(self, results, context: ReportContext | None, decimals: int = 2, charts: bool = True,
                   stale: bool = False) -> None:
        selected = self.item_combo.currentData()
        self._results, self._context = list(results), context or ReportContext()
        self._decimals = decimals
        self._charts = charts and "charts" in self._context.sections
        self._stale = stale
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        for result in self._results:
            self.item_combo.addItem(item_label(result), result.label)
        self.item_combo.setCurrentIndex(max(0, self.item_combo.findData(selected)))
        self.item_combo.blockSignals(False)
        count = len(self._results)
        total = self._context.total or count
        self.coverage.setText(f"{count} of {total} measurements")
        self.item_combo.setEnabled(bool(count))
        self.notice.setText("Reference only: results changed. Update analysis before exporting."
                            if stale else "Preview uses report values and charts. PDF pagination may differ.")
        self.notice.setProperty("role", "warn" if stale else "micro")
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self._show_item()

    def _text(self, text: str, *, heading: bool = False) -> None:
        widget = QLabel(text, self.paper)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setWordWrap(True)
        widget.setProperty("reportHeading", heading)
        self.paper_body.addWidget(widget)

    def _table(self, headers, rows) -> None:
        table = DataTable(LIGHT, self.paper, row_height=25, row_lines=True)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.set_table(headers, rows, stretch=0, max_width=300)
        table.horizontalHeader().setVisible(any(headers))
        height = 25 * min(max(1, len(rows)), 8) + (30 if any(headers) else 0) + 20
        table.setFixedHeight(height)
        self.paper_body.addWidget(table)

    def _show_item(self, _index: int = -1) -> None:
        while self.paper_body.count():
            item = self.paper_body.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        if not self._results:
            self._text("Update analysis to preview the report." if self._stale else "Select measurements to preview the report.")
            self.paper_body.addStretch(1)
            return
        result = self._results[max(0, self.item_combo.currentIndex())]
        if self._stale:
            self._text("REFERENCE ONLY · Update analysis before exporting.", heading=True)
        names = {"capability": "Process Capability", "grr": "Variable Gage R&R", "attribute": "Attribute Agreement Analysis"}
        self._text(names[result.method], heading=True)
        self._text(item_label(result), heading=True)
        for name, value in info_rows(result, self._context):
            self._text(f"{name} {value}")
        if len(self._results) > 1:
            self._text("Selected measurements", heading=True)
            headers, rows = summary_rows(self._results, judged=False)
            formatted = [[summary_number(value, headers[i], self._decimals, result.method) for i, value in enumerate(row)]
                         for row in rows]
            self._table(headers, formatted)
        if not result.valid:
            self._text(failure(result))
            self.paper_body.addStretch(1)
            return
        if self._charts:
            charts = ChartPanel(self.paper)
            charts.set_specs(report_charts(result, titled=True))
            self.paper_body.addWidget(charts)
        tables = {"capability": capability_tables, "grr": grr_tables, "attribute": attribute_tables}[result.method](result)
        acceptance = acceptance_table(result)
        for table in [*tables, *([acceptance] if acceptance is not None else [])]:
            self._text(table.title, heading=True)
            self._table(table.headers, table.cells(self._decimals))
            if table.note:
                self._text(table.note)
        if result.method == "grr":
            self._text(f"Number of Distinct Categories = {format_value(result.metrics.get('ndc'), 'int')}")
        for issue in result.issues:
            if issue.severity in ("warning", "error"):
                self._text(issue.message)
        if "observations" in self._context.sections:
            self._text("Readings (Excel)", heading=True)
            self._table(("Sample ID", "Trial", "Appraiser", "Value", "Standard"),
                        [(o.sample_id, o.trial, o.operator, o.value, o.standard) for o in result.observations])
        self.paper_body.addStretch(1)
