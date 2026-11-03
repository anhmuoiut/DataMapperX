"""Checking an Excel file before it is analysed, and the Attribute template (no window).

The checks use the analysis's own reading, mapping and rules; these tests only follow what the person is told (status, sheet, row and
column) and that the file's values reach the analysis as they are.
"""
from __future__ import annotations

from openpyxl import load_workbook

from datamapperx.excel_intake import (
    ATTRIBUTE_SHEET,
    ATTRIBUTE_VERSION,
    MAX_LISTED,
    STATUS_TEXT,
    Finding,
    mapping_from_record,
    validate_attribute,
    write_attribute_template,
)

from .excel_support import EXPORT_HEADERS, attribute_rows, write_ratings


def errors(report) -> list[str]:
    return [str(finding) for finding in report.findings if finding.severity == "error"]


def warnings(report) -> list[str]:
    return [finding.message for finding in report.findings if finding.severity == "warning"]


# ----------------------------------------------------------------------------- the template
def test_the_template_has_the_data_sheet_the_instructions_and_an_example_that_is_not_data(tmp_path):
    path = write_attribute_template(tmp_path / "Attribute_Template.xlsx")
    book = load_workbook(path)
    assert book.sheetnames == [ATTRIBUTE_SHEET, "Instructions", "Examples"]
    assert [cell.value for cell in book[ATTRIBUTE_SHEET][1]] == list(EXPORT_HEADERS) and book[ATTRIBUTE_SHEET].max_row == 1  # headers only
    notes = {row[0].value: [cell.value for cell in row[1:]] for row in book["Instructions"].iter_rows() if row[0].value}
    assert notes["Template version"][0] == ATTRIBUTE_VERSION
    assert [notes[name][0] for name in EXPORT_HEADERS] == ["Optional", "Required", "Optional", "Optional", "Required", "Optional"]
    assert "EXAMPLE ONLY" in book["Examples"]["A1"].value


def test_a_completed_template_is_ready_and_the_empty_one_and_the_examples_are_not_analysed(tmp_path):
    path = write_attribute_template(tmp_path / "Attribute_Template.xlsx")
    empty = validate_attribute(path)
    assert empty.status == "invalid" and not empty.ready and "no rows" in errors(empty)[0]  # nothing to analyse until it is filled in
    assert validate_attribute(path, "Examples").status == "invalid"  # the examples sheet cannot be analysed by choosing it
    book = load_workbook(path)
    for row in attribute_rows():
        book[ATTRIBUTE_SHEET].append([row[2], row[0], row[3], row[4], row[1], row[5]])  # the rows are (sample, rating, item, …)
    book.save(path)
    report = validate_attribute(path)
    assert report.status == "ready" and report.ready and report.imported.samples == 4 and report.imported.appraisers == 2


# ----------------------------------------------------------------------------- a file that may be analysed
def test_a_good_file_is_ready_and_its_values_reach_the_analysis_as_they_are(tmp_path):
    rows = [("007", "Pass", "Visual", "Ann", 1, "Pass"), ("007", "Pass", "Visual", "Ann", 2, "Pass"),
            ("008", "Fail", "Visual", "Ann", 1, "Fail"), ("008", "Fail", "Visual", "Ann", 2, "Fail")]
    report = validate_attribute(write_ratings(tmp_path / "ratings.xlsx", rows))
    assert STATUS_TEXT[report.status] == "Ready for Analysis" and report.ready and report.count("error") == 0
    seen = [(o.sample_id, o.value, o.test_item, o.operator, o.trial, o.standard) for o in report.imported.dataset.observations]
    assert seen == [("007", "Pass", "Visual", "Ann", "1", "Pass"), ("007", "Pass", "Visual", "Ann", "2", "Pass"),
                    ("008", "Fail", "Visual", "Ann", "1", "Fail"), ("008", "Fail", "Visual", "Ann", "2", "Fail")]  # 007 stays 007, Pass stays Pass
    assert report.summary.startswith("2 samples · 1 appraiser · 2 trials per sample · 2 categories")


def test_what_the_import_did_is_said_but_is_not_a_warning(tmp_path):
    rows = [(r[0], r[1]) for r in attribute_rows(appraisers=("Ann",), standard=False)]
    report = validate_attribute(write_ratings(tmp_path / "plain.xlsx", rows, headers=("Sample ID", "Rating")))
    assert report.status == "ready"
    notes = [finding.message for finding in report.findings if finding.severity == "info"]
    assert any("numbered 1, 2, 3" in note for note in notes) and any("No Standard" in note for note in notes)


def test_warnings_do_not_block_the_analysis(tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    rows[0] = ("S001", "Pass", *rows[0][2:])  # a spelling of PASS that differs only by letter case
    report = validate_attribute(write_ratings(tmp_path / "case.xlsx", rows))
    assert report.status == "warnings" and report.ready and STATUS_TEXT[report.status] == "Warnings Found"
    assert any("letter case" in text for text in warnings(report))
    odd = [("S001", "PASS", "I", "Ann", 1, "OK"), ("S001", "PASS", "I", "Ann", 2, "OK"), ("S002", "MAYBE", "I", "Ann", 1, "FAIL"),
           ("S002", "FAIL", "I", "Ann", 2, "FAIL")]
    report = validate_attribute(write_ratings(tmp_path / "odd.xlsx", odd))
    assert report.ready and any("4 categories" in text for text in warnings(report))  # PASS, FAIL, MAYBE, and the Standard's OK
    assert any("The Standard has labels no rating uses: OK" in text for text in warnings(report))


# ----------------------------------------------------------------------------- a file that may not
def test_an_empty_required_cell_is_named_by_sheet_row_and_column(tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    rows[2] = (rows[2][0], None, *rows[2][2:])  # the Rating of the third row (row 4 of the sheet)
    rows[5] = (None, *rows[5][1:])  # the Sample ID of the sixth row (row 7)
    report = validate_attribute(write_ratings(tmp_path / "blanks.xlsx", rows))
    assert report.status == "invalid" and STATUS_TEXT[report.status] == "Invalid File" and not report.ready and report.imported is None
    assert errors(report) == ["Sheet: Attribute_Data | Row 4 | Column: Rating | Rating is empty.",
                              "Sheet: Attribute_Data | Row 7 | Column: Sample ID | Sample ID is empty."]


def test_a_column_of_mistakes_is_listed_for_its_first_rows_and_then_counted(tmp_path):
    rows = [(f"S{n:03d}", None, "I", "Ann", 1, None) for n in range(1, MAX_LISTED + 6)]
    report = validate_attribute(write_ratings(tmp_path / "many.xlsx", rows))
    assert len(errors(report)) == MAX_LISTED + 1 and "5 more rows" in errors(report)[-1]


def test_a_trial_column_must_be_filled_for_every_row_or_for_none(tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    half = [(*row[:4], None if index == 3 else row[4], row[5]) for index, row in enumerate(rows)]
    assert errors(validate_attribute(write_ratings(tmp_path / "half.xlsx", half))) == \
        ["Sheet: Attribute_Data | Row 5 | Column: Trial | Trial is empty: give every rating its trial, or none."]
    none = [(*row[:4], None, row[5]) for row in rows]
    assert validate_attribute(write_ratings(tmp_path / "none.xlsx", none)).status != "invalid"  # an empty Trial column is no Trial column


def test_the_analysis_own_rules_block_what_they_block_there(tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    twice = [*rows, rows[0]]  # the same sample, appraiser and trial twice
    assert any("Duplicate trial identity" in text for text in errors(validate_attribute(write_ratings(tmp_path / "twice.xlsx", twice))))
    uneven = rows[:-1]  # one rating missing from the last sample
    assert any("same number of times" in text for text in errors(validate_attribute(write_ratings(tmp_path / "uneven.xlsx", uneven))))


def test_a_workbook_that_cannot_be_read_is_an_invalid_file_not_a_crash(tmp_path):
    csv = tmp_path / "ratings.csv"
    csv.write_text("Sample ID,Rating\nS1,PASS\n")
    assert errors(validate_attribute(csv)) == ["Only .xlsx workbooks are supported."]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"this is not a workbook")
    report = validate_attribute(broken)
    assert report.status == "invalid" and "cannot be read" in errors(report)[0]
    assert validate_attribute(tmp_path / "missing.xlsx").status == "invalid"


# ----------------------------------------------------------------------------- columns with other names
def test_columns_with_other_names_are_matched_and_the_ones_not_found_are_asked_for(tmp_path):
    headers = ("Serial", "Result", "Inspector", "Repeat", "Reference")
    rows = [(r[0], r[1], r[3], r[4], r[5]) for r in attribute_rows()]
    report = validate_attribute(write_ratings(tmp_path / "named.xlsx", rows, headers=headers, sheet="Inspection"))
    assert report.ready and report.imported.record["columns"] == {"sample": "Serial", "rating": "Result", "appraiser": "Inspector",
                                                                   "trial": "Repeat", "standard": "Reference"}
    lost = validate_attribute(write_ratings(tmp_path / "lost.xlsx", rows, headers=("Serial", "Judgement", "Inspector", "Repeat", "Reference")))
    assert errors(lost) == ["Sheet: Attribute_Data | Choose the Rating column. Use Review columns…"]


def test_the_mapping_a_person_chose_is_checked_as_chosen(tmp_path):
    headers = ("Serial", "Judgement", "Inspector", "Repeat", "Reference")
    rows = [(r[0], r[1], r[3], r[4], r[5]) for r in attribute_rows()]
    path = write_ratings(tmp_path / "chosen.xlsx", rows, headers=headers)
    first = validate_attribute(path, mapping=mapping_from_record(
        {"columns": {"sample": "Serial", "rating": "Judgement"}, "assign_trials": True, "categories": []}))
    assert first.ready and first.imported.record["columns"] == {"sample": "Serial", "rating": "Judgement"}
    assert first.imported.appraisers == 1  # the Inspector column was not chosen: the study has no appraiser names


# ----------------------------------------------------------------------------- the template version
def test_a_template_of_another_version_is_a_warning(tmp_path):
    path = write_ratings(tmp_path / "old.xlsx", attribute_rows(appraisers=("Ann",)), others=("Instructions",))
    book = load_workbook(path)
    book["Instructions"].append(["Template version", "Attribute-9"])
    book.save(path)
    report = validate_attribute(path)
    assert report.ready and any("Attribute-9" in text for text in warnings(report))


def test_a_finding_reads_as_sheet_row_column_message():
    assert str(Finding("error", "Measurement must be numeric.", "Cpk_Data", 12)) == "Sheet: Cpk_Data | Row 12 | Measurement must be numeric."
    assert str(Finding("warning", "Check this.")) == "Check this."


def test_the_report_lists_what_blocks_before_what_only_warns(tmp_path):
    rows = attribute_rows(appraisers=("Ann",))
    rows[1] = (rows[1][0], "Pass", *rows[1][2:])  # a warning ...
    rows[0] = (rows[0][0], None, *rows[0][2:])  # ... and an error
    report = validate_attribute(write_ratings(tmp_path / "order.xlsx", rows))
    assert report.status == "invalid" and [finding.severity for finding in report.findings][0] == "error"


# ----------------------------------------------------------------------------- the Excel report is a file that is read back
def test_the_observations_sheet_of_the_excel_report_is_read_back_as_it_is(tmp_path):
    from datamapperx.stat_reports import ReportContext, export_statistical_report
    from datamapperx.statistics import analyze

    from .test_attribute import ATTRIBUTE, only, reference_rows

    rows = reference_rows(mistakes={(4, 2)})
    result = only(rows)
    context = ReportContext(info=(("Gage name", "G1"),), included=1, total=1, sections=("observations",))
    path = export_statistical_report(tmp_path / "report.xlsx", [result], context=context)
    assert [cell.value for cell in load_workbook(path)["Observations"][1]][:6] == list(EXPORT_HEADERS)  # the template has these columns
    report = validate_attribute(path)  # no sheet is named: the Observations sheet is the one to read
    assert report.ready and report.sheet == "Observations" and "Observations" in report.sheets, errors(report)
    back = report.imported.dataset.observations
    assert [(o.test_item, o.sample_id, o.value, o.trial, o.standard) for o in back] ==         [(o.test_item, o.sample_id, o.value, o.trial, o.standard) for o in rows]
    assert {o.operator for o in back} == {"1"}  # the report names the one unnamed appraiser 1
    assert analyze(back, ATTRIBUTE)[0].metrics == result.metrics  # the same ratings give the same figures

