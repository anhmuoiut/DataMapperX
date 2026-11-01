"""The workspace's own code, run on a Tk that records instead of drawing (``tests/recorded_tk.py``): no window, no display, no focus.

These follow what a person does with Attribute Agreement: import a table, look at the data, set up, run, read the Results,
Details, Checks and charts, switch methods, make a report. They check what the workspace puts on screen and when it blocks.
They cannot show how it looks; that is the checklist in ``docs/attribute-gui-verification.md``.
"""
from __future__ import annotations

import dataclasses
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from datamapperx.statistics import Dataset, Observation
from datamapperx.ui import validation_workspace as workspace

from .recorded_tk import build_workspace, canvas_texts, is_gridded, last_option
from .test_ratings import MAPPING, imported, write_csv
from .test_ratings import reference_rows as file_rows


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
def recorder(monkeypatch):
    return build_workspace(monkeypatch)


def load(ws, tmp_path, rows=None, mapping=MAPPING, name="Programming.csv"):
    """What the Import dialog does when the user presses Import: the table, the mapping, the dataset."""
    ws._ratings_ready(imported(write_csv(tmp_path / name, rows if rows is not None else file_rows()), mapping))


def results_table(ws):
    return [ws.table.heading(column, "text") for column in ws.table["columns"]], [row["values"] for row in ws.table.rows()]


def numeric_study(kind):
    """A Variable Gage R&R study (10 samples x 3 readings) or a capability study (40 readings), as a dataset."""
    rng = random.Random(7)
    if kind == "grr":
        rows = [Observation("Voltage", f"S{part}", 10 + part + rng.gauss(0, 0.05), 0, 30, trial=str(trial)) for part in range(1, 11) for trial in (1, 2, 3)]
    else:
        rows = [Observation("Voltage", f"S{i}", rng.gauss(10, 0.3), 8, 12, source=f"log{i}.txt") for i in range(40)]
    return Dataset.from_observations(rows)


def use_numbers(ws, kind):
    ws.source_var.set("file")
    ws.imported = SimpleNamespace(dataset=numeric_study(kind), warnings=())
    ws.method_var.set(kind if kind != "grr" else "grr")
    ws._prepare_dataset()


# ----------------------------------------------------------------------------- start-up and the three methods
def test_the_workspace_builds_and_each_method_shows_only_its_own_settings(recorder, unreleased):
    root, ws = recorder
    assert ws.method_var.get() == "grr" and ws.confidence_var.get() == "95%" and ws.agreement_var.get() == "90" and not ws.judge_var.get()
    expected = {"grr": (True, False, False), "capability": (False, True, False), "attribute": (False, False, True)}
    for method, shown in expected.items():
        ws.method_var.set(method)
        assert tuple(is_gridded(root, frame) for frame in (ws.grr_setup, ws.cap_setup, ws.attr_setup)) == shown, method
    choices = {"grr": "{Test Item} %SV/Tol {%Study Var} NDC", "capability": "{Test Item} Cpk Ppk", "attribute": "{Test Item} {Within %} {vs Standard %} Kappa"}
    for method, expected_choices in choices.items():  # what the Sort box offers follows the method
        ws.method_var.set(method)
        assert last_option(root, ws.sort_combo, "values") == expected_choices, method
    ws.method_var.set("attribute")
    assert ws.preview["displaycolumns"] == workspace.ATTRIBUTE_COLUMNS and ws.preview.heading("operator", "text") == "Appraiser"
    assert ws.preview.heading("value", "text") == "Rating"
    ws.method_var.set("capability")
    assert ws.preview["displaycolumns"] == workspace.DISPLAY_COLUMNS and ws.preview.heading("operator", "text") == "Operator"
    assert ws.preview.heading("value", "text") == "Value"


def test_acceptance_settings_appear_only_for_the_method_that_uses_them(recorder, unreleased):
    root, ws = recorder
    ws.method_var.set("attribute")
    assert is_gridded(root, ws.agreement_row) is False  # acceptance is off: no minimum asked for
    ws.judge_var.set(True)
    assert is_gridded(root, ws.agreement_row) is True and is_gridded(root, ws.criteria_row) is True  # each in its own (hidden or shown) frame
    ws.judge_var.set(False)
    assert is_gridded(root, ws.agreement_row) is False


# ----------------------------------------------------------------------------- import and the data tab
def test_importing_a_ratings_table_makes_it_the_study_and_the_attribute_method(recorder, unreleased, tmp_path):
    root, ws = recorder
    load(ws, tmp_path)
    assert ws.method_var.get() == "attribute" and ws.source_var.get() == "ratings" and ws.setup_error == ""
    assert ws.dataset is not None and ws.study.options.method == "attribute" and ws.study.mapping["source"] == "ratings"
    assert ws.study.mapping["ratings"]["columns"]["sample"] == "Samples"  # which column held what is part of the study
    assert ws.dataset_var.get() == "Test Items 1  ·  Samples 30  ·  Appraisers 1  ·  Ratings 90  ·  Trials per Sample 3"
    assert ws.plan_var.get() == "1 Test Item · 30 Samples · 1 Appraiser" and ws.plan_title_var.get() == "Attribute Agreement"
    assert "numbered 1, 2, 3" in ws.hint_var.get() and ws.file_var.get().endswith("Programming.csv")
    rows = ws.preview.rows()
    assert len(rows) == 90 and rows[0]["values"] == ("Programming", "VSEG000001", "1", "1", "PASS", "", "", "", "Programming.csv!R2", "PASS")
    assert ws.preview.heading("value", "text") == "Rating" and ws.preview["displaycolumns"] == workspace.ATTRIBUTE_COLUMNS


def test_a_numeric_table_is_flagged_as_not_looking_like_ratings(recorder, unreleased, tmp_path):
    root, ws = recorder
    rows = [(f"S{i}", "1", f"{1.5 + i * 0.37:.3f}", "") for i in range(40) for _ in range(2)]
    load(ws, tmp_path, rows)
    assert "numbers with 40 different values" in ws.hint_var.get()


# ----------------------------------------------------------------------------- the switches
def test_attribute_agreement_cannot_be_run_or_reported_until_it_is_released(recorder, unreleased, tmp_path):
    root, ws = recorder
    load(ws, tmp_path)
    assert last_option(root, ws.run_button, "state") == "disabled" and ws.message_var.get() == workspace.ATTRIBUTE_PENDING
    ws.run_analysis()
    assert ws.results == [] and ws.message_var.get() == workspace.ATTRIBUTE_PENDING
    ws.method_var.set("grr")  # another method is not held back
    assert last_option(root, ws.run_button, "state") == "normal"


def test_a_report_of_attribute_agreement_is_withheld_until_its_own_switch_is_on(recorder, tmp_path, monkeypatch):
    root, ws = recorder
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    monkeypatch.delenv(workspace.ATTRIBUTE_REPORTS_ENV, raising=False)
    load(ws, tmp_path)
    ws.run_analysis()
    assert len(ws.results) == 1
    assert last_option(root, ws.pdf_button, "state") == "disabled" and last_option(root, ws.excel_button, "state") == "disabled"
    assert ws.report_var.get() == workspace.ATTRIBUTE_REPORT_PENDING
    asked = []
    monkeypatch.setattr(workspace.filedialog, "asksaveasfilename", lambda **kw: asked.append(kw) or "")
    ws.generate_report(".pdf")
    assert asked == [] and ws.report_var.get() == workspace.ATTRIBUTE_REPORT_PENDING  # it does not even ask where to save


# ----------------------------------------------------------------------------- run and read the results
def test_running_attribute_agreement_fills_the_table_the_details_the_checks_and_the_charts(recorder, released, tmp_path):
    root, ws = recorder
    load(ws, tmp_path)
    assert last_option(root, ws.run_button, "state") == "normal"
    ws.run_analysis()
    assert ws.summary_var.get() == "1 item analyzed · Acceptance off" and ws.setup_error == ""
    headings, rows = results_table(ws)
    assert headings == ["Test Item", "Samples", "Within %", "vs Standard %", "Kappa"]  # no acceptance column while acceptance is off
    assert rows == [("Programming", "30", "100.00", "100.00", "1.00")]
    assert ws.table.column("0", "anchor") == "w" and ws.table.column("2", "anchor") == "e" and ws.table.heading("2", "anchor") == "e"
    sections = [row["values"][0] for row in ws.grr_tree.rows() if row["tags"] == ("section",)]
    assert sections == ["Within Appraisers", "Fleiss' Kappa Statistics", "Each Appraiser vs Standard", "Fleiss' Kappa Statistics vs Standard",
                        "Assessment Disagreement"]
    assert is_gridded(root, ws.grr_frame) and not is_gridded(root, ws.grr_headline) and not is_gridded(root, ws.tables_note)  # no note to make
    rows = ws.grr_tree.rows()
    start = next(i for i, row in enumerate(rows) if row["values"][0] == "Assessment Disagreement")
    assert rows[start + 1]["values"] == ("Appraiser", "#PASS/FAIL", "Percent", "#FAIL/PASS", "Percent", "#Mixed", "Percent")  # Minitab's table
    assert rows[start + 2]["values"] == ("1", "0", "0.00", "0", "0.00", "0", "0.00") and len(rows) == start + 3
    group, = ws.checks_tree.rows()
    assert group["text"] == "Data Checks" and [(r["text"], r["values"]) for r in ws.checks_tree.rows(ws.checks_tree.get_children()[0])] == [
        ("All checks", ("No data issues detected.", "OK"))]
    texts = canvas_texts(root, ws.chart_canvas)
    assert "Within Appraisers" in texts and "Appraiser vs Standard" in texts and "Percent" in texts and "95% CI" in texts
    assert ws.selected_result().label == "Programming" and not is_gridded(root, ws.notes_bar)


def test_acceptance_adds_its_column_and_summary_and_a_bad_minimum_blocks_the_run(recorder, released, tmp_path):
    root, ws = recorder
    load(ws, tmp_path, [(s, a, r, st) for s, a, r, st in file_rows()])
    ws.run_analysis()
    ws.judge_var.set(True)  # acceptance is the user's layer on top of finished statistics: nothing is recomputed, nothing goes stale
    assert not ws.stale and ws.summary_var.get() == "1 item analyzed · 1 PASS"
    headings, rows = results_table(ws)
    assert headings[-1] == "Acceptance Result" and rows[0][-1] == "PASS" and ws.table.heading("5", "anchor") == "w"
    ws.agreement_var.set("")
    assert ws.setup_error == "Minimum agreement: enter a percentage such as 90." and last_option(root, ws.run_button, "state") == "disabled"
    ws.agreement_var.set("100")
    assert ws.setup_error == "" and ws.summary_var.get() == "1 item analyzed · 1 PASS"
    ws.agreement_var.set("100.5")
    assert "at most 100" in ws.setup_error
    ws.agreement_var.set("90")
    ws.judge_var.set(False)
    assert results_table(ws)[0] == ["Test Item", "Samples", "Within %", "vs Standard %", "Kappa"] and ws.summary_var.get().endswith("Acceptance off")


def test_sorting_puts_n_a_last_and_the_search_box_narrows_the_list(recorder, released, tmp_path):
    root, ws = recorder
    headers = ("Item", "Samples", "Appraisers", "Measurements", "Standard")
    alpha = [("Alpha", s, a, r, "") for s, a, r, _st in file_rows()]  # no Standard: vs Standard % is N/A
    beta = [("Beta", s, a, ("FAIL" if (s, i % 3) == ("VSEG000004", 1) else r), st) for i, (s, a, r, st) in enumerate(file_rows())]
    ws._ratings_ready(imported(write_csv(tmp_path / "two.csv", alpha + beta, headers), dataclasses.replace(MAPPING, item="Item")))
    ws.run_analysis()
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


def test_the_decimals_setting_changes_the_table_and_the_details(recorder, released, tmp_path):
    root, ws = recorder
    load(ws, tmp_path, [(s, a, r, st) for s, a, r, st in file_rows()])
    ws.run_analysis()
    ws.precision_var.set("4")
    assert results_table(ws)[1] == [("Programming", "30", "100.0000", "100.0000", "1.0000")]
    within = [row["values"] for row in ws.grr_tree.rows() if not row["tags"]][0]
    assert within[3] == "100.0000" and within[4].startswith("(90.4966, 100.0000)")


def test_a_study_without_a_standard_still_gives_within_and_says_so_as_info(recorder, released, tmp_path):
    root, ws = recorder
    rows = [(s, a, r, "") for s, a, r, _st in file_rows()]
    load(ws, tmp_path, rows, dataclasses.replace(MAPPING, standard=""), name="No standard.csv")
    ws.run_analysis()
    assert results_table(ws)[1] == [("No standard", "30", "100.00", "N/A", "1.00")]
    findings = [(r["text"], r["values"][1], r["tags"]) for r in ws.checks_tree.rows(ws.checks_tree.get_children()[0])]
    assert findings == [("Standard", "Info", ("Info",))]
    assert "Within Appraisers" in canvas_texts(root, ws.chart_canvas) and "Appraiser vs Standard" not in canvas_texts(root, ws.chart_canvas)
    ws.judge_var.set(True)  # without a Standard the study is not a pass
    assert ws.summary_var.get() == "1 item analyzed · 1 N/A" and results_table(ws)[1][0][-1] == "N/A"


def test_a_standard_that_cannot_be_used_is_critical_marks_the_item_and_leaves_its_panel_n_a(recorder, released, tmp_path):
    root, ws = recorder
    rows = [(s, a, r, "" if s == "VSEG000005" else st) for s, a, r, st in file_rows()]
    load(ws, tmp_path, rows)
    ws.run_analysis()
    assert results_table(ws)[1][0][2:4] == ("100.00", "N/A") and ws.summary_var.get() == "1 item analyzed · Acceptance off · 1 Need Review"
    assert results_table(ws)[1][0][0].endswith("⚠")
    findings = [(r["text"], r["values"][1], r["values"][0]) for r in ws.checks_tree.rows(ws.checks_tree.get_children()[0])]
    assert findings == [("Standard", "Critical", "Appraiser vs Standard is not computed. The Standard is missing for 1 of 30 samples")]
    assert "N/A: The Standard is missing for 1 of 30 samples." in " ".join(canvas_texts(root, ws.chart_canvas))
    assert ws.tables_note_var.get().startswith("Appraiser vs Standard is N/A.")


def test_an_item_that_could_not_be_analysed_is_counted_apart_and_listed_as_critical(recorder, released, tmp_path):
    root, ws = recorder
    load(ws, tmp_path, file_rows()[:-1])  # the last rating is missing
    ws.run_analysis()
    assert ws.summary_var.get() == "0 items analyzed · Acceptance off · 1 not analyzed"
    findings = [(r["text"], r["values"][1]) for r in ws.checks_tree.rows(ws.checks_tree.get_children()[0])]
    assert findings == [("Study layout", "Critical")]
    assert is_gridded(root, ws.notes_bar) and "could not be analysed" in ws.notes_var.get()
    assert canvas_texts(root, ws.chart_canvas) == []  # no chart for an item that has no result


def test_several_appraisers_show_n_a_in_the_table_and_a_row_each_in_the_details(recorder, released, tmp_path):
    root, ws = recorder
    rows = [(s, who, r, st) for who in ("Ann", "Ben") for s, _a, r, st in file_rows()]
    load(ws, tmp_path, rows)
    ws.run_analysis()
    assert results_table(ws)[1] == [("Programming", "30", "N/A", "N/A", "N/A")]  # not pooled: each appraiser is in the Details
    within = next(r["values"] for r in ws.grr_tree.rows() if r["values"][:1] == ("Appraiser",))
    assert within[0] == "Appraiser"
    figures = [row["values"][0] for row in ws.grr_tree.rows() if not row["tags"]]
    assert {"Ann", "Ben", "All"} <= set(figures)
    assert ws.plan_var.get() == "1 Test Item · 30 Samples · 2 Appraisers"


# ----------------------------------------------------------------------------- the other methods, and switching
def test_switching_methods_marks_the_old_results_out_of_date_and_changes_every_view(recorder, released, tmp_path):
    root, ws = recorder
    load(ws, tmp_path)
    ws.run_analysis()
    assert not ws.stale
    ws.method_var.set("capability")
    assert ws.stale and ws.plan_title_var.get() == "Process Capability" and is_gridded(root, ws.stale_banner)
    ws.method_var.set("grr")
    assert ws.stale and ws.plan_title_var.get() == "Variable Gage R&R" and ws.preview.heading("operator", "text") == "Operator"
    ws.method_var.set("attribute")
    assert not ws.stale and not is_gridded(root, ws.stale_banner) and ws.plan_title_var.get() == "Attribute Agreement"
    ws.confidence_var.set("99%")  # a statistical setting: the results no longer match it
    assert ws.stale
    ws.confidence_var.set("95%")
    assert not ws.stale


def test_gage_rr_and_capability_still_run_and_show_their_own_views(recorder, released):
    root, ws = recorder
    use_numbers(ws, "grr")
    ws.run_analysis()
    headings, rows = results_table(ws)
    assert headings[:4] == ["Test Item", "%SV/Tol", "%Study Var", "NDC"] and rows[0][0] == "Voltage"
    assert ws.summary_var.get() == "1 item analyzed · Acceptance off" and last_option(root, ws.pdf_button, "state") == "normal"
    assert [row["values"][0] for row in ws.grr_tree.rows() if row["tags"] == ("section",)] == ["One-Way ANOVA", "Variance Components", "Gage Evaluation"]
    assert is_gridded(root, ws.grr_headline) and ws.ndc_var.get() != ""
    use_numbers(ws, "capability")
    ws.run_analysis()
    headings, rows = results_table(ws)
    assert headings == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"] and rows[0][1] == "40"
    assert [ws.details.item(group, "text") for group in ws.details.get_children()] == ["Specification", "Variation", "Capability", "Advanced Details"]
    assert is_gridded(root, ws.details_frame) and not is_gridded(root, ws.grr_frame)


# ----------------------------------------------------------------------------- the report
def test_the_pdf_and_the_workbook_are_made_from_what_is_on_screen(recorder, released, tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from openpyxl import load_workbook

    root, ws = recorder
    load(ws, tmp_path, [(s, a, ("FAIL" if (s, i) == ("VSEG000004", 1) else r), st) for i, (s, a, r, st) in enumerate(file_rows())])
    ws.run_analysis()
    ws.judge_var.set(True)
    assert last_option(root, ws.pdf_button, "state") == "normal" and last_option(root, ws.excel_button, "state") == "normal"
    saved = {}
    monkeypatch.setattr(workspace.filedialog, "asksaveasfilename", lambda **kw: saved.setdefault(kw["defaultextension"], str(tmp_path / f"report{kw['defaultextension']}")))
    ws.generate_report(".pdf")
    ws.generate_report(".xlsx")
    assert ws.report_var.get().startswith("Saved:") and (tmp_path / "report.pdf").is_file() and (tmp_path / "report.xlsx").is_file()
    pages = [" ".join(page.extract_text().split()) for page in pypdf.PdfReader(tmp_path / "report.pdf").pages]
    assert len(pages) == 2 and "Within Appraisers: Assessment Agreement" in pages[0] and "Acceptance (a criterion you chose" in pages[0]
    sheet = load_workbook(tmp_path / "report.xlsx")["Programming"]
    column = [sheet.cell(row, 1).value for row in range(1, sheet.max_row + 1)]
    assert "Within Appraisers: Assessment Agreement" in column and "Acceptance (a criterion you chose, not a statistical result)" in column
    assert ws.last_report == Path(tmp_path / "report.xlsx")


def test_the_report_of_a_study_whose_results_are_out_of_date_is_refused(recorder, released, tmp_path, monkeypatch):
    root, ws = recorder
    load(ws, tmp_path)
    ws.run_analysis()
    ws.confidence_var.set("90%")
    asked = []
    monkeypatch.setattr(workspace.filedialog, "asksaveasfilename", lambda **kw: asked.append(kw) or "")
    ws.generate_report(".pdf")
    assert asked == [] and ws.report_var.get() == "Update the results before generating a report."
