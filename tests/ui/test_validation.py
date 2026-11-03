"""Validation & Reports in the Qt window: Data, Analysis, Results (table, charts, Details, Checks) and Report.

These follow the behaviours the Tk workspace was tested for (tests/test_ui.py), on the Qt widgets and headless.
"""
from __future__ import annotations

import copy
import os
from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLabel

from datamapperx.ui import validation_workspace as vp
from datamapperx.ui.dialogs import ReportDialog
from datamapperx.ui.method_dialog import MethodDialog
from datamapperx.ui.validation_dialogs import AssignmentDialog, CustomersDialog, DatePickerDialog

from ..conftest import ict_block, write_ict_log
from .support import pump, ready_to_review, scan


def open_validation(app, win):
    """The workspace on a clean slate, with its data ready."""
    win._show_workspace("validation")
    ws = win.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    return ws


def run_validation(app, ws):
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None and not ws.stale)
    return ws


def ready(app, win, tmp_path, name="logs", **kwargs):
    folder = tmp_path / name
    ready_to_review(app, win, folder, **kwargs)
    return open_validation(app, win)


def check_rows(ws):
    """The Checks tab as (section, check, result, status) rows."""
    tree = ws.checks_tree
    rows = []
    for index in range(tree.topLevelItemCount()):
        section = tree.topLevelItem(index)
        rows += [(section.text(0), section.child(c).text(0), section.child(c).text(1), section.child(c).text(2))
                 for c in range(section.childCount())]
    return rows


def grr_rows(ws):
    """The Details tables as (cells, tag): a title row, a row of column names, then the figures. Blank padding is left off."""
    return [(tuple(cells[:max((i + 1 for i, c in enumerate(cells) if c), default=0)]), tag)
            for cells, tag in zip(ws.grr_tree.rows(), ws.grr_tree.tags(), strict=True)]


def headings(ws):
    return ws.table.headings()


def test_validation_is_a_workspace_beside_data_mapping_and_leaves_the_raw_export_alone(app, window, tmp_path):
    from dataclasses import asdict

    ready_to_review(app, window, tmp_path / "stat_logs")
    window._show_step("review")
    before = {str(r.path): asdict(r) for records in window.scan_result.grouped.values() for r in records}
    assert window.validate_button.isEnabled() and window.export_button.isEnabled()
    window.validate_button.click()
    assert window.workspace == "validation" and window.content.currentWidget() is window.validation
    assert window.step_bar.isVisibleTo(window) and window.home_button.isVisible()  # the step bar goes on to Analyze, Results and Report
    ws = open_validation(app, window)
    assert [ws.tabs.isTabEnabled(i) for i in range(4)] == [True, True, False, False]  # the tabs open up as the work progresses
    assert all(part in ws.dataset_var.get() for part in ("Test Items 3", "Samples 3", "Total Readings 18", "Trials per Sample 2"))
    run_validation(app, ws)  # Quick Analysis: no trial step, no setup needed
    assert ws.tabs.currentWidget() is ws.results_tab
    assert len(ws.results) == 3 and all("ndc" in r.metrics for r in ws.results)
    assert ws.table.table_model.rowCount() == 3 and ws.summary_var.get().startswith("3 items analyzed · Acceptance off")
    assert ws.tabs.isTabEnabled(3) and ws.pdf_button.isEnabled()
    assert before == {str(r.path): asdict(r) for records in window.scan_result.grouped.values() for r in records}
    window.mapping_switch.click()
    assert window.workspace == "mapping" and window.step == "review" and window.export_button.isEnabled()  # Excel never depends on it


def test_validation_opens_with_nothing_scanned_and_data_mapping_keeps_working(app, window):
    window._show_workspace("validation")
    ws = window.validation
    pump(app, lambda: not ws.busy)
    assert ws.dataset is None and not ws.run_button.isEnabled() and "No Data Mapping results" in ws.message_var.get()
    assert [ws.tabs.isTabEnabled(i) for i in (1, 2, 3)] == [False] * 3
    window.mapping_switch.click()
    assert window.workspace == "mapping" and window.content.currentWidget() is window._pages["select"]


def test_changing_the_study_makes_results_stale_but_changing_criteria_or_decimals_does_not(app, window, tmp_path):
    ws = ready(app, window, tmp_path)
    run_validation(app, ws)
    assert ws.stale_banner.isHidden() and ws.pdf_button.isEnabled()
    first = ws.result_set
    ws.profile_var.set("Jabil")  # a different customer judges the same numbers
    ws.precision_var.set("5")
    assert ws.result_set is first and not ws.stale and ws.stale_banner.isHidden()
    assert ws.evaluated.record.settings.profile == "Jabil"
    ws.assign_var.set(False)  # numbering the repeated readings changes what is computed
    assert ws.stale and not ws.stale_banner.isHidden()
    ws.assign_var.set(True)  # back to what the results were computed from: current again
    assert not ws.stale and ws.stale_banner.isHidden()
    ws.assign_var.set(False)
    assert ws.stale and not ws.pdf_button.isEnabled() and not ws.excel_button.isEnabled()
    assert "Update the results" in ws.report_var.get() and ws.table.table_model.rowCount() == 3  # the old results stay, for reference
    ws.update_button.click()
    pump(app, lambda: not ws.running and not ws.stale)
    assert ws.result_set is not first and ws.result_set.id == "RS-0002" and ws.stale_banner.isHidden()
    assert ws.pdf_button.isEnabled() and ws.result_set.options.assign_trials is False


def test_a_result_that_finishes_after_the_study_changed_is_recorded_as_stale(app, window, tmp_path, monkeypatch):
    ws = ready(app, window, tmp_path)
    pending = []
    monkeypatch.setattr(ws.tasks, "run", lambda work, **callbacks: pending.append((work, callbacks)))
    ws.run_button.click()
    assert not ws.run_button.isEnabled() and len(pending) == 1
    ws.method_var.set("capability")  # edited while the analysis is on its worker thread
    work, callbacks = pending[0]
    callbacks["on_success"](work(lambda *_: None))
    assert ws.result_set is not None and ws.result_set.options.method == "grr" and ws.stale
    assert ws.run_button.isEnabled() and not ws.pdf_button.isEnabled()


def test_results_appear_at_once_with_notes_and_without_any_confirmation(app, window, tmp_path, monkeypatch):
    ws = ready(app, window, tmp_path, "cap_logs")
    ws.method_var.set("capability")
    run_validation(app, ws)
    assert headings(ws) == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"]  # no criteria chosen: statistics only, no Result column
    assert "Acceptance off" in ws.summary_var.get() and ws.filter_combo.isHidden()
    assert all(r.metrics.get("cpk") is not None and r.status == "N/A" for r in ws.results) and ws.pdf_button.isEnabled()
    assert ws.notes_bar.isHidden() and ws.notes_var.get() == "" and not ws.notes_link.isHidden()
    shown = []
    monkeypatch.setattr(vp, "ReportDialog", lambda parent, title, heading, text: type("D", (), {"present": lambda self: shown.append(text)})())
    ws.show_notes()
    assert "Process stability" in shown[-1] and "Normal distribution" in shown[-1] and "do not block" in shown[-1]
    ws.judge_var.set(True)  # judging against a limit is optional and changes no number
    cpk = [r.metrics["cpk"] for r in ws.results]
    assert headings(ws)[-1] == "Result" and all(row[-1] in ("PASS", "FAIL") for row in ws.table.rows())
    assert [r.metrics["cpk"] for r in ws.results] == cpk and not ws.stale
    ws.judge_var.set(False)
    assert headings(ws)[-1] == "Ppk" and not ws.stale
    ws.subgroup_var.set(True)  # a statistical input: the results go stale
    assert ws.stale


def test_grr_has_no_pass_or_fail_until_criteria_are_chosen(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "criteria_logs")
    assert ws.profile_var.get() == vp.NO_CRITERIA
    run_validation(app, ws)
    assert headings(ws) == ["Test Item", "%SV/Tol", "%Study Var", "NDC"]
    assert all(r.status == "N/A" and "ndc" in r.metrics for r in ws.results) and "Acceptance off" in ws.summary_var.get()
    assert ws.plan_title_var.get() == "Variable Gage R&R" and ws.plan_var.get() == "3 Test Items · 3 Samples" and not ws._judge_for("grr")
    ws.profile_var.set("SolarEdge")  # criteria are a layer on top: the figures stay and PASS / FAIL appear
    assert not ws.stale and headings(ws)[-2:] == ["Acceptance Result", "Review"]
    assert {row[-2] for row in ws.table.rows()} <= {"PASS", "CONDITIONAL PASS", "FAIL", "N/A"}
    assert ws.study.evaluation.profile == "SolarEdge" and ws._judge_for("grr") and not ws.filter_combo.isHidden()


def test_within_sigma_is_chosen_from_the_subgroup_size_unless_the_user_says_otherwise(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "within_logs")
    ws.method_var.set("capability")
    assert ws.study.options.within_method == "individuals" and ws.within_hint_var.get() == "In use: average moving range"
    ws.subgroup_var.set(True)  # the two files of a serial number form a subgroup
    assert ws.study.options.within_method == "pooled" and ws.within_hint_var.get() == "In use: pooled standard deviation"
    ws.within_var.set("Average moving range, length 2 (subgroup size 1)")
    assert ws.study.options.within_method == "individuals" and ws.within_hint_var.get() == "In use: average moving range"


def test_the_within_sigma_method_is_an_advanced_option_and_the_capability_setup_is_short(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "cap_setup")
    ws.method_var.set("capability")
    assert ws.plan_title_var.get() == "Process Capability" and ws.plan_var.get() == "3 Test Items · 3 Samples"
    assert [b.text() for b in ws.method_radios.values()] == [
        "Process Capability", "Variable Gage R&&R", "Attribute Agreement"]
    assert ws.subgroup_check.text() == "Group readings by Sample ID" and ws.judge_check.text() == "Enable acceptance criteria"
    assert ws.criteria_row.isHidden() and ws.advanced.isHidden() and ws.threshold_var.get() == "1.33"
    ws.judge_var.set(True)
    assert not ws.criteria_row.isHidden() and [b.text() for b in ws.index_radios.values()] == ["Cpk (Within)", "Ppk (Overall)"]
    ws.index_var.set("ppk")
    ws.threshold_var.set("1.67")
    assert ws.study.evaluation.decision_metric == "ppk" and ws.study.evaluation.cpk_threshold == 1.67
    ws.judge_var.set(False)
    assert ws.criteria_row.isHidden() and not ws._judge_for("capability")
    ws.advanced_button.click()
    assert not ws.advanced.isHidden() and "▼" in ws.advanced_button.text()
    ws.advanced_button.click()
    assert ws.advanced.isHidden()
    ws.method_var.set("grr")
    assert ws.plan_title_var.get() == "Variable Gage R&R"


def test_the_details_tab_shows_the_tables_of_the_selected_item(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "session_logs")
    run_validation(app, ws)
    rows = grr_rows(ws)  # Gage R&R: three tables, NDC above them
    assert [cells[0] for cells, tag in rows if tag == "section"] == ["One-Way ANOVA", "Variance Components", "Gage Evaluation"]
    heads = [cells for cells, tag in rows if tag == "head"]
    assert heads[0][:5] == ("Source", "DF", "MS", "F", "P") and "SS" not in heads[0]  # the essential columns
    assert heads[1][:3] == ("Source", "VarComp", "%Contribution") and "%Tolerance" in heads[2] and "Study Var (6 × SD)" not in heads[2]
    assert any(cells[0] == "Part-To-Part" for cells, _ in rows) and ws.ndc_var.get() == str(ws.results[0].metrics["ndc"])
    assert ws.details_stack.currentWidget() is ws.grr_frame
    ws.method_var.set("capability")
    run_validation(app, ws)
    groups = [ws.details.topLevelItem(i).text(0) for i in range(ws.details.topLevelItemCount())]  # a capability item: a table, not text
    assert groups == ["Specification", "Variation", "Capability", "Advanced Details"] and ws.details_stack.currentWidget() is ws.details
    metrics = [ws.details.topLevelItem(g).child(c).text(0) for g in range(4) for c in range(ws.details.topLevelItem(g).childCount())]
    for expected in ("LSL", "USL", "Sample N", "Mean", "Within SD", "Overall SD", "Cp", "Cpk", "Pp", "Ppk", "CPL", "PPU", "Observed PPM Total"):
        assert expected in metrics


def test_gage_rr_details_show_the_essential_columns_and_all_of_them_on_request(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "grr_details")
    ws.precision_var.set("2")
    run_validation(app, ws)

    def heads():
        return [cells for cells, tag in grr_rows(ws) if tag == "head"]

    assert heads()[0][:5] == ("Source", "DF", "MS", "F", "P") and "Study Var (6 × SD)" not in heads()[2]
    assert not ws.grr_headline.isHidden() and ws.ndc_var.get() == str(ws.results[0].metrics["ndc"])  # NDC stays above the tables
    ws.all_columns_var.set(True)
    assert heads()[0] == ("Source", "DF", "SS", "MS", "F", "P") and "Study Var (6 × SD)" in heads()[2]
    assert any(cells[0] == "Sample ID" for cells, tag in grr_rows(ws) if not tag)  # complete results stay available
    ws.precision_var.set("4")  # the decimals setting of the window
    sample = next(cells for cells, tag in grr_rows(ws) if not tag and cells[0] == "Sample ID")
    assert sample[2] == f"{ws.results[0].details['anova'][0]['ss']:.9f}"


def test_capability_details_follow_the_decimals_and_advanced_details_stay_as_left(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "cap_details")
    ws.method_var.set("capability")
    ws.precision_var.set("2")
    run_validation(app, ws)

    def figures():
        return {ws.details.topLevelItem(g).child(c).text(0): ws.details.topLevelItem(g).child(c).text(1)
                for g in range(ws.details.topLevelItemCount()) for c in range(ws.details.topLevelItem(g).childCount())}

    *primary, advanced = (ws.details.topLevelItem(i) for i in range(ws.details.topLevelItemCount()))
    assert all(group.isExpanded() for group in primary) and not advanced.isExpanded()
    result = ws.selected_result()
    assert figures()["Cpk"] == f"{result.metrics['cpk']:.2f}" and figures()["Sample N"] == str(result.n)
    ws.precision_var.set("4")  # the decimals setting of the window
    assert figures()["Cpk"] == f"{ws.selected_result().metrics['cpk']:.4f}"
    advanced = ws.details.topLevelItem(ws.details.topLevelItemCount() - 1)
    advanced.setExpanded(True)
    ws.table.select_row(1)  # another item: Advanced Details stays as the user left it
    assert ws.details.topLevelItem(ws.details.topLevelItemCount() - 1).isExpanded() and ws.selected_result() is ws._visible[1]
    ws.method_var.set("grr")
    run_validation(app, ws)
    assert ws.details_stack.currentWidget() is ws.grr_frame


def test_ppk_can_be_the_decision_index_and_the_table_leaves_out_what_does_not_decide(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "ppk_logs")
    ws.method_var.set("capability")
    ws.judge_var.set(True)
    ws.index_var.set("ppk")
    ws.precision_var.set("5")  # decimals only change what is shown
    run_validation(app, ws)
    assert {r.decision_metric for r in ws.results} == {"ppk"}
    assert len(ws.table.rows()[0][2].split(".")[1]) == 5
    ws.precision_var.set("2")
    assert len(ws.table.rows()[0][2].split(".")[1]) == 2 and not ws.stale
    assert headings(ws) == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk", "Result"]  # Mean/Min/Max and an empty System are in the details
    ws.method_var.set("grr")
    ws.profile_var.set("SolarEdge")
    run_validation(app, ws)
    assert headings(ws) == ["Test Item", "%SV/Tol", "%Study Var", "NDC", "Acceptance Result", "Review"]


def test_data_mapping_changes_reach_validation_when_it_is_shown_again(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "change_logs")
    run_validation(app, ws)
    assert len(ws.results) == 3
    window.mapping_switch.click()
    window.selected_components = ["R1", "R2"]
    window._selection_changed()
    window.validation_switch.click()
    pump(app, lambda: ws.dataset is not None and not ws.busy and len(ws.dataset.items) == 2)
    assert "Test Items 2" in ws.dataset_var.get() and ws.stale and not ws.stale_banner.isHidden()
    assert ws.table.table_model.rowCount() == 3  # still the old results, marked as such
    ws.update_button.click()
    pump(app, lambda: not ws.running and not ws.stale)
    assert len(ws.results) == 2


def test_every_new_study_starts_as_statistics_only_even_if_an_older_version_saved_a_customer(app, window, tmp_path):
    from datamapperx.settings import Settings

    saved = Settings()
    saved.validation_customer = "SolarEdge"  # what the previous version remembered
    fresh = vp.ValidationWorkspace(window.palette_tokens, settings=saved, parent=window)
    assert fresh.profile_var.get() == vp.NO_CRITERIA and not fresh.judge_var.get()
    ws = ready(app, window, tmp_path, "criteria_reset_logs")
    ws.profile_var.set("SolarEdge")
    ws.method_var.set("capability")
    ws.judge_var.set(True)
    ws.method_var.set("grr")
    window.reset_workflow()  # nothing to analyse: the study is gone
    ready_to_review(app, window, tmp_path / "criteria_reset_logs")
    window._show_workspace("validation")
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    assert ws.profile_var.get() == vp.NO_CRITERIA and not ws.judge_var.get()  # the next study starts again without criteria
    run_validation(app, ws)
    assert all(r.status == "N/A" for r in ws.results) and "Acceptance off" in ws.summary_var.get()


# ----------------------------------------------------------------------------- the worksheet, the checks and the order of readings
def write_study_logs(folder, *, parts=10, operators=("Ann", "Bob", "Cy"), readings=3, by_folder=True, skip=()):
    """One log per part, operator and reading, with some spread; in a folder per operator, or all in one folder."""
    for k, operator in enumerate(operators):
        target = folder / operator if by_folder else folder
        target.mkdir(exist_ok=True)
        for part in range(1, parts + 1):
            for reading in range(readings):
                if (part, operator) in skip:
                    continue
                value = 10 + part + 0.1 * ((part * 3 + reading * 5 + k * 7) % 4)
                write_ict_log(target / f"P{part:02d}_{operator}_{reading + 1}.log", f"VSE{part:03d}",
                              [ict_block("R1", f"{value:+.5E}", "+4.0E+01", "+0.0E+00")])


def scanned_study(app, win, folder, *, parts=10, operators=("Ann", "Bob", "Cy"), readings=3, **kwargs):
    folder.mkdir(exist_ok=True)
    write_study_logs(folder, parts=parts, operators=operators, readings=readings, **kwargs)
    scan(app, win, folder, expected=parts, repeats=len(operators) * readings)
    win.add_all_shown()
    return open_validation(app, win)


def column(ws, key):
    return [row[vp.PREVIEW_COLUMNS.index(key)] for row in ws.preview.rows()]


def test_a_single_tester_study_needs_no_operators_and_the_worksheet_says_how_it_looks(app, window, tmp_path):
    ws = scanned_study(app, window, tmp_path / "one_tester", operators=("T1",), by_folder=False)
    assert ws.preview.isColumnHidden(vp.PREVIEW_COLUMNS.index("operator"))  # nobody is named: the worksheet has no Operator column
    assert column(ws, "trial")[:6] == ["1", "2", "3"] * 2  # the trial each reading will get, counted per part
    assert all(part in ws.dataset_var.get() for part in ("Test Items 1", "Samples 10", "Total Readings 30", "Trials per Sample 3"))
    assert ws.hint_var.get() == "" and ws.hint_label.isHidden()  # balanced and complete: nothing to warn about
    run_validation(app, ws)
    assert ws.results[0].valid and not ws.results[0].details.get("crossed") and ws.plan_title_var.get() == "Variable Gage R&R"
    assert not any(c.code == "one_appraiser" for c in ws.evaluated.record.validation.conditions)
    assert not any(check.startswith("Operators") for _section, check, *_rest in check_rows(ws))


def test_the_study_variation_factor_scales_study_var_and_tolerance_only(app, window, tmp_path):
    from datamapperx.method_guide import guide_text, method_guide
    from datamapperx.stat_reports import session_text

    ws = scanned_study(app, window, tmp_path / "factor", operators=("T1",), by_folder=False)
    assert ws.study_factor_var.get() == "6" and [ws.study_factor_combo.itemText(i) for i in range(6)] == ["1", "2", "3", "4", "5", "6"]
    run_validation(app, ws)
    six = dict(ws.results[0].metrics)
    assert "6 × SD" in session_text(ws.results[0])
    ws.study_factor_var.set("4")
    assert ws.stale  # the factor decides the numbers
    run_validation(app, ws)
    four = ws.results[0].metrics
    assert four["study_var"] == pytest.approx(six["study_var"] * 4 / 6) and four["percent_tolerance"] == pytest.approx(six["percent_tolerance"] * 4 / 6)
    for unchanged in ("percent_study_var", "ndc", "sigma_grr", "sigma_part", "variance_grr", "variance_part"):
        assert four[unchanged] == six[unchanged], unchanged
    assert "4 × SD" in session_text(ws.results[0]) and ws.study.options.study_factor == 4.0
    note = guide_text(method_guide(ws._config()))
    assert "uses k = 4" in note and "±3σ" in note and "Gage R&R is the repeatability" in note
    ws.study_factor_var.set("7")
    assert "from 1 to 6" in ws.setup_error and not ws.run_button.isEnabled()
    ws.study_factor_var.set("6")
    assert ws.setup_error == ""


def test_the_checks_tab_gives_amount_of_data_and_the_guidelines_for_gage_rr(app, window, tmp_path):
    ws = scanned_study(app, window, tmp_path / "checks_grr", parts=8, operators=("T1",), by_folder=False)
    run_validation(app, ws)
    rows = check_rows(ws)
    assert rows[0] == ("Data Checks", "All checks", "No data issues detected.", "OK")  # nothing wrong with the readings themselves
    guidelines = {row[1]: row for row in rows if row[0] == "Guidelines (reference only)"}
    assert guidelines["Parts"][2:] == ("8 parts (10 or more recommended)", "Review") and "Operators" not in guidelines
    assert {"%Study Var", "%Contribution", "NDC"} <= set(guidelines) and all(row[3] in ("OK", "Review") for row in guidelines.values())
    assert all(len(row) == 4 and len(row[2]) < 70 for row in rows)  # one short line each, no paragraphs
    assert ws.summary_var.get().endswith("1 Need Review")


def test_file_time_order_sorts_by_when_each_log_was_saved_and_is_taken_as_the_order_of_measurement(app, window, tmp_path):
    ws = scanned_study(app, window, tmp_path / "timed", operators=("Ann",), readings=9, by_folder=False)
    paths = sorted(str(r.path) for records in window.scan_result.grouped.values() for r in records)
    for position, path in enumerate(paths):  # saved in the reverse of the name order
        os.utime(path, ns=(10**18 + (len(paths) - position) * 10**9,) * 2)
    ws.method_var.set("capability")
    assert "worksheet order" in ws.hint_var.get() and "Settings" in ws.hint_var.get()  # capability depends on the order: said once
    ws.order_var.set(vp.ORDERS["filetime"])
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.dataset.order_basis == "acquisition")
    assert "the time each log file was saved" in ws.dataset.description
    first = column(ws, "source")[:2]
    assert first[0].endswith("P10_Ann_9.log") and first[1].endswith("P10_Ann_8.log")  # the last name was saved first
    run_validation(app, ws)
    shown = " ".join(" ".join(row) for row in check_rows(ws))
    assert "Sample Size Limited (N = 9" in shown and "not verified" not in shown  # an order was chosen: no caveat on the stability
    assert ws.hint_var.get() == ""  # and nothing to warn about on the Data tab
    ws.order_var.set(vp.ORDERS["worksheet"])
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.dataset.order_basis == "worksheet")
    run_validation(app, ws)
    assert any(row[1] == "Stability" and row[2].startswith("Worksheet order, not verified as time order") and row[3] == "Review"
               for row in check_rows(ws))


def test_the_capability_checks_list_only_what_was_found_in_short_lines(app, window, tmp_path):
    from datamapperx.statistics.checks import Check

    ws = ready(app, window, tmp_path, "cap_checks")
    ws.method_var.set("capability")
    run_validation(app, ws)
    rows = check_rows(ws)
    stability = next(row for row in rows if row[1] == "Stability")  # a sequence test says nothing about time here
    assert stability[0] == "Data Checks" and stability[2].startswith("Worksheet order, not verified as time order") and stability[3] == "Review"
    assert next(row for row in rows if row[1] == "Sample Size")[0] == "Guidelines (reference only)"  # how much data: a guideline
    shown = " ".join(" ".join(row) for row in rows)
    assert "Capability assumes a stable process" not in shown and "No data issues detected." not in shown
    assert not ws.notes_link.isHidden()  # the report notes: one click away
    result = ws.selected_result()
    ws._checks[result.label] = ([Check("Normality", "ok", "passed", "Passed (Anderson–Darling p = 0.235).")], [])
    ws._show_checks(result)
    assert check_rows(ws) == [("Data Checks", "All checks", "No data issues detected.", "OK")]  # a check that passed is not listed
    ws._checks[result.label] = ([Check("Stability", "info", "the whole statement", "the short line"),
                                 Check("Normality", "caution", "the whole statement", "Failed (Anderson–Darling p = 0.006, below 0.05).")], [])
    ws._show_checks(result)
    assert check_rows(ws) == [("Data Checks", "Normality", "Failed (Anderson–Darling p = 0.006, below 0.05)", "Issue"),
                              ("Data Checks", "Stability", "the short line", "Review")]  # what was found, the issues first


def test_a_warning_mark_leads_to_the_checks_and_never_changes_pass_or_fail(app, window, tmp_path):
    from collections import Counter

    ws = ready(app, window, tmp_path, "cap_marks")
    ws.method_var.set("capability")
    run_validation(app, ws)
    marked = sorted(ws._marked)
    assert marked and all(ws.table.rows()[row][0].endswith(vp.WARNING_MARK) for row in marked)
    assert headings(ws) == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"]
    assert ws.summary_var.get() == f"3 items analyzed · Acceptance off · {len(marked)} Need Review"
    ws.judge_var.set(True)  # acceptance: the Cpk threshold only
    assert [r.status for r in ws._visible] == ["PASS" if r.metrics["cpk"] > 1.33 else "FAIL" for r in ws._visible]
    counts = Counter(r.status for r in ws._visible)
    assert ws.summary_var.get() == " · ".join(["3 items analyzed", *(f"{n} {status}" for status, n in counts.items()), f"{len(marked)} Need Review"])
    row = marked[0]
    text = ws.table.table_model.row_text(row)[0]
    metrics = ws.table.fontMetrics()
    on_mark = 6 + metrics.horizontalAdvance(text.removesuffix(vp.WARNING_MARK)) + 4
    assert ws._on_mark(row, on_mark) and not ws._on_mark(row, 3)  # on the mark, not the name
    ws.result_tabs.setCurrentIndex(0)
    ws._table_click(row, 0, 3)
    assert ws.result_tabs.currentWidget() is not ws.checks_page
    ws._table_click(row, 0, on_mark)
    assert ws.result_tabs.currentWidget() is ws.checks_page and ws.table.selected_index() == row


def test_the_capability_histogram_scale_is_chosen_beside_the_chart_and_gage_rr_has_none(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "cap_scale")
    ws.method_var.set("capability")
    run_validation(app, ws)
    assert not ws.chart_tools.isHidden() and list(ws.chart_scale_buttons) == ["auto", "full"] and ws.chart_scale_var.get() == "auto"
    result = ws.selected_result()
    assert ws.chart_panel._x_scale == "auto"
    ws.chart_scale_buttons["full"].click()  # Full Limits: both limits, at their true places
    assert ws.chart_scale_var.get() == "full" and ws.chart_panel._x_scale == "full"
    ws.chart_scale_buttons["auto"].click()
    assert ws.chart_scale_var.get() == "auto" and ws.selected_result() is result
    ws.method_var.set("grr")
    run_validation(app, ws)
    assert ws.chart_tools.isHidden() and ws.chart_panel._x_scale is None and len(ws.chart_panel.specs()) == 4


def test_the_results_table_sits_beside_the_charts_in_a_wide_window_and_above_them_in_a_narrow_one(app, window, tmp_path):
    from PySide6.QtCore import Qt

    ws = ready(app, window, tmp_path, "results_layout")
    run_validation(app, ws)
    window.resize(1400, 860)
    app.processEvents()
    assert ws.split.orientation() == Qt.Orientation.Horizontal
    window.resize(1000, 700)
    app.processEvents()
    assert ws.split.orientation() == Qt.Orientation.Vertical
    assert ws.selected_var.get() == vp.item_label(ws.selected_result())


# ----------------------------------------------------------------------------- the data
def test_the_data_tab_has_a_compact_summary_a_test_item_filter_and_marks_inferred_trials(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "data_tab")
    shown = tuple(key for key, i in zip(vp.PREVIEW_COLUMNS, range(len(vp.PREVIEW_COLUMNS)), strict=True) if not ws.preview.isColumnHidden(i))
    assert shown == vp.DISPLAY_COLUMNS
    assert [h for h, i in zip(ws.preview.headings(), range(10), strict=True) if not ws.preview.isColumnHidden(i)] == [
        "Test Item", "Sample ID", "Trial", "Value", "LSL", "USL", "Unit"]
    assert column(ws, "source")[0] and "ingerprint" not in ws.dataset_var.get() + ws.hint_var.get() + ws.preview_note_var.get()
    assert ws.hint_var.get() == "" and ws.hint_label.isHidden()  # nothing to fix, nothing said
    assert ws.preview.tags()[0] == "inferred" and "not the order of measurement" in ws.preview_note_var.get()
    ws.assign_var.set(False)  # without the labelling the readings have no Trial at all: that is a problem to fix
    assert "no Trial" in ws.hint_var.get() and ws.preview.tags()[0] == "" and not ws.hint_label.isHidden()
    ws.assign_var.set(True)
    items = [ws.item_filter.itemText(i) for i in range(ws.item_filter.count())]  # the filter
    assert items[0] == "All Test Items" and ws.item_filter_var.get() == "All Test Items" and len(items) == 4
    assert len(ws.preview.rows()) == 18
    ws.item_filter_var.set(items[1])
    assert {row[0] for row in ws.preview.rows()} == {items[1]} and len(ws.preview.rows()) == 6
    ws.item_filter_var.set("All Test Items")
    assert len(ws.preview.rows()) == 18
    assert not ws.mapping_controls.isHidden() and len(ws.order_menu.actions()) == 6  # the title and the five orders
    ws.source_var.set("file")
    assert ws.mapping_controls.isHidden() and not ws.file_controls.isHidden()
    ws.source_var.set("mapping")
    assert not ws.mapping_controls.isHidden() and ws.file_controls.isHidden()


def test_readings_are_shown_with_reasonable_precision_and_the_data_keep_their_own_values(app):
    cell = vp.ValidationWorkspace._cell
    assert cell(0.269585132598877) == "0.269585" and cell(1.5) == "1.5" and cell(40) == "40"
    assert cell(1e-8) == "0.00000001" and cell("bad") == "bad" and cell(None) == "" and cell(1234567.891) == "1234567.891" and cell(0.0) == "0"


def test_mapping_assignments_and_order_apply_to_the_snapshot_and_never_to_the_scan(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "map_logs")
    for records in window.scan_result.grouped.values():  # a tester and a slot for every file
        for record in records:
            ws.assignments[str(record.path)] = {"tester": "T1", "slot": "1"}
    ws.data_edited()
    pump(app, lambda: not ws.busy)
    run_validation(app, ws)
    assert all("Slot=1" in r.system and "Tester=T1" in r.system for r in ws.results)
    source = str(next(iter(window.scan_result.grouped.values()))[0].path)
    ws.assignments[source] = {**ws.assignments[source], "sample_id": "different-sample"}
    ws.data_edited()
    pump(app, lambda: not ws.busy)
    ws.update_button.click()
    pump(app, lambda: not ws.running and not ws.stale)
    assert any(not r.valid for r in ws.results)  # an identity edit makes the study unbalanced
    ws.assignments.clear()
    ws.method_var.set("capability")
    ws.order_var.set(vp.ORDERS["timestamp"])
    pump(app, lambda: not ws.busy)
    assert "ISO 8601" in ws.message_var.get() and ws.dataset is None
    for index, row in enumerate(r for records in window.scan_result.grouped.values() for r in records):
        ws.assignments[str(row.path)] = {"timestamp": f"2026-10-30T10:00:{50 - index:02d}"}
    ws.data_edited()
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    assert ws.dataset.order_basis == "acquisition" and "rows sorted by timestamp" in ws.dataset.description
    stamps = [o.timestamp for o in ws.dataset.observations if o.test_item == "R1"]
    assert stamps == sorted(stamps)
    run_validation(app, ws)
    assert "acquisition_order" not in {c.code for c in ws.evaluated.record.validation.conditions}


def test_a_rawdata_workbook_can_be_analysed_without_scanning_anything(app, window, tmp_path):
    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder

    from ..baseline_support import write_rawdata_logs

    logs = tmp_path / "raw_logs"
    logs.mkdir()
    write_rawdata_logs(logs)
    result = scan_folder(logs, copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"]))
    workbook = tmp_path / "RawData.xlsx"
    generate_excel(result.grouped, ["R1", "Long"], workbook, expected_repeated=2)
    window._show_workspace("validation")
    ws = window.validation
    pump(app, lambda: not ws.busy)
    ws.open_file(workbook)
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.source_var.get() == "file")
    assert ws.file_var.get() == str(workbook)
    assert all(part in ws.dataset_var.get() for part in ("Test Items 2", "Samples 3", "Total Readings 12", "Trials per Sample 2"))
    assert ws.mapping_controls.isHidden() and not ws.file_controls.isHidden()
    assert [a.text() for a in ws.order_menu.actions()] == ["Order of the readings", "Worksheet order", "Rows are in measurement order (I confirm)"]
    assert column(ws, "sample")[0] == "VSE000123"  # text serial numbers, worksheet order
    ws.assign_var.set(True)
    run_validation(app, ws)
    assert len(ws.results) == 2 and ws.study.mapping["source"] == "file"
    ws.source_var.set("mapping")  # back to Data Mapping's results: nothing scanned, so no data
    pump(app, lambda: not ws.busy)
    assert ws.dataset is None and not ws.run_button.isEnabled()


def test_importing_a_file_that_is_not_a_rawdata_workbook_says_why(app, window, tmp_path):
    from openpyxl import Workbook

    wrong = tmp_path / "wrong.xlsx"
    book = Workbook()
    book.active.append(["Name", "Value"])
    book.save(wrong)
    window._show_workspace("validation")
    ws = window.validation
    ws.open_file(wrong)
    pump(app, lambda: not ws.busy)
    assert "STT and SN" in ws.message_var.get() and ws.dataset is None


def test_file_assignment_browsing_shows_the_logs_own_identities_and_pins_nothing(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "assignment_logs")
    dialog = AssignmentDialog(ws)
    dialog.present()
    dialog.files.setCurrentRow(1)  # second file of the first sample
    assert dialog.edits["sample_id"].text() == dialog.records[1].sn and dialog.edits["trial"].text() == ""
    dialog.files.setCurrentRow(2)
    assert not dialog.pending  # browsing alone does not pin overrides
    dialog.edits["slot"].setText("Nest 2")
    dialog.apply()
    assert list(ws.assignments.values()) == [{"slot": "Nest 2"}]
    pump(app, lambda: not ws.busy)
    assert any(o.slot == "Nest 2" for o in ws.dataset.observations)


def test_an_invalid_item_does_not_stop_the_others_and_the_table_can_be_filtered(app, window, tmp_path):
    from datamapperx.models import Measurement

    folder = tmp_path / "invalid_logs"
    ready_to_review(app, window, folder)
    record = next(iter(window.scan_result.grouped.values()))[0]
    record.entries["R1"] = Measurement("R1", "bad", "0", "9")
    window._data_changed()  # what the duplicate choice does when it changes a value
    ws = open_validation(app, window)
    ws.method_var.set("capability")
    run_validation(app, ws)
    assert len(ws.results) == 3 and next(r for r in ws.results if r.test_item == "R1").status == "N/A"
    assert "1 item could not be analysed" in ws.notes_var.get() and not ws.notes_bar.isHidden()  # said where it matters
    ws.search_var.set("R1")
    assert ws.table.table_model.rowCount() == 1
    ws.search_var.set("")
    ws.judge_var.set(True)  # filtering by result needs criteria
    ws.filter_var.set("N/A")
    assert ws.table.table_model.rowCount() == 1  # the invalid item
    verdict = next(r.status for r in ws.results if r.valid)
    ws.filter_var.set(verdict)
    assert ws.table.table_model.rowCount() == len([r for r in ws.results if r.status == verdict]) == 2  # the two valid items
    window.reset_workflow()
    assert window.workspace == "validation" or window.scan_result is None


def test_review_notice_shows_only_for_acceptable_results_that_disagree(app, window, tmp_path):
    from datamapperx.statistics import Dataset, Observation

    ws = ready(app, window, tmp_path, "review_logs")
    ws.profile_var.set("SolarEdge")  # the Review flag belongs to the criteria
    wide = [Observation("Wide tolerance", f"S{part}", value, -1000, 1000, trial=str(trial), source=f"w{part}{trial}")
            for part, values in enumerate(((0, 2), (0, 2)), 1) for trial, value in enumerate(values, 1)]
    clean = [Observation("Clean", f"S{part}", value, 0, 100, trial=str(trial), source=f"c{part}{trial}")
             for part, values in enumerate(((0, .1), (10, 10.1), (20, 20.2), (30, 30.1)), 1) for trial, value in enumerate(values, 1)]
    ws._dataset_ready(Dataset.from_observations(clean))
    run_validation(app, ws)
    assert ws.review_label.isHidden() and ws.review_var.get() == ""
    ws._dataset_ready(Dataset.from_observations(wide + clean))
    ws.update_button.click()
    pump(app, lambda: not ws.running and not ws.stale)
    assert "Review" in headings(ws) and "Review needed: 1 of 2" in ws.review_var.get() and not ws.review_label.isHidden()
    flagged = next(row for row in ws.table.rows() if "Wide" in row[0])
    assert "NDC" in flagged[headings(ws).index("Review")] and flagged[headings(ws).index("Acceptance Result")] == "PASS"
    ws._dataset_ready(Dataset.from_observations(clean))
    ws.update_button.click()
    pump(app, lambda: not ws.running and not ws.stale)
    assert ws.review_label.isHidden() and ws.review_var.get() == ""


# ----------------------------------------------------------------------------- explanations, dates, customers, reports
def test_about_the_method_follows_the_analysis_and_the_selected_item(app, window, tmp_path, monkeypatch):
    from datamapperx.method_guide import guide_text

    ws = ready(app, window, tmp_path, "about_logs")
    shown = []
    monkeypatch.setattr("datamapperx.ui.method_dialog.MethodDialog", lambda parent, guide: type("D", (), {"present": lambda self: shown.append(guide)})())
    ws.method_var.set("capability")
    ws.about_button.click()
    assert shown[-1].title.startswith("Process Capability") and "1.128" in guide_text(shown[-1])
    assert "Values for the selected item" not in [s.title for s in shown[-1].sections]  # nothing analysed yet
    ws.method_var.set("grr")
    ws.about_button.click()
    assert shown[-1].title == "Variable Gage R&R" and shown[-1].method == "One-way ANOVA (Single Tester)"
    run_validation(app, ws)
    ws.table.select_row(0)
    ws.about_button.click()
    assert shown[-1].sections[-2].title == "Values for the selected item" and shown[-1].sections[-2].values


def test_the_about_dialog_draws_the_groups_of_formulas_and_they_can_be_closed(app, window):
    from datamapperx.method_guide import method_guide
    from datamapperx.statistics import AnalysisConfig
    from datamapperx.ui.math_view import MathView

    guide = method_guide(AnalysisConfig(method="grr"))
    dialog = MethodDialog(window, guide)
    dialog.present()
    titles = [section.title for section in guide.sections]
    assert titles[:3] == ["ANOVA calculations", "Variance components", "Key metrics"] and set(dialog.sections) == set(titles)
    body, _header = dialog.sections["Key metrics"]
    formulas = body.findChildren(MathView)
    assert formulas and all(w.width() > 10 and w.height() > 10 for w in formulas)
    assert not body.isHidden() and dialog.sections["Known limits"][0].isHidden()
    dialog.toggle("Key metrics")
    dialog.toggle("Known limits")
    assert body.isHidden() and not dialog.sections["Known limits"][0].isHidden()
    dialog.close()


def test_the_date_of_study_is_today_and_is_chosen_from_a_calendar_in_dd_mm_yyyy(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "date_logs")
    assert ws.date_var.get() == date.today().strftime("%d-%m-%Y") and ws.info_entries["Date of study"].isReadOnly()
    assert ws.study.info.date_of_study == ws.date_var.get()
    picked = []
    dialog = DatePickerDialog(window, date(2026, 2, 27), picked.append)
    dialog.present()
    assert dialog.month_label.text() == "February 2026"
    dialog._move(1)
    app.processEvents()  # the days of February are removed when the event loop is free
    assert dialog.month_label.text() == "March 2026"
    next(b for b in dialog.findChildren(type(ws.run_button)) if b.text() == "15" and not b.isHidden()).click()
    assert picked == [date(2026, 3, 15)]
    ws.choose_date()  # opens the calendar on the date shown
    ws._dialog_parent().findChildren(DatePickerDialog)[-1].pick(date(2026, 1, 5))
    assert ws.date_var.get() == "05-01-2026" and ws.study.info.date_of_study == "05-01-2026"
    ws.on_show()
    assert ws.date_var.get() == "05-01-2026"  # a chosen date is kept
    ws._date_chosen = False
    ws.on_show()
    assert ws.date_var.get() == date.today().strftime("%d-%m-%Y")  # until then it is today


def test_customers_are_edited_in_a_dialog_and_the_choice_is_remembered(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "customers")
    ws.criteria_button.click()
    dialog = window.findChildren(CustomersDialog)[-1]
    assert dialog.combo.currentText() == "Jabil" or dialog.combo.currentText() in ws.customers
    dialog.new_edit.setText("My customer")
    dialog.add_customer()
    assert dialog.combo.currentText() == "My customer" and "My customer" in dialog.working
    dialog.pass_edits["percent_tolerance"].setText("15")
    dialog.fail_edits["percent_tolerance"].setText("25")
    assert "15" in dialog.bands["percent_tolerance"].text()
    dialog.apply_checks["percent_tolerance"].setChecked(True)
    dialog.save()
    assert ws.profile_var.get() == "My customer" and "My customer" in window.settings.customer_criteria
    assert ws._evaluation_for("grr").criteria == ws.customers["My customer"]
    ws.criteria_button.click()
    again = window.findChildren(CustomersDialog)[-1]
    again.pass_edits["percent_tolerance"].setText("abc")
    again.save()
    assert any("PASS and FAIL limits as numbers" in text for _kind, text in window.shown)
    again.close()


def test_a_report_needs_no_study_information_and_can_cover_part_of_the_items(app, window, tmp_path, monkeypatch):
    ws = ready(app, window, tmp_path, "report_logs")
    run_validation(app, ws)
    outputs = [tmp_path / "bare.xlsx", tmp_path / "partial.xlsx"]
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (asked.append(a) or str(outputs[len(asked) - 1]), "")))
    today = date.today().strftime("%d-%m-%Y")
    assert ws.date_var.get() == today
    ws.excel_button.click()  # nothing entered: the report is made all the same
    pump(app, lambda: not ws.export_busy)
    assert ws.report_var.get() == f"Saved: {outputs[0]}"
    bare = load_workbook(outputs[0])
    assert bare.sheetnames[0] == "Summary" and len(bare.sheetnames) == 7  # a summary, then a sheet and its plot data per item
    assert not any(str(c.value).startswith(("Gage name", "Reported by")) for sheet in bare for row in sheet.iter_rows() for c in row)
    assert any(c.value == f"Date of study: {today}" for row in bare["Summary"].iter_rows() for c in row)  # today unless chosen
    bare.close()
    ws.gage_var.set("Bench DMM 7")
    ws.by_var.set("T. Man")
    ws.comments_var.set("first article")
    ws.item_list.clearSelection()
    ws.item_list.item(0).setSelected(True)
    assert ws.coverage_var.get() == "Included 1 of 3 items"
    ws.sections["observations"].set(True)
    ws.excel_button.click()
    pump(app, lambda: not ws.export_busy)
    assert ws.report_var.get() == f"Saved: {outputs[1]}" and ws.last_report == outputs[1] and ws.open_button.isEnabled()
    book = load_workbook(outputs[1])
    assert len(book.sheetnames) == 3 and book.sheetnames[-1] == "Observations"  # one item: its sheet, plot data, observations
    labels = {str(row[0].value): row[1].value for row in book[book.sheetnames[0]].iter_rows(min_col=1, max_col=2) if row[0].value}
    assert labels["Gage name:"] == "Bench DMM 7" and labels["Reported by:"] == "T. Man" and labels["Misc:"] == "first article"
    book.close()


def test_a_pdf_report_is_written_and_none_when_nothing_is_chosen(app, window, tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    ws = ready(app, window, tmp_path, "pdf_logs")
    run_validation(app, ws)
    target = tmp_path / "study.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    ws.item_list.clearSelection()
    ws.pdf_button.click()
    assert "at least one item" in ws.report_var.get() and not target.exists()
    ws._select_items(True)
    ws.pdf_button.click()
    pump(app, lambda: not ws.export_busy)
    reader = pypdf.PdfReader(str(target))
    assert len(reader.pages) >= 3 and "Gage R&R" in " ".join(page.extract_text() for page in reader.pages)


def test_the_notes_of_a_capability_analysis_point_to_the_checks_tab_without_changing_the_noted_text(app, window, tmp_path):
    ws = scanned_study(app, window, tmp_path / "notes", operators=("Ann",), readings=9, by_folder=False)
    ws.method_var.set("capability")
    run_validation(app, ws)
    ws.show_notes()
    first = window.findChildren(ReportDialog)[-1].text.toPlainText()
    assert "Stability is not tested here" in first  # the note that the report prints is unchanged
    assert "Screening in this program" in first and "not printed in the report" in first
    ws.method_var.set("grr")
    run_validation(app, ws)
    ws.show_notes()
    assert "Screening in this program" not in window.findChildren(ReportDialog)[-1].text.toPlainText()


def test_the_validation_workspace_follows_the_theme_and_shows_a_wide_report_tab(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "theme_logs")
    run_validation(app, ws)
    window._toggle_theme()
    assert ws.palette_tokens is window.palette_tokens and ws.table.palette_tokens is window.palette_tokens
    ws.tabs.setCurrentWidget(ws.report_tab)
    assert ws.item_list.count() == 3 and ws.coverage_var.get() == "Included 3 of 3 items"


def test_a_long_file_path_is_shortened_and_does_not_widen_the_workspace(app, window, tmp_path):
    ws = ready(app, window, tmp_path, "long_path_logs")
    ws.source_var.set("file")
    window.resize(1500, 800)
    ws.file_var.set("C:\\RawData.xlsx")
    QTest.qWait(200)  # the layout gives the label its room a moment after the text changes
    short = ws.minimumSizeHint().width()
    long_path = "C:\\" + "\\".join(["a long folder name"] * 12) + "\\RawData.xlsx"
    ws.file_var.set(long_path)
    QTest.qWait(200)
    assert ws.file_label.text() == long_path and ws.file_label.toolTip() == long_path  # shortened on screen, whole on hover
    assert len(QLabel.text(ws.file_label)) < len(long_path) and "…" in QLabel.text(ws.file_label)
    assert ws.minimumSizeHint().width() == short  # a long path no longer decides how narrow the window may be
