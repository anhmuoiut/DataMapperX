"""Checking an Excel file for Variable Gage R&R and Cpk before it is analysed, and Variable_Cpk_Template.xlsx (no window).

There is one layout: the RawData.xlsx that Data Mapping exports. These tests follow the person's side: a file the program wrote is ready
as it is, the template is that layout, what is found has its sheet, row and column, and a study that would FAIL is still a file that may
be analysed (that is for the analysis to say).
"""
from __future__ import annotations

import copy

import pytest
from openpyxl import load_workbook

from datamapperx.excel_intake import (
    MAX_LISTED,
    NO_TRIAL,
    VARIABLE_VERSION,
    validate_variable,
    write_variable_template,
)
from datamapperx.statistics import AnalysisConfig, analyze, import_rawdata_xlsx

from .excel_support import store_digits, write_ratings, write_rawdata


def errors(report) -> list[str]:
    return [str(finding) for finding in report.findings if finding.severity == "error"]


def warnings(report) -> list[str]:
    return [finding.message for finding in report.findings if finding.severity == "warning"]


def notes(report) -> list[str]:
    return [finding.message for finding in report.findings if finding.severity == "info"]


@pytest.fixture
def exported(tmp_path):
    """A RawData.xlsx written by DataMapperX itself from synthetic logs: 3 samples of 2 files, the test items R1 and Long."""
    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder

    from .baseline_support import write_rawdata_logs

    logs = tmp_path / "logs"
    logs.mkdir()
    write_rawdata_logs(logs)
    result = scan_folder(logs, copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"]))
    path = tmp_path / "RawData.xlsx"
    generate_excel(result.grouped, ["R1", "Long"], path, expected_repeated=2)
    return path


# ----------------------------------------------------------------------------- the file the program writes
def test_a_rawdata_workbook_exported_by_the_program_is_ready_as_it_is_for_either_method(exported):
    for method in ("grr", "capability"):
        report = validate_variable(exported, method)
        assert report.ready and report.sheet == "Raw Data" and report.imported.items == ("R1", "Long"), errors(report)
        assert report.imported.dataset == import_rawdata_xlsx(exported).dataset  # the importer the program always had read it, unchanged
        assert report.count("error") == 0


def test_a_study_that_would_fail_its_acceptance_is_still_a_file_that_may_be_analysed(tmp_path):
    noisy = write_rawdata(tmp_path / "noisy.xlsx", serials=4, readings=3, items=("R1",), limits=((950, 1050),),
                          value=lambda n, r, i: 1000 + ((n * 3 + r) * 37 % 41) - 20)
    report = validate_variable(noisy, "grr")
    assert report.ready and report.count("error") == 0  # a data problem blocks; a poor measurement system does not
    result = analyze(report.imported.dataset.observations, AnalysisConfig(method="grr", assign_trials=True))[0]
    assert result.status == "FAIL"  # the analysis says so, later


def test_the_values_of_the_file_reach_the_analysis_as_they_are(tmp_path):
    path = write_rawdata(tmp_path / "digits.xlsx", items=("R1",), limits=((0, 9),), value=lambda n, r, i: 0.3 if (n, r) == (0, 0) else 5 + n + r)
    store_digits(path, "0.3", "0.30000000000000004")  # what Excel stores for 0.1 + 0.2
    observations = validate_variable(path, "capability").imported.dataset.observations
    assert observations[0].value == 0.30000000000000004 and observations[0].sample_id == "VSE001"  # not 0.3: no digit is lost
    assert (observations[0].lsl, observations[0].usl, observations[0].unit, observations[0].source) == (0, 9, "Ohm", "Raw Data!R2")


# ----------------------------------------------------------------------------- the template
def test_the_template_is_the_rawdata_layout_with_instructions_and_an_example_that_is_not_data(tmp_path):
    book = load_workbook(write_variable_template(tmp_path / "Variable_Cpk_Template.xlsx"))
    assert book.sheetnames == ["Raw Data", "Instructions", "Examples"]
    assert [c.value for c in book["Raw Data"][1]] == ["STT", "SN", "Test item 1", "Test item 2", "Test item 3", None, "NAME", "MIN", "MAX", "UNIT"]
    assert [book["Raw Data"].cell(row, 7).value for row in (2, 3, 4)] == ["Test item 1", "Test item 2", "Test item 3"]  # a place for each limit
    notes = [[cell.value for cell in row] for row in book["Instructions"].iter_rows() if row[0].value]
    assert notes[1][:2] == ["Template version", VARIABLE_VERSION]
    needs = {row[0]: row[1] for row in notes if row[1] in ("Required", "Optional")}
    assert needs == {"STT": "Required", "SN": "Required", "Test item columns": "Required", "Empty column": "Required",
                     "NAME": "Optional", "MIN": "Optional", "MAX": "Optional", "UNIT": "Optional"}
    assert "EXAMPLE ONLY" in book["Examples"]["A1"].value and book["Examples"].max_row > 8


def test_the_empty_template_is_not_a_file_to_analyse_and_the_filled_one_is_read_like_an_export(tmp_path):
    path = write_variable_template(tmp_path / "Variable_Cpk_Template.xlsx")
    empty = validate_variable(path, "grr")
    assert empty.status == "invalid" and "no data rows" in errors(empty)[0]  # nothing filled in yet; the placeholders are not data
    book = load_workbook(path)
    sheet = book["Raw Data"]
    for line in range(6):  # 3 samples of 2 readings
        for column, value in enumerate((line + 1, f"S{line // 2 + 1}", 1000 + line, 2000 + line, 3000 + line), 1):
            sheet.cell(row=line + 2, column=column, value=value)
    for row, (low, high) in zip((2, 3), ((950, 1050), (1900, 2100)), strict=True):
        sheet.cell(row=row, column=8, value=low)
        sheet.cell(row=row, column=9, value=high)
    book.save(path)
    report = validate_variable(path, "grr")
    assert report.ready and report.imported.items == ("Test item 1", "Test item 2", "Test item 3") and report.imported.samples == 3
    first = [o for o in report.imported.dataset.observations if o.test_item == "Test item 1"][0]
    assert (first.lsl, first.usl) == (950, 1050)


# ----------------------------------------------------------------------------- what the person is told
def test_gage_rr_says_the_trials_are_numbered_in_row_order_as_a_note_and_cpk_has_no_trials(tmp_path):
    path = write_rawdata(tmp_path / "raw.xlsx")
    grr, cpk = validate_variable(path, "grr"), validate_variable(path, "capability")
    assert NO_TRIAL in notes(grr) and NO_TRIAL not in warnings(grr) and NO_TRIAL not in notes(cpk)  # a layout without Trial is not a problem


def test_a_test_item_with_an_empty_or_non_numeric_cell_is_a_warning_while_another_can_be_analysed(tmp_path):
    def value(n, r, i):
        return None if (n, r, i) == (1, 0, 1) else "abc" if (n, r, i) == (2, 1, 1) else 100 + 10 * n + r + 5 * i

    path = write_rawdata(tmp_path / "gaps.xlsx", serials=3, readings=2, items=("R1", "R2"), value=value)
    for method in ("grr", "capability"):
        report = validate_variable(path, method)
        assert report.ready and report.status == "warnings", errors(report)  # R1 can be analysed; the analysis will say R2 cannot
        said = [str(f) for f in report.findings if f.severity == "warning"]
        assert "Sheet: Raw Data | Row 4 | Column: R2 | Measurement is empty." in said
        assert "Sheet: Raw Data | Row 7 | Column: R2 | Measurement must be numeric." in said


def test_when_no_test_item_can_be_analysed_the_file_is_invalid_and_says_where(tmp_path):
    path = write_rawdata(tmp_path / "bad.xlsx", items=("R1",), limits=((0, 9),), value=lambda n, r, i: "abc" if (n, r) == (1, 1) else 5 + n + r)
    report = validate_variable(path, "capability")
    assert report.status == "invalid" and report.imported is None
    assert errors(report) == ["Sheet: Raw Data | Row 5 | Column: R1 | Measurement must be numeric."]


def test_a_column_of_mistakes_is_listed_for_its_first_rows_and_then_counted(tmp_path):
    path = write_rawdata(tmp_path / "many.xlsx", serials=MAX_LISTED + 4, readings=2, items=("R1",), limits=((0, 9),),
                         value=lambda n, r, i: None)
    got = errors(validate_variable(path, "capability"))
    assert len(got) == MAX_LISTED + 1 and got[0] == "Sheet: Raw Data | Row 2 | Column: R1 | Measurement is empty."
    assert got[-1].endswith("more errors of the same kind.")


def test_an_unbalanced_study_blocks_gage_rr_but_not_cpk(tmp_path):
    path = write_rawdata(tmp_path / "uneven.xlsx")
    book = load_workbook(path)
    book["Raw Data"].append([7, "VSE001", 111, 116])  # the first sample has three readings, the others two
    book.save(path)
    grr, cpk = validate_variable(path, "grr"), validate_variable(path, "capability")
    assert grr.status == "invalid" and any("Unbalanced study" in text for text in errors(grr))
    assert cpk.ready  # Cpk does not need the same number of readings of every sample


def test_missing_limits_are_said_by_the_importer_and_the_engine_and_do_not_block(tmp_path):
    path = write_rawdata(tmp_path / "nolimits.xlsx", limits=None)
    report = validate_variable(path, "capability")
    assert report.ready and any("NAME/MIN/MAX/UNIT table was not found" in text for text in warnings(report))
    assert any("LSL/USL" in text for text in warnings(report))  # the analysis's own words, for each test item


def test_a_template_of_another_version_is_a_warning(tmp_path):
    path = write_rawdata(tmp_path / "old.xlsx")
    book = load_workbook(path)
    book.create_sheet("Instructions").append(["Template version", "Variable-9"])
    book.save(path)
    report = validate_variable(path, "grr")
    assert report.ready and any("Variable-9" in text for text in warnings(report))


# ----------------------------------------------------------------------------- a file that is not one
def test_a_workbook_that_is_not_in_the_rawdata_layout_or_cannot_be_read_is_an_invalid_file(tmp_path):
    odd = write_ratings(tmp_path / "odd.xlsx", [("a", 1)], headers=("Name", "Value"), sheet="Raw Data")
    assert "not a DataMapperX RawData workbook" in errors(validate_variable(odd, "grr"))[0]
    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n")
    assert errors(validate_variable(csv, "grr")) == ["Only .xlsx workbooks are supported."]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    assert "cannot be read" in errors(validate_variable(broken, "capability"))[0]
    assert validate_variable(tmp_path / "missing.xlsx", "grr").status == "invalid"
