"""Attribute Agreement (P4): the PDF and Excel report, and the tables they are made from.

The report prints the result snapshot that the screen shows, and nothing is calculated again. Every check here is headless: the
PDF is read back as text and as pages, the workbook as cells, number formats and chart parts.
"""
from __future__ import annotations

import dataclasses
import re
import zipfile

import pytest
from openpyxl import load_workbook

from datamapperx.stat_reports import (
    ReportContext,
    _excel_format,
    acceptance_table,
    attribute_details,
    attribute_tables,
    export_statistical_report,
    format_value,
    session_text,
)
from datamapperx.statistics import AnalysisConfig, analyze
from datamapperx.statistics.attribute import agreement_interval

from .test_attribute import ATTRIBUTE, only, pass_only_rows, rate, reference_rows
from .test_attribute_charts import appraisers_study

JUDGED = AnalysisConfig(method="attribute", agreement_min=90)
CONTEXT = ReportContext(info=(("Gage name", "FIXTURE-1163"), ("Date of study", "10-22-2026"), ("Reported by", "Thao Le")), included=1, total=1,
                        sections=("charts", "observations"))
NO_CHARTS = dataclasses.replace(CONTEXT, sections=())


def titled(tables):
    return {table.title: table for table in tables}


def pdf_text(path):
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(path).pages)


def flat(text):
    return " ".join(text.split())


# ----------------------------------------------------------------------------- how a figure is written
def test_an_interval_a_p_value_and_extra_decimals_are_written_the_same_in_every_report():
    assert format_value((90.4966147, 100.0), "ci", 2) == "(90.50, 100.00)" and format_value((90.4966147, 100.0), "ci", 4) == "(90.4966, 100.0000)"
    assert [format_value(p, "p4") for p in (0.0, 1.19e-21, 0.00004, 0.00005, 0.0123, 1.0)] == ["<0.0001", "<0.0001", "<0.0001", "0.0001", "0.0123", "1.0000"]
    assert format_value(0.1054092553, "f+4", 2) == "0.105409" and format_value(9.4868329805, "f+3", 2) == "9.48683"
    assert format_value(0.1054092553, "f+4", 4) == "0.10540926" and format_value("N/A", "f+4", 2) == "N/A"
    assert _excel_format(0.1, "f+4", 2) == "0.000000" and _excel_format(1e-21, "p4", 2) == '[<0.00005]"<0.0001";0.0000'
    assert format_value(None, "f") == "*"  # what the other reports print for an undefined figure is unchanged


# ----------------------------------------------------------------------------- the tables
def test_the_reference_study_prints_the_tables_of_minitabs_report_in_order():
    tables = attribute_tables(only(reference_rows(), ATTRIBUTE))
    assert [t.title for t in tables] == ["Within Appraisers: Assessment Agreement", "Fleiss' Kappa Statistics",
                                         "Each Appraiser vs Standard: Assessment Agreement", "Fleiss' Kappa Statistics vs Standard",
                                         "Assessment Disagreement"]
    within, kappa, against = tables[:3]
    assert within.headers == ("Appraiser", "# Inspected", "# Matched", "Percent", "95% CI") and within.kinds == ("text", "int", "int", "f", "ci")
    (label, inspected, matched, percent, (lower, upper)), = within.rows
    assert (label, inspected, matched, percent, upper) == ("1", 30, 30, 100.0, 100.0) and lower == pytest.approx(100 * agreement_interval(30, 30)[0], abs=1e-12)
    assert round(lower, 2) == 90.50 and against.rows == within.rows  # the published 30 of 30
    assert kappa.headers == ("Appraiser", "Response", "Kappa", "SE Kappa", "Z", "P(vs > 0)")
    assert [row[:2] for row in kappa.rows] == [("1", "Fail"), ("1", "Pass")]
    for row in kappa.rows:
        assert row[2] == pytest.approx(1.0) and round(row[3], 6) == 0.105409 and round(row[4], 5) == 9.48683 and 0 <= row[5] < 1e-15
    assert kappa.cells(2)[0] == ["1", "Fail", "1.00", "0.105409", "9.48683", "<0.0001"]
    assert tables[3].rows == kappa.rows  # the same ratings, trial by trial against the Standard


def test_several_appraisers_are_printed_one_row_each_and_compared_where_the_study_allows():
    result = only(appraisers_study(("Ann", "Ben", "Carla"), {("Ben", n, 1) for n in range(1, 6)}), ATTRIBUTE)
    tables = titled(attribute_tables(result))
    assert [row[0] for row in tables["Within Appraisers: Assessment Agreement"].rows] == ["Ann", "Ben", "Carla"]
    assert [row[0] for row in tables["Fleiss' Kappa Statistics"].rows] == ["Ann", "Ann", "Ben", "Ben", "Carla", "Carla"]  # per appraiser
    assert tables["Between Appraisers: Assessment Agreement"].rows[0][:4] == ("All", 30, 25, pytest.approx(100 * 25 / 30))
    assert tables["All Appraisers vs Standard: Assessment Agreement"].rows[0][:3] == ("All", 30, 25)
    single = titled(attribute_tables(only(reference_rows(), ATTRIBUTE)))
    assert not any(title.startswith(("Between", "All Appraisers")) for title in single)  # not for one appraiser


def test_a_response_count_above_two_adds_the_overall_kappa_to_each_appraiser():
    levels, rows = ("Pass", "Fail", "Hold"), []
    for number in range(1, 31):
        truth = levels[number % 3]
        rows += rate(f"S{number:02d}", [truth] * 3, truth)
    kappa = titled(attribute_tables(only(rows, ATTRIBUTE)))["Fleiss' Kappa Statistics"]
    assert [row[1] for row in kappa.rows] == ["Fail", "Hold", "Pass", "Overall"]


def test_what_the_study_does_not_have_is_not_printed_and_what_cannot_be_computed_is_n_a_with_its_reason():
    no_standard = titled(attribute_tables(only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE)))
    assert list(no_standard) == ["Within Appraisers: Assessment Agreement", "Fleiss' Kappa Statistics"]  # nothing against a Standard that is not there
    one_trial = titled(attribute_tables(only(reference_rows(trials=1), ATTRIBUTE)))
    assert not any(title.startswith("Within") for title in one_trial) and "Each Appraiser vs Standard: Assessment Agreement" in one_trial
    unusable = [dataclasses.replace(r, standard="") if r.sample_id == "S05" else r for r in reference_rows()]
    against = titled(attribute_tables(only(unusable, ATTRIBUTE)))["Each Appraiser vs Standard: Assessment Agreement"]
    assert against.rows == (("1", "N/A", "N/A", "N/A", "N/A"),) and against.note == "N/A: The Standard is missing for 1 of 30 samples."
    assert against.cells(2) == [["1", "N/A", "N/A", "N/A", "N/A"]]
    one_category = [dataclasses.replace(r, value="Pass", standard="Pass") for r in reference_rows()]
    kappa = titled(attribute_tables(only(one_category, ATTRIBUTE)))["Fleiss' Kappa Statistics"]
    assert kappa.rows == (("1", "Pass", "N/A", "N/A", "N/A", "N/A"),) and kappa.note == "N/A: kappa is not defined for a response with no variation."
    assert attribute_tables(only(reference_rows()[:-1], ATTRIBUTE)) == []  # an item that could not be analysed has none


def test_the_report_prints_minitabs_assessment_disagreement_table():
    # sample 3 (Standard Pass) is always rated Fail; sample 20 (Standard Fail) is rated wrongly once, so its trials differ
    result = only(reference_rows(mistakes={(3, 1), (3, 2), (3, 3), (20, 1)}), ATTRIBUTE)
    table = titled(attribute_tables(result))["Assessment Disagreement"]
    assert table.headers == ("Appraiser", "#Pass/Fail", "Percent", "#Fail/Pass", "Percent", "#Mixed", "Percent")
    assert table.kinds == ("text", "int", "f", "int", "f", "int", "f")
    assert table.rows == (("1", 0, 0.0, 1, pytest.approx(100 / 15), 1, pytest.approx(100 / 30)),)  # 15 Pass samples, 15 Fail, 30 in all
    assert table.note == "" and table.cells(2) == [["1", "0", "0.00", "1", "6.67", "1", "3.33"]]  # nothing about a rule or a verification


def test_a_percent_with_nothing_to_divide_by_is_n_a_in_the_report_and_says_why():
    table = titled(attribute_tables(only(pass_only_rows({3: "FFF", 7: "PFP"}), ATTRIBUTE)))["Assessment Disagreement"]
    assert table.rows == (("1", 0, "N/A", 1, pytest.approx(100 / 30), 1, pytest.approx(100 / 30)),)  # no sample has the Standard Fail
    assert table.cells(2) == [["1", "0", "N/A", "1", "3.33", "1", "3.33"]] and table.note == "N/A: no sample has that value as its Standard."


def test_acceptance_is_a_separate_optional_table_and_never_part_of_the_statistics():
    judged = only(reference_rows(mistakes={(4, 2)}), JUDGED)
    table = acceptance_table(judged)
    assert table.title.startswith("Acceptance") and "not a statistical result" in table.title
    assert table.rows == (("Within Appraisers", "90 %", "PASS"), ("Appraiser vs Standard", "90 %", "PASS"), ("Overall", "", "PASS"))
    assert acceptance_table(only(reference_rows(), ATTRIBUTE)) is None  # off: nothing about acceptance
    assert not any("PASS" in str(cell) or "FAIL" in str(cell) for t in attribute_tables(judged) for row in t.rows for cell in row)
    no_standard = acceptance_table(only([dataclasses.replace(r, standard="") for r in reference_rows()], JUDGED))
    assert [row[2] for row in no_standard.rows] == ["PASS", "N/A", "N/A"]  # without a Standard it is not a pass


def test_the_screen_and_the_report_hold_the_same_figures():
    result = only(appraisers_study(("Ann", "Ben"), {("Ben", n, 1) for n in range(1, 6)}), ATTRIBUTE)
    shown, printed = titled(attribute_details(result, 2)[0]), titled(attribute_tables(result))
    pairs = {"Within Appraisers": "Within Appraisers: Assessment Agreement", "Fleiss' Kappa Statistics": "Fleiss' Kappa Statistics",
             "Each Appraiser vs Standard": "Each Appraiser vs Standard: Assessment Agreement",
             "Fleiss' Kappa Statistics vs Standard": "Fleiss' Kappa Statistics vs Standard", "Assessment Disagreement": "Assessment Disagreement",
             "Between Appraisers": "Between Appraisers: Assessment Agreement",
             "Fleiss' Kappa Statistics (Between Appraisers)": "Fleiss' Kappa Statistics (Between Appraisers)",
             "All Appraisers vs Standard": "All Appraisers vs Standard: Assessment Agreement",
             "Fleiss' Kappa Statistics (All Appraisers vs Standard)": "Fleiss' Kappa Statistics (All Appraisers vs Standard)"}
    assert list(shown) == list(pairs) and list(printed) == list(pairs.values())  # the same tables, in the same order (Minitab's)
    for screen, report in pairs.items():
        assert [list(row) for row in shown[screen].rows] == printed[report].cells(2), screen
    again = titled(attribute_details(result, 4)[0])  # and with other decimals
    assert [list(row) for row in again["Within Appraisers"].rows] == titled(attribute_tables(result))[pairs["Within Appraisers"]].cells(4)


def test_the_text_version_lists_the_same_tables():
    text = session_text(only(reference_rows(mistakes={(4, 2)}), JUDGED))
    for expected in ("Attribute Agreement Analysis", "Within Appraisers: Assessment Agreement", "(82.78, 99.92)", "Assessment Disagreement", "Acceptance"):
        assert expected in text
    assert "Notes" not in text  # what a note would say is under its table


# ----------------------------------------------------------------------------- the PDF
def test_the_pdf_has_the_sections_in_order_a_page_of_tables_and_a_page_of_charts(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = export_statistical_report(tmp_path / "attribute.pdf", [only(reference_rows(), ATTRIBUTE)], context=CONTEXT)
    reader = pypdf.PdfReader(path)
    assert len(reader.pages) == 2 and float(reader.pages[0].mediabox[2]) < float(reader.pages[1].mediabox[2])  # tables upright, charts across
    tables, charts = (flat(page.extract_text()) for page in reader.pages)
    order = [tables.index(heading) for heading in (
        "Attribute Agreement Analysis for Programming", "FIXTURE-1163", "Within Appraisers: Assessment Agreement", "Fleiss' Kappa Statistics",
        "Each Appraiser vs Standard: Assessment Agreement", "Fleiss' Kappa Statistics vs Standard", "Assessment Disagreement")]
    assert order == sorted(order)
    for printed in ("1 30 30 100.00 (90.50, 100.00)", "Fail 1.00 0.105409 9.48683 <0.0001", "#Pass/Fail Percent #Fail/Pass Percent #Mixed Percent",
                    "1 0 0.00 0 0.00 0 0.00"):
        assert printed in tables
    assert "counting rule" not in tables and "not verified" not in tables
    assert "Assessment Agreement for Programming" in charts and "Within Appraisers" in charts and "Appraiser vs Standard" in charts
    assert "FIXTURE-1163" in charts and "95% CI" in charts and "Percent" in charts and "Appraiser" in charts  # the study named above the panels
    assert not re.search(r"Jabil|Minitab|Confidential", tables + charts)  # no cover, no branding, no source named in the report


def test_the_pdf_follows_the_decimals_and_leaves_the_charts_out_when_asked(tmp_path):
    result = only(reference_rows(mistakes={(4, 2)}), ATTRIBUTE)
    text = flat(pdf_text(export_statistical_report(tmp_path / "four.pdf", [result], decimals=4, context=NO_CHARTS)))
    assert "96.6667" in text and "(82.7831, 99.9156)" in text and "Assessment Agreement for Programming" not in text
    pypdf = pytest.importorskip("pypdf")
    assert len(pypdf.PdfReader(tmp_path / "four.pdf").pages) == 1


def test_the_acceptance_is_in_the_pdf_only_when_it_was_applied_and_apart_from_the_statistics(tmp_path):
    judged = flat(pdf_text(export_statistical_report(tmp_path / "judged.pdf", [only(reference_rows(mistakes={(4, 2)}), JUDGED)], context=NO_CHARTS)))
    assert "Acceptance (a criterion you chose, not a statistical result)" in judged and "Within Appraisers 90 % PASS" in judged
    assert judged.index("Assessment Disagreement") < judged.index("Acceptance (a criterion")
    off = flat(pdf_text(export_statistical_report(tmp_path / "off.pdf", [only(reference_rows(), ATTRIBUTE)], context=NO_CHARTS)))
    assert "Acceptance" not in off and "PASS" not in off and "FAIL" not in off


def test_a_pdf_with_several_appraisers_and_a_standard_that_cannot_be_used_says_what_is_n_a(tmp_path):
    several = flat(pdf_text(export_statistical_report(
        tmp_path / "several.pdf", [only(appraisers_study(("Ann", "Ben")), ATTRIBUTE)], context=NO_CHARTS)))
    assert "Between Appraisers: Assessment Agreement" in several and "All Appraisers vs Standard: Assessment Agreement" in several
    assert "Ann 30 30 100.00" in several and "Ben 30 30 100.00" in several
    unusable = [dataclasses.replace(r, standard="") if r.sample_id == "S05" else r for r in reference_rows()]
    text = flat(pdf_text(export_statistical_report(tmp_path / "unusable.pdf", [only(unusable, ATTRIBUTE)], context=CONTEXT)))
    assert "1 N/A N/A N/A N/A" in text and "N/A: The Standard is missing for 1 of 30 samples." in text
    assert text.count("N/A: The Standard is missing for 1 of 30 samples.") >= 2  # under its table, and in the middle of its panel


def test_several_items_are_one_pdf_each_with_its_own_pages_and_an_item_that_failed_says_so(tmp_path):
    other = [dataclasses.replace(r, test_item="Second") for r in reference_rows()[:-1]]  # cannot be analysed: a rating is missing
    results = [only(reference_rows(), ATTRIBUTE), *analyze(other, ATTRIBUTE)]
    pypdf = pytest.importorskip("pypdf")
    path = export_statistical_report(tmp_path / "two.pdf", results, context=dataclasses.replace(CONTEXT, included=2, total=2))
    pages = [flat(page.extract_text()) for page in pypdf.PdfReader(path).pages]
    assert len(pages) == 3 and "Attribute Agreement Analysis for Second" in pages[2]
    assert "Analysis not available" in pages[2] and "Every appraiser must rate every sample the same number of times" in pages[2]


# ----------------------------------------------------------------------------- the workbook
def cells_of(sheet, title):
    """The rows of one table of a sheet, as lists of cell values, found by its title."""
    start = next(row for row in range(1, sheet.max_row + 1) if sheet.cell(row, 1).value == title)
    rows, row = [], start + 2
    while sheet.cell(row, 1).value not in (None, ""):
        rows.append([sheet.cell(row, col).value for col in range(1, 9)])
        row += 1
    return start, rows


def test_the_workbook_keeps_every_figure_in_full_and_only_formats_its_display(tmp_path):
    result = only(reference_rows(mistakes={(4, 2)}), ATTRIBUTE)
    path = export_statistical_report(tmp_path / "attribute.xlsx", [result], decimals=2, context=NO_CHARTS)
    sheet = load_workbook(path)["Programming"]
    assert sheet["A1"].value == "Attribute Agreement Analysis for Programming"
    start, rows = cells_of(sheet, "Within Appraisers: Assessment Agreement")
    assert [sheet.cell(start + 1, col).value for col in range(1, 7)] == ["Appraiser", "# Inspected", "# Matched", "Percent", "95% CI lower", "95% CI upper"]
    label, inspected, matched, percent, lower, upper = rows[0][:6]
    low, high = agreement_interval(29, 30)
    assert (label, inspected, matched) == ("1", 30, 29)
    assert (percent, lower, upper) == (pytest.approx(100 * 29 / 30, rel=1e-15), pytest.approx(100 * low, rel=1e-12), pytest.approx(100 * high, rel=1e-12))
    assert sheet.cell(start + 2, 4).number_format == "0.00" and sheet.cell(start + 2, 5).number_format == "0.00"  # displayed to two decimals
    start, rows = cells_of(sheet, "Fleiss' Kappa Statistics")
    se, z, p = rows[0][3:6]
    assert se == pytest.approx((2 / (30 * 3 * 2)) ** 0.5, rel=1e-13) and z == pytest.approx(rows[0][2] / se, rel=1e-13) and 0 <= p < 1
    assert [sheet.cell(start + 2, col).number_format for col in (3, 4, 5, 6)] == ["0.00", "0.000000", "0.00000", '[<0.00005]"<0.0001";0.0000']


def test_the_workbook_holds_the_disagreement_percents_in_full_with_n_a_where_there_is_no_base(tmp_path):
    result = only(pass_only_rows({3: "FFF", 7: "PFP"}), ATTRIBUTE)  # no sample has the Standard Fail
    sheet = load_workbook(export_statistical_report(tmp_path / "pass_only.xlsx", [result], decimals=2, context=NO_CHARTS))["Programming"]
    start, rows = cells_of(sheet, "Assessment Disagreement")
    assert [sheet.cell(start + 1, col).value for col in range(1, 8)] == ["Appraiser", "#Pass/Fail", "Percent", "#Fail/Pass", "Percent", "#Mixed", "Percent"]
    label, false_pass, false_pass_percent, false_fail, false_fail_percent, mixed, mixed_percent = rows[0][:7]
    assert (label, false_pass, false_pass_percent, false_fail, mixed) == ("1", 0, "N/A", 1, 1)  # counts are numbers, a missing percent is text
    assert false_fail_percent == pytest.approx(100 / 30, rel=1e-15) and mixed_percent == pytest.approx(100 / 30, rel=1e-15)  # in full, not 3.33
    assert sheet.cell(start + 2, 5).number_format == "0.00"  # only the display is rounded
    assert sheet.cell(start + 3, 1).value == "N/A: no sample has that value as its Standard."


def test_the_workbook_decimals_follow_the_setting_without_touching_the_values(tmp_path):
    result = only(reference_rows(mistakes={(4, 2)}), ATTRIBUTE)
    two = load_workbook(export_statistical_report(tmp_path / "two.xlsx", [result], decimals=2, context=NO_CHARTS))["Programming"]
    four = load_workbook(export_statistical_report(tmp_path / "four.xlsx", [result], decimals=4, context=NO_CHARTS))["Programming"]
    start, rows_two = cells_of(two, "Within Appraisers: Assessment Agreement")
    _, rows_four = cells_of(four, "Within Appraisers: Assessment Agreement")
    assert rows_two == rows_four  # the same values
    assert two.cell(start + 2, 4).number_format == "0.00" and four.cell(start + 2, 4).number_format == "0.0000"


def test_the_workbook_has_two_native_charts_with_their_data_and_no_gage_rr_chart(tmp_path):
    path = export_statistical_report(tmp_path / "charts.xlsx", [only(appraisers_study(("Ann", "Ben"), {("Ben", n, 1) for n in range(1, 6)}), ATTRIBUTE)], context=CONTEXT)
    workbook = load_workbook(path)
    assert workbook.sheetnames == ["Programming", "Plot data 1", "Observations"] and workbook["Plot data 1"].sheet_state == "hidden"
    data = workbook["Plot data 1"]
    assert [data.cell(1, col).value for col in range(1, 5)] == ["Appraiser", "Percent", "95% CI lower", "95% CI upper"]
    assert [data.cell(row, 1).value for row in (2, 3)] == ["Ann", "Ben"] and data.cell(3, 2).value == pytest.approx(100 * 25 / 30, rel=1e-15)
    assert data.cell(3, 3).value == pytest.approx(100 * agreement_interval(25, 30)[0], rel=1e-12)
    with zipfile.ZipFile(path) as archive:
        charts = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/charts/chart\d+\.xml", name))
        parts = [archive.read(name).decode() for name in charts]
    assert len(parts) == 2
    for xml, title in zip(parts, ("Within Appraisers", "Appraiser vs Standard"), strict=True):
        assert title in xml and "<hiLowLines" in xml and xml.count('<symbol val="x"') == 2 and xml.count('<symbol val="circle"') == 1
        assert "R Chart" not in xml and "Xbar" not in xml and "<c:barChart" not in xml
    assert '<min val="60"' in parts[0] and '<max val="100"' in parts[0]  # the percent scale ends at 100


def test_the_workbook_without_charts_has_no_plot_data_and_the_observations_are_the_ratings(tmp_path):
    result = only(reference_rows(), ATTRIBUTE)
    workbook = load_workbook(export_statistical_report(tmp_path / "plain.xlsx", [result], context=dataclasses.replace(CONTEXT, sections=("observations",))))
    assert workbook.sheetnames == ["Programming", "Observations"]
    observations = workbook["Observations"]
    assert [observations.cell(1, col).value for col in range(1, 8)] == ["Test Item", "Sample ID", "Appraiser", "Trial", "Rating", "Standard", "Source"]
    assert observations.max_row == 91 and [observations.cell(2, col).value for col in range(1, 7)] == ["Programming", "S01", "1", "1", "Pass", "Pass"]
    assert "LSL" not in [observations.cell(1, col).value for col in range(1, 10)]


def test_acceptance_is_in_the_workbook_only_when_applied_and_after_the_statistics(tmp_path):
    judged = load_workbook(export_statistical_report(tmp_path / "judged.xlsx", [only(reference_rows(mistakes={(4, 2)}), JUDGED)], context=NO_CHARTS))["Programming"]
    start, rows = cells_of(judged, "Acceptance (a criterion you chose, not a statistical result)")
    assert [row[:3] for row in rows[:3]] == [["Within Appraisers", "90 %", "PASS"], ["Appraiser vs Standard", "90 %", "PASS"], ["Overall", None, "PASS"]]
    assert rows[3][0].startswith("PASS: at or above the minimum")  # one line under the table says what the results mean
    assert start > cells_of(judged, "Assessment Disagreement")[0]
    off = load_workbook(export_statistical_report(tmp_path / "off.xlsx", [only(reference_rows(), ATTRIBUTE)], context=NO_CHARTS))["Programming"]
    assert not any("Acceptance" in str(off.cell(row, 1).value) or off.cell(row, 3).value in ("PASS", "FAIL") for row in range(1, off.max_row + 1))


def test_a_workbook_of_several_items_has_a_summary_with_na_where_a_figure_does_not_exist(tmp_path):
    second = [dataclasses.replace(r, test_item="Second", standard="") for r in reference_rows(mistakes={(4, 2)})]
    results = [only(reference_rows(), ATTRIBUTE), *analyze(second, ATTRIBUTE)]
    workbook = load_workbook(export_statistical_report(tmp_path / "two.xlsx", results, context=dataclasses.replace(CONTEXT, included=2, total=2, sections=())))
    assert workbook.sheetnames == ["Summary", "Programming", "Second"]
    summary = workbook["Summary"]
    assert summary["A1"].value == "Attribute Agreement Analysis"
    rows = [[summary.cell(row, col).value for col in range(1, 6)] for row in range(1, summary.max_row + 1)]
    header = next(i for i, row in enumerate(rows) if row[0] == "Test Item")
    assert rows[header] == ["Test Item", "Samples", "Within %", "vs Standard %", "Kappa"]
    assert rows[header + 1][:4] == ["Programming", 30, 100, 100] and rows[header + 2][:2] == ["Second", 30]
    assert rows[header + 2][2] == pytest.approx(100 * 29 / 30) and rows[header + 2][3] == "N/A"  # no Standard: not a number


def test_an_item_that_could_not_be_analysed_is_one_line_in_the_workbook(tmp_path):
    sheet = load_workbook(export_statistical_report(tmp_path / "failed.xlsx", [only(reference_rows()[:-1], ATTRIBUTE)], context=NO_CHARTS))["Programming"]
    assert any(str(sheet.cell(row, 1).value).startswith("Analysis not available") for row in range(1, 12))
    assert not any(sheet.cell(row, 1).value == "Within Appraisers: Assessment Agreement" for row in range(1, 20))


def test_a_report_never_mixes_attribute_agreement_with_another_method(tmp_path):
    from .test_stat_reports import grr

    with pytest.raises(ValueError, match="only one analysis method"):
        export_statistical_report(tmp_path / "mixed.pdf", [only(reference_rows(), ATTRIBUTE), grr()])
    assert not list(tmp_path.glob("*.pdf")) and not list(tmp_path.glob(".datamapperx-stat-*"))  # nothing is left behind
