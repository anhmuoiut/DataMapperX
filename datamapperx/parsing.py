"""Read one log file (text or Excel) and extract its serial number and measurements."""

from __future__ import annotations

import codecs
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from .models import Measurement, ParsedFile
from .profiles import compile_text_profile_regexes
from .utils import (
    column_number,
    compile_profile_regex,
    group_value,
    looks_like_cell_coordinate,
    normalize_excel_column,
    parse_positive_int,
    safe_text,
)
from .xlsx import read_workbook

logger = logging.getLogger(__name__)

# Used when a profile has no SN_Regex of its own.
SN_PATTERN = re.compile(r"(VSE[A-Z0-9]+)", re.IGNORECASE)


# -----------------------------------------------------------------------------
# Serial number
# -----------------------------------------------------------------------------
def sn_from_match(match: re.Match[str]) -> str:
    if "sn" in match.groupdict():
        value = match.group("sn")
    elif match.groups():
        value = match.group(1)
    else:
        value = match.group(0)
    return safe_text(value).upper()


def _find_sn(source: Any, pattern: re.Pattern[str] | None) -> str:
    """The serial number in ``source`` according to ``pattern`` (the default pattern when None)."""
    text = safe_text(source)
    if not text:
        return ""
    match = (pattern or SN_PATTERN).search(text)
    return sn_from_match(match) if match else ""


def extract_sn_from_text(source: str, sn_regex: str = "") -> str:
    return _find_sn(source, compile_profile_regex(sn_regex, "SN_Regex", re.IGNORECASE))


# -----------------------------------------------------------------------------
# Shared bookkeeping
# -----------------------------------------------------------------------------
def _register(entries: dict[str, Measurement], duplicates: dict[str, list[Measurement]], new: Measurement) -> None:
    """Keep the first occurrence of a component and remember the others for the user to choose from."""
    first = entries.get(new.component)
    if first is None:
        entries[new.component] = new
    else:
        duplicates.setdefault(new.component, [first]).append(new)


# -----------------------------------------------------------------------------
# Text logs
# -----------------------------------------------------------------------------
def read_text_file(path: Path) -> str:
    """Decode a log file, honouring UTF-16 byte-order marks that some testers write."""
    try:
        raw = path.read_bytes()
    except PermissionError:
        raise PermissionError(
            f"Cannot access '{path.name}'.\n\nThe file is locked by another program. Please CLOSE it before scanning."
        ) from None
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="ignore")
    return raw.decode("utf-8-sig", errors="ignore")


def _sn_for_text_file(path: Path, text: str, sn_re: re.Pattern[str] | None) -> str:
    pattern = sn_re or SN_PATTERN
    for source in (path.name, text):
        match = pattern.search(source)
        if match:
            return sn_from_match(match)
    return ""


def _limits_from_tail(tail: str, lim2_re, lim3_re) -> tuple[str, str]:
    """LIM3 (nominal|max|min) wins over LIM2 (max|min) when both are configured."""
    for pattern in (lim3_re, lim2_re):
        if pattern is None:
            continue
        match = pattern.search(tail)
        if match:
            min_value, max_value = group_value(match, "min"), group_value(match, "max")
            if min_value or max_value:
                return min_value, max_value
    return "", ""


@dataclass(frozen=True, slots=True)
class TextRecord:
    """A component line and the measurement line that follows it (indexes are 0-based)."""

    block_index: int
    block_match: re.Match[str]
    block_offset: int  # the block pattern is matched against the stripped line; this is the stripped prefix
    measure_index: int
    measure_match: re.Match[str]
    component: str


def iter_text_records(lines: Sequence[str], block_re: re.Pattern[str], measure_re: re.Pattern[str]) -> Iterator[TextRecord]:
    """Pair each component line with its measurement line, which is the next non-blank line."""
    total = len(lines)
    i = 0
    while i < total:
        stripped = lines[i].strip()
        block_match = block_re.search(stripped)
        if not block_match:
            i += 1
            continue

        component = safe_text(group_value(block_match, "component", fallback_first=True))

        j = i + 1
        while j < total and not lines[j].strip():
            j += 1

        measure_match = measure_re.search(lines[j]) if component and j < total else None
        if measure_match is None:
            # Not followed by a measurement: look at the very next line, which may be another block.
            i += 1
            continue

        offset = len(lines[i]) - len(lines[i].lstrip())
        yield TextRecord(i, block_match, offset, j, measure_match, component)
        i = j + 1


def parse_text_file(path: Path, profile: dict, compiled: dict | None = None) -> ParsedFile:
    text = read_text_file(path)
    compiled = compiled or compile_text_profile_regexes(profile)
    block_re, measure_re = compiled["block_re"], compiled["measure_re"]
    if not block_re or not measure_re:
        raise ValueError("Text profile must include Name_Regex and Measure_Regex.")

    sn = _sn_for_text_file(path, text, compiled["sn_re"])

    entries: dict[str, Measurement] = {}
    duplicates: dict[str, list[Measurement]] = {}
    for record in iter_text_records(text.splitlines(), block_re, measure_re):
        measure_match = record.measure_match
        min_value, max_value = _limits_from_tail(
            group_value(measure_match, "tail"), compiled["lim2_re"], compiled["lim3_re"]
        )
        _register(
            entries,
            duplicates,
            Measurement(
                component=record.component,
                measured=safe_text(group_value(measure_match, "measured", fallback_first=True)),
                min_value=safe_text(min_value),
                max_value=safe_text(max_value),
                unit=safe_text(group_value(measure_match, "type").upper()),
                source_row=str(record.block_index + 1),
            ),
        )

    return ParsedFile(sn=sn, entries=entries, duplicates=duplicates, row_label="Lines")


# -----------------------------------------------------------------------------
# Excel logs
# -----------------------------------------------------------------------------
_SN_SCAN_ROWS, _SN_SCAN_COLUMNS = 80, 30  # where to hunt for a serial number when no cell is given


def _cell(row: Sequence[Any], index: int | None) -> Any:
    if index is None or index >= len(row):
        return None
    return row[index]


@dataclass(frozen=True, slots=True)
class _ExcelSettings:
    """A profile's Excel rules, checked once before any file is opened."""

    sn_sheet: str
    data_sheet: str
    sn_cell: str  # such as "B1" when the serial number rule is a cell, otherwise ""
    sn_pattern: re.Pattern[str] | None  # the rule when it is a pattern; None means the default pattern
    row_start: int
    columns: tuple[int | None, ...]  # component, measured, min, max, unit (0-based; None when not used)
    skip_headings: bool

    @classmethod
    def from_profile(cls, profile: dict) -> _ExcelSettings:
        rule = safe_text(profile.get("sn_regex", ""))
        is_cell = looks_like_cell_coordinate(rule)
        letters = (
            normalize_excel_column(profile.get("component_col", "A"), "Component_Col"),
            normalize_excel_column(profile.get("measure_col", "B"), "Measure_Col"),
            normalize_excel_column(profile.get("min_col", "C"), "Min_Col", allow_blank=True),
            normalize_excel_column(profile.get("max_col", "D"), "Max_Col", allow_blank=True),
            normalize_excel_column(profile.get("unit_col", "E"), "Unit_Col", allow_blank=True),
        )
        return cls(
            sn_sheet=safe_text(profile.get("sn_sheet", "")),
            data_sheet=safe_text(profile.get("data_sheet", "")),
            sn_cell=rule.upper() if is_cell else "",
            sn_pattern=None if is_cell else compile_profile_regex(rule, "SN_Regex", re.IGNORECASE),
            row_start=parse_positive_int(profile.get("row_start", 2), "Row_Start"),
            columns=tuple(column_number(letter) - 1 if letter else None for letter in letters),
            # Section headings ("INITIALIZE (Init)") have a name but no result; they are not measurements.
            skip_headings=profile.get("skip_empty_rows", True) is not False,
        )


def _excel_sn(reader, sheet: str, path: Path, settings: _ExcelSettings) -> str:
    rows, columns = _SN_SCAN_ROWS, _SN_SCAN_COLUMNS
    cell_row = cell_column = 0
    if settings.sn_cell:
        match = re.fullmatch(r"([A-Z]+)(\d+)", settings.sn_cell)
        cell_row, cell_column = int(match.group(2)), column_number(match.group(1))
        rows, columns = max(rows, cell_row), max(columns, cell_column)
    grid = reader.grid(sheet, rows, columns)

    if settings.sn_cell:
        value = grid[cell_row - 1][cell_column - 1] if 1 <= cell_row <= len(grid) and cell_column <= len(grid[cell_row - 1]) else None
        text = safe_text(value)
        sn = _find_sn(text, None) or text.upper()
        if sn:
            return sn

    sn = _find_sn(path.name, settings.sn_pattern)
    if sn:
        return sn
    for row in grid[:_SN_SCAN_ROWS]:
        for value in row[:_SN_SCAN_COLUMNS]:
            sn = _find_sn(value, settings.sn_pattern)
            if sn:
                return sn
    return ""


def _read_excel(reader, path: Path, settings: _ExcelSettings) -> ParsedFile:
    names = reader.sheet_names
    if not names:
        raise ValueError(f"'{path.name}' has no worksheets.")
    sn_sheet = settings.sn_sheet if settings.sn_sheet in names else names[0]
    second = names[1] if len(names) > 1 else names[0]
    data_sheet = settings.data_sheet if settings.data_sheet in names else second

    sn = _excel_sn(reader, sn_sheet, path, settings)
    idx_comp, idx_meas, idx_min, idx_max, idx_unit = settings.columns

    entries: dict[str, Measurement] = {}
    duplicates: dict[str, list[Measurement]] = {}
    for row_no, row in reader.iter_rows(data_sheet, min_row=settings.row_start):
        component = safe_text(_cell(row, idx_comp))
        if not component:
            continue
        measurement = Measurement(
            component=component,
            measured=safe_text(_cell(row, idx_meas)),
            min_value=safe_text(_cell(row, idx_min)),
            max_value=safe_text(_cell(row, idx_max)),
            unit=safe_text(_cell(row, idx_unit)),
            source_row=str(row_no),
        )
        if settings.skip_headings and not (measurement.measured or measurement.min_value or measurement.max_value or measurement.unit):
            continue
        _register(entries, duplicates, measurement)

    return ParsedFile(sn=sn, entries=entries, duplicates=duplicates, row_label="Rows")


def parse_excel_file(path: Path, profile: dict) -> ParsedFile:
    settings = _ExcelSettings.from_profile(profile)
    try:
        return read_workbook(path, lambda reader: _read_excel(reader, path, settings))
    except PermissionError:
        raise PermissionError(
            f"Cannot access '{path.name}'.\n\n"
            "Microsoft Excel locks files when they are open. "
            "Please CLOSE the file in Excel and try scanning again."
        ) from None
    except BadZipFile:
        raise ValueError(f"'{path.name}' is not a valid Excel workbook.") from None


# -----------------------------------------------------------------------------
def parse_log_file(path: Path, profile: dict, compiled: dict | None = None) -> ParsedFile:
    if profile.get("type", "text") == "excel":
        return parse_excel_file(path, profile)
    return parse_text_file(path, profile, compiled=compiled)
