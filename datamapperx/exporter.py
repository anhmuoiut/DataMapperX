"""Build the RawData workbook. The on-screen preview uses the same row generator."""

from __future__ import annotations

import math
import os
import re
import textwrap
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from .config import MISSING_TEXT
from .models import LogRecord, Measurement
from .utils import column_letter, safe_text

if TYPE_CHECKING:  # openpyxl is imported only when a workbook is written: it costs about half a second
    from openpyxl import Workbook

_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_MAX_EXACT_DIGITS = 15  # beyond this a float silently loses digits, so keep such values as text

# Look of the workbook. The layout (which cell holds what) is unchanged; only the styling is.
@cache
def _styles() -> SimpleNamespace:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    line = Side(style="thin", color="B7C4D1")
    return SimpleNamespace(
        header_font=Font(bold=True, color="FFFFFF"),
        header_fill=PatternFill("solid", fgColor="005288"),
        band_fill=PatternFill("solid", fgColor="EAF1F8"),  # every other sample, so a sample's files read as a group
        border=Border(left=line, right=line, top=line, bottom=line),
        header_align=Alignment(horizontal="center", vertical="center", wrap_text=True),
        center=Alignment(horizontal="center", vertical="center"),
        left=Alignment(horizontal="left", vertical="center"),
        right=Alignment(horizontal="right", vertical="center"),
    )


_COLUMN_PADDING = 3  # characters of room beyond the longest value, so nothing shows as ####
_MIN_WIDTH, _MAX_WIDTH = 10, 60
_HEADING_WIDTH = 24  # a long heading wraps onto more lines instead of making the column this wide or wider
_LINE_HEIGHT = 15


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
    """Min / max / unit per component, taken from the first file (in SN order) that has it.

    One pass over the files that stops as soon as every component has been seen, so asking for every component
    of a big scan (as the component list does) costs about one file, not one sort of all SNs per component.
    """
    first: dict[str, Measurement] = {}
    remaining = set(components)
    for sn in sorted(grouped):
        for record in grouped[sn]:
            for component in remaining.intersection(record.entries):
                first[component] = record.entries[component]
            remaining.difference_update(first)
        if not remaining:
            break

    summary: dict[str, dict[str, str]] = {}
    for component in components:
        entry = first.get(component)
        summary[component] = {
            "min": (entry.min_value if entry else "") or MISSING_TEXT,
            "max": (entry.max_value if entry else "") or MISSING_TEXT,
            "unit": (entry.unit if entry else "") or MISSING_TEXT,
        }
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


def _style_header(cell) -> None:
    st = _styles()
    cell.font = st.header_font
    cell.fill = st.header_fill
    cell.alignment = st.header_align
    cell.border = st.border


def _shown_length(cell) -> int:
    """How many characters Excel needs to show the cell in full."""
    value = cell.value
    if value is None:
        return 0
    if isinstance(value, float) and "E" in cell.number_format:
        mantissa = cell.number_format.split("E")[0]
        decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
        return len(f"{value:.{decimals}E}")
    return len(str(value))


def _column_width(shown: Iterable[int], heading: str = "") -> float:
    """Wide enough for the longest value. A long heading wraps rather than widening the column past a limit."""
    data = max(shown, default=0) + _COLUMN_PADDING
    words = max((len(word) for word in heading.split()), default=0) + 2
    wanted = max(data, min(len(heading) + 2, _HEADING_WIDTH), words)
    return float(min(_MAX_WIDTH, max(_MIN_WIDTH, wanted)))


def _heading_lines(heading: str, width: float) -> int:
    return max(1, len(textwrap.wrap(heading, width=max(4, int(width) - 2), break_long_words=False)))


def _write_summary(ws, first_col: int, components: Sequence[str], summary: dict[str, dict[str, str]]) -> None:
    st = _styles()
    titles = ("NAME", "MIN", "MAX", "UNIT")
    shown: list[list[int]] = [[] for _ in titles]
    for offset, title in enumerate(titles):
        cell = ws.cell(1, first_col + offset)
        cell.value = title
        _style_header(cell)
        shown[offset].append(len(title))

    for row, component in enumerate(components, start=2):
        info = summary.get(component, {})
        values = (component, info.get("min", MISSING_TEXT), info.get("max", MISSING_TEXT), info.get("unit", MISSING_TEXT))
        for offset, value in enumerate(values):
            cell = ws.cell(row, first_col + offset)
            if offset in (1, 2) and value != MISSING_TEXT:
                set_cell_value(cell, value)
            else:
                set_text(cell, value)
            cell.border = st.border
            cell.alignment = (st.left, st.right, st.right, st.center)[offset]
            shown[offset].append(_shown_length(cell))

    for offset in range(len(titles)):
        ws.column_dimensions[column_letter(first_col + offset)].width = _column_width(shown[offset])


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

    from openpyxl import Workbook

    st = _styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "Raw Data"

    headings = ("STT", "SN", *components)
    for col, title in enumerate(headings, start=1):
        set_text(ws.cell(1, col), title)
        _style_header(ws.cell(1, col))

    last_data_col = 2 + len(components)
    shown: list[list[int]] = [[] for _ in headings]  # data only: a long heading wraps instead of widening its column
    band = False
    previous_sn = None
    for row_no, row in enumerate(iter_export_rows(grouped, components), start=2):
        if row.sn != previous_sn:
            band = not band if previous_sn is not None else False
            previous_sn = row.sn
        cells = [ws.cell(row_no, col) for col in range(1, last_data_col + 1)]
        cells[0].value = row.index
        cells[0].alignment = st.center
        set_text(cells[1], row.sn)
        cells[1].alignment = st.left
        for cell, value in zip(cells[2:], row.values, strict=True):
            if value != MISSING_TEXT:
                set_cell_value(cell, value)
            else:
                cell.value = MISSING_TEXT
            cell.alignment = st.right
        for index, cell in enumerate(cells):
            cell.border = st.border
            if band:
                cell.fill = st.band_fill
            shown[index].append(_shown_length(cell))

    summary_first_col = last_data_col + 2
    _write_summary(ws, summary_first_col, components, summarize_limits(grouped, components))

    for col, title in enumerate(headings, start=1):
        # The first two columns are always short; the rest follow their values, with long headings wrapped.
        ws.column_dimensions[column_letter(col)].width = _column_width(shown[col - 1], title if col > 2 else "")
    header_lines = max(_heading_lines(title, ws.column_dimensions[column_letter(col)].width) for col, title in enumerate(headings, start=1))
    ws.row_dimensions[1].height = max(24, _LINE_HEIGHT * header_lines + 9)

    ws.freeze_panes = "C2"
    ws.sheet_view.showGridLines = False  # the table has its own borders and bands
    ws.page_setup.orientation = "landscape"
    ws.print_title_rows = "1:1"

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
