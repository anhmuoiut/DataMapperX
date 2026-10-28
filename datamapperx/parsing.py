"""Read one log file (text or Excel) and extract its serial number and measurements."""

from __future__ import annotations

import codecs
import logging
import re
from collections.abc import Iterator, Sequence
from itertools import islice
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from .models import Measurement, ParsedFile
from .profiles import compile_text_profile_regexes
from .utils import (
    compile_profile_regex,
    group_value,
    looks_like_cell_coordinate,
    normalize_excel_column,
    parse_positive_int,
    safe_text,
)

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


def extract_sn_from_text(source: str, sn_regex: str = "") -> str:
    source = safe_text(source)
    if not source:
        return ""
    pattern = compile_profile_regex(sn_regex, "SN_Regex", re.IGNORECASE) or SN_PATTERN
    match = pattern.search(source)
    return sn_from_match(match) if match else ""


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


def parse_text_file(path: Path, profile: dict, compiled: dict | None = None) -> ParsedFile:
    text = read_text_file(path)
    compiled = compiled or compile_text_profile_regexes(profile)
    block_re, measure_re = compiled["block_re"], compiled["measure_re"]
    if not block_re or not measure_re:
        raise ValueError("Text profile must include Name_Regex and Measure_Regex.")

    sn = _sn_for_text_file(path, text, compiled["sn_re"])

    entries: dict[str, Measurement] = {}
    duplicates: dict[str, list[Measurement]] = {}
    lines = text.splitlines()
    total = len(lines)

    i = 0
    while i < total:
        block_match = block_re.search(lines[i].strip())
        if not block_match:
            i += 1
            continue

        component = safe_text(group_value(block_match, "component", fallback_first=True))

        # The measurement is on the next non-blank line.
        j = i + 1
        while j < total and not lines[j].strip():
            j += 1

        measure_match = measure_re.search(lines[j]) if component and j < total else None
        if measure_match is None:
            # Not followed by a measurement: look at the very next line, which may be another block.
            i += 1
            continue

        min_value, max_value = _limits_from_tail(
            group_value(measure_match, "tail"), compiled["lim2_re"], compiled["lim3_re"]
        )
        _register(
            entries,
            duplicates,
            Measurement(
                component=component,
                measured=safe_text(group_value(measure_match, "measured", fallback_first=True)),
                min_value=safe_text(min_value),
                max_value=safe_text(max_value),
                unit=safe_text(group_value(measure_match, "type").upper()),
                source_row=str(i + 1),
            ),
        )
        i = j + 1

    return ParsedFile(sn=sn, entries=entries, duplicates=duplicates, row_label="Lines")


# -----------------------------------------------------------------------------
# Excel logs
# -----------------------------------------------------------------------------
def _cell(row: Sequence[Any], index: int | None) -> Any:
    if index is None or index >= len(row):
        return None
    return row[index]


def _iter_sheet_text(ws, max_rows: int = 80, max_cols: int = 30) -> Iterator[str]:
    """Yield the text of the first cells of a sheet (used to hunt for a serial number)."""
    for row in islice(ws.iter_rows(max_col=max_cols, values_only=True), max_rows):
        for value in row:
            text = safe_text(value)
            if text:
                yield text


def _column_index(letter: str) -> int | None:
    return column_index_from_string(letter) - 1 if letter else None


def _excel_sn(ws_sn, path: Path, sn_rule: str) -> str:
    is_cell = looks_like_cell_coordinate(sn_rule)
    regex_rule = "" if is_cell else sn_rule

    if is_cell:
        try:
            cell_text = safe_text(ws_sn[sn_rule.upper()].value)
        except (IndexError, KeyError, ValueError):
            cell_text = ""
        sn = extract_sn_from_text(cell_text) or cell_text.upper()
        if sn:
            return sn

    sn = extract_sn_from_text(path.name, regex_rule)
    if sn:
        return sn

    for cell_text in _iter_sheet_text(ws_sn):
        sn = extract_sn_from_text(cell_text, regex_rule)
        if sn:
            return sn
    return ""


def parse_excel_file(path: Path, profile: dict) -> ParsedFile:
    try:
        wb = load_workbook(str(path), data_only=True, read_only=True)
    except PermissionError:
        raise PermissionError(
            f"Cannot access '{path.name}'.\n\n"
            "Microsoft Excel locks files when they are open. "
            "Please CLOSE the file in Excel and try scanning again."
        ) from None
    except BadZipFile:
        raise ValueError(f"'{path.name}' is not a valid Excel workbook.") from None

    try:
        return _parse_workbook(wb, path, profile)
    finally:
        wb.close()


def _parse_workbook(wb, path: Path, profile: dict) -> ParsedFile:
    sn_sheet_name = safe_text(profile.get("sn_sheet", ""))
    data_sheet_name = safe_text(profile.get("data_sheet", ""))

    ws_sn = wb[sn_sheet_name] if sn_sheet_name in wb.sheetnames else wb.worksheets[0]
    if data_sheet_name in wb.sheetnames:
        ws_data = wb[data_sheet_name]
    elif len(wb.worksheets) > 1:
        ws_data = wb.worksheets[1]
    else:
        ws_data = wb.active

    # Some tools write a wrong <dimension> tag; read-only mode would then stop after the first row.
    for ws in (ws_sn, ws_data):
        if hasattr(ws, "reset_dimensions"):
            ws.reset_dimensions()

    sn = _excel_sn(ws_sn, path, safe_text(profile.get("sn_regex", "")))

    row_start = parse_positive_int(profile.get("row_start", 2), "Row_Start")
    idx_comp = _column_index(normalize_excel_column(profile.get("component_col", "A"), "Component_Col"))
    idx_meas = _column_index(normalize_excel_column(profile.get("measure_col", "B"), "Measure_Col"))
    idx_min = _column_index(normalize_excel_column(profile.get("min_col", "C"), "Min_Col", allow_blank=True))
    idx_max = _column_index(normalize_excel_column(profile.get("max_col", "D"), "Max_Col", allow_blank=True))
    idx_unit = _column_index(normalize_excel_column(profile.get("unit_col", "E"), "Unit_Col", allow_blank=True))

    entries: dict[str, Measurement] = {}
    duplicates: dict[str, list[Measurement]] = {}
    for row_no, row in enumerate(ws_data.iter_rows(min_row=row_start, values_only=True), start=row_start):
        component = safe_text(_cell(row, idx_comp))
        if not component:
            continue
        _register(
            entries,
            duplicates,
            Measurement(
                component=component,
                measured=safe_text(_cell(row, idx_meas)),
                min_value=safe_text(_cell(row, idx_min)),
                max_value=safe_text(_cell(row, idx_max)),
                unit=safe_text(_cell(row, idx_unit)),
                source_row=str(row_no),
            ),
        )

    return ParsedFile(sn=sn, entries=entries, duplicates=duplicates, row_label="Rows")


# -----------------------------------------------------------------------------
def parse_log_file(path: Path, profile: dict, compiled: dict | None = None) -> ParsedFile:
    if profile.get("type", "text") == "excel":
        return parse_excel_file(path, profile)
    return parse_text_file(path, profile, compiled=compiled)
