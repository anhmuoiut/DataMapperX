"""Phase 0 regression baseline: the scan order and the RawData.xlsx workbook must stay exactly as they were.

``tests/fixtures/baseline/rawdata_baseline.json`` was generated from the pre-Phase-0 code by ``tests/make_baseline.py``.
It covers serial numbers kept as text, scientific-notation values (kept with their number format), a missing component,
a component name with two spaces, the NAME/MIN/MAX/UNIT table beside the data, styling, widths and the error text.
The folders are laid out so that the path order of the files differs from the serial-number order of the export.
"""
from __future__ import annotations

import json
from pathlib import Path

from .baseline_support import dumps, first_difference, rawdata_signature

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "baseline" / "rawdata_baseline.json").read_text(encoding="utf-8"))["signature"]


def test_scan_order_and_rawdata_workbook_are_unchanged(tmp_path):
    actual = json.loads(dumps(rawdata_signature(tmp_path)))
    difference = first_difference(EXPECTED, actual)
    assert not difference, difference
    assert dumps(actual) == dumps(EXPECTED)  # also tells 1 from 1.0 and keeps key order


def test_baseline_records_the_known_order_difference_between_scan_and_export():
    # The scan keeps serial numbers in the order their first file is met on disk; RawData.xlsx sorts them.
    assert EXPECTED["scan_sn_order"] == ["VSE000125", "VSE000123", "VSE000124"]
    assert [row[1] for row in EXPECTED["export_rows"]] == ["VSE000123", "VSE000123", "VSE000124", "VSE000124", "VSE000125", "VSE000125"]
    assert [cell for cell in EXPECTED["cells"] if cell[0] == "B2"][0][1] == "VSE000123"
    assert [cell for cell in EXPECTED["cells"] if cell[0] == "B2"][0][2] == "s"
