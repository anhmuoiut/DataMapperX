"""What "Analyze by Excel File" needs, without any widget: the template workbooks, and the check of a file before it is analysed.

There is one layout for each type, and it is the one the program itself writes: Variable Gage R&R and Cpk read a RawData.xlsx (what
Data Mapping exports: ``statistics/importers.py``), and Attribute reads a table of ratings (what the Observations sheet of the Excel
report lists: ``statistics/ratings.py``). A file written by the program is therefore a file it reads, and a template is only an empty
one with its instructions.

The reading, the column matching and the data checks are the ones the analysis already has (the engine itself says what is wrong with
the data); this module puts them in one report with the sheet, row and column of each finding, so the person can correct the file and
check it again. Nothing here changes a value of the file. The engine is asked for its statistics only, never its acceptance: a study
that would FAIL is a result of the analysis, not a reason to refuse the file.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .statistics.attribute import attribute_calculation
from .statistics.checks import describe_layouts
from .statistics.design import auto_within_method
from .statistics.engine import compute
from .statistics.importers import SHEET as RAW_SHEET
from .statistics.importers import ImportedData, RawDataFormatError, import_rawdata_xlsx
from .statistics.models import AnalysisConfig
from .statistics.ratings import (
    FIELD_NAMES,
    MAX_LABELS,
    REQUIRED,
    ImportedRatings,
    RatingsFormatError,
    RatingsMapping,
    RatingsTable,
    attribute_warnings,
    build_ratings,
    mapping_problems,
    read_ratings_table,
    suggest_mapping,
)
from .utils import safe_text, to_number
from .xlsx import read_workbook

logger = logging.getLogger(__name__)

ATTRIBUTE_SHEET, OBSERVATIONS_SHEET = "Attribute_Data", "Observations"  # the template's data sheet, and the one the Excel report writes
INSTRUCTIONS_SHEET, EXAMPLES_SHEET = "Instructions", "Examples"
ATTRIBUTE_VERSION, VARIABLE_VERSION = "Attribute-1", "Variable-1"  # the format of each template; written to its Instructions sheet
ATTRIBUTE_TEMPLATE, VARIABLE_TEMPLATE = "Attribute_Template.xlsx", "Variable_Cpk_Template.xlsx"
VERSION_LABEL = "Template version"
MAX_LISTED = 20  # findings listed for one kind of problem: a file with a column of mistakes is not a list of a thousand lines
STATUS_TEXT = {"ready": "Ready for Analysis", "warnings": "Warnings Found", "invalid": "Invalid File"}
RANK = {"error": 0, "warning": 1, "info": 2}
ASSIGNED = "Repetition order explicitly assigned"  # what the engine says of a trial labelling the person has not (yet) chosen
UNUSABLE = "Missing or invalid numeric measurement"  # what the engine says of a cell; the report says it with its place
NO_TRIAL = ("No Trial in this layout: the Analysis tab's trial labelling (on unless you turn it off) numbers the readings of each sample in "
            "the order of the rows.")
_SOURCE_ROW = re.compile(r"!R(\d+)$")  # the row of a reading, as its source names it: "Raw Data!R12"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing found in a file. An ``error`` stops the analysis, a ``warning`` does not, ``info`` only says what was done."""
    severity: str
    message: str
    sheet: str = ""
    row: int | None = None
    column: str = ""

    def __str__(self) -> str:
        where = (f"Sheet: {self.sheet}" if self.sheet else "", f"Row {self.row}" if self.row else "",
                 f"Column: {self.column}" if self.column else "")
        return " | ".join([part for part in where if part] + [self.message])


@dataclass(frozen=True, slots=True)
class IntakeReport:
    """The outcome of checking a file: what was found, the sheets it has to choose from and the one that was read. ``imported`` is
    there only when nothing blocks the analysis. ``headline`` is the size of the study when it is not the one the data say by themselves."""
    path: str
    findings: tuple[Finding, ...]
    imported: ImportedRatings | ImportedData | None = None
    sheet: str = ""
    sheets: tuple[str, ...] = ()
    headline: str = ""

    @property
    def status(self) -> str:
        severities = {finding.severity for finding in self.findings}
        return "invalid" if "error" in severities else "warnings" if "warning" in severities else "ready"

    @property
    def ready(self) -> bool:
        return self.imported is not None

    def count(self, severity: str) -> int:
        return sum(1 for finding in self.findings if finding.severity == severity)

    @property
    def summary(self) -> str:
        """The size of the study, for a file that can be analysed."""
        imported = self.imported
        if imported is None:
            return ""
        if self.headline:
            return self.headline
        if isinstance(imported, ImportedData):
            return (f"{len(imported.items)} test item{'' if len(imported.items) == 1 else 's'} · {imported.samples} samples · "
                    f"{imported.rows} rows")
        noun = "appraiser" if imported.appraisers == 1 else "appraisers"
        shown = ", ".join(imported.categories[:6]) + (" …" if len(imported.categories) > 6 else "")
        return (f"{imported.samples} samples · {imported.appraisers} {noun} · {imported.trials} trials per sample · "
                f"{len(imported.categories)} categories: {shown}")


def _report(path: Path, findings: list[Finding], imported=None, table=None, headline: str = "") -> IntakeReport:
    ordered = tuple(sorted(findings, key=lambda finding: RANK[finding.severity]))
    blocked = any(finding.severity == "error" for finding in ordered)
    return IntakeReport(str(path), ordered, None if blocked else imported, table.sheet if table else "",
                        table.sheets if table else (), headline)


def mapping_from_record(record: dict) -> RatingsMapping:
    """The mapping a person chose in the column dialog, as ``build_ratings`` recorded it."""
    return RatingsMapping(**record["columns"], assign_trials=record["assign_trials"],
                          categories=tuple((label, name) for label, name in record["categories"]))


# ----------------------------------------------------------------------------- what both checks share
def _listed(sheet: str, column: str, rows: list[int], message: str) -> list[Finding]:
    found = [Finding("error", message, sheet, row, column) for row in rows[:MAX_LISTED]]
    if len(rows) > MAX_LISTED:
        found.append(Finding("error", f"{len(rows) - MAX_LISTED} more rows: {message}", sheet, column=column))
    return found


def _each_capped(findings: list[Finding]) -> list[Finding]:
    """The first MAX_LISTED findings of each severity (the analysis says the same of every test item of a big file)."""
    kept: list[Finding] = []
    for severity in ("error", "warning"):
        group = [finding for finding in findings if finding.severity == severity]
        kept += group[:MAX_LISTED]
        if len(group) > MAX_LISTED:
            kept.append(Finding(severity, f"… and {len(group) - MAX_LISTED} more {severity}s of the same kind.", group[0].sheet))
    return kept


def _template_version(path: Path) -> str:
    """The version a DataMapperX template wrote on its Instructions sheet; empty for any other workbook."""
    def work(reader) -> str:
        if INSTRUCTIONS_SHEET not in reader.sheet_names:
            return ""
        for _number, values in reader.iter_rows(INSTRUCTIONS_SHEET, max_row=12):
            if values and str(values[0] or "").strip() == VERSION_LABEL and len(values) > 1:
                return str(values[1] or "").strip()
        return ""

    return read_workbook(path, work)


def _unreadable(path: Path, exc: Exception) -> IntakeReport:
    """A damaged file, or one another program has open: whatever it is, the person is told which file and why."""
    logger.info("Could not read %s: %s", path.name, exc, exc_info=True)
    return _report(path, [Finding("error", f"The workbook cannot be read ({exc}). Is it a valid .xlsx file, closed in Excel?")])


def _wrong_version(version: str, expected: str) -> list[Finding]:
    return ([Finding("warning", f"Template version {version}; this program writes {expected}.", INSTRUCTIONS_SHEET)]
            if version and version != expected else [])


# ----------------------------------------------------------------------------- checking an Attribute file
def _rows_without(table: RatingsTable, position: dict[str, int], name: str) -> list[int]:
    return [number for cells, number in zip(table.rows, table.numbers, strict=True) if not cells[position[name]]]


def validate_attribute(path: str | Path, sheet: str | None = None, mapping: RatingsMapping | None = None) -> IntakeReport:
    """Check a workbook for Attribute Agreement. With no ``sheet`` it reads ``Attribute_Data`` (the template), else ``Observations`` (the
    sheet of the Excel report), else the first sheet; with no ``mapping`` the columns are the ones their names suggest. Blocking errors
    say sheet, row and column where they can."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        return _report(path, [Finding("error", "Only .xlsx workbooks are supported.")])
    try:
        table = read_ratings_table(path, sheet or ATTRIBUTE_SHEET, (OBSERVATIONS_SHEET,))
        version = _template_version(path)
    except RatingsFormatError as exc:
        return _report(path, [Finding("error", str(exc))])
    except Exception as exc:
        return _unreadable(path, exc)
    sheet = table.sheet
    mapping = mapping or RatingsMapping(**suggest_mapping(table.headers))
    problems = mapping_problems(table, mapping)
    if problems:
        return _report(path, [Finding("error", f"{problem} Use Review columns…", sheet) for problem in problems], table=table)

    position = {name: table.headers.index(column) for name, column in mapping.columns().items()}
    errors: list[Finding] = []
    for name in REQUIRED:
        errors += _listed(sheet, getattr(mapping, name), _rows_without(table, position, name), f"{FIELD_NAMES[name]} is empty.")
    if "trial" in position:
        empty = _rows_without(table, position, "trial")
        if 0 < len(empty) < len(table.rows):  # a Trial column with nothing in it is the same as none
            errors += _listed(sheet, mapping.trial, empty, "Trial is empty: give every rating its trial, or none.")
    if errors:
        return _report(path, sorted(errors, key=lambda finding: finding.row or float("inf")), table=table)  # in the order of the sheet

    imported = build_ratings(table, mapping)
    findings = [Finding("info", note, sheet) for note in imported.warnings] + _wrong_version(version, ATTRIBUTE_VERSION)
    rows = imported.dataset.observations
    by_item: dict[str, list] = defaultdict(list)
    for row in rows:
        by_item[row.test_item].append(row)
    for item, group in by_item.items():  # the analysis's own rules (duplicates, missing trials, uneven counts, a Standard that disagrees…)
        _metrics, _details, issues = attribute_calculation(group, [], None, None, AnalysisConfig(method="attribute"))
        prefix = f"{item}: " if len(by_item) > 1 else ""
        findings += [Finding(issue.severity, prefix + issue.message, sheet) for issue in issues]
    if len(imported.categories) > MAX_LABELS:
        findings.append(Finding("warning", f"{len(imported.categories)} different labels: too many for categories. Is "
                                           f"'{mapping.rating}' the column of PASS and FAIL?", sheet, column=mapping.rating))
    elif len(imported.categories) > 2:
        findings.append(Finding("warning", f"{len(imported.categories)} categories ({', '.join(imported.categories)}); a Pass / Fail "
                                           "study has two. Review columns… can count variants as one.", sheet, column=mapping.rating))
    unused = sorted({row.standard for row in rows if row.standard} - {row.value for row in rows if row.value})
    if unused:
        findings.append(Finding("warning", f"The Standard has labels no rating uses: {', '.join(unused)}.", sheet, column=mapping.standard))
    findings += [Finding("warning", text, sheet, column=mapping.rating) for text in attribute_warnings(rows)]
    return _report(path, findings, imported, table)


# ----------------------------------------------------------------------------- checking a Variable GR&R or Cpk file
def validate_variable(path: str | Path, method: str) -> IntakeReport:
    """Check a RawData.xlsx (the file Data Mapping exports, and the template) for Variable Gage R&R (``method`` "grr") or Cpk
    ("capability"). The engine is asked for its statistics only, never the acceptance, so what it says of the data is what the analysis
    will say. A test item it cannot use (an empty or non-numeric cell, an unbalanced study) is a warning while another can be analysed,
    as it always was in the analysis; when none can, the file is invalid."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        return _report(path, [Finding("error", "Only .xlsx workbooks are supported.")])
    try:
        imported = import_rawdata_xlsx(path)
        version = _template_version(path)
    except RawDataFormatError as exc:
        return _report(path, [Finding("error", str(exc))])
    except Exception as exc:
        return _unreadable(path, exc)
    sheet, rows = imported.sheet, imported.dataset.observations
    findings = _wrong_version(version, VARIABLE_VERSION) + [Finding("warning", text, sheet) for text in imported.warnings]
    unlabelled = method == "grr" and not any(safe_text(row.trial) for row in rows)
    if unlabelled:
        findings.append(Finding("info", NO_TRIAL, sheet))  # the layout has no Trial: a fact, not a problem
    config = (AnalysisConfig(method="grr", assign_trials=unlabelled) if method == "grr"
              else AnalysisConfig(method="capability", within_method=auto_within_method(rows)))
    results = compute(rows, config)
    broken = {stat.test_item for stat in results if not stat.valid}
    level = "error" if len(broken) == len(results) else "warning"
    said = []
    for row in rows:  # the cells the analysis cannot use, where they are
        if row.test_item in broken and (not safe_text(row.value) or to_number(row.value) is None):
            match = _SOURCE_ROW.search(row.source)
            said.append(Finding(level, "Measurement is empty." if not safe_text(row.value) else "Measurement must be numeric.", sheet,
                                int(match.group(1)) if match else None, row.test_item))
    for stat in results:
        said += [Finding(level if issue.severity == "error" else "warning", issue.message, sheet, column=stat.test_item)
                 for issue in stat.issues if issue.severity != "info" and not issue.message.startswith((ASSIGNED, UNUSABLE))]
    findings += _each_capped(sorted(said, key=lambda finding: RANK[finding.severity]))
    layout = describe_layouts(rows)
    report = _report(path, findings, imported, headline=layout[0].rstrip(".") if method == "grr" and layout else "")
    return IntakeReport(report.path, report.findings, report.imported, sheet, (), report.headline)  # one sheet: nothing to choose


# ----------------------------------------------------------------------------- the templates
_ATTRIBUTE_FIELDS = ("item", "sample", "appraiser", "trial", "rating", "standard")  # the columns of the Observations sheet of the report
_ATTRIBUTE_NAMES = {"item": "Test Item", "sample": "Sample ID", "appraiser": "Appraiser", "trial": "Trial", "rating": "Rating",
                    "standard": "Standard"}
_ATTRIBUTE_WHAT = {
    "item": ("Optional", "What is assessed, when one file holds several. Empty: the file name.", "Text"),
    "sample": ("Required", "The part or unit that is rated. Give every rating of one sample the same ID.", "Text or number"),
    "appraiser": ("Optional", "Who rated. Empty: one unnamed appraiser. Needed to compare appraisers.", "Name or number"),
    "trial": ("Optional", "The repetition: 1, 2, 3… for the same appraiser and sample. Empty column: numbered in row order. "
                          "If used, fill every row.", "Number"),
    "rating": ("Required", "The decision of one assessment.", "PASS or FAIL. Any two labels work (Pass/Fail, OK/NG) if the whole "
                                                              "file spells them alike: PASS and Pass count as different labels."),
    "standard": ("Optional", "The known correct rating of the sample. Needed to compare with the standard. The same on every row of a "
                             "sample; if given, give it for every sample.", "The same labels as Rating"),
}
_ATTRIBUTE_EXAMPLE = (("Visual check", "S001", "Ann", 1, "PASS", "PASS"), ("Visual check", "S001", "Ann", 2, "PASS", "PASS"),
                      ("Visual check", "S001", "Ben", 1, "PASS", "PASS"), ("Visual check", "S001", "Ben", 2, "PASS", "PASS"),
                      ("Visual check", "S002", "Ann", 1, "FAIL", "FAIL"), ("Visual check", "S002", "Ann", 2, "FAIL", "FAIL"),
                      ("Visual check", "S002", "Ben", 1, "FAIL", "FAIL"), ("Visual check", "S002", "Ben", 2, "PASS", "FAIL"))
_RAWDATA_WHAT = (
    ("STT", "Required", "A running number of the row: 1, 2, 3… It is not a trial.", "Number"),
    ("SN", "Required", "The sample: a part or a serial number. Gage R&R: give it on every row that is a repetition of that sample, "
                       "the same number of rows (at least two) for every sample. Cpk: one row for each unit.", "Text or number"),
    ("Test item columns", "Required", "One column for each test item, headed with its name (C, D, … as many as you need, side by side). "
                                      "The measured numbers, one in each row.", "Number"),
    ("Empty column", "Required", "Leave the column after the last test item empty: it ends the test items.", "Nothing"),
    ("NAME", "Optional", "The name of a test item, exactly as in its column heading. One row for each test item.", "Text"),
    ("MIN", "Optional", "The lower specification limit (LSL) of that test item. Cpk needs at least one limit for every test item.", "Number"),
    ("MAX", "Optional", "The upper specification limit (USL) of that test item. Above the MIN.", "Number"),
    ("UNIT", "Optional", "The unit of that test item.", "Text"),
)
_RAWDATA_EXAMPLE_HEADERS = ["STT", "SN", "R10", "R11", None, "NAME", "MIN", "MAX", "UNIT"]
_RAWDATA_EXAMPLE = tuple(
    [n + 1, f"VSE{n // 2 + 1:03d}", 1000 + 6 * (n // 2) + n % 2, 4700 + 3 * (n // 2) + n % 2, None,
     *((("R10", 950, 1050, "Ohm"), ("R11", 4650, 4750, "Ohm"))[n] if n < 2 else (None,) * 4)] for n in range(6))
_RAWDATA_PLACEHOLDERS = ("Test item 1", "Test item 2", "Test item 3")


def _styles():
    from openpyxl.styles import Alignment, Font, PatternFill

    required = (PatternFill("solid", fgColor="0068A8"), Font(bold=True, color="FFFFFF"))
    optional = (PatternFill("solid", fgColor="DCE6F1"), Font(bold=True, color="1F2D3D"))
    return required, optional, Font, Alignment


def _instructions(book, title: str, version: str, intro: list[str], rows, closing: str) -> None:
    """The Instructions sheet: the template version, a few lines of what to do, and a line for every column."""
    _required, _optional, font, alignment = _styles()
    notes = book.create_sheet(INSTRUCTIONS_SHEET)
    notes.append([title])
    notes["A1"].font = font(bold=True, size=14)
    notes.append([VERSION_LABEL, version])
    for line in intro:
        notes.append([line])
    notes.append([])
    start = notes.max_row + 1
    notes.append(["Column", "Required?", "What to enter", "Accepted values"])
    for cell in notes[start]:
        cell.font = font(bold=True)
    for row in rows:
        notes.append(list(row))
    notes.append([])
    notes.append([closing])
    for letter, width in zip("ABCD", (18, 12, 70, 52), strict=True):
        notes.column_dimensions[letter].width = width
    for row in notes.iter_rows(min_row=start + 1, max_row=start + len(rows)):
        for cell in row:
            cell.alignment = alignment(wrap_text=True, vertical="top")


def _examples_sheet(book, blocks: list[tuple[str, list, tuple]]) -> None:
    """The Examples sheet: a banner, then for each block its title, headers and rows. It is never read as data."""
    _required, _optional, font, _alignment = _styles()
    sample = book.create_sheet(EXAMPLES_SHEET)
    sample.append(["EXAMPLE ONLY: these rows are not analysed."])
    sample["A1"].font = font(bold=True, color="C0392B")
    for title, headers, rows in blocks:
        sample.append([])
        sample.append([title])
        sample.cell(row=sample.max_row, column=1).font = font(bold=True)
        sample.append(headers)
        for cell in sample[sample.max_row]:
            cell.font = font(bold=True)
        for values in rows:
            sample.append(list(values))
    for letter in "ABCDEFGHI":
        sample.column_dimensions[letter].width = 16


def _save(book, path: str | Path, version: str) -> Path:
    book.properties.creator = "DataMapperX"
    book.properties.title = f"DataMapperX template {version}"
    path = Path(path)
    book.save(path)
    return path


def write_attribute_template(path: str | Path) -> Path:
    """Attribute_Template.xlsx: the data sheet (the columns the Excel report lists as Observations, headers only), the Instructions,
    and an Examples sheet that is not data."""
    from openpyxl import Workbook

    required, optional, _font, _alignment = _styles()
    book = Workbook()
    data = book.active
    data.title = ATTRIBUTE_SHEET
    for column, name in enumerate(_ATTRIBUTE_FIELDS, 1):
        cell = data.cell(row=1, column=column, value=_ATTRIBUTE_NAMES[name])
        cell.fill, cell.font = required if name in ("sample", "rating") else optional
        data.column_dimensions[cell.column_letter].width = 18
        if name == "sample":
            data.column_dimensions[cell.column_letter].number_format = "@"  # sample IDs stay text: 007 stays 007
    data.freeze_panes = "A2"
    _instructions(book, "Attribute Agreement: Excel template", ATTRIBUTE_VERSION,
                  ["Fill the sheet 'Attribute_Data': one row per rating, headers in row 1. These are the columns of the Observations sheet "
                   "of the Excel report, so that sheet can be used as it is (a Source column is ignored).",
                   "Other column names can be matched when the file is opened."],
                  [[_ATTRIBUTE_NAMES[name], *_ATTRIBUTE_WHAT[name]] for name in _ATTRIBUTE_FIELDS],
                  "The 'Examples' sheet only shows how a completed sheet looks. It is never analysed.")
    _examples_sheet(book, [("Attribute Agreement (sheet Attribute_Data)", [_ATTRIBUTE_NAMES[n] for n in _ATTRIBUTE_FIELDS],
                            _ATTRIBUTE_EXAMPLE)])
    return _save(book, path, ATTRIBUTE_VERSION)


def write_variable_template(path: str | Path) -> Path:
    """Variable_Cpk_Template.xlsx: the sheet ``Raw Data`` in the layout of the RawData.xlsx that Data Mapping exports (one layout for
    Gage R&R and for Cpk; the method is chosen when the file is opened), the Instructions, and an Examples sheet that is not data."""
    from openpyxl import Workbook

    required, optional, _font, _alignment = _styles()
    book = Workbook()
    data = book.active
    data.title = RAW_SHEET
    last = 2 + len(_RAWDATA_PLACEHOLDERS)
    for column, text in enumerate(("STT", "SN", *_RAWDATA_PLACEHOLDERS), 1):
        cell = data.cell(row=1, column=column, value=text)
        cell.fill, cell.font = required
    for offset, text in enumerate(("NAME", "MIN", "MAX", "UNIT")):
        cell = data.cell(row=1, column=last + 2 + offset, value=text)
        cell.fill, cell.font = optional
    for row, text in enumerate(_RAWDATA_PLACEHOLDERS, 2):
        data.cell(row=row, column=last + 2, value=text)  # the limits go beside their test item, one row for each
    for letter in "ABCDEFGHIJ":
        data.column_dimensions[letter].width = 14
    data.column_dimensions["B"].number_format = "@"  # sample IDs stay text: 007 stays 007
    data.freeze_panes = "C2"
    _instructions(book, "Variable Gage R&R and Cpk: Excel template", VARIABLE_VERSION,
                  ["Fill the sheet 'Raw Data': the layout of the RawData.xlsx that Data Mapping exports, so that file can be used as it is. "
                   "Rename the test item columns (and their NAME) and add or remove columns as you need.",
                   "You choose Variable GR&R or Cpk when you open the file. Gage R&R: the readings of one SN are its trials, in the order of "
                   "the rows; operators are set in the Analysis tab."],
                  _RAWDATA_WHAT, "The 'Examples' sheet only shows how a completed sheet looks. It is never analysed.")
    _examples_sheet(book, [("Raw Data: 3 samples of 2 readings (Gage R&R), or 6 units (Cpk)", _RAWDATA_EXAMPLE_HEADERS, _RAWDATA_EXAMPLE)])
    return _save(book, path, VARIABLE_VERSION)
