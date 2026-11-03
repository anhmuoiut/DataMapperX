"""Workbooks for the tests of "Analyze by Excel File": ratings tables as a person would fill them in."""
from __future__ import annotations

from pathlib import Path

HEADERS = ("Sample ID", "Rating", "Test Item", "Appraiser", "Trial", "Known Standard")


def attribute_rows(samples: int = 4, trials: int = 2, appraisers=("Ann", "Ben"), standard: bool = True) -> list[tuple]:
    """(sample, rating, item, appraiser, trial, standard): every appraiser rates every sample every time as the standard says."""
    rows = []
    for who in appraisers:
        for n in range(1, samples + 1):
            truth = "PASS" if n % 2 else "FAIL"
            for trial in range(1, trials + 1):
                rows.append((f"S{n:03d}", truth, "Visual check", who, trial, truth if standard else None))
    return rows


def write_ratings(path: Path, rows, headers=HEADERS, sheet: str = "Attribute_Data", others: tuple[str, ...] = ()) -> Path:
    """A workbook whose first sheet is ``sheet`` (headers, then ``rows``) followed by empty sheets named ``others``."""
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = sheet
    book.active.append(list(headers))
    for row in rows:
        book.active.append(list(row))
    for name in others:
        book.create_sheet(name)
    book.save(path)
    return path


def store_digits(path: Path, stored: str, exact: str) -> None:
    """Rewrite the number ``stored`` in the first sheet as ``exact``: Excel keeps up to 17 digits, the writer of these tests only 15."""
    import zipfile

    with zipfile.ZipFile(path) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    sheet = "xl/worksheets/sheet1.xml"
    assert f"<v>{stored}</v>".encode() in parts[sheet]
    parts[sheet] = parts[sheet].replace(f"<v>{stored}</v>".encode(), f"<v>{exact}</v>".encode())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in parts.items():
            target.writestr(name, data)


EXPORT_HEADERS = ("Test Item", "Sample ID", "Appraiser", "Trial", "Rating", "Standard")  # the columns of the Observations sheet of the report


def write_rawdata(path: Path, serials: int = 3, readings: int = 2, items=("R1", "R2"), limits=((0, 9), (0, 9)), value=None) -> Path:
    """A RawData.xlsx as DataMapperX writes it: STT, SN and a column for each test item, an empty column, then NAME / MIN / MAX / UNIT
    (``limits`` is a (MIN, MAX) for each item, or None for no limits table). ``value(serial, reading, item)`` is the measurement; None
    leaves the cell empty."""
    from openpyxl import Workbook

    value = value or (lambda n, r, i: 100 + 10 * n + 0.3 * r + 5 * i)
    book = Workbook()
    sheet = book.active
    sheet.title = "Raw Data"
    sheet.append(["STT", "SN", *items, *([None, "NAME", "MIN", "MAX", "UNIT"] if limits else [])])
    line = 0
    for n in range(serials):
        for r in range(readings):
            row = [line + 1, f"VSE{n + 1:03d}", *(value(n, r, i) for i in range(len(items)))]
            if limits and line < len(items):
                row += [None, items[line], *limits[line], "Ohm"]
            sheet.append(row)
            line += 1
    book.save(path)
    return path
