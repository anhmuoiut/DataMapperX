"""Read data into a ``Dataset`` from files other than a scan: the RawData.xlsx that DataMapperX itself writes.

Layout (see exporter.py): sheet "Raw Data"; row 1 is STT, SN, one column per component, an empty column, then the
limits table NAME / MIN / MAX / UNIT. Each later row is one file; the limits table runs down the same sheet and has
no relation to the number of data rows. Rules that keep the data honest:

* the empty column ends the data columns, so NAME/MIN/MAX/UNIT are never mistaken for measurements;
* serial numbers are kept as text (leading zeros stay), and STT is only a running count, never a trial;
* limits and units are matched to a component by its exact name;
* an empty cell stays a missing reading (the analysis reports it), it is not skipped or filled in;
* every reading has its own source (``Raw Data!R<row>``), so a repeated source can never be reported falsely;
* the order of the rows is the order of the data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import safe_text
from ..xlsx import read_workbook
from .dataset import Dataset
from .models import Observation

SHEET = "Raw Data"


class RawDataFormatError(ValueError):
    """The file is not a DataMapperX RawData workbook, or is unusable; the message says why."""


@dataclass(frozen=True, slots=True)
class ImportedData:
    dataset: Dataset
    items: tuple[str, ...]
    samples: int
    rows: int
    sheet: str
    warnings: tuple[str, ...] = field(default=())


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return safe_text(value)


def _name(value: Any) -> str:
    """A column or component name exactly as written (limits are matched by the exact name)."""
    return value if isinstance(value, str) else _text(value)


def _plain(value: Any) -> Any:
    """A cell value as the analysis should see it: numbers stay numbers, text stays text, empty is empty."""
    if value is None:
        return ""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else safe_text(value)


def _cell(values: list, position: int | None) -> Any:
    return values[position] if position is not None and position < len(values) else None


def _parse(reader, name: str) -> dict[str, Any]:
    sheets = reader.sheet_names
    sheet = SHEET if SHEET in sheets else (sheets[0] if sheets else "")
    if not sheet:
        raise RawDataFormatError("The workbook has no worksheet.")
    rows = reader.iter_rows(sheet)
    first = next(rows, None)
    header = first[1] if first else []
    if len(header) < 3 or _text(header[0]).upper() != "STT" or _text(header[1]).upper() != "SN":
        raise RawDataFormatError(
            f"'{name}' is not a DataMapperX RawData workbook: row 1 of the sheet '{sheet}' must start with STT and SN.")
    columns: list[tuple[int, str]] = []
    index = 2
    while index < len(header) and _text(header[index]):
        columns.append((index, _name(header[index])))
        index += 1
    if not columns:
        raise RawDataFormatError("There are no measurement columns after STT and SN.")
    names = [column for _, column in columns]
    if len(set(names)) != len(names):
        duplicate = next(column for column in names if names.count(column) > 1)
        raise RawDataFormatError(f"The column name '{duplicate}' appears more than once; every test item needs its own name.")
    labels = {_text(value).upper(): position for position, value in enumerate(header) if position >= index and _text(value)}
    limit_columns = {key: labels.get(key) for key in ("NAME", "MIN", "MAX", "UNIT")}
    limits: dict[str, tuple[Any, Any, str]] = {}
    data: list[tuple[int, list[Any]]] = []
    for number, values in rows:
        name, low, high, unit = (_cell(values, limit_columns[key]) for key in ("NAME", "MIN", "MAX", "UNIT"))
        if _text(name):
            limits[_name(name)] = (_plain(low), _plain(high), _text(unit))
        if len(values) > 1 and _text(values[1]):
            data.append((number, values))
    return {"sheet": sheet, "columns": columns, "limits": limits, "data": data, "has_limits": limit_columns["NAME"] is not None}


def import_rawdata_xlsx(path: str | Path) -> ImportedData:
    """Read a RawData.xlsx into a dataset (worksheet order), without changing or guessing anything."""
    path = Path(path)
    parsed = read_workbook(path, lambda reader: _parse(reader, path.name))
    columns, limits, data, sheet = parsed["columns"], parsed["limits"], parsed["data"], parsed["sheet"]
    if not data:
        raise RawDataFormatError("The sheet has no data rows (a serial number in the SN column on each row).")
    warnings: list[str] = []
    if not parsed["has_limits"]:
        warnings.append("The NAME/MIN/MAX/UNIT table was not found: no specification limits are available.")
    else:
        missing = [name for _, name in columns if name not in limits]
        if missing:
            warnings.append("No limits found for: " + ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else "") + ".")
    observations: list[Observation] = []
    for number, values in data:
        sample = _text(values[1])
        source = f"{sheet}!R{number}"
        for position, name in columns:
            low, high, unit = limits.get(name, ("", "", ""))
            observations.append(Observation(name, sample, _plain(values[position] if position < len(values) else None),
                                            low, high, unit=unit, source=source))
    dataset = Dataset.from_observations(observations, order_basis="worksheet", description=f"RawData workbook {path.name}")
    return ImportedData(dataset, tuple(name for _, name in columns), len({_text(values[1]) for _, values in data}), len(data),
                        sheet, tuple(warnings))
