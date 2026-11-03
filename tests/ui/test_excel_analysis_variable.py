"""The "Analyze by Excel File" dialog for numeric measurements: Variable Gage R&R and Cpk read the RawData.xlsx layout that Data
Mapping exports, so an exported file is chosen as it is and the template is that layout. What a file is checked for is tested in
tests/test_excel_intake_variable.py; here the person is followed through the window, and the analysis is compared with the engine
called directly on the same readings.
"""
from __future__ import annotations

import copy

import pytest
from openpyxl import load_workbook
from PySide6.QtTest import QTest

from datamapperx.excel_intake import NO_TRIAL
from datamapperx.statistics import AnalysisConfig, analyze

from ..excel_support import write_rawdata
from .excel_helpers import checked, choose, lines, open_dialog
from .support import pump
from .test_widgets import overlapping, squeezed


@pytest.fixture
def exported(tmp_path):
    """A RawData.xlsx written by DataMapperX itself from synthetic logs: 3 samples of 2 files, the test items R1 and Long."""
    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder

    from ..baseline_support import write_rawdata_logs

    logs = tmp_path / "logs"
    logs.mkdir()
    write_rawdata_logs(logs)
    path = tmp_path / "RawData.xlsx"
    generate_excel(scan_folder(logs, copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"])).grouped, ["R1", "Long"], path, expected_repeated=2)
    return path


def carry_on(app, window, dialog):
    """Continue to Analysis: the workspace with the data imported and the Analysis tab in front (nothing run yet)."""
    dialog.continue_button.click()
    ws = window.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.source_var.get() == "file")
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    return ws


def run(app, ws) -> None:
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)


# ----------------------------------------------------------------------------- choosing
def test_the_method_is_chosen_before_a_file_and_the_template_can_be_had_for_either(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    dialog.cards["variable"].clicked.emit()
    assert dialog.method_row.isVisible() and [b.text() for b in dialog.method_buttons.values()] == ["Variable GR&&R", "Cpk"]  # && shows as one &
    assert not any(button.isChecked() for button in dialog.method_buttons.values())  # nothing is assumed
    assert dialog.download_button.isEnabled() and not dialog.choose_button.isEnabled()
    picks.save = str(tmp_path / "template")
    dialog.download_button.click()
    pump(app, lambda: dialog.note.text().startswith("Template saved"))
    assert load_workbook(tmp_path / "template.xlsx").sheetnames == ["Raw Data", "Instructions", "Examples"]  # one layout for both methods
    dialog.method_buttons["capability"].setChecked(True)
    assert dialog.state.method == "capability" and dialog.choose_button.isEnabled()


def test_an_exported_rawdata_file_is_chosen_as_it_is_and_has_no_columns_or_sheet_to_choose(app, window, dialogs, picks, exported):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, exported, "variable", "grr")
    assert dialog.state.report.ready and dialog.continue_button.isEnabled() and dialog.state.report.sheet == "Raw Data"
    assert dialog.summary.text().startswith("All 2 test items: 3 parts × 2 readings each, balanced")
    shown = lines(dialog)
    assert f"Note | Sheet: Raw Data | {NO_TRIAL}" in shown  # Gage R&R: the trials are the readings in the order of the rows
    assert any(line.startswith("Warning | Sheet: Raw Data | Column: Long | ") for line in shown)  # what the analysis says of one test item
    assert not dialog.review_button.isVisible() and not dialog.sheet_box.isVisible()  # one fixed layout: nothing to map, no sheet to pick
    assert dialog.again_button.isVisible()


def test_a_clean_file_is_ready_and_a_note_is_not_a_warning(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_rawdata(tmp_path / "clean.xlsx", serials=4, readings=3, items=("R1",), limits=((90, 140),)), "variable", "grr")
    assert dialog.status.text() == "Ready for Analysis" and dialog.summary.text() == "The test item: 4 parts × 3 readings each, balanced"
    assert lines(dialog) == [f"Note | Sheet: Raw Data | {NO_TRIAL}"]


# ----------------------------------------------------------------------------- the two analyses
def test_gage_rr_goes_on_with_the_data_of_the_file_and_the_engines_own_result(app, window, dialogs, picks, exported):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, exported, "variable", "grr")
    report = dialog.state.report
    ws = carry_on(app, window, dialog)
    assert window.workspace == "validation" and ws.method_var.get() == "grr" and ws.imported is report.imported
    assert ws.file_var.get() == str(exported) and ws.result_set is None  # nothing was analysed yet
    assert window.workflow_breadcrumb.text() == "Analyze by Excel File" and window.scan_result is None
    run(app, ws)
    assert [r.test_item for r in ws.results] == ["R1", "Long"]
    direct = analyze(report.imported.dataset.observations, AnalysisConfig(method="grr", assign_trials=True))
    assert [r.metrics for r in ws.results] == [r.metrics for r in direct]  # the data were loaded without changing their meaning


def test_cpk_goes_on_with_the_limits_of_the_file_and_the_engines_own_result(app, window, dialogs, picks, tmp_path):
    path = write_rawdata(tmp_path / "cpk.xlsx", serials=30, readings=1, items=("R1",), limits=((90, 140),),
                         value=lambda n, r, i: 110 + (n * 7 % 11) - 5)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path, "variable", "capability")
    report = dialog.state.report
    assert dialog.status.text() == "Ready for Analysis" and report.summary == "1 test item · 30 samples · 30 rows"
    ws = carry_on(app, window, dialog)
    assert ws.method_var.get() == "capability"
    run(app, ws)
    result = ws.results[0]
    assert (result.lsl, result.usl, result.n, result.unit) == (90, 140, 30, "Ohm")
    assert result.metrics == analyze(report.imported.dataset.observations, AnalysisConfig(method="capability"))[0].metrics


def test_a_measurement_system_that_would_fail_is_not_a_reason_to_stop(app, window, dialogs, picks, tmp_path):
    path = write_rawdata(tmp_path / "noisy.xlsx", serials=4, readings=3, items=("R1",), limits=((950, 1050),),
                         value=lambda n, r, i: 1000 + ((n * 3 + r) * 37 % 41) - 20)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path, "variable", "grr")
    assert dialog.state.report.ready and dialog.continue_button.isEnabled()  # no data problem
    ws = carry_on(app, window, dialog)
    run(app, ws)
    assert ws.results[0].valid and ws.results[0].metrics["percent_tolerance"] > 30  # it is analysed; the analysis says what it finds


# ----------------------------------------------------------------------------- what is found
def test_a_file_with_an_error_names_it_blocks_continue_and_can_be_corrected_and_checked_again(app, window, dialogs, picks, tmp_path):
    def broken(n, r, i):
        return "abc" if (n, r) == (1, 1) else 5 + n + r

    path = write_rawdata(tmp_path / "raw.xlsx", items=("R1",), limits=((0, 9),), value=broken)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path, "variable", "capability")
    assert dialog.status.text() == "Invalid File"
    assert lines(dialog) == ["Error | Sheet: Raw Data | Row 5 | Column: R1 | Measurement must be numeric."]
    assert not dialog.continue_button.isEnabled()
    dialog.continue_button.click()
    assert window.workspace == "dashboard"  # a file with an error does not go on
    write_rawdata(path, items=("R1",), limits=((0, 9),))  # corrected in Excel
    dialog.again_button.click()
    checked(app, dialog)
    assert dialog.status.text() in ("Ready for Analysis", "Warnings Found") and dialog.continue_button.isEnabled()
    assert "Error" not in dialog.findings.toPlainText()


def test_a_test_item_that_cannot_be_analysed_is_a_warning_while_another_can(app, window, dialogs, picks, tmp_path):
    path = write_rawdata(tmp_path / "gaps.xlsx", value=lambda n, r, i: None if (n, r, i) == (1, 0, 1) else 100 + 10 * n + r + 5 * i)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path, "variable", "grr")
    assert dialog.status.text() == "Warnings Found" and dialog.continue_button.isEnabled()
    assert "Warning | Sheet: Raw Data | Row 4 | Column: R2 | Measurement is empty." in lines(dialog)
    ws = carry_on(app, window, dialog)
    run(app, ws)
    assert [(r.test_item, r.valid) for r in ws.results] == [("R1", True), ("R2", False)]  # the analysis shows which one could not be done


def test_continuing_again_with_the_same_file_and_method_does_not_replace_the_data_but_another_method_does(app, window, dialogs, picks, exported):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, exported, "variable", "grr")
    state = dialog.state
    ws = carry_on(app, window, dialog)
    dataset = ws.dataset
    window._show_workspace("dashboard")
    again = open_dialog(window, dialogs)
    assert again.state is state and again.method_buttons["grr"].isChecked() and again.continue_button.isEnabled()
    again.continue_button.click()
    assert window.workspace == "validation" and ws.dataset is dataset  # back to the data that are open
    window._show_workspace("dashboard")
    third = open_dialog(window, dialogs)
    third.method_buttons["capability"].setChecked(True)  # the same file read for Cpk: another analysis, so the data are replaced
    checked(app, third)
    third.continue_button.click()
    pump(app, lambda: ws.method_var.get() == "capability" and ws.dataset is not dataset and not ws.busy)
    assert ws.imported is third.state.report.imported


# ----------------------------------------------------------------------------- how it looks
@pytest.mark.parametrize("dark", [False, True])
def test_the_numeric_dialog_fits_at_its_smallest_and_larger_sizes_in_both_themes(app, window, dialogs, picks, exported, dark):
    if dark:
        window._toggle_theme()
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, exported, "variable", "grr")
    assert dialog.palette_tokens.mode == ("dark" if dark else "light") and dialog.method_row.isVisible()
    for size in (dialog.minimumSize(), dialog.size(), dialog.size().expandedTo(dialog.size() * 1.4)):
        dialog.resize(size)
        QTest.qWait(80)
        assert overlapping(dialog) == [] and squeezed(dialog) == []
        assert dialog.continue_button.isVisible() and dialog.method_buttons["grr"].isChecked()
    assert dialog.cards["variable"].property("selected") is True
    if dark:  # an unchecked radio is drawn a shade darker than the window colour, which in the dark theme is the dialog's own: lighter
        assert all(b.palette().window().color().name() == dialog.palette_tokens.muted for b in dialog.method_buttons.values())
