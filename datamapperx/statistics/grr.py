"""Balanced, one-system random-effects one-way ANOVA for repeated measurements."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from .models import GRR_METRICS, NDC_FACTOR, AnalysisConfig, Issue, Observation
from .numeric import f_survival, finite, ndc_from_variances, scaled_data, square

# Minitab's unbiasing table, rounded to the documented precision. R and Xbar
# chart limits use Rbar/d2, separately from ANOVA's repeatability SD.
R_CONSTANTS = {2: (1.128, .8525), 3: (1.693, .8884), 4: (2.059, .8798),
               5: (2.326, .8641), 6: (2.534, .8480), 7: (2.704, .8332), 8: (2.847, .8198)}


def control_chart_details(summaries: Sequence[dict], grand_mean: float, repeats: int) -> tuple[float, dict, Issue | None]:
    """Rbar and the R/Xbar limits shared by the one-way and crossed studies."""
    r_bar = math.fsum(row["range"] for row in summaries) / len(summaries)
    if repeats not in R_CONSTANTS:
        return r_bar, {}, Issue("warning", "R/Xbar control limits supported for 2-8 repetitions; charts retain points without control limits for this design.")
    d2, d3 = R_CONSTANTS[repeats]
    sigma_chart = r_bar / d2
    half_width = 3 * sigma_chart / math.sqrt(repeats)
    return r_bar, {"r_limits": {"lcl": max(0., r_bar - 3 * sigma_chart * d3), "center": r_bar, "ucl": r_bar + 3 * sigma_chart * d3},
                   "xbar_limits": {"lcl": grand_mean - half_width, "center": grand_mean, "ucl": grand_mean + half_width},
                   "chart_sigma": sigma_chart, "chart_d2": d2, "chart_d3": d3}, None


def grr_calculation(
    rows: Sequence[Observation], values: Sequence[float], low: float | None, high: float | None,
    config: AnalysisConfig,
) -> tuple[dict, dict, list[Issue]]:
    metrics = dict.fromkeys(GRR_METRICS)
    details: dict = {"model": "Balanced one-way random-effects ANOVA by Sample ID; single system",
                     "study_factor": config.study_factor, "ndc_factor": NDC_FACTOR,
                     "reproducibility": "Not independently estimable in a single-system study"}
    issues = [Issue("info", "Repeatability-only study for this tester/operator/slot. Between-appraiser reproducibility is not estimated.")]
    groups: dict[str, list[int]] = defaultdict(list)
    trials: dict[str, set[str]] = defaultdict(set)
    missing_trials = False
    for index, row in enumerate(rows):
        sample_id = str(row.sample_id).strip()
        groups[sample_id].append(index)
        trial = str(row.trial).strip()
        if not trial:
            missing_trials = True
        elif trial in trials[sample_id]:
            issues.append(Issue("error", f"Duplicate measurement identity: sample {row.sample_id}, trial {trial}."))
        trials[sample_id].add(trial)
    if missing_trials:
        if not config.assign_trials:
            issues.append(Issue("error", "Trial/repetition is missing. Map Trial or explicitly assign repetition order."))
        elif any(str(row.trial).strip() for row in rows):
            issues.append(Issue("error", "Partially mapped Trial cannot be mixed with assigned order. Map every trial or clear Trial and assign all."))
        else:
            issues.append(Issue("warning", "Repetition order explicitly assigned within each sample from supplied logfile order."))
    counts = {name: len(indices) for name, indices in groups.items()}
    details["repetition_counts"] = counts
    if len(groups) < 2:
        issues.append(Issue("error", "One-way ANOVA needs at least two distinct Sample IDs."))
    if len(set(counts.values())) != 1:
        issues.append(Issue("error", "Unbalanced study is unsupported by this ANOVA model: "
                            + ", ".join(f"{name}: {count} trials" for name, count in counts.items()) + "."))
    repeats = next(iter(counts.values()), 0)
    if repeats < 2:
        issues.append(Issue("error", "Each sample needs at least two repetitions."))
    if config.expected_repeats is not None:
        for name, count in counts.items():
            if count != config.expected_repeats:
                issues.append(Issue("error", f"Sample {name} has {count} trials instead of {config.expected_repeats}."))
    if any(issue.severity == "error" for issue in issues):
        return metrics, details, issues
    data = scaled_data(values)
    part_values = {name: [data.values[index] for index in indices] for name, indices in groups.items()}
    means = {name: math.fsum(group) / repeats for name, group in part_values.items()}
    ss_error_norm = math.fsum((value - means[name]) ** 2 for name, group in part_values.items() for value in group)
    ss_part_norm = repeats * math.fsum((mean - data.mean_scaled) ** 2 for mean in means.values())
    df_part, df_error = len(groups) - 1, len(groups) * (repeats - 1)
    ms_error_norm, ms_part_norm = ss_error_norm / df_error, ss_part_norm / df_part
    var_part_norm = max((ms_part_norm - ms_error_norm) / repeats, 0.0)
    var_total_norm = ms_error_norm + var_part_norm
    grr = data.scale * math.sqrt(ms_error_norm)
    part = data.scale * math.sqrt(var_part_norm)
    total = data.scale * math.sqrt(var_total_norm)
    grr_underflow = grr == 0 and ms_error_norm > 0
    part_underflow = part == 0 and var_part_norm > 0
    total_underflow = total == 0 and var_total_norm > 0
    study_var = None if grr_underflow else finite(config.study_factor * grr)
    if grr_underflow or part_underflow or total_underflow:
        issues.append(Issue("warning", "A nonzero standard deviation is below the floating-point range and is N/A; it was not treated as zero."))
    metrics.update({"sigma_grr": None if grr_underflow else finite(grr), "sigma_part": None if part_underflow else finite(part), "sigma_total": None if total_underflow else finite(total),
                    "sigma_repeatability": None if grr_underflow else finite(grr),
                    "variance_repeatability": None if grr_underflow else square(grr),
                    "variance_grr": None if grr_underflow else square(grr), "variance_part": None if part_underflow else square(part),
                    "variance_total": None if total_underflow else square(total), "study_var": study_var,
                    "percent_study_var": 100 * math.sqrt(ms_error_norm / var_total_norm) if var_total_norm else None})
    if low is not None and high is not None and study_var is not None:
        metrics["percent_tolerance"] = finite(study_var / (high - low) * 100)
    else:
        issues.append(Issue("warning", "%SV/Tol requires consistent, finite two-sided limits with USL > LSL."))
    if ms_error_norm > 0:
        metrics["ndc"], details["ndc_raw"] = ndc_from_variances(var_part_norm, ms_error_norm)
    else:
        details["ndc_raw"] = None
        issues.append(Issue("warning", "Cannot estimate NDC: repeatability sigma is zero (division by zero); NDC is N/A."))
    if var_total_norm == 0:
        issues.append(Issue("warning", "%Study Var is N/A because total variation is zero."))
    if ms_part_norm < ms_error_norm:
        issues.append(Issue("warning", "Negative part-to-part variance estimate truncated to zero; repeatability was not pooled or changed."))
    if any(metrics[key] is None for key in ("variance_repeatability", "variance_part", "variance_total")):
        issues.append(Issue("warning", "A variance is outside the numeric range; its SD is retained where representable."))
    f_value = ms_part_norm / ms_error_norm if ms_error_norm else None
    p_value = f_survival(f_value, df_part, df_error) if f_value is not None else None
    def rescale_ss(ss: float) -> float | None:
        return square(data.scale * math.sqrt(ss))
    anova = (
        {"source": "Sample ID", "ss": rescale_ss(ss_part_norm), "df": df_part,
         "ms": rescale_ss(ms_part_norm), "f": finite(f_value) if f_value is not None else None, "p": p_value},
        {"source": "Repeatability", "ss": rescale_ss(ss_error_norm), "df": df_error,
         "ms": rescale_ss(ms_error_norm), "f": None, "p": None},
        {"source": "Total", "ss": rescale_ss(ss_part_norm + ss_error_norm), "df": len(values) - 1,
         "ms": None, "f": None, "p": None},
    )
    summaries = tuple({"sample_id": name, "n": repeats, "mean": data.origin + data.scale * means[name],
                       "range": data.scale * (max(group) - min(group)),
                       "values": tuple(values[index] for index in groups[name])}
                      for name, group in part_values.items())
    details.update({"anova": anova, "part_summaries": summaries,
                    "ms_part": rescale_ss(ms_part_norm), "ms_error": rescale_ss(ms_error_norm),
                    "part_variance_untruncated": finite((ms_part_norm - ms_error_norm) / repeats * data.scale * data.scale),
                    "mean": data.mean, "scale": data.scale, "origin": data.origin})
    r_bar, chart_details, chart_issue = control_chart_details(summaries, data.mean, repeats)
    details["r_bar"] = r_bar
    details.update(chart_details)
    if chart_issue:
        issues.append(chart_issue)
    return metrics, details, issues
