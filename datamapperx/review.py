"""What the review step adds to the preview: comparing a value with its limits and a summary to read before exporting.

Everything here is plain data in, plain data out (no window), so it can be tested without a display.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import MISSING_TEXT
from .exporter import ExportRow, iter_export_rows, summarize_limits
from .models import LogRecord
from .utils import to_number

HIGH = "high"
LOW = "low"
MISSING = "missing"


def _bounds(low: str, high: str) -> tuple[float | None, float | None]:
    """The numeric limits, smaller first (a log that lists them the other way round still works)."""
    lo, hi = to_number(low), to_number(high)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _outside(number: float, lo: float | None, hi: float | None) -> str:
    if hi is not None and number > hi:
        return HIGH
    if lo is not None and number < lo:
        return LOW
    return ""


def limit_status(value: str, low: str, high: str) -> str:
    """``"high"`` / ``"low"`` when the value is a number outside its limits (the limits themselves are inside).

    Anything that cannot be judged (text such as PASS, a missing limit, a blank value) is ``""``.
    """
    number = to_number(value)
    if number is None:
        return ""
    return _outside(number, *_bounds(low, high))


@dataclass(frozen=True, slots=True)
class LimitRow:
    """One component of one exported row, next to its limits."""

    component: str
    value: str
    low: str
    high: str
    unit: str
    status: str  # "", "high", "low" or "missing"


def limit_rows(row: ExportRow, components: Sequence[str], limits: Mapping[str, Mapping[str, str]]) -> list[LimitRow]:
    """Every selected component with this row's value and the limits it is judged against."""
    rows: list[LimitRow] = []
    for component, value in zip(components, row.values, strict=True):
        info = limits.get(component, {})
        low, high = info.get("min", MISSING_TEXT), info.get("max", MISSING_TEXT)
        status = MISSING if value == MISSING_TEXT else limit_status(value, low, high)
        rows.append(LimitRow(component, value, low, high, info.get("unit", MISSING_TEXT), status))
    return rows


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    rows: int
    empty_cells: int
    empty_columns: tuple[str, ...]  # components with at least one empty cell, in column order
    outside_rows: tuple[int, ...]  # export row numbers that have a value outside its limits


def summarize_review(
    grouped: dict[str, list[LogRecord]],
    components: Sequence[str],
    limits: Mapping[str, Mapping[str, str]] | None = None,
) -> ReviewSummary:
    """Count empty cells and find the rows with values outside their limits, over *all* rows (not only the preview)."""
    if limits is None:
        limits = summarize_limits(grouped, components)
    bounds = [_bounds(limits.get(c, {}).get("min", MISSING_TEXT), limits.get(c, {}).get("max", MISSING_TEXT)) for c in components]
    judged = [(j, lo, hi) for j, (lo, hi) in enumerate(bounds) if lo is not None or hi is not None]
    empty = [0] * len(components)
    outside: list[int] = []
    rows = 0
    for row in iter_export_rows(grouped, components):
        rows += 1
        values = row.values
        if MISSING_TEXT in values:
            for j, value in enumerate(values):
                if value == MISSING_TEXT:
                    empty[j] += 1
        for j, lo, hi in judged:
            number = to_number(values[j])
            if number is not None and _outside(number, lo, hi):
                outside.append(row.index)
                break
    columns = tuple(c for c, count in zip(components, empty, strict=True) if count)
    return ReviewSummary(rows, sum(empty), columns, tuple(outside))
