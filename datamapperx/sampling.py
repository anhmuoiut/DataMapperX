"""Look at one sample log and work out how to read that kind of log.

Everything here is plain logic with no windows, so it can be tested and reused: detecting a profile from a
sample, listing the columns of a worksheet, previewing what a profile extracts, finding the parts of a text
log that a profile matched, and checking a profile against the other files in the same folder.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from .config import EXCEL_FILE_EXTENSIONS
from .models import Measurement
from .parsing import iter_text_records, parse_log_file, read_text_file
from .patterns import sn_regex_from_example
from .profiles import compile_text_profile_regexes, get_profile_extensions, text_profile_from_patterns
from .scanner import discover_files
from .utils import column_letter, column_number, group_value, safe_text
from .xlsx import read_workbook

logger = logging.getLogger(__name__)

SKETCH_ROWS = 60
SKETCH_COLUMNS = 30

# The standard in-circuit-test (HP / Keysight i3070) layout.
I3070_PATTERNS = {
    "block": "{@BLOCK|[Component]|00",  # 00 = passed; a failed attempt (01) is repeated later and must not win
    "measure": "{@A-[Unit]|[Any]|[Measured]",
    "lim2": "{@LIM2|[Max]|[Min]",
    "lim3": "{@LIM3|[Any]|[Max]|[Min]",
}


@dataclass(slots=True)
class Detection:
    """What was worked out from a sample: a ready-to-edit profile and a plain-language explanation."""

    profile: dict[str, Any]
    notes: list[str]
    suggested_name: str
    warnings: list[str] = field(default_factory=list)


def is_excel(path: Path) -> bool:
    return path.suffix.lower() in EXCEL_FILE_EXTENSIONS


def sibling_files(path: Path, limit: int = 12) -> list[Path]:
    """Other files of the same kind in the sample's folder; used to tell what changes from file to file."""
    try:
        names = sorted(
            (p for p in path.parent.iterdir()
             if p.is_file() and p != path and p.suffix.lower() == path.suffix.lower() and not p.name.startswith("~$")),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []
    return names[:limit]


# --------------------------------------------------------------------------------------------------
# Serial number
# --------------------------------------------------------------------------------------------------
_NAME_PARTS = re.compile(r"[_\s.]+")


def _name_tokens(path: Path) -> list[str]:
    return [part for part in _NAME_PARTS.split(path.stem) if part]


def guess_serial_example(path: Path, siblings: Iterable[Path] = (), content: str = "") -> str:
    """The part of the file name that identifies the unit.

    It differs from file to file and, for text logs, also appears inside the file. Product and program names
    are the same in every file and timestamps are not written inside, so both are ruled out.
    """
    token_lists = [_name_tokens(path), *(_name_tokens(p) for p in siblings)]
    haystack = content.lower()
    best: tuple[tuple[bool, bool, bool, int], str] | None = None
    for index, token in enumerate(token_lists[0]):
        if len(token) < 5 or not re.search(r"\d", token):
            continue
        varies = len({tokens[index] for tokens in token_lists if len(tokens) > index}) > 1
        present = bool(haystack) and token.lower() in haystack
        key = (varies and present, varies, present, len(token))
        if best is None or key > best[0]:
            best = (key, token)
    return best[1] if best else ""


# --------------------------------------------------------------------------------------------------
# Excel workbooks
# --------------------------------------------------------------------------------------------------
_HEADER_WORDS: dict[str, frozenset[str]] = {
    "component": frozenset({"test", "test name", "testname", "name", "component", "item", "description", "parameter", "step", "designator"}),
    "measured": frozenset({"result", "results", "value", "measured", "measured value", "measurement", "reading", "actual"}),
    "min": frozenset({"min", "minimum", "low", "low limit", "lower", "lower limit", "lsl", "lo"}),
    "max": frozenset({"max", "maximum", "high", "high limit", "upper", "upper limit", "usl", "hi"}),
    "unit": frozenset({"unit", "units", "uom"}),
}
_PROFILE_COLUMN_KEYS = {
    "component": "component_col", "measured": "measure_col", "min": "min_col", "max": "max_col", "unit": "unit_col",
}


def _normalise_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", safe_text(value).lower()).strip()


@dataclass(frozen=True, slots=True)
class ColumnChoice:
    letter: str
    header: str
    example: str

    @property
    def label(self) -> str:
        if self.header:
            return f"{self.letter}  -  {self.header}"
        return f"{self.letter}  -  (e.g. {self.example})" if self.example else self.letter


@dataclass(slots=True)
class WorkbookSketch:
    """The first rows of every sheet, enough to recognise the layout without reading big sheets in full."""

    path: Path
    sheets: dict[str, list[list[Any]]]

    @classmethod
    def load(cls, path: Path, max_rows: int = SKETCH_ROWS, max_cols: int = SKETCH_COLUMNS) -> WorkbookSketch:
        def collect(reader) -> dict[str, list[list[Any]]]:
            sheets: dict[str, list[list[Any]]] = {}
            for name in reader.sheet_names:
                rows = reader.grid(name, max_rows, max_cols)
                while rows and not any(safe_text(v) for v in rows[-1]):
                    rows.pop()
                sheets[name] = rows
            return sheets

        try:
            return cls(path, read_workbook(path, collect))
        except BadZipFile:
            raise ValueError(f"'{path.name}' is not a valid Excel workbook.") from None
        except PermissionError:
            raise PermissionError(f"Cannot open '{path.name}'. Close it in Excel and try again.") from None

    @property
    def names(self) -> list[str]:
        return list(self.sheets)

    def cell(self, sheet: str, ref: str) -> str:
        match = re.fullmatch(r"([A-Za-z]{1,3})(\d{1,7})", safe_text(ref))
        rows = self.sheets.get(sheet, [])
        if not match:
            return ""
        column = column_number(match.group(1)) - 1
        row = int(match.group(2)) - 1
        if row < len(rows) and column < len(rows[row]):
            return safe_text(rows[row][column])
        return ""

    def columns(self, sheet: str, row_start: int) -> list[ColumnChoice]:
        rows = self.sheets.get(sheet, [])
        width = max((len(r) for r in rows), default=0)
        header_row = rows[row_start - 2] if 2 <= row_start <= len(rows) + 1 else []
        choices = []
        for index in range(width):
            header = safe_text(header_row[index]) if index < len(header_row) else ""
            example = next(
                (safe_text(r[index])[:28] for r in rows[max(row_start - 1, 0):] if index < len(r) and safe_text(r[index])),
                "",
            )
            if header or example:
                choices.append(ColumnChoice(column_letter(index + 1), header, example))
        return choices


def _find_header_row(rows: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    """The first row that names both a component column and a result column, with the columns it found."""
    best: tuple[int, int, dict[str, int]] | None = None
    for row_index, row in enumerate(rows[:15]):
        found: dict[str, int] = {}
        for col_index, value in enumerate(row):
            word = _normalise_header(value)
            if not word:
                continue
            for role, words in _HEADER_WORDS.items():
                if word in words and role not in found:
                    found[role] = col_index
        has_both = "component" in found and "measured" in found and found["component"] != found["measured"]
        if has_both and (best is None or len(found) > best[1]):
            best = (row_index, len(found), found)
    return (best[0], best[2]) if best else None


def _find_serial_cell(rows: list[list[Any]], file_stem: str) -> tuple[str, str] | None:
    """Locate the cell holding the serial number: a cell whose text is part of the file name, else a labelled cell."""
    stem = file_stem.upper()
    best: tuple[tuple[int, int], str, str] | None = None
    for row_index, row in enumerate(rows[:20]):
        for col_index, value in enumerate(row[:10]):
            text = safe_text(value)
            if len(text) < 4 or text.upper() not in stem:
                continue
            label = safe_text(row[col_index - 1]).lower() if col_index > 0 else ""
            key = (1 if "serial" in label or label in {"sn", "s/n"} else 0, len(text))
            if best is None or key > best[0]:
                best = (key, f"{column_letter(col_index + 1)}{row_index + 1}", text)
    if best:
        return best[1], best[2]
    for row_index, row in enumerate(rows[:20]):
        for col_index in range(len(row) - 1):
            if re.fullmatch(r"serial( number| no\.?)?|sn|s/n", safe_text(row[col_index]).lower()) and safe_text(row[col_index + 1]):
                return f"{column_letter(col_index + 2)}{row_index + 1}", safe_text(row[col_index + 1])
    return None


def detect_excel(path: Path, siblings: Iterable[Path] = (), sketch: WorkbookSketch | None = None) -> Detection:
    sketch = sketch or WorkbookSketch.load(path)
    notes: list[str] = []
    warnings_: list[str] = []

    # The results sheet is the one whose header row names the most of: component, result, min, max, unit.
    data_sheet, header = "", None
    for name in sketch.names:
        candidate = _find_header_row(sketch.sheets[name])
        if candidate and (header is None or len(candidate[1]) > len(header[1])):
            data_sheet, header = name, candidate

    profile: dict[str, Any] = {
        "type": "excel", "file_extensions": ",".join(EXCEL_FILE_EXTENSIONS), "sn_regex": "", "sn_sheet": "",
        "data_sheet": "", "row_start": "2", "component_col": "A", "measure_col": "B",
        "min_col": "", "max_col": "", "unit_col": "", "skip_empty_rows": True,
    }
    if header is None:
        data_sheet = sketch.names[1] if len(sketch.names) > 1 else (sketch.names[0] if sketch.names else "")
        warnings_.append(
            "I could not find a table with a test name and a result column. Pick the sheet and columns yourself."
        )
    else:
        header_row, columns = header
        profile["row_start"] = str(header_row + 2)
        for role, key in _PROFILE_COLUMN_KEYS.items():
            profile[key] = column_letter(columns[role] + 1) if role in columns else ""
        notes.append(
            f"Results table: sheet '{data_sheet}', column headings on row {header_row + 1}, data from row {header_row + 2}."
        )
    profile["data_sheet"] = data_sheet

    # Serial number: prefer the sheet that is not the results table (usually 'Session' or 'Info').
    sn_sheet = next((n for n in sketch.names if n != data_sheet), data_sheet)
    profile["sn_sheet"] = sn_sheet
    located = _find_serial_cell(sketch.sheets.get(sn_sheet, []), path.stem)
    if located:
        profile["sn_regex"], value = located
        notes.append(f"Serial number: cell {located[0]} on sheet '{sn_sheet}' ({value}).")
    else:
        guess = guess_serial_example(path, siblings)
        if guess:
            profile["sn_regex"] = sn_regex_from_example(guess)
            profile["sn_example"] = guess
            notes.append(f"Serial number: taken from the file name (looks like {guess}).")
        else:
            warnings_.append("I could not find the serial number. Give the cell that holds it, or an example.")

    return Detection(profile, notes, _suggested_name(path), warnings_)


# --------------------------------------------------------------------------------------------------
# Text logs
# --------------------------------------------------------------------------------------------------
def detect_text(path: Path, siblings: Iterable[Path] = ()) -> Detection:
    text = read_text_file(path)
    sn_example = guess_serial_example(path, siblings, text)
    notes: list[str] = []
    warnings_: list[str] = []

    looks_like_i3070 = re.search(r"^\s*\{@BLOCK\|", text, re.MULTILINE) and re.search(r"^\s*\{@A-[A-Z0-9]+\|", text, re.MULTILINE)
    patterns = dict(I3070_PATTERNS) if looks_like_i3070 else {}
    profile = text_profile_from_patterns(patterns, sn_example, extensions=path.suffix.lower() or ".log")
    if looks_like_i3070:
        notes.append("This is an in-circuit test (i3070) log. The standard patterns were filled in.")
    else:
        warnings_.append(
            "I do not know this log format yet. Select the text that changes in the sample (a component name, a "
            "measured value) and press the matching button to teach me."
        )
    if sn_example:
        notes.append(f"Serial number: taken from the file name (looks like {sn_example}).")
    else:
        warnings_.append("I could not find the serial number. Type an example or select one in the sample.")
    return Detection(profile, notes, _suggested_name(path), warnings_)


def detect_profile(path: Path) -> Detection:
    siblings = sibling_files(path)
    return detect_excel(path, siblings) if is_excel(path) else detect_text(path, siblings)


def _suggested_name(path: Path) -> str:
    folder = path.parent.name.strip()
    return folder if folder and folder not in {".", ""} else path.stem


# --------------------------------------------------------------------------------------------------
# Previews
# --------------------------------------------------------------------------------------------------
@dataclass(slots=True)
class Preview:
    sn: str = ""
    rows: list[Measurement] = field(default_factory=list)
    total: int = 0
    duplicates: int = 0
    error: str = ""


def preview_profile(path: Path, profile: Mapping[str, Any], limit: int = 12) -> Preview:
    """Read ``path`` the way a scan would and report what came out (or why nothing did)."""
    try:
        parsed = parse_log_file(path, dict(profile))
    except (ValueError, OSError, KeyError, IndexError) as exc:
        return Preview(error=str(exc))
    entries = list(parsed.entries.values())
    return Preview(parsed.sn, entries[:limit], len(entries), len(parsed.duplicates))


@dataclass(frozen=True, slots=True)
class Highlight:
    line: int  # 0-based
    start: int
    end: int
    role: str  # block / measure (whole line), then component / measured / unit / min / max / serial


def _group_span(match: re.Match[str], name: str, offset: int = 0) -> tuple[int, int] | None:
    if name not in match.groupdict() or match.start(name) < 0:
        return None
    return match.start(name) + offset, match.end(name) + offset


def annotate_text(text: str, profile: Mapping[str, Any]) -> list[Highlight]:
    """Where a text profile finds its data in ``text``. Raises ``ValueError`` for a pattern that cannot compile."""
    compiled = compile_text_profile_regexes(dict(profile))
    block_re, measure_re = compiled["block_re"], compiled["measure_re"]
    lines = text.splitlines()
    marks: list[Highlight] = []

    if compiled["sn_re"]:
        for index, line in enumerate(lines):
            match = compiled["sn_re"].search(line)
            if match:
                group = "sn" if "sn" in match.groupdict() else (1 if match.groups() else 0)
                marks.append(Highlight(index, match.start(group), match.end(group), "serial"))
                break

    if not block_re or not measure_re:
        return marks

    for record in iter_text_records(lines, block_re, measure_re):
        block_line, measure_line = lines[record.block_index], lines[record.measure_index]
        marks.append(Highlight(record.block_index, 0, len(block_line), "block"))
        span = _group_span(record.block_match, "component", record.block_offset)
        if span is None and record.block_match.groups():
            span = (record.block_match.start(1) + record.block_offset, record.block_match.end(1) + record.block_offset)
        if span:
            marks.append(Highlight(record.block_index, *span, "component"))

        marks.append(Highlight(record.measure_index, 0, len(measure_line), "measure"))
        for group, role in (("measured", "measured"), ("type", "unit")):
            found = _group_span(record.measure_match, group)
            if found:
                marks.append(Highlight(record.measure_index, *found, role))
        tail_start = record.measure_match.start("tail") if "tail" in record.measure_match.groupdict() else -1
        if tail_start >= 0:
            tail = group_value(record.measure_match, "tail")
            for pattern in (compiled["lim3_re"], compiled["lim2_re"]):
                limit = pattern.search(tail) if pattern else None
                if limit and (group_value(limit, "min") or group_value(limit, "max")):
                    for group in ("min", "max"):
                        found = _group_span(limit, group, tail_start)
                        if found:
                            marks.append(Highlight(record.measure_index, *found, group))
                    break
    return marks


# --------------------------------------------------------------------------------------------------
# A whole folder
# --------------------------------------------------------------------------------------------------
@dataclass(slots=True)
class FolderCheck:
    tried: int = 0
    readable: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return self.tried > 0 and self.readable == self.tried


def check_files(files: Iterable[Path], profile: Mapping[str, Any]) -> FolderCheck:
    result = FolderCheck()
    for path in files:
        result.tried += 1
        preview = preview_profile(path, profile, limit=0)
        if preview.error:
            result.problems.append(f"{path.name}: {preview.error.splitlines()[0]}")
        elif not preview.sn:
            result.problems.append(f"{path.name}: no serial number found")
        elif not preview.total:
            result.problems.append(f"{path.name}: no components found")
        else:
            result.readable += 1
    return result


def check_folder(folder: Path, profile: Mapping[str, Any], limit: int = 30) -> FolderCheck:
    """Try ``profile`` on up to ``limit`` of the files it would pick up when scanning ``folder``."""
    extensions = get_profile_extensions(dict(profile))
    files = [p for p in discover_files(folder) if p.suffix.lower() in extensions]
    return check_files(files[:limit], profile)


def suggest_profile(folder: Path, profiles: Mapping[str, Mapping[str, Any]], files_per_profile: int = 3) -> str | None:
    """The profile that reads the files in ``folder`` best, or None when none of them can read them."""
    candidates = discover_files(folder)
    best: tuple[int, str] | None = None
    for name, profile in profiles.items():
        extensions = get_profile_extensions(dict(profile))
        sample = [p for p in candidates if p.suffix.lower() in extensions][:files_per_profile]
        if not sample:
            continue
        score = 0
        for path in sample:
            preview = preview_profile(path, profile, limit=0)
            if not preview.error and preview.sn and preview.total:
                score += 1000 + preview.total
        if score and (best is None or score > best[0]):
            best = (score, name)
    return best[1] if best else None
