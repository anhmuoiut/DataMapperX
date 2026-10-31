"""The About guide: its formulas parse and can be laid out, and the values it lists reproduce the reported metrics by its own sequence."""

from __future__ import annotations

import math
import random

import pytest

from datamapperx.mathtext import layout, parse, to_text
from datamapperx.method_guide import capability_values, grr_values, guide_text, method_guide
from datamapperx.statistics import AnalysisConfig, Observation, analyze

CONFIGS = [AnalysisConfig(method="grr"), AnalysisConfig(method="grr", study_factor=4.0),
           AnalysisConfig(method="capability", within_method="individuals"),
           AnalysisConfig(method="capability", within_method="pooled"),
           AnalysisConfig(method="capability", within_method="pooled", use_unbiasing=False)]


def measure(text, size, italic):
    return 0.6 * size * len(text), 0.8 * size, 0.2 * size


def number(text):
    return float(text)


def grr_result(factor=6.0, parts=10, repeats=3, seed=3, low=0.0, high=40.0, spread=0.3):
    rng = random.Random(seed)
    rows = [Observation("Item", f"S{p}", 10 + 2 * p + rng.gauss(0, spread), low, high, trial=str(t))
            for p in range(parts) for t in range(1, repeats + 1)]
    result, = analyze(rows, AnalysisConfig(method="grr", study_factor=factor))
    assert result.valid
    return result, rows


def test_the_notation_is_a_small_latex_that_reads_back_as_text():
    assert to_text(r"\frac{a}{b}") == "a/b" and to_text(r"x_{ij}^{2}") == "x_ij^2"
    assert to_text(r"\sigma_{GRR}=\sqrt{\sigma^{2}_{GRR}}") == "σ_GRR = √(σ_GRR^2)"
    assert to_text(r"C_{pk}=\min\left(a,\,b\right)") == "C_pk = min(a,b)"
    for broken in (r"\frac{a}", r"\nonsense", r"x_{", r"\left(a"):
        with pytest.raises(ValueError):
            parse(broken)


def test_names_of_several_letters_are_upright_and_take_the_subscript_that_follows():
    assert parse("SS_{Part}") == ("row", (("script", ("t", "SS", False), ("row", (("t", "Part", False),)), None),))
    assert parse("x_{ij}")[1][0][1] == ("t", "x", True) and parse("x_{ij}")[1][0][2] == ("row", (("t", "ij", True),))  # indexes stay italic


@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: f"{c.method}-{c.within_method}-{c.study_factor}")
def test_every_formula_of_every_guide_parses_and_can_be_laid_out(config):
    guide = method_guide(config)
    assert guide.method and "Minitab" not in guide_text(guide) and guide.sections  # an independent application: no menu paths
    for section in guide.sections:
        for formula in section.formulas:
            assert formula.name and formula.explanation and formula.lines
            for source in (*formula.lines, *(symbol for symbol, _ in formula.variables)):
                box = layout(parse(source), 15, measure)
                assert box.w > 0 and box.asc + box.desc > 0 and to_text(source), source
    assert guide_text(guide).count("\n") > 20


def test_the_gage_guide_has_the_three_groups_and_never_shows_reproducibility_as_an_estimate():
    guide = method_guide(AnalysisConfig(method="grr"))
    assert [s.title for s in guide.sections][:3] == ["ANOVA calculations", "Variance components", "Key metrics"]
    lines = [to_text(line) for s in guide.sections for f in s.formulas for line in f.lines]
    assert not any("eprod" in line or "Oper" in line for line in lines)
    for needed in ("SS_Part", "df_Error", "MS_Part", "σ_Repeat^2 = MS_Error", "max((MS_Part − MS_Error)/r,0)", "σ_Total^2 = σ_GRR^2 + σ_Part^2",
                   "SV_GRR = kσ_GRR", "100", "USL − LSL", "1.41"):
        assert any(needed in line for line in lines), needed
    assert guide.method == "One-way ANOVA (Single Tester)" and "uses k = 6" in guide_text(guide)


def test_the_listed_values_repeat_the_calculation_and_give_the_reported_metrics():
    for factor in (6.0, 4.0):
        result, rows = grr_result(factor)
        listed = {symbol: number(value) for symbol, value in grr_values(result) if symbol not in ("",)}
        p, r = int(listed["p"]), int(listed["r"])
        data = {}
        for row in rows:
            data.setdefault(row.sample_id, []).append(row.value)
        means = [math.fsum(v) / r for v in data.values()]
        grand = math.fsum(means) / p
        ss_part = r * math.fsum((m - grand) ** 2 for m in means)
        ss_error = math.fsum((x - m) ** 2 for (v, m) in zip(data.values(), means, strict=True) for x in v)
        ms_part, ms_error = ss_part / (p - 1), ss_error / (p * (r - 1))
        var_repeat, var_part = ms_error, max((ms_part - ms_error) / r, 0)
        var_total = var_repeat + var_part
        sd_grr, sd_part, sd_total = (math.sqrt(v) for v in (var_repeat, var_part, var_total))
        sv = factor * sd_grr
        expected = {"p": p, "r": r, "N": p * r, r"\bar{\bar{x}}": grand, "SS_{Part}": ss_part, "SS_{Error}": ss_error, "df_{Part}": p - 1,
                    "df_{Error}": p * (r - 1), "MS_{Part}": ms_part, "MS_{Error}": ms_error, "k": factor, r"\sigma^{2}_{Repeat}": var_repeat,
                    r"\sigma^{2}_{Part}": var_part, r"\sigma^{2}_{Total}": var_total, r"\sigma_{GRR}": sd_grr, r"\sigma_{Part}": sd_part,
                    r"\sigma_{Total}": sd_total, "SV_{GRR}": sv, "USL-LSL": 40.0, r"\text{%Study Var}": 100 * sd_grr / sd_total,
                    r"\text{%Tolerance}": 100 * sv / 40.0, "ndc": max(1, math.floor(1.41 * sd_part / sd_grr))}
        for symbol, value in expected.items():
            assert listed[symbol] == pytest.approx(value, rel=2e-5), symbol
        for symbol, value in expected.items():  # and the engine's metrics are the same numbers
            metric = {r"\sigma_{GRR}": "sigma_grr", r"\sigma_{Part}": "sigma_part", r"\sigma_{Total}": "sigma_total", "SV_{GRR}": "study_var",
                      r"\text{%Study Var}": "percent_study_var", r"\text{%Tolerance}": "percent_tolerance", "ndc": "ndc"}.get(symbol)
            if metric:
                assert result.metrics[metric] == pytest.approx(value, rel=1e-9), symbol
        assert result.metrics["variance_grr"] == result.metrics["variance_repeatability"]  # one tester: Gage R&R is the repeatability
    assert listed[r"1.41\,\frac{\sigma_{Part}}{\sigma_{GRR}}"] == pytest.approx(1.41 * sd_part / sd_grr, rel=1e-4)


def test_k_rescales_study_variation_and_tolerance_only():
    six, _ = grr_result(6.0)
    three, _ = grr_result(3.0)
    assert three.metrics["study_var"] == pytest.approx(six.metrics["study_var"] / 2)
    assert three.metrics["percent_tolerance"] == pytest.approx(six.metrics["percent_tolerance"] / 2)
    for same in ("percent_study_var", "ndc", "sigma_grr", "sigma_part", "sigma_total", "variance_part"):
        assert three.metrics[same] == six.metrics[same], same


def test_a_negative_part_variance_is_zero_and_a_zero_gage_deviation_gives_no_ndc_as_documented():
    # the same readings in every sample: MS_Part = 0 < MS_Error, so the part-to-part estimate is negative
    rows = [Observation("Item", f"S{p}", value, 0, 40, trial=str(t)) for p in range(5) for t, value in enumerate((10.0, 11.0, 12.5), 1)]
    flat, = analyze(rows, AnalysisConfig(method="grr"))
    assert flat.metrics["variance_part"] == 0 and flat.metrics["percent_study_var"] == 100 and flat.metrics["ndc"] == 1
    assert flat.details["part_variance_untruncated"] < 0
    # identical readings within every sample: MS_Error = 0
    exact = [Observation("Item", f"S{p}", 10.0 + p, 0, 40, trial=str(t)) for p in range(5) for t in (1, 2)]
    sharp, = analyze(exact, AnalysisConfig(method="grr"))
    assert sharp.metrics["sigma_grr"] == 0 and sharp.metrics["ndc"] is None and sharp.metrics["percent_study_var"] == 0
    wide, = analyze([Observation("Item", f"S{p}", 10.0 + p + t * 0.1, None, None, trial=str(t)) for p in range(5) for t in (1, 2)],
                    AnalysisConfig(method="grr"))
    assert wide.metrics["percent_tolerance"] is None  # no limits: N/A
    text = guide_text(method_guide(AnalysisConfig(method="grr")))
    for sentence in ("set to 0", "ndc is N/A", "%Tolerance needs two finite limits"):
        assert sentence in text, sentence


def capability_result(within, unbiasing=True, subgroup=False):
    rng = random.Random(8)
    rows = [Observation("C3", str(i), 50 + rng.gauss(0, 1) + 0.05 * i, 44, 58, source=f"log{i}", subgroup=f"g{i // 5}" if subgroup else "")
            for i in range(30)]
    result, = analyze(rows, AnalysisConfig(method="capability", within_method=within, use_unbiasing=unbiasing))
    return result, [row.value for row in rows]


@pytest.mark.parametrize("within,unbiasing", [("individuals", True), ("pooled", True), ("pooled", False)])
def test_the_capability_values_repeat_the_calculation_and_give_the_reported_indices(within, unbiasing):
    result, values = capability_result(within, unbiasing, subgroup=within == "pooled")
    config = AnalysisConfig(method="capability", within_method=within, use_unbiasing=unbiasing)
    listed = {symbol: number(value) for symbol, value in capability_values(result, config)}
    n, low, high = len(values), 44.0, 58.0
    mean = math.fsum(values) / n
    overall = math.sqrt(math.fsum((x - mean) ** 2 for x in values) / (n - 1))
    if within == "individuals":
        mr_bar = math.fsum(abs(b - a) for a, b in zip(values, values[1:], strict=False)) / (n - 1)
        within_sd = mr_bar / 1.128
        assert listed[r"\bar{MR}"] == pytest.approx(mr_bar, rel=2e-5)
    else:
        groups = [values[i:i + 5] for i in range(0, n, 5)]
        d = sum(len(g) - 1 for g in groups)
        sp = math.sqrt(math.fsum((x - math.fsum(g) / len(g)) ** 2 for g in groups for x in g) / d)
        c4 = math.sqrt(2 / d) * math.gamma((d + 1) / 2) / math.gamma(d / 2)
        within_sd = sp / c4 if unbiasing else sp
        assert listed["s_{p}"] == pytest.approx(sp, rel=2e-5) and listed["d"] == d
        assert listed["c_{4}(d+1)"] == pytest.approx(c4 if unbiasing else 1.0, rel=2e-5)
    expected = {"N": n, r"\bar{x}": mean, r"\sigma_{overall}": overall, r"\sigma_{within}": within_sd,
                "C_{p}": (high - low) / (6 * within_sd), "C_{pk}": min(high - mean, mean - low) / (3 * within_sd),
                "P_{p}": (high - low) / (6 * overall), "P_{pk}": min(high - mean, mean - low) / (3 * overall)}
    for symbol, value in expected.items():
        assert listed[symbol] == pytest.approx(value, rel=2e-5), symbol
    for metric, value in (("sigma_within", within_sd), ("sigma_overall", overall), ("cp", expected["C_{p}"]), ("cpk", expected["C_{pk}"]),
                          ("pp", expected["P_{p}"]), ("ppk", expected["P_{pk}"])):
        assert result.metrics[metric] == pytest.approx(value, rel=1e-9), metric


def test_the_guide_for_capability_follows_the_within_method_and_keeps_the_two_deviations_apart():
    individuals = guide_text(method_guide(AnalysisConfig(method="capability", within_method="individuals")))
    pooled = guide_text(method_guide(AnalysisConfig(method="capability", within_method="pooled")))
    assert "1.128" in individuals and "c_4" not in individuals and "c_4(d + 1)" in pooled and "1.128" not in pooled
    assert "σ_within = s_p" in guide_text(method_guide(AnalysisConfig(method="capability", within_method="pooled", use_unbiasing=False)))
    for text in (individuals, pooled):
        assert "not interchangeable" in text and "σ_overall" in text and "σ_within" in text
