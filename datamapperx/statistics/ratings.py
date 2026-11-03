"""Ratings for Attribute Agreement Analysis from a long-format table: one row per assessment, in a CSV or an Excel sheet.

A row holds the Sample ID and the Rating, and optionally the Test Item, the Appraiser, the Trial and the known Standard
(the "Attribute column" arrangement of Minitab's Attribute Agreement Analysis). The user maps the columns; nothing is guessed
silently. The file is never changed: the ratings keep the labels they have in it (PASS stays PASS, ``Pass`` stays ``Pass``),
and a label is renamed only when the user maps it to a category. Whatever is empty in the file stays empty, so the analysis
reports it (a missing Sample ID or rating, a missing Appraiser or Standard) instead of this module filling it in.

No widget here: ``ui/ratings_import.py`` draws the mapping, and everything it decides is decided in this module.
"""
from __future__ import annotations

import csv
import io
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import to_number
from ..xlsx import read_workbook
from .dataset import Dataset
from .models import Observation

FIELDS = ("sample", "rating", "item", "appraiser", "trial", "standard")
REQUIRED = ("sample", "rating")
FIELD_NAMES = {"sample": "Sample ID", "rating": "Rating", "item": "Test Item", "appraiser": "Appraiser", "trial": "Trial",
               "standard": "Known Standard"}
MAX_LABELS = 12  # more distinct labels than this are not categories: the Rating column is probably the wrong one
CSV_ENCODINGS = ("utf-8-sig", "cp1252")
CSV_DELIMITERS = ",;\t|"
SUFFIXES = {".csv", ".txt", ".tsv", ".xlsx"}

# What a column is called, by field. Whole-name matches win over a name that merely contains the word.
KEYWORDS = {
    "sample": ("sample id", "samples", "sample", "serial number", "serial", "sn", "unit", "part"),
    "rating": ("measurements", "measurement", "ratings", "rating", "assessment", "response", "result", "attribute"),
    "standard": ("standard", "reference", "known", "truth", "expected"),
    "appraiser": ("appraisers", "appraiser", "operator", "inspector", "rater", "assessor"),
    "trial": ("trial", "repetition", "replicate", "repeat"),
    "item": ("test item", "item", "component", "characteristic"),
}


class RatingsFormatError(ValueError):
    """The file or the column mapping cannot be used; the message says why."""


@dataclass(frozen=True, slots=True)
class RatingsTable:
    """A sheet or a CSV as text: the header, and the cells of each non-empty row with the row number they had in the file."""
    path: str
    name: str
    sheet: str
    sheets: tuple[str, ...]
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numbers: tuple[int, ...]
    empty_rows: int = 0


@dataclass(frozen=True, slots=True)
class RatingsMapping:
    """Which column holds what ("" for a column the file does not have), and how the ratings are read."""
    sample: str
    rating: str
    item: str = ""
    appraiser: str = ""
    trial: str = ""
    standard: str = ""
    assign_trials: bool = True  # with no Trial column: number the ratings of each sample 1, 2, 3... in the order of the rows
    categories: tuple[tuple[str, str], ...] = ()  # (label in the file, category it counts as); other labels are kept as they are

    def columns(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in FIELDS if getattr(self, name)}


@dataclass(frozen=True, slots=True)
class ImportedRatings:
    dataset: Dataset
    items: tuple[str, ...]
    samples: int
    appraisers: int
    ratings: int
    trials: str  # "3", or "2–3" when the samples differ
    categories: tuple[str, ...]  # the labels the analysis will see
    warnings: tuple[str, ...] = field(default=())
    record: dict[str, Any] = field(default_factory=dict, compare=False)  # what was mapped, for the study's record


# ----------------------------------------------------------------------------- reading the file
def _cell_text(value: Any) -> str:
    """A cell as text, the same for a CSV and a workbook: 1 and 1.0 are both "1", an empty cell is empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else format(value, ".15g")
    return str(value).strip()


def _unique(headers: Sequence[str]) -> tuple[str, ...]:
    """Header names that are all different and not empty, so a column can always be chosen by its name."""
    seen: Counter[str] = Counter()
    named = []
    for position, header in enumerate(headers, 1):
        base = header or f"Column {position}"
        seen[base] += 1
        named.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return tuple(named)


def _table(path: Path, sheet: str, sheets: Sequence[str], grid: Sequence[tuple[int, Sequence[Any]]]) -> RatingsTable:
    header_at = next((i for i, (_, cells) in enumerate(grid) if any(_cell_text(c) for c in cells)), None)
    if header_at is None:
        raise RatingsFormatError(f"'{path.name}' has no data: the first row with anything in it must name the columns.")
    headers = [_cell_text(c) for c in grid[header_at][1]]
    while headers and not headers[-1]:
        headers.pop()  # empty columns at the right edge are not columns
    names = _unique(headers)
    rows, numbers, empty = [], [], 0
    for number, cells in grid[header_at + 1:]:
        text = tuple(_cell_text(cells[i]) if i < len(cells) else "" for i in range(len(names)))
        if any(text):
            rows.append(text)
            numbers.append(number)
        else:
            empty += 1
    if not rows:
        raise RatingsFormatError(f"'{path.name}' has column names but no rows of ratings.")
    return RatingsTable(str(path), path.name, sheet, tuple(sheets), names, tuple(rows), tuple(numbers), empty)


def _read_csv(path: Path) -> RatingsTable:
    raw = path.read_bytes()
    for encoding in CSV_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # cp1252 leaves a few bytes undefined; nothing here depends on them
        text = raw.decode("latin-1")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    grid = [(number, row) for number, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1)]
    return _table(path, "", (), grid)


def read_ratings_table(path: str | Path, sheet: str | None = None, fallbacks: Sequence[str] = ()) -> RatingsTable:
    """Read a CSV (comma, semicolon, tab or bar separated; UTF-8 or Windows-1252) or the sheet of an XLSX workbook: ``sheet``, else the
    first of the ``fallbacks`` the workbook has, else its first sheet."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise RatingsFormatError(f"'{path.name}' is not a CSV or XLSX file.")
    if suffix != ".xlsx":
        return _read_csv(path)

    def work(reader):
        names = tuple(reader.sheet_names)
        if not names:
            raise RatingsFormatError("The workbook has no worksheet.")
        chosen = next((name for name in (sheet, *fallbacks) if name in names), names[0])
        return chosen, names, [(number, values) for number, values in reader.iter_rows(chosen)]

    chosen, names, grid = read_workbook(path, work)
    return _table(path, chosen, names, grid)


# ----------------------------------------------------------------------------- the mapping
def suggest_mapping(headers: Sequence[str]) -> dict[str, str]:
    """A starting point for the mapping, from the column names; the user confirms or changes every choice. A column is
    suggested for one field only, and a field with no matching name is left empty."""
    names = {header: " ".join(header.casefold().replace("_", " ").split()) for header in headers}
    taken: set[str] = set()
    found = dict.fromkeys(FIELDS, "")
    for exact in (True, False):
        for name in ("sample", "rating", "standard", "appraiser", "trial", "item"):
            if found[name]:
                continue
            for keyword in KEYWORDS[name]:
                match = next((h for h, text in names.items() if h not in taken and (text == keyword if exact else keyword in text.split())), "")
                if match:
                    found[name] = match
                    taken.add(match)
                    break
    return found


def mapping_problems(table: RatingsTable, mapping: RatingsMapping) -> list[str]:
    """What is wrong with the mapping (empty when it can be used)."""
    problems = [f"Choose the {FIELD_NAMES[name]} column." for name in REQUIRED if not getattr(mapping, name)]
    chosen = mapping.columns()
    problems += [f"The {FIELD_NAMES[name]} column '{column}' is not in the file." for name, column in chosen.items()
                 if column not in table.headers]
    counts = Counter(chosen.values())
    problems += [f"The column '{column}' is chosen for more than one field." for column, n in counts.items() if n > 1]
    return problems


def _column_values(table: RatingsTable, column: str) -> list[str]:
    if not column or column not in table.headers:
        return []
    position = table.headers.index(column)
    return [row[position] for row in table.rows]


def label_counts(table: RatingsTable, mapping: RatingsMapping) -> list[tuple[str, int]]:
    """Every distinct label of the Rating and Standard columns, with how often it occurs, in the order first met."""
    counts: Counter[str] = Counter()
    for column in (mapping.rating, mapping.standard):
        counts.update(label for label in _column_values(table, column) if label)
    return list(counts.items())


def attribute_settings(confidence: str, enabled: bool, minimum: str) -> tuple[float, float | None]:
    """(confidence level as a proportion, minimum agreement in percent or None) from what is on screen. A ValueError says what
    to fix. The minimum is read only when acceptance is on."""
    try:
        level = float(str(confidence).strip().rstrip("%"))
    except ValueError:
        raise ValueError("Confidence level: choose a percentage such as 95 %.") from None
    level = level / 100 if level > 1 else level
    if not 0.5 <= level < 1:
        raise ValueError("Confidence level must be at least 50 % and below 100 %.")
    if not enabled:
        return level, None
    try:
        value = float(str(minimum).strip().rstrip("%"))
    except ValueError:
        raise ValueError("Minimum agreement: enter a percentage such as 90.") from None
    if not math.isfinite(value) or not 0 < value <= 100:
        raise ValueError("Minimum agreement must be a percentage above 0 and at most 100.")
    return level, value


# ----------------------------------------------------------------------------- building the dataset
def build_ratings(table: RatingsTable, mapping: RatingsMapping) -> ImportedRatings:
    """The ratings as an immutable dataset (worksheet order, one ``Observation`` per row).

    Sample ID, Rating and the optional columns are copied as they are, trimmed of spaces. The Test Item is the file name when
    there is no Test Item column. With no Trial column and ``assign_trials`` the ratings of each sample by each appraiser are
    numbered 1, 2, 3... in row order (said in the warnings); with a Trial column the file's own trials are used, empty or not.
    An empty Appraiser is the unnamed appraiser (shown as 1). Raises ``RatingsFormatError`` for a mapping that cannot be used.
    """
    problems = mapping_problems(table, mapping)
    if problems:
        raise RatingsFormatError(" ".join(problems))
    renamed = {label: category for label, category in mapping.categories if category and category != label}
    position = {name: table.headers.index(column) for name, column in mapping.columns().items()}
    default_item = Path(table.name).stem
    stem = table.name if not table.sheet else f"{table.name}!{table.sheet}"
    count: Counter[tuple[str, str, str]] = Counter()
    observations = []
    for cells, number in zip(table.rows, table.numbers, strict=True):
        def cell(name: str, cells=cells) -> str:
            return cells[position[name]] if name in position else ""

        item, sample, appraiser = cell("item") or default_item, cell("sample"), cell("appraiser")
        rating, standard = cell("rating"), cell("standard")
        trial = cell("trial")
        if "trial" not in position and mapping.assign_trials:
            count[(item, sample, appraiser)] += 1
            trial = str(count[(item, sample, appraiser)])
        observations.append(Observation(item, sample, renamed.get(rating, rating), trial=trial, operator=appraiser,
                                        source=f"{stem}!R{number}", standard=renamed.get(standard, standard)))
    warnings = []
    if "trial" not in position and mapping.assign_trials:
        warnings.append("No Trial column: the ratings of each sample were numbered 1, 2, 3… in the order of the rows.")
    if table.empty_rows:
        warnings.append(f"{table.empty_rows} empty row(s) in the file were skipped.")
    merged = sorted({label for label, _ in label_counts(table, mapping) if label in renamed})
    if merged:
        warnings.append("Labels counted as another category: " + ", ".join(f"{label} → {renamed[label]}" for label in merged) + ".")
    unrated = sum(1 for o in observations if not o.value)
    if unrated:
        warnings.append(f"{unrated} row(s) have no rating; the analysis cannot use them until they are filled in.")
    rows = tuple(observations)
    dataset = Dataset.from_observations(
        rows, order_basis="worksheet",
        description=f"Ratings table {stem}; " + ", ".join(f"{FIELD_NAMES[n]} = '{c}'" for n, c in mapping.columns().items()))
    cells_per = Counter((o.test_item, o.sample_id, o.operator) for o in rows)
    sizes = sorted(set(cells_per.values()))
    trials = str(sizes[0]) if len(sizes) == 1 else f"{sizes[0]}–{sizes[-1]}"
    categories = tuple(sorted({o.value for o in rows if o.value} | {o.standard for o in rows if o.standard},
                              key=lambda text: (text.casefold(), text)))
    record = {"file": table.path, "sheet": table.sheet, "columns": mapping.columns(), "assign_trials": mapping.assign_trials,
              "categories": [list(pair) for pair in mapping.categories]}
    return ImportedRatings(dataset, tuple(dict.fromkeys(o.test_item for o in rows)), len({o.sample_id for o in rows}),
                           len({o.operator for o in rows}), len(rows), trials, categories, tuple(warnings), record)


# ----------------------------------------------------------------------------- what the Data tab says about ratings
def attribute_summary(rows: Sequence[Observation]) -> str:
    """The one-line summary of the Data tab for ratings."""
    cells = Counter((row.test_item, row.sample_id, row.operator) for row in rows)
    sizes = sorted(set(cells.values()))
    trials = "–".join(str(n) for n in dict.fromkeys((sizes[0], sizes[-1]))) if sizes else "0"
    return (f"Test Items {len({row.test_item for row in rows})}  ·  Samples {len({row.sample_id for row in rows})}  ·  "
            f"Appraisers {len({row.operator for row in rows})}  ·  Ratings {len(rows)}  ·  Trials per Sample {trials}")


def attribute_warnings(rows: Sequence[Observation]) -> list[str]:
    """Hints for the Data tab when the data do not look like ratings (the analysis itself reports what is wrong with them)."""
    values = [str(row.value).strip() for row in rows if str(row.value).strip()]
    distinct = len(set(values))
    if values and distinct > MAX_LABELS and all(to_number(value) is not None for value in values):
        return [f"The ratings are numbers with {distinct} different values. Attribute Agreement analyses categories such as "
                "PASS and FAIL: check which column holds the rating."]
    return []


def category_mapping(pairs: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The categories a user typed, as the mapping stores them: only labels given a different, non-empty name."""
    return tuple((label, name.strip()) for label, name in pairs.items() if name.strip() and name.strip() != label)
