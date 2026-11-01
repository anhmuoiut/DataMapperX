"""Attribute Agreement Analysis (P1): the statistics, tested against independent calculations and Minitab's published figures.

The reference values come from Minitab's own documentation and from the report the study was modelled on (30 samples, one
appraiser, 100 % agreement, 95 % interval (90.50, 100.00), kappa 1, SE 0.105409, Z 9.48683). They are published figures,
not proof that an invented dataset reproduces that study. Everything here is headless.
"""
from __future__ import annotations

import dataclasses
import math
import random
from pathlib import Path

import pytest

from datamapperx.models import LogRecord, Measurement
from datamapperx.statistics import (
    AnalysisConfig,
    Dataset,
    EvaluationSettings,
    Observation,
    StatisticalOptions,
    Study,
    analyze,
    compute,
    explain_method,
    normalize_records,
)
from datamapperx.statistics.acceptance import attribute_acceptance
from datamapperx.statistics.attribute import agreement_interval, fleiss
from datamapperx.statistics.models import FAIL, NOT_EVALUATED, PASS
from datamapperx.statistics.study import METHOD_VERIFICATION, PENDING_VERIFICATION

ATTRIBUTE = AnalysisConfig(method="attribute")


# ----------------------------------------------------------------------------- independent reference calculations
def binomial_cdf(k: int, n: int, p: float) -> float:
    return math.fsum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def bisect(decreasing_in_x, target: float) -> float:
    """x in (0, 1) where a monotone function of x crosses ``target``."""
    low, high = 0.0, 1.0
    increasing = decreasing_in_x(0.75) > decreasing_in_x(0.25)
    for _ in range(100):
        middle = (low + high) / 2
        if (decreasing_in_x(middle) < target) == increasing:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def reference_interval(m: int, n: int, confidence: float) -> tuple[float, float]:
    """The exact binomial limits found from the binomial distribution itself (no beta function), with Minitab's boundary rule."""
    alpha = 1 - confidence
    lower_tail = alpha if m == n else alpha / 2
    upper_tail = alpha if m == 0 else alpha / 2
    lower = 0.0 if m == 0 else bisect(lambda p: 1 - binomial_cdf(m - 1, n, p), lower_tail)  # P(X >= m) = tail
    upper = 1.0 if m == n else bisect(lambda p: binomial_cdf(m, n, p), upper_tail)  # P(X <= m) = tail
    return lower, upper


def collapsed_kappa(counts, m: int, category: int) -> float:
    """Kappa of one category as Minitab describes it: every other category is combined into one, then the two-category
    kappa is Po-Pe over 1-Pe with Po the observed proportion of agreeing pairs of ratings."""
    n = len(counts)
    pairs = n * m * (m - 1)
    ones = [row[category] for row in counts]
    agreeing = sum(x * (x - 1) + (m - x) * (m - x - 1) for x in ones)
    p = sum(ones) / (n * m)
    observed, expected = agreeing / pairs, p * p + (1 - p) ** 2
    return (observed - expected) / (1 - expected)


# ----------------------------------------------------------------------------- the confidence interval
@pytest.mark.parametrize("matched,inspected,low,high", [(30, 30, 90.50, 100.00), (50, 50, 94.18, 100.00),
                                                         (47, 50, 83.45, 98.75), (37, 50, 59.66, 85.37)])
def test_the_interval_reproduces_minitabs_published_limits(matched, inspected, low, high):
    lower, upper = agreement_interval(matched, inspected, 0.95)  # 30/30 is the reference report; the others are Minitab's example
    assert (round(100 * lower, 2), round(100 * upper, 2)) == (low, high)


def test_perfect_agreement_uses_alpha_not_half_of_it_at_the_boundary():
    assert agreement_interval(30, 30)[0] == pytest.approx(0.05 ** (1 / 30), rel=1e-12)  # 0.9050, not 0.025**(1/30) = 0.8843
    assert agreement_interval(0, 30) == (0.0, pytest.approx(1 - 0.05 ** (1 / 30), rel=1e-12))
    assert agreement_interval(30, 30)[1] == 1.0


@pytest.mark.parametrize("confidence", [0.90, 0.95, 0.99])
@pytest.mark.parametrize("inspected", [1, 2, 5, 12, 30, 100])
def test_the_interval_matches_an_independent_binomial_calculation(inspected, confidence):
    for matched in range(inspected + 1):
        lower, upper = agreement_interval(matched, inspected, confidence)
        expected = reference_interval(matched, inspected, confidence)
        assert (lower, upper) == pytest.approx(expected, abs=1e-9), (matched, inspected)
        assert 0 <= lower <= matched / inspected <= upper <= 1


def test_a_higher_confidence_level_never_narrows_the_interval():
    for matched in (0, 7, 29, 30):
        narrow, wide = agreement_interval(matched, 30, 0.90), agreement_interval(matched, 30, 0.99)
        assert wide[0] <= narrow[0] and wide[1] >= narrow[1]


def test_the_interval_refuses_a_count_that_cannot_exist():
    for bad in ((31, 30), (-1, 30), (0, 0)):
        with pytest.raises(ValueError):
            agreement_interval(*bad)


# ----------------------------------------------------------------------------- Fleiss' kappa
WIKIPEDIA = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]  # 10 subjects, 14 raters, 5 categories


def test_fleiss_kappa_reproduces_the_published_worked_example():
    result = fleiss(WIKIPEDIA, 14)
    assert round(result["overall"][0], 3) == 0.210  # the value printed with this table (Po = 0.378, Pe = 0.213)


def random_counts(seed: int, samples: int, trials: int, categories: int):
    rng = random.Random(seed)
    weights = [rng.random() + 0.2 for _ in range(categories)]
    table = []
    for _ in range(samples):
        row = [0] * categories
        for _ in range(trials):
            row[rng.choices(range(categories), weights)[0]] += 1
        table.append(row)
    return table


@pytest.mark.parametrize("seed", range(6))
def test_each_category_kappa_is_the_collapsed_two_category_kappa(seed):
    counts, m = random_counts(seed, 12, 4, 3), 4
    result = fleiss(counts, m)
    for j, (kappa, variance) in enumerate(result["categories"]):
        assert kappa == pytest.approx(collapsed_kappa(counts, m, j), abs=1e-12)
        assert variance == pytest.approx(2 / (12 * m * (m - 1)))
    p = [sum(row[j] for row in counts) / (12 * m) for j in range(3)]
    weights = [x * (1 - x) for x in p]  # the overall kappa is the average of the category kappas weighted by p(1-p)
    average = sum(w * k for w, (k, _) in zip(weights, result["categories"], strict=True)) / sum(weights)
    assert result["overall"][0] == pytest.approx(average, abs=1e-12)


def test_with_two_categories_the_overall_kappa_and_its_variance_are_those_of_each_category():
    counts, m = random_counts(3, 20, 3, 2), 3
    result = fleiss(counts, m)
    (first, variance), (second, _) = result["categories"]
    assert first == pytest.approx(second, abs=1e-12) and result["overall"][0] == pytest.approx(first, abs=1e-12)
    assert result["overall"][1] == pytest.approx(variance, rel=1e-12) == pytest.approx(2 / (20 * 3 * 2))


def test_the_overall_variance_under_h0_matches_a_simulation():
    n, m = 40, 3
    table = random_counts(5, n, m, 3)
    shares = [sum(row[j] for row in table) / (n * m) for j in range(3)]  # the formula is evaluated at these shares
    rng = random.Random(11)
    kappas = []
    for _ in range(4000):  # independent ratings with these marginal shares: kappa is 0 and its spread is the H0 variance
        counts = []
        for _ in range(n):
            row = [0, 0, 0]
            for _ in range(m):
                row[rng.choices(range(3), shares)[0]] += 1
            counts.append(row)
        kappas.append(fleiss(counts, m)["overall"][0])
    mean = sum(kappas) / len(kappas)
    simulated = sum((k - mean) ** 2 for k in kappas) / (len(kappas) - 1)
    formula = fleiss(table, m)["overall"][1]
    assert simulated == pytest.approx(formula, rel=0.12)  # the formula uses estimated shares: close, not identical


def test_a_category_with_no_variation_has_no_kappa():
    counts = [[3, 0], [3, 0], [3, 0]]
    result = fleiss(counts, 3)
    assert result["overall"][0] is None and all(kappa is None for kappa, _ in result["categories"])
    half = fleiss([[3, 0], [0, 3], [3, 0], [0, 3]], 3)
    assert half["overall"][0] == pytest.approx(1.0) and [k for k, _ in half["categories"]] == [pytest.approx(1.0)] * 2


def test_kappa_refuses_ratings_that_are_not_balanced():
    for bad in ([[2, 1], [1, 1]], [[1, 0], [0, 1]]):  # unequal ratings per sample; a single rating per sample
        with pytest.raises(ValueError):
            fleiss(bad, 2)


# ----------------------------------------------------------------------------- building studies
def rate(sample, ratings, standard="", appraiser="", item="Programming"):
    return [Observation(item, sample, rating, trial=str(trial), operator=appraiser, standard=standard,
                        source=f"{item}/{appraiser}/{sample}/{trial}") for trial, rating in enumerate(ratings, 1)]


def reference_rows(passing=15, failing=15, trials=3, mistakes=()):
    """30 samples rated by one appraiser: ``passing`` Pass and ``failing`` Fail, every trial equal to the standard except the
    (sample number, trial number) pairs in ``mistakes``, which are rated the other way."""
    rows = []
    for number in range(1, passing + failing + 1):
        standard = "Pass" if number <= passing else "Fail"
        other = "Fail" if standard == "Pass" else "Pass"
        rows += rate(f"S{number:02d}", [other if (number, t) in mistakes else standard for t in range(1, trials + 1)], standard)
    return rows


def pass_only_rows(changes=None, appraiser="", trials=3, samples=30):
    """Every sample has the Standard Pass (no sample is a reference Fail) and is rated Pass in every trial, except the numbered
    samples in ``changes`` ("FFF" = Fail, Fail, Fail)."""
    word = {"P": "Pass", "F": "Fail"}
    rows = []
    for number in range(1, samples + 1):
        ratings = [word[letter] for letter in (changes or {}).get(number, "P" * trials)]
        rows += rate(f"S{number:02d}", ratings, "Pass", appraiser)
    return rows


def only(observations, config=ATTRIBUTE):
    result, = analyze(observations, config)
    return result


def appraiser(result, index=0):
    return result.details["appraisers"][index]


def test_the_reference_study_gives_the_published_figures():
    result = only(reference_rows())
    assert result.valid and result.parts == 30 and result.repeats == 3 and result.n == 90
    assert result.metrics["within_percent"] == 100 and result.metrics["standard_percent"] == 100
    assert (result.metrics["within_matched"], result.metrics["within_inspected"]) == (30, 30)
    only_appraiser = appraiser(result)
    for table in ("within", "standard"):
        agreement = only_appraiser[table]
        assert (agreement["inspected"], agreement["matched"], agreement["percent"]) == (30, 30, 100.0)
        assert (round(agreement["lower"], 2), agreement["upper"]) == (90.50, 100.0)
    for table in ("kappa_within", "kappa_standard"):
        kappa = only_appraiser[table]
        assert [row["response"] for row in kappa["rows"]] == ["Fail", "Pass"] and kappa["overall"]["response"] == "Overall"
        for row in (*kappa["rows"], kappa["overall"]):
            assert row["kappa"] == pytest.approx(1.0)
            assert round(row["se"], 6) == 0.105409 and round(row["z"], 5) == 9.48683 and round(row["p"], 4) == 0.0
    disagreement = only_appraiser["disagreement"]
    assert disagreement["applicable"] and disagreement["different"] == 0 and disagreement["percent"] == 0.0
    assert result.metrics["kappa_within"] == pytest.approx(1.0) and result.metrics["kappa_standard"] == pytest.approx(1.0)


def test_one_inconsistent_sample_lowers_within_agreement_only():
    result = only(reference_rows(mistakes={(4, 2)}))  # sample 4 was rated Pass, Fail, Pass
    within, against = appraiser(result)["within"], appraiser(result)["standard"]
    assert (within["matched"], within["percent"]) == (29, pytest.approx(100 * 29 / 30))
    assert (against["matched"], against["percent"]) == (29, pytest.approx(100 * 29 / 30))  # and it no longer equals the standard
    assert (within["lower"], within["upper"]) == pytest.approx(tuple(100 * x for x in reference_interval(29, 30, 0.95)), abs=1e-7)
    assert appraiser(result)["kappa_within"]["overall"]["kappa"] < 1


def test_a_consistent_error_is_within_agreement_but_not_agreement_with_the_standard():
    mistakes = {(n, t) for n in (3, 20) for t in (1, 2, 3)}  # two samples always rated the wrong way
    result = only(reference_rows(mistakes=mistakes))
    assert result.metrics["within_percent"] == 100 and result.metrics["standard_matched"] == 28
    assert result.metrics["standard_percent"] == pytest.approx(100 * 28 / 30)
    disagreement = appraiser(result)["disagreement"]
    assert (disagreement["assessments"], disagreement["different"]) == (90, 6) and disagreement["percent"] == pytest.approx(100 * 6 / 90)
    # sample 3 has the standard Pass, sample 20 the standard Fail: three assessments each in the two directions
    assert disagreement["by_direction"] == (("Fail", "Pass", 3), ("Pass", "Fail", 3))
    # sample 20 (Standard Fail) is always rated Pass, sample 3 (Standard Pass) always Fail: one of each, none mixed
    assert columns(result) == [("#Pass/Fail", 1, 15, pytest.approx(100 / 15)), ("#Fail/Pass", 1, 15, pytest.approx(100 / 15)), ("#Mixed", 0, 30, 0.0)]


# ----------------------------------------------------------------------------- Assessment Disagreement
def columns(result, index=0):
    """(heading, count, what the percent is of, percent) of each column of one appraiser's Assessment Disagreement."""
    return [(c["heading"], c["count"], c["base"], c["percent"]) for c in appraiser(result, index)["disagreement"]["columns"]]


def brute_force_disagreement(trials_by_sample, standard_by_sample, low, high):
    """Minitab's Assessment Disagreement of one appraiser, counted sample by sample straight from its definition, with no code of the
    engine: ``#high/low`` every trial rated ``high`` while the Standard is ``low``; ``#low/high`` the reverse; ``#Mixed`` the trials
    of the sample are not all the same. The percents divide by the samples whose Standard is ``low``, ``high`` and by all samples."""
    high_for_low = low_for_high = mixed = 0
    for sample, trials in trials_by_sample.items():
        if any(trial != trials[0] for trial in trials):
            mixed += 1
        elif trials[0] == high and standard_by_sample[sample] == low:
            high_for_low += 1
        elif trials[0] == low and standard_by_sample[sample] == high:
            low_for_high += 1
    bases = (sum(s == low for s in standard_by_sample.values()), sum(s == high for s in standard_by_sample.values()), len(trials_by_sample))
    return [(count, base, 100 * count / base if base else None) for count, base in zip((high_for_low, low_for_high, mixed), bases, strict=True)]


def test_each_sample_is_classified_once_as_a_consistent_error_in_one_direction_or_as_mixed():
    # S01-S04 have the Standard Pass, S05-S08 the Standard Fail; three trials each
    trials = {"S01": "PPP", "S02": "FFF", "S03": "PFP", "S04": "FFP", "S05": "FFF", "S06": "PPP", "S07": "FPF", "S08": "PPF"}
    rows = []
    for number, (sample, ratings) in enumerate(trials.items()):
        rows += rate(sample, ["Pass" if letter == "P" else "Fail" for letter in ratings], "Pass" if number < 4 else "Fail")
    assert columns(only(rows)) == [("#Pass/Fail", 1, 4, 25.0),   # S06: Fail Standard, always Pass
                                   ("#Fail/Pass", 1, 4, 25.0),   # S02: Pass Standard, always Fail
                                   ("#Mixed", 4, 8, 50.0)]       # S03, S04, S07, S08: wrong in one trial or in two, never counted a second time


def test_ten_samples_with_one_false_pass_and_one_mixed_give_the_percents_of_the_published_example():
    """'Six Sigma Case Studies with Minitab', chapter 12, as quoted in the task: 10 inspected samples, #Pass/Fail 1 with Percent 25.00,
    #Mixed 1 with Percent 10.00. The book's own data could not be read, so this study is built to have that shape (4 Fail samples,
    one of them always rated Pass; one sample rated Pass once and Fail once): it shows what the denominators give, and nothing more."""
    rows = []
    for number in range(1, 11):
        standard = "Pass" if number <= 6 else "Fail"
        ratings = ["Pass", "Fail"] if number == 3 else ["Pass", "Pass"] if number == 8 else [standard, standard]
        rows += rate(f"S{number:02d}", ratings, standard)
    assert columns(only(rows)) == [("#Pass/Fail", 1, 4, 25.0), ("#Fail/Pass", 0, 6, 0.0), ("#Mixed", 1, 10, 10.0)]


def random_binary_study(seed):
    """Appraisers, samples, trials, errors and a Standard drawn at random; the Standard may hold one class only. Returns the
    observations, each appraiser's trials of each sample, the Standard of each sample and the responses used."""
    rng = random.Random(seed)
    appraisers = [f"A{k}" for k in range(rng.randint(1, 3))]
    samples = [f"S{n:02d}" for n in range(rng.randint(4, 30))]
    trials, careless, share = rng.randint(1, 4), rng.choice([0.0, 0.15, 0.5]), rng.choice([0.0, 0.3, 0.5, 1.0])
    standard = {s: "Pass" if rng.random() < share else "Fail" for s in samples}
    rated = {}
    for who in appraisers:
        rated[who] = {}
        for sample in samples:
            wrong = "Fail" if standard[sample] == "Pass" else "Pass"
            roll = rng.random()
            rated[who][sample] = ([wrong] * trials if roll < careless / 2 else [rng.choice(["Pass", "Fail"]) for _ in range(trials)] if roll < careless
                                  else [standard[sample]] * trials)
    rows = [row for who in appraisers for sample in samples for row in rate(sample, rated[who][sample], standard[sample], who)]
    used = {r for who in appraisers for trial in rated[who].values() for r in trial} | set(standard.values())
    return rows, appraisers, rated, standard, used


@pytest.mark.parametrize("seed", range(150))
def test_the_counts_and_percents_equal_an_independent_count_of_random_studies(seed):
    rows, appraisers, rated, standard, used = random_binary_study(seed)
    result = only(rows)
    for index, who in enumerate(appraisers):
        disagreement = appraiser(result, index)["disagreement"]
        assert disagreement["applicable"] == (len(used) == 2), seed  # Minitab shows the table for exactly two responses
        if len(used) == 2:
            expected = brute_force_disagreement(rated[who], standard, "Fail", "Pass")
            assert [(c["count"], c["base"], c["percent"]) for c in disagreement["columns"]] == [
                (count, base, pytest.approx(percent) if percent is not None else None) for count, base, percent in expected], (seed, who)


def test_the_random_studies_reach_every_case_the_comparison_is_meant_to_cover():
    seen = {"not shown": 0, "pass/fail": 0, "fail/pass": 0, "mixed": 0, "no base": 0, "all three": 0, "several appraisers": 0, "one trial": 0}
    for seed in range(150):
        rows, appraisers, rated, standard, used = random_binary_study(seed)
        seen["several appraisers"] += len(appraisers) > 1
        seen["one trial"] += len(next(iter(rated[appraisers[0]].values()))) == 1
        if len(used) != 2:
            seen["not shown"] += 1
            continue
        for who in appraisers:
            (a, _, _), (b, _, _), (c, _, _) = brute_force_disagreement(rated[who], standard, "Fail", "Pass")
            seen["pass/fail"] += a > 0
            seen["fail/pass"] += b > 0
            seen["mixed"] += c > 0
            seen["all three"] += a > 0 and b > 0 and c > 0
            seen["no base"] += not any(standard[s] == "Fail" for s in standard) or not any(standard[s] == "Pass" for s in standard)
    assert all(count >= 5 for count in seen.values()), seen


def test_with_no_sample_of_one_standard_its_percent_is_none_not_zero_and_not_made_up():
    result = only(pass_only_rows({3: "FFF", 7: "PFP"}))  # every Standard is Pass, yet Fail is rated: two responses, one reference category
    assert columns(result) == [("#Pass/Fail", 0, 0, None), ("#Fail/Pass", 1, 30, pytest.approx(100 / 30)), ("#Mixed", 1, 30, pytest.approx(100 / 30))]
    perfect = only(pass_only_rows({3: "FFF"}, trials=3))  # a consistent false fail only
    assert columns(perfect)[0][3] is None and columns(perfect)[1][3] == pytest.approx(100 / 30)


def test_one_rating_per_sample_can_be_wrong_but_never_mixed():
    result = only(reference_rows(trials=1, mistakes={(3, 1), (20, 1)}))
    assert columns(result) == [("#Pass/Fail", 1, 15, pytest.approx(100 / 15)), ("#Fail/Pass", 1, 15, pytest.approx(100 / 15)), ("#Mixed", 0, 30, 0.0)]


def test_without_a_standard_there_is_no_disagreement_at_all_and_one_response_gives_none_either():
    assert appraiser(only([dataclasses.replace(r, standard="") for r in reference_rows(mistakes={(3, 1)})]))["disagreement"] is None
    one_response = only([dataclasses.replace(r, value="Pass", standard="Pass") for r in reference_rows()])
    assert not appraiser(one_response)["disagreement"]["applicable"] and appraiser(one_response)["disagreement"]["columns"] == ()


@pytest.mark.parametrize(("labels", "headings"), [(("PASS", "FAIL"), ["#PASS/FAIL", "#FAIL/PASS", "#Mixed"]), (("Pass", "Fail"), ["#Pass/Fail", "#Fail/Pass", "#Mixed"]),
                                                   (("P", "F"), ["#P/F", "#F/P", "#Mixed"]), (("1", "0"), ["#1/0", "#0/1", "#Mixed"])])
def test_the_columns_are_named_after_the_two_responses_of_the_study(labels, headings):
    """Minitab names the columns after the responses. They are put in order (Fail before Pass, F before P, 0 before 1) and the table
    starts with the later one rated against the earlier one's samples: #Pass/Fail, then #Fail/Pass, then #Mixed."""
    good, bad = labels
    rows = []
    for number in range(1, 9):
        standard = good if number <= 4 else bad
        rows += [Observation("Programming", f"S{number:02d}", bad if number == 2 else standard, trial=str(t), standard=standard) for t in (1, 2)]
    result = only(rows)
    assert [c[0] for c in columns(result)] == headings
    assert [c[1] for c in columns(result)] == [0, 1, 0]  # S02 is always rated the other way: the Standard is "good", the rating "bad"


def test_each_appraiser_has_a_row_of_their_own_and_the_overall_trial_level_figure_is_kept():
    result = only(two_appraisers(second_mistakes={(3, 1), (3, 2), (3, 3), (5, 1), (20, 1), (20, 2), (20, 3), (21, 2)}))
    ann, ben = columns(result, 0), columns(result, 1)
    assert [c[1] for c in ann] == [0, 0, 0]
    assert ben == [("#Pass/Fail", 1, 15, pytest.approx(100 / 15)), ("#Fail/Pass", 1, 15, pytest.approx(100 / 15)), ("#Mixed", 2, 30, pytest.approx(100 / 15))]
    trial_level = appraiser(result, 1)["disagreement"]  # the single ratings that differ from the Standard, over all of them, as before
    assert (trial_level["assessments"], trial_level["different"]) == (90, 8) and trial_level["percent"] == pytest.approx(100 * 8 / 90)


def test_the_known_standard_kappa_is_the_average_of_one_kappa_per_trial_against_the_standard():
    mistakes = {(2, 1), (7, 1), (9, 2), (14, 3), (15, 3), (16, 3), (28, 2)}
    rows = reference_rows(mistakes=mistakes)
    result = only(rows)
    n, trials = 30, 3

    def rated_pass(number, trial):  # the standard is Pass for samples 1 to 15; a mistake rates the other way
        return (number <= 15) != ((number, trial) in mistakes)

    kappas = []
    for trial in range(1, trials + 1):  # Scott's pi of the trial and the standard, from the definition (binary: the same for each response)
        agree = sum((number, trial) not in mistakes for number in range(1, n + 1))
        passes = sum(rated_pass(number, trial) for number in range(1, n + 1))
        share = (passes + 15) / (2 * n)
        expected = share**2 + (1 - share) ** 2
        kappas.append((agree / n - expected) / (1 - expected))
    row = appraiser(result)["kappa_standard"]["overall"]
    assert row["kappa"] == pytest.approx(sum(kappas) / trials, abs=1e-12)
    assert row["se"] == pytest.approx(math.sqrt(1 / (n * trials))) and row["z"] == pytest.approx(row["kappa"] / row["se"])
    assert 0 < row["p"] < 1e-6


# ----------------------------------------------------------------------------- the data the study needs
def messages(result):
    return [issue.message for issue in result.issues]


def errors(result):
    return [issue.message for issue in result.issues if issue.severity == "error"]


def test_without_a_standard_only_agreement_within_the_appraiser_is_computed():
    rows = [dataclasses.replace(row, standard="") for row in reference_rows()]
    result = only(rows)
    assert result.valid and result.metrics["within_percent"] == 100
    assert result.metrics["standard_percent"] is None and result.metrics["kappa_standard"] is None
    assert appraiser(result)["standard"] is None and appraiser(result)["disagreement"] is None
    assert "No Standard: only Within Appraisers agreement is computed." in messages(result)


def assert_the_standard_alone_is_unusable(result, problem):
    """Within Appraisers does not depend on the Standard, so only what does is not computed."""
    assert result.valid and not errors(result)
    assert result.metrics["within_percent"] == 100 and result.metrics["within_matched"] == 30  # still there
    assert result.metrics["standard_percent"] is None and result.metrics["kappa_standard"] is None
    only_appraiser = appraiser(result)
    assert only_appraiser["standard"] is None and only_appraiser["kappa_standard"] is None and only_appraiser["disagreement"] is None
    assert result.details["standard_known"] is False and result.details["standard_problem"] == problem
    assert result.details["all_standard"] is None
    warning = f"Appraiser vs Standard is not computed. {problem}"
    assert warning in [i.message for i in result.issues if i.severity == "warning"]
    assert "No Standard: only Within Appraisers agreement is computed." not in messages(result)  # one was given: it is not "no Standard"


def test_a_standard_given_to_some_samples_only_stops_the_comparison_with_it_but_not_the_rest():
    rows = [dataclasses.replace(row, standard="") if row.sample_id == "S05" else row for row in reference_rows()]
    assert_the_standard_alone_is_unusable(only(rows), "The Standard is missing for 1 of 30 samples.")


def test_a_sample_with_two_different_standards_stops_the_comparison_with_it_but_not_the_rest():
    rows = reference_rows()
    rows[0] = dataclasses.replace(rows[0], standard="Fail")  # S01 is Pass in its other two ratings
    assert_the_standard_alone_is_unusable(only(rows), "Inconsistent Standard: samples S01 have more than one.")


def test_a_standard_given_on_the_first_rating_of_each_sample_only_is_not_silently_ignored():
    rows = [dataclasses.replace(row, standard="") if row.trial != "1" else row for row in reference_rows()]
    assert_the_standard_alone_is_unusable(only(rows), "The Standard is missing for 30 of 30 samples.")


def test_both_problems_are_named_and_a_complete_standard_is_not_a_problem():
    rows = reference_rows()
    rows[0] = dataclasses.replace(rows[0], standard="Fail")
    rows[10] = dataclasses.replace(rows[10], standard="")
    problem = only(rows).details["standard_problem"]
    assert "Inconsistent Standard: samples S01" in problem and "The Standard is missing for 1 of 30 samples." in problem
    assert only(reference_rows()).details["standard_problem"] == ""


def test_a_standard_problem_leaves_acceptance_of_within_agreement_but_never_passes_the_study():
    rows = [dataclasses.replace(row, standard="") if row.sample_id == "S05" else row for row in reference_rows()]
    result = only(rows, AnalysisConfig(method="attribute", agreement_min=90))
    assert result.details["agreement_status"] == {"within": PASS, "standard": NOT_EVALUATED} and result.status == NOT_EVALUATED


def test_one_response_category_gives_agreement_but_no_kappa():
    rows = [dataclasses.replace(row, value="Pass", standard="Pass") for row in reference_rows()]
    result = only(rows)  # Minitab: "Unique value in assessments and standards across samples. Cannot compute kappa."
    assert result.valid and result.metrics["within_percent"] == 100 and result.metrics["standard_percent"] == 100
    assert result.metrics["kappa_within"] is None and result.metrics["kappa_standard"] is None
    table = appraiser(result)["kappa_within"]
    assert table["reason"] and table["overall"]["kappa"] is None and table["rows"][0]["se"] is None
    assert any("kappa cannot be computed" in message for message in messages(result))
    assert not appraiser(result)["disagreement"]["applicable"]  # the table needs exactly two levels


def test_a_single_trial_has_no_within_agreement_but_still_agrees_with_the_standard():
    result = only(reference_rows(trials=1))
    assert result.valid and appraiser(result)["within"] is None and appraiser(result)["kappa_within"] is None
    assert result.metrics["within_percent"] is None and result.metrics["standard_percent"] == 100
    assert appraiser(result)["kappa_standard"]["overall"]["kappa"] == pytest.approx(1.0)
    assert appraiser(result)["kappa_standard"]["overall"]["se"] == pytest.approx(math.sqrt(1 / 30))


@pytest.mark.parametrize("damage,fragment", [
    (lambda rows: rows[:-1], "Every appraiser must rate every sample the same number of times"),
    (lambda rows: [dataclasses.replace(r, trial="") if i == 3 else r for i, r in enumerate(rows)], "Trial is missing for some ratings"),
    (lambda rows: [dataclasses.replace(r, trial="1") if i == 1 else r for i, r in enumerate(rows)], "Duplicate trial identity: S01 / 1 / 1"),
    (lambda rows: [dataclasses.replace(r, sample_id="") if i == 0 else r for i, r in enumerate(rows)], "Missing Sample ID in 1 rating"),
    (lambda rows: [dataclasses.replace(r, value="") if i == 5 else r for i, r in enumerate(rows)], "Missing rating for 1 assessment"),
    (lambda rows: [*rows, rows[0]], "Duplicate source"),
])
def test_missing_duplicate_and_unequal_ratings_are_refused_not_guessed(damage, fragment):
    result = only(damage(reference_rows()))
    assert not result.valid and any(fragment in message for message in errors(result)), messages(result)
    assert result.status == NOT_EVALUATED and all(value is None for value in result.metrics.values())


def test_responses_that_differ_only_by_letter_case_are_flagged_not_merged():
    rows = reference_rows()
    rows[0] = dataclasses.replace(rows[0], value="PASS")
    result = only(rows)
    assert result.valid and any("differ only by letter case" in issue.message for issue in result.issues if issue.severity == "warning")
    assert appraiser(result)["within"]["matched"] == 29  # "PASS" is not "Pass"


def test_the_appraiser_column_is_the_operator_and_blank_names_are_one_unnamed_appraiser():
    named = only([dataclasses.replace(r, operator="Ann") for r in reference_rows()])
    assert appraiser(named)["name"] == "Ann" and appraiser(named)["label"] == "Ann"
    assert appraiser(only(reference_rows()))["label"] == "1" and only(reference_rows()).system == ""


# ----------------------------------------------------------------------------- several appraisers
def two_appraisers(second_mistakes=()):
    rows = []
    for name, mistakes in (("Ann", ()), ("Ben", second_mistakes)):
        rows += [dataclasses.replace(r, operator=name, source=f"{name}/{r.source}") for r in reference_rows(mistakes=mistakes)]
    return rows


def test_each_appraiser_is_analysed_and_the_appraisers_are_compared():
    result = only(two_appraisers(second_mistakes={(5, 1)}))
    assert result.valid and result.parts == 30 and result.repeats == 3 and len(result.details["appraisers"]) == 2
    ann, ben = result.details["appraisers"]
    assert (ann["label"], ann["within"]["matched"]) == ("Ann", 30) and ben["within"]["matched"] == 29 and ben["standard"]["matched"] == 29
    assert result.details["between"]["matched"] == 29 and result.details["all_standard"]["matched"] == 29
    assert result.details["kappa_between"]["overall"]["kappa"] < 1
    assert result.metrics["between_percent"] == pytest.approx(100 * 29 / 30)
    assert result.metrics["within_percent"] is None and result.metrics["standard_percent"] is None  # one figure per appraiser instead
    assert result.details["kappa_between"]["overall"]["se"] == pytest.approx(math.sqrt(2 / (30 * 6 * 5)))  # m is the trials of both appraisers


def test_all_appraisers_against_the_standard_has_a_kappa_only_with_a_standard_and_several_appraisers():
    rows = two_appraisers(second_mistakes={(5, 1), (6, 2), (20, 3)})
    result = only(rows)
    pooled, (ann, ben) = result.details["kappa_all_standard"], [a["kappa_standard"] for a in result.details["appraisers"]]
    assert [r["response"] for r in pooled["rows"]] == ["Fail", "Pass"] and pooled["reason"] == ""
    assert pooled["overall"]["kappa"] == pytest.approx((ann["overall"]["kappa"] + ben["overall"]["kappa"]) / 2)
    assert pooled["overall"]["se"] ** 2 == pytest.approx((ann["overall"]["se"] ** 2 + ben["overall"]["se"] ** 2) / 4)
    assert ben["overall"]["kappa"] < pooled["overall"]["kappa"] < ann["overall"]["kappa"] == 1  # Ann is perfect, Ben is not
    assert only([dataclasses.replace(r, standard="") for r in rows]).details["kappa_all_standard"] is None  # no Standard
    assert only(reference_rows()).details["kappa_all_standard"] is None  # one appraiser: that appraiser's own table is the answer


def test_all_appraisers_against_the_standard_is_n_a_when_the_ratings_hold_one_category():
    rows = [r for name in ("Ann", "Ben") for n in range(1, 11) for r in rate(f"S{n:02d}", ["Pass"] * 3, "Pass", appraiser=name)]
    pooled = only(rows).details["kappa_all_standard"]
    assert pooled["overall"]["kappa"] is None and all(r["kappa"] is None for r in pooled["rows"]) and pooled["reason"]


def test_an_appraiser_who_did_not_rate_every_sample_is_refused():
    rows = [r for r in two_appraisers() if not (r.operator == "Ben" and r.sample_id == "S07")]
    result = only(rows)
    assert not result.valid and any("S07 by Ben (0)" in message for message in errors(result))


def test_some_ratings_without_an_appraiser_when_others_have_one_is_refused():
    rows = two_appraisers()
    rows[0] = dataclasses.replace(rows[0], operator="")
    assert any("Missing operator identifier" in message for message in errors(only(rows)))


# ----------------------------------------------------------------------------- acceptance is a separate step
def test_acceptance_is_off_by_default_and_never_changes_a_statistic():
    rows = reference_rows(mistakes={(4, 2)})
    assert only(rows).status == NOT_EVALUATED and only(rows).decision_metric == ""
    plain = compute(rows, ATTRIBUTE)[0]
    judged = only(rows, AnalysisConfig(method="attribute", agreement_min=90))
    assert plain.metrics == judged.metrics and plain.details["appraisers"] == judged.details["appraisers"]
    assert judged.status == PASS and judged.decision_metric == "agreement"
    assert judged.details["agreement_status"] == {"within": PASS, "standard": PASS} and judged.details["agreement_min"] == 90


def test_within_and_against_the_standard_are_judged_independently_at_exactly_the_minimum():
    thirty = {(n, 2) for n in range(1, 4)}  # 3 of 30 samples rated inconsistently: 27 of 30 = 90 %
    exactly = only(reference_rows(mistakes=thirty), AnalysisConfig(method="attribute", agreement_min=90))
    assert exactly.metrics["within_matched"] == 27 and exactly.status == PASS  # at the minimum: PASS
    below = only(reference_rows(mistakes=thirty), AnalysisConfig(method="attribute", agreement_min=90.1))
    assert below.status == FAIL and below.details["agreement_status"] == {"within": FAIL, "standard": FAIL}
    consistent_error = {(n, t) for n in (1, 2, 3, 4) for t in (1, 2, 3)}  # always wrong: within is 100 %, vs standard 26 of 30
    split = only(reference_rows(mistakes=consistent_error), AnalysisConfig(method="attribute", agreement_min=90))
    assert split.details["agreement_status"] == {"within": PASS, "standard": FAIL} and split.status == FAIL


def test_a_missing_standard_is_not_evaluated_and_never_a_pass():
    rows = [dataclasses.replace(row, standard="") for row in reference_rows()]
    result = only(rows, AnalysisConfig(method="attribute", agreement_min=90))
    assert result.details["agreement_status"] == {"within": PASS, "standard": NOT_EVALUATED} and result.status == NOT_EVALUATED
    failing = only([dataclasses.replace(r, standard="") for r in reference_rows(mistakes={(1, 2), (2, 2), (3, 2), (4, 2)})],
                   AnalysisConfig(method="attribute", agreement_min=90))
    assert failing.status == FAIL  # a failure is still a failure without a standard


def test_several_appraisers_must_each_meet_the_minimum():
    details = only(two_appraisers(second_mistakes={(n, 2) for n in range(1, 8)})).details
    assert attribute_acceptance(details, 90) == (FAIL, {"within": FAIL, "standard": FAIL})
    assert attribute_acceptance(details, 70) == (PASS, {"within": PASS, "standard": PASS})
    assert attribute_acceptance(details, None) == (NOT_EVALUATED, {"within": NOT_EVALUATED, "standard": NOT_EVALUATED})


@pytest.mark.parametrize("kwargs", [{"agreement_min": 0}, {"agreement_min": 101}, {"agreement_min": True}, {"confidence": 1},
                                    {"confidence": 0}, {"confidence": math.nan}, {"confidence": True}])
def test_the_new_settings_are_validated(kwargs):
    with pytest.raises(ValueError):
        analyze(reference_rows(), AnalysisConfig(method="attribute", **kwargs))


def test_the_confidence_level_sets_the_interval_and_nothing_else():
    ninety, ninety_nine = (only(reference_rows(), AnalysisConfig(method="attribute", confidence=c)) for c in (0.90, 0.99))
    assert appraiser(ninety)["within"]["lower"] == pytest.approx(100 * 0.10 ** (1 / 30)) and appraiser(ninety_nine)["within"]["lower"] == pytest.approx(100 * 0.01 ** (1 / 30))
    assert ninety.metrics == ninety_nine.metrics and ninety.details["confidence"] == 0.90


# ----------------------------------------------------------------------------- the rest of the application
def test_standard_is_part_of_the_dataset_fingerprint_only_when_there_is_one():
    rows = reference_rows()
    without = [dataclasses.replace(r, standard="") for r in rows]
    assert Dataset.from_observations(rows).fingerprint != Dataset.from_observations(without).fingerprint
    assert Dataset.from_observations(without).fingerprint == Dataset.from_observations([dataclasses.replace(r, standard=" ") for r in without]).fingerprint
    plain = [Observation("X", "S1", 1.5, 0, 2, trial="1", source="a")]
    assert Dataset.from_observations(plain).fingerprint == Dataset.from_observations(
        [dataclasses.replace(plain[0], standard="")]).fingerprint


def test_a_study_runs_the_attribute_method_and_keeps_its_results_current():
    study = Study(Dataset.from_observations(reference_rows()), options=StatisticalOptions(method="attribute"))
    result_set = study.run_statistics()
    assert dict(result_set.method_verification) == {"attribute_agreement": PENDING_VERIFICATION}
    assert METHOD_VERIFICATION["attribute_agreement"] == PENDING_VERIFICATION and not study.is_stale(result_set)
    study.options = dataclasses.replace(study.options, study_factor=4.0)  # a Gage R&R option: it cannot change this analysis
    assert not study.is_stale(result_set)
    study.options = dataclasses.replace(study.options, confidence=0.9)
    assert study.stale_reasons(result_set) == ("options",)
    evaluated = study.evaluate(result_set, EvaluationSettings(agreement_min=90))
    assert evaluated.record.judged and evaluated.record.criteria_snapshot == {"kind": "attribute", "agreement_min": 90}
    assert evaluated.results[0].status == PASS and evaluated.record.validation.conditions == ()
    unjudged = study.evaluate(result_set, judge=False)
    assert not unjudged.record.judged and unjudged.results[0].status == NOT_EVALUATED
    assert unjudged.results[0].metrics == evaluated.results[0].metrics


def test_the_ratings_can_be_mapped_from_the_scanned_logs_and_a_standard_from_a_constant():
    def record(sn, name, value):
        return LogRecord(path=Path(f"{sn}_{name}.log"), sn=sn, entries={"Result": Measurement("Result", value)})

    grouped = {"SN1": [record("SN1", "a", "Pass"), record("SN1", "b", "Pass")], "SN2": [record("SN2", "a", "Fail"), record("SN2", "b", "Pass")]}
    observations = normalize_records(grouped, ["Result"], {"standard": "=Pass"}, assign_trials=True)
    assert [(o.sample_id, o.value, o.trial, o.standard) for o in observations] == [
        ("SN1", "Pass", "1", "Pass"), ("SN1", "Pass", "2", "Pass"), ("SN2", "Fail", "1", "Pass"), ("SN2", "Pass", "2", "Pass")]
    result = only(observations)
    assert result.valid and result.metrics["within_matched"] == 1 and result.metrics["standard_matched"] == 1


def test_the_method_explanation_names_the_formulas_that_are_implemented():
    text = explain_method(AnalysisConfig(method="attribute", agreement_min=90))
    for expected in ("Clopper-Pearson", "alpha^(1/N)", "Fleiss' kappa", "2/(n", "never PASS", "90 %"):
        assert expected in text
    assert "not calculated" in text and "#Mixed" in text  # what is left out is said
