"""Numerical primitives, independent of UI and file formats."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .models import NDC_FACTOR


@dataclass(frozen=True)
class ScaledData:
    origin: float
    scale: float
    values: tuple[float, ...]
    mean_scaled: float
    mean: float


def scaled_data(values: Sequence[float]) -> ScaledData:
    """Center then scale, preventing squared units from under/overflowing."""
    origin = values[0]
    shifted = [value - origin for value in values]
    if any(not math.isfinite(value) for value in shifted):
        raise ValueError("Measurement range exceeds the supported numeric range.")
    scale = max(abs(value) for value in shifted) or 1.0
    normalized = tuple(value / scale for value in shifted)
    mean_scaled = math.fsum(normalized) / len(normalized)
    mean = origin + scale * mean_scaled
    if not math.isfinite(mean):
        raise ValueError("Mean exceeds the supported numeric range.")
    return ScaledData(origin, scale, normalized, mean_scaled, mean)


def finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def ndc_from_variances(part: float, gage: float) -> tuple[int | None, float | None]:
    """Minitab convention: truncate 1.41 * sigma_part / sigma_gage, minimum one.

    Variances may be normalized by any common positive scale. A zero or invalid
    denominator is undefined; do not replace it with an arbitrary high category count.
    """
    if not math.isfinite(part) or not math.isfinite(gage) or part < 0 or gage <= 0:
        return None, None
    ratio = part / gage
    # Preserve the usual calculation order, while avoiding overflow in an extreme ratio.
    raw = NDC_FACTOR * math.sqrt(ratio) if math.isfinite(ratio) else NDC_FACTOR * math.sqrt(part) / math.sqrt(gage)
    if not math.isfinite(raw):
        return None, None
    return max(1, math.floor(raw)), raw


def square(value: float) -> float | None:
    result = value * value
    # A nonzero SD must not be presented as a zero variance after underflow.
    return result if math.isfinite(result) and (result != 0 or value == 0) else None


def c4(n: int) -> float:
    """Unbiasing constant for a sample SD from n observations (n >= 2)."""
    if n < 2:
        raise ValueError("c4 requires n >= 2.")
    # Avoid cancellation in lgamma for large degrees of freedom.
    if n > 100_000:
        df = n - 1
        return 1 - 1 / (4 * df) + 1 / (32 * df * df) + 5 / (128 * df**3)
    return math.exp(0.5 * math.log(2 / (n - 1)) + math.lgamma(n / 2) - math.lgamma((n - 1) / 2))


def _beta_fraction(a: float, b: float, x: float) -> float:
    """Modified Lentz continued fraction for regularized incomplete beta."""
    qab, qap, qam = a + b, a + 1, a - 1
    tiny = 1e-300
    c = 1.0
    d = 1 - qab * x / qap
    d = 1 / (d if abs(d) >= tiny else tiny)
    h = d
    for m in range(1, 501):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = d if abs(d) >= tiny else tiny
        c = 1 + aa / c
        c = c if abs(c) >= tiny else tiny
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = d if abs(d) >= tiny else tiny
        c = 1 + aa / c
        c = c if abs(c) >= tiny else tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 3e-14:
            return h
    raise ValueError("ANOVA p-value did not converge.")


def regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        value = front * _beta_fraction(a, b, x) / a
    else:
        value = 1 - front * _beta_fraction(b, a, 1 - x) / b
    return min(1.0, max(0.0, value))


def f_survival(f_value: float, df1: int, df2: int) -> float:
    if f_value < 0 or df1 < 1 or df2 < 1:
        raise ValueError("Invalid F distribution inputs.")
    if math.isinf(f_value):
        return 0.0
    return regularized_beta(1 / (1 + df1 / df2 * f_value), df2 / 2, df1 / 2)
