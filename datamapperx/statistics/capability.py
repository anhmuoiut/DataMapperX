"""Normal process capability: MR(2) for individuals or pooled subgroup SD."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from .models import MR_D2, AnalysisConfig, Issue, Observation
from .numeric import c4, finite, scaled_data, square


def capability_calculation(
    rows: Sequence[Observation], values: Sequence[float], low: float | None, high: float | None,
    config: AnalysisConfig,
) -> tuple[dict, dict, list[Issue]]:
    metrics = dict.fromkeys(("sigma_within", "sigma_overall", "cp", "cpk", "pp", "ppk"))
    details: dict = {"within_method": config.within_method, "moving_range_length": 2,
                     "d2": MR_D2, "overall_unbiasing": False}
    issues = []
    if len(values) < 2:
        return metrics, details, [Issue("error", "Capability needs at least two measurements.")]
    data = scaled_data(values)
    ss_scaled = math.fsum((value - data.mean_scaled) ** 2 for value in data.values)
    overall = data.scale * math.sqrt(ss_scaled / (len(values) - 1))
    overall_underflow = overall == 0 and ss_scaled > 0
    if overall_underflow:
        issues.append(Issue("warning", "Nonzero overall sigma is below the floating-point range and is N/A."))
        overall = None
    metrics["sigma_overall"] = finite(overall) if overall is not None else None
    details.update({"ss_overall": square(data.scale * math.sqrt(ss_scaled)), "overall_df": len(values) - 1,
                    "mean": data.mean, "scale": data.scale, "origin": data.origin})
    if len(values) < 30:
        issues.append(Issue("warning", "Small sample (N < 30): capability estimates can be imprecise; verify stability and normality."))
    within = None
    if config.within_method == "individuals":
        normalized_ranges = [abs(right - left) for left, right in zip(data.values[:-1], data.values[1:], strict=True)]
        mr_bar = data.scale * (math.fsum(normalized_ranges) / len(normalized_ranges))
        within = mr_bar / MR_D2
        if within == 0 and any(normalized_ranges):
            within = None
            issues.append(Issue("warning", "Nonzero within sigma is below the floating-point range and is N/A."))
        details.update({"moving_ranges": tuple(data.scale * value for value in normalized_ranges), "mr_bar": mr_bar})
        issues.append(Issue("info", "MR(2) uses the supplied observation order within each system. Confirm this is the collection order."))
    else:
        groups: dict[str, list[float]] = defaultdict(list)
        for row, value in zip(rows, data.values, strict=True):
            groups[str(row.subgroup).strip()].append(value)
        if "" in groups:
            issues.append(Issue("error", "Pooled within sigma requires a mapped subgroup ID for every measurement."))
        elif any(len(group) < 2 for group in groups.values()):
            issues.append(Issue("error", "Every pooled subgroup needs at least two measurements; singleton subgroups are unsupported."))
        else:
            subgroup_means = {name: math.fsum(group) / len(group) for name, group in groups.items()}
            within_df = sum(len(group) - 1 for group in groups.values())
            ss_within_scaled = math.fsum((value - subgroup_means[name]) ** 2
                                       for name, group in groups.items() for value in group)
            correction = c4(within_df + 1) if config.use_unbiasing else 1.0
            pooled = data.scale * math.sqrt(ss_within_scaled / within_df)
            within = pooled / correction
            if within == 0 and ss_within_scaled > 0:
                within = None
                issues.append(Issue("warning", "Nonzero within sigma is below the floating-point range and is N/A."))
            details.update({"within_df": within_df, "c4": correction, "pooled_s": pooled,
                            "ss_within": square(data.scale * math.sqrt(ss_within_scaled)),
                            "subgroup_sizes": {name: len(group) for name, group in groups.items()}})
    metrics["sigma_within"] = finite(within) if within is not None else None
    for sigma, potential, centered in ((within, "cp", "cpk"), (overall, "pp", "ppk")):
        if sigma is None:
            continue
        if not math.isfinite(sigma) or sigma <= 0:
            issues.append(Issue("warning", f"{potential}/{centered} are N/A: the corresponding sigma is zero or outside the numeric range."))
            continue
        if low is not None and high is not None:
            metrics[potential] = finite((high - low) / sigma / 6)
        sides = []
        if high is not None:
            sides.append((high - data.mean) / sigma / 3)
        if low is not None:
            sides.append((data.mean - low) / sigma / 3)
        metrics[centered] = finite(min(sides)) if sides else None
        if sides and metrics[centered] is None:
            issues.append(Issue("warning", f"{centered} exceeds the numeric range and is N/A."))
    if (low is None) != (high is None):
        issues.append(Issue("info", "One-sided specification: Cpk/Ppk use the available side; Cp/Pp are N/A."))
    return metrics, details, issues
