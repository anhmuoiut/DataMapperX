"""Data checks: what to look at before trusting a result.

The idea is that of the Report Card in Minitab's Assistant: a short list of plain statements, each one fine, for your
information, or worth a look. The figures they rest on (10 and 35 parts, 3 to 5 operators, 100 observations, tests 1 and
2 of the control charts, the Anderson-Darling test at p < 0.05, the 10 % / 30 % and 1 % / 9 % guidelines, 5 distinct
categories) are the ones Minitab publishes in its Assistant white papers and its help on measurement-system acceptance.
The wording is our own.

Nothing here changes a calculated value, blocks a result, or goes into a report. These checks are screening aids and are
not yet compared with Minitab output (see docs/statistical-validation.md).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..utils import safe_text, to_number
from .grr import R_CONSTANTS
from .models import MR_D2, Observation

OK, INFO, CAUTION = "ok", "info", "caution"

PARTS_MINIMUM, PARTS_GOOD = 10, 35
OBSERVATIONS_MINIMUM = 100
NORMALITY_ALPHA = 0.05
RUN_LENGTH = 9  # test 2: this many points in a row on one side of the centre line


@dataclass(frozen=True, slots=True)
class Check:
    topic: str
    status: str  # ok, info or caution
    message: str


def needs_attention(checks: Sequence[Check]) -> bool:
    return any(check.status == CAUTION for check in checks)


# ----------------------------------------------------------------------------- the layout of a measurement study
@dataclass(frozen=True, slots=True)
class Layout:
    """Parts x operators x readings of one system, as the analysis will see them."""

    parts: int
    operators: int  # 0 means one appraiser
    fewest: int  # readings in the smallest part/operator cell
    most: int
    problems: tuple[str, ...]

    @property
    def balanced(self) -> bool:
        return not self.problems and self.fewest == self.most

    def describe(self) -> str:
        readings = (f"{self.most} readings each" if self.fewest == self.most
                    else f"{self.fewest} to {self.most} readings each")
        if self.operators:
            text = f"{self.parts} parts × {self.operators} operators × {readings}"
        else:
            text = f"{self.parts} parts × {readings}"
        return text + (", balanced" if self.balanced else ", NOT balanced")


def layout_of(rows: Sequence[Observation]) -> Layout:
    cells: Counter[tuple[str, str]] = Counter()
    operators: set[str] = set()
    parts: set[str] = set()
    for row in rows:
        part, operator = safe_text(row.sample_id), safe_text(row.operator)
        if not part:
            continue
        parts.add(part)
        if operator:
            operators.add(operator)
        cells[(part, operator)] += 1
    problems: list[str] = []
    if operators:
        for operator in sorted(operators):
            missing = sorted(part for part in parts if (part, operator) not in cells)
            if missing:
                shown = ", ".join(missing[:3]) + (" …" if len(missing) > 3 else "")
                problems.append(f"operator {operator} has no readings of part {shown}")
        if any(operator == "" for _part, operator in cells):
            problems.append("some readings have no operator")
    counts = list(cells.values())
    return Layout(len(parts), len(operators), min(counts, default=0), max(counts, default=0), tuple(problems))


def describe_layouts(rows: Sequence[Observation], only_unbalanced: bool = False) -> list[str]:
    """The study in plain words, one line per distinct layout among the test items (and testers and slots)."""
    systems: dict[tuple[str, str, str], list[Observation]] = defaultdict(list)
    for row in rows:
        systems[(safe_text(row.test_item), safe_text(row.tester), safe_text(row.slot))].append(row)
    if not systems:
        return []
    layouts = {key: layout_of(group) for key, group in systems.items()}
    groups: dict[tuple, list[tuple[str, str, str]]] = defaultdict(list)
    for key, layout in layouts.items():
        groups[(layout.parts, layout.operators, layout.fewest, layout.most, layout.problems)].append(key)
    lines = []
    for keys in groups.values():
        layout = layouts[keys[0]]
        if only_unbalanced and layout.balanced:
            continue
        if len(systems) == 1:
            who = "The test item"
        else:
            who = f"All {len(systems)} test items" if len(keys) == len(systems) else f"{len(keys)} of {len(systems)} test items"
        line = f"{who}: {layout.describe()}."
        if layout.problems:
            line += f" For example {keys[0][0]}: {'; '.join(layout.problems[:2])}."
        lines.append(line)
    return lines


# ----------------------------------------------------------------------------- Variable Gage R&R: amount of data
def grr_amount_checks(parts: int, operators: int) -> list[Check]:
    """How much the study can tell. ``operators`` is 0 for one appraiser."""
    if parts < PARTS_MINIMUM:
        checks = [Check("Parts", CAUTION, f"Only {parts} parts; at least {PARTS_MINIMUM} is the usual minimum. With few parts the "
                        "part-to-part variation, and so every percentage of the study variation, is imprecise, and it is "
                        "misleading if the parts do not cover the normal range of the process.")]
    elif parts <= 15:
        checks = [Check("Parts", INFO, f"{parts} parts meets the usual minimum of {PARTS_MINIMUM}, but the part-to-part "
                        "estimate is still imprecise: Minitab's simulations suggest about 35 parts for a margin of 20 % "
                        "(at 90 % confidence). Use parts that cover the normal range of the process.")]
    elif parts < PARTS_GOOD:
        checks = [Check("Parts", OK, f"{parts} parts is well above the usual minimum of {PARTS_MINIMUM}. If they cover the "
                        "normal range of the process, the part-to-part estimate is much better than with 10.")]
    else:
        checks = [Check("Parts", OK, f"{parts} parts is enough for a precise part-to-part estimate, if they cover the normal "
                        "range of the process.")]
    if not operators:
        return checks  # one tester: nothing to say about operators
    if operators <= 2 or parts < PARTS_MINIMUM:
        checks.append(Check("Operators", CAUTION, f"{operators} operators and {parts} parts: read the measurement variation "
                            "as a general tendency, not a precise figure (the usual minimum is 10 parts and 3 operators)."))
    elif operators <= 5:
        checks.append(Check("Operators", INFO, f"{operators} operators and {parts} parts: usually adequate for repeatability, "
                            "but the reproducibility estimate is less precise. If reproducibility is large, look at the "
                            "differences between operators and ask whether other operators would differ the same way."))
    else:
        checks.append(Check("Operators", OK, f"{operators} operators: the extra operators improve the reproducibility estimate."))
    return checks


# ----------------------------------------------------------------------------- Variable Gage R&R: guidelines
def _band(value: float, low: float, high: float) -> str:
    return "below" if value < low else "above" if value > high else "between"


def grr_guidelines(metrics: Mapping[str, float | int | None]) -> list[Check]:
    """The AIAG guidelines as Minitab quotes them, applied to the figures. They guide a judgement; they are not a verdict."""
    lines: list[Check] = []
    wording = {"below": "generally considered acceptable",
               "between": "may be acceptable, depending on the application, the cost of the measurement device, the cost of "
                          "repair or other factors",
               "above": "generally considered not acceptable; the measurement system should be improved"}
    for key, name in (("percent_study_var", "%Study Var"), ("percent_tolerance", "%Tolerance")):
        value = metrics.get(key)
        if value is not None:
            band = _band(value, 10, 30)
            limit = {"below": "below 10 %", "between": "between 10 % and 30 %", "above": "above 30 %"}[band]
            lines.append(Check(name, INFO, f"{value:.2f} % is {limit}: {wording[band]}."))
    variance, total = metrics.get("variance_grr"), metrics.get("variance_total")
    if variance is not None and total:
        contribution = 100 * variance / total
        band = _band(contribution, 1, 9)
        limit = {"below": "below 1 %", "between": "between 1 % and 9 %", "above": "above 9 %"}[band]
        lines.append(Check("%Contribution", INFO, f"{contribution:.2f} % is {limit}: {wording[band]}."))
    ndc = metrics.get("ndc")
    if ndc is not None:
        if ndc >= 5:
            lines.append(Check("Distinct categories", INFO, f"{ndc} meets the guideline of at least 5."))
        elif ndc < 2:
            lines.append(Check("Distinct categories", INFO, f"{ndc} is below the guideline of at least 5, and below 2: "
                               "the measurement system cannot tell the parts apart, so it is of no use for controlling "
                               "the process."))
        else:
            lines.append(Check("Distinct categories", INFO, f"{ndc} is below the guideline of at least 5: the measurement "
                               "system may not have enough resolution to tell the parts apart."))
    return lines


# ----------------------------------------------------------------------------- capability: stability
@dataclass(frozen=True, slots=True)
class Signals:
    """Readings (0-based positions) that signal on the individuals (I) and moving range (MR) charts."""

    i_beyond: tuple[int, ...]  # test 1: a reading more than 3 sigma from the centre line
    i_run: tuple[int, ...]  # test 2: the 9th and later readings of a run of 9 or more on one side of the centre line
    mr_beyond: tuple[int, ...]  # test 1 on the MR chart: a moving range above its upper limit (position of the later reading)

    @property
    def any(self) -> bool:
        return bool(self.i_beyond or self.i_run or self.mr_beyond)


def i_mr_signals(values: Sequence[float]) -> Signals | None:
    """Tests 1 and 2 on the I chart and test 1 on the MR chart (moving range of length 2, sigma = MRbar / d2).

    Control limits come from the data, as in Minitab's default. None when there is no variation to judge against.
    """
    if len(values) < 2:
        return None
    mean = math.fsum(values) / len(values)
    ranges = [abs(b - a) for a, b in zip(values[:-1], values[1:], strict=True)]
    mr_bar = math.fsum(ranges) / len(ranges)
    sigma = mr_bar / MR_D2
    if not sigma > 0:
        return None
    d2, d3 = R_CONSTANTS[2]
    mr_limit = mr_bar * (1 + 3 * d3 / d2)
    beyond = tuple(i for i, value in enumerate(values) if abs(value - mean) > 3 * sigma)
    side = [(v > mean) - (v < mean) for v in values]  # +1 above the centre line, -1 below, 0 on it
    run, flagged = 0, []
    for i, current in enumerate(side):
        run = run + 1 if current and i and side[i - 1] == current else (1 if current else 0)
        if run >= RUN_LENGTH:
            flagged.append(i)
    return Signals(beyond, tuple(flagged), tuple(i + 1 for i, r in enumerate(ranges) if r > mr_limit))


def stability_check(values: Sequence[float], *, order_known: bool, order_note: str) -> Check:
    signals = i_mr_signals(values)
    if signals is None:
        return Check("Stability", INFO, "Not assessed: the readings do not vary, or there are fewer than 2.")
    caveat = ("" if order_known else " The readings are not in a known order of measurement, so this says little about "
                                      "stability over time.")
    if not signals.any:
        status = OK if order_known else INFO
        return Check("Stability", status, "No out-of-control signal on the I chart (tests 1 and 2) or the MR chart "
                     f"(test 1).{caveat}{order_note}")
    parts = []
    if signals.i_beyond:
        parts.append(f"{len(signals.i_beyond)} reading(s) more than 3 sigma from the centre line (first: reading "
                     f"{signals.i_beyond[0] + 1})")
    if signals.i_run:
        parts.append(f"a run of {RUN_LENGTH} or more readings on one side of the centre line (from reading "
                     f"{signals.i_run[0] + 1})")
    if signals.mr_beyond:
        parts.append(f"{len(signals.mr_beyond)} unusually large change(s) between consecutive readings (first: reading "
                     f"{signals.mr_beyond[0] + 1})")
    return Check("Stability", CAUTION, "Possible instability: " + "; ".join(parts) + ". Capability assumes a stable process; "
                 f"look for the cause before relying on the indices.{caveat}{order_note}")


# ----------------------------------------------------------------------------- capability: normality
def _normal_cdf_pair(z: float) -> tuple[float, float]:
    """(Phi(z), 1 - Phi(z)), each accurate in its own tail."""
    root = math.sqrt(2)
    return 0.5 * math.erfc(-z / root), 0.5 * math.erfc(z / root)


def anderson_darling_normal(values: Sequence[float]) -> tuple[float, float] | None:
    """(A-squared, p-value) of the Anderson-Darling test of normality, mean and standard deviation estimated from the data.

    A-squared is adjusted for the sample size, A'^2 = A^2 (1 + 0.75/n + 2.25/n^2), and p comes from the piecewise
    equations of D'Agostino and Stephens (1986), whose coefficients Minitab prints in its methods for the normality test.
    None when the readings do not vary or there are fewer than 3.
    """
    n = len(values)
    if n < 3:
        return None
    mean = math.fsum(values) / n
    spread = math.fsum((v - mean) ** 2 for v in values)
    if not spread > 0:
        return None
    sd = math.sqrt(spread / (n - 1))
    ordered = sorted((v - mean) / sd for v in values)
    total = 0.0
    for i, z in enumerate(ordered, start=1):
        below = _normal_cdf_pair(z)[0]
        above = _normal_cdf_pair(ordered[n - i])[1]
        total += (2 * i - 1) * (math.log(max(below, 1e-300)) + math.log(max(above, 1e-300)))
    a2 = -n - total / n
    adjusted = a2 * (1 + 0.75 / n + 2.25 / n**2)
    if adjusted >= 13:
        p = 0.0
    elif adjusted >= 0.6:
        p = math.exp(1.2937 - 5.709 * adjusted + 0.0186 * adjusted**2)
    elif adjusted > 0.34:
        p = math.exp(0.9177 - 4.279 * adjusted - 1.38 * adjusted**2)
    elif adjusted > 0.2:
        p = 1 - math.exp(-8.318 + 42.796 * adjusted - 59.938 * adjusted**2)
    else:
        p = 1 - math.exp(-13.436 + 101.14 * adjusted - 223.73 * adjusted**2)
    return a2, min(1.0, max(0.0, p))


def normality_check(values: Sequence[float]) -> Check:
    if len(values) < 8:
        return Check("Normality", INFO, f"Not tested: {len(values)} readings are too few for a normality test.")
    outcome = anderson_darling_normal(values)
    if outcome is None:
        return Check("Normality", INFO, "Not tested: the readings do not vary.")
    p = outcome[1]
    shown = "< 0.001" if p < 0.001 else f"= {p:.3f}"
    if p >= NORMALITY_ALPHA:
        return Check("Normality", OK, f"Anderson-Darling p {shown} (at least {NORMALITY_ALPHA}): no evidence against a normal "
                     "distribution.")
    return Check("Normality", CAUTION, f"Anderson-Darling p {shown} (below {NORMALITY_ALPHA}): the readings may not follow a "
                 "normal distribution, so Cp, Cpk, Pp and Ppk, which assume one, may be inaccurate. Look at the histogram.")


def capability_checks(values: Sequence[float], *, individuals: bool, order_known: bool, order_note: str = "") -> list[Check]:
    n = len(values)
    if n >= OBSERVATIONS_MINIMUM:
        amount = Check("Amount of data", OK, f"{n} observations.")
    else:
        amount = Check("Amount of data", CAUTION, f"Only {n} observations; at least {OBSERVATIONS_MINIMUM} are recommended for "
                       "precise capability estimates (with 100, the estimated benchmark Z is within 15 % of the true value "
                       "with 90 % confidence when Z is above 3).")
    if individuals:
        stability = stability_check(values, order_known=order_known, order_note=order_note)
    else:
        stability = Check("Stability", INFO, "Not assessed: this analysis uses subgroups, and stability is checked here on "
                          "individual readings only. Look at an Xbar and S chart.")
    return [stability, normality_check(values), amount]


# ----------------------------------------------------------------------------- one result
def result_checks(result, *, order_known: bool, order_note: str = "") -> tuple[list[Check], list[Check]]:
    """The data checks and the guidelines for one analysis result."""
    if not result.valid:
        return [Check("Data", INFO, "This item could not be analysed; see Data messages.")], []
    if result.method == "grr":
        crossed = result.details.get("crossed")
        operators = len(result.details.get("operators") or ()) if crossed else 0
        return grr_amount_checks(result.parts, operators), grr_guidelines(result.metrics)
    values = [number for number in (to_number(row.value) for row in result.observations) if number is not None]
    individuals = result.details.get("within_method") == "individuals"
    return capability_checks(values, individuals=individuals, order_known=order_known, order_note=order_note), []
