"""Attribute Agreement Analysis: how well categorical ratings agree with themselves and with a known standard.

It follows Minitab's Stat > Quality Tools > Attribute Agreement Analysis. One test item is one study: every sample is rated
by one or more appraisers over repeated trials, and every sample may carry a known Standard. The statistics are:

* Percent agreement, counted per sample: Within Appraisers (all of an appraiser's trials of the sample agree), Appraiser vs
  Standard (all of them equal the Standard), Between Appraisers and All Appraisers vs Standard (the same over all appraisers).
* An exact confidence interval for each percent (``agreement_interval``).
* Fleiss' kappa for each response and overall, with its standard error under H0, Z and the one-sided P value (``fleiss``).
* Assessment Disagreement (``_disagreement``), for a known Standard and exactly two response levels: each appraiser's samples
  are classified once, as #X/Y (every trial rated X while the Standard is Y) or #Mixed (the trials differ), each with its
  percent of the samples whose Standard is Y (of all samples for #Mixed). The trial-level 100 x c / N is kept beside it.

Nothing here judges the result. Acceptance (a minimum agreement) is applied afterwards, in ``acceptance.attribute_acceptance``.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence

from .models import ATTRIBUTE_METRICS, AnalysisConfig, Issue, Observation
from .numeric import regularized_beta

KAPPA_UNDEFINED = "Only one response category in the ratings and the standard, so kappa cannot be computed."


# ----------------------------------------------------------------------------- exact confidence interval
def _beta_quantile(probability: float, a: float, b: float) -> float:
    """x with I_x(a, b) = probability, by bisection on the regularized incomplete beta function."""
    low, high = 0.0, 1.0
    for _ in range(90):
        middle = (low + high) / 2
        if regularized_beta(middle, a, b) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def agreement_interval(matched: int, inspected: int, confidence: float = 0.95) -> tuple[float, float]:
    """Exact (Clopper-Pearson) confidence limits of matched/inspected, as proportions.

    Each side holds alpha/2 of the probability, except at the boundary: with every sample matched the lower limit holds all
    of alpha (alpha^(1/n)) and the upper limit is 1; with none matched the lower limit is 0 and the upper holds all of alpha.
    This is what reproduces Minitab's published 30 of 30 = (90.50, 100.00) and 50 of 50 = (94.18, 100.00); a plain two-sided
    interval would give 88.43 and 92.89.
    """
    if inspected < 1 or not 0 <= matched <= inspected:
        raise ValueError("The number matched must be between 0 and the number inspected, and at least one sample is needed.")
    alpha = 1 - confidence
    if matched == inspected:
        return alpha ** (1 / inspected), 1.0
    if matched == 0:
        return 0.0, 1 - alpha ** (1 / inspected)
    return (_beta_quantile(alpha / 2, matched, inspected - matched + 1),
            _beta_quantile(1 - alpha / 2, matched + 1, inspected - matched))


def _agreement(matched: int, inspected: int, confidence: float) -> dict:
    lower, upper = agreement_interval(matched, inspected, confidence)
    return {"inspected": inspected, "matched": matched, "percent": 100 * matched / inspected,
            "lower": 100 * lower, "upper": 100 * upper}


# ----------------------------------------------------------------------------- Fleiss' kappa
def _upper_tail(z: float) -> float:
    """P(Z > z) for a standard normal Z, accurate in the tail (it reads 0.0000 for the published Z of 9.48683)."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def fleiss(counts: Sequence[Sequence[int]], trials: int) -> dict:
    """Fleiss' kappa of ``counts[i][j]`` = the ratings of sample i that fall in category j, ``trials`` ratings per sample.

    Returns the kappa of each category and the overall kappa, with the variance under H0 (kappa = 0):
    Var(Kj) = 2 / (n m (m - 1)), and for the overall kappa the same times
    ((sum pq)^2 - sum pq (q - p)) / (sum pq)^2, where p is the proportion of all ratings in a category and q = 1 - p.
    A kappa that has no variation to measure (a category that holds none or all of the ratings) is None.
    """
    n, m = len(counts), trials
    categories = len(counts[0]) if counts else 0
    if n < 1 or m < 2 or any(sum(row) != m for row in counts):
        raise ValueError("Kappa needs the same number of at least two ratings for every sample.")
    pairs = n * m * (m - 1)
    share = [sum(row[j] for row in counts) / (n * m) for j in range(categories)]
    spread = [p * (1 - p) for p in share]
    variance = 2 / pairs
    per_category = []
    for j in range(categories):
        if spread[j] <= 0:
            per_category.append((None, variance))
        else:
            per_category.append((1 - sum(row[j] * (m - row[j]) for row in counts) / (pairs * spread[j]), variance))
    expected = sum(p * p for p in share)
    observed = sum(x * (x - 1) for row in counts for x in row) / pairs
    total = sum(spread)
    if expected >= 1 or total <= 0:
        return {"categories": per_category, "overall": (None, variance)}
    overall_variance = variance * (total * total - sum(s * (1 - 2 * p) for s, p in zip(spread, share, strict=True))) / (total * total)
    return {"categories": per_category, "overall": ((observed - expected) / (1 - expected), overall_variance)}


def _statistic(response: str, kappa: float | None, variance: float | None) -> dict:
    if kappa is None or variance is None:
        return {"response": response, "kappa": None, "se": None, "z": None, "p": None}
    se = math.sqrt(variance)
    z = kappa / se
    return {"response": response, "kappa": kappa, "se": se, "z": z, "p": _upper_tail(z)}


def _kappa_table(levels: Sequence[str], estimates: dict, present: Sequence[bool]) -> dict:
    """The kappa rows of one table: each response that occurs, then Overall; ``reason`` says why a kappa is missing."""
    rows = [_statistic(level, *estimates["categories"][j]) for j, level in enumerate(levels) if present[j]]
    overall = _statistic("Overall", *estimates["overall"])
    return {"rows": tuple(rows), "overall": overall,
            "reason": "" if overall["kappa"] is not None and all(r["kappa"] is not None for r in rows) else KAPPA_UNDEFINED}


def _counts(groups: Sequence[Sequence[str]], levels: Sequence[str]) -> list[list[int]]:
    return [[list(group).count(level) for level in levels] for group in groups]


def _kappa_within(groups: Sequence[Sequence[str]], trials: int, levels: Sequence[str]) -> dict:
    """Agreement among the ``trials`` ratings each sample got (one appraiser, or all appraisers together)."""
    counts = _counts(groups, levels)
    present = [any(row[j] for row in counts) for j in range(len(levels))]
    return _kappa_table(levels, fleiss(counts, trials), present)


def _kappa_against_standard(ratings: Sequence[Sequence[str]], standard: Sequence[str], levels: Sequence[str]) -> dict:
    """Known Standard: kappa of every trial with the Standard as a second trial, averaged over the trials. The variance of the
    average is the sum of the variances divided by trials squared."""
    trials = len(ratings[0])
    runs = [fleiss(_counts([(row[t], standard[i]) for i, row in enumerate(ratings)], levels), 2) for t in range(trials)]
    present = [any(row[t] == level or standard[i] == level for i, row in enumerate(ratings) for t in range(trials))
               for level in levels]

    def average(position) -> tuple[float | None, float | None]:
        kappas = [position(run)[0] for run in runs]
        if any(k is None for k in kappas):
            return None, None
        return math.fsum(kappas) / trials, math.fsum(position(run)[1] for run in runs) / trials ** 2

    estimates = {"categories": [average(lambda run, j=j: run["categories"][j]) for j in range(len(levels))],
                 "overall": average(lambda run: run["overall"])}
    return _kappa_table(levels, estimates, present)


def _kappa_all_standard(tables: Sequence[dict], levels: Sequence[str]) -> dict:
    """All appraisers against the Standard: the mean of the appraisers' kappas against the Standard, with the sum of their
    variances over the number of appraisers squared as its variance. Minitab's published tables (Textile print quality, 4
    appraisers x 2 trials x 50 samples, 5 responses) are reproduced to every printed digit. A response that is not in the
    table of every appraiser has no mean, so it reads N/A."""
    count = len(tables)

    def mean(statistics: Sequence[dict | None]) -> tuple[float | None, float | None]:
        if any(s is None or s["kappa"] is None for s in statistics):
            return None, None
        return math.fsum(s["kappa"] for s in statistics) / count, math.fsum(s["se"] ** 2 for s in statistics) / count ** 2

    by_response = [{r["response"]: r for r in table["rows"]} for table in tables]
    present = [any(level in rows for rows in by_response) for level in levels]
    estimates = {"categories": [mean([rows.get(level) for rows in by_response]) if shown else (None, None)
                                for level, shown in zip(levels, present, strict=True)],
                 "overall": mean([table["overall"] for table in tables])}
    return _kappa_table(levels, estimates, present)


# ----------------------------------------------------------------------------- disagreement with the Standard
def _disagreement_column(heading: str, count: int, base: int) -> dict:
    """One count of the table with the number it is a percent of; with nothing to divide by there is no percent."""
    return {"heading": heading, "count": count, "base": base, "percent": 100 * count / base if base else None}


def _disagreement(ratings: Sequence[Sequence[str]], standard: Sequence[str] | None, levels: Sequence[str]) -> dict:
    """Assessment Disagreement of one appraiser. Minitab shows it only with a known Standard and exactly two response levels.

    Each sample is counted once. When the appraiser rated it the same way in every trial but not as its Standard says, it is
    ``#X/Y`` (every trial X, the Standard Y; with levels Fail and Pass, #Pass/Fail is a false pass and #Fail/Pass a false fail).
    When the trials differ it is ``#Mixed``, whatever the Standard is. Percent: ``#X/Y`` over the samples whose Standard is Y,
    ``#Mixed`` over all samples. ``columns`` lists them in the order of Minitab's table. The trial-level figure (single ratings
    that differ from the Standard over all ratings) stays in ``assessments``, ``different`` and ``percent``."""
    empty = {"applicable": False, "samples": None, "columns": (), "assessments": None, "different": None, "percent": None, "by_direction": ()}
    if standard is None or len(levels) != 2:
        return empty
    first, second = levels
    against = Counter((trials[0], expected) for trials, expected in zip(ratings, standard, strict=True)
                      if len(set(trials)) == 1 and trials[0] != expected)  # (rated, Standard) of the samples consistently rated against it
    mixed = sum(len(set(trials)) > 1 for trials in ratings)
    reference = Counter(standard)
    columns = (_disagreement_column(f"#{second}/{first}", against[(second, first)], reference[first]),
               _disagreement_column(f"#{first}/{second}", against[(first, second)], reference[second]),
               _disagreement_column("#Mixed", mixed, len(ratings)))
    pairs = [(rating, standard[i]) for i, row in enumerate(ratings) for rating in row]
    different = Counter((rating, expected) for rating, expected in pairs if rating != expected)
    total, count = len(pairs), sum(different.values())
    return {"applicable": True, "samples": len(ratings), "columns": columns, "assessments": total, "different": count,
            "percent": 100 * count / total, "by_direction": tuple((rating, expected, n) for (rating, expected), n in sorted(different.items()))}


# ----------------------------------------------------------------------------- reading the observations
def _category(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _trial_order(trial: str) -> tuple:
    try:
        return 0, float(trial), trial
    except ValueError:
        return 1, 0.0, trial


def _first(items: Sequence[str], limit: int = 4) -> str:
    return ", ".join(items[:limit]) + (" ..." if len(items) > limit else "")


def _read(rows: Sequence[Observation], issues: list[Issue]):
    """(samples, appraisers, ratings[appraiser][sample] -> [ratings in trial order], standard[sample] | None, problem), or None
    when the data cannot be analysed (an error was added to ``issues`` for each reason).

    A Standard that is not usable does not stop the analysis: ``standard`` is then None and ``problem`` says why, so that
    Within Appraisers is still computed and only what depends on the Standard is not. The Standard is usable when every rating
    of a sample carries it, the same one, for every sample. A study that gives none at all has no problem: it has no Standard."""
    entries = [(str(r.sample_id).strip(), str(r.operator).strip(), str(r.trial).strip(), _category(r.value), _category(r.standard), r)
               for r in rows]
    problems = len(issues)
    blank = [e for e in entries if not e[0]]
    if blank:
        issues.append(Issue("error", f"Missing Sample ID in {len(blank)} rating(s) (first: {blank[0][5].source or 'a rating'})."))
    unrated = [e[0] for e in entries if e[0] and not e[3]]
    if unrated:
        issues.append(Issue("error", f"Missing rating for {len(unrated)} assessment(s); samples {_first(list(dict.fromkeys(unrated)))}."))
    sources = Counter(e[5].source for e in entries if e[5].source)
    if any(count > 1 for count in sources.values()):
        issues.append(Issue("error", "Duplicate source: the same logfile occurs more than once in this test item."))
    if len(issues) > problems:
        return None
    samples = tuple(dict.fromkeys(e[0] for e in entries))
    appraisers = tuple(dict.fromkeys(e[1] for e in entries))
    trials = [e[2] for e in entries]
    if any(trials) and not all(trials):
        issues.append(Issue("error", "Trial is missing for some ratings. Map every trial, or none."))
    cells: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for sample, appraiser, trial, rating, _standard, _row in entries:
        cells[(sample, appraiser)].append((trial, rating))
    if all(trials):
        repeated = [f"{s} / {a or '1'} / {t}" for (s, a), cell in cells.items() for t, n in Counter(t for t, _ in cell).items() if n > 1]
        if repeated:
            issues.append(Issue("error", f"Duplicate trial identity: {_first(repeated)}."))
    counts = {cell: len(items) for cell, items in cells.items()}
    sizes = {counts.get((s, a), 0) for s in samples for a in appraisers}
    if len(sizes) > 1:
        uneven = [f"{s} by {a or 'the appraiser'} ({counts.get((s, a), 0)})" for s in samples for a in appraisers
                  if counts.get((s, a), 0) != max(sizes)]
        issues.append(Issue("error", "Every appraiser must rate every sample the same number of times; "
                                     f"fewer ratings: {_first(uneven)}."))
    given: dict[str, set[str]] = defaultdict(set)
    for sample, _appraiser, _trial, _rating, standard, _row in entries:
        given[sample].add(standard)
    inconsistent = [s for s, values in given.items() if len({v for v in values if v}) > 1]
    provided = any(value for values in given.values() for value in values)
    lacking = [s for s, values in given.items() if "" in values] if provided else []
    reasons = ([f"Inconsistent Standard: samples {_first(inconsistent)} have more than one."] if inconsistent else []) + \
              ([f"The Standard is missing for {len(lacking)} of {len(samples)} samples."] if lacking else [])
    if any(issue.severity == "error" for issue in issues[problems:]):
        return None
    ratings = {a: {s: [r for _, r in sorted(cells[(s, a)], key=lambda item: _trial_order(item[0]))] if all(trials)
                   else [r for _, r in cells[(s, a)]] for s in samples} for a in appraisers}
    standard = {s: next(v for v in given[s] if v) for s in samples} if provided and not reasons else None
    return samples, appraisers, ratings, standard, " ".join(reasons)


# ----------------------------------------------------------------------------- the analysis
def attribute_calculation(
    rows: Sequence[Observation], values: Sequence[float], low: float | None, high: float | None, config: AnalysisConfig,
) -> tuple[dict, dict, list[Issue]]:
    """Agreement statistics of one test item. ``values``, ``low`` and ``high`` belong to the numeric methods and are not used."""
    metrics = dict.fromkeys(ATTRIBUTE_METRICS)
    details: dict = {"model": "Attribute agreement analysis of categorical ratings", "confidence": config.confidence,
                     "interval": "Exact (Clopper-Pearson); at 0 % or 100 % the limit at the boundary holds all of alpha"}
    issues: list[Issue] = []
    read = _read(rows, issues)
    if read is None:
        return metrics, details, issues
    samples, appraisers, ratings, standard, problem = read
    trials = len(ratings[appraisers[0]][samples[0]])
    levels = tuple(sorted({r for table in ratings.values() for group in table.values() for r in group}
                          | set(standard.values() if standard else ()), key=lambda text: (text.casefold(), text)))
    folded = Counter(level.casefold() for level in levels)
    if any(count > 1 for count in folded.values()):
        issues.append(Issue("warning", "Responses that differ only by letter case are treated as different categories: "
                                       + _first([level for level in levels if folded[level.casefold()] > 1]) + "."))
    confidence, n = config.confidence, len(samples)
    details.update({"samples": n, "trials": trials, "levels": levels, "standard_known": standard is not None,
                    "standard_problem": problem, "sample_ids": samples})
    results = []
    for appraiser in appraisers:
        table = ratings[appraiser]
        grid = [table[s] for s in samples]
        item = {"name": appraiser, "label": appraiser or "1", "trials": trials, "within": None, "standard": None,
                "kappa_within": None, "kappa_standard": None, "disagreement": None}
        if trials >= 2:
            item["within"] = _agreement(sum(len(set(group)) == 1 for group in grid), n, confidence)
            item["kappa_within"] = _kappa_within(grid, trials, levels)
        if standard is not None:
            expected = [standard[s] for s in samples]
            item["standard"] = _agreement(sum(all(r == e for r in group) for group, e in zip(grid, expected, strict=True)), n, confidence)
            item["kappa_standard"] = _kappa_against_standard(grid, expected, levels)
            item["disagreement"] = _disagreement(grid, expected, levels)
        results.append(item)
    details["appraisers"] = tuple(results)
    details["between"] = details["all_standard"] = details["kappa_between"] = details["kappa_all_standard"] = None
    if len(appraisers) > 1:
        pooled = [[r for a in appraisers for r in ratings[a][s]] for s in samples]
        details["between"] = _agreement(sum(len(set(group)) == 1 for group in pooled), n, confidence)
        details["kappa_between"] = _kappa_within(pooled, len(pooled[0]), levels)
        if standard is not None:
            details["all_standard"] = _agreement(sum(all(r == standard[s] for r in group) for s, group in zip(samples, pooled, strict=True)),
                                                 n, confidence)
            details["kappa_all_standard"] = _kappa_all_standard([item["kappa_standard"] for item in results], levels)
    if len(levels) < 2:
        issues.append(Issue("info", KAPPA_UNDEFINED))
    if problem:
        issues.append(Issue("warning", f"Appraiser vs Standard is not computed. {problem}"))
    elif standard is None:
        issues.append(Issue("info", "No Standard: only Within Appraisers agreement is computed."))
    if trials < 2:
        issues.append(Issue("info", "One rating per sample: Within Appraisers agreement and its kappa need at least two trials."))
    if len(appraisers) == 1:  # the summary of a study with one appraiser; with several, each appraiser is in the details
        only = results[0]
        for key, source in (("within", "within"), ("standard", "standard")):
            if only[source]:
                metrics.update({f"{key}_percent": only[source]["percent"], f"{key}_matched": only[source]["matched"],
                                f"{key}_inspected": only[source]["inspected"]})
        metrics["kappa_within"] = only["kappa_within"]["overall"]["kappa"] if only["kappa_within"] else None
        metrics["kappa_standard"] = only["kappa_standard"]["overall"]["kappa"] if only["kappa_standard"] else None
    if details["between"]:
        metrics["between_percent"] = details["between"]["percent"]
    if details["all_standard"]:
        metrics["all_standard_percent"] = details["all_standard"]["percent"]
    return metrics, details, issues
