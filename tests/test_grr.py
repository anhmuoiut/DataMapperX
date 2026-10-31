"""Independent examples and invalid-input checks for the single-factor GRR precheck."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from datamapperx.grr import (
    CAUTION,
    DEFAULT_QUICK_CRITERIA,
    FAIL,
    NOT_APPLIED,
    NOT_EVALUATED,
    PASS,
    combine_quick_statuses,
    grr_status,
    metric_status,
    quick_check,
    quick_criteria_from_json,
    quick_criteria_to_json,
    summarize_grr,
    validate_quick_criteria,
)
from datamapperx.models import LogRecord, Measurement
from datamapperx.settings import Settings, load_settings, save_settings
from datamapperx.statistics.models import Criterion


def data(values=((1, 2, 3), (4, 5, 6), (7, 8, 9)), low="0", high="20", unit="V"):
    return {
        f"S{part}": [
            LogRecord(Path(f"S{part}_{repeat}.log"), f"S{part}", {
                "X": Measurement("X", str(value), low, high, unit),
            })
            for repeat, value in enumerate(readings)
        ]
        for part, readings in enumerate(values)
    }


@pytest.mark.parametrize("value, expected", [
    (0, PASS), (9.999, PASS), (10, PASS), (10.00001, CAUTION),
    (29.999, CAUTION), (30, CAUTION), (30.00001, FAIL), (100, FAIL),
    (None, NOT_EVALUATED), (-1, NOT_EVALUATED), (math.nan, NOT_EVALUATED),
    (math.inf, NOT_EVALUATED), (-math.inf, NOT_EVALUATED),
])
def test_status_uses_unrounded_value_and_exact_boundaries(value, expected):
    assert grr_status(value) == expected


def test_known_one_way_anova_example():
    # Each part has within SS=2, hence MSwithin=6/6=1. Part means 2,5,8 give
    # MSbetween=3*(9+0+9)/2=27. Part variance=(27-1)/3=26/3, total=29/3.
    result, = summarize_grr(data(), ["X"], expected_repeats=3)
    assert result.study_var == pytest.approx(6)
    assert result.percent_study_var == pytest.approx(100 * math.sqrt(3 / 29))
    assert result.percent_tolerance == pytest.approx(30)
    assert (result.study_status, result.tolerance_status) == (FAIL, CAUTION)
    assert (result.parts, result.repeats, result.unit, result.note) == (3, 3, "V", "")
    assert result.ndc == 4 and result.ndc_status == FAIL


def test_negative_part_variance_is_clipped_without_pooling():
    result, = summarize_grr(data(((0, 2), (0, 2)), high="100"), ["X"])
    assert result.study_var == pytest.approx(6 * math.sqrt(2))
    assert result.percent_study_var == 100
    assert result.percent_tolerance == pytest.approx(6 * math.sqrt(2))
    assert result.ndc == 1 and result.ndc_status == FAIL


def test_large_offset_does_not_change_anova():
    baseline, = summarize_grr(data(), ["X"])
    shifted, = summarize_grr(data(tuple(tuple(1e12 + x for x in part) for part in ((1, 2, 3), (4, 5, 6), (7, 8, 9)))), ["X"])
    assert shifted.study_var == pytest.approx(baseline.study_var)
    assert shifted.percent_study_var == pytest.approx(baseline.percent_study_var)
    assert shifted.ndc == baseline.ndc


def test_identical_values_have_zero_tolerance_percentage_but_no_study_percentage():
    result, = summarize_grr(data(((5, 5), (5, 5))), ["X"])
    assert result.study_var == 0
    assert result.percent_study_var is None and result.study_status == NOT_EVALUATED
    assert result.percent_tolerance == 0 and result.tolerance_status == PASS
    assert "total variation is zero" in result.note
    assert result.ndc is None and result.ndc_status == NOT_EVALUATED
    assert "NDC" in result.note


def test_perfect_repeatability_with_distinct_parts_is_zero_percent():
    result, = summarize_grr(data(((1, 1), (2, 2))), ["X"])
    assert result.study_var == result.percent_study_var == result.percent_tolerance == 0
    assert result.study_status == result.tolerance_status == PASS
    assert result.ndc is None and result.ndc_status == NOT_EVALUATED
    assert "NDC is unavailable because repeatability is zero" in result.note


@pytest.mark.parametrize("values, expected_repeats, phrase", [
    ((), None, "at least two serial"),
    (((1, 2),), None, "at least two serial"),
    (((1,), (2,)), None, "at least two repeated"),
    (((1, 2), (3, 4, 5)), None, "same number"),
    (((1, 2), (3, 4)), 3, "needs 3 repeated"),
    (((), ()), None, "at least two repeated"),
])
def test_invalid_study_structure_is_not_evaluated(values, expected_repeats, phrase):
    result, = summarize_grr(data(values), ["X"], expected_repeats)
    assert result.study_var is result.percent_study_var is result.percent_tolerance is None
    assert result.study_status == result.tolerance_status == NOT_EVALUATED
    assert phrase in result.note
    assert result.ndc is None and result.ndc_status == NOT_EVALUATED


@pytest.mark.parametrize("value", ["", "PASS", "NaN", "inf", "-inf", "1e999", "1,2"])
def test_non_numeric_measurement_is_not_silently_dropped(value):
    grouped = data()
    record = grouped["S1"][0]
    record.entries["X"] = replace(record.entries["X"], measured=value)
    result, = summarize_grr(grouped, ["X"])
    assert result.study_status == result.tolerance_status == NOT_EVALUATED
    assert "S1" in result.note and record.filename in result.note


def test_missing_component_does_not_drop_a_part_or_affect_another_component():
    grouped = data()
    for records in grouped.values():
        for record in records:
            record.entries["Y"] = replace(record.entries["X"], component="Y")
    del grouped["S1"][0].entries["Y"]
    results = summarize_grr(grouped, ["Y", "X"])
    assert [result.component for result in results] == ["Y", "X"]
    assert results[0].study_status == NOT_EVALUATED
    assert results[1].study_var == pytest.approx(6)


@pytest.mark.parametrize("low, high", [("", "20"), ("0", ""), ("", ""), ("0", "0"), ("20", "0"), ("nan", "20"), ("0", "inf")])
def test_invalid_limits_only_prevent_tolerance_evaluation(low, high):
    result, = summarize_grr(data(low=low, high=high), ["X"])
    assert result.study_var == pytest.approx(6)
    assert result.percent_study_var is not None and result.study_status == FAIL
    assert result.percent_tolerance is None and result.tolerance_status == NOT_EVALUATED
    assert "SV/Toler" in result.note
    assert result.ndc == 4 and result.ndc_status == FAIL


def test_conflicting_limits_do_not_use_the_first_files_limits():
    grouped = data()
    record = grouped["S1"][0]
    record.entries["X"] = replace(record.entries["X"], max_value="30")
    result, = summarize_grr(grouped, ["X"])
    assert result.percent_study_var is not None
    assert result.percent_tolerance is None
    assert "limits differ" in result.note


def test_equivalent_numeric_limit_formats_are_consistent():
    grouped = data()
    record = grouped["S1"][0]
    record.entries["X"] = replace(record.entries["X"], min_value="0.0", max_value="2e1")
    result, = summarize_grr(grouped, ["X"])
    assert result.percent_tolerance == pytest.approx(30)


@pytest.mark.parametrize("unit", ["mV", ""])
def test_conflicting_units_prevent_both_metrics(unit):
    grouped = data()
    record = grouped["S1"][0]
    record.entries["X"] = replace(record.entries["X"], unit=unit)
    result, = summarize_grr(grouped, ["X"])
    assert result.study_var is result.percent_study_var is result.percent_tolerance is None
    assert result.study_status == result.tolerance_status == NOT_EVALUATED
    assert "Units differ" in result.note


def test_consistently_unspecified_unit_is_allowed():
    result, = summarize_grr(data(unit=""), ["X"])
    assert result.study_var == pytest.approx(6) and result.unit == ""


def test_extreme_finite_measurements_do_not_produce_nan_or_infinite_results():
    result, = summarize_grr(data(((-1e308, 1e308), (-1e308, 1e308))), ["X"])
    assert result.study_status == result.tolerance_status == NOT_EVALUATED
    assert "range is too large" in result.note


def test_extreme_finite_limits_do_not_create_a_false_zero_tolerance_percentage():
    result, = summarize_grr(data(low="-1e308", high="1e308"), ["X"])
    assert result.percent_study_var is not None and result.percent_tolerance is None
    assert "range is too large" in result.note


def test_empty_selection_stays_empty():
    assert summarize_grr(data(), []) == []


def test_ndc_passes_when_parts_are_distinct_relative_to_repeatability():
    # Means 1.1,10.1,20.1 yield MS_Part=271; MS_Error=.01. Thus
    # part variance=90.33 and floor(1.41*sqrt(90.33/.01))=134.
    result, = summarize_grr(data(((1, 1.1, 1.2), (10, 10.1, 10.2), (20, 20.1, 20.2))), ["X"])
    assert result.ndc == 134 and result.ndc_status == PASS


@pytest.mark.parametrize("values", [
    ((1, 2, 3), (4, 5, 6), (7, 8, 9)),
    ((0, 2), (0, 2)),
    ((1, 1), (2, 2)),
    ((5, 5), (5, 5)),
    ((1e-100, 2e-100), (10e-100, 11e-100)),
])
def test_ndc_matches_the_statistical_validation_engine(values):
    from datamapperx.statistics import AnalysisConfig, analyze, normalize_records

    grouped = data(values)
    quick, = summarize_grr(grouped, ["X"])
    detailed, = analyze(normalize_records(grouped, ["X"], assign_trials=True), AnalysisConfig(method="grr"))
    assert quick.ndc == detailed.metrics["ndc"]


def test_ndc_convention_preserves_integer_boundary_minimum_and_extreme_finite_ratio():
    from datamapperx.statistics.numeric import ndc_from_variances

    assert ndc_from_variances(25, 1)[0] == 7  # floor(7.05), not rounding
    assert ndc_from_variances(0, 1) == (1, 0.0)
    for part, gage in ((1, 0), (math.inf, 1), (1, math.nan), (-1, 1)):
        assert ndc_from_variances(part, gage) == (None, None)
    integer, raw = ndc_from_variances(1, 1e-320)
    assert integer is not None and raw is not None and math.isfinite(raw)


# ----------------------------------------------------------------------------- the Quick Check criteria
STUDY, TOLERANCE, NDC = DEFAULT_QUICK_CRITERIA


def test_the_default_criteria_keep_the_old_behaviour_and_leave_tolerance_out_of_the_decision():
    assert [(c.metric, c.enabled, c.pass_limit, c.fail_limit) for c in DEFAULT_QUICK_CRITERIA] == [
        ("percent_study_var", True, 10, 30), ("percent_tolerance", False, 10, 30), ("ndc", True, 5, 5)]
    for value in (0, 9.999, 10, 10.00001, 30, 30.00001, 100, None, -1, math.nan, math.inf):
        assert metric_status(value, STUDY) == grr_status(value) == metric_status(value, TOLERANCE)  # the same grading as before
    for value, expected in ((5, PASS), (4, FAIL), (134, PASS), (1, FAIL), (None, NOT_EVALUATED), (math.nan, NOT_EVALUATED)):
        assert metric_status(value, NDC) == expected  # NDC is higher-is-better: a large one is never a failure
    assert metric_status(True, NDC) == NOT_EVALUATED


def test_the_limits_are_the_ones_given_for_each_metric_independently():
    study = Criterion("percent_study_var", True, 20, 50)
    assert [metric_status(v, study) for v in (20, 20.1, 50, 50.1)] == [PASS, CAUTION, CAUTION, FAIL]
    assert metric_status(20.1, STUDY) == CAUTION and metric_status(20.1, Criterion("percent_tolerance", True, 25, 40)) == PASS
    ndc = Criterion("ndc", True, 8, 8)
    assert [metric_status(v, ndc) for v in (7, 8, 9)] == [FAIL, PASS, PASS]


def test_the_result_is_the_worst_of_the_metrics_that_decide_and_what_cannot_be_judged_is_never_a_pass():
    assert combine_quick_statuses([PASS, PASS]) == PASS and combine_quick_statuses([PASS, CAUTION]) == CAUTION
    assert combine_quick_statuses([CAUTION, FAIL, PASS]) == FAIL and combine_quick_statuses([FAIL, NOT_EVALUATED]) == FAIL
    assert combine_quick_statuses([PASS, NOT_EVALUATED]) == combine_quick_statuses([CAUTION, NOT_EVALUATED]) == NOT_EVALUATED
    assert combine_quick_statuses([]) == NOT_APPLIED  # nothing decides: no result, not a pass
    study, = summarize_grr(data(((1, 2, 3), (4, 5, 6), (7, 8, 9))), ["X"])  # %Study Var 32.16, %SV/Tol 30, NDC 4
    default = quick_check(study, DEFAULT_QUICK_CRITERIA)
    assert (default.study, default.tolerance, default.ndc, default.overall) == (FAIL, NOT_APPLIED, FAIL, FAIL)
    lenient = tuple(replace(c, enabled=c.metric == "percent_tolerance") for c in DEFAULT_QUICK_CRITERIA)
    assert quick_check(study, lenient).overall == CAUTION  # only %SV/Tol (30 is the last CAUTION value) decides
    none = tuple(replace(c, enabled=False) for c in DEFAULT_QUICK_CRITERIA)
    assert quick_check(study, none).overall == NOT_APPLIED


def test_an_unavailable_figure_that_decides_gives_no_result_unless_another_metric_already_fails():
    no_limits, = summarize_grr(data(low="", high=""), ["X"])
    assert no_limits.percent_tolerance is None
    both = tuple(replace(c, enabled=True) for c in DEFAULT_QUICK_CRITERIA)
    assert quick_check(no_limits, DEFAULT_QUICK_CRITERIA).tolerance == NOT_APPLIED  # it does not decide: nothing to say
    status = quick_check(no_limits, both)
    assert status.tolerance == NOT_EVALUATED and status.overall == FAIL  # SV and NDC fail on these data
    good = tuple(replace(c, pass_limit=100, fail_limit=100) if c.metric == "percent_study_var" else
                 replace(c, pass_limit=1, fail_limit=1) if c.metric == "ndc" else c for c in both)
    assert quick_check(no_limits, good).overall == NOT_EVALUATED  # everything else passes: still not a pass


def test_limits_are_checked_for_range_and_order():
    validate_quick_criteria(DEFAULT_QUICK_CRITERIA)
    bad = {
        "PASS limit cannot be above": replace(STUDY, pass_limit=40, fail_limit=30),
        "above 0 and at most 100": replace(STUDY, fail_limit=101),
        "above 0 and at most 1000": replace(TOLERANCE, pass_limit=0),
        "enter numbers": replace(STUDY, pass_limit=math.nan),
        "whole number from 1 to 100": replace(NDC, pass_limit=2.5, fail_limit=2.5),
    }
    for message, criterion in bad.items():
        criteria = tuple(criterion if c.metric == criterion.metric else c for c in DEFAULT_QUICK_CRITERIA)
        with pytest.raises(ValueError, match=message):
            validate_quick_criteria(criteria)
    for ndc in (replace(NDC, pass_limit=0, fail_limit=0), replace(NDC, pass_limit=101, fail_limit=101), replace(NDC, pass_limit=5, fail_limit=4)):
        with pytest.raises(ValueError, match="NDC"):
            validate_quick_criteria((STUDY, TOLERANCE, ndc))
    validate_quick_criteria((replace(STUDY, pass_limit=30, fail_limit=30), replace(TOLERANCE, fail_limit=1000), replace(NDC, pass_limit=100, fail_limit=100)))
    with pytest.raises(ValueError, match="once each"):
        validate_quick_criteria((STUDY, NDC))


def test_the_criteria_are_saved_in_the_settings_and_damaged_ones_fall_back_to_the_defaults(tmp_path):
    changed = (replace(STUDY, pass_limit=8, fail_limit=25), replace(TOLERANCE, enabled=True), replace(NDC, pass_limit=6, fail_limit=6))
    assert quick_criteria_to_json(DEFAULT_QUICK_CRITERIA) == []  # nothing is saved while they are the defaults
    path = tmp_path / "settings.json"
    save_settings(Settings(quick_check_criteria=quick_criteria_to_json(changed)), path)
    assert quick_criteria_from_json(load_settings(path).quick_check_criteria) == changed
    assert quick_criteria_from_json(load_settings(tmp_path / "missing.json").quick_check_criteria) == DEFAULT_QUICK_CRITERIA
    for damaged in ("text", [1, 2], [{"metric": "ndc"}], [{"metric": "ndc", "enabled": True, "pass_limit": "x", "fail_limit": 5}],
                    [{"metric": "percent_study_var", "enabled": True, "pass_limit": 50, "fail_limit": 10}], None):
        assert quick_criteria_from_json(damaged) == DEFAULT_QUICK_CRITERIA
    partial = quick_criteria_from_json([{"metric": "ndc", "enabled": True, "pass_limit": 7, "fail_limit": 7}])
    assert partial == (STUDY, TOLERANCE, replace(NDC, pass_limit=7, fail_limit=7))  # a metric left out keeps its default
