"""Data checks: the layout of a study, the amount-of-data rules, the guidelines, stability and normality."""
from __future__ import annotations

import math
import random

import pytest

from datamapperx.statistics import AnalysisConfig, Observation, analyze
from datamapperx.statistics.checks import (
    CAUTION,
    INFO,
    OK,
    anderson_darling_normal,
    capability_checks,
    describe_layouts,
    grr_amount_checks,
    grr_guidelines,
    i_mr_signals,
    layout_of,
    needs_attention,
    normality_check,
    result_checks,
    stability_check,
)


def rows(parts=10, operators=("A", "B", "C"), readings=3, item="X", skip=()):
    return [Observation(item, f"P{p}", float(p), 0, 20, trial=str(t), operator=op)
            for p in range(1, parts + 1) for op in operators for t in range(readings) if (p, op) not in skip]


# ----------------------------------------------------------------------------- the layout of a study
def test_a_balanced_crossed_study_is_described_in_one_line():
    assert describe_layouts(rows()) == ["The test item: 10 parts × 3 operators × 3 readings each, balanced."]
    assert describe_layouts(rows() + rows(item="Y")) == ["All 2 test items: 10 parts × 3 operators × 3 readings each, balanced."]


def test_one_tester_is_described_without_operators():
    assert layout_of(rows(operators=("",))).describe() == "10 parts × 3 readings each, balanced"


def test_a_part_an_operator_did_not_measure_is_named():
    layout = layout_of(rows(skip={(4, "B")}))
    assert not layout.balanced and layout.problems == ("operator B has no readings of part P4",)
    assert "NOT balanced" in layout.describe()
    line = describe_layouts(rows(skip={(4, "B")}))[0]
    assert "operator B has no readings of part P4" in line


def test_unequal_readings_are_reported_as_a_range():
    data = rows() + [Observation("X", "P1", 1.0, 0, 20, operator="A", trial="9")]
    layout = layout_of(data)
    assert (layout.fewest, layout.most) == (3, 4) and "3 to 4 readings each" in layout.describe() and not layout.balanced


def test_different_layouts_among_items_get_their_own_lines():
    lines = describe_layouts(rows() + rows(item="Y", parts=12))
    assert len(lines) == 2 and lines[0].startswith("1 of 2 test items:") and "12 parts" in lines[1]


def test_a_reading_without_an_operator_in_a_crossed_study_is_flagged():
    data = rows() + [Observation("X", "P1", 1.0, 0, 20, operator="")]
    assert "some readings have no operator" in layout_of(data).problems


# ----------------------------------------------------------------------------- amount of data
@pytest.mark.parametrize("parts,status", [(3, CAUTION), (9, CAUTION), (10, INFO), (15, INFO), (16, OK), (34, OK), (35, OK), (60, OK)])
def test_the_parts_rule_follows_the_published_thresholds(parts, status):
    assert grr_amount_checks(parts, 3)[0].status == status


@pytest.mark.parametrize("parts,operators,status", [
    (10, 2, CAUTION), (9, 3, CAUTION), (10, 3, INFO), (10, 5, INFO), (10, 6, OK), (30, 8, OK)])
def test_the_operators_rule_follows_the_published_thresholds(parts, operators, status):
    assert grr_amount_checks(parts, operators)[1].status == status


def test_one_tester_has_no_operators_check():
    assert [c.topic for c in grr_amount_checks(10, 0)] == ["Parts"]


# ----------------------------------------------------------------------------- guidelines
def metrics(sv=None, tol=None, vg=None, vt=None, ndc=None):
    return {"percent_study_var": sv, "percent_tolerance": tol, "variance_grr": vg, "variance_total": vt, "ndc": ndc}


@pytest.mark.parametrize("value,word", [(5, "below 10 %"), (9.99, "below 10 %"), (10, "between 10 % and 30 %"), (30, "between 10 % and 30 %"),
                                        (30.01, "above 30 %")])
def test_the_study_variation_guideline_bands(value, word):
    (check,) = grr_guidelines(metrics(sv=value))
    assert check.topic == "%Study Var" and word in check.message and check.status == INFO  # a guideline, never a verdict colour


def test_the_contribution_and_distinct_category_guidelines():
    by_topic = {c.topic: c.message for c in grr_guidelines(metrics(vg=0.5, vt=100, ndc=4))}
    assert "below 1 %" in by_topic["%Contribution"] and "below the guideline of at least 5" in by_topic["Distinct categories"]
    assert "between 1 % and 9 %" in {c.topic: c.message for c in grr_guidelines(metrics(vg=5, vt=100))}["%Contribution"]
    assert "above 9 %" in {c.topic: c.message for c in grr_guidelines(metrics(vg=20, vt=100))}["%Contribution"]
    assert "cannot tell the parts apart" in grr_guidelines(metrics(ndc=1))[0].message
    assert "meets the guideline" in grr_guidelines(metrics(ndc=5))[0].message
    assert grr_guidelines(metrics()) == []  # nothing to say about what was not computed


def test_the_figures_of_minitabs_own_crossed_example_land_in_the_bands_it_describes():
    # Minitab's help for the Gage data example: %Study Var 27.86, %Tolerance 22.68, ndc 4, %Contribution 7.76.
    by_topic = {c.topic: c.message for c in grr_guidelines(metrics(sv=27.86, tol=22.68, vg=0.09143, vt=1.17788, ndc=4))}
    assert "between 10 % and 30 %" in by_topic["%Study Var"] and "between 10 % and 30 %" in by_topic["%Tolerance"]
    assert "between 1 % and 9 %" in by_topic["%Contribution"] and "below the guideline" in by_topic["Distinct categories"]


# ----------------------------------------------------------------------------- stability
def naive_signals(values):
    n, mean = len(values), sum(values) / len(values)
    mrs = [abs(values[i + 1] - values[i]) for i in range(n - 1)]
    mr_bar = sum(mrs) / len(mrs)
    sigma = mr_bar / 1.128
    ucl_mr = 3.2673 * mr_bar
    beyond = [i for i in range(n) if values[i] > mean + 3 * sigma or values[i] < mean - 3 * sigma]
    flagged = []
    for i in range(8, n):  # a run of 9 ends at index i when the 9 readings i-8..i are all on one side
        window = values[i - 8:i + 1]
        if all(v > mean for v in window) or all(v < mean for v in window):
            flagged.append(i)
    return beyond, flagged, [i + 1 for i, r in enumerate(mrs) if r > ucl_mr]


def test_signals_agree_with_a_plain_rewrite_on_random_data():
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(5, 60)
        values = [rng.gauss(0, 1) + (3.5 if rng.random() < .03 else 0) + (0.9 if 20 < i < 33 else 0) for i in range(n)]
        signals = i_mr_signals(values)
        assert (signals.i_beyond, signals.i_run, signals.mr_beyond) == tuple(map(tuple, naive_signals(values)))


def test_a_single_wild_reading_signals_on_both_charts():
    values = [10.0, 10.1, 9.9, 10.0, 10.1, 9.9, 10.0, 10.1, 9.9, 10.0, 12.5, 10.0, 10.1, 9.9, 10.0]
    signals = i_mr_signals(values)
    assert 10 in signals.i_beyond and 10 in signals.mr_beyond and 11 in signals.mr_beyond


def test_nine_in_a_row_on_one_side_is_test_two_and_a_reading_on_the_line_breaks_the_run():
    below = [9.9, 9.8, 9.9, 9.7, 9.9, 9.8, 9.9, 9.7, 9.9, 9.8]
    above = [10.3, 10.2, 10.4, 10.3, 10.2, 10.4, 10.3, 10.2, 10.4, 10.3]
    signals = i_mr_signals(below + above)
    assert signals is not None and set(range(8, 10)) <= set(signals.i_run)
    constant = i_mr_signals([5.0] * 12)
    assert constant is None  # nothing varies, so there is nothing to judge against


def test_stability_status_depends_on_whether_the_order_is_known():
    steady = [10.0, 10.1, 9.9, 10.05, 9.95, 10.0, 10.1, 9.9, 10.05, 9.95, 10.0, 10.1]
    assert stability_check(steady, order_known=True, order_note="").status == OK
    unknown = stability_check(steady, order_known=False, order_note="")
    assert unknown.status == INFO and "not in a known order" in unknown.message
    drifting = [10.0 + 0.1 * i for i in range(30)]
    assert stability_check(drifting, order_known=True, order_note="").status == CAUTION
    assert "Possible instability" in stability_check(drifting, order_known=False, order_note="").message


# ----------------------------------------------------------------------------- normality
# Reference values computed independently with scipy (A-squared) and statsmodels (p-value).
REFERENCE = {
    "A": ([9.8, 10.1, 10.3, 9.9, 10.0, 10.2, 9.7, 10.4, 10.1, 9.9, 10.0, 10.2], 0.14348592968408092, 0.956894452519696),
    "B": ([1, 2, 2, 3, 3, 3, 4, 4, 5, 9, 12, 20], 1.2494426916368564, 0.0017243786332352675),
    "C": (list(range(1, 21)), 0.22073784165630173, 0.8063550613283764),
}


@pytest.mark.parametrize("name", REFERENCE)
def test_anderson_darling_matches_independent_implementations(name):
    values, a2, p = REFERENCE[name]
    got_a2, got_p = anderson_darling_normal(values)
    assert got_a2 == pytest.approx(a2, rel=1e-9) and got_p == pytest.approx(p, rel=1e-9)


def test_anderson_darling_edge_cases():
    assert anderson_darling_normal([1, 2]) is None and anderson_darling_normal([4.0] * 10) is None
    a2, p = anderson_darling_normal([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert a2 > 0 and 0 < p <= 1
    skewed = anderson_darling_normal([math.exp(i / 3) for i in range(40)])
    assert skewed[1] < 0.001  # strongly non-normal data


def test_normality_check_statuses():
    rng = random.Random(3)
    assert normality_check([rng.gauss(0, 1) for _ in range(200)]).status == OK
    assert normality_check([math.exp(i / 3) for i in range(40)]).status == CAUTION
    assert "too few" in normality_check([1.0, 2.0, 3.0]).message and normality_check([1.0, 2.0, 3.0]).status == INFO
    assert "do not vary" in normality_check([2.0] * 20).message


# ----------------------------------------------------------------------------- capability checks as a whole
def quantiles(n, seed):
    """Normal-looking readings with no outlier: the n evenly spaced quantiles of a normal distribution, in a fixed shuffle."""
    from statistics import NormalDist

    values = [50 + NormalDist().inv_cdf((i + 0.5) / n) for i in range(n)]
    random.Random(seed).shuffle(values)
    return values


def test_capability_checks_report_amount_stability_and_normality():
    steady = quantiles(120, seed=1)  # a shuffle with no control-chart signal
    by_topic = {c.topic: c for c in capability_checks(steady, individuals=True, order_known=True)}
    assert set(by_topic) == {"Stability", "Normality", "Amount of data"} and by_topic["Amount of data"].status == OK
    short = {c.topic: c for c in capability_checks(steady[:30], individuals=True, order_known=True)}
    assert short["Amount of data"].status == CAUTION and "Only 30 observations" in short["Amount of data"].message
    pooled = {c.topic: c for c in capability_checks(steady, individuals=False, order_known=True)}
    assert pooled["Stability"].status == INFO and "subgroups" in pooled["Stability"].message
    assert needs_attention(list(short.values())) and not needs_attention(list(by_topic.values()))


# ----------------------------------------------------------------------------- the real results
def test_result_checks_for_a_crossed_study_and_for_capability():
    # give the readings some spread so that the study can be analysed
    noisy = [Observation(o.test_item, o.sample_id, o.value + 0.01 * ((i * 7) % 5), 0, 20, trial=o.trial, operator=o.operator)
             for i, o in enumerate(rows(parts=10))]
    crossed = analyze(noisy, AnalysisConfig(method="grr", assign_trials=True))[0]
    checks, guidelines = result_checks(crossed, order_known=False)
    assert [c.topic for c in checks] == ["Parts", "Operators"] and checks[1].status == INFO  # 3 operators, 10 parts
    assert {g.topic for g in guidelines} >= {"%Study Var", "%Contribution"}

    rng = random.Random(5)
    cap_rows = [Observation("C", f"S{i}", rng.gauss(50, 1), 40, 60) for i in range(40)]
    capability = analyze(cap_rows, AnalysisConfig(method="capability"))[0]
    checks, guidelines = result_checks(capability, order_known=False, order_note=" Order note.")
    assert guidelines == [] and {c.topic for c in checks} == {"Stability", "Normality", "Amount of data"}
    assert "Order note." in next(c for c in checks if c.topic == "Stability").message

    broken = analyze([Observation("B", "S1", "n/a", 0, 1)], AnalysisConfig(method="capability"))[0]
    assert result_checks(broken, order_known=False)[0][0].topic == "Data"
