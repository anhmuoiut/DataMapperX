"""What "About the method" says: the calculation sequence of the selected analysis, as formulas in ``mathtext`` notation.

The formulas are those of ``statistics/grr.py`` (one tester: balanced one-way ANOVA) and ``statistics/capability.py``. They are written
out here, not generated, so ``tests/test_method_guide.py`` recomputes the reported metrics from the values this guide lists and compares.
No GUI code: ``ui/method_dialog.py`` draws a ``Guide``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .mathtext import to_text
from .stat_charts import plain_number
from .statistics.models import MR_D2, AnalysisConfig

GRR_METHOD = "One-way ANOVA (Single Tester)"
CAPABILITY_METHOD = "Normal capability analysis (within and overall standard deviation)"


@dataclass(frozen=True, slots=True)
class Formula:
    name: str
    lines: tuple[str, ...]  # mathtext
    explanation: str
    variables: tuple[tuple[str, str], ...] = ()  # (symbol in mathtext, meaning)


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    formulas: tuple[Formula, ...] = ()
    notes: tuple[str, ...] = ()  # plain sentences
    values: tuple[tuple[str, str], ...] = ()  # (symbol in mathtext, value), for the item that is selected
    opened: bool = True


@dataclass(frozen=True, slots=True)
class Guide:
    title: str
    method: str
    summary: str
    sections: tuple[Section, ...]


def _f(name, lines, explanation, *variables) -> Formula:
    return Formula(name, tuple(lines) if not isinstance(lines, str) else (lines,), explanation, tuple(variables))


# ----------------------------------------------------------------------------- Variable Gage R&R
def _grr_guide(config: AnalysisConfig, result) -> Guide:
    k = f"{config.study_factor:g}"
    anova = Section("ANOVA calculations", (
        _f("Sample mean and overall mean", (r"\bar{x}_{i}=\frac{1}{r}\sum_{j=1}^{r}x_{ij}", r"\bar{\bar{x}}=\frac{1}{p}\sum_{i=1}^{p}\bar{x}_{i}"),
           "Each sample's readings are averaged; the overall mean is the average of those sample means.",
           ("p", "number of samples"), ("r", "readings of each sample"), ("x_{ij}", "reading j of sample i"),
           (r"\bar{x}_{i}", "mean of sample i"), (r"\bar{\bar{x}}", "overall mean")),
        _f("Sum of squares (SS)",
           (r"SS_{Part}=r\sum_{i=1}^{p}\left(\bar{x}_{i}-\bar{\bar{x}}\right)^{2}",
            r"SS_{Error}=\sum_{i=1}^{p}\sum_{j=1}^{r}\left(x_{ij}-\bar{x}_{i}\right)^{2}", r"SS_{Total}=SS_{Part}+SS_{Error}"),
           "Part: how far the sample means are from the overall mean. Error: how far the readings are from the mean of their own "
           "sample, which is the repeatability."),
        _f("Degrees of freedom (DF)", (r"df_{Part}=p-1", r"df_{Error}=p(r-1)", r"df_{Total}=N-1"),
           "Independent pieces of information in each sum of squares.", ("N", "all readings, N = p r")),
        _f("Mean squares (MS)", (r"MS_{Part}=\frac{SS_{Part}}{df_{Part}}", r"MS_{Error}=\frac{SS_{Error}}{df_{Error}}",
                                 r"F=\frac{MS_{Part}}{MS_{Error}}"),
           "A sum of squares per degree of freedom. F is printed in the ANOVA table; no reported metric uses it.")))
    components = Section("Variance components", (
        _f("Repeatability variance", r"\sigma^{2}_{Repeat}=MS_{Error}",
           "The variation of repeated readings of the same sample by the same tester."),
        _f("Part-to-part variance", r"\sigma^{2}_{Part}=\max\left(\frac{MS_{Part}-MS_{Error}}{r},\,0\right)",
           "The variation between samples that remains after removing the measurement noise in the sample means. When "
           "MS_Part is below MS_Error the estimate is negative and is set to 0; repeatability is left as it is."),
        _f("Gage R&R, total variance and standard deviations",
           (r"\sigma^{2}_{GRR}=\sigma^{2}_{Repeat}", r"\sigma^{2}_{Total}=\sigma^{2}_{GRR}+\sigma^{2}_{Part}",
            r"\sigma_{GRR}=\sqrt{\sigma^{2}_{GRR}}", r"\sigma_{Part}=\sqrt{\sigma^{2}_{Part}}", r"\sigma_{Total}=\sqrt{\sigma^{2}_{Total}}"),
           "With one tester Reproducibility cannot be estimated, so it is not shown: Gage R&R is the repeatability.")))
    metrics = Section("Key metrics", (
        _f("Study Variation", (r"SV_{GRR}=k\,\sigma_{GRR}", r"SV_{Total}=k\,\sigma_{Total}"),
           f"The spread taken up by the measurement, as k standard deviations. This study uses k = {k}; k = 6 is the usual choice "
           "and means ±3σ around the mean (99.73 % of a normal distribution).",
           ("k", "study variation factor, 1 to 6")),
        _f("%Study Var", r"\text{%Study Var}=100\,\frac{\sigma_{GRR}}{\sigma_{Total}}",
           "The share of the total spread that is measurement variation. A ratio of standard deviations, so k cancels."),
        _f("%Tolerance (SV/Tol)", r"\text{%Tolerance}=100\,\frac{SV_{GRR}}{USL-LSL}",
           "The share of the tolerance width taken up by the measurement spread. Proportional to k.",
           ("USL, LSL", "upper and lower specification limits")),
        _f("%Contribution", r"\text{%Contribution}=100\,\frac{\sigma^{2}_{x}}{\sigma^{2}_{Total}}",
           "A source's share of the total variance.", ("x", "Gage R&R, Repeatability or Part-to-Part")),
        _f("Number of distinct categories", r"ndc=\max\left(1,\,\floor\left(1.41\,\frac{\sigma_{Part}}{\sigma_{GRR}}\right)\right)",
           "How many groups the measurement can tell apart: 1.41 (≈ √2) times the part spread over the gage spread, rounded down, "
           "never below 1.")))
    undefined = Section("Zero, negative and undefined values", notes=(
        "A negative part-to-part variance estimate is set to 0. Then the total equals the repeatability and %Study Var is 100.",
        "Identical readings within every sample (MS_Error = 0): σ_GRR = 0, so ndc is N/A (no large number is made up).",
        "All readings equal (σ_Total = 0): %Study Var is N/A.",
        "%Tolerance needs two finite limits with USL > LSL; otherwise it is N/A.",
        "A standard deviation that is not zero but below the floating-point range is N/A, never 0.",
        "At least 2 samples, at least 2 readings of each sample and the same number for every sample are needed; otherwise "
        "the item is not analysed and the message says what to fix."))
    sections = [anova, components, metrics, undefined]
    if result is not None:
        sections.append(Section("Values for the selected item", values=grr_values(result), opened=True))
    sections.append(Section("Known limits", notes=(
        "Not supported: unequal numbers of readings per sample, a historical process standard deviation, attribute studies.",
        "With one specification limit %Tolerance is N/A.",
        "The R and Xbar chart limits use the average range R̄/d₂ (2 to 8 readings per sample), separate from the ANOVA.",
        "Rounding ndc down and its minimum of 1 are conventions that have not been compared with reference output for a "
        "single-tester study."), opened=False))
    return Guide("Variable Gage R&R", GRR_METHOD,
                 "One tester measures p samples r times each. Balanced one-way ANOVA with the sample as the only factor.",
                 tuple(sections))


def _number(value, places: int = 6) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    return plain_number(float(value), places) if math.isfinite(value) else "N/A"


def grr_values(result) -> tuple[tuple[str, str], ...]:
    """The inputs and intermediate values of one item, enough to repeat the calculation sequence by hand."""
    d, m = result.details, result.metrics
    if d.get("crossed"):
        return (("", "This item has operators in its data, so a crossed ANOVA was used. The one-way values are not listed."),)
    if not d.get("anova"):
        return (("", "This item could not be analysed."),)
    part, error, total = d["anova"]
    repeats = next(iter(d["repetition_counts"].values()))
    tolerance = result.usl - result.lsl if result.usl is not None and result.lsl is not None and result.usl > result.lsl else None
    rows = [("p", str(len(d["repetition_counts"]))), ("r", str(repeats)), ("N", str(total["df"] + 1)),
            (r"\bar{\bar{x}}", _number(d["mean"])), ("SS_{Part}", _number(part["ss"])), ("SS_{Error}", _number(error["ss"])),
            ("df_{Part}", str(part["df"])), ("df_{Error}", str(error["df"])), ("MS_{Part}", _number(d["ms_part"])),
            ("MS_{Error}", _number(d["ms_error"])), ("F", _number(part["f"], 4)), ("k", f"{result.config.study_factor:g}"),
            (r"\sigma^{2}_{Repeat}", _number(m.get("variance_repeatability"))), (r"\sigma^{2}_{Part}", _number(m.get("variance_part"))),
            (r"\sigma^{2}_{Total}", _number(m.get("variance_total"))), (r"\sigma_{GRR}", _number(m.get("sigma_grr"))),
            (r"\sigma_{Part}", _number(m.get("sigma_part"))), (r"\sigma_{Total}", _number(m.get("sigma_total"))),
            ("SV_{GRR}", _number(m.get("study_var"))), ("USL-LSL", _number(tolerance)),
            (r"\text{%Study Var}", _number(m.get("percent_study_var"))), (r"\text{%Tolerance}", _number(m.get("percent_tolerance"))),
            (r"1.41\,\frac{\sigma_{Part}}{\sigma_{GRR}}", _number(d.get("ndc_raw"))), ("ndc", _number(m.get("ndc")))]
    return tuple(rows)


# ----------------------------------------------------------------------------- Process capability
def _capability_guide(config: AnalysisConfig, result) -> Guide:
    individuals = config.within_method == "individuals"
    if individuals:
        within = _f("Within standard deviation: average moving range",
                    (r"MR_{i}=|x_{i}-x_{i-1}|", r"\bar{MR}=\frac{1}{N-1}\sum_{i=2}^{N}MR_{i}",
                     r"\sigma_{within}=\frac{\bar{MR}}{d_{2}},\quad d_{2}=" + str(MR_D2)),
                    "Short-term spread from the difference between consecutive readings (moving range of length 2). The readings must be "
                    "in the order they were taken, within each test item: a drift raises the overall SD but hardly this one.",
                    ("MR_{i}", "moving range of readings i−1 and i"), ("d_{2}", "unbiasing constant for a range of length 2"))
    else:
        pooled = r"s_{p}=\sqrt{\frac{\sum_{g}\sum_{j=1}^{n_{g}}\left(x_{gj}-\bar{x}_{g}\right)^{2}}{d}},\quad d=\sum_{g}(n_{g}-1)"
        lines = ((pooled, r"\sigma_{within}=\frac{s_{p}}{c_{4}(d+1)}", r"c_{4}(n)=\sqrt{\frac{2}{n-1}}\,\frac{\Gamma(n/2)}{\Gamma((n-1)/2)}")
                 if config.use_unbiasing else (pooled, r"\sigma_{within}=s_{p}"))
        within = _f("Within standard deviation: pooled subgroups", lines,
                    "Variation inside subgroups only; every subgroup needs at least 2 readings. The subgroup comes from the data (or the "
                    "Sample ID, if you chose that) and is assumed to be a rational subgroup: readings taken together, under the same "
                    "conditions." + (" The c₄ constant removes the bias of a standard deviation." if config.use_unbiasing else ""),
                    ("g", "subgroup"), ("n_{g}", "readings in subgroup g"), (r"\bar{x}_{g}", "mean of subgroup g"))
    estimation = Section("Standard deviation estimation", (
        _f("Sample mean", r"\bar{x}=\frac{1}{N}\sum_{i=1}^{N}x_{i}", "The average of all N readings of the test item.",
           ("N", "number of readings"), ("x_{i}", "reading i")),
        _f("Overall standard deviation", r"\sigma_{overall}=\sqrt{\frac{\sum_{i=1}^{N}\left(x_{i}-\bar{x}\right)^{2}}{N-1}}",
           "The ordinary sample standard deviation of all readings, with no unbiasing constant. It contains every source of variation, "
           "including drift between subgroups."),
        within), notes=("Within and overall are different estimates, not interchangeable: within is the short-term spread, overall "
                        "includes variation over time or between subgroups. They agree only for a stable process.",))
    indices = Section("Capability indices", (
        _f("Cp and Cpk (within)",
           (r"C_{p}=\frac{USL-LSL}{6\,\sigma_{within}}",
            r"C_{pk}=\min\left(\frac{USL-\bar{x}}{3\,\sigma_{within}},\,\frac{\bar{x}-LSL}{3\,\sigma_{within}}\right)"),
           "The process spread is taken as 6σ, that is ±3σ around the mean. Cp compares the tolerance width with 6σ; Cpk compares the "
           "distance from the mean to the nearest limit with 3σ, so it drops when the process is off-centre.",
           ("USL, LSL", "upper and lower specification limits")),
        _f("Pp and Ppk (overall)",
           (r"P_{p}=\frac{USL-LSL}{6\,\sigma_{overall}}",
            r"P_{pk}=\min\left(\frac{USL-\bar{x}}{3\,\sigma_{overall}},\,\frac{\bar{x}-LSL}{3\,\sigma_{overall}}\right)"),
           "The same indices with the overall standard deviation.")),
        notes=("With one specification limit, Cpk and Ppk use that side and Cp and Pp are N/A (printed *).",
               "A standard deviation of zero, or outside the numeric range, makes the indices N/A.",
               "Cpm needs a target and is not calculated."))
    sections = [estimation, indices]
    if result is not None:
        sections.append(Section("Values for the selected item", values=capability_values(result, config), opened=True))
    sections.append(Section("Known limits", notes=(
        "The indices assume a stable process and normally distributed readings; the Checks tab screens both, the figures do not test them.",
        "The formulas are tested on data with known results; they have not been compared with reference output for a complete "
        "study."), opened=False))
    return Guide("Process Capability (Cp/Cpk, Pp/Ppk)", CAPABILITY_METHOD,
                 "N readings of one test item against its specification limits. Normal distribution assumed.", tuple(sections))


def capability_values(result, config: AnalysisConfig) -> tuple[tuple[str, str], ...]:
    d, m = result.details, result.metrics
    if "mean" not in d:
        return (("", "This item could not be analysed."),)
    rows = [("N", str(result.n)), (r"\bar{x}", _number(d["mean"])), ("LSL", _number(result.lsl)), ("USL", _number(result.usl)),
            (r"\sigma_{overall}", _number(m.get("sigma_overall")))]
    if config.within_method == "individuals":
        rows.append((r"\bar{MR}", _number(d.get("mr_bar"))))
    else:
        rows += [("s_{p}", _number(d.get("pooled_s"))), ("d", str(d.get("within_df"))), ("c_{4}(d+1)", _number(d.get("c4")))]
    rows += [(r"\sigma_{within}", _number(m.get("sigma_within"))), ("C_{p}", _number(m.get("cp"))), ("C_{pk}", _number(m.get("cpk"))),
             ("P_{p}", _number(m.get("pp"))), ("P_{pk}", _number(m.get("ppk")))]
    return tuple(rows)


def method_guide(config: AnalysisConfig, result=None) -> Guide:
    """The guide for the analysis in ``config``. With a ``result`` it ends with the values of that item."""
    return _grr_guide(config, result) if config.method == "grr" else _capability_guide(config, result)


def guide_text(guide: Guide) -> str:
    """The whole guide as plain text (tests, copying)."""
    lines = [guide.title, f"Method: {guide.method}", guide.summary]
    for section in guide.sections:
        lines += ["", section.title]
        for formula in section.formulas:
            lines += [f"  {formula.name}", *(f"    {to_text(line)}" for line in formula.lines), f"    {formula.explanation}",
                      *(f"    {to_text(symbol)}: {meaning}" for symbol, meaning in formula.variables)]
        lines += [f"  - {note}" for note in section.notes]
        lines += [f"  {to_text(symbol)} = {value}" if symbol else f"  {value}" for symbol, value in section.values]
    return "\n".join(lines)


__all__ = ["Formula", "Guide", "Section", "capability_values", "grr_values", "guide_text", "method_guide"]
