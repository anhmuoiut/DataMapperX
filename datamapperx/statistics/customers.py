"""Per-customer Gage R&R acceptance rules: built-in presets from the work instruction, and their storage form."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import CRITERION_METRICS, Criterion
from .validation import validate_criteria

# (PASS limit, FAIL limit): percentages pass below / fail above; NDC passes at or above / fails below.
DEFAULT_LIMITS = {"percent_tolerance": (10.0, 30.0), "percent_study_var": (10.0, 30.0), "ndc": (5.0, 5.0)}


def build_criteria(applied: Sequence[str]) -> tuple[Criterion, ...]:
    return tuple(Criterion(metric, metric in applied, *DEFAULT_LIMITS[metric]) for metric in CRITERION_METRICS)


# GR&R work instruction 50-TE30-GEN-INS-00046 rev I. Keurig (8.6.1.1.4) and Hanwha (8.6.1.1.5) have rules that
# are not a per-metric worst-of, so they are left for the user to define.
BUILTIN_CUSTOMERS: dict[str, tuple[Criterion, ...]] = {
    "SolarEdge": build_criteria(("percent_tolerance",)),  # 8.6.1.1.2: only %SV/Tolerance
    "Zebra": build_criteria(("percent_tolerance",)),  # 8.6.1.1.2: only %SV/Tolerance
    "SES": build_criteria(("percent_tolerance", "ndc")),  # 8.6.1.1.3: NDC and %SV/Tolerance
    "Jabil": build_criteria(CRITERION_METRICS),  # 8.6.1, table 8.12.2, 8.15.2: NDC, %SV and %SV/Tol
}
DEFAULT_CUSTOMER = "SolarEdge"


def criteria_to_json(criteria: Sequence[Criterion]) -> list[dict]:
    return [{"metric": c.metric, "enabled": c.enabled, "pass_limit": c.pass_limit, "fail_limit": c.fail_limit}
            for c in criteria]


def criteria_from_json(raw: object) -> tuple[Criterion, ...] | None:
    """Rebuild a customer's criteria; a hand-edited or damaged entry gives None instead of crashing."""
    if not isinstance(raw, list):
        return None
    found: dict[str, Criterion] = {}
    for item in raw:
        if not isinstance(item, dict) or item.get("metric") not in CRITERION_METRICS:
            return None
        defaults = DEFAULT_LIMITS[item["metric"]]
        found[item["metric"]] = Criterion(item["metric"], item.get("enabled") is True,
                                          item.get("pass_limit", defaults[0]), item.get("fail_limit", defaults[1]))
    criteria = tuple(found.get(m, Criterion(m, False, *DEFAULT_LIMITS[m])) for m in CRITERION_METRICS)
    try:
        validate_criteria(criteria)
    except ValueError:
        return None
    return criteria


def merge_customers(stored: Mapping[str, object]) -> dict[str, tuple[Criterion, ...]]:
    """Built-in customers, overridden or extended by what the user saved."""
    customers = dict(BUILTIN_CUSTOMERS)
    for name, raw in stored.items():
        criteria = criteria_from_json(raw)
        if isinstance(name, str) and name.strip() and criteria is not None:
            customers[name.strip()] = criteria
    return customers


def customers_to_json(customers: Mapping[str, Sequence[Criterion]]) -> dict[str, list[dict]]:
    """Only what differs from the built-in presets (or is new), so later preset updates still reach users."""
    return {name: criteria_to_json(criteria) for name, criteria in customers.items()
            if tuple(criteria) != BUILTIN_CUSTOMERS.get(name)}
