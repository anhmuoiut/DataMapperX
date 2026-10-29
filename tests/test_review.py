"""The review step's logic: limits, comparing values with them, and the pre-export summary (no window needed)."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from datamapperx.exporter import iter_export_rows, summarize_limits
from datamapperx.models import LogRecord, Measurement
from datamapperx.review import HIGH, LOW, MISSING, limit_rows, limit_status, summarize_review
from datamapperx.utils import to_number


def record(sn: str, name: str, **entries: tuple) -> LogRecord:
    """``entries``: component -> (measured, min, max, unit)."""
    return LogRecord(
        Path(f"{sn}_{name}.log"), sn,
        {c: Measurement(c, *values) for c, values in entries.items()},
    )


# ----------------------------------------------------------------------------- numbers and limits
@pytest.mark.parametrize("text, expected", [
    ("+1.5E+03", 1500.0), ("-2", -2.0), (".5", 0.5), ("7.", 7.0), ("  3.25 ", 3.25), ("1e-3", 0.001), ("0", 0.0),
])
def test_numbers_are_read_in_plain_and_scientific_notation(text, expected):
    assert to_number(text) == expected


@pytest.mark.parametrize("text", ["", "PASS", "nan", "inf", "-inf", "1_000", "1,5", "0x10", "1e999", "--1", "+", None])
def test_anything_else_is_text(text):
    assert to_number(text) is None


@pytest.mark.parametrize("value, low, high, expected", [
    ("5", "0", "10", ""),
    ("10", "0", "10", ""),  # a limit itself is inside
    ("0", "0", "10", ""),
    ("10.0001", "0", "10", HIGH),
    ("-0.0001", "0", "10", LOW),
    ("+1.5E+03", "+0.0E+00", "+1.0E+03", HIGH),
    ("7", "", "10", ""),  # only an upper limit
    ("11", "", "10", HIGH),
    ("-1", "0", "", LOW),  # only a lower limit
    ("1e9", "", "", ""),  # no limits at all: nothing to judge
    ("PASS", "0", "10", ""),  # text is never judged
    ("", "0", "10", ""),
    ("5", "10", "0", ""),  # limits written the other way round still mean 0..10
    ("11", "10", "0", HIGH),
    ("-1", "10", "0", LOW),
    ("5", "n/a", "10", ""),  # an unreadable limit is ignored, the other still applies
    ("11", "n/a", "10", HIGH),
])
def test_limit_status(value, low, high, expected):
    assert limit_status(value, low, high) == expected


# ----------------------------------------------------------------------------- the limits panel
LIMITS = {"R1": {"min": "0", "max": "10", "unit": "V"}, "R2": {"min": "", "max": "5", "unit": ""}}


def test_limit_rows_pair_each_value_with_its_limits_and_status():
    grouped = {"S1": [record("S1", "a", R1=("12", "0", "10", "V"), R2=("PASS", "", "5", ""))]}
    row = next(iter_export_rows(grouped, ["R1", "R2", "NOPE"]))
    rows = limit_rows(row, ["R1", "R2", "NOPE"], LIMITS)
    assert [(r.component, r.value, r.low, r.high, r.unit, r.status) for r in rows] == [
        ("R1", "12", "0", "10", "V", HIGH),
        ("R2", "PASS", "", "5", "", ""),
        ("NOPE", "", "", "", "", MISSING),  # not in this file, not in the limits either
    ]


def test_a_blank_value_is_missing_even_when_the_component_has_limits():
    grouped = {"S1": [record("S1", "a", R2=("1", "", "5", ""))]}
    row = next(iter_export_rows(grouped, ["R1", "R2"]))
    assert [r.status for r in limit_rows(row, ["R1", "R2"], LIMITS)] == [MISSING, ""]


# ----------------------------------------------------------------------------- the summary shown before exporting
def sample_data():
    return {
        "S1": [
            record("S1", "a", R1=("5", "0", "10", "V"), R2=("1", "", "5", "")),
            record("S1", "b", R1=("12", "0", "10", "V")),  # R1 too high (row 2); R2 missing
        ],
        "S2": [
            record("S2", "a", R1=("-3", "0", "10", "V"), R2=("9", "", "5", "")),  # R1 too low, R2 too high (row 3)
            record("S2", "b", R1=("PASS", "0", "10", "V")),  # text, R2 missing
        ],
    }


def test_the_summary_counts_empty_cells_and_lists_the_rows_outside_their_limits():
    grouped = sample_data()
    summary = summarize_review(grouped, ["R1", "R2"])
    assert summary.rows == 4
    assert summary.empty_cells == 2 and summary.empty_columns == ("R2",)
    assert summary.outside_rows == (2, 3)  # export row numbers, one entry per row even when two values are off


def test_the_summary_follows_the_selected_columns_only():
    summary = summarize_review(sample_data(), ["R2"])
    assert summary.outside_rows == (3,) and summary.empty_columns == ("R2",)
    assert summarize_review(sample_data(), []).rows == 4


def test_a_clean_selection_has_nothing_to_report():
    grouped = {"S1": [record("S1", "a", R1=("5", "0", "10", "V"))]}
    summary = summarize_review(grouped, ["R1"])
    assert (summary.rows, summary.empty_cells, summary.empty_columns, summary.outside_rows) == (1, 0, (), ())


def test_the_summary_can_reuse_limits_already_worked_out():
    grouped = sample_data()
    limits = summarize_limits(grouped, ["R1", "R2"])
    assert summarize_review(grouped, ["R1", "R2"], limits) == summarize_review(grouped, ["R1", "R2"])
    loose = {"R1": {"min": "-100", "max": "100"}, "R2": {"min": "-100", "max": "100"}}
    assert summarize_review(grouped, ["R1", "R2"], loose).outside_rows == ()


# ----------------------------------------------------------------------------- summarize_limits stays correct after being made faster
def slow_reference(grouped, components):
    """The original definition: per component, the first file (in SN order) that has it."""
    summary = {}
    for component in components:
        found = {"min": "", "max": "", "unit": ""}
        for sn in sorted(grouped):
            entry = next((r.entries[component] for r in grouped[sn] if component in r.entries), None)
            if entry:
                found = {"min": entry.min_value or "", "max": entry.max_value or "", "unit": entry.unit or ""}
                break
        summary[component] = found
    return summary


def test_limits_come_from_the_first_file_in_sn_order_that_has_the_component():
    grouped = {
        "B": [record("B", "1", X=("1", "10", "20", "mV"))],
        "A": [record("A", "1", Y=("1", "", "", "")), record("A", "2", X=("1", "1", "2", "V"), Z=("1", "", "9", ""))],
    }
    assert summarize_limits(grouped, ["X", "Y", "Z", "NOPE"]) == {
        "X": {"min": "1", "max": "2", "unit": "V"},  # A comes before B
        "Y": {"min": "", "max": "", "unit": ""},
        "Z": {"min": "", "max": "9", "unit": ""},
        "NOPE": {"min": "", "max": "", "unit": ""},
    }


def test_the_fast_limits_match_the_original_definition_on_random_data():
    rng = random.Random(7)
    names = [f"C{i}" for i in range(40)]
    for _ in range(25):
        grouped = {}
        for _ in range(rng.randint(1, 8)):
            sn = f"S{rng.randint(0, 20):02d}"
            files = grouped.setdefault(sn, [])
            for f in range(rng.randint(1, 3)):
                chosen = rng.sample(names, rng.randint(0, 25))
                files.append(record(sn, str(f), **{
                    c: (str(rng.random()), rng.choice(["", "0", "1"]), rng.choice(["", "5", "9"]), rng.choice(["", "V"]))
                    for c in chosen
                }))
        wanted = rng.sample(names, rng.randint(0, 40)) + ["MISSING"]
        assert summarize_limits(grouped, wanted) == slow_reference(grouped, wanted)


def test_limits_of_a_big_scan_are_quick():
    names = [f"C{i}" for i in range(400)]
    grouped = {
        f"S{n:05d}": [record(f"S{n:05d}", "a", **{c: ("1", "0", "9", "V") for c in names})] for n in range(3000)
    }
    start = time.perf_counter()
    limits = summarize_limits(grouped, names)
    summary = summarize_review(grouped, names[:100], limits)
    elapsed = time.perf_counter() - start
    assert limits["C399"]["max"] == "9" and summary.rows == 3000
    assert elapsed < 3.0, f"{elapsed:.2f}s"  # about half a second on a normal PC; the bound only catches an accident
