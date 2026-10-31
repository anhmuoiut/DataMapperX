"""Statistics and evaluation are separate steps; ``analyze`` runs both and keeps the original one-call API.

``compute`` produces statistics from observations and the statistical options only. ``evaluation.evaluate`` then applies
acceptance criteria to those statistics. One result snapshot is consumed unchanged by preview, details, charts and exports.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from .capability import capability_calculation
from .crossed import crossed_grr_calculation
from .evaluation import evaluate_one
from .grr import grr_calculation
from .models import (
    GRR_METRICS,
    AnalysisConfig,
    AnalysisResult,
    Issue,
    Observation,
    StatisticsResult,
    statistical_config,
)
from .numeric import scaled_data
from .study import validate_statistical_options
from .validation import common_validation, validate_config


def _merge_crossed(grouped: dict[tuple, list[Observation]]) -> dict[tuple, list[Observation]]:
    """Operators who measured the same item/tester/slot form one crossed study.

    The merged key carries the tuple of operator names. A group without an operator keeps its own key,
    so a missing identifier is still reported instead of being absorbed into the study.
    """
    systems: dict[tuple, list[tuple]] = defaultdict(list)
    for key in grouped:
        item, tester, operator, slot = key
        if operator:
            systems[(item, tester, slot)].append(key)
    crossed = {system: keys for system, keys in systems.items() if len(keys) > 1}
    merged: dict[tuple, list[Observation]] = {}
    for key, rows in grouped.items():
        item, tester, operator, slot = key
        keys = crossed.get((item, tester, slot)) if operator else None
        if keys is None:
            merged[key] = rows
        elif key == keys[0]:
            merged[(item, tester, tuple(k[2] for k in keys), slot)] = [row for k in keys for row in grouped[k]]
    return merged


def _compute(observations: Sequence[Observation], config: AnalysisConfig) -> list[StatisticsResult]:
    """The statistics. ``config`` is read only for the statistical options; the caller has validated it."""
    grouped: dict[tuple, list[Observation]] = defaultdict(list)
    for row in observations:
        grouped[(str(row.test_item).strip(), str(row.tester).strip(), str(row.operator).strip(), str(row.slot).strip())].append(row)
    if config.method == "grr":
        grouped = _merge_crossed(grouped)
    # A missing system identifier must not become an apparently valid unnamed system.
    metadata_fields = ("tester", "operator", "slot")
    item_metadata: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        item = str(row.test_item).strip()
        item_metadata[item].update(name for name in metadata_fields if str(getattr(row, name)).strip())
    results = []
    for (item, tester, operator, slot), rows in grouped.items():
        crossed = isinstance(operator, tuple)
        operator_label = ("Operators", ", ".join(operator)) if crossed else ("Operator", operator)
        system = " | ".join(f"{name}={value}" for name, value in (("Tester", tester), operator_label, ("Slot", slot)) if value)
        values, low, high, issues = common_validation(rows)
        if config.method == "grr" and config.assign_trials and all(not str(row.trial).strip() for row in rows):
            # Assign identities in the analysis snapshot; retain every original raw observation.
            trial_counts: dict[tuple[str, str], int] = defaultdict(int)
            assigned_rows = []
            for row in rows:
                cell = (str(row.sample_id).strip(), str(row.operator).strip())
                trial_counts[cell] += 1
                assigned_rows.append(replace(row, trial=str(trial_counts[cell])))
            rows = assigned_rows
            issues.append(Issue("warning", "Repetition order explicitly assigned within each sample from supplied logfile order."))
        for name in metadata_fields:
            if name in item_metadata[item] and any(not str(getattr(row, name)).strip() for row in rows):
                issues.append(Issue("error", f"Missing {name} identifier where other measurements for this Test Item have {name} metadata. Resolve the grouping before analysis."))
        if not item:
            issues.append(Issue("error", "Test Item is required."))
        counts: dict[str, int] = defaultdict(int)
        cell_counts: dict[tuple[str, str], int] = defaultdict(int)
        for row in rows:
            counts[str(row.sample_id).strip()] += 1
            cell_counts[(str(row.sample_id).strip(), str(row.operator).strip())] += 1
        # Repetitions are counted per sample, and per operator within a sample for a crossed study.
        tally = cell_counts if crossed else counts
        repeats = next(iter(tally.values())) if len(set(tally.values())) == 1 else None
        metrics: dict = {}
        details: dict = {}
        mean = minimum = maximum = None
        if not any(issue.severity == "error" for issue in issues):
            try:
                if values:
                    mean, minimum, maximum = scaled_data(values).mean, min(values), max(values)
                if config.method == "capability":
                    calculate = capability_calculation
                else:
                    calculate = crossed_grr_calculation if crossed else grr_calculation
                metrics, details, extra = calculate(rows, values, low, high, config)
                issues.extend(extra)
            except (ArithmeticError, ValueError) as exc:
                issues.append(Issue("error", f"Analysis could not be estimated: {exc}"))
        expected_metrics = ("sigma_within", "sigma_overall", "cp", "cpk", "pp", "ppk") if config.method == "capability" else GRR_METRICS
        for key in expected_metrics:
            metrics.setdefault(key, None)
        facts = {"sample_count": len(counts), "measurement_count": len(rows), "valid_numeric_count": len(values),
                 "lsl": low, "usl": high, "trial_assignment": config.assign_trials, "crossed": crossed}
        # Preserve issue order but avoid reporting one identical problem repeatedly.
        results.append(StatisticsResult(config.method, item, system, len(rows), len(counts), repeats,
                                        mean, minimum, maximum, low, high, rows[0].unit if rows else "",
                                        metrics, tuple(dict.fromkeys(issues)), details, facts, tuple(rows)))
    return results


def compute(observations: Sequence[Observation], config: AnalysisConfig | None = None) -> list[StatisticsResult]:
    """Statistics only. Acceptance criteria, thresholds and display options in ``config`` play no part."""
    config = config or AnalysisConfig()
    validate_statistical_options(config)
    return _compute(observations, statistical_config(config))


def analyze(observations: Sequence[Observation], config: AnalysisConfig | None = None) -> list[AnalysisResult]:
    """Statistics and evaluation in one call, as before the two steps were separated."""
    config = config or AnalysisConfig()
    validate_config(config)
    return [evaluate_one(stat, config) for stat in _compute(observations, statistical_config(config))]
