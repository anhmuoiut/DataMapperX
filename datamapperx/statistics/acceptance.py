"""Configurable acceptance rules; informational metrics never override a decision."""
from __future__ import annotations

import math
from collections.abc import Sequence

from .models import CONDITIONAL, FAIL, NOT_EVALUATED, PASS, AnalysisConfig, Criterion

METRIC_NAMES = {"percent_tolerance": "%SV/Tol", "percent_study_var": "%Study Var", "ndc": "NDC", "cpk": "Cpk", "ppk": "Ppk"}
CONFLICT_LABELS = {key: METRIC_NAMES[key] for key in ("percent_tolerance", "percent_study_var", "ndc")}


def metric_label(metric: str) -> str:
    """Readable name of a decision metric; several applied metrics are joined with ' + '."""
    return " + ".join(METRIC_NAMES.get(part, part) for part in metric.split("+"))


def percentage_status(value: float | None, config: AnalysisConfig) -> str:
    if value is None or not math.isfinite(value) or value < 0:
        return NOT_EVALUATED
    if value < config.percent_pass:
        return PASS
    return CONDITIONAL if value <= config.percent_fail else FAIL


def criterion_status(value: float | None, criterion: Criterion) -> str:
    """PASS / CONDITIONAL PASS / FAIL of one metric against one customer rule."""
    if value is None or not math.isfinite(value) or value < 0:
        return NOT_EVALUATED
    if criterion.metric == "ndc":
        if value >= criterion.pass_limit:
            return PASS
        return FAIL if value < criterion.fail_limit else CONDITIONAL
    if value < criterion.pass_limit:
        return PASS
    return CONDITIONAL if value <= criterion.fail_limit else FAIL


def describe_criterion(criterion: Criterion) -> str:
    label, p, f = METRIC_NAMES[criterion.metric], criterion.pass_limit, criterion.fail_limit
    if criterion.metric == "ndc":
        middle = f", CONDITIONAL PASS {f:g} to below {p:g}" if f < p else ""
        return f"{label}: PASS >= {p:g}{middle}, FAIL < {f:g}"
    middle = f", CONDITIONAL PASS {p:g}% to {f:g}%" if p < f else ""
    return f"{label}: PASS < {p:g}%{middle}, FAIL > {f:g}%"


def describe_criteria(config: AnalysisConfig) -> str:
    """The customer's rules in words: applied metrics first, then the informational ones."""
    criteria = config.criteria or ()
    applied = "; ".join(describe_criterion(c) for c in criteria if c.enabled)
    ignored = ", ".join(METRIC_NAMES[c.metric] for c in criteria if not c.enabled)
    return f"Applied: {applied}." + (f" Not applied (informational): {ignored}." if ignored else "")


def applied_metrics(config: AnalysisConfig) -> list[str]:
    return [c.metric for c in config.criteria or () if c.enabled]


def decision_metric(config: AnalysisConfig) -> str:
    if config.method == "capability":
        # Cpk by default; Ppk (overall, long-term capability) is selected with decision_metric.
        return config.decision_metric if config.decision_metric in ("cpk", "ppk") else "cpk"
    if config.criteria is not None:
        return "+".join(applied_metrics(config))
    # SolarEdge's acceptance criterion is always tolerance, even if a stale custom
    # setting requested another metric. No combined implicit pass/fail is computed.
    return "percent_tolerance" if config.profile.casefold() == "solaredge" else config.decision_metric


def combine_statuses(statuses: Sequence[str]) -> str:
    """Worst of the applied metrics: any FAIL fails; otherwise an unevaluable metric blocks a decision."""
    if FAIL in statuses:
        return FAIL
    if not statuses or NOT_EVALUATED in statuses:
        return NOT_EVALUATED
    return CONDITIONAL if CONDITIONAL in statuses else PASS


def acceptance_conflicts(metrics: dict, config: AnalysisConfig, decision: str) -> list[tuple[str, str]]:
    """Informational GRR metrics that would FAIL on their own although the decision did not.

    A wide tolerance can make %SV/Tol small while the gage still cannot tell the sampled parts apart
    (low NDC, high %Study Var). The decision is not changed; the disagreement is only reported.
    """
    found = []
    if config.criteria is not None:
        for c in config.criteria:
            value = metrics.get(c.metric)
            if c.enabled or criterion_status(value, c) != FAIL:
                continue
            found.append((c.metric, f"NDC {value} is below {c.fail_limit:g}" if c.metric == "ndc"
                          else f"{METRIC_NAMES[c.metric]} {value:.2f}% is above {c.fail_limit:g}%"))
        return found
    for key, label in CONFLICT_LABELS.items():
        value = metrics.get(key)
        if key == decision or value is None or not math.isfinite(value):
            continue
        if key == "ndc":
            if value < config.ndc_min:
                found.append((key, f"NDC {value} is below {config.ndc_min}"))
        elif percentage_status(value, config) == FAIL:
            found.append((key, f"{label} {value:.2f}% is above {config.percent_fail:g}%"))
    return found


def acceptance(metrics: dict, config: AnalysisConfig) -> tuple[str, str]:
    metric = decision_metric(config)
    if config.method == "grr" and config.criteria is not None:
        statuses = [criterion_status(metrics.get(c.metric), c) for c in config.criteria if c.enabled]
        return combine_statuses(statuses), metric
    value = metrics.get(metric)
    if value is None or not math.isfinite(value):
        return NOT_EVALUATED, metric
    if metric in ("cpk", "ppk"):
        return (PASS if value > config.cpk_threshold else FAIL), metric
    if metric == "ndc":
        return (PASS if value >= config.ndc_min else FAIL), metric
    return percentage_status(value, config), metric
