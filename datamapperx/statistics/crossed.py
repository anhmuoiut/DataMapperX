"""Balanced crossed Gage R&R: Sample ID x Operator random-effects ANOVA (Minitab's ANOVA method)."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from .grr import control_chart_details
from .models import GRR_METRICS, NDC_FACTOR, AnalysisConfig, Issue, Observation
from .numeric import f_survival, finite, scaled_data, square


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator > 0:
        return numerator / denominator
    return math.inf if numerator > 0 else None


def _p_value(f_value: float | None, df1: int, df2: int) -> float | None:
    return f_survival(f_value, df1, df2) if f_value is not None else None


def crossed_grr_calculation(
    rows: Sequence[Observation], values: Sequence[float], low: float | None, high: float | None,
    config: AnalysisConfig,
) -> tuple[dict, dict, list[Issue]]:
    metrics = dict.fromkeys(GRR_METRICS)
    samples = list(dict.fromkeys(str(row.sample_id).strip() for row in rows))
    operators = list(dict.fromkeys(str(row.operator).strip() for row in rows))
    details: dict = {"model": "Balanced crossed random-effects ANOVA (Sample ID x Operator), Minitab ANOVA method",
                     "crossed": True, "operators": tuple(operators), "study_factor": config.study_factor,
                     "ndc_factor": NDC_FACTOR, "interaction_alpha": config.interaction_alpha}
    issues = [Issue("info", f"Crossed Gage R&R with {len(operators)} operators ({', '.join(operators)}): repeatability, "
                            "operator reproducibility and the Sample x Operator interaction are estimated.")]
    cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    trials: dict[tuple[str, str], set[str]] = defaultdict(set)
    missing_trials = False
    for index, row in enumerate(rows):
        cell = (str(row.sample_id).strip(), str(row.operator).strip())
        cells[cell].append(index)
        trial = str(row.trial).strip()
        if not trial:
            missing_trials = True
        elif trial in trials[cell]:
            issues.append(Issue("error", f"Duplicate measurement identity: sample {cell[0]}, operator {cell[1]}, trial {trial}."))
        trials[cell].add(trial)
    if missing_trials:
        issues.append(Issue("error", "Trial/repetition is missing. Map Trial or explicitly assign repetition order."
                            if not config.assign_trials else
                            "Partially mapped Trial cannot be mixed with assigned order. Map every trial or clear Trial and assign all."))
    if len(samples) < 2:
        issues.append(Issue("error", "Crossed ANOVA needs at least two distinct Sample IDs."))
    absent = [f"{sample}/{operator}" for sample in samples for operator in operators if (sample, operator) not in cells]
    if absent:
        issues.append(Issue("error", "Not a crossed design: every operator must measure every Sample ID. Missing sample/operator: "
                            + ", ".join(absent[:8]) + (" ..." if len(absent) > 8 else "")
                            + ". To analyze operators separately, map them to Slot or Tester instead of Operator."))
    counts = {cell: len(indices) for cell, indices in cells.items()}
    details["repetition_counts"] = {f"{sample}/{operator}": count for (sample, operator), count in counts.items()}
    if not absent and len(set(counts.values())) != 1:
        issues.append(Issue("error", "Unbalanced crossed study is unsupported by this ANOVA model: "
                            + ", ".join(f"{sample}/{operator}: {count} trials" for (sample, operator), count in counts.items()) + "."))
    repeats = next(iter(counts.values()), 0)
    if repeats < 2:
        issues.append(Issue("error", "Each sample needs at least two repetitions per operator."))
    # "Files per sample" is either the repetitions per operator or the total for all operators.
    if (config.expected_repeats is not None and not absent and len(set(counts.values())) == 1
            and config.expected_repeats not in (repeats, repeats * len(operators))):
        issues.append(Issue("error", f"Each sample has {repeats} trials per operator ({repeats * len(operators)} in total) "
                                     f"instead of {config.expected_repeats}."))
    if any(issue.severity == "error" for issue in issues):
        return metrics, details, issues

    data = scaled_data(values)
    p, o, r = len(samples), len(operators), repeats
    cell_values = {cell: [data.values[i] for i in indices] for cell, indices in cells.items()}
    cell_mean = {cell: math.fsum(group) / r for cell, group in cell_values.items()}
    sample_mean = {s: math.fsum(cell_mean[(s, op)] for op in operators) / o for s in samples}
    operator_mean = {op: math.fsum(cell_mean[(s, op)] for s in samples) / p for op in operators}
    grand = data.mean_scaled
    ss_part = o * r * math.fsum((m - grand) ** 2 for m in sample_mean.values())
    ss_op = p * r * math.fsum((m - grand) ** 2 for m in operator_mean.values())
    ss_int = r * math.fsum((cell_mean[(s, op)] - sample_mean[s] - operator_mean[op] + grand) ** 2
                           for s in samples for op in operators)
    ss_err = math.fsum((x - cell_mean[cell]) ** 2 for cell, group in cell_values.items() for x in group)
    df_part, df_op, df_int, df_err = p - 1, o - 1, (p - 1) * (o - 1), p * o * (r - 1)
    ms_part, ms_op, ms_int, ms_err = ss_part / df_part, ss_op / df_op, ss_int / df_int, ss_err / df_err

    f_int = _ratio(ms_int, ms_err)
    p_int = _p_value(f_int, df_int, df_err)
    removed = p_int is None or p_int >= config.interaction_alpha
    if removed:
        # Reduced model: the interaction sum of squares joins the error term.
        df_error = df_int + df_err
        ms_error = (ss_int + ss_err) / df_error
        denominator = ms_error
        var_int = 0.0
    else:
        df_error, ms_error = df_err, ms_err
        # Operator and part effects are tested against the interaction.
        denominator = ms_int
        var_int = max((ms_int - ms_err) / r, 0.0)
    var_op = max((ms_op - denominator) / (p * r), 0.0)
    var_part = max((ms_part - denominator) / (o * r), 0.0)
    truncated = [name for name, mean_square in (("operator", ms_op), ("part", ms_part)) if mean_square < denominator]
    var_repro = var_op + var_int
    var_grr = ms_error + var_repro
    var_total = var_grr + var_part

    def sigma(variance: float) -> tuple[float | None, bool]:
        value = data.scale * math.sqrt(variance)
        return (None, True) if value == 0 and variance > 0 else (finite(value), False)

    sig_repeat, u1 = sigma(ms_error)
    sig_repro, u2 = sigma(var_repro)
    sig_grr, u3 = sigma(var_grr)
    sig_part, u4 = sigma(var_part)
    sig_total, u5 = sigma(var_total)
    if any((u1, u2, u3, u4, u5)):
        issues.append(Issue("warning", "A nonzero standard deviation is below the floating-point range and is N/A; it was not treated as zero."))

    def variance_of(value: float | None) -> float | None:
        return None if value is None else square(value)

    study_var = None if sig_grr is None else finite(config.study_factor * sig_grr)
    metrics.update({
        "sigma_grr": sig_grr, "sigma_repeatability": sig_repeat, "sigma_reproducibility": sig_repro,
        "sigma_part": sig_part, "sigma_total": sig_total,
        "variance_repeatability": variance_of(sig_repeat), "variance_reproducibility": variance_of(sig_repro),
        "variance_grr": variance_of(sig_grr), "variance_part": variance_of(sig_part), "variance_total": variance_of(sig_total),
        "study_var": study_var,
        "percent_study_var": 100 * math.sqrt(var_grr / var_total) if var_total else None})
    if low is not None and high is not None and study_var is not None:
        metrics["percent_tolerance"] = finite(study_var / (high - low) * 100)
    else:
        issues.append(Issue("warning", "%SV/Tol requires consistent, finite two-sided limits with USL > LSL."))
    if var_grr > 0:
        raw_ndc = finite(NDC_FACTOR * math.sqrt(var_part / var_grr))
        metrics["ndc"] = max(1, math.floor(raw_ndc)) if raw_ndc is not None else None
        details["ndc_raw"] = raw_ndc
    else:
        details["ndc_raw"] = None
        issues.append(Issue("warning", "Cannot estimate NDC: Gage R&R sigma is zero (division by zero); NDC is N/A."))
    if var_total == 0:
        issues.append(Issue("warning", "%Study Var is N/A because total variation is zero."))
    if truncated:
        issues.append(Issue("warning", f"Negative {' and '.join(truncated)} variance estimate truncated to zero; other components were not changed."))
    if removed:
        shown = "undefined" if p_int is None else f"{p_int:.4g}"
        issues.append(Issue("info", f"Sample x Operator interaction removed (p = {shown} >= {config.interaction_alpha:g}); "
                                    "its variation is pooled into repeatability."))
    else:
        issues.append(Issue("info", f"Sample x Operator interaction retained (p = {p_int:.4g} < {config.interaction_alpha:g})."))

    def rescale(ss: float) -> float | None:
        return square(data.scale * math.sqrt(ss))

    def row(source, ss, df, ms, f=None, p_value=None):
        return {"source": source, "ss": None if ss is None else rescale(ss), "df": df,
                "ms": None if ms is None else rescale(ms), "f": finite(f) if f is not None else None, "p": p_value}

    f_part_full, f_op_full = _ratio(ms_part, ms_int), _ratio(ms_op, ms_int)
    full = (row("Sample ID", ss_part, df_part, ms_part, f_part_full, _p_value(f_part_full, df_part, df_int)),
            row("Operator", ss_op, df_op, ms_op, f_op_full, _p_value(f_op_full, df_op, df_int)),
            row("Sample ID x Operator", ss_int, df_int, ms_int, f_int, p_int),
            row("Repeatability", ss_err, df_err, ms_err),
            row("Total", ss_part + ss_op + ss_int + ss_err, len(values) - 1, None))
    if removed:
        f_part, f_op = _ratio(ms_part, ms_error), _ratio(ms_op, ms_error)
        anova = (row("Sample ID", ss_part, df_part, ms_part, f_part, _p_value(f_part, df_part, df_error)),
                 row("Operator", ss_op, df_op, ms_op, f_op, _p_value(f_op, df_op, df_error)),
                 row("Repeatability", ss_int + ss_err, df_error, ms_error),
                 full[-1])
    else:
        anova = full
    summaries = tuple({"sample_id": sample, "operator": operator, "n": r,
                       "mean": data.origin + data.scale * cell_mean[(sample, operator)],
                       "range": data.scale * (max(cell_values[(sample, operator)]) - min(cell_values[(sample, operator)])),
                       "values": tuple(values[i] for i in cells[(sample, operator)])}
                      for operator in operators for sample in samples)
    details.update({"anova": anova, "anova_with_interaction": full, "part_summaries": summaries,
                    "interaction_p": p_int, "interaction_removed": removed,
                    "ms_part": rescale(ms_part), "ms_operator": rescale(ms_op), "ms_interaction": rescale(ms_int),
                    "ms_error": rescale(ms_error),
                    "variance_operator": variance_of(sigma(var_op)[0]), "variance_interaction": variance_of(sigma(var_int)[0]),
                    "mean": data.mean, "scale": data.scale, "origin": data.origin})
    r_bar, chart_details, chart_issue = control_chart_details(summaries, data.mean, r)
    details["r_bar"] = r_bar
    details.update(chart_details)
    if chart_issue:
        issues.append(chart_issue)
    return metrics, details, issues
