"""Attribute Agreement and the three methods side by side in the Qt workspace.

These follow what a person does: import a ratings table, look at the data, set up, run, read the Results, Details, Checks and
charts, switch methods, make a report. Attribute Agreement is held back by its two release flags exactly as in the Tk window
(``ATTRIBUTE_RESULTS_READY`` / ``ATTRIBUTE_REPORTS_READY`` stay False); the tests switch the checking variables on to run it.
"""
from __future__ import annotations

import dataclasses
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog

from datamapperx.stat_charts import chart_primitives
from datamapperx.statistics import Dataset, Observation
from datamapperx.ui import validation_workspace as workspace

from ..test_ratings import MAPPING, imported, write_csv
from ..test_ratings import reference_rows as file_rows
from .support import pump
from .test_validation import check_rows, grr_rows


@pytest.fixture
def released(monkeypatch):
    """The two switches that let Attribute Agreement run and make its report, as when it is being checked."""
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "1")


@pytest.fixture
def unreleased(monkeypatch):
    for name in (workspace.ATTRIBUTE_PREVIEW_ENV, workspace.ATTRIBUTE_REPORTS_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def ws(app, window):
    window._show_workspace("validation")
    pump(app, lambda: not window.validation.busy)
    return window.validation


def load(app, ws, tmp_path, rows=None, mapping=MAPPING, name="Programming.csv"):
    """What the Import dialog does when the user presses Import: the table, the mapping, the dataset."""
    ws._ratings_ready(imported(write_csv(tmp_path / name, rows if rows is not None else file_rows()), mapping))
    pump(app, lambda: ws.dataset is not None and not ws.busy)


def run(app, ws):
    ws.run_analysis()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    return ws


def results_table(ws):
    return ws.table.headings(), [tuple(row) for row in ws.table.rows()]


def chart_texts(ws):
    panel = ws.chart_panel
    texts = [style["text"] for spec in panel.specs() for kind, _coords, style in chart_primitives(spec, 600, 300, panel._x_scale, True, 1.0)
             if kind == "text"]
    return texts or ([panel._note] if panel._note else [])


def numeric_study(kind):
    """A Variable Gage R&R study (10 samples x 3 readings) or a capability study (40 readings), as a dataset."""
    rng = random.Random(7)
    if kind == "grr":
        rows = [Observation("Voltage", f"S{part}", 10 + part + rng.gauss(0, 0.05), 0, 30, trial=str(trial)) for part in range(1, 11)
                for trial in (1, 2, 3)]
    else:
        rows = [Observation("Voltage", f"S{i}", rng.gauss(10, 0.3), 8, 12, source=f"log{i}.txt") for i in range(40)]
    return Dataset.from_observations(rows)


def use_numbers(app, ws, kind):
    ws.source_var.set("file")
    ws.imported = SimpleNamespace(dataset=numeric_study(kind), warnings=())
    ws.method_var.set(kind)
    ws._prepare_dataset()
    pump(app, lambda: ws.dataset is not None and not ws.busy)


# ----------------------------------------------------------------------------- start-up and the three methods
def test_the_workspace_builds_and_each_method_shows_only_its_own_settings(app, ws, unreleased):
    assert ws.method_var.get() == "grr" and ws.confidence_var.get() == "95%" and ws.agreement_var.get() == "90" and not ws.judge_var.get()
    expected = {"grr": (True, False, False), "capability": (False, True, False), "attribute": (False, False, True)}
    for method, shown in expected.items():
        ws.method_var.set(method)
        assert tuple(not frame.isHidden() for frame in (ws.grr_setup, ws.cap_setup, ws.attr_setup)) == shown, method
    choices = {"grr": ["Test Item", "%SV/Tol", "%Study Var", "NDC"], "capability": ["Test Item", "Cpk", "Ppk"],
               "attribute": ["Test Item", "Within %", "vs Standard %", "Kappa"]}
    for method, expected_choices in choices.items():  # what the Sort box offers follows the method
        ws.method_var.set(method)
        assert [ws.sort_combo.itemText(i) for i in range(ws.sort_combo.count())] == expected_choices, method
    ws.method_var.set("attribute")
    shown = [key for i, key in enumerate(workspace.PREVIEW_COLUMNS) if not ws.preview.isColumnHidden(i)]
    assert tuple(shown) == workspace.ATTRIBUTE_COLUMNS and ws.preview.headings()[2] == "Appraiser" and ws.preview.headings()[4] == "Rating"
    ws.method_var.set("capability")
    shown = [key for i, key in enumerate(workspace.PREVIEW_COLUMNS) if not ws.preview.isColumnHidden(i)]
    assert tuple(shown) == workspace.DISPLAY_COLUMNS and ws.preview.headings()[2] == "Operator" and ws.preview.headings()[4] == "Value"


def test_acceptance_settings_appear_only_for_the_method_that_uses_them(app, ws, unreleased):
    ws.method_var.set("attribute")
    assert ws.agreement_row.isHidden()  # acceptance is off: no minimum asked for
    ws.judge_var.set(True)
    assert not ws.agreement_row.isHidden() and not ws.criteria_row.isHidden()  # each in its own (hidden or shown) frame
    ws.judge_var.set(False)
    assert ws.agreement_row.isHidden()


def test_the_release_flags_are_still_off_and_the_variables_override_them(monkeypatch, unreleased):
    assert workspace.ATTRIBUTE_RESULTS_READY is False and workspace.ATTRIBUTE_REPORTS_READY is False
    assert not workspace.attribute_runnable() and "cannot be run yet" in workspace.ATTRIBUTE_PENDING
    assert not workspace.attribute_reportable() and "not available yet" in workspace.ATTRIBUTE_REPORT_PENDING
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    assert workspace.attribute_runnable() and not workspace.attribute_reportable()  # running and reporting are checked one at a time
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "1")
    assert workspace.attribute_reportable()
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "0")
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "0")
    assert not workspace.attribute_runnable() and not workspace.attribute_reportable()
    assert set(workspace.METHOD_NAMES) == set(workspace.PLAN_TITLES) == {"grr", "capability", "attribute"}
    assert workspace.CONFIDENCE_LEVELS == ("90%", "95%", "99%")


# ----------------------------------------------------------------------------- import and the data tab
def test_importing_a_ratings_table_makes_it_the_study_and_the_attribute_method(app, ws, unreleased, tmp_path):
    load(app, ws, tmp_path)
    assert ws.method_var.get() == "attribute" and ws.source_var.get() == "ratings" and ws.setup_error == ""
    assert ws.dataset is not None and ws.study.options.method == "attribute" and ws.study.mapping["source"] == "ratings"
    assert ws.study.mapping["ratings"]["columns"]["sample"] == "Samples"  # which column held what is part of the study
    assert ws.dataset_var.get() == "Test Items 1  ·  Samples 30  ·  Appraisers 1  ·  Ratings 90  ·  Trials per Sample 3"
    assert ws.plan_var.get() == "1 Test Item · 30 Samples · 1 Appraiser" and ws.plan_title_var.get() == "Attribute Agreement"
    assert "numbered 1, 2, 3" in ws.hint_var.get() and ws.file_var.get().endswith("Programming.csv")
    rows = ws.preview.rows()
    assert len(rows) == 90 and rows[0] == ("Programming", "VSEG000001", "1", "1", "PASS", "", "", "", "Programming.csv!R2", "PASS")


def test_a_numeric_table_is_flagged_as_not_looking_like_ratings(app, ws, unreleased, tmp_path):
    rows = [(f"S{i}", "1", f"{1.5 + i * 0.37:.3f}", "") for i in range(40) for _ in range(2)]
    load(app, ws, tmp_path, rows)
    assert "numbers with 40 different values" in ws.hint_var.get()


def test_the_ratings_import_dialog_maps_columns_and_renames_categories(app, ws, tmp_path):
    from datamapperx.statistics.ratings import read_ratings_table
    from datamapperx.ui.ratings_import import RatingsImportDialog

    table = read_ratings_table(write_csv(tmp_path / "r.csv", file_rows()))
    done = []
    dialog = RatingsImportDialog(ws.window(), table, done.append)
    dialog.present()
    assert dialog.imported is not None and dialog.import_button.isEnabled() and dialog.preview.table_model.rowCount() == 90
    assert "30 samples" in dialog.summary.text() and set(dialog.names) == {"PASS", "FAIL"}
    dialog.boxes["rating"].setCurrentText("(none)")  # the Rating column is required
    assert dialog.imported is None and not dialog.import_button.isEnabled() and dialog.message.text()
    dialog.boxes["rating"].setCurrentText(table.headers[2])
    dialog.names["PASS"].setText("OK")
    assert "OK" in dialog.summary.text()
    dialog.import_button.click()
    assert len(done) == 1 and "OK" in done[0].categories


# ----------------------------------------------------------------------------- the switches
def test_attribute_agreement_cannot_be_run_or_reported_until_it_is_released(app, ws, unreleased, tmp_path):
    load(app, ws, tmp_path)
    assert not ws.run_button.isEnabled() and ws.message_var.get() == workspace.ATTRIBUTE_PENDING
    ws.run_analysis()
    assert ws.results == [] and ws.message_var.get() == workspace.ATTRIBUTE_PENDING
    ws.method_var.set("grr")  # another method is not held back
    assert ws.run_button.isEnabled()


def test_a_report_of_attribute_agreement_is_withheld_until_its_own_switch_is_on(app, ws, tmp_path, monkeypatch):
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    monkeypatch.delenv(workspace.ATTRIBUTE_REPORTS_ENV, raising=False)
    load(app, ws, tmp_path)
    run(app, ws)
    assert len(ws.results) == 1 and not ws.pdf_button.isEnabled() and not ws.excel_button.isEnabled()
    assert ws.report_var.get() == workspace.ATTRIBUTE_REPORT_PENDING
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: asked.append(a) or ("", "")))
    ws.generate_report(".pdf")
    assert asked == [] and ws.report_var.get() == workspace.ATTRIBUTE_REPORT_PENDING  # it does not even ask where to save


# ----------------------------------------------------------------------------- run and read the results
def test_running_attribute_agreement_fills_the_table_the_details_the_checks_and_the_charts(app, ws, released, tmp_path):
    load(app, ws, tmp_path)
    assert ws.run_button.isEnabled()
    run(app, ws)
    assert ws.summary_var.get() == "1 item analyzed · Acceptance off" and ws.setup_error == ""
    headings, rows = results_table(ws)
    assert headings == ["Test Item", "Samples", "Within %", "vs Standard %", "Kappa"]  # no acceptance column while acceptance is off
    assert rows == [("Programming", "30", "100.00", "100.00", "1.00")]
    sections = [cells[0] for cells, tag in grr_rows(ws) if tag == "section"]
    assert sections == ["Within Appraisers", "Fleiss' Kappa Statistics", "Each Appraiser vs Standard", "Fleiss' Kappa Statistics vs Standard",
                        "Assessment Disagreement"]
    assert ws.details_stack.currentWidget() is ws.grr_frame and ws.grr_headline.isHidden() and ws.tables_note.isHidden()
    rows = grr_rows(ws)
    start = next(i for i, (cells, _tag) in enumerate(rows) if cells[0] == "Assessment Disagreement")
    assert rows[start + 1][0] == ("Appraiser", "#PASS/FAIL", "Percent", "#FAIL/PASS", "Percent", "#Mixed", "Percent")  # Minitab's table
    assert rows[start + 2][0] == ("1", "0", "0.00", "0", "0.00", "0", "0.00") and len(rows) == start + 3
    assert check_rows(ws) == [("Data Checks", "All checks", "No data issues detected.", "OK")]
    texts = chart_texts(ws)
    assert "Within Appraisers" in texts and "Appraiser vs Standard" in texts and "Percent" in texts and "95% CI" in texts
    assert ws.selected_result().label == "Programming" and ws.notes_bar.isHidden()


def test_acceptance_adds_its_column_and_summary_and_a_bad_minimum_blocks_the_run(app, ws, released, tmp_path):
    load(app, ws, tmp_path)
    run(app, ws)
    ws.judge_var.set(True)  # acceptance is the user's layer on top of finished statistics: nothing is recomputed, nothing goes stale
    assert not ws.stale and ws.summary_var.get() == "1 item analyzed · 1 PASS"
    headings, rows = results_table(ws)
    assert headings[-1] == "Acceptance Result" and rows[0][-1] == "PASS"
    ws.agreement_var.set("")
    assert ws.setup_error == "Minimum agreement: enter a percentage such as 90." and not ws.run_button.isEnabled()
    ws.agreement_var.set("100")
    assert ws.setup_error == "" and ws.summary_var.get() == "1 item analyzed · 1 PASS"
    ws.agreement_var.set("100.5")
    assert "at most 100" in ws.setup_error
    ws.agreement_var.set("90")
    ws.judge_var.set(False)
    assert results_table(ws)[0] == ["Test Item", "Samples", "Within %", "vs Standard %", "Kappa"] and ws.summary_var.get().endswith("Acceptance off")


def test_sorting_puts_n_a_last_and_the_search_box_narrows_the_list(app, ws, released, tmp_path):
    headers = ("Item", "Samples", "Appraisers", "Measurements", "Standard")
    alpha = [("Alpha", s, a, r, "") for s, a, r, _st in file_rows()]  # no Standard: vs Standard % is N/A
    beta = [("Beta", s, a, ("FAIL" if (s, i % 3) == ("VSEG000004", 1) else r), st) for i, (s, a, r, st) in enumerate(file_rows())]
    ws._ratings_ready(imported(write_csv(tmp_path / "two.csv", alpha + beta, headers), dataclasses.replace(MAPPING, item="Item")))
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    run(app, ws)
    assert ws.summary_var.get() == "2 items analyzed · Acceptance off"
    assert [row[0] for row in results_table(ws)[1]] == ["Alpha", "Beta"]
    ws.sort_var.set("vs Standard %")
    assert [(row[0], row[3]) for row in results_table(ws)[1]] == [("Beta", "96.67"), ("Alpha", "N/A")]  # N/A last, not first
    ws.sort_var.set("Within %")
    assert [(row[0], row[2]) for row in results_table(ws)[1]] == [("Beta", "96.67"), ("Alpha", "100.00")]
    ws.search_var.set("alp")
    assert [row[0] for row in results_table(ws)[1]] == ["Alpha"]
    ws.search_var.set("")
    ws.sort_var.set("Test Item")
    assert [row[0] for row in results_table(ws)[1]] == ["Alpha", "Beta"]


def test_the_decimals_setting_changes_the_table_and_the_details(app, ws, released, tmp_path):
    load(app, ws, tmp_path)
    run(app, ws)
    ws.precision_var.set("4")
    assert results_table(ws)[1] == [("Programming", "30", "100.0000", "100.0000", "1.0000")]
    within = next(cells for cells, tag in grr_rows(ws) if not tag)
    assert within[3] == "100.0000" and within[4].startswith("(90.4966, 100.0000)")


def test_a_study_without_a_standard_still_gives_within_and_says_so_as_info(app, ws, released, tmp_path):
    rows = [(s, a, r, "") for s, a, r, _st in file_rows()]
    load(app, ws, tmp_path, rows, dataclasses.replace(MAPPING, standard=""), name="No standard.csv")
    run(app, ws)
    assert results_table(ws)[1] == [("No standard", "30", "100.00", "N/A", "1.00")]
    assert [(row[1], row[3]) for row in check_rows(ws)] == [("Standard", "Info")]
    assert "Within Appraisers" in chart_texts(ws) and "Appraiser vs Standard" not in chart_texts(ws)
    ws.judge_var.set(True)  # without a Standard the study is not a pass
    assert ws.summary_var.get() == "1 item analyzed · 1 N/A" and results_table(ws)[1][0][-1] == "N/A"


def test_a_standard_that_cannot_be_used_is_critical_marks_the_item_and_leaves_its_panel_n_a(app, ws, released, tmp_path):
    rows = [(s, a, r, "" if s == "VSEG000005" else st) for s, a, r, st in file_rows()]
    load(app, ws, tmp_path, rows)
    run(app, ws)
    assert results_table(ws)[1][0][2:4] == ("100.00", "N/A") and ws.summary_var.get() == "1 item analyzed · Acceptance off · 1 Need Review"
    assert results_table(ws)[1][0][0].endswith(workspace.WARNING_MARK)
    assert [(row[1], row[3], row[2]) for row in check_rows(ws)] == [
        ("Standard", "Critical", "Appraiser vs Standard is not computed. The Standard is missing for 1 of 30 samples")]
    assert "N/A: The Standard is missing for 1 of 30 samples." in " ".join(chart_texts(ws))
    assert ws.tables_note_var.get().startswith("Appraiser vs Standard is N/A.")


def test_an_item_that_could_not_be_analysed_is_counted_apart_and_listed_as_critical(app, ws, released, tmp_path):
    load(app, ws, tmp_path, file_rows()[:-1])  # the last rating is missing
    run(app, ws)
    assert ws.summary_var.get() == "0 items analyzed · Acceptance off · 1 not analyzed"
    assert [(row[1], row[3]) for row in check_rows(ws)] == [("Study layout", "Critical")]
    assert not ws.notes_bar.isHidden() and "could not be analysed" in ws.notes_var.get()
    assert ws.chart_panel.specs() == []  # no chart for an item that has no result


def test_several_appraisers_show_n_a_in_the_table_and_a_row_each_in_the_details(app, ws, released, tmp_path):
    rows = [(s, who, r, st) for who in ("Ann", "Ben") for s, _a, r, st in file_rows()]
    load(app, ws, tmp_path, rows)
    run(app, ws)
    assert results_table(ws)[1] == [("Programming", "30", "N/A", "N/A", "N/A")]  # not pooled: each appraiser is in the Details
    figures = [cells[0] for cells, tag in grr_rows(ws) if not tag]
    assert {"Ann", "Ben", "All"} <= set(figures)
    assert ws.plan_var.get() == "1 Test Item · 30 Samples · 2 Appraisers"


# ----------------------------------------------------------------------------- the other methods, and switching
def test_switching_methods_marks_the_old_results_out_of_date_and_changes_every_view(app, ws, released, tmp_path):
    load(app, ws, tmp_path)
    run(app, ws)
    assert not ws.stale
    ws.method_var.set("capability")
    assert ws.stale and ws.plan_title_var.get() == "Process Capability" and not ws.stale_banner.isHidden()
    ws.method_var.set("grr")
    assert ws.stale and ws.plan_title_var.get() == "Variable Gage R&R" and ws.preview.headings()[2] == "Operator"
    ws.method_var.set("attribute")
    assert not ws.stale and ws.stale_banner.isHidden() and ws.plan_title_var.get() == "Attribute Agreement"
    ws.confidence_var.set("99%")  # a statistical setting: the results no longer match it
    assert ws.stale
    ws.confidence_var.set("95%")
    assert not ws.stale


def test_gage_rr_and_capability_still_run_and_show_their_own_views(app, ws, released):
    use_numbers(app, ws, "grr")
    run(app, ws)
    headings, rows = results_table(ws)
    assert headings[:4] == ["Test Item", "%SV/Tol", "%Study Var", "NDC"] and rows[0][0] == "Voltage"
    assert ws.summary_var.get() == "1 item analyzed · Acceptance off" and ws.pdf_button.isEnabled()
    assert [cells[0] for cells, tag in grr_rows(ws) if tag == "section"] == ["One-Way ANOVA", "Variance Components", "Gage Evaluation"]
    assert not ws.grr_headline.isHidden() and ws.ndc_var.get() != ""
    use_numbers(app, ws, "capability")
    run(app, ws)
    headings, rows = results_table(ws)
    assert headings == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"] and rows[0][1] == "40"
    assert [ws.details.topLevelItem(i).text(0) for i in range(ws.details.topLevelItemCount())] == [
        "Specification", "Variation", "Capability", "Advanced Details"]
    assert ws.details_stack.currentWidget() is ws.details


# ----------------------------------------------------------------------------- the report
def test_the_pdf_and_the_workbook_are_made_from_what_is_on_screen(app, ws, released, tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from openpyxl import load_workbook

    load(app, ws, tmp_path, [(s, a, ("FAIL" if (s, i) == ("VSEG000004", 1) else r), st) for i, (s, a, r, st) in enumerate(file_rows())])
    run(app, ws)
    ws.judge_var.set(True)
    assert ws.pdf_button.isEnabled() and ws.excel_button.isEnabled()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda parent, title, initial, *a: (str(tmp_path / f"report{Path(initial).suffix}"), "")))
    ws.generate_report(".pdf")
    pump(app, lambda: not ws.export_busy)
    ws.generate_report(".xlsx")
    pump(app, lambda: not ws.export_busy)
    assert ws.report_var.get().startswith("Saved:") and (tmp_path / "report.pdf").is_file() and (tmp_path / "report.xlsx").is_file()
    pages = [" ".join(page.extract_text().split()) for page in pypdf.PdfReader(tmp_path / "report.pdf").pages]
    assert len(pages) == 2 and "Within Appraisers: Assessment Agreement" in pages[0] and "Acceptance (a criterion you chose" in pages[0]
    sheet = load_workbook(tmp_path / "report.xlsx")["Programming"]
    column = [sheet.cell(row, 1).value for row in range(1, sheet.max_row + 1)]
    assert "Within Appraisers: Assessment Agreement" in column and "Acceptance (a criterion you chose, not a statistical result)" in column
    assert ws.last_report == Path(tmp_path / "report.xlsx")


def test_the_report_of_a_study_whose_results_are_out_of_date_is_refused(app, ws, released, tmp_path, monkeypatch):
    load(app, ws, tmp_path)
    run(app, ws)
    ws.confidence_var.set("90%")
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: asked.append(a) or ("", "")))
    ws.generate_report(".pdf")
    assert asked == [] and ws.report_var.get() == "Update the results before generating a report."
