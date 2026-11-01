"""Attribute Agreement against the figures Minitab prints for its own example, the Textile print quality study.

Minitab's help page "Example of Attribute Agreement Analysis" prints the output for 4 appraisers rating 50 samples twice on a
1 to 5 scale with a known Standard, and offers the worksheet. ``tests/reference/`` holds that worksheet and the tables as the
page prints them (read on 2026-11-01; the Kendall tables are left out because ordered categories are out of scope). The ratings
are analysed as nominal categories. Every figure is compared at the precision Minitab prints it, so a difference in the last
printed digit fails.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from datamapperx.statistics import AnalysisConfig, Observation, analyze

REFERENCE = Path(__file__).parent / "reference"


@pytest.fixture(scope="module")
def printed():
    return json.loads((REFERENCE / "minitab_textile_print_quality_expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def details():
    with open(REFERENCE / "minitab_textile_print_quality.csv", newline="", encoding="utf-8") as handle:
        rows = [Observation("Textile", r["Sample"], r["Response"], trial=r["Trial"], operator=r["Appraiser"], standard=r["Standard"])
                for r in csv.DictReader(handle)]
    result, = analyze(rows, AnalysisConfig(method="attribute"))
    assert result.valid and not [i for i in result.issues if i.severity == "error"]
    return result.details


def same(value, text: str) -> bool:
    """Whether the value, rounded to the decimals Minitab printed, is what Minitab printed."""
    return value is not None and f"{value:.{len(text.partition('.')[2])}f}" == text


def agreement_cases(printed, details):
    named = {a["name"]: a for a in details["appraisers"]}
    for key, block in (("within_agreement", "within"), ("standard_agreement", "standard")):
        for who, *figures in printed[key]["rows"]:
            yield f"{key}: {who}", named[who][block], figures
    for key, block in (("between_agreement", "between"), ("all_standard_agreement", "all_standard")):
        for figures in printed[key]["rows"]:
            yield key, details[block], figures


def kappa_cases(printed, details):
    named = {a["name"]: a for a in details["appraisers"]}
    for key, field in (("within_kappa", "kappa_within"), ("standard_kappa", "kappa_standard")):
        for who, response, *figures in printed[key]["rows"]:
            yield f"{key}: {who}, response {response}", named[who][field], response, figures
    for key, field in (("between_kappa", "kappa_between"), ("all_standard_kappa", "kappa_all_standard")):
        for response, *figures in printed[key]["rows"]:
            yield f"{key}: response {response}", details[field], response, figures


def test_the_study_is_the_one_minitab_describes(printed, details):
    assert (details["samples"], details["trials"], len(details["appraisers"]), details["levels"]) == (50, 2, 4, ("1", "2", "3", "4", "5"))
    assert details["standard_known"] and "minitab.com" in printed["source"]["url"]


def test_every_assessment_agreement_table_matches_to_the_printed_digit(printed, details):
    """Within Appraisers, Each Appraiser vs Standard, Between Appraisers and All Appraisers vs Standard: the counts, the percent and
    both limits of the 95 % interval, for the 4 appraisers and the two pooled tables (10 rows, 5 figures each)."""
    compared = 0
    for label, block, (inspected, matched, percent, interval) in agreement_cases(printed, details):
        low, high = interval.strip("()").split(", ")
        assert (block["inspected"], block["matched"]) == (int(inspected), int(matched)), label
        assert same(block["percent"], percent), (label, block["percent"], percent)
        assert same(block["lower"], low), (label, "lower", block["lower"], low)
        assert same(block["upper"], high), (label, "upper", block["upper"], high)
        compared += 5
    assert compared == 50


def test_every_fleiss_kappa_table_matches_to_the_printed_digit(printed, details):
    """Kappa, its standard error, Z and P for each response and Overall, within each appraiser, against the Standard for each
    appraiser, between the appraisers, and all appraisers against the Standard (60 rows, 4 figures each). With 5 responses the
    overall variance is the one that differs from a single response's, so this is where that formula is checked."""
    compared = 0
    for label, table, response, figures in kappa_cases(printed, details):
        row = table["overall"] if response == "Overall" else next(r for r in table["rows"] if r["response"] == response)
        for name, text in zip(("kappa", "se", "z", "p"), figures, strict=True):
            assert same(row[name], text), (label, name, row[name], text)
            compared += 1
    assert compared == 60 * 4


def test_all_appraisers_against_the_standard_is_the_mean_of_the_appraisers(details):
    """The construction behind the last table: the mean of the appraisers' kappas, and the sum of their variances over the number
    of appraisers squared."""
    tables = [a["kappa_standard"] for a in details["appraisers"]]
    pooled = details["kappa_all_standard"]
    assert [r["response"] for r in pooled["rows"]] == ["1", "2", "3", "4", "5"] and pooled["reason"] == ""
    for key, row in [("overall", pooled["overall"]), *((r["response"], r) for r in pooled["rows"])]:
        members = [t["overall"] if key == "overall" else next(r for r in t["rows"] if r["response"] == key) for t in tables]
        assert row["kappa"] == pytest.approx(sum(m["kappa"] for m in members) / 4, rel=1e-12)
        assert row["se"] ** 2 == pytest.approx(sum(m["se"] ** 2 for m in members) / 16, rel=1e-12)
