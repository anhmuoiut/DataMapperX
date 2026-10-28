from __future__ import annotations

import re
import shutil
import zipfile

import pytest

from datamapperx.parsing import extract_sn_from_text, parse_excel_file, parse_text_file

from .conftest import ict_block, write_ft_workbook, write_ict_log


# ----------------------------------------------------------------------------- text
def test_text_extracts_value_unit_and_limits(tmp_path, ict_profile):
    log = write_ict_log(
        tmp_path / "VSE0001_run1.log",
        "VSE0001",
        [ict_block("R101", "+1.00500E+03", "+1.10000E+03", "+9.00000E+02"), ict_block("C7", "+2.2E-07", kind="CAP")],
    )
    parsed = parse_text_file(log, ict_profile)

    assert parsed.sn == "VSE0001"
    r101 = parsed.entries["R101"]
    assert (r101.measured, r101.min_value, r101.max_value, r101.unit) == (
        "+1.00500E+03", "+9.00000E+02", "+1.10000E+03", "RES",
    )
    c7 = parsed.entries["C7"]
    assert (c7.measured, c7.min_value, c7.max_value, c7.unit) == ("+2.2E-07", "", "", "CAP")


def test_text_blank_lines_between_block_and_measurement(tmp_path, ict_profile):
    log = write_ict_log(tmp_path / "VSE0002.log", "VSE0002", [ict_block("R5", "+5.0E+00", blank_lines=3)])
    assert parse_text_file(log, ict_profile).entries["R5"].measured == "+5.0E+00"


def test_text_block_directly_after_block_is_not_lost(tmp_path, ict_profile):
    """Regression: v1.1.0 skipped a BLOCK line that immediately followed a BLOCK without a measurement."""
    blocks = ["{@BLOCK|ORPHAN|00|1\n", ict_block("R9", "+9.0E+00")]
    log = write_ict_log(tmp_path / "VSE0003.log", "VSE0003", blocks)
    parsed = parse_text_file(log, ict_profile)
    assert list(parsed.entries) == ["R9"]
    assert parsed.entries["R9"].measured == "+9.0E+00"


def test_text_duplicate_component_keeps_first_and_records_all(tmp_path, ict_profile):
    log = write_ict_log(
        tmp_path / "VSE0004.log", "VSE0004",
        [ict_block("R1", "+1.0E+00"), ict_block("R1", "+2.0E+00"), ict_block("R1", "+3.0E+00")],
    )
    parsed = parse_text_file(log, ict_profile)
    assert parsed.entries["R1"].measured == "+1.0E+00"
    assert [m.measured for m in parsed.duplicates["R1"]] == ["+1.0E+00", "+2.0E+00", "+3.0E+00"]
    assert parsed.row_label == "Lines"


def test_text_sn_falls_back_to_file_content(tmp_path, ict_profile):
    log = write_ict_log(tmp_path / "untitled.log", "VSEABC123", [ict_block("R1", "+1.0E+00")])
    assert parse_text_file(log, ict_profile).sn == "VSEABC123"


def test_text_utf16_bom_is_decoded(tmp_path, ict_profile):
    path = tmp_path / "VSE0005.log"
    path.write_text("{@BATCH|VSE0005\n" + ict_block("R2", "+2.0E+00"), encoding="utf-16")
    parsed = parse_text_file(path, ict_profile)
    assert parsed.entries["R2"].measured == "+2.0E+00"


def test_text_without_sn_returns_empty_sn(tmp_path, ict_profile):
    path = tmp_path / "nothing.log"
    path.write_text(ict_block("R1", "+1.0E+00"), encoding="utf-8")
    assert parse_text_file(path, ict_profile).sn == ""


# ----------------------------------------------------------------------------- sn helper
@pytest.mark.parametrize(
    ("text", "regex", "expected"),
    [
        ("log_vse123abc_final.txt", "", "VSE123ABC"),
        ("board SN=XY99 ok", r"SN=(?P<sn>[A-Z0-9]+)", "XY99"),
        ("nothing here", "", ""),
        ("", "", ""),
    ],
)
def test_extract_sn(text, regex, expected):
    assert extract_sn_from_text(text, regex) == expected


# ----------------------------------------------------------------------------- excel
RESULT_ROWS = [("R1", 1.5, 1.0, 2.0, "V"), ("R2", 3.25, 3.0, 4.0, "mA")]


def test_excel_reads_values_and_sn_from_cell(tmp_path, ft_profile):
    ft_profile["sn_regex"] = "B2"
    path = write_ft_workbook(tmp_path / "run.xlsx", "VSE777", RESULT_ROWS)
    parsed = parse_excel_file(path, ft_profile)

    assert parsed.sn == "VSE777"
    r2 = parsed.entries["R2"]
    assert (r2.measured, r2.min_value, r2.max_value, r2.unit, r2.source_row) == ("3.25", "3", "4", "mA", "3")
    assert parsed.row_label == "Rows"


def test_excel_sn_from_filename_when_regex_is_pattern(tmp_path, ft_profile):
    path = write_ft_workbook(tmp_path / "VSE555_final.xlsx", None, RESULT_ROWS)
    assert parse_excel_file(path, ft_profile).sn == "VSE555"


def test_excel_sn_found_by_scanning_cells(tmp_path, ft_profile):
    path = write_ft_workbook(tmp_path / "plain.xlsx", "serial VSE888 ok", RESULT_ROWS)
    assert parse_excel_file(path, ft_profile).sn == "VSE888"


def test_excel_duplicates_are_collected(tmp_path, ft_profile):
    rows = [("R1", 1, 0, 2, "V"), ("R1", 9, 0, 2, "V")]
    path = write_ft_workbook(tmp_path / "VSE1.xlsx", "VSE1", rows)
    parsed = parse_excel_file(path, ft_profile)
    assert parsed.entries["R1"].measured == "1"
    assert [m.measured for m in parsed.duplicates["R1"]] == ["1", "9"]
    assert [m.source_row for m in parsed.duplicates["R1"]] == ["2", "3"]


def test_excel_wrong_dimension_tag_still_reads_every_row(tmp_path, ft_profile):
    """Some tools write <dimension ref="A1"/>; read-only mode must not truncate the sheet."""
    rows = [(f"R{i}", i, 0, 100, "V") for i in range(1, 31)]
    good = write_ft_workbook(tmp_path / "VSE9_good.xlsx", "VSE9", rows)
    bad = tmp_path / "VSE9_bad.xlsx"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/"):
                data = re.sub(rb'<dimension ref="[^"]*"\s*/>', b'<dimension ref="A1"/>', data)
            dst.writestr(item, data)

    assert len(parse_excel_file(bad, ft_profile).entries) == 30


def test_excel_not_a_workbook_raises_value_error(tmp_path, ft_profile):
    fake = tmp_path / "VSE1.xlsx"
    fake.write_text("this is not a zip file")
    with pytest.raises(ValueError, match="not a valid Excel workbook"):
        parse_excel_file(fake, ft_profile)


def test_excel_file_handle_is_released(tmp_path, ft_profile):
    """The workbook must be closed so the file can be deleted right after parsing (Windows locks open files)."""
    path = write_ft_workbook(tmp_path / "VSE2.xlsx", "VSE2", RESULT_ROWS)
    parse_excel_file(path, ft_profile)
    copy = tmp_path / "moved.xlsx"
    shutil.move(path, copy)
    assert copy.exists()
