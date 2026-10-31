"""Dataset validation shared by capability and the balanced one-way ANOVA model."""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from ..utils import to_number
from .models import CRITERION_METRICS, AnalysisConfig, Criterion, Issue, Observation


def validate_criteria(criteria: Sequence[Criterion]) -> None:
    if not criteria or any(not isinstance(c, Criterion) or c.metric not in CRITERION_METRICS for c in criteria):
        raise ValueError("Each criterion must be %SV/Tol, %Study Var or NDC.")
    names = [c.metric for c in criteria]
    if len(set(names)) != len(names):
        raise ValueError("Each metric may appear only once in a customer's criteria.")
    if not any(c.enabled for c in criteria):
        raise ValueError("Apply at least one metric.")
    for c in criteria:
        for name in ("pass_limit", "fail_limit"):
            value = getattr(c, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{c.metric}: {name} must be positive and finite.")
        if c.metric == "ndc" and c.fail_limit > c.pass_limit:
            raise ValueError("NDC: the FAIL limit cannot be above the PASS limit.")
        if c.metric != "ndc" and c.pass_limit > c.fail_limit:
            raise ValueError(f"{c.metric}: the PASS limit cannot be above the FAIL limit.")


def validate_config(config: AnalysisConfig) -> None:
    if config.method not in {"capability", "grr"}:
        raise ValueError("Select capability or grr; attribute studies are unsupported.")
    if config.within_method not in {"individuals", "pooled"}:
        raise ValueError("Within sigma method must be individuals or pooled.")
    for name in ("cpk_threshold", "percent_pass", "percent_fail", "study_factor"):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")
    if config.criteria is not None:
        validate_criteria(config.criteria)
    alpha = config.interaction_alpha
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise ValueError("interaction_alpha must be greater than 0 and less than 1.")
    if config.percent_fail < config.percent_pass:
        raise ValueError("The conditional upper boundary must be at least the pass boundary.")
    allowed = {"percent_tolerance", "percent_study_var", "ndc"} | ({"cpk", "ppk"} if config.method == "capability" else set())
    if config.decision_metric not in allowed:
        raise ValueError("Select one supported GRR acceptance metric.")
    if not isinstance(config.ndc_min, int) or isinstance(config.ndc_min, bool) or config.ndc_min < 1:
        raise ValueError("NDC minimum must be a positive integer.")
    if config.expected_repeats is not None and (
        not isinstance(config.expected_repeats, int) or isinstance(config.expected_repeats, bool)
        or config.expected_repeats < 2
    ):
        raise ValueError("Expected repetitions must be an integer of at least two.")
    if isinstance(config.precision, bool) or not isinstance(config.precision, int) or not 0 <= config.precision <= 10:
        raise ValueError("Display precision must be an integer from 0 to 10.")


def common_validation(rows: Sequence[Observation]) -> tuple[list[float], float | None, float | None, list[Issue]]:
    issues: list[Issue] = []
    values = []
    for row in rows:
        if not str(row.sample_id).strip():
            issues.append(Issue("error", f"Missing Sample ID in {row.source or 'a measurement'}."))
        value = to_number(row.value)
        if value is None:
            issues.append(Issue("error", f"Missing or invalid numeric measurement: {row.sample_id}, {row.source or row.trial}."))
        else:
            values.append(value)
    sources = Counter(row.source for row in rows if row.source)
    if any(count > 1 for count in sources.values()):
        issues.append(Issue("error", "Duplicate source measurement: the same logfile occurs more than once in this test/system."))
    if len({row.unit.strip() for row in rows}) > 1:
        issues.append(Issue("error", "Conflicting units; measurements cannot be combined without explicit unit conversion."))
    limits = []
    bad_limit = False
    for name in ("lsl", "usl"):
        raw = [getattr(row, name) for row in rows]
        missing = [value is None or str(value).strip() == "" for value in raw]
        numbers = [to_number(value) for value in raw]
        if any(not absent and number is None for absent, number in zip(missing, numbers, strict=True)):
            issues.append(Issue("warning", f"Invalid {name.upper()}; specification-dependent indices are N/A."))
            bad_limit = True
        present = {number for number in numbers if number is not None}
        if len(present) > 1 or (present and any(missing)):
            issues.append(Issue("warning", f"Conflicting or partially missing {name.upper()} limits for this Test Item; specification-dependent indices are N/A."))
            bad_limit = True
        limits.append(next(iter(present)) if len(present) == 1 and not any(missing) else None)
    low, high = limits
    if low is not None and high is not None and (high <= low or not math.isfinite(high - low)):
        issues.append(Issue("warning", "Invalid specification limits: USL must exceed LSL with a finite tolerance."))
        bad_limit = True
    if bad_limit:
        low = high = None
    if low is None and high is None and not bad_limit:
        issues.append(Issue("warning", "Missing LSL/USL; specification-dependent indices are N/A."))
    return values, low, high, issues
