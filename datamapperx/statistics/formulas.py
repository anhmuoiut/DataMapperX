"""Formula documentation drawn from the same constants and settings as the engine."""
from __future__ import annotations

import math

from .acceptance import decision_metric, describe_criteria, metric_label
from .models import MR_D2, NDC_FACTOR, AnalysisConfig, AnalysisResult

METRIC_LABELS = {"percent_tolerance": "%SV/Tol", "percent_study_var": "%Study Var", "ndc": "NDC", "cpk": "Cpk"}


def _formula_sections(config: AnalysisConfig) -> tuple[tuple[str, str], ...]:
    if config.method == "capability":
        within = (f"Individuals in supplied collection order: MR_i = |x_i - x_(i-1)|; "
                  f"MRbar = sum(MR_i)/(N-1); sigma_within = MRbar/{MR_D2}. Moving range length = 2."
                  if config.within_method == "individuals" else
                  "Mapped subgroups: df = sum(n_g - 1); SS_within = sum_g sum_j (x_gj - mean_g)^2; "
                  "Sp = sqrt(SS_within/df); " + ("sigma_within = Sp/c4(df+1). " if config.use_unbiasing else "sigma_within = Sp (unbiasing disabled). ")
                  + "c4(k) = sqrt(2/(k-1)) * Gamma(k/2)/Gamma((k-1)/2). Subgroups may differ in size; each needs n_g >= 2.")
        return (
            ("Purpose", "Cp measures the tolerance width relative to short-term variation; Cpk also accounts for off-center measurements. Pp/Ppk use overall variation and can differ from Cp/Cpk."),
            ("Required input", "Test Item, Sample ID, numeric measurement, and consistent LSL and/or USL. Pooled analysis also needs a subgroup ID. Tester, operator and slot are kept separate. Two observations minimum; larger representative samples improve precision."),
            ("Formulas used", "mean = sum(x_i)/N; sigma_overall = sqrt(sum((x_i - mean)^2)/(N-1)) (sample SD, no c4 correction).\n" + within + "\nCp = (USL-LSL)/(6*sigma_within); Cpk = min((USL-mean)/(3*sigma_within), (mean-LSL)/(3*sigma_within)).\nPp = (USL-LSL)/(6*sigma_overall); Ppk = min((USL-mean)/(3*sigma_overall), (mean-LSL)/(3*sigma_overall)). One-sided limits use the available side for Cpk/Ppk; Cp/Pp are N/A."),
            ("Variables", "x_i: observation i; N: measurement count; g: subgroup; n_g: subgroup size; mean_g: subgroup mean; df: within degrees of freedom; SS: sum of squares; Sp: pooled SD; Gamma: gamma function; MR: moving range; sigma: estimated standard deviation; LSL/USL: lower/upper specification limits."),
            ("Calculation steps", "1. Check identities, numeric values, units and limits. 2. Partition tester/operator/slot. 3. Calculate mean, min and max. 4. Calculate within sigma using the selected method above. 5. Calculate sample overall SD. 6. Calculate each defined index at full precision. 7. Apply the selected Cpk threshold. Round only for display."),
            ("Acceptance", f"PASS only when unrounded {metric_label(decision_metric(config))} > {config.cpk_threshold:g}; otherwise FAIL. Undefined {metric_label(decision_metric(config))} gives N/A, never a fabricated pass."),
            ("Worked example", "Individuals [1,2,3,4,5], LSL=0, USL=6: N=5, mean=3, min=1, max=5; MRbar=1; sigma_within=1/1.128=0.886524823; sigma_overall=sqrt(10/4)=1.581138830; Cp=Cpk=1.128; Pp=Ppk=0.632455532.\nPooled example: subgroups [1,2,3], [4,5,6], [7,8,9], limits0..20: mean=5, SS_within=6, df=6; Sp=1; sigma_within=1/c4(7) when unbiasing is on; sigma_overall=sqrt(60/8)."),
            ("Assumptions and limitations", "Normal-distribution capability assumes a stable, representative process and independent observations. Moving ranges depend on collection order. Repeated readings of the same part can overstate process capability unless subgrouping matches the study design. Zero sigma produces N/A indices. Missing/invalid values are never silently discarded. No automatic normality test, transformation, confidence interval or nonnormal capability model is provided. Results are statistical estimates subject to model, data quality and assumptions."),
        )
    metric = decision_metric(config)
    if config.criteria is not None:
        acceptance_text = (
            f"Customer: {config.profile}. {describe_criteria(config)} Overall result: any applied metric FAIL gives FAIL; otherwise any "
            "CONDITIONAL PASS gives CONDITIONAL PASS; otherwise PASS. An applied metric that cannot be evaluated gives N/A unless another "
            "applied metric already fails. Metrics that are not applied are informational: when the overall result is PASS or CONDITIONAL "
            "PASS but one of them would FAIL on its own limits, the result is flagged for review; the decision itself is unchanged.")
    else:
        criterion = (f"NDC >= {config.ndc_min}: PASS; otherwise FAIL." if metric == "ndc" else
                     f"{METRIC_LABELS.get(metric, metric)} < {config.percent_pass:g}%: PASS; "
                     f"{config.percent_pass:g}% through {config.percent_fail:g}% inclusive: CONDITIONAL PASS; above {config.percent_fail:g}%: FAIL.")
        acceptance_text = (
            f"Profile: {config.profile}. Decision metric: {METRIC_LABELS.get(metric, metric)}. {criterion} "
            + ("SolarEdge always uses %SV/Tol alone; %Study Var and NDC are informational and cannot override this decision." if config.profile.casefold() == "solaredge" else "All other metrics are informational and do not override the selected criterion.")
            + f" When the decision is PASS or CONDITIONAL PASS but an informational metric would fail on its own (NDC < {config.ndc_min}, or %Study Var / %SV/Tol > {config.percent_fail:g}%), the result is flagged for review; the decision itself is unchanged.")
    return (
        ("Purpose", "Estimate the variation of a measurement system from repeated measurements of identified samples. With one operator (or none mapped) the model is a balanced one-way random-effects ANOVA: repeatability only. When two or more Operators measured the same samples, a crossed two-way ANOVA (Sample ID x Operator) also estimates operator reproducibility and the Sample x Operator interaction, as Minitab's Gage R&R (Crossed) does."),
        ("Required input", "Test Item, Sample ID, numeric measurement and Trial. Map Trial or explicitly assign repetition order. At least two samples and two repeats per sample, with equal repetition counts. Typical design: 10 samples x 3 repetitions (x 3 operators when crossed). In a crossed study every operator must measure every sample the same number of times. Two-sided LSL/USL required for %SV/Tol. Tester and slot combinations are always evaluated separately."),
        ("Formulas used", "mean_i = sum_j(x_ij)/r; mean = sum_i mean_i/p.\nSS_Part = r*sum_i(mean_i-mean)^2; df_Part=p-1; MS_Part=SS_Part/df_Part.\nSS_Error=sum_i sum_j(x_ij-mean_i)^2; df_Error=p*(r-1); MS_Error=SS_Error/df_Error.\nF=MS_Part/MS_Error; p-value=P(F_(df_Part,df_Error) >= F).\nvariance_GRR=MS_Error; variance_Part=max((MS_Part-MS_Error)/r,0); variance_Total=variance_GRR+variance_Part.\nsigma_GRR=sqrt(variance_GRR); sigma_Part=sqrt(variance_Part); sigma_Total=sqrt(variance_Total).\n"
         + f"StudyVar_GRR={config.study_factor:g}*sigma_GRR; %SV/Tol=100*StudyVar_GRR/(USL-LSL); %StudyVar=100*sigma_GRR/sigma_Total.\nNDC_raw={NDC_FACTOR}*sigma_Part/sigma_GRR; NDC=max(1,floor(NDC_raw)). Zero denominator gives N/A.\n"
         + "Rbar=mean of sample ranges; sigma_chart=Rbar/d2(r). R limits: max(0,Rbar-3*d3(r)*sigma_chart), Rbar+3*d3(r)*sigma_chart. Xbar limits: mean +/- 3*sigma_chart/sqrt(r). Chart sigma is separate from ANOVA sigma_GRR; d2/d3 constants implemented for 2..8 repeats.\n"
         + "Crossed model (two or more Operators on the same samples): p samples, o operators, r repetitions. SS_Oper=p*r*sum_j(mean_j-mean)^2; SS_Int=r*sum_ij(mean_ij-mean_i-mean_j+mean)^2; SS_Error=sum_ijk(x_ijk-mean_ij)^2; df = p-1, o-1, (p-1)*(o-1), p*o*(r-1).\n"
         + f"The interaction (F=MS_Int/MS_Error) is removed when its p-value >= {config.interaction_alpha:g} (Minitab's alpha to remove). With interaction: var_Repeat=MS_Error; var_Int=max((MS_Int-MS_Error)/r,0); var_Oper=max((MS_Oper-MS_Int)/(p*r),0); var_Part=max((MS_Part-MS_Int)/(o*r),0). Without it: MS_Pooled=(SS_Int+SS_Error)/(df_Int+df_Error); var_Repeat=MS_Pooled; var_Oper=max((MS_Oper-MS_Pooled)/(p*r),0); var_Part=max((MS_Part-MS_Pooled)/(o*r),0).\n"
         + "var_Reprod=var_Oper+var_Int; variance_GRR=var_Repeat+var_Reprod; variance_Total=variance_GRR+var_Part. Study variation, %StudyVar, %SV/Tol and NDC then use this sigma_GRR exactly as above."),
        ("Variables", "i: sample index; j: repetition (or operator in the crossed model); k: repetition within an operator; p: distinct sample count; o: operator count; r: repetitions per sample (per operator when crossed); x_ij: measurement; mean_i: sample mean; SS: sum of squares; df: degrees of freedom; MS: mean square; F: ANOVA statistic; sigma: estimated SD; GRR: gage repeatability (and reproducibility when crossed) for this system; LSL/USL: specification limits; d2/d3: expected range and range SD constants for normal samples; floor: truncate toward zero for positive numbers."),
        ("Calculation steps", "1. Validate identities, trials, completeness and balance (and that every operator measured every sample, when crossed). 2. Keep each tester/slot separate; operators of one tester/slot are analyzed together. 3. Calculate sample means and grand mean. 4. Calculate SS, df, MS and ANOVA F/p. 5. Derive variance components, clipping negative components to zero without pooling them into other terms. 6. Derive SDs, study variation and all three key metrics. 7. Apply only the configured acceptance metric to unrounded results; report any informational metric that would fail on its own. 8. Generate charts from these same observations."),
        ("Acceptance", acceptance_text),
        ("Worked example", f"Samples [1,2,3], [4,5,6], [7,8,9], LSL=0, USL=20: p=3, r=3, N=9, mean=5. SS_Part=54, df_Part=2, MS_Part=27; SS_Error=6, df_Error=6, MS_Error=1. F=27, p=0.001. variance_Part=26/3; sigma_GRR=1; sigma_Total=sqrt(29/3); %StudyVar=32.163376. With the selected multiplier, StudyVar={config.study_factor:g}, %SV/Tol={config.study_factor * 5:g}%. NDC_raw=1.41*sqrt(26/3)=4.150928; NDC=4."),
        ("Assumptions and limitations", "Independent normal repeatability errors with common variance; samples represent the intended part variation. Balanced repeated measurements only; unbalanced designs are rejected. With a single operator, reproducibility is not estimated, so the result describes repeatability only. Operator is the crossed factor and is treated as a random sample of its levels (a nest can stand in for the operator in a crossed study when the fixture is evaluated as a whole). To evaluate and approve each nest individually, map it to Slot or Tester instead. Tester and slot combinations are never pooled. No nested multi-appraiser model, attribute study, historical process sigma or confidence intervals. Zero total variation makes %Study Var N/A; zero Gage R&R makes NDC N/A. Results are statistical estimates subject to model, data quality and assumptions."),
    )


def formula_sections(config: AnalysisConfig) -> tuple[tuple[str, str], ...]:
    """Use native mathematical glyphs supported by the application/report fonts."""
    def mathematical(text: str) -> str:
        for old, new in (("sigma_", "\u03c3_"), ("*", " \u00d7 "), ("sqrt(", "\u221a("),
                         (">=", "\u2265"), ("<=", "\u2264"), ("^2", "\u00b2"), ("+/-", "\u00b1")):
            text = text.replace(old, new)
        return text
    return tuple((heading, mathematical(text)) for heading, text in _formula_sections(config))


def explain_method(config: AnalysisConfig) -> str:
    return "\n\n".join(f"{heading}\n{text}" for heading, text in formula_sections(config))


def format_number(value: float | int | None, precision: int = 3) -> str:
    if value is None or not math.isfinite(value):
        return "N/A"
    if isinstance(value, int):
        return str(value)
    if value and (abs(value) < 10 ** -precision or abs(value) >= 1e9):
        return f"{value:.{max(precision, 2)}g}"
    return f"{value:.{precision}f}"


def calculation_details(result: AnalysisResult) -> str:
    precision = max(8, result.config.precision)
    lines = [f"{result.label} | {result.status}",
             f"Samples={result.parts}; measurements={result.n}; repetitions={result.repeats or 'unbalanced'}",
             f"Mean={format_number(result.mean, precision)}; Min={format_number(result.minimum, precision)}; Max={format_number(result.maximum, precision)}",
             f"LSL={format_number(result.lsl, precision)}; USL={format_number(result.usl, precision)}",
             f"Profile={result.config.profile}; decision metric={metric_label(result.decision_metric)}"]
    for key, value in result.metrics.items():
        lines.append(f"{key} = {format_number(value, precision)}")
    for key, value in result.details.items():
        if key not in {"part_summaries", "moving_ranges"}:
            lines.append(f"{key} = {value}")
    lines.extend(f"{issue.severity.upper()}: {issue.message}" for issue in result.issues)
    return "\n".join(lines)
