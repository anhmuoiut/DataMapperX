"""What the Data Mapping screens and the Validation workspace decide, tested without opening a window."""
from __future__ import annotations

import dataclasses

import pytest

from datamapperx.config import PREVIEW_COLUMNS_PER_PAGE
from datamapperx.review import ReviewSummary
from datamapperx.scanner import scan_folder
from datamapperx.statistics import Dataset, Observation, snapshot_from_records
from datamapperx.workflow import (
    available_view,
    check_chips,
    limit_overview,
    limit_panel,
    limit_texts,
    move_items,
    preview_table,
    row_list,
    selected_info,
)
from datamapperx.workspace_data import MappingSource, build_mapping_dataset, int_field, reorder_dataset

from .conftest import ict_block, write_ict_log


@pytest.fixture
def scanned(tmp_path, ict_profile):
    """Two samples, two files each. VSE002's second file has no R2; R1 has limits 0..10, R2 has none."""
    write_ict_log(tmp_path / "a1.log", "VSE001", [ict_block("R1", "+5.0E+00", "+1.0E+01", "+0.0E+00"), ict_block("R2", "+1.0E+00")])
    write_ict_log(tmp_path / "a2.log", "VSE001", [ict_block("R1", "+11.0E+00", "+1.0E+01", "+0.0E+00"), ict_block("R2", "+2.0E+00")])
    write_ict_log(tmp_path / "b1.log", "VSE002", [ict_block("R1", "-1.0E+00", "+1.0E+01", "+0.0E+00"), ict_block("R2", "+3.0E+00")])
    write_ict_log(tmp_path / "b2.log", "VSE002", [ict_block("R1", "+6.0E+00", "+1.0E+01", "+0.0E+00")])
    return scan_folder(tmp_path, ict_profile)


# ----------------------------------------------------------------------------- component lists
def test_the_available_list_hides_what_is_selected_and_explains_an_empty_list():
    everything = ["Alpha", "Beta", "alpine", "Gamma"]
    view = available_view(everything, ["Beta"], "")
    assert view.items == ["Alpha", "alpine", "Gamma"] and view.info == "3 available" and not view.filtering

    view = available_view(everything, ["Beta"], "  ALP ")  # case-insensitive, trimmed
    assert view.items == ["Alpha", "alpine"] and view.info == "2 of 3 shown" and view.filtering

    assert available_view(everything, [], "zzz").empty_text == "No component matches the filter."
    assert available_view(everything, everything, "").empty_text == "Every component is selected."
    nothing = available_view([], [], "")
    assert nothing.empty_text.startswith("Scan a folder") and nothing.info == ""


def test_limit_texts_use_a_dash_when_there_is_no_limit():
    limits = {"R1": {"min": "0", "max": "10"}, "R2": {"min": "", "max": ""}}
    assert limit_texts(limits, "R1") == ("0", "10")
    assert limit_texts(limits, "R2") == limit_texts(limits, "unknown") == ("–", "–")


def test_selected_info_counts_the_columns():
    assert selected_info(0) == "No columns selected" and selected_info(3) == "3 selected"


@pytest.mark.parametrize("indices,direction,expected,moved", [
    ([1], -1, ["b", "a", "c", "d"], True),
    ([1, 2], 1, ["a", "d", "b", "c"], True),
    ([0], -1, ["a", "b", "c", "d"], False),      # already at the top
    ([3], 1, ["a", "b", "c", "d"], False),       # already at the bottom
    ([0, 1], 1, ["c", "a", "b", "d"], True),
    ([], 1, ["a", "b", "c", "d"], False),
])
def test_move_items(indices, direction, expected, moved):
    items = ["a", "b", "c", "d"]
    assert move_items(items, indices, direction) is moved
    assert items == expected


# ----------------------------------------------------------------------------- review table
def test_the_preview_is_the_table_that_will_be_exported(scanned):
    table = preview_table(scanned, ["R1", "R2"], page=0, repeats=2)
    assert table.headings == ("No.", "Serial number", "File", "R1", "R2")
    assert [row[:2] for row in table.rows] == [(1, "VSE001"), (2, "VSE001"), (3, "VSE002"), (4, "VSE002")]
    assert [row[3:] for row in table.rows][0] == ("+5.0E+00", "+1.0E+00")
    assert [row.sn for row in table.export_rows] == ["VSE001", "VSE001", "VSE002", "VSE002"]
    assert table.tags == ["", "", "", "missing"]  # the last file has no R2
    assert table.note == "4 rows." and table.count_text == "(4 rows)" and table.empty_text == ""


def test_a_sample_with_the_wrong_number_of_files_is_marked_invalid(scanned):
    assert preview_table(scanned, ["R1"], page=0, repeats=3).tags == ["invalid"] * 4
    assert preview_table(scanned, ["R1"], page=0, repeats=None).tags == [""] * 4


def test_with_nothing_selected_the_files_are_still_listed(scanned):
    table = preview_table(scanned, [], page=0, repeats=2)
    assert len(table.rows) == 4 and table.headings == ("No.", "Serial number", "File")
    assert table.note == "4 files found. Add components in the Select step to build your Excel columns."


def test_columns_are_paged_and_the_page_is_clamped(scanned):
    names = [f"C{i}" for i in range(PREVIEW_COLUMNS_PER_PAGE + 5)]
    first = preview_table(scanned, names, page=0, repeats=2)
    assert first.pages == 2 and first.first == 0 and len(first.page_components) == PREVIEW_COLUMNS_PER_PAGE
    assert first.note.endswith(f"The Excel file has all {len(names)} columns.")
    last = preview_table(scanned, names, page=99, repeats=2)
    assert last.page == 1 and last.first == PREVIEW_COLUMNS_PER_PAGE and last.page_components == tuple(names[PREVIEW_COLUMNS_PER_PAGE:])
    assert preview_table(scanned, names, page=-4, repeats=2).page == 0


def test_before_a_scan_the_preview_says_how_to_start():
    table = preview_table(None, ["R1"], page=0, repeats=2)
    assert table.rows == [] and table.count_text == "" and table.empty_text.startswith("Your data preview starts here.")


# ----------------------------------------------------------------------------- limits panel
def test_the_limits_panel_marks_values_outside_their_limits(scanned):
    from datamapperx.exporter import iter_export_rows, summarize_limits

    limits = summarize_limits(scanned.grouped, ["R1", "R2"])
    rows = {row.index: row for row in iter_export_rows(scanned.grouped, ["R1", "R2"])}
    panel, tags = limit_panel(rows[2], ["R1", "R2"], limits)  # R1 = 11 > max 10
    assert panel[0][:2] == ("R1", "+11.0E+00 ▲") and tags == ["out", ""]
    panel, tags = limit_panel(rows[3], ["R1", "R2"], limits)  # R1 = -1 < min 0
    assert panel[0][1] == "-1.0E+00 ▼" and tags[0] == "out"
    panel, tags = limit_panel(rows[4], ["R1", "R2"], limits)  # R2 missing
    assert panel[1][1] == "–" and tags[1] == "gap"
    assert limit_overview(["R1", "R2"], limits)[0][:4] == ("R1", "", "+0.0E+00", "+1.0E+01")


# ----------------------------------------------------------------------------- checks before exporting
def test_the_check_chips_say_what_to_know_before_saving(scanned):
    clean = ReviewSummary(rows=4, empty_cells=0, empty_columns=(), outside_rows=())
    assert check_chips(scanned, clean, expected=2, repeats=2, wrong=[]) == [
        ("ok", "✓  2 of 2 samples"), ("ok", "✓  2 files per sample"), ("ok", "✓  No empty cells")]

    messy = ReviewSummary(rows=4, empty_cells=1, empty_columns=("R2",), outside_rows=(2, 3))
    found = check_chips(scanned, messy, expected=10, repeats=3, wrong=["VSE001"])
    kinds, texts = [kind for kind, _ in found], [text for _, text in found]
    assert kinds == ["warn", "bad", "warn", "info"]
    assert texts[0] == "!  2 of 10 samples. You will be asked to confirm"
    assert texts[1] == "!  VSE001 has 2 files, not 3. Export is blocked"
    assert texts[2] == "!  1 empty cell in 1 column" and texts[3] == "Outside min–max: rows 2, 3"
    several = check_chips(scanned, clean, expected=None, repeats=3, wrong=["VSE001", "VSE002"])
    assert several[0] == ("bad", "!  2 samples do not have 3 files (VSE001, VSE002…). Export is blocked")


def test_a_long_list_of_rows_is_shortened():
    assert row_list((7,)) == "row 7" and row_list((1, 2)) == "rows 1, 2"
    assert row_list(tuple(range(1, 10))) == "rows 1, 2, 3, 4, 5, 6 … +3 more"


# ----------------------------------------------------------------------------- Validation: the data side
def rows_with_sources(*names, **extra):
    return [Observation("X", f"S{i}", float(i), 0, 20, source=name, **extra) for i, name in enumerate(names)]


def test_a_whole_number_field_may_be_empty_but_never_wrong():
    assert int_field("", "Readings", 2) is None and int_field("  ", "Readings", 2) is None
    assert int_field(" 3 ", "Readings", 2) == 3
    with pytest.raises(ValueError, match="Readings: enter a whole number, or leave it empty."):
        int_field("three", "Readings", 2)
    with pytest.raises(ValueError, match="Readings must be at least 2."):
        int_field("1", "Readings", 2)


def test_worksheet_order_is_the_dataset_itself_and_the_others_are_recorded_claims():
    dataset = Dataset.from_observations(rows_with_sources("C:/logs/b.log", "C:/logs/A.log"), description="scan")
    assert reorder_dataset(dataset, "worksheet") is dataset

    by_name = reorder_dataset(dataset, "filename")
    assert [o.source for o in by_name.observations] == ["C:/logs/A.log", "C:/logs/b.log"]  # case-insensitive
    assert by_name.description == "scan; rows sorted by file name"

    confirmed = reorder_dataset(dataset, "confirmed")
    assert [o.source for o in confirmed.observations] == [o.source for o in dataset.observations]
    assert confirmed.order_basis == "acquisition"


def test_timestamp_order_needs_a_valid_timestamp_for_every_row():
    dataset = Dataset.from_observations([
        dataclasses.replace(o, timestamp=stamp) for o, stamp in zip(
            rows_with_sources("late", "early"), ("2026-10-30T10:00:05Z", "2026-10-30T10:00:01Z"), strict=True)])
    assert [o.source for o in reorder_dataset(dataset, "timestamp").observations] == ["early", "late"]
    broken = Dataset.from_observations(rows_with_sources("one", "two"))
    with pytest.raises(ValueError, match="valid ISO 8601 timestamp"):
        reorder_dataset(broken, "timestamp")


def test_file_time_order_sorts_by_save_time_and_says_which_files_share_one(tmp_path):
    import os
    from pathlib import Path

    paths = []
    for name, seconds in (("a.log", 30), ("b.log", 10), ("c.log", 20), ("d.log", 20)):
        path = tmp_path / name
        path.write_text("x")
        os.utime(path, ns=(seconds * 10**9,) * 2)
        paths.append(path)
    dataset = Dataset.from_observations(
        [Observation("X", f"S{i}", float(i), 0, 20, source=str(path)) for i, path in enumerate(paths)], description="scan")
    ordered = reorder_dataset(dataset, "filetime")
    assert [Path(o.source).name for o in ordered.observations] == ["b.log", "c.log", "d.log", "a.log"]  # ties by file name
    assert ordered.order_basis == "acquisition"
    assert "the time each log file was saved" in ordered.description and "1 file(s) share a save time" in ordered.description
    assert [o.value for o in dataset.observations] == [0.0, 1.0, 2.0, 3.0]  # the dataset it came from is untouched


def test_file_time_order_needs_files_that_can_be_read(tmp_path):
    dataset = Dataset.from_observations([Observation("X", "S1", 1.0, 0, 20, source=str(tmp_path / "missing.log"))])
    with pytest.raises(ValueError, match="missing.log cannot be read"):
        reorder_dataset(dataset, "filetime")


def test_the_mapping_dataset_is_the_scan_copied_without_changing_it(scanned):
    source = MappingSource(scanned.grouped, ("R1", "R2"), 2, serial=1, description="Data Mapping scan")
    assert source.key == (1, ("R1", "R2"), 2)
    dataset = build_mapping_dataset(source, {}, "worksheet")
    assert dataset == snapshot_from_records(scanned.grouped, ["R1", "R2"], assignments={}, description="Data Mapping scan")
    assert len(dataset.observations) == 8  # 4 files x 2 components; a missing reading stays, as an empty value
    assert [o.test_item for o in dataset.observations if o.value in ("", None)] == ["R2"]
