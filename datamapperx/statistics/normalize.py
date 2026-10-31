"""Normalize existing mapped log records without changing any raw measurements."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..models import LogRecord
from .models import Observation

_FIELDS = frozenset(Observation.__dataclass_fields__) - {"source"}


def normalize_records(
    grouped: Mapping[str, Sequence[LogRecord]],
    components: Sequence[str],
    field_mapping: Mapping[str, str] | None = None,
    assign_trials: bool = False,
) -> list[Observation]:
    """Map fields from @sample/@filename/@trial or an existing component's value.

    @test_item/@measurement/@lsl/@usl/@unit refer to the current measurement.
    '=text' assigns an explicit constant. Unmapped trial remains blank until the user
    explicitly requests assignment. Input order is retained for moving ranges.
    """
    mapping = dict(field_mapping or {})
    unknown = set(mapping) - _FIELDS
    if unknown:
        raise ValueError(f"Unknown analysis field: {', '.join(sorted(unknown))}")
    result = []
    for records in grouped.values():
        for index, record in enumerate(records, 1):
            for component in components:
                entry = record.entries.get(component)
                builtins = {
                    "@sample": record.sn, "@filename": record.filename,
                    "@trial": str(index), "@test_item": component,
                    "@measurement": entry.measured if entry else "",
                    "@lsl": entry.min_value if entry else "",
                    "@usl": entry.max_value if entry else "",
                    "@unit": entry.unit if entry else "",
                }
                values = {
                    "test_item": component, "sample_id": record.sn,
                    "value": builtins["@measurement"], "lsl": builtins["@lsl"],
                    "usl": builtins["@usl"], "unit": builtins["@unit"],
                    "trial": str(index) if assign_trials else "", "source": str(record.path),
                }
                for field, source in mapping.items():
                    if source.startswith("="):
                        values[field] = source[1:]
                    elif source in builtins:
                        values[field] = builtins[source]
                    else:
                        mapped = record.entries.get(source)
                        values[field] = mapped.measured if mapped else ""
                # Preserve raw numeric strings: validation and conversion belong to the engine.
                result.append(Observation(**values))
    return result
