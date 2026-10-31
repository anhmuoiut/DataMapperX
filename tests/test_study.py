"""Phase 0: statistics and evaluation are separate; study, result sets, staleness, criteria version, validation status."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from datamapperx.statistics import (
    BUILTIN_CUSTOMERS,
    MINITAB_VERIFIED,
    PENDING_VERIFICATION,
    Acknowledgement,
    AnalysisConfig,
    Condition,
    Dataset,
    EvaluationSettings,
    Observation,
    Severity,
    StaleResultError,
    StatisticalOptions,
    Study,
    StudyInfo,
    ValidationRecord,
    ValidationState,
    Verification,
    analyze,
    compute,
    criteria_version,
    declared_conditions,
    evaluate,
    validate_config,
)
from datamapperx.statistics.evaluation import (
    build_record,
    criteria_snapshot,
    effective_decision_metric,
    evaluation_settings,
    validate_evaluation_settings,
)
from datamapperx.statistics.models import DISPLAY_FIELDS, EVALUATION_FIELDS, STATISTICAL_FIELDS, statistical_config
from datamapperx.statistics.study import method_verification, validate_statistical_options

from .baseline_support import config_from_dict, encode, result_signature

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "baseline" / "analyze_baseline.json").read_text(encoding="utf-8"))


def numbers(statistics):
    """What the statistics say, without the observations they echo (those carry provenance such as the source text)."""
    return [{f.name: encode(getattr(stat, f.name)) for f in dataclasses.fields(stat) if f.name != "observations"} for stat in statistics]


def grr_rows(values=((1, 2, 3), (4, 5, 6), (7, 8, 9)), **extra):
    return [Observation("X", f"S{i}", v, 0, 20, trial=str(j), source=f"f{i}{j}", **extra)
            for i, g in enumerate(values) for j, v in enumerate(g)]


def capability_rows(values=(1, 2, 3, 4, 5)):
    return [Observation("X", f"S{i}", v, 0, 6, source=f"c{i}") for i, v in enumerate(values)]


def grr_study(**kwargs):
    return Study(Dataset.from_observations(grr_rows()), options=StatisticalOptions(method="grr"), **kwargs)


# ----------------------------------------------------------------------------- the three kinds of setting
def test_every_config_field_is_exactly_one_of_statistical_evaluation_or_display():
    names = [f.name for f in dataclasses.fields(AnalysisConfig)]
    groups = (STATISTICAL_FIELDS, EVALUATION_FIELDS, DISPLAY_FIELDS)
    assert sorted(names) == sorted(name for group in groups for name in group)
    assert [f.name for f in dataclasses.fields(StatisticalOptions)] == list(STATISTICAL_FIELDS)
    assert [f.name for f in dataclasses.fields(EvaluationSettings)] == list(EVALUATION_FIELDS)
    assert statistical_config(AnalysisConfig(method="grr", cpk_threshold=9, precision=7)) == AnalysisConfig(method="grr")


# ----------------------------------------------------------------------------- compute does not depend on evaluation
CASES = {case["name"]: case for case in BASELINE["cases"]}


@pytest.mark.parametrize("name", ["grr_seeded_10x3", "crossed_seeded_10x3x3", "capability_30_units_x_3_individuals",
                                  "capability_pooled", "grr_negative_part_variance", "capability_empty_input"])
def test_statistics_do_not_depend_on_criteria_thresholds_or_display(name):
    from .baseline_support import observation_from_dict

    case = CASES[name]
    observations = [observation_from_dict(item) for item in case["observations"]]
    base = config_from_dict(case["config"])
    other = dataclasses.replace(base, cpk_threshold=9.0, profile="Other", decision_metric="ndc", percent_pass=1.0,
                                percent_fail=2.0, ndc_min=9, precision=9, criteria=BUILTIN_CUSTOMERS["Jabil"])
    assert encode(compute(observations, base)) == encode(compute(observations, other))


@pytest.mark.parametrize("name", ["grr_seeded_customer_Jabil", "crossed_seeded_customer_Jabil", "capability_basic",
                                  "grr_solaredge_with_conflicts", "grr_two_items_one_invalid"])
def test_analyze_is_compute_followed_by_evaluate(name):
    from .baseline_support import observation_from_dict

    case = CASES[name]
    observations = [observation_from_dict(item) for item in case["observations"]]
    config = config_from_dict(case["config"])
    combined = [result_signature(r) for r in evaluate(compute(observations, config), config)]
    assert combined == [result_signature(r) for r in analyze(observations, config)]


def test_evaluating_again_never_calls_compute_and_never_changes_a_metric(monkeypatch):
    import datamapperx.statistics.engine as engine

    stats = compute(grr_rows(), AnalysisConfig(method="grr"))
    monkeypatch.setattr(engine, "_compute", lambda *a, **k: pytest.fail("statistics were recomputed"))
    monkeypatch.setattr(engine, "compute", lambda *a, **k: pytest.fail("statistics were recomputed"))
    verdicts = {}
    for name, criteria in BUILTIN_CUSTOMERS.items():
        result, = evaluate(stats, AnalysisConfig(method="grr", profile=name, criteria=criteria))
        verdicts[name] = result.status
        assert encode(result.metrics) == encode(stats[0].metrics)
    assert set(verdicts.values()) > {"CONDITIONAL PASS"} or len(set(verdicts.values())) > 1
    assert verdicts["SolarEdge"] != verdicts["Jabil"]


def test_evaluation_leaves_the_statistics_result_untouched():
    stats = compute(grr_rows(), AnalysisConfig(method="grr"))
    before = encode(stats)
    evaluate(stats, AnalysisConfig(method="grr", criteria=BUILTIN_CUSTOMERS["Jabil"]))
    evaluate(stats, AnalysisConfig(method="grr"))
    assert encode(stats) == before
    one, two = (evaluate(stats, AnalysisConfig(method="grr"))[0] for _ in range(2))
    assert one.metrics is not two.metrics and one.details is not two.details and one.metrics is not stats[0].metrics


def test_the_new_validators_give_the_messages_validate_config_gives():
    statistical = {"unknown_method", "within_method", "study_factor_inf", "expected_repeats_one", "expected_repeats_float",
                   "alpha_zero", "alpha_one", "alpha_nan"}
    display = {"precision_11", "precision_bool"}
    for case in BASELINE["config_errors"]:
        config = config_from_dict(case["config"])
        with pytest.raises(ValueError) as expected:
            validate_config(config)
        assert str(expected.value) == case["message"]
        name = case["name"]
        if name in statistical:
            with pytest.raises(ValueError) as caught:
                validate_statistical_options(config)
            assert str(caught.value) == case["message"]
            validate_evaluation_settings(evaluation_settings(config))
        elif name in display:
            validate_statistical_options(config)
            validate_evaluation_settings(evaluation_settings(config))
        else:
            validate_statistical_options(config)
            with pytest.raises(ValueError) as caught:
                validate_evaluation_settings(evaluation_settings(config))
            assert str(caught.value) == case["message"]


# ----------------------------------------------------------------------------- stale detection
def other_observations():
    data = grr_rows()
    data[0] = dataclasses.replace(data[0], value=1.5)
    return data


def edit_dataset(study):
    study.dataset = Dataset.from_observations(other_observations())


def reorder_dataset(study):
    study.dataset = Dataset.from_observations(grr_rows()[::-1])


def edit_mapping(study):
    study.mapping["trial"] = "@trial"


def edit_design(study):
    study.design["operators"] = ["A", "B"]


def edit_relevant_option(study):
    study.options = dataclasses.replace(study.options, study_factor=5.15)


def edit_alpha(study):
    study.options = dataclasses.replace(study.options, interaction_alpha=0.1)


@pytest.mark.parametrize("change,reasons", [
    (edit_dataset, ("dataset",)), (reorder_dataset, ("dataset",)), (edit_mapping, ("mapping",)),
    (edit_design, ("design",)), (edit_relevant_option, ("options",)), (edit_alpha, ("options",)),
], ids=lambda value: getattr(value, "__name__", ""))
def test_changing_a_statistical_input_makes_results_stale(change, reasons):
    study = grr_study()
    result_set = study.run_statistics()
    assert not study.is_stale(result_set) and study.require_current(result_set) is result_set
    change(study)
    assert study.is_stale(result_set) and study.stale_reasons(result_set) == reasons
    with pytest.raises(StaleResultError, match="stale"):
        study.require_current(result_set)


def edit_info(study):
    study.info = StudyInfo(gage_name="G1", date_of_study="2026-10-30", reported_by="me", misc="x", gage_resolution="0.01")


def edit_criteria(study):
    study.evaluation = EvaluationSettings(profile="Jabil", criteria=BUILTIN_CUSTOMERS["Jabil"], cpk_threshold=2.0)


def edit_irrelevant_option(study):
    study.options = dataclasses.replace(study.options, within_method="pooled", use_unbiasing=False)


def same_data_other_provenance(study):
    study.dataset = Dataset.from_observations([dataclasses.replace(o, source=f"sheet!R{n}", timestamp="2026") for n, o in enumerate(grr_rows())],
                                              order_basis="acquisition", description="elsewhere")


@pytest.mark.parametrize("change", [edit_info, edit_criteria, edit_irrelevant_option, same_data_other_provenance],
                         ids=lambda value: value.__name__)
def test_changing_something_that_is_not_a_statistical_input_keeps_results_current(change):
    study = grr_study()
    result_set = study.run_statistics()
    change(study)
    assert study.stale_reasons(result_set) == () and not study.is_stale(result_set)
    # ...and it really cannot change the numbers: recomputing gives identical statistics.
    assert numbers(study.run_statistics().statistics) == numbers(result_set.statistics)


def test_an_option_the_method_does_not_read_is_not_an_input():
    capability = Study(Dataset.from_observations(capability_rows()), options=StatisticalOptions(method="capability"))
    first = capability.run_statistics()
    capability.options = dataclasses.replace(capability.options, study_factor=5.15, interaction_alpha=0.2, expected_repeats=3)
    assert not capability.is_stale(first) and numbers(capability.run_statistics().statistics) == numbers(first.statistics)
    for stale in (dataclasses.replace(capability.options, within_method="pooled"),
                  dataclasses.replace(capability.options, assign_trials=True)):  # every result echoes assign_trials
        capability.options = stale
        assert capability.is_stale(first)
        capability.options = StatisticalOptions(method="capability")


def test_a_stale_result_set_stays_available_but_is_not_current():
    study = grr_study()
    old = study.run_statistics()
    edit_dataset(study)
    new = study.run_statistics()
    assert study.result_sets == [old, new] and (old.id, new.id) == ("RS-0001", "RS-0002")
    assert study.is_stale(old) and not study.is_stale(new)
    assert old.statistics[0].metrics != new.statistics[0].metrics
    assert old.inputs.combined != new.inputs.combined and old.inputs.differences(new.inputs) == ("dataset",)


def test_inputs_hash_each_part_separately_and_ignore_everything_else():
    study = grr_study()
    inputs = study.inputs()
    edit_info(study)
    edit_criteria(study)
    assert study.inputs() == inputs and inputs.combined.startswith("inputs-v1:")
    study.mapping["x"] = 1
    assert study.inputs().mapping != inputs.mapping and study.inputs().dataset == inputs.dataset


# ----------------------------------------------------------------------------- evaluation record: criteria, version, acknowledgements
def test_evaluating_a_result_set_records_criteria_version_and_validation_status():
    study = grr_study()
    result_set = study.run_statistics()
    solar = study.evaluate(result_set, EvaluationSettings(profile="SolarEdge", criteria=BUILTIN_CUSTOMERS["SolarEdge"]))
    jabil = study.evaluate(result_set, EvaluationSettings(profile="Jabil", criteria=BUILTIN_CUSTOMERS["Jabil"]))
    again = study.evaluate(result_set, EvaluationSettings(profile="Jabil", criteria=BUILTIN_CUSTOMERS["Jabil"]))
    assert solar.record.criteria_version != jabil.record.criteria_version == again.record.criteria_version
    assert jabil.record.criteria_version.startswith("criteria-v1:") and len(jabil.record.criteria_version) == len("criteria-v1:") + 16
    assert jabil.record.statistics_inputs == result_set.inputs.combined and jabil.result_set_id == result_set.id
    assert jabil.record.criteria_snapshot["criteria"][0][:2] == ["percent_tolerance", True]
    assert jabil.record.settings.criteria == BUILTIN_CUSTOMERS["Jabil"]
    assert [r.status for r in solar.results] != [r.status for r in jabil.results]
    assert encode([r.metrics for r in solar.results]) == encode([r.metrics for r in jabil.results])
    assert encode(study.result_sets) == encode([result_set]) and study.result_sets[0] is result_set


def test_the_criteria_version_follows_the_rules_and_only_the_rules():
    base = EvaluationSettings(profile="Jabil", criteria=BUILTIN_CUSTOMERS["Jabil"])
    version = lambda settings, method="grr": criteria_version(criteria_snapshot(settings, method))  # noqa: E731
    assert version(base) == version(dataclasses.replace(base))
    loosened = tuple(dataclasses.replace(c, fail_limit=c.fail_limit + 1) if c.metric != "ndc" else c for c in base.criteria)
    assert version(dataclasses.replace(base, criteria=loosened)) != version(base)
    assert version(dataclasses.replace(base, cpk_threshold=9.0)) == version(base)  # irrelevant to a GRR judgement
    assert version(dataclasses.replace(base, cpk_threshold=9.0), "capability") != version(base, "capability")
    legacy = EvaluationSettings(profile="Customer", decision_metric="ndc")
    assert version(legacy) != version(dataclasses.replace(legacy, ndc_min=6))
    assert effective_decision_metric(base, "grr") == "percent_tolerance+percent_study_var+ndc"
    assert effective_decision_metric(EvaluationSettings(), "capability") == "cpk"


def test_acknowledgements_are_stored_with_the_evaluation_but_change_no_number():
    study = Study(Dataset.from_observations(capability_rows(tuple(range(1, 31)))), options=StatisticalOptions(method="capability"))
    result_set = study.run_statistics()
    quiet = study.evaluate(result_set)
    acks = (Acknowledgement("acquisition_order", "me", "2026-10-30T09:59:59"),
            Acknowledgement("process_stability", "me", "2026-10-30T10:00:00"),
            Acknowledgement("normality", "me", "2026-10-30T10:00:01", "reviewed"))
    acknowledged = study.evaluate(result_set, acknowledgements=acks)
    assert acknowledged.record.validation.acknowledgements == acks
    assert quiet.record.validation.state is ValidationState.UNCONFIRMED
    assert acknowledged.record.validation.state is ValidationState.ACKNOWLEDGED
    assert encode([r.metrics for r in quiet.results]) == encode([r.metrics for r in acknowledged.results])
    assert [r.status for r in quiet.results] == [r.status for r in acknowledged.results]


# ----------------------------------------------------------------------------- validation status
def warning(code="w", verification=Verification.NOT_ASSESSED):
    return Condition(code, Severity.WARNING, "warning", verification)


def critical(code="c", verification=Verification.NOT_MET):
    return Condition(code, Severity.CRITICAL, "critical", verification)


def ack(code):
    return Acknowledgement(code, "user", "2026-10-30T10:00:00")


@pytest.mark.parametrize("conditions,acknowledgements,state,concludes", [
    ((), (), ValidationState.VERIFIED, True),
    ((Condition("n", Severity.INFORMATION, "fewer than 100 points"),), (), ValidationState.VERIFIED, True),
    ((warning("a"),), (), ValidationState.UNCONFIRMED, False),
    ((warning("a"), warning("b")), (ack("a"),), ValidationState.UNCONFIRMED, False),
    ((warning("a"), warning("b")), (ack("a"), ack("b")), ValidationState.ACKNOWLEDGED, True),
    ((warning("a", Verification.MET), warning("b")), (ack("b"),), ValidationState.ACKNOWLEDGED, True),
    ((warning("a", Verification.MET), warning("b", Verification.MET)), (), ValidationState.VERIFIED, True),
    ((warning("a", Verification.NOT_MET),), (ack("a"),), ValidationState.ACKNOWLEDGED, True),
    ((critical(),), (), ValidationState.INVALID, False),
    ((critical(),), (ack("c"),), ValidationState.INVALID, False),  # acknowledging never overrides a critical condition
    ((critical(verification=Verification.MET), warning("a")), (ack("a"),), ValidationState.ACKNOWLEDGED, True),
    ((warning("a"),), (ack("other"),), ValidationState.UNCONFIRMED, False),
], ids=lambda value: "" if not isinstance(value, ValidationState) else value.value)
def test_validation_state_from_conditions_and_acknowledgements(conditions, acknowledgements, state, concludes):
    record = ValidationRecord(conditions, acknowledgements)
    assert record.state is state and record.can_conclude is concludes


def test_acknowledging_a_condition_never_marks_it_as_met():
    conditions = declared_conditions("capability")
    record = ValidationRecord(conditions, tuple(ack(c.code) for c in conditions))
    assert record.state is ValidationState.ACKNOWLEDGED and record.state is not ValidationState.VERIFIED
    assert all(c.verification is Verification.NOT_ASSESSED for c in record.conditions)
    assert {c.code for c in conditions} == {"process_stability", "normality"}
    assert all(c.severity is Severity.WARNING for c in conditions) and declared_conditions("grr") == ()


# ----------------------------------------------------------------------------- method verification is not dataset validation
def test_method_verification_describes_the_method_and_defaults_to_pending():
    study = Study(Dataset.from_observations(grr_rows()), options=StatisticalOptions(method="grr"))
    result_set = study.run_statistics()
    assert dict(result_set.method_verification) == {"grr_one_way": PENDING_VERIFICATION}
    assert method_verification("something_new") == PENDING_VERIFICATION != MINITAB_VERIFIED
    crossed = Study(Dataset.from_observations(
        [dataclasses.replace(o, operator=op, source=f"{op}-{o.source}") for op in "AB" for o in grr_rows(((1, 3), (4, 6), (7, 9)))]),
        options=StatisticalOptions(method="grr"))
    assert dict(crossed.run_statistics().method_verification) == {"grr_crossed_interaction_removed": PENDING_VERIFICATION}
    broken = Study(Dataset.from_observations([dataclasses.replace(o, operator=op) for op in "AB" for o in grr_rows(((1, 3), (4, 6)))]),
                   options=StatisticalOptions(method="grr"))  # the same sources twice: invalid, but still a crossed study
    assert not broken.run_statistics().statistics[0].valid
    assert dict(broken.result_sets[0].method_verification) == {"grr_crossed": PENDING_VERIFICATION}
    capability = Study(Dataset.from_observations(capability_rows()), options=StatisticalOptions(method="capability"))
    assert dict(capability.run_statistics().method_verification) == {"capability_individuals": PENDING_VERIFICATION}
    # Acknowledging conditions changes the validation status of a dataset, not the verification of the method.
    open_codes = [c.code for c in capability.evaluate(capability.result_sets[0]).record.validation.conditions]
    assert {"acquisition_order", "process_stability", "normality"} <= set(open_codes)
    evaluated = capability.evaluate(capability.result_sets[0], acknowledgements=[ack(code) for code in open_codes])
    assert evaluated.record.validation.state is ValidationState.ACKNOWLEDGED
    assert dict(capability.result_sets[0].method_verification) == {"capability_individuals": PENDING_VERIFICATION}


def test_a_record_can_be_built_for_any_method_and_keeps_what_was_used():
    settings = EvaluationSettings()
    record = build_record("capability", settings, ValidationRecord(), "inputs-v1:abc")
    assert record.method == "capability" and record.statistics_inputs == "inputs-v1:abc"
    assert record.criteria_snapshot == {"kind": "capability", "cpk_threshold": 1.33}
    assert record.validation.state is ValidationState.VERIFIED
