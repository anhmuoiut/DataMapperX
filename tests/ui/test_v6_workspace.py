"""The V6 report preview follows real analyses and preserves their reporting guards."""

from __future__ import annotations

import copy

import pytest
from PySide6.QtWidgets import QLabel

from datamapperx.stat_reports import capability_tables, grr_tables, info_rows, report_charts
from datamapperx.statistics import Dataset, Observation
from datamapperx.ui import validation_workspace as workspace
from datamapperx.ui.widgets import ChartPanel, DataTable

from .support import pump
from .test_validation import ready, run_validation
from .test_validation_attribute import load, run


def paper_widgets(preview, kind):
    """Only the current paper, excluding widgets waiting for Qt's deferred deletion."""
    return [preview.paper_body.itemAt(i).widget() for i in range(preview.paper_body.count())
            if isinstance(preview.paper_body.itemAt(i).widget(), kind)]


def paper_text(preview):
    return [widget.text() for widget in paper_widgets(preview, QLabel)]


@pytest.mark.parametrize("method, tables_for", [("capability", capability_tables), ("grr", grr_tables)])
def test_report_preview_prints_the_real_report_tables_and_charts(app, window, tmp_path, method, tables_for):
    ws = ready(app, window, tmp_path)
    ws.method_var.set(method)
    run_validation(app, ws)
    ws.tabs.setCurrentWidget(ws.report_tab)
    preview = ws.report_preview
    result = ws.results[0]
    assert result.valid and preview.item_combo.currentData() == result.label

    actual = [(table.headings(), table.rows()) for table in paper_widgets(preview, DataTable)]
    for table in tables_for(result):
        assert (list(table.headers), [tuple(row) for row in table.cells(ws._precision())]) in actual
    charts = paper_widgets(preview, ChartPanel)
    assert len(charts) == 1 and charts[0].specs() == report_charts(result, titled=True)
    assert preview.coverage.text() == "3 of 3 measurements"


def test_report_metadata_sections_and_inclusion_update_without_recalculating(app, window, tmp_path):
    ws = ready(app, window, tmp_path)
    run_validation(app, ws)
    original = ws.result_set
    metrics = copy.deepcopy([stat.metrics for stat in original.statistics])
    ws.tabs.setCurrentWidget(ws.report_tab)
    preview = ws.report_preview

    ws.gage_var.set("Bench DMM 7")
    ws.by_var.set("T. Man")
    ws.comments_var.set("First article")
    context, _included = ws._context()
    assert all(f"{name} {value}" in paper_text(preview) for name, value in info_rows(ws.results[0], context))
    assert any("Bench DMM 7" in text for text in paper_text(preview))
    assert any("T. Man" in text for text in paper_text(preview))

    ws.sections["charts"].set(False)
    assert not paper_widgets(preview, ChartPanel)
    ws.sections["charts"].set(True)
    assert paper_widgets(preview, ChartPanel)
    ws.sections["observations"].set(True)
    assert "Readings (Excel)" in paper_text(preview)

    ws.item_list.clearSelection()
    assert preview.item_combo.count() == 0 and not paper_widgets(preview, ChartPanel)
    ws.item_list.item(1).setSelected(True)
    selected = ws.results[1]
    assert preview.item_combo.count() == 1 and preview.item_combo.currentData() == selected.label
    assert preview.coverage.text() == "1 of 3 measurements"
    assert paper_widgets(preview, ChartPanel)[0].specs() == report_charts(selected, titled=True)
    readings = paper_widgets(preview, DataTable)[-1]
    assert readings.headings() == ["Sample ID", "Trial", "Appraiser", "Value", "Standard"]
    assert readings.table_model.rowCount() == len(selected.observations)
    assert ws.result_set is original and not ws.stale
    assert [stat.metrics for stat in original.statistics] == metrics


def test_changed_statistics_clear_an_open_report_preview_and_disable_exports(app, window, tmp_path):
    ws = ready(app, window, tmp_path)
    run_validation(app, ws)
    original = ws.result_set
    ws.tabs.setCurrentWidget(ws.report_tab)
    preview = ws.report_preview
    assert preview.item_combo.count() == 3 and ws.pdf_button.isEnabled() and ws.excel_button.isEnabled()

    ws.assign_var.set(False)
    assert ws.stale and ws.result_set is original
    assert preview.item_combo.count() == 0 and not paper_widgets(preview, DataTable)
    assert not paper_widgets(preview, ChartPanel)
    assert "Update analysis to preview the report." in paper_text(preview)
    assert "Update analysis before exporting" in preview.notice.text()
    assert not ws.pdf_button.isEnabled() and not ws.excel_button.isEnabled()

    ws.assign_var.set(True)
    assert not ws.stale and ws.result_set is original
    assert preview.item_combo.count() == 3 and ws.pdf_button.isEnabled() and ws.excel_button.isEnabled()


def test_attribute_report_flag_withholds_preview_and_exports(app, window, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ATTRIBUTE_RESULTS_READY", True)
    monkeypatch.setattr(workspace, "ATTRIBUTE_REPORTS_READY", False)
    monkeypatch.delenv(workspace.ATTRIBUTE_REPORTS_ENV, raising=False)
    window._show_workspace("validation")
    ws = window.validation
    pump(app, lambda: not ws.busy)
    load(app, ws, tmp_path)
    run(app, ws)
    ws.tabs.setCurrentWidget(ws.report_tab)
    preview = ws.report_preview
    assert ws.results[0].method == "attribute" and not ws.stale
    assert preview.item_combo.count() == 0 and not paper_widgets(preview, ChartPanel)
    assert preview.notice.text() == workspace.ATTRIBUTE_REPORT_PENDING
    assert not ws.pdf_button.isEnabled() and not ws.excel_button.isEnabled()

    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "1")
    ws._refresh_state()
    assert preview.item_combo.count() == len(ws.results)
    assert paper_widgets(preview, ChartPanel)
    assert ws.pdf_button.isEnabled() and ws.excel_button.isEnabled()


def test_choosing_a_method_does_not_run_analysis(app, window, tmp_path, monkeypatch):
    ws = ready(app, window, tmp_path)
    calls = []
    monkeypatch.setattr(ws.tasks, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    for method in ("capability", "attribute", "grr"):
        ws.method_radios[method].click()
        app.processEvents()
        assert ws.method_var.get() == method and ws.result_set is None and not ws.running
    assert calls == []


def test_readiness_handles_numeric_strings_mixed_limits_and_missing_values(app, window, tmp_path):
    ws = ready(app, window, tmp_path)
    observations = (
        Observation("Numeric strings", "S1", "3", "2", "10"),
        Observation("Mixed limits", "S1", "3.5E+00", 2, "1.0E+01"),
        Observation("Missing limit", "S1", 3, None, "10"),
        Observation("Invalid limit", "S1", 3, "invalid", 10),
        Observation("Reversed limits", "S1", 3, "10", "2"),
        Observation("Invalid value", "S1", "error", "2", "10"),
        Observation("Missing value", "S1", None, 2, 10),
        Observation("Actual ratings", "S1", "PASS"),
        Observation("Actual ratings", "S2", "FAIL"),
        Observation("Mixed data", "S1", "PASS"),
        Observation("Mixed data", "S2", 3),
    )
    dataset = Dataset.from_observations(observations)
    fingerprint = dataset.fingerprint
    ws._dataset_ready(dataset)
    expected = [
        ("Numeric strings", "Numeric", "Provided"),
        ("Mixed limits", "Numeric", "Provided"),
        ("Missing limit", "Numeric", "Review"),
        ("Invalid limit", "Numeric", "Review"),
        ("Reversed limits", "Numeric", "Review"),
        ("Invalid value", "Review", "Provided"),
        ("Missing value", "Review", "Provided"),
        ("Actual ratings", "Ratings", "—"),
        ("Mixed data", "Review", "Review"),
    ]
    assert ws.setup_items.rows() == expected
    for method in ("attribute", "capability"):
        ws.method_var.set(method)
        assert ws.setup_items.rows() == expected  # choosing a method does not convert the data
    assert ws.result_set is None and not ws.running
    assert ws.dataset is dataset and dataset.observations == observations and dataset.fingerprint == fingerprint
