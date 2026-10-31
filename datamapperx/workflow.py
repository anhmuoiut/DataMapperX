"""What the Data Mapping screens show, worked out without any widget.

The two component lists, the review table, the limits panel and the check chips are decided here from the scan, the
selection and the limits. A window only has to display the answers, so the same logic serves any toolkit and can be
tested without opening one. Nothing here reads or writes a file, and nothing changes what is exported.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import islice

from .config import MISSING_TEXT, PREVIEW_COLUMNS_PER_PAGE, PREVIEW_ROW_LIMIT
from .exporter import ExportRow, iter_export_rows
from .models import ScanResult
from .review import HIGH, LOW, MISSING, ReviewSummary, limit_rows

SELECTED_EMPTY_TEXT = "Press + on a component on the left,\nor double-click it."
EMPTY_PREVIEW_TEXT = "Your data preview starts here.\nChoose a source folder, then scan its logs."
IDLE_PREVIEW_NOTE = "The preview uses the same rows and column order as your Excel file."
NO_ROW_CHOSEN_TEXT = "Click a row to compare its values with the limits."
PREVIEW_FIXED_HEADINGS = ("No.", "Serial number", "File")  # the columns before the components


# ----------------------------------------------------------------------------- component lists
def limit_texts(limits: Mapping[str, Mapping[str, str]], component: str) -> tuple[str, str]:
    """A component's Min and Max as shown in a list: an en dash when there is none."""
    info = limits.get(component, {})
    return info.get("min") or "–", info.get("max") or "–"


@dataclass(frozen=True, slots=True)
class AvailableView:
    """The "Available components" list: what to show, what to say when it is empty, and its count line."""

    items: list[str]
    empty_text: str
    info: str
    filtering: bool


def available_view(components: Sequence[str], selected: Sequence[str], keyword: str) -> AvailableView:
    chosen = set(selected)
    keyword = keyword.strip().lower()
    remaining = [c for c in components if c not in chosen]
    shown = [c for c in remaining if keyword in c.lower()] if keyword else remaining
    if not components:
        empty = "Scan a folder to list\nits components here."
    elif not remaining:
        empty = "Every component is selected."
    else:
        empty = "No component matches the filter."
    if not components:
        info = ""
    elif keyword:
        info = f"{len(shown)} of {len(remaining)} shown"
    else:
        info = f"{len(remaining)} available"
    return AvailableView(shown, empty, info, bool(keyword))


def selected_info(count: int) -> str:
    return f"{count} selected" if count else "No columns selected"


def move_items(items: list, indices: Sequence[int], direction: int) -> bool:
    """Move the items at ``indices`` (ascending) one place up (-1) or down (+1) in place. False when nothing can move."""
    if not indices or (direction < 0 and indices[0] == 0) or (direction > 0 and indices[-1] == len(items) - 1):
        return False
    for index in indices if direction < 0 else reversed(indices):
        items[index], items[index + direction] = items[index + direction], items[index]
    return True


# ----------------------------------------------------------------------------- review table
@dataclass(frozen=True, slots=True)
class PreviewTable:
    """One page of columns of the table that will be exported, with a tag per row (``invalid``, ``missing`` or empty)."""

    page: int
    pages: int
    first: int  # index of the first component on this page
    page_components: tuple[str, ...]
    rows: list[tuple]
    tags: list[str]
    export_rows: list[ExportRow]
    note: str
    count_text: str
    empty_text: str = ""

    @property
    def headings(self) -> tuple[str, ...]:
        return (*PREVIEW_FIXED_HEADINGS, *self.page_components)


def preview_table(result: ScanResult | None, components: Sequence[str], page: int, repeats: int | None) -> PreviewTable:
    """The review table for ``page`` (clamped to the pages that exist). The export always has every column."""
    pages = max(1, -(-len(components) // PREVIEW_COLUMNS_PER_PAGE))
    page = max(0, min(page, pages - 1))
    first = page * PREVIEW_COLUMNS_PER_PAGE
    shown_components = tuple(components[first : first + PREVIEW_COLUMNS_PER_PAGE])
    if result is None or not result.grouped:
        return PreviewTable(page, pages, first, shown_components, [], [], [], IDLE_PREVIEW_NOTE, "", EMPTY_PREVIEW_TEXT)

    wrong = set(result.sns_with_wrong_repeat_count(repeats)) if repeats else set()
    rows: list[tuple] = []
    tags: list[str] = []
    export_rows: list[ExportRow] = []
    for row in islice(iter_export_rows(result.grouped, components), PREVIEW_ROW_LIMIT):
        missing = bool(components) and MISSING_TEXT in row.values
        tags.append("invalid" if row.sn in wrong else "missing" if missing else "")
        rows.append((row.index, row.sn, row.filename, *row.values[first : first + PREVIEW_COLUMNS_PER_PAGE]))
        export_rows.append(row)

    shown = len(rows)
    if components:
        note = f"Showing {shown} of {result.total_files} rows." if shown < result.total_files else f"{shown} rows."
        if pages > 1:
            note += f"  The Excel file has all {len(components)} columns."
    else:
        note = f"{result.total_files} files found. Add components in the Select step to build your Excel columns."
    return PreviewTable(page, pages, first, shown_components, rows, tags, export_rows, note, f"({result.total_files} rows)")


# ----------------------------------------------------------------------------- limits panel
def limit_overview(components: Sequence[str], limits: Mapping[str, Mapping[str, str]]) -> list[tuple[str, ...]]:
    """Every selected component with its limits and unit, when no row is chosen."""
    return [(c, "", *limit_texts(limits, c), limits.get(c, {}).get("unit", "")) for c in components]


def limit_panel(
    row: ExportRow, components: Sequence[str], limits: Mapping[str, Mapping[str, str]]
) -> tuple[list[tuple[str, ...]], list[str]]:
    """Every selected component with the chosen row's value judged against its limits (▲ above max, ▼ below min)."""
    rows: list[tuple[str, ...]] = []
    tags: list[str] = []
    for entry in limit_rows(row, components, limits):
        mark = {HIGH: " ▲", LOW: " ▼"}.get(entry.status, "")
        rows.append((entry.component, "–" if entry.status == MISSING else entry.value + mark,
                     entry.low or "–", entry.high or "–", entry.unit))
        tags.append("gap" if entry.status == MISSING else "out" if entry.status in (HIGH, LOW) else "")
    return rows, tags


# ----------------------------------------------------------------------------- checks before exporting
def row_list(rows: tuple[int, ...], shown: int = 6) -> str:
    text = ", ".join(str(n) for n in rows[:shown])
    return f"{'rows' if len(rows) > 1 else 'row'} {text}" + (f" … +{len(rows) - shown} more" if len(rows) > shown else "")


def check_chips(
    result: ScanResult, summary: ReviewSummary, *, expected: int | None, repeats: int | None, wrong: Sequence[str]
) -> list[tuple[str, str]]:
    """The chips beside the Export button as (kind, text): what to know before saving. ``wrong`` are the samples whose
    file count is not ``repeats``."""
    chips: list[tuple[str, str]] = []
    if expected is not None:
        found = result.total_sns
        chips.append(("ok", f"✓  {found} of {expected} samples") if found == expected
                     else ("warn", f"!  {found} of {expected} samples. You will be asked to confirm"))
    if repeats is not None:
        if not wrong:
            chips.append(("ok", f"✓  {repeats} files per sample"))
        elif len(wrong) == 1:
            chips.append(("bad", f"!  {wrong[0]} has {len(result.grouped[wrong[0]])} files, not {repeats}. Export is blocked"))
        else:
            chips.append(("bad", f"!  {len(wrong)} samples do not have {repeats} files ({', '.join(wrong[:2])}…). Export is blocked"))
    if summary.empty_cells:
        count, columns = summary.empty_cells, len(summary.empty_columns)
        chips.append(("warn", f"!  {count} empty cell{'s' if count != 1 else ''} in {columns} column{'s' if columns != 1 else ''}"))
    else:
        chips.append(("ok", "✓  No empty cells"))
    if summary.outside_rows:
        chips.append(("info", f"Outside min–max: {row_list(summary.outside_rows)}"))
    return chips
