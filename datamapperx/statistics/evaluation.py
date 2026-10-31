"""Evaluation: PASS / CONDITIONAL PASS / FAIL from finished statistics and acceptance criteria.

Evaluation never recomputes statistics. It also carries what a result must remember about how it was judged: the
criteria used, their version, and the validation status (conditions, acknowledgements, verification). Metrics,
evaluation status and validation status are three separate things:

* metrics (Cpk, %SV/Tol, NDC...) come from ``compute`` and depend only on data and statistical options;
* the evaluation status comes from the metrics and the criteria;
* the validation status says whether the conditions of the analysis are met, still open, or merely acknowledged.

A user acknowledging a condition is not evidence that the condition holds: acknowledgement and verification are
recorded separately and the first never changes the second.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .acceptance import acceptance, acceptance_conflicts, decision_metric, describe_criteria, metric_label
from .models import (
    CONDITIONAL,
    NOT_EVALUATED,
    PASS,
    AnalysisConfig,
    AnalysisResult,
    Criterion,
    Issue,
    StatisticsResult,
)
from .validation import validate_criteria

# ----------------------------------------------------------------------------- evaluation settings


@dataclass(frozen=True, slots=True)
class EvaluationSettings:
    """The fields of ``AnalysisConfig`` that decide PASS/FAIL (see ``models.EVALUATION_FIELDS``)."""
    cpk_threshold: float = 1.33
    profile: str = "SolarEdge"
    decision_metric: str = "percent_tolerance"
    percent_pass: float = 10.0
    percent_fail: float = 30.0
    ndc_min: int = 5
    criteria: tuple[Criterion, ...] | None = None


def evaluation_settings(config: AnalysisConfig) -> EvaluationSettings:
    return EvaluationSettings(config.cpk_threshold, config.profile, config.decision_metric, config.percent_pass,
                              config.percent_fail, config.ndc_min, config.criteria)


def combine_config(statistics, settings: EvaluationSettings, precision: int = 3) -> AnalysisConfig:
    """An ``AnalysisConfig`` from statistical options (a config or ``StatisticalOptions``) plus evaluation settings."""
    return AnalysisConfig(
        method=statistics.method, within_method=statistics.within_method, use_unbiasing=statistics.use_unbiasing,
        study_factor=statistics.study_factor, expected_repeats=statistics.expected_repeats,
        assign_trials=statistics.assign_trials, interaction_alpha=statistics.interaction_alpha,
        cpk_threshold=settings.cpk_threshold, profile=settings.profile, decision_metric=settings.decision_metric,
        percent_pass=settings.percent_pass, percent_fail=settings.percent_fail, ndc_min=settings.ndc_min,
        criteria=settings.criteria, precision=precision)


def validate_evaluation_settings(settings, method: str | None = None) -> None:
    """The evaluation checks of ``validate_config``, with the same messages."""
    for name in ("cpk_threshold", "percent_pass", "percent_fail"):
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")
    if settings.criteria is not None:
        validate_criteria(settings.criteria)
    if settings.percent_fail < settings.percent_pass:
        raise ValueError("The conditional upper boundary must be at least the pass boundary.")
    allowed = {"percent_tolerance", "percent_study_var", "ndc"} | ({"cpk", "ppk"} if method in (None, "capability") else set())
    if settings.decision_metric not in allowed:
        raise ValueError("Select one supported GRR acceptance metric.")
    if not isinstance(settings.ndc_min, int) or isinstance(settings.ndc_min, bool) or settings.ndc_min < 1:
        raise ValueError("NDC minimum must be a positive integer.")


# ----------------------------------------------------------------------------- evaluating


def evaluate_one(stat: StatisticsResult, config: AnalysisConfig) -> AnalysisResult:
    """Judge one statistics result. The logic, issue order and details order are those ``analyze`` has always produced."""
    status, selected_metric = acceptance(stat.metrics, config)
    if not stat.valid:
        # Partial/invalid data cannot receive a statistical acceptance decision.
        status = "N/A"
    conflicts = acceptance_conflicts(stat.metrics, config, selected_metric) if config.method == "grr" and status in (PASS, CONDITIONAL) else []
    issues = list(stat.issues)
    if conflicts:
        issues.append(Issue("warning", f"{status} on {metric_label(selected_metric)}, but "
                            + " and ".join(text for _, text in conflicts)
                            + ". The measurement system may not distinguish the sampled parts, or the tolerance is much wider than the "
                              "process spread. Review the study before relying on this result."))
    details = dict(stat.details)
    facts = stat.facts
    details.update({key: facts[key] for key in ("sample_count", "measurement_count", "valid_numeric_count", "lsl", "usl")})
    details.update({"acceptance_metric": selected_metric,
                    "acceptance_conflicts": tuple(key for key, _ in conflicts),
                    "cpk_threshold": config.cpk_threshold, "profile": config.profile})
    details["trial_assignment"] = facts["trial_assignment"]
    if config.method == "grr" and config.criteria is not None:
        details["applied_criteria"] = describe_criteria(config)
    else:
        details.update({"percent_pass": config.percent_pass, "percent_fail": config.percent_fail, "ndc_min": config.ndc_min})
    # Preserve issue order but avoid reporting one identical problem repeatedly.
    return AnalysisResult(stat.method, stat.test_item, stat.system, stat.n, stat.parts, stat.repeats, stat.mean,
                          stat.minimum, stat.maximum, stat.lsl, stat.usl, stat.unit, dict(stat.metrics), status,
                          selected_metric, tuple(dict.fromkeys(issues)), details, stat.observations, config)


def evaluate(statistics: Sequence[StatisticsResult], config: AnalysisConfig) -> list[AnalysisResult]:
    """Apply the acceptance criteria in ``config`` to finished statistics. Statistics are not recomputed."""
    validate_evaluation_settings(config)
    return [evaluate_one(stat, config) for stat in statistics]


# ----------------------------------------------------------------------------- criteria version


def criteria_snapshot(settings, method: str) -> dict[str, Any]:
    """Everything that decides PASS/FAIL for ``method``, in a form that can be stored and hashed."""
    if method == "capability":
        return {"kind": "capability", "cpk_threshold": settings.cpk_threshold}
    if settings.criteria is not None:
        return {"kind": "customer-criteria", "profile": settings.profile,
                "criteria": [[c.metric, c.enabled, c.pass_limit, c.fail_limit] for c in settings.criteria]}
    return {"kind": "legacy-single-metric", "profile": settings.profile, "decision_metric": settings.decision_metric,
            "percent_pass": settings.percent_pass, "percent_fail": settings.percent_fail, "ndc_min": settings.ndc_min}


def criteria_version(snapshot: dict[str, Any]) -> str:
    """A short content hash: the same rules always give the same version, different rules never do."""
    text = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "criteria-v1:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------- validation status


class Severity(StrEnum):
    INFORMATION = "information"  # background or a recommendation
    WARNING = "warning"  # a limitation that matters for how the results are read; shown with them, never blocking
    CRITICAL = "critical"  # the data cannot support a conclusion


class Verification(StrEnum):
    NOT_ASSESSED = "not assessed"
    MET = "met"
    NOT_MET = "not met"


class ValidationState(StrEnum):
    INVALID = "invalid"  # an unmet critical condition: no PASS/FAIL, whatever the user acknowledges
    UNCONFIRMED = "unconfirmed"  # a warning is still open
    ACKNOWLEDGED = "acknowledged"  # every open warning was read and accepted, but not all are verified
    VERIFIED = "verified"  # every warning-or-worse condition is verified as met


@dataclass(frozen=True, slots=True)
class Condition:
    """An assumption or requirement of the analysis, and what is known about whether it holds."""
    code: str
    severity: Severity
    message: str
    verification: Verification = Verification.NOT_ASSESSED
    evidence: tuple[tuple[str, Any], ...] = ()  # e.g. (("test", "Anderson-Darling"), ("p_value", 0.31))


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """The user read a condition and accepted the risk. This is not evidence that the condition is met."""
    code: str
    by: str
    at: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class ValidationRecord:
    conditions: tuple[Condition, ...] = ()
    acknowledgements: tuple[Acknowledgement, ...] = ()

    @property
    def state(self) -> ValidationState:
        acknowledged = {a.code for a in self.acknowledgements}
        unmet = [c for c in self.conditions if c.verification is not Verification.MET]
        if any(c.severity is Severity.CRITICAL for c in unmet):
            return ValidationState.INVALID
        open_warnings = [c for c in unmet if c.severity is Severity.WARNING]
        if not open_warnings:
            return ValidationState.VERIFIED
        if any(c.code not in acknowledged for c in open_warnings):
            return ValidationState.UNCONFIRMED
        return ValidationState.ACKNOWLEDGED

    @property
    def can_conclude(self) -> bool:
        """Whether a PASS/FAIL may be issued: no unmet critical condition and no open, unacknowledged warning."""
        return self.state in (ValidationState.ACKNOWLEDGED, ValidationState.VERIFIED)


def declared_conditions(method: str) -> tuple[Condition, ...]:
    """Conditions a method assumes, whatever the data. Normal capability assumes a stable process and a normal
    distribution; no test for either is implemented yet, so both stay 'not assessed'."""
    if method != "capability":
        return ()
    return (
        Condition("process_stability", Severity.WARNING,
                  "Capability indices describe a process that is stable and in control, and Minitab says they cannot be "
                  "relied on for future capability otherwise. Stability is not tested here: check a control chart "
                  "(Minitab suggests Xbar-S or the Capability Sixpack)."),
        Condition("normality", Severity.WARNING,
                  "Normal capability assumes the data follow a normal distribution. Normality is not tested here: compare "
                  "the histogram with the normal curves. Minitab offers Box-Cox or Johnson transformations and a "
                  "nonnormal analysis when the data are not normal."),
    )


def detect_conditions(statistics: Sequence[StatisticsResult], method: str, order_basis: str,
                      design: dict | None = None) -> tuple[Condition, ...]:
    """What the reader should know about this analysis: found from the data and the design, plus what the method assumes.

    These are notes shown beside the results and printed in the report. None of them blocks a result or a report.
    Items whose data are invalid already carry their own errors, so they add no note.
    """
    valid = [stat for stat in statistics if stat.valid]
    if method == "capability":
        found: list[Condition] = []
        if order_basis != "acquisition":
            found.append(Condition("acquisition_order", Severity.WARNING,
                                   "The readings are in worksheet order, which is not a known order of measurement. Minitab "
                                   "assumes the data are in the order they were collected; the moving-range estimate of Within "
                                   "sigma, and so Cp and Cpk, depend on that order. Pp and Ppk do not."))
        repeated = [stat for stat in valid if stat.parts < stat.n]
        if repeated:
            found.append(Condition("repeated_measurements", Severity.WARNING,
                                   f"{len(repeated)} of {len(valid)} test items have several readings per sample ID (SN). "
                                   "Repeated readings of one unit measure the measurement system as well as the process, so the "
                                   "indices may describe the repeatability of the measurement rather than the variation of the "
                                   "process. They are rational subgroups only if that is how the data were sampled."))
        if valid and min(stat.n for stat in valid) < 100:
            found.append(Condition("sample_size", Severity.INFORMATION,
                                   f"Fewer than 100 observations (smallest: {min(stat.n for stat in valid)}). Minitab suggests at "
                                   "least 100 data points for a capability analysis."))
        return (*found, *declared_conditions("capability"))
    found = []
    design = design or {}
    if design.get("nest_as_operator"):
        found.append(Condition("nest_as_operator", Severity.INFORMATION,
                               "Nest as Operator: each slot is treated as an operator. Reproducibility then reflects "
                               "differences between nests, not between people, and the conclusion applies to the fixture as a "
                               "whole, not to each nest."))
    elif valid and not any(stat.facts.get("crossed") for stat in valid):
        found.append(Condition("one_appraiser", Severity.INFORMATION,
                               "One appraiser: a one-way ANOVA estimates repeatability. Reproducibility between operators is not "
                               "estimated."))
    if valid and any(stat.facts.get("trial_assignment") for stat in valid):
        found.append(Condition("trial_inferred", Severity.INFORMATION,
                               "Where the data carry no Trial, the repeated readings of a sample are numbered 1, 2, 3… in row "
                               "order. The numbers only organise the data; they are not the order of measurement."))
    if valid and min(stat.parts for stat in valid) < 10:
        found.append(Condition("design_samples", Severity.INFORMATION,
                               f"Fewer than 10 parts (smallest: {min(stat.parts for stat in valid)}). Minitab advises at least 10 "
                               "parts that cover the actual or expected range of process variation."))
    operators = [len(stat.details.get("operators") or ()) for stat in valid if stat.facts.get("crossed")]
    if operators and min(operators) < 3:
        found.append(Condition("design_operators", Severity.INFORMATION,
                               f"Fewer than 3 operators ({min(operators)}). Minitab advises at least 3 unless fewer people "
                               "actually use the measurement system."))
    return tuple(found)


def evaluate_unjudged(stat: StatisticsResult, config: AnalysisConfig) -> AnalysisResult:
    """The statistics as a result with no criteria applied: no status, no decision metric, no Review flag."""
    details = dict(stat.details)
    facts = stat.facts
    details.update({key: facts[key] for key in ("sample_count", "measurement_count", "valid_numeric_count", "lsl", "usl")})
    details["trial_assignment"] = facts["trial_assignment"]
    return AnalysisResult(stat.method, stat.test_item, stat.system, stat.n, stat.parts, stat.repeats, stat.mean,
                          stat.minimum, stat.maximum, stat.lsl, stat.usl, stat.unit, dict(stat.metrics), NOT_EVALUATED, "",
                          tuple(dict.fromkeys(stat.issues)), details, stat.observations, config)


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """How one set of statistics was judged: the criteria, their version and the validation status in force."""
    method: str
    settings: EvaluationSettings
    criteria_version: str
    criteria_snapshot: dict[str, Any] = field(compare=False)
    validation: ValidationRecord
    statistics_inputs: str  # the combined input fingerprint of the statistics that were judged

    @property
    def judged(self) -> bool:
        """False when no acceptance criteria were applied: the results are statistics only."""
        return self.criteria_snapshot.get("kind") != "none"


@dataclass(frozen=True, slots=True)
class EvaluatedResultSet:
    """The judged results for one result set, with the record of how they were judged."""
    result_set_id: str
    record: EvaluationRecord
    results: tuple[AnalysisResult, ...]


def build_record(method: str, settings: EvaluationSettings, validation: ValidationRecord, statistics_inputs: str,
                 judged: bool = True) -> EvaluationRecord:
    snapshot = criteria_snapshot(settings, method) if judged else {"kind": "none"}
    return EvaluationRecord(method, settings, criteria_version(snapshot), snapshot, validation, statistics_inputs)


def effective_decision_metric(settings: EvaluationSettings, method: str) -> str:
    """The metric (or metrics, joined with '+') the criteria actually decide on."""
    return decision_metric(combine_config(AnalysisConfig(method=method), settings))
