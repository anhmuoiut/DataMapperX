"""Build the RawData workbook. The on-screen preview uses the same row generator."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from .config import MISSING_TEXT
from .models import LogRecord
from .utils import safe_text

_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_MAX_EXACT_DIGITS = 15  # beyond this a float silently loses digits, so keep such values as text

_BOLD = Font(bold=True)
_CENTER = Alignment(horizontal="center")
_RIGHT = Alignment(horizontal="right")
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


@dataclass(frozen=True, slots=True)
class ExportRow:
    index: int
    sn: str
    filename: str
    values: tuple[str, ...]


def iter_export_rows(grouped: dict[str, list[LogRecord]], components: Sequence[str]) -> Iterator[ExportRow]:
    """One row per log file: SNs sorted, files sorted within each SN."""
    index = 1
    for sn in sorted(grouped):
        for record in grouped[sn]:
            values = tuple(
                entry.measured if (entry := record.entries.get(component)) else MISSING_TEXT
                for component in components
            )
            yield ExportRow(index, sn, record.filename, values)
            index += 1


def summarize_limits(grouped: dict[str, list[LogRecord]], components: Sequence[str]) -> dict[str, dict[str, str]]:
    """Min / max / unit per component, taken from the first file (in SN order) that has it."""
    summary: dict[str, dict[str, str]] = {}
    for component in components:
        found = {"min": MISSING_TEXT, "max": MISSING_TEXT, "unit": MISSING_TEXT}
        for sn in sorted(grouped):
            entry = next((r.entries[component] for r in grouped[sn] if component in r.entries), None)
            if entry:
                found = {
                    "min": entry.min_value or MISSING_TEXT,
                    "max": entry.max_value or MISSING_TEXT,
                    "unit": entry.unit or MISSING_TEXT,
                }
                break
        summary[component] = found
    return summary


def sns_with_wrong_repeat_count(grouped: dict[str, list[LogRecord]], expected: int) -> list[str]:
    return [sn for sn in sorted(grouped) if len(grouped[sn]) != expected]


# -----------------------------------------------------------------------------
# Cell writers
# -----------------------------------------------------------------------------
def set_text(cell, text: str) -> None:
    """Store text verbatim. A leading '=' from a log must never turn into a live formula."""
    cell.value = text
    if text.startswith("="):
        cell.data_type = "s"


def set_cell_value(cell, raw: str) -> None:
    """Write a number when the text is one (keeping scientific notation), otherwise the text."""
    text = safe_text(raw)
    if text and _NUMBER_RE.fullmatch(text):
        number = float(text)
        has_exponent = "e" in text.lower()
        too_long = not has_exponent and sum(c.isdigit() for c in text) > _MAX_EXACT_DIGITS
        if math.isfinite(number) and not too_long:
            if has_exponent:
                cell.value = number
                mantissa = text.lower().split("e")[0]
                decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
                cell.number_format = "0." + "0" * decimals + "E+00" if decimals else "0E+00"
            elif number.is_integer():
                cell.value = int(number)
            else:
                cell.value = number
            return
    set_text(cell, text)


def _write_summary(ws, first_col: int, components: Sequence[str], summary: dict[str, dict[str, str]]) -> None:
    for offset, title in enumerate(("NAME", "MIN", "MAX", "UNIT")):
        cell = ws.cell(1, first_col + offset)
        cell.value = title
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BORDER

    for row, component in enumerate(components, start=2):
        info = summary.get(component, {})
        values = (component, info.get("min", MISSING_TEXT), info.get("max", MISSING_TEXT), info.get("unit", MISSING_TEXT))
        for offset, value in enumerate(values):
            cell = ws.cell(row, first_col + offset)
            if offset in (1, 2) and value != MISSING_TEXT:
                set_cell_value(cell, value)
            else:
                set_text(cell, value)
            cell.border = _BORDER
            if offset > 0:
                cell.alignment = _RIGHT


def generate_excel(
    grouped: dict[str, list[LogRecord]],
    components: Sequence[str],
    output_path: Path,
    expected_repeated: int,
) -> None:
    if not grouped:
        raise ValueError("No scanned data is available. Please scan a folder first.")

    invalid = sns_with_wrong_repeat_count(grouped, expected_repeated)
    if invalid:
        raise ValueError(
            f"Each SN must have exactly {expected_repeated} files. Please update the folder. Problem SN: "
            + ", ".join(invalid)
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Raw Data"

    for col, title in enumerate(("STT", "SN", *components), start=1):
        cell = ws.cell(1, col)
        set_text(cell, title)
        cell.font = _BOLD
        cell.alignment = _CENTER

    last_data_col = 2 + len(components)
    last_row = 1
    for row_no, row in enumerate(iter_export_rows(grouped, components), start=2):
        last_row = row_no
        ws.cell(row_no, 1, row.index).alignment = _CENTER
        set_text(ws.cell(row_no, 2), row.sn)
        for col, value in enumerate(row.values, start=3):
            cell = ws.cell(row_no, col)
            if value != MISSING_TEXT:
                set_cell_value(cell, value)
            else:
                cell.value = MISSING_TEXT
            cell.alignment = _RIGHT

    for r in range(1, last_row + 1):
        for c in range(1, last_data_col + 1):
            ws.cell(r, c).border = _BORDER

    summary_first_col = last_data_col + 2
    _write_summary(ws, summary_first_col, components, summarize_limits(grouped, components))

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 22
    for col in range(3, last_data_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18
    for col in range(summary_first_col, summary_first_col + 4):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.freeze_panes = "C2"

    _save_atomically(wb, output_path)


def _save_atomically(wb: Workbook, output_path: Path) -> None:
    """Save next to the target, then rename, so a failure never leaves a truncated workbook behind."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    try:
        wb.save(tmp)
        os.replace(tmp, output_path)
    except PermissionError:
        raise PermissionError(
            f"Cannot save '{output_path.name}'.\n\n"
            "The output file may already be open in Excel. Please close it and export again."
        ) from None
    finally:
        tmp.unlink(missing_ok=True)
