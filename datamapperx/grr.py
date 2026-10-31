"""Pre-export GRR for a balanced, single-factor study: serial numbers and repeated measurements.

This is the one-way random-effects ANOVA model, without an operator term. Repeatability is
MS(within), and part variance is max((MS(between) - MS(within)) / repeats, 0). Negative part
variance is set to zero; it is not pooled into repeatability. Study variation uses 6 SD.

Metric definitions: https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/
measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/methods-and-formulas/gage-r-r-table/
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .models import LogRecord, Measurement
from .statistics.numeric import ndc_from_variances
from .utils import to_number

PASS = "PASS"
CAUTION = "CAUTION"
FAIL = "FAIL"
NOT_EVALUATED = "NOT EVALUATED"


def grr_status(value: float | None) -> str:
    """Grade the unrounded percentage. Exactly 10 is PASS and exactly 30 is CAUTION."""
    if value is None or not math.isfinite(value) or value < 0:
        return NOT_EVALUATED
    if value <= 10:
        return PASS
    return CAUTION if value <= 30 else FAIL


@dataclass(frozen=True, slots=True)
class GrrResult:
    component: str
    study_var: float | None
    percent_study_var: float | None
    percent_tolerance: float | None
    study_status: str
    tolerance_status: str
    note: str
    parts: int
    repeats: int | None
    unit: str = ""
    ndc: int | None = None
    ndc_status: str = NOT_EVALUATED


def _result(
    component: str,
    parts: int,
    repeats: int | None,
    *,
    study_var: float | None = None,
    percent_study_var: float | None = None,
    percent_tolerance: float | None = None,
    note: str = "",
    unit: str = "",
    ndc: int | None = None,
) -> GrrResult:
    return GrrResult(
        component, study_var, percent_study_var, percent_tolerance,
        grr_status(percent_study_var), grr_status(percent_tolerance), note, parts, repeats, unit,
        ndc, NOT_EVALUATED if ndc is None else PASS if ndc >= 5 else FAIL,
    )


def _tolerance(entries: Sequence[Measurement]) -> tuple[float | None, str]:
    bounds: set[tuple[float, float]] = set()
    for entry in entries:
        low, high = to_number(entry.min_value), to_number(entry.max_value)
        if low is None or high is None:
            return None, "SV/Toler needs finite lower and upper limits in every file."
        if high <= low:
            return None, "SV/Toler needs an upper limit greater than the lower limit."
        bounds.add((low, high))
    if len(bounds) != 1:
        return None, "SV/Toler is unavailable because specification limits differ between files."
    low, high = next(iter(bounds))
    tolerance = high - low
    if not math.isfinite(tolerance):
        return None, "The specification range is too large to calculate SV/Toler."
    return tolerance, ""


def _anova(values: Sequence[Sequence[float]]) -> tuple[float | None, float | None, int | None, str]:
    """Return Study Var, %Study Var and NDC without squaring large measurement offsets."""
    origin = values[0][0]
    shifted = [[value - origin for value in part] for part in values]
    scale = max(abs(value) for part in shifted for value in part)
    if not math.isfinite(scale):
        return None, None, None, "The measurement range is too large to calculate GRR."
    if scale == 0:
        return 0.0, None, None, "%Study Var is unavailable because total variation is zero. NDC is unavailable because repeatability is zero."

    normalized = [[value / scale for value in part] for part in shifted]
    parts, repeats = len(normalized), len(normalized[0])
    means = [math.fsum(part) / repeats for part in normalized]
    mean = math.fsum(means) / parts
    within = math.fsum(
        (value - part_mean) ** 2
        for part, part_mean in zip(normalized, means, strict=True)
        for value in part
    ) / (parts * (repeats - 1))
    between = repeats * math.fsum((part_mean - mean) ** 2 for part_mean in means) / (parts - 1)
    part_variance = max((between - within) / repeats, 0.0)
    total_variance = within + part_variance
    percent = 100 * math.sqrt(within / total_variance) if total_variance else None
    ndc, _ = ndc_from_variances(part_variance, within)
    ndc_note = ""
    if ndc is None:
        ndc_note = "NDC is unavailable because repeatability is zero." if within == 0 else "NDC exceeds the supported numeric range."
    study_var = scale * (6 * math.sqrt(within))
    if not math.isfinite(study_var):
        return None, percent, ndc, " ".join(part for part in ("Study Var exceeds the supported numeric range.", ndc_note) if part)
    return study_var, percent, ndc, ndc_note


def summarize_grr(
    grouped: Mapping[str, Sequence[LogRecord]],
    components: Sequence[str],
    expected_repeats: int | None = None,
) -> list[GrrResult]:
    """Evaluate every selected component in order, without dropping any part or measurement.

    At least two SNs and two repeats per SN are required. A missing/non-numeric value or
    inconsistent units makes that component unevaluable. Invalid/inconsistent two-sided
    limits affect only SV/Toler; %Study Var still uses all the measurements.
    """
    parts = len(grouped)
    repeat_counts = {len(records) for records in grouped.values()}
    repeats = next(iter(repeat_counts)) if len(repeat_counts) == 1 else None
    problem = ""
    if parts < 2:
        problem = "GRR needs at least two serial numbers."
    elif repeats is None:
        problem = "GRR needs the same number of repeated files for every serial number."
    elif repeats < 2:
        problem = "GRR needs at least two repeated files per serial number."
    elif expected_repeats is not None and repeats != expected_repeats:
        problem = f"Each serial number needs {expected_repeats} repeated files; found {repeats}."
    if problem:
        return [_result(component, parts, repeats, note=problem) for component in components]

    results: list[GrrResult] = []
    for component in components:
        entries: list[Measurement] = []
        values: list[list[float]] = []
        problem = ""
        for sn, records in grouped.items():
            part_values: list[float] = []
            for record in records:
                entry = record.entries.get(component)
                number = to_number(entry.measured) if entry else None
                if entry is None or number is None:
                    problem = f"Missing or non-numeric measurement: {sn}, {record.filename}."
                    break
                entries.append(entry)
                part_values.append(number)
            if problem:
                break
            values.append(part_values)
        if problem:
            results.append(_result(component, parts, repeats, note=problem))
            continue

        units = {entry.unit.strip() for entry in entries}
        if len(units) != 1:
            results.append(_result(
                component, parts, repeats, note="Units differ between files; GRR cannot combine these measurements.",
            ))
            continue
        unit = next(iter(units))
        study_var, percent_study_var, ndc, anova_note = _anova(values)
        tolerance, tolerance_note = _tolerance(entries)
        percent_tolerance = None
        if study_var is not None and tolerance is not None:
            value = (study_var / tolerance) * 100
            if math.isfinite(value):
                percent_tolerance = value
            else:
                tolerance_note = "SV/Toler exceeds the supported numeric range."
        note = " ".join(part for part in (anova_note, tolerance_note) if part)
        results.append(_result(
            component, parts, repeats, study_var=study_var, percent_study_var=percent_study_var,
            percent_tolerance=percent_tolerance, note=note, unit=unit, ndc=ndc,
        ))
    return results
