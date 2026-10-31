"""Independent algebraic examples and data-integrity checks for optional statistics."""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from datamapperx.models import LogRecord, Measurement
from datamapperx.statistics import (
    CONDITIONAL,
    FAIL,
    NOT_EVALUATED,
    PASS,
    AnalysisConfig,
    Observation,
    analyze,
    calculation_details,
    explain_method,
    format_number,
    normalize_records,
    percentage_status,
)
from datamapperx.statistics.numeric import c4, f_survival


def capability(values=(1, 2, 3, 4, 5), low=0, high=6):
    return [Observation("X", f"S{i}", value, low, high) for i, value in enumerate(values)]


def repeated(values=((1, 2, 3), (4, 5, 6), (7, 8, 9)), low=0, high=20):
    return [Observation("X", f"S{i}", value, low, high, trial=str(j))
            for i, group in enumerate(values) for j, value in enumerate(group)]


def messages(result):
    return " ".join(issue.message for issue in result.issues)


SAMPLES_A = {"S1": (1, 3), "S2": (4, 6), "S3": (7, 9)}


def crossed(data=None, low=0, high=20):
    """Rows for {operator: {sample: (trial values)}}; operator B defaults to A shifted up by one."""
    data = data or {"A": SAMPLES_A, "B": {s: tuple(x + 1 for x in v) for s, v in SAMPLES_A.items()}}
    return [Observation("X", sample, value, low, high, trial=str(trial), operator=operator)
            for operator, samples in data.items() for sample, values in samples.items()
            for trial, value in enumerate(values, 1)]


def crossed_reference(data, alpha=0.05):
    """Textbook crossed ANOVA from the definitions (SS_interaction by subtraction, closed-form F(2, d) p-value)."""
    operators, samples = list(data), list(next(iter(data.values())))
    p, o, r = len(samples), len(operators), len(data[operators[0]][samples[0]])
    assert (p - 1) * (o - 1) == 2  # the closed form below is exact for numerator df = 2
    everything = [v for op in operators for s in samples for v in data[op][s]]
    grand = sum(everything) / len(everything)
    cell = {(s, op): sum(data[op][s]) / r for s in samples for op in operators}
    sample = {s: sum(sum(data[op][s]) for op in operators) / (o * r) for s in samples}
    oper = {op: sum(sum(data[op][s]) for s in samples) / (p * r) for op in operators}
    ss_part = o * r * sum((m - grand) ** 2 for m in sample.values())
    ss_oper = p * r * sum((m - grand) ** 2 for m in oper.values())
    ss_error = sum((v - cell[(s, op)]) ** 2 for op in operators for s in samples for v in data[op][s])
    ss_int = sum((v - grand) ** 2 for v in everything) - ss_part - ss_oper - ss_error
    df_int, df_error = (p - 1) * (o - 1), p * o * (r - 1)
    ms_part, ms_oper, ms_int, ms_error = ss_part / (p - 1), ss_oper / (o - 1), ss_int / df_int, ss_error / df_error
    f_int = ms_int / ms_error
    p_int = (1 + 2 * f_int / df_error) ** (-df_error / 2)
    if p_int >= alpha:
        pooled = (ss_int + ss_error) / (df_int + df_error)
        repeat, inter, denominator = pooled, 0.0, pooled
    else:
        repeat, inter, denominator = ms_error, max((ms_int - ms_error) / r, 0), ms_int
    oper_var, part = max((ms_oper - denominator) / (p * r), 0), max((ms_part - denominator) / (o * r), 0)
    grr = repeat + oper_var + inter
    return {"p_int": p_int, "removed": p_int >= alpha, "repeat": repeat, "repro": oper_var + inter, "grr": grr,
            "part": part, "total": grr + part}


def test_assigned_repetitions_are_materialized_without_modifying_input():
    rows = [replace(row, trial="") for row in repeated()]
    result, = analyze(rows, AnalysisConfig(method="grr", assign_trials=True))
    assert result.valid
    assert [row.trial for row in result.observations] == ["1", "2", "3"] * 3
    assert all(row.trial == "" for row in rows)
    assert "explicitly assigned" in messages(result)


def test_individual_capability_uses_moving_range_not_overall_sd():
    result, = analyze(capability())
    assert result.n == result.parts == 5
    assert (result.mean, result.minimum, result.maximum) == (3, 1, 5)
    expected = {"sigma_within": 1 / 1.128, "sigma_overall": math.sqrt(2.5),
                "cp": 1.128, "cpk": 1.128, "pp": 1 / math.sqrt(2.5), "ppk": 1 / math.sqrt(2.5)}
    assert result.metrics == pytest.approx(expected)
    assert result.details["moving_ranges"] == pytest.approx((1, 1, 1, 1))
    assert result.status == FAIL


def test_individual_capability_respects_supplied_collection_order():
    a, = analyze(capability((1, 2, 3, 4, 5)))
    b, = analyze(capability((1, 5, 2, 4, 3)))
    assert a.metrics["sigma_overall"] == pytest.approx(b.metrics["sigma_overall"])
    assert a.metrics["sigma_within"] != pytest.approx(b.metrics["sigma_within"])
    assert "supplied observation order" in messages(a)


def test_pooled_within_sigma_unbiasing_matches_gamma_definition():
    rows = [replace(row, subgroup=row.sample_id) for row in repeated()]
    result, = analyze(rows, AnalysisConfig(within_method="pooled"))
    # Each subgroup has SS=2. df=3*(3-1)=6; Sp=1; overall SS=60,df=8.
    expected_c4 = math.sqrt(2 / 6) * math.gamma(3.5) / math.gamma(3)
    assert result.details["ss_within"] == pytest.approx(6)
    assert result.details["within_df"] == 6
    assert result.details["c4"] == pytest.approx(expected_c4)
    assert result.metrics["sigma_within"] == pytest.approx(1 / expected_c4)
    assert result.metrics["sigma_overall"] == pytest.approx(math.sqrt(7.5))
    assert result.metrics["cpk"] == pytest.approx(5 * expected_c4 / 3)
    no_bias, = analyze(rows, AnalysisConfig(within_method="pooled", use_unbiasing=False))
    assert no_bias.metrics["sigma_within"] == pytest.approx(1)


def test_pooled_supports_unequal_subgroup_sizes_with_weighted_df():
    rows = [replace(row, subgroup=row.sample_id) for row in repeated(((1, 3), (4, 5, 6)))]
    result, = analyze(rows, AnalysisConfig(within_method="pooled", use_unbiasing=False))
    assert result.valid
    assert result.details["within_df"] == 3
    assert result.metrics["sigma_within"] == pytest.approx(math.sqrt(4 / 3))


@pytest.mark.parametrize("groups", [("", "", ""), ("a", "a", "b")])
def test_pooled_rejects_missing_or_singleton_subgroups(groups):
    rows = [replace(row, subgroup=group) for row, group in zip(capability((1, 2, 3)), groups, strict=True)]
    result, = analyze(rows, AnalysisConfig(within_method="pooled"))
    assert not result.valid and result.status == NOT_EVALUATED
    assert result.metrics["sigma_within"] is None


@pytest.mark.parametrize("low,high,expected", [(None, 6, 1.128), (0, None, 1.128), (4, None, -0.376)])
def test_one_sided_capability_uses_available_index(low, high, expected):
    result, = analyze(capability(low=low, high=high))
    assert result.metrics["cp"] is result.metrics["pp"] is None
    assert result.metrics["cpk"] == pytest.approx(expected)
    assert "One-sided" in messages(result)


@pytest.mark.parametrize("low,high", [(None, None), (6, 0), (1, 1), ("nan", 6), (0, "inf"), (-1e308, 1e308)])
def test_missing_invalid_limits_preserve_descriptive_statistics(low, high):
    result, = analyze(capability(low=low, high=high))
    assert result.mean == 3
    assert result.metrics["sigma_overall"] == pytest.approx(math.sqrt(2.5))
    assert result.metrics["cpk"] is None and result.status == NOT_EVALUATED
    assert any(issue.severity == "warning" for issue in result.issues)


def test_conflicting_limits_do_not_silently_select_first():
    rows = capability()
    rows[0] = replace(rows[0], lsl=1)
    result, = analyze(rows)
    assert result.lsl is result.usl is None
    assert result.metrics["cpk"] is None
    assert "Conflicting" in messages(result)


@pytest.mark.parametrize("bad", [None, "", "PASS", "NaN", "inf", "1e999", "1,2", "1_000", True])
def test_non_numeric_data_is_not_dropped(bad):
    rows = capability()
    rows[1] = replace(rows[1], value=bad)
    result, = analyze(rows)
    assert result.n == 5
    assert not result.valid and result.status == NOT_EVALUATED
    assert all(value is None for value in result.metrics.values())
    assert "S1" in messages(result)


def test_single_bad_test_does_not_block_valid_test():
    rows = capability() + [replace(row, test_item="Bad", value="bad") for row in capability()]
    good, bad = analyze(rows)
    assert good.valid and good.metrics["cpk"] == pytest.approx(1.128)
    assert not bad.valid


def test_missing_sample_and_duplicate_source_are_errors():
    rows = [replace(row, sample_id="", source="same.log") for row in capability()]
    result, = analyze(rows)
    assert not result.valid
    assert "Missing Sample ID" in messages(result) and "Duplicate source" in messages(result)


def test_conflicting_units_are_errors():
    rows = capability()
    rows[0] = replace(rows[0], unit="mV")
    result, = analyze(rows)
    assert not result.valid and "Conflicting units" in messages(result)


def test_constant_values_produce_undefined_capability_not_infinite_pass():
    result, = analyze(capability((3, 3, 3)))
    assert result.metrics["sigma_within"] == result.metrics["sigma_overall"] == 0
    assert all(result.metrics[key] is None for key in ("cp", "cpk", "pp", "ppk"))
    assert result.status == NOT_EVALUATED
    assert "zero" in messages(result)


def test_one_measurement_is_insufficient():
    result, = analyze(capability((3,)))
    assert not result.valid and "at least two" in messages(result)


@pytest.mark.parametrize("scale", [1e-200, 1e-10, 1000, 1e100])
def test_capability_is_unit_scale_invariant_and_preserves_small_variation(scale):
    result, = analyze(capability(tuple(scale * n for n in (1, 2, 3, 4, 5)), 0, scale * 6))
    assert result.valid and result.metrics["cpk"] == pytest.approx(1.128)
    assert result.metrics["sigma_within"] > 0


def test_large_offsets_do_not_damage_variation():
    rows = capability(tuple(1e12 + n for n in (1, 2, 3, 4, 5)), 1e12, 1e12 + 6)
    result, = analyze(rows)
    assert result.metrics["cpk"] == pytest.approx(1.128)


def test_extreme_measurement_range_has_explanation():
    result, = analyze(capability((-1e308, 1e308)))
    assert not result.valid and "numeric range" in messages(result)


def test_capability_acceptance_is_strict_and_unrounded():
    # This example has exactly Cpk=1.128.
    threshold = 1.128
    boundary, = analyze(capability(), AnalysisConfig(cpk_threshold=threshold))
    above, = analyze(capability(), AnalysisConfig(cpk_threshold=threshold - 1e-8))
    assert boundary.status == FAIL and above.status == PASS


def test_one_way_anova_all_components_match_independent_algebra():
    result, = analyze(repeated(), AnalysisConfig(method="grr"))
    assert result.valid and (result.parts, result.repeats, result.n, result.mean) == (3, 3, 9, 5)
    assert result.details["ms_error"] == pytest.approx(1)
    assert result.details["ms_part"] == pytest.approx(27)
    part_row, error_row, total_row = result.details["anova"]
    assert part_row["ss"] == pytest.approx(54)
    assert part_row["df"] == 2
    assert part_row["f"] == pytest.approx(27)
    assert part_row["p"] == pytest.approx(.001)
    assert error_row["ss"] == pytest.approx(6) and error_row["df"] == 6
    assert total_row["ss"] == pytest.approx(60) and total_row["df"] == 8
    assert result.metrics["variance_repeatability"] == pytest.approx(1)
    assert result.metrics["variance_part"] == pytest.approx(26 / 3)
    assert result.metrics["variance_total"] == pytest.approx(29 / 3)
    assert result.metrics["sigma_grr"] == pytest.approx(1)
    assert result.metrics["percent_tolerance"] == pytest.approx(30)
    assert result.metrics["percent_study_var"] == pytest.approx(100 * math.sqrt(3 / 29))
    assert result.metrics["ndc"] == 4
    assert result.status == CONDITIONAL
    assert result.metrics["sigma_reproducibility"] is None


def test_chart_sigma_is_based_on_ranges_separately_from_anova():
    result, = analyze(repeated(), AnalysisConfig(method="grr"))
    assert result.details["r_bar"] == pytest.approx(2)
    assert result.details["chart_sigma"] == pytest.approx(2 / 1.693)
    assert result.details["chart_sigma"] != result.metrics["sigma_grr"]
    assert result.details["r_limits"]["ucl"] == pytest.approx(2 + 3 * 2 / 1.693 * .8884)
    assert result.details["xbar_limits"]["ucl"] == pytest.approx(5 + 3 * 2 / 1.693 / math.sqrt(3))


def test_negative_part_variance_is_clipped_and_ndc_has_minitab_minimum_one():
    result, = analyze(repeated(((0, 2), (0, 2))), AnalysisConfig(method="grr"))
    assert result.metrics["variance_repeatability"] == pytest.approx(2)
    assert result.metrics["variance_part"] == 0
    assert result.metrics["percent_study_var"] == 100
    assert result.metrics["ndc"] == 1
    assert "truncated to zero" in messages(result)


@pytest.mark.parametrize("values,expected_study", [(((5, 5), (5, 5)), None), (((1, 1), (2, 2)), 0)])
def test_zero_repeatability_grr_defines_tolerance_but_not_ndc(values, expected_study):
    result, = analyze(repeated(values), AnalysisConfig(method="grr"))
    assert result.metrics["study_var"] == result.metrics["percent_tolerance"] == 0
    assert result.metrics["percent_study_var"] == expected_study
    assert result.metrics["ndc"] is None and "Cannot estimate NDC" in messages(result)
    assert result.status == PASS  # SolarEdge criterion is tolerance alone.


def test_grr_missing_limits_only_prevents_tolerance_decision():
    result, = analyze(repeated(low=None, high=None), AnalysisConfig(method="grr"))
    assert result.valid and result.metrics["percent_study_var"] is not None
    assert result.metrics["ndc"] == 4
    assert result.metrics["percent_tolerance"] is None and result.status == NOT_EVALUATED


@pytest.mark.parametrize("values,phrase", [(((1, 2),), "two distinct"), (((1,), (2,)), "two repetitions"),
                                           (((1, 2), (3, 4, 5)), "Unbalanced")])
def test_grr_rejects_unsupported_designs(values, phrase):
    result, = analyze(repeated(values), AnalysisConfig(method="grr"))
    assert not result.valid and result.status == NOT_EVALUATED
    assert phrase in messages(result)


def test_expected_repetition_count_is_validated_per_sample():
    result, = analyze(repeated(((1, 2), (3, 4))), AnalysisConfig(method="grr", expected_repeats=3))
    assert not result.valid and "2 trials instead of 3" in messages(result)


def test_trial_mapping_or_explicit_assignment_is_required():
    rows = [replace(row, trial="") for row in repeated()]
    invalid, = analyze(rows, AnalysisConfig(method="grr"))
    assert not invalid.valid and "explicitly assign" in messages(invalid)
    assigned, = analyze(rows, AnalysisConfig(method="grr", assign_trials=True))
    assert assigned.valid and assigned.metrics["ndc"] == 4
    assert "explicitly assigned" in messages(assigned)


def test_partial_or_duplicate_trial_identity_is_not_silently_reassigned():
    rows = repeated()
    rows[0] = replace(rows[0], trial="")
    result, = analyze(rows, AnalysisConfig(method="grr", assign_trials=True))
    assert not result.valid and "Partially mapped" in messages(result)
    rows = repeated()
    rows[0] = replace(rows[0], trial=rows[1].trial)
    result, = analyze(rows, AnalysisConfig(method="grr"))
    assert not result.valid and "Duplicate measurement identity" in messages(result)


def test_multiple_systems_and_slots_are_evaluated_independently():
    rows = [replace(row, tester="T", operator=operator, slot=slot) for operator, slot in (("A", "1"), ("B", "2")) for row in repeated()]
    results = analyze(rows, AnalysisConfig(method="grr"))
    assert len(results) == 2
    assert all(result.n == 9 and result.metrics["ndc"] == 4 for result in results)
    assert "Slot=1" in results[0].system and "Operator=B" in results[1].system
    assert all("reproducibility is not estimated" in messages(result) for result in results)


def test_selected_study_factor_changes_only_tolerance_and_study_variation():
    result, = analyze(repeated(), AnalysisConfig(method="grr", study_factor=5.15))
    assert result.metrics["study_var"] == pytest.approx(5.15)
    assert result.metrics["percent_tolerance"] == pytest.approx(25.75)
    assert result.metrics["percent_study_var"] == pytest.approx(100 * math.sqrt(3 / 29))


def test_solaredge_tolerance_alone_overrides_stale_custom_metric():
    rows = repeated(((0, 2), (0, 2)), low=-1000, high=1000)
    solar, = analyze(rows, AnalysisConfig(method="grr", profile="SolarEdge", decision_metric="ndc"))
    jabil, = analyze(rows, AnalysisConfig(method="grr", profile="Jabil", decision_metric="ndc"))
    assert solar.metrics["percent_study_var"] == 100 and solar.metrics["ndc"] == 1
    assert solar.status == PASS and solar.decision_metric == "percent_tolerance"
    assert jabil.status == FAIL and jabil.decision_metric == "ndc"


@pytest.mark.parametrize("value,expected", [(9.999999, PASS), (10, CONDITIONAL), (30, CONDITIONAL), (30.000001, FAIL),
                                            (None, NOT_EVALUATED), (math.nan, NOT_EVALUATED), (-1, NOT_EVALUATED)])
def test_percentage_acceptance_exact_boundaries(value, expected):
    assert percentage_status(value, AnalysisConfig()) == expected


def test_custom_profile_thresholds():
    config = AnalysisConfig(method="grr", profile="Customer A", decision_metric="percent_study_var", percent_pass=40, percent_fail=50)
    result, = analyze(repeated(), config)
    assert result.status == PASS and result.decision_metric == "percent_study_var"


@pytest.mark.parametrize("kwargs", [{"method": "attribute"}, {"within_method": "overall"}, {"cpk_threshold": 0},
                                     {"cpk_threshold": math.nan}, {"percent_pass": 40, "percent_fail": 30},
                                     {"study_factor": math.inf}, {"expected_repeats": 1}, {"expected_repeats": 2.5},
                                     {"ndc_min": 0}, {"precision": 11}, {"decision_metric": "all"}])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        analyze(capability(), AnalysisConfig(**kwargs))


@pytest.mark.parametrize("f_value", [.01, .1, 1, 5, 27, 1e5])
def test_f_probability_against_closed_form_distributions(f_value):
    assert f_survival(f_value, 2, 2) == pytest.approx(1 / (1 + f_value), rel=1e-11)
    assert f_survival(f_value, 2, 6) == pytest.approx((3 / (3 + f_value)) ** 3, rel=1e-11)
    assert f_survival(f_value, 1, 1) == pytest.approx(2 / math.pi * math.atan(1 / math.sqrt(f_value)), rel=1e-10)


def test_c4_known_values_and_large_df():
    assert c4(2) == pytest.approx(math.sqrt(2 / math.pi))
    assert c4(3) == pytest.approx(math.sqrt(math.pi) / 2)
    assert .99999 < c4(1_000_000) < 1


def test_about_formulas_and_details_match_actual_selected_configuration():
    capability_help = explain_method(AnalysisConfig(within_method="individuals", cpk_threshold=2))
    assert "\u03c3_within = MRbar/1.128" in capability_help
    assert "Cpk > 2" in capability_help
    pooled_help = explain_method(AnalysisConfig(within_method="pooled", use_unbiasing=False))
    assert "\u03c3_within = Sp (unbiasing disabled)" in pooled_help
    grr_help = explain_method(AnalysisConfig(method="grr", study_factor=5.15, percent_pass=8, percent_fail=25))
    assert "StudyVar_GRR=5.15 \u00d7 \u03c3_GRR" in grr_help
    assert "NDC=max(1,floor(NDC_raw))" in grr_help
    assert "8% through 25%" in grr_help
    assert "SolarEdge always uses %SV/Tol alone" in grr_help
    assert "reproducibility" in grr_help
    result, = analyze(repeated(), AnalysisConfig(method="grr"))
    details = calculation_details(result)
    assert "measurement" in details and "ms_error =" in details and "percent_tolerance = 30" in details


def test_mapping_keeps_raw_values_and_requires_explicit_trial_assignment():
    entry = Measurement("X", "1.23000", "0", "6", "V")
    metadata = Measurement("Tester", "T1")
    record = LogRecord(Path("sample.log"), "S1", {"X": entry, "Tester": metadata})
    grouped = {"S1": [record]}
    rows = normalize_records(grouped, ["X"], {"tester": "Tester", "slot": "=2"})
    assert rows[0].value == "1.23000" and rows[0].trial == ""
    assert rows[0].tester == "T1" and rows[0].slot == "2"
    assert rows[0].lsl == "0" and rows[0].usl == "6"
    assigned = normalize_records(grouped, ["X"], assign_trials=True)
    assert assigned[0].trial == "1"
    mapped = normalize_records(grouped, ["X"], {"trial": "@trial", "sample_id": "@filename"})
    assert mapped[0].trial == "1" and mapped[0].sample_id == "sample.log"
    assert record.entries["X"] is entry and entry.measured == "1.23000"
    with pytest.raises(ValueError):
        normalize_records(grouped, ["X"], {"unknown": "X"})


def test_missing_component_is_preserved_as_invalid_observation():
    rows = normalize_records({"S": [LogRecord(Path("s.log"), "S")]}, ["Missing"])
    assert len(rows) == 1 and rows[0].value == ""
    result, = analyze(rows)
    assert not result.valid


def test_display_handles_undefined_and_tiny_values_without_rounding_data():
    assert format_number(None) == "N/A"
    assert format_number(math.inf) == "N/A"
    assert format_number(5) == "5"
    assert format_number(1e-20) != "0.000"
    assert format_number(1.23456, 3) == "1.235"
    assert analyze([], AnalysisConfig()) == []


def test_whitespace_in_sample_identity_is_normalized_without_changing_input():
    rows = repeated()
    rows[0] = replace(rows[0], sample_id=" S0 ")
    result, = analyze(rows, AnalysisConfig(method="grr"))
    assert result.valid and result.parts == 3
    assert result.observations[0].sample_id == " S0 "
    assert result.metrics["ndc"] == 4


@pytest.mark.parametrize("field", ["tester", "operator", "slot"])
def test_partially_missing_system_metadata_is_an_error_for_unspecified_group(field):
    known = [replace(row, **{field: "A"}) for row in repeated()]
    missing = [replace(row, **{field: ""}) for row in repeated()]
    a, b = analyze(known + missing, AnalysisConfig(method="grr"))
    assert a.valid and a.metrics["ndc"] == 4
    assert not b.valid and b.status == NOT_EVALUATED
    assert f"Missing {field} identifier" in messages(b)


def test_subnormal_nonzero_sigma_is_never_silently_treated_as_zero():
    tiny = 5e-324
    rows = capability((0., 0., tiny, 0., 0., 0., 0.), 0., 1.)
    result, = analyze(rows)
    assert result.metrics["sigma_within"] is None
    assert result.metrics["cpk"] is None
    assert "below the floating-point range" in messages(result)


@pytest.mark.parametrize("kwargs", [{"cpk_threshold": True}, {"precision": False}])
def test_boolean_settings_are_not_accepted_as_numeric_configuration(kwargs):
    with pytest.raises(ValueError):
        analyze(capability(), AnalysisConfig(**kwargs))


def test_about_displays_actual_unicode_math_instead_of_missing_glyph_placeholders():
    text = explain_method(AnalysisConfig())
    assert "\u03c3_within" in text and "\u00d7" in text and "\u221a" in text
    assert "?_" not in text


# ----------------------------------------------------------------------------- crossed Gage R&R (two or more operators)
def test_crossed_anova_matches_hand_calculation_and_reduced_model():
    # Operator B is operator A plus exactly one unit: no interaction, a pure operator offset.
    result, = analyze(crossed(), AnalysisConfig(method="grr"))
    assert result.valid and result.system == "Operators=A, B"
    assert (result.parts, result.repeats, result.n, result.mean) == (3, 2, 12, 5.5)
    assert result.details["crossed"] and result.details["interaction_removed"]
    assert result.details["interaction_p"] == pytest.approx(1.0)
    m = result.metrics
    assert m["variance_repeatability"] == pytest.approx(1.5)      # (SS_int + SS_err) / (2 + 6)
    assert m["variance_reproducibility"] == pytest.approx(.25)    # (3 - 1.5) / (p * r)
    assert m["variance_grr"] == pytest.approx(1.75)
    assert m["variance_part"] == pytest.approx(8.625)             # (36 - 1.5) / (o * r)
    assert m["variance_total"] == pytest.approx(10.375)
    assert m["sigma_grr"] == pytest.approx(math.sqrt(1.75)) and m["sigma_reproducibility"] == pytest.approx(.5)
    assert m["percent_study_var"] == pytest.approx(100 * math.sqrt(1.75 / 10.375))
    assert m["percent_tolerance"] == pytest.approx(6 * math.sqrt(1.75) / 20 * 100)
    assert m["ndc"] == math.floor(1.41 * math.sqrt(8.625 / 1.75)) == 3
    part, operator, error, total = result.details["anova"]
    assert (part["ss"], part["df"], part["ms"], part["f"]) == pytest.approx((72, 2, 36, 24)) and part["p"] == pytest.approx(1 / 2401)
    assert (operator["ss"], operator["df"], operator["f"]) == pytest.approx((3, 1, 2))
    assert (error["source"], error["ss"], error["df"], error["ms"]) == ("Repeatability", pytest.approx(12), 8, pytest.approx(1.5))
    assert (total["ss"], total["df"]) == (pytest.approx(87), 11)
    full = result.details["anova_with_interaction"]
    assert [row["source"] for row in full] == ["Sample ID", "Operator", "Sample ID x Operator", "Repeatability", "Total"]
    assert (full[2]["ss"], full[2]["df"], full[3]["ss"], full[3]["df"]) == pytest.approx((0, 2, 12, 6))
    assert "interaction removed" in messages(result)


def test_crossed_study_includes_the_reproducibility_that_single_operator_studies_omit():
    both, = analyze(crossed(), AnalysisConfig(method="grr"))
    alone, = analyze(crossed({"A": SAMPLES_A}), AnalysisConfig(method="grr"))
    assert alone.metrics["sigma_reproducibility"] is None and "not estimated" in messages(alone)
    assert both.metrics["sigma_grr"] > both.metrics["sigma_repeatability"]
    assert both.metrics["sigma_reproducibility"] > 0


def test_crossed_retains_a_significant_interaction_and_uses_it_for_operator_and_part_terms():
    data = {"A": SAMPLES_A, "B": {"S1": (2, 4), "S2": (5, 7), "S3": (16, 18)}}  # operator B drifts only on S3
    result, = analyze(crossed(data), AnalysisConfig(method="grr"))
    expected = crossed_reference(data)
    assert not expected["removed"] and result.details["interaction_removed"] is False
    assert result.details["interaction_p"] == pytest.approx(expected["p_int"], rel=1e-9)
    assert [row["source"] for row in result.details["anova"]][2] == "Sample ID x Operator"
    for key, name in (("variance_repeatability", "repeat"), ("variance_reproducibility", "repro"), ("variance_grr", "grr"),
                      ("variance_part", "part"), ("variance_total", "total")):
        assert result.metrics[key] == pytest.approx(expected[name], rel=1e-9), key
    assert "interaction retained" in messages(result)


@pytest.mark.parametrize("data", [
    {"A": SAMPLES_A, "B": {"S1": (2, 4), "S2": (5, 7), "S3": (9, 10)}},  # weak interaction, removed
    {"A": {"S1": (1, 3.5), "S2": (4, 6), "S3": (7, 9)}, "B": {"S1": (2, 4), "S2": (5, 7.2), "S3": (8, 10.4)}},
    {"A": {"S1": (1, 3), "S2": (4, 8), "S3": (7, 9)}, "B": {"S1": (9, 4), "S2": (5, 1), "S3": (8, 3)}},  # part variance truncated
    {"A": SAMPLES_A, "B": {"S1": (2, 4), "S2": (5, 7), "S3": (16, 18)}},  # significant interaction, retained
])
def test_crossed_variance_components_agree_with_an_independent_textbook_calculation(data):
    result, = analyze(crossed(data), AnalysisConfig(method="grr"))
    expected = crossed_reference(data)
    assert result.valid and result.details["interaction_removed"] == expected["removed"]
    for key, name in (("variance_repeatability", "repeat"), ("variance_reproducibility", "repro"), ("variance_grr", "grr"),
                      ("variance_part", "part"), ("variance_total", "total")):
        assert result.metrics[key] == pytest.approx(expected[name], rel=1e-9, abs=1e-12), key


def test_operators_that_did_not_measure_the_same_samples_are_not_pooled_silently():
    data = {"A": SAMPLES_A, "B": {"S2": (5, 7), "S3": (8, 10), "S4": (11, 13)}}
    result, = analyze(crossed(data), AnalysisConfig(method="grr"))
    assert not result.valid and result.status == NOT_EVALUATED
    assert "Not a crossed design" in messages(result) and "Slot or Tester" in messages(result)
    rows = crossed()
    unbalanced, = analyze(rows[:-1], AnalysisConfig(method="grr"))
    assert not unbalanced.valid and "Unbalanced crossed" in messages(unbalanced)


def test_crossed_trials_are_assigned_within_each_sample_and_operator_cell():
    rows = [replace(row, trial="") for row in crossed()]
    result, = analyze(rows, AnalysisConfig(method="grr", assign_trials=True))
    assert result.valid and [row.trial for row in result.observations] == ["1", "2"] * 6
    missing, = analyze(rows, AnalysisConfig(method="grr"))
    assert not missing.valid and "explicitly assign" in messages(missing)
    rows = crossed()
    rows[1] = replace(rows[1], trial=rows[0].trial)  # second measurement of S1 by A repeats trial 1
    duplicate, = analyze(rows, AnalysisConfig(method="grr"))
    assert not duplicate.valid and "Duplicate measurement identity: sample S1, operator A" in messages(duplicate)


def test_operators_in_different_slots_or_testers_stay_separate_and_a_missing_operator_is_reported():
    rows = [replace(row, slot="1" if row.operator == "A" else "2") for row in crossed()]
    assert [r.system for r in analyze(rows, AnalysisConfig(method="grr"))] == ["Operator=A | Slot=1", "Operator=B | Slot=2"]
    rows = crossed() + [replace(row, operator="") for row in repeated()]
    crossed_result, blank = analyze(rows, AnalysisConfig(method="grr"))
    assert crossed_result.valid and crossed_result.system == "Operators=A, B"
    assert not blank.valid and "Missing operator identifier" in messages(blank)


@pytest.mark.parametrize("expected,valid", [(2, True), (4, True), (3, False)])
def test_expected_files_per_sample_may_count_one_operator_or_all_of_them(expected, valid):
    result, = analyze(crossed(), AnalysisConfig(method="grr", expected_repeats=expected))
    assert result.valid is valid


def test_crossed_negative_components_are_truncated_without_touching_the_others():
    data = {"A": SAMPLES_A, "B": SAMPLES_A}  # identical operators: operator mean square is zero
    result, = analyze(crossed(data), AnalysisConfig(method="grr"))
    assert result.metrics["variance_reproducibility"] == 0 and result.metrics["sigma_reproducibility"] == 0
    assert result.metrics["variance_repeatability"] == pytest.approx(1.5)  # 12 / (2 + 6): interaction pooled into error
    assert "Negative operator variance estimate truncated to zero" in messages(result)


def test_crossed_study_uses_a_configurable_interaction_alpha():
    data = {"A": SAMPLES_A, "B": {"S1": (2, 4), "S2": (5, 7), "S3": (9, 10)}}  # interaction p is about 0.95
    lenient, = analyze(crossed(data), AnalysisConfig(method="grr", interaction_alpha=.999))
    strict, = analyze(crossed(data), AnalysisConfig(method="grr", interaction_alpha=.0001))
    assert not lenient.details["interaction_removed"] and strict.details["interaction_removed"]
    for alpha in (0, 1, -.1, True, math.nan):
        with pytest.raises(ValueError):
            analyze(crossed(), AnalysisConfig(method="grr", interaction_alpha=alpha))


def test_crossed_charts_are_per_operator_cell_and_about_text_describes_both_models():
    result, = analyze(crossed(), AnalysisConfig(method="grr"))
    summaries = result.details["part_summaries"]
    assert [(s["operator"], s["sample_id"]) for s in summaries] == [(op, s) for op in "AB" for s in ("S1", "S2", "S3")]
    assert result.details["r_bar"] == pytest.approx(2) and result.details["chart_sigma"] == pytest.approx(2 / 1.128)
    help_text = explain_method(AnalysisConfig(method="grr"))
    assert "Crossed model" in help_text and "var_Reprod" in help_text and "alpha to remove" in help_text


# ----------------------------------------------------------------------------- acceptable result vs. informational metrics
def test_pass_on_tolerance_with_poor_discrimination_is_flagged_and_the_decision_is_unchanged():
    rows = repeated(((0, 2), (0, 2)), low=-1000, high=1000)
    result, = analyze(rows, AnalysisConfig(method="grr", profile="SolarEdge"))
    assert result.status == PASS and result.decision_metric == "percent_tolerance"
    assert result.details["acceptance_conflicts"] == ("percent_study_var", "ndc")
    text = messages(result)
    assert "PASS on %SV/Tol" in text and "NDC 1 is below 5" in text and "%Study Var 100.00% is above 30%" in text
    assert any(issue.severity == "warning" and "Review the study" in issue.message for issue in result.issues)


def test_review_flag_follows_the_selected_decision_metric_and_thresholds():
    good = repeated(((0, .1), (10, 10.1), (20, 20.2), (30, 30.1)), low=0, high=100)
    clean, = analyze(good, AnalysisConfig(method="grr"))
    assert clean.status == PASS and clean.details["acceptance_conflicts"] == () and "Review the study" not in messages(clean)
    narrow = repeated(((0, .1), (10, 10.1), (20, 20.2), (30, 30.1)), low=0, high=1)
    custom, = analyze(narrow, AnalysisConfig(method="grr", profile="Customer", decision_metric="percent_study_var"))
    assert custom.status == PASS and custom.details["acceptance_conflicts"] == ("percent_tolerance",)
    failing, = analyze(repeated(((0, 2), (0, 2)), low=-1000, high=1000),
                       AnalysisConfig(method="grr", profile="Jabil", decision_metric="ndc"))
    assert failing.status == FAIL and failing.details["acceptance_conflicts"] == ()
    invalid, = analyze(repeated(((1, 2),)), AnalysisConfig(method="grr"))
    assert invalid.status == NOT_EVALUATED and invalid.details["acceptance_conflicts"] == ()
    cap, = analyze(capability(), AnalysisConfig())
    assert cap.details["acceptance_conflicts"] == ()

