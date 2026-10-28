"""A small, fast reader for ``.xlsx`` workbooks, using only the standard library.

openpyxl takes about 0.5 s to import and, even in read-only mode, scans every sheet of a workbook (including
large chart-data sheets) before it returns a single cell. A log only needs a few rows of one or two sheets, so they
are read here directly: roughly five times faster, and openpyxl is then only needed to *write* the export.

Cell values follow openpyxl's rules (``data_only=True``) so results are identical. Anything this reader does not
handle raises ``UnsupportedWorkbook`` and ``read_workbook`` falls back to openpyxl.
"""

from __future__ import annotations

import datetime as dt
import logging
import posixpath
import re
import warnings
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar
from zipfile import ZipFile

from .utils import column_number

logger = logging.getLogger(__name__)
T = TypeVar("T")


class UnsupportedWorkbook(Exception):
    """The file uses something this reader does not handle; use openpyxl instead."""


# What a malformed or unusual file can raise inside the reader. Callers never see these: they become
# ``UnsupportedWorkbook``, so a problem the *caller* raises (such as "no worksheets") is never mistaken for one.
_PARSE_ERRORS = (ET.ParseError, KeyError, IndexError, AttributeError, TypeError, ValueError)


_WINDOWS_EPOCH = dt.datetime(1899, 12, 30)
_MAC_EPOCH = dt.datetime(1904, 1, 1)

# Number formats that mean "date or time" (the same table and rules openpyxl uses).
_BUILTIN_DATE_FORMATS = {
    14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm",
    21: "h:mm:ss", 22: "m/d/yy h:mm", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0",
}
_STRIP_FORMAT = re.compile(r'".*?"|\[(?!hh?\]|mm?\]|ss?\])[^\]]*\]')
_TIMEDELTA_FORMAT = re.compile(r"\[hh?\](:mm(:ss(\.0*)?)?|.0*)|\[mm?\](:ss(\.0*)?)?|\[ss?\](\.0*)?", re.IGNORECASE)


def is_date_format(code: str | None) -> bool:
    if code is None:
        return False
    stripped = _STRIP_FORMAT.sub("", code.split(";")[0])
    return re.search(r"(?<![_\\])[dmhysDMHYS]", stripped) is not None


def is_timedelta_format(code: str | None) -> bool:
    return code is not None and _TIMEDELTA_FORMAT.search(code.split(";")[0]) is not None


def _from_excel(value: float, epoch: dt.datetime, as_delta: bool) -> Any:
    if as_delta:
        delta = dt.timedelta(days=value)
        if delta.microseconds:
            delta = dt.timedelta(seconds=delta.total_seconds() // 1, microseconds=round(delta.microseconds, -3))
        return delta
    day, fraction = divmod(value, 1)
    diff = dt.timedelta(milliseconds=round(fraction * 86400 * 1000))
    if 0 <= value < 1 and diff.days == 0:
        minutes, seconds = divmod(diff.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return dt.time(hours, minutes, seconds, diff.microseconds)
    if 0 < value < 60 and epoch == _WINDOWS_EPOCH:
        day += 1
    return epoch + dt.timedelta(days=day) + diff


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attribute(element: ET.Element, name: str) -> str | None:
    """An attribute whatever its namespace (the relationship id is namespaced, and differs in 'strict' files)."""
    for key, value in element.attrib.items():
        if key == name or key.endswith("}" + name):
            return value
    return None


def _text_of(node: ET.Element) -> str:
    """Plain text of a shared / inline string: the direct text plus every rich-text run (phonetic hints ignored)."""
    parts = []
    for child in node:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _column_of(reference: str) -> int:
    number = 0
    for char in reference:
        if "A" <= char <= "Z":
            number = number * 26 + ord(char) - 64
        elif "a" <= char <= "z":
            number = number * 26 + ord(char) - 96
        else:
            break
    return number


class _Reader(ABC):
    """What the application needs from a workbook; subclasses only have to provide ``iter_rows``."""

    @property
    @abstractmethod
    def sheet_names(self) -> list[str]:
        """The names of the worksheets, in workbook order."""

    @abstractmethod
    def iter_rows(
        self, sheet: str, *, min_row: int = 1, max_row: int | None = None, max_col: int | None = None
    ) -> Iterator[tuple[int, list[Any]]]:
        """Yield ``(row number, values)`` for the rows that exist, lazily."""

    @abstractmethod
    def close(self) -> None:
        """Release the file."""

    def __enter__(self) -> _Reader:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def grid(self, sheet: str, max_rows: int, max_cols: int) -> list[list[Any]]:
        """The top-left corner of a sheet as a list of rows; rows that do not exist are empty lists."""
        rows: list[list[Any]] = []
        for number, values in self.iter_rows(sheet, max_row=max_rows, max_col=max_cols):
            rows.extend([] for _ in range(number - 1 - len(rows)))
            rows.append(values)
        return rows

    def cell(self, sheet: str, reference: str) -> Any:
        match = re.fullmatch(r"([A-Za-z]{1,3})(\d{1,7})", reference.strip())
        if not match:
            return None
        column, row = column_number(match.group(1)), int(match.group(2))
        for number, values in self.iter_rows(sheet, min_row=row, max_row=row, max_col=column):
            if number == row and column <= len(values):
                return values[column - 1]
        return None


class XlsxReader(_Reader):
    """Fast reader for one workbook, standard library only. Use as a context manager or call ``close()``."""

    def __init__(self, path: Path) -> None:
        self._zip = ZipFile(path)  # BadZipFile / OSError propagate to the caller
        self._shared: list[str] | None = None
        self._styles: tuple[frozenset[int], frozenset[int]] | None = None
        try:
            self._load_structure()
        except _PARSE_ERRORS as exc:
            self._zip.close()
            raise UnsupportedWorkbook(f"{type(exc).__name__}: {exc}") from exc
        except Exception:
            self._zip.close()
            raise

    def close(self) -> None:
        self._zip.close()

    # ------------------------------------------------------------------ structure
    def _xml(self, name: str) -> ET.Element:
        with self._zip.open(name) as stream:
            return ET.parse(stream).getroot()

    def _relationships(self, part: str) -> dict[str, tuple[str, str]]:
        """id -> (type, absolute path inside the zip) for the relationships of ``part``."""
        folder, filename = posixpath.split(part)
        rels_name = posixpath.join(folder, "_rels", filename + ".rels")
        if rels_name not in self._zip.namelist():
            return {}
        result = {}
        for rel in self._xml(rels_name):
            target = rel.get("Target", "")
            absolute = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            result[rel.get("Id", "")] = (rel.get("Type", ""), absolute)
        return result

    def _load_structure(self) -> None:
        workbook_part = "xl/workbook.xml"
        if "_rels/.rels" in self._zip.namelist():
            for rel in self._xml("_rels/.rels"):
                if rel.get("Type", "").endswith("/officeDocument"):
                    workbook_part = rel.get("Target", "").lstrip("/") or workbook_part
        rels = self._relationships(workbook_part)
        root = self._xml(workbook_part)

        self._epoch = _WINDOWS_EPOCH
        self._sheets: dict[str, str] = {}
        for element in root.iter():
            name = _local(element.tag)
            if name == "workbookPr" and element.get("date1904") in ("1", "true"):
                self._epoch = _MAC_EPOCH
            elif name == "sheet":
                kind, target = rels.get(_attribute(element, "id") or "", ("", ""))
                if kind.endswith("/worksheet"):
                    self._sheets[element.get("name", "")] = target
        self._related = {kind.rsplit("/", 1)[-1]: path for kind, path in rels.values()}

    @property
    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    # ------------------------------------------------------------------ shared data
    def _shared_strings(self) -> list[str]:
        if self._shared is None:
            self._shared = []
            part = self._related.get("sharedStrings")
            if part and part in self._zip.namelist():
                with self._zip.open(part) as stream:
                    for _event, element in ET.iterparse(stream):
                        if _local(element.tag) == "si":
                            self._shared.append(_text_of(element).replace("x005F_", ""))
                            element.clear()
        return self._shared

    def _style_flags(self) -> tuple[frozenset[int], frozenset[int]]:
        """Indexes of the cell styles that hold dates / durations."""
        if self._styles is None:
            dates: set[int] = set()
            deltas: set[int] = set()
            part = self._related.get("styles")
            if part and part in self._zip.namelist():
                custom: dict[int, str] = {}
                formats: list[int] = []
                for element in self._xml(part).iter():
                    name = _local(element.tag)
                    if name == "numFmt":
                        custom[int(element.get("numFmtId", 0))] = element.get("formatCode", "")
                    elif name == "cellXfs":
                        formats = [int(xf.get("numFmtId", 0)) for xf in element if _local(xf.tag) == "xf"]
                for index, number_format in enumerate(formats):
                    code = custom.get(number_format, _BUILTIN_DATE_FORMATS.get(number_format))
                    if is_date_format(code):
                        dates.add(index)
                    if is_timedelta_format(code):
                        deltas.add(index)
            self._styles = (frozenset(dates), frozenset(deltas))
        return self._styles

    # ------------------------------------------------------------------ cells
    def _value(self, cell: ET.Element, v_tag: str, is_tag: str) -> Any:
        kind = cell.get("t", "n")
        raw = None
        if kind != "inlineStr":
            node = cell.find(v_tag)
            raw = (node.text if node is not None else None) or None
        if raw is not None:
            if kind == "n":
                value: Any = float(raw) if ("." in raw or "E" in raw or "e" in raw) else int(raw)
                style = int(cell.get("s") or 0)
                if style:
                    dates, deltas = self._style_flags()
                    if style in dates:
                        try:
                            return _from_excel(value, self._epoch, style in deltas)
                        except (OverflowError, ValueError):
                            return "#VALUE!"
                return value
            if kind == "s":
                return self._shared_strings()[int(raw)]
            if kind == "b":
                return bool(int(raw))
            if kind == "d":
                raise UnsupportedWorkbook("ISO date cells are read by openpyxl")
            return raw  # "str" (a formula's text result) and "e" (an error such as #N/A)
        if kind == "inlineStr":
            inline = cell.find(is_tag)
            return _text_of(inline) if inline is not None else None
        return None

    def iter_rows(
        self, sheet: str, *, min_row: int = 1, max_row: int | None = None, max_col: int | None = None
    ) -> Iterator[tuple[int, list[Any]]]:
        try:
            yield from self._iter_rows(sheet, min_row, max_row, max_col)
        except _PARSE_ERRORS as exc:
            raise UnsupportedWorkbook(f"{type(exc).__name__}: {exc}") from exc

    def _iter_rows(
        self, sheet: str, min_row: int, max_row: int | None, max_col: int | None
    ) -> Iterator[tuple[int, list[Any]]]:
        part = self._sheets[sheet]
        namespace: str | None = None
        c_tag = row_tag = v_tag = is_tag = ""
        pending: list[Any] = []
        column = 0
        row_number = 0
        with self._zip.open(part) as stream:
            for _event, element in ET.iterparse(stream):
                tag = element.tag
                if namespace is None:
                    namespace = tag[: tag.index("}") + 1] if tag.startswith("{") else ""
                    c_tag, row_tag, v_tag, is_tag = (namespace + name for name in ("c", "row", "v", "is"))
                if tag == c_tag:
                    reference = element.get("r")
                    column = _column_of(reference) if reference else column + 1
                    if max_col is None or column <= max_col:
                        value = self._value(element, v_tag, is_tag)
                        if value is not None:
                            if len(pending) < column:
                                pending.extend([None] * (column - len(pending)))
                            pending[column - 1] = value
                elif tag == row_tag:
                    row_number = int(element.get("r") or row_number + 1)
                    values, pending, column = pending, [], 0
                    element.clear()
                    if max_row is not None and row_number > max_row:
                        return
                    if row_number >= min_row:
                        yield row_number, values


class OpenpyxlReader(_Reader):
    """The same interface on top of openpyxl: slower, but reads anything openpyxl can."""

    def __init__(self, path: Path) -> None:
        from openpyxl import load_workbook  # imported here: it is slow, and only needed as a fallback

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # openpyxl warns about extensions many tester files use
            self._workbook = load_workbook(str(path), data_only=True, read_only=True)
        self._sheets = {sheet.title: sheet for sheet in self._workbook.worksheets}

    @property
    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    def close(self) -> None:
        self._workbook.close()

    def iter_rows(
        self, sheet: str, *, min_row: int = 1, max_row: int | None = None, max_col: int | None = None
    ) -> Iterator[tuple[int, list[Any]]]:
        worksheet = self._sheets[sheet]
        worksheet.reset_dimensions()  # some tools write a wrong <dimension>, which would end the sheet after one row
        rows = worksheet.iter_rows(min_row=min_row, max_row=max_row, max_col=max_col, values_only=True)
        for number, values in enumerate(rows, start=min_row):
            yield number, list(values)


def read_workbook(path: Path, work: Callable[[_Reader], T]) -> T:
    """Run ``work(reader)`` on the fast reader; if it cannot cope with the file, run it again on openpyxl.

    ``work`` must start from scratch each time it is called. Every other error, including ``PermissionError``
    and ``BadZipFile``, is raised as it is: the caller decides what to tell the person.
    """
    try:
        with XlsxReader(path) as reader:
            return work(reader)
    except UnsupportedWorkbook:
        logger.info("%s was not read by the fast reader; using openpyxl", path.name, exc_info=True)
    with OpenpyxlReader(path) as reader:
        return work(reader)
