"""The data side of Validation & Reports, without any widget.

A ``MappingSource`` is what Data Mapping offers (its scan, the chosen components, and a counter that moves when they
change). ``build_mapping_dataset`` turns it into the immutable ``Dataset`` a ``Study`` is built on, and everything here
is pure, so it can run off the UI thread and under any toolkit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import LogRecord
from .statistics import Dataset, snapshot_from_records


@dataclass(frozen=True, slots=True)
class MappingSource:
    """What Data Mapping offers: its current scan, the components chosen, and a counter that moves when the data change."""
    grouped: Mapping[str, Sequence[LogRecord]]
    components: tuple[str, ...]
    expected_repeats: int | None
    serial: int
    description: str
    scan: int = 0  # moves only with a new scan, not when a choice among duplicates changes the values

    @property
    def key(self) -> tuple:
        return (self.serial, self.components, self.expected_repeats)


# ----------------------------------------------------------------------------- data (pure, so it can run off the UI thread)
def reorder_dataset(dataset: Dataset, order: str) -> Dataset:
    """Apply the order the user chose. Worksheet order is the dataset as it is; the others are claims the user makes."""
    if order == "worksheet":
        return dataset
    rows = list(dataset.observations)
    note = ""
    if order == "confirmed":
        basis = "acquisition"
    elif order == "filename":
        rows.sort(key=lambda row: (Path(str(row.source)).name.casefold(), str(row.source)))
        basis, note = "custom", "rows sorted by file name"
    elif order == "filetime":
        saved = {}
        for source in {str(row.source) for row in rows}:
            try:
                saved[source] = Path(source).stat().st_mtime_ns
            except OSError as exc:
                raise ValueError(f"File time order needs the time each log file was saved, and {Path(source).name or 'a file'} "
                                 "cannot be read where it was scanned. Choose another order.") from exc
        rows.sort(key=lambda row: (saved[str(row.source)], Path(str(row.source)).name.casefold(), str(row.source)))
        shared = len(saved) - len(set(saved.values()))
        basis, note = "acquisition", "rows sorted by the time each log file was saved"
        if shared:
            note += f" ({shared} file(s) share a save time with another file; those are kept in file name order)"
    else:
        try:
            rows.sort(key=lambda row: datetime.fromisoformat(str(row.timestamp).strip().replace("Z", "+00:00")))
        except (ValueError, TypeError) as exc:
            raise ValueError("Timestamp order requires a valid ISO 8601 timestamp for every file (assign them under File "
                             "assignments), with consistent timezone usage.") from exc
        basis, note = "acquisition", "rows sorted by timestamp"
    description = f"{dataset.description}; {note}" if note else dataset.description
    return Dataset.from_observations(rows, order_basis=basis, description=description)


def build_mapping_dataset(source: MappingSource, assignments: Mapping[str, Mapping[str, str]], order: str) -> Dataset:
    dataset = snapshot_from_records(source.grouped, source.components, assignments=assignments,
                                    description=source.description)
    return reorder_dataset(dataset, order)


def int_field(text: str, name: str, minimum: int) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{name}: enter a whole number, or leave it empty.") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value
