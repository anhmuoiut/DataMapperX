"""An immutable dataset snapshot, with a statistical fingerprint kept apart from provenance.

The **statistical fingerprint** identifies what the numbers depend on: for each test item, its observations in order
(sample, value, limits, trial, tester, operator, slot, unit, subgroup). It does not depend on where the data came
from: not on object ids, file paths, sheet or row, timestamps or the description. Two sources holding the same data in
the same order therefore have the same fingerprint, and the same statistics.

**Provenance** (paths, sources, timestamps, how the data were obtained) is recorded separately, with its own hash.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from ..models import LogRecord
from ..utils import safe_text, to_number
from .models import Observation
from .normalize import normalize_records

ORDER_BASES = ("worksheet", "acquisition", "custom")
FINGERPRINT_VERSION = "v1"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\x1e", "\\x1e").replace("\x1f", "\\x1f")


def _canonical_value(value) -> str:
    """A number by its value (``"1.230"`` and ``1.23`` agree); anything else as text; nothing as an empty string."""
    number = to_number(value)
    if number is not None:
        return "n:" + repr(number)
    text = safe_text(value)
    return "t:" + text if text else ""


def _item_digest(name: str, rows: Sequence[Observation]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{FINGERPRINT_VERSION}-item\x1e{_escape(name)}\x1e".encode())
    first_seen: dict[str, int] = {}
    for row in rows:
        # Which observations share a source matters (the engine rejects one source used twice); its text does not.
        source = str(first_seen.setdefault(row.source, len(first_seen))) if row.source else ""
        fields = (safe_text(row.sample_id), _canonical_value(row.value), _canonical_value(row.lsl),
                  _canonical_value(row.usl), safe_text(row.trial), safe_text(row.tester), safe_text(row.operator),
                  safe_text(row.slot), safe_text(row.unit), safe_text(row.subgroup), source)
        digest.update(("\x1f".join(_escape(item) for item in fields) + "\x1e").encode())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Dataset:
    """Observations in analysis order. Immutable: the tuple and every ``Observation`` are frozen."""
    observations: tuple[Observation, ...]
    order_basis: str = "worksheet"  # what the order means: worksheet (as given), acquisition (measured), custom (chosen)
    description: str = ""  # how the data were obtained; provenance only
    fingerprint: str = field(init=False, default="")
    item_fingerprints: tuple[tuple[str, str], ...] = field(init=False, default=())
    provenance_fingerprint: str = field(init=False, default="")

    def __post_init__(self):
        if self.order_basis not in ORDER_BASES:
            raise ValueError(f"order_basis must be one of {', '.join(ORDER_BASES)}.")
        observations = tuple(self.observations)
        by_item: dict[str, list[Observation]] = defaultdict(list)
        for row in observations:
            by_item[safe_text(row.test_item)].append(row)
        items = tuple((name, _item_digest(name, rows)) for name, rows in sorted(by_item.items()))
        whole = hashlib.sha256()
        for name, digest in items:
            whole.update(f"{_escape(name)}\x1f{digest}\x1e".encode())
        provenance = json.dumps(
            {"description": self.description, "order_basis": self.order_basis,
             "sources": [row.source for row in observations], "timestamps": [safe_text(row.timestamp) for row in observations]},
            ensure_ascii=False, separators=(",", ":"))
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "item_fingerprints", items)
        object.__setattr__(self, "fingerprint", f"{FINGERPRINT_VERSION}:{whole.hexdigest()}")
        object.__setattr__(self, "provenance_fingerprint", f"{FINGERPRINT_VERSION}:{hashlib.sha256(provenance.encode()).hexdigest()}")

    def __len__(self) -> int:
        return len(self.observations)

    @property
    def items(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.item_fingerprints)

    def rows_for(self, item: str) -> tuple[Observation, ...]:
        return tuple(row for row in self.observations if safe_text(row.test_item) == item)

    @classmethod
    def from_observations(cls, observations: Sequence[Observation], *, order_basis: str = "worksheet",
                          description: str = "") -> Dataset:
        return cls(tuple(observations), order_basis, description)


def snapshot_from_records(
    grouped: Mapping[str, Sequence[LogRecord]],
    components: Sequence[str],
    field_mapping: Mapping[str, str] | None = None,
    *,
    assignments: Mapping[str, Mapping[str, str]] | None = None,
    assign_trials: bool = False,
    order_basis: str = "worksheet",
    description: str = "",
) -> Dataset:
    """Copy scanned records into an immutable dataset, leaving the records untouched.

    The order is the order of the RawData.xlsx rows (serial numbers sorted, files in their scan order within each).
    That is the order of the data as a worksheet, which is not necessarily the order they were measured in.
    Field mapping and per-file assignments follow ``normalize_records`` and the validation panel's rules.
    """
    ordered = {sn: grouped[sn] for sn in sorted(grouped)}
    rows = normalize_records(ordered, components, field_mapping, assign_trials)
    if assignments:
        rows = [replace(row, **assignments.get(str(row.source), {})) for row in rows]
    return Dataset.from_observations(rows, order_basis=order_basis, description=description)
