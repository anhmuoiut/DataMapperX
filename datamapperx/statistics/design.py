"""Study design, applied on screen to a copy of the data: who measured, and what counts as a subgroup.

RawData.xlsx and most logs do not say which operator took a reading, so the design says it. The raw dataset is never
changed; the design produces the observations that are analysed. Design keys (all optional):

* ``operators``: two or more names. Each sample's readings are split between them by row order.
* ``operator_order``: ``"by_operator"`` (all of A's readings of a sample, then all of B's...) or ``"by_pass"``
  (A, B, C, A, B, C...).
* ``nest_as_operator``: the Slot of each reading is used as the operator, giving one crossed study across nests.
  It answers a different question than a study of each nest on its own.
* ``subgroup_from_sample``: the Sample ID is used as the subgroup (capability).

With no operators and no nest option the study has one appraiser: repeatability only.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from ..utils import safe_text
from .models import Observation

ORDER_CHOICES = ("by_operator", "by_pass")


class DesignError(ValueError):
    """The design cannot be applied to this data; the message says what to change."""


def operator_names(design: Mapping[str, Any]) -> tuple[str, ...]:
    names = tuple(safe_text(name) for name in design.get("operators") or ())
    return names if len(names) >= 2 else ()


def relevant_design(design: Mapping[str, Any], method: str) -> dict[str, Any]:
    """The part of the design that can change the statistics of ``method``."""
    if method == "capability":
        return {"subgroup_from_sample": bool(design.get("subgroup_from_sample"))}
    return {"operators": list(operator_names(design)), "operator_order": design.get("operator_order", "by_operator"),
            "nest_as_operator": bool(design.get("nest_as_operator"))}


def describe_design(design: Mapping[str, Any], method: str) -> tuple[str, ...]:
    """The design in words, for the plan line and the report."""
    if method == "capability":
        return (("Sample ID is used as the subgroup. Repeated readings of one sample are not rational subgroups; "
                 "this is only appropriate if that is the sampling design.") if design.get("subgroup_from_sample")
                else "Subgroups come from the data (none unless a Subgroup field is present).",)
    names = operator_names(design)
    if design.get("nest_as_operator"):
        return ("Nest as Operator: each slot is treated as an operator (crossed study). Reproducibility then reflects "
                "differences between nests, not between people, and the conclusion applies to the fixture as a whole, "
                "not to each nest.",)
    if names:
        order = "by pass" if design.get("operator_order") == "by_pass" else "by operator"
        return (f"Operators: {', '.join(names)} (a sample's readings assigned {order}, in row order). "
                "Crossed study: repeatability and reproducibility are estimated.",)
    return ("Single-tester repeatability study.",)


def auto_within_method(observations: Sequence[Observation]) -> str:
    """Within sigma from the subgroup size: pooled standard deviation when every reading belongs to a subgroup of at least
    two readings (within one test item, tester and slot), the moving range of individuals otherwise."""
    sizes: dict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in observations:
        subgroup = safe_text(row.subgroup)
        if not subgroup:
            return "individuals"
        sizes[(safe_text(row.test_item), safe_text(row.tester), safe_text(row.slot), subgroup)] += 1
    return "pooled" if sizes and min(sizes.values()) >= 2 else "individuals"


def apply_design(observations: Sequence[Observation], design: Mapping[str, Any], method: str) -> tuple[Observation, ...]:
    """The observations to analyse. Returns the input unchanged when the design asks for nothing."""
    rows = tuple(observations)
    if method == "capability":
        if design.get("subgroup_from_sample"):
            return tuple(replace(row, subgroup=safe_text(row.sample_id)) for row in rows)
        return rows
    names = operator_names(design)
    if design.get("nest_as_operator"):
        if names:
            raise DesignError("Choose either named operators or Nest as Operator, not both.")
        if any(safe_text(row.operator) for row in rows):
            raise DesignError("The data already identify operators; Nest as Operator would replace them.")
        if any(not safe_text(row.slot) for row in rows):
            raise DesignError("Nest as Operator needs a Slot (nest) for every reading.")
        return tuple(replace(row, operator=safe_text(row.slot), slot="") for row in rows)
    if not names:
        return rows
    order = design.get("operator_order", "by_operator")
    if order not in ORDER_CHOICES:
        raise DesignError("The row order of operators must be by operator or by pass.")
    if len(set(names)) != len(names) or not all(names):
        raise DesignError("Operator names must be different and not empty.")
    if any(safe_text(row.operator) for row in rows):
        raise DesignError("The data already identify operators; remove the operator assignment from the study design.")
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[(safe_text(row.test_item), safe_text(row.tester), safe_text(row.slot), safe_text(row.sample_id))].append(index)
    count = len(names)
    uneven = [f"{key[0]} / {key[3]} ({len(indices)} readings)" for key, indices in groups.items() if len(indices) % count]
    if uneven:
        raise DesignError(f"Each sample needs a multiple of {count} readings to split between {count} operators; "
                          f"first problems: {', '.join(uneven[:4])}.")
    assigned = list(rows)
    for indices in groups.values():
        per_operator = len(indices) // count
        for position, index in enumerate(indices):
            if order == "by_operator":
                who, trial = divmod(position, per_operator)
            else:
                trial, who = divmod(position, count)
            assigned[index] = replace(rows[index], operator=names[who], trial=str(trial + 1))
    return tuple(assigned)
