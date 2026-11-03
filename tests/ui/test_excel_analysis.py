"""The "Analyze by Excel File" dialog of the Dashboard: choosing the type, the template, a file and what is found in it, and the way on
to the analysis. What a file is checked for is tested in tests/test_excel_intake.py; here the person is followed through the window.
"""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from datamapperx.excel_intake import Finding, IntakeReport, validate_attribute
from datamapperx.ui import excel_analysis_dialog as module
from datamapperx.ui.excel_analysis_dialog import SUBTITLE
from datamapperx.ui.ratings_import import RatingsImportDialog

from ..excel_support import attribute_rows, write_ratings, write_rawdata
from .excel_helpers import checked, choose, lines, open_dialog
from .support import pump
from .test_widgets import overlapping, squeezed


# ----------------------------------------------------------------------------- the dialog
def test_the_dialog_shows_two_types_and_waits_for_a_choice(app, window, dialogs):
    dialog = open_dialog(window, dialogs)
    assert dialog.windowTitle() == "Analyze by Excel File" and dialog.isModal()
    assert SUBTITLE in [label.text() for label in dialog.findChildren(QLabel)]
    assert [(card.title.text(), card.body.text()) for card in dialog.cards.values()] ==         [("Attribute", "Pass / Fail evaluation"), ("Variable / Cpk", "Numeric measurements")]
    assert all(card.isEnabled() for card in dialog.cards.values())
    for button in (dialog.download_button, dialog.choose_button, dialog.review_button, dialog.again_button, dialog.continue_button):
        assert not button.isEnabled()  # no type chosen, no file, nothing to continue with
    assert not dialog.status.isVisible() and dialog.findings.toPlainText() == "" and not dialog.method_row.isVisible()
    assert dialog.continue_button.text() == "Continue to Analysis  →"


def test_only_one_type_is_selected_at_a_time_and_it_can_be_chosen_from_the_keyboard(app, window, dialogs):
    dialog = open_dialog(window, dialogs)
    attribute, variable = dialog.cards["attribute"], dialog.cards["variable"]
    QTest.keyClick(attribute, Qt.Key.Key_Space)
    assert attribute.property("selected") is True and variable.property("selected") is False
    assert dialog.download_button.isEnabled() and dialog.choose_button.isEnabled() and not dialog.continue_button.isEnabled()
    assert not dialog.method_row.isVisible()
    QTest.keyClick(variable, Qt.Key.Key_Return)
    assert attribute.property("selected") is False and variable.property("selected") is True and dialog.state.category == "variable"
    assert dialog.method_row.isVisible() and dialog.download_button.isEnabled()
    assert not dialog.choose_button.isEnabled()  # the method is the person's to say: no file before it


def test_an_attribute_analysis_that_is_not_released_is_not_offered(app, window, dialogs, monkeypatch):
    from datamapperx.ui import validation_workspace

    monkeypatch.setattr(validation_workspace, "ATTRIBUTE_RESULTS_READY", False)
    monkeypatch.delenv(validation_workspace.ATTRIBUTE_PREVIEW_ENV, raising=False)
    dialog = open_dialog(window, dialogs)
    assert not dialog.cards["attribute"].isEnabled() and "not been released" in dialog.cards["attribute"].toolTip()
    assert not dialog.choose_button.isEnabled()


# ----------------------------------------------------------------------------- the template
def test_the_template_is_saved_where_the_person_says_and_is_not_yet_a_file_to_analyse(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    dialog.cards["attribute"].clicked.emit()
    picks.save = str(tmp_path / "mine")  # no extension typed: the file still is an .xlsx
    dialog.download_button.click()
    pump(app, lambda: dialog.note.text().startswith("Template saved"))
    saved = tmp_path / "mine.xlsx"
    assert saved.exists() and str(saved) in dialog.note.text()
    assert validate_attribute(saved).status == "invalid"  # nothing filled in yet
    picks.save = ""  # cancelled: nothing more is written, nothing is said
    dialog.download_button.click()
    assert sorted(path.name for path in tmp_path.glob("*.xlsx")) == ["mine.xlsx"]


# ----------------------------------------------------------------------------- a file
def test_a_good_file_is_ready_and_continue_opens_the_analysis_without_running_it(app, window, dialogs, picks, tmp_path):
    path = write_ratings(tmp_path / "ratings.xlsx", attribute_rows())
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path)
    assert dialog.status.text() == "Ready for Analysis" and dialog.status.property("badge") == "ok"
    assert dialog.file_label.text() == str(path) and "4 samples · 2 appraisers" in dialog.summary.text()
    assert dialog.continue_button.isEnabled() and dialog.review_button.isEnabled() and dialog.again_button.isEnabled()
    dialog.continue_button.click()
    ws = window.validation
    assert window.workspace == "validation" and window.workflow_route == "raw" and window.workflow_breadcrumb.text() == "Analyze by Excel File"
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.source_var.get() == "ratings")
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    assert ws.method_var.get() == "attribute" and ws.ratings is dialog.state.report.imported
    assert ws.result_set is None and ws.evaluated is None  # nothing was analysed
    assert window.scan_result is None and not window.selected_components  # Data Mapping was never needed
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    assert len(ws.results) == 1 and ws.results[0].method == "attribute"  # the analysis is the one that was already there


def test_a_file_with_an_error_names_it_blocks_continue_and_can_be_corrected_and_checked_again(app, window, dialogs, picks, tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    broken = [*rows[:2], (rows[2][0], None, *rows[2][2:]), *rows[3:]]
    path = write_ratings(tmp_path / "ratings.xlsx", broken)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path)
    assert dialog.status.text() == "Invalid File" and dialog.status.property("badge") == "bad"
    assert lines(dialog) == ["Error | Sheet: Attribute_Data | Row 4 | Column: Rating | Rating is empty."]
    assert dialog.summary.text() == "1 error" and not dialog.continue_button.isEnabled()
    dialog.continue_button.click()
    assert window.workspace == "dashboard"  # a file with an error does not go on
    write_ratings(path, rows)  # the person corrects the file in Excel and checks again: no restart
    dialog.again_button.click()
    checked(app, dialog)
    assert dialog.status.text() == "Ready for Analysis" and dialog.continue_button.isEnabled() and "Error" not in dialog.findings.toPlainText()


def test_a_file_with_warnings_may_still_be_analysed(app, window, dialogs, picks, tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    rows[0] = (rows[0][0], "Pass", *rows[0][2:])
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_ratings(tmp_path / "ratings.xlsx", rows))
    assert dialog.status.text() == "Warnings Found" and dialog.status.property("badge") == "warn" and dialog.continue_button.isEnabled()
    assert any(line.startswith("Warning | ") and "letter case" in line for line in lines(dialog))
    assert any("3 categories" in line for line in lines(dialog)) and dialog.summary.text().endswith("2 warnings")  # PASS, FAIL and Pass


def test_the_columns_of_a_file_with_other_names_are_reviewed_in_the_columns_dialog_and_the_file_is_checked_again(app, window, dialogs, picks, tmp_path):
    headers = ("Serial", "Judgement", "Inspector", "Repeat", "Reference")
    rows = [(r[0], r[1], r[3], r[4], r[5]) for r in attribute_rows()]
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_ratings(tmp_path / "ratings.xlsx", rows, headers=headers))
    assert dialog.status.text() == "Invalid File" and lines(dialog) == ["Error | Sheet: Attribute_Data | Choose the Rating column. Use Review columns…"]
    dialog.review_button.click()
    pump(app, lambda: bool(dialog.findChildren(RatingsImportDialog)))
    mapping = dialog.findChildren(RatingsImportDialog)[-1]
    assert mapping.boxes["sample"].currentText() == "Serial" and mapping.boxes["rating"].currentText() == "(none)"
    mapping.boxes["rating"].setCurrentText("Judgement")
    mapping.import_button.click()
    checked(app, dialog)
    assert dialog.status.text() == "Ready for Analysis" and dialog.continue_button.isEnabled()
    assert dialog.state.mapping.rating == "Judgement" and dialog.state.report.imported.record["columns"]["rating"] == "Judgement"
    dialog.again_button.click()  # checking again keeps the columns that were chosen
    checked(app, dialog)
    assert dialog.status.text() == "Ready for Analysis"


def test_a_file_that_is_not_a_workbook_is_an_invalid_file_and_cancelling_the_file_dialog_changes_nothing(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    dialog.cards["attribute"].clicked.emit()
    dialog.choose_button.click()  # cancelled
    assert dialog.state.path == "" and dialog.state.report is None and not dialog.status.isVisible()
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    picks.open = str(broken)
    dialog.choose_button.click()
    checked(app, dialog)
    assert dialog.status.text() == "Invalid File" and "cannot be read" in dialog.findings.toPlainText() and not dialog.continue_button.isEnabled()


def test_the_dialog_stays_usable_while_a_file_is_checked(app, window, dialogs, picks, tmp_path, monkeypatch):
    release = threading.Event()

    def slow(path, sheet, mapping, method):
        release.wait(5)
        return validate_attribute(path, sheet, mapping)

    monkeypatch.setitem(module.CHECKS, "attribute", slow)
    dialog = open_dialog(window, dialogs)
    dialog.cards["attribute"].clicked.emit()
    picks.open = str(write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    dialog.choose_button.click()
    assert dialog._checking and "Checking ratings.xlsx" in dialog.summary.text()  # the window answers while the worker reads
    for button in (dialog.choose_button, dialog.download_button, dialog.review_button, dialog.again_button, dialog.continue_button):
        assert not button.isEnabled()
    release.set()
    checked(app, dialog)
    assert dialog.continue_button.isEnabled()


def test_the_answer_of_an_older_check_is_thrown_away(app, window, dialogs, picks, tmp_path, monkeypatch):
    started, release, calls = threading.Event(), threading.Event(), []

    def check(path, sheet, mapping, method):
        calls.append(path)
        if len(calls) == 1:  # the first check reads for a long time, the second answers at once
            started.set()
            release.wait(5)
            return IntakeReport(path, (Finding("error", "the old answer"),))
        return IntakeReport(path, (Finding("error", "the new answer"),))

    monkeypatch.setitem(module.CHECKS, "attribute", check)
    dialog = open_dialog(window, dialogs)
    dialog.cards["attribute"].clicked.emit()
    picks.open = str(write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    dialog.choose_button.click()
    pump(app, started.is_set)  # the first check is reading
    dialog._check()  # a newer check starts while it is
    pump(app, lambda: dialog.state.report is not None)
    release.set()
    QTest.qWait(150)  # the old answer arrives now, and is not shown
    assert "the new answer" in dialog.findings.toPlainText() and "the old answer" not in dialog.findings.toPlainText()


def test_the_excel_report_of_an_attribute_study_is_chosen_as_it_is_and_gives_the_same_figures(app, window, dialogs, picks, tmp_path):
    from datamapperx.stat_reports import ReportContext, export_statistical_report

    from ..test_attribute import only, reference_rows

    result = only(reference_rows(mistakes={(4, 2)}))
    context = ReportContext(info=(("Gage name", "G1"),), included=1, total=1, sections=("observations",))  # "Observations used (Excel only)"
    path = export_statistical_report(tmp_path / "report.xlsx", [result], context=context)
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path)
    assert dialog.status.text() == "Ready for Analysis" and dialog.state.report.sheet == "Observations"
    assert dialog.sheet_box.isVisible() and dialog.sheet_box.currentText() == "Observations"  # the sheet of the report is the one read
    dialog.continue_button.click()
    ws = window.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.tabs.currentWidget() is ws.setup_tab)
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    assert ws.results[0].metrics == result.metrics


# ----------------------------------------------------------------------------- what is kept
def test_the_dialog_opens_as_it_was_left_and_continuing_again_does_not_replace_the_data(app, window, dialogs, picks, tmp_path):
    path = write_ratings(tmp_path / "ratings.xlsx", attribute_rows())
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, path)
    state, report = dialog.state, dialog.state.report
    dialog.close()
    assert window.workspace == "dashboard"  # closing is not continuing
    again = open_dialog(window, dialogs)
    assert again is not dialog and again.state is state
    assert again.cards["attribute"].property("selected") is True and again.file_label.text() == str(path)
    assert again.status.text() == "Ready for Analysis" and again.continue_button.isEnabled() and again.state.report is report
    again.continue_button.click()
    ws = window.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.tabs.currentWidget() is ws.setup_tab)
    dataset = ws.dataset
    window._show_workspace("dashboard")
    third = open_dialog(window, dialogs)
    third.continue_button.click()  # the same file again: back to the data that are open, nothing read or replaced
    assert window.workspace == "validation" and ws.dataset is dataset and ws.ratings is report.imported


def test_the_dialog_does_not_open_while_the_program_is_busy(app, window, dialogs):
    window._set_busy(True)
    window.start_excel_analysis()
    window._set_busy(False)
    assert dialogs == []


# ----------------------------------------------------------------------------- Reset
def test_reset_is_in_the_top_right_corner_and_there_only_while_there_is_something_to_forget(app, window, dialogs):
    dialog = open_dialog(window, dialogs)
    title = next(label for label in dialog.findChildren(QLabel) if label.text() == "Analyze by Excel File")
    reset = dialog.reset_button
    assert reset.text() == "↺  Reset" and reset.toolTip() and not reset.isEnabled()  # nothing chosen yet
    corner = reset.mapTo(dialog, QPoint(reset.width(), 0))
    assert dialog.width() - corner.x() < 40 and corner.y() < 60  # the top right corner
    assert abs(reset.mapTo(dialog, reset.rect().center()).y() - title.mapTo(dialog, title.rect().center()).y()) <= 10  # on the title's line
    dialog.cards["attribute"].clicked.emit()
    assert reset.isEnabled()


def test_reset_forgets_the_type_the_file_and_what_was_found_and_the_next_opening_is_blank(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    picks.save = str(tmp_path / "template")
    dialog.download_button.click()
    pump(app, lambda: dialog.note.text().startswith("Template saved"))
    state = dialog.state
    assert state.report is not None and dialog.continue_button.isEnabled()
    dialog.reset_button.click()
    assert state is dialog.state is window._excel_state  # emptied in place: the main window holds this very object
    assert (state.category, state.method, state.path, state.sheet, state.mapping, state.report) == (None, None, "", None, None, None)
    assert not any(card.property("selected") for card in dialog.cards.values()) and dialog.file_label.text() == ""
    assert not dialog.status.isVisible() and dialog.findings.toPlainText() == "" and dialog.summary.text() == "" and dialog.note.text() == ""
    for button in (dialog.download_button, dialog.choose_button, dialog.review_button, dialog.again_button, dialog.continue_button, dialog.reset_button):
        assert not button.isEnabled()
    dialog.close()
    again = open_dialog(window, dialogs)
    assert again.state.category is None and again.state.path == "" and not again.continue_button.isEnabled()  # blank the next time too
    choose(app, again, picks, tmp_path / "ratings.xlsx")  # and a new start works
    assert again.status.text() == "Ready for Analysis"


def test_reset_unchecks_the_method_too_so_nothing_old_is_assumed(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_rawdata(tmp_path / "raw.xlsx"), "variable", "grr")
    assert dialog.method_buttons["grr"].isChecked()
    dialog.reset_button.click()
    assert not any(button.isChecked() for button in dialog.method_buttons.values()) and dialog.state.method is None
    dialog.cards["variable"].clicked.emit()
    assert dialog.method_row.isVisible() and not any(button.isChecked() for button in dialog.method_buttons.values())
    assert not dialog.choose_button.isEnabled()  # the method has to be said again


def test_reset_while_a_file_is_being_checked_forgets_it_and_throws_its_answer_away(app, window, dialogs, picks, tmp_path, monkeypatch):
    release = threading.Event()

    def slow(path, sheet, mapping, method):
        release.wait(5)
        return validate_attribute(path, sheet, mapping)

    monkeypatch.setitem(module.CHECKS, "attribute", slow)
    dialog = open_dialog(window, dialogs)
    dialog.cards["attribute"].clicked.emit()
    picks.open = str(write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    dialog.choose_button.click()
    assert dialog._checking and dialog.reset_button.isEnabled()  # the one thing that can be done while it reads
    dialog.reset_button.click()
    assert not dialog._checking and dialog.state.path == "" and not dialog.choose_button.isEnabled()
    release.set()
    QTest.qWait(200)  # the old answer arrives now, and is not shown
    assert dialog.state.report is None and not dialog.status.isVisible() and dialog.findings.toPlainText() == ""


def test_reset_leaves_the_data_already_open_in_the_analysis_as_they_are(app, window, dialogs, picks, tmp_path):
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    dialog.continue_button.click()
    ws = window.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.tabs.currentWidget() is ws.setup_tab)
    dataset, ratings = ws.dataset, ws.ratings
    window._show_workspace("dashboard")
    again = open_dialog(window, dialogs)
    again.reset_button.click()
    assert not again.continue_button.isEnabled()  # the old file is not offered any more
    assert ws.dataset is dataset and ws.ratings is ratings  # what is open is replaced only by continuing with another file


# ----------------------------------------------------------------------------- how it looks
@pytest.mark.parametrize("dark", [False, True])
def test_the_dialog_fits_at_its_smallest_and_larger_sizes_in_both_themes(app, window, dialogs, picks, tmp_path, dark):
    if dark:
        window._toggle_theme()
    dialog = open_dialog(window, dialogs)
    choose(app, dialog, picks, write_ratings(tmp_path / "ratings.xlsx", attribute_rows()))
    assert dialog.palette_tokens.mode == ("dark" if dark else "light")
    for size in (dialog.minimumSize(), dialog.size(), dialog.size().expandedTo(dialog.size() * 1.4)):
        dialog.resize(size)
        QTest.qWait(80)
        assert overlapping(dialog) == [] and squeezed(dialog) == []
        assert dialog.findings.height() > 40 and dialog.continue_button.isVisible()
    assert dialog.cards["attribute"].property("selected") is True
