"""The one-time check in the real window (docs/attribute-gui-verification.md), rehearsed without a window.

The ten sample files of tools/make_attribute_samples.py are opened the way the Import dialog opens them (its own functions and
its suggested mapping), run in the workspace on the recording Tk, and what the checklist expects is asserted. What this cannot
show is how anything looks: that is the checklist. The nine Pass/Fail studies of tools/attribute_disagreement_cases.py are
checked for what docs/attribute-minitab-comparison.md says about them.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from openpyxl import load_workbook

from datamapperx.stat_charts import agreement_charts, agreement_extra_height
from datamapperx.stat_reports import attribute_details, attribute_tables
from datamapperx.statistics.ratings import (
    RatingsFormatError,
    RatingsMapping,
    build_ratings,
    category_mapping,
    read_ratings_table,
    suggest_mapping,
)
from datamapperx.ui import validation_workspace as workspace

from .recorded_tk import build_workspace

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    return {path.name: path for path in load_tool("make_attribute_samples").write_samples(tmp_path_factory.mktemp("samples"))}


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    return build_workspace(monkeypatch)


def run_sample(ws, path, categories=()):
    """What choosing the file in the Import dialog and pressing Import, then Run, does."""
    table = read_ratings_table(path)
    ws._ratings_ready(build_ratings(table, RatingsMapping(**suggest_mapping(table.headers), categories=categories)))
    ws.run_analysis()
    group = ws.checks_tree.get_children()
    return {"table": [row["values"] for row in ws.table.rows()], "summary": ws.summary_var.get(),
            "checks": [(r["text"], r["values"][1]) for r in ws.checks_tree.rows(group[0])] if group else [],
            "sections": [r["values"][0] for r in ws.grr_tree.rows() if r["tags"] == ("section",)], "result": ws.results[0]}


ONE = ["Within Appraisers", "Fleiss' Kappa Statistics", "Each Appraiser vs Standard", "Fleiss' Kappa Statistics vs Standard", "Assessment Disagreement"]
MANY = [*ONE, "Between Appraisers", "Fleiss' Kappa Statistics (Between Appraisers)", "All Appraisers vs Standard",
        "Fleiss' Kappa Statistics (All Appraisers vs Standard)"]
OK = [("All checks", "OK")]
ANALYSED, REVIEW = "1 item analyzed · Acceptance off", "1 item analyzed · Acceptance off · 1 Need Review"


@pytest.mark.parametrize(("name", "row", "checks", "sections", "summary"), [
    ("1_reference.csv", ("1_reference", "30", "100.00", "100.00", "1.00"), OK, ONE, ANALYSED),
    ("2_one_inconsistent_sample.csv", ("2_one_inconsistent_sample", "30", "96.67", "96.67", "0.96"), OK, ONE, ANALYSED),
    ("3_three_appraisers.csv", ("3_three_appraisers", "30", "N/A", "N/A", "N/A"), OK, MANY, ANALYSED),
    ("4_no_standard.csv", ("4_no_standard", "30", "100.00", "N/A", "1.00"), [("Standard", "Info")], ONE[:2], ANALYSED),
    ("5_unusable_standard.csv", ("5_unusable_standard" + workspace.WARNING_MARK, "30", "100.00", "N/A", "1.00"), [("Standard", "Critical")],
     ONE[:2], REVIEW),
    ("6_single_trial.csv", ("6_single_trial" + workspace.WARNING_MARK, "30", "N/A", "100.00", "N/A"), [("Trials", "Review")], ONE[2:], REVIEW),
    ("8_one_category.csv", ("8_one_category" + workspace.WARNING_MARK, "30", "100.00", "100.00", "N/A"), [("Categories", "Review")], ONE[:4], REVIEW),
    ("9_workbook_two_sheets.xlsx", ("9_workbook_two_sheets", "30", "96.67", "96.67", "0.96"), OK, ONE, ANALYSED),
])
def test_each_sample_file_gives_what_the_checklist_expects(window, samples, name, row, checks, sections, summary):
    shown = run_sample(window[1], samples[name])
    assert shown["table"] == [row] and shown["summary"] == summary
    assert shown["checks"] == checks and shown["sections"] == sections


def test_the_labels_p_and_f_are_kept_until_they_are_mapped_in_the_dialog(window, samples):
    root, ws = window
    kept = run_sample(ws, samples["7_labels_P_F.csv"])
    assert kept["result"].details["levels"] == ("F", "P") and kept["table"][0][2:] == ("100.00", "100.00", "1.00")
    mapped = run_sample(ws, samples["7_labels_P_F.csv"], category_mapping({"P": "PASS", "F": "FAIL"}))
    assert mapped["result"].details["levels"] == ("FAIL", "PASS") and mapped["table"][0][2:] == ("100.00", "100.00", "1.00")
    assert {r.value for r in ws.dataset.observations} == {"PASS", "FAIL"} and {r.standard for r in ws.dataset.observations} == {"PASS", "FAIL"}


def test_the_figures_the_checklist_names(window, samples):
    root, ws = window
    d = run_sample(ws, samples["1_reference.csv"])["result"].details
    ann, = d["appraisers"]
    assert (ann["within"]["percent"], f"{ann['within']['lower']:.2f}", ann["within"]["upper"]) == (100.0, "90.50", 1.0 * 100)
    overall = ann["kappa_within"]["overall"]
    assert f"{overall['se']:.6f}" == "0.105409" and f"{overall['z']:.5f}" == "9.48683" and overall["p"] < 0.0001
    assert (ann["disagreement"]["different"], ann["disagreement"]["assessments"]) == (0, 90)
    d = run_sample(ws, samples["2_one_inconsistent_sample.csv"])["result"].details
    assert (f"{d['appraisers'][0]['within']['lower']:.2f}", f"{d['appraisers'][0]['within']['upper']:.2f}") == ("82.78", "99.92")


def test_three_appraisers_are_each_in_the_details_and_pooled_in_between_and_all_vs_standard(window, samples):
    root, ws = window
    d = run_sample(ws, samples["3_three_appraisers.csv"])["result"].details
    ann, ben, carla = d["appraisers"]
    assert [(a["name"], a["within"]["matched"], a["standard"]["matched"]) for a in (ann, ben, carla)] == [
        ("Ann", 30, 30), ("Ben", 25, 25), ("Carla", 30, 11)]  # Carla is consistent (within) but wrong on 19 samples
    assert d["between"]["matched"] == 11 and d["all_standard"]["matched"] == 11 and d["kappa_all_standard"]["reason"] == ""
    assert [r["values"][0] for r in ws.grr_tree.rows() if r["tags"] == ("section",)] == MANY


def test_twelve_long_names_are_each_in_the_tables_and_the_chart_panels_are_made_tall_enough(window, samples):
    root, ws = window
    shown = run_sample(ws, samples["10_twelve_long_names.csv"])
    d = shown["result"].details
    assert [a["name"] for a in d["appraisers"]] == list(load_tool("make_attribute_samples").LONG_NAMES) and shown["table"][0][2:] == ("N/A", "N/A", "N/A")
    assert shown["sections"] == MANY and shown["summary"] == ANALYSED
    panels = agreement_charts(shown["result"])
    assert len(panels) == 2 and all(len(p.categories) == 12 for p in panels)
    assert all(agreement_extra_height(p, 344, 204, 1.333) > 0 for p in panels)  # in the smallest panel the names would leave no plot


def test_the_workbook_offers_its_sheets_and_refuses_an_empty_one(samples):
    path = samples["9_workbook_two_sheets.xlsx"]
    assert read_ratings_table(path).sheets == ("Ratings", "Notes", "Empty") and read_ratings_table(path).sheet == "Ratings"
    assert read_ratings_table(path, "Notes").headers == ("not ratings", "x")
    with pytest.raises(RatingsFormatError, match="has no data"):
        read_ratings_table(path, "Empty")


# ----------------------------------------------------------------------------- screen, PDF and workbook hold the same figures
SCREEN_TO_REPORT = {"Within Appraisers": "Within Appraisers: Assessment Agreement", "Each Appraiser vs Standard": "Each Appraiser vs Standard: Assessment Agreement",
                    "Between Appraisers": "Between Appraisers: Assessment Agreement",
                    "All Appraisers vs Standard": "All Appraisers vs Standard: Assessment Agreement"}


def screen_tables(ws):
    """The tables of the Details tab as the tree holds them: title -> rows of cell texts."""
    tables = {}
    for row in ws.grr_tree.rows():
        if row["tags"] == ("section",):
            rows = tables.setdefault(row["values"][0], [])
        elif row["tags"] != ("head",):
            rows.append(list(row["values"]))
    return tables


def sheet_rows(sheet, title):
    start = next(row for row in range(1, sheet.max_row + 1) if sheet.cell(row, 1).value == title)
    rows, row = [], start + 2
    while sheet.cell(row, 1).value not in (None, ""):
        rows.append([sheet.cell(row, col).value for col in range(1, 9)])
        row += 1
    return rows


def full_cells(table):
    """One row of a report table as the workbook holds it: the interval is a lower and an upper cell (N/A in both when it is N/A)."""
    def cells(value, kind):
        return [value, value] if kind == "ci" and isinstance(value, str) else list(value) if kind == "ci" else [value]

    return [[cell for value, kind in zip(row, table.kinds, strict=True) for cell in cells(value, kind)] for row in table.rows]


ALL_STUDIES = ["1_reference.csv", "2_one_inconsistent_sample.csv", "3_three_appraisers.csv", "4_no_standard.csv", "5_unusable_standard.csv",
               "6_single_trial.csv", "8_one_category.csv", "9_workbook_two_sheets.xlsx", "10_twelve_long_names.csv"]


@pytest.mark.parametrize("name", ALL_STUDIES)
def test_the_screen_the_pdf_and_the_workbook_hold_the_same_figures(window, samples, tmp_path, monkeypatch, name):
    pypdf = pytest.importorskip("pypdf")
    root, ws = window
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "1")
    ws.judge_var.set(False)
    result = run_sample(ws, samples[name])["result"]
    ws.judge_var.set(True)  # and with acceptance, which is a table of its own
    chosen = {}
    monkeypatch.setattr(workspace.filedialog, "asksaveasfilename", lambda **kw: chosen.setdefault(kw["defaultextension"], str(tmp_path / f"r{kw['defaultextension']}")))
    for suffix in (".pdf", ".xlsx"):
        ws.generate_report(suffix)
        assert ws.report_var.get().startswith("Saved:"), (name, suffix, ws.report_var.get())
    tables = {t.title: t for t in attribute_tables(result)}
    precision = ws._precision()
    # the screen: every table of the Details is a table of the report, with the same cell texts
    for title, rows in screen_tables(ws).items():
        assert rows == tables[SCREEN_TO_REPORT.get(title, title)].cells(precision), (name, title)
    # the PDF: every row of every table is printed as the screen shows it
    pages = " ".join(" ".join(p.extract_text().split()) for p in pypdf.PdfReader(tmp_path / "r.pdf").pages)
    for title, table in tables.items():
        assert title in pages, (name, title)
        for row in table.cells(precision):
            assert " ".join(row) in pages, (name, title, row)
    # the workbook: the same figures, in full
    sheet = load_workbook(tmp_path / "r.xlsx").worksheets[0]
    for title, table in tables.items():
        found = sheet_rows(sheet, title)  # a note under the table follows its last row directly
        assert len(found) >= len(table.rows), (name, title)
        for cells, expected in zip(found, full_cells(table), strict=False):
            for got, want in zip(cells, expected, strict=False):
                if isinstance(want, float):
                    assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (name, title, expected)
                else:
                    assert got == want, (name, title, expected)


# ----------------------------------------------------------------------------- the Pass/Fail studies for Minitab
@pytest.fixture(scope="module")
def cases():
    return load_tool("attribute_disagreement_cases")


# What the table of Assessment Disagreement must show for each study, worked out by hand from the data of the tool: 24 samples, S01-S14
# with the Standard Pass and S15-S24 with the Standard Fail, three trials. Each entry is (count, what the percent is of, percent).
ZEROS = [(0, 10, 0.0), (0, 14, 0.0), (0, 24, 0.0)]
MULTIPLE = [(3, 10, 30.0), (2, 14, 100 * 2 / 14), (4, 24, 100 * 4 / 24)]  # S15-S17 always Pass; S01, S02 always Fail; S03, S04, S18, S19 mixed
EXPECTED = {
    "A_perfect_agreement": {"Ann": ZEROS},
    "B_consistent_false_pass": {"Ann": [(3, 10, 30.0), (0, 14, 0.0), (0, 24, 0.0)]},
    "C_consistent_false_fail": {"Ann": [(0, 10, 0.0), (2, 14, 100 * 2 / 14), (0, 24, 0.0)]},
    "D_mixed_repeated_ratings": {"Ann": [(0, 10, 0.0), (0, 14, 0.0), (4, 24, 100 * 4 / 24)]},  # wrong in one trial or two, never in all
    "E_multiple_error_types": {"Ann": MULTIPLE},
    "F_multiple_appraisers": {"Ann": MULTIPLE, "Ben": [(10, 10, 100.0), (0, 14, 0.0), (0, 24, 0.0)], "Carla": ZEROS},
    "G_missing_standard": None,
    "H_one_reference_category_absent": {"Ann": [(0, 0, None), (1, 24, 100 / 24), (1, 24, 100 / 24)]},  # no Standard Fail: nothing to divide by
    "I_every_sample_always_wrong": {"Ann": [(10, 10, 100.0), (14, 14, 100.0), (0, 24, 0.0)]},
}


def test_the_nine_studies_are_24_samples_rated_three_times(cases, tmp_path):
    assert list(cases.CASES) == list(EXPECTED)
    for path, name in zip(cases.write_cases(tmp_path), cases.CASES, strict=True):
        table = read_ratings_table(path)
        standard, appraisers = cases.CASES[name]
        assert table.headers == ("Samples", "Appraisers", "Measurements", "Standard") and len(table.rows) == 24 * 3 * len(appraisers), name
        assert all(row[3] == "" for row in table.rows) == (standard is None), name  # only the missing-Standard study has no Standard
    assert sum(s == "Pass" for s in cases.STANDARD.values()) == 14 and sum(s == "Fail" for s in cases.STANDARD.values()) == 10


@pytest.mark.parametrize("name", list(EXPECTED))
def test_the_application_shows_what_the_hand_count_of_each_study_gives(cases, name):
    result = cases.analysed(name)
    assert result.valid and not [i for i in result.issues if i.severity == "error"], name
    cases.check(name, result)  # the independent count of the tool agrees with the engine
    expected = EXPECTED[name]
    for item in result.details["appraisers"]:
        if expected is None:
            assert item["disagreement"] is None  # without a known Standard the section does not exist
        else:
            assert [(c["count"], c["base"], c["percent"]) for c in item["disagreement"]["columns"]] == [
                (count, base, pytest.approx(percent) if percent is not None else None) for count, base, percent in expected[item["name"]]], (name, item["name"])


def test_the_study_without_a_standard_has_no_section_on_screen_or_in_the_report(cases):
    result = cases.analysed("G_missing_standard")
    assert "Assessment Disagreement" not in [t.title for t in attribute_details(result)[0]]
    assert "Assessment Disagreement" not in [t.title for t in attribute_tables(result)]


def test_the_boundary_intervals_and_the_trial_level_figure_are_what_the_comparison_document_says(cases):
    wrong, = cases.analysed("I_every_sample_always_wrong").details["appraisers"]
    assert (wrong["standard"]["percent"], f"{wrong['standard']['lower']:.2f}", f"{wrong['standard']['upper']:.2f}") == (0.0, "0.00", "11.73")
    assert wrong["within"]["percent"] == 100.0 and wrong["disagreement"]["percent"] == 100.0  # all 72 ratings differ from the Standard
    perfect, = cases.analysed("A_perfect_agreement").details["appraisers"]
    assert (f"{perfect['standard']['lower']:.2f}", perfect["standard"]["upper"]) == ("88.27", 1.0 * 100) and perfect["disagreement"]["different"] == 0
