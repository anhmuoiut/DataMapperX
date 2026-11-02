"""The Excel reports are opened by real Microsoft Excel, which refuses a whole workbook for chart XML that openpyxl lets through.

One rule that was broken once: a line in a chart (``a:ln``) may carry a single fill (none, solid, gradient or pattern). A marker-only
series that was given "no fill" and a solid fill made Excel say it could not open the Gage R&R workbook at all.
"""
from __future__ import annotations

import zipfile
from xml.etree import ElementTree

import pytest

from datamapperx.stat_reports import export_statistical_report

from .test_attribute import only, reference_rows
from .test_attribute_reports import CONTEXT as ATTRIBUTE_CONTEXT
from .test_stat_reports import INFO, capability, crossed_grr, grr

DRAWINGML = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
FILLS = {DRAWINGML + name for name in ("noFill", "solidFill", "gradFill", "pattFill")}


def lines_with_several_fills(path) -> list[str]:
    found = []
    with zipfile.ZipFile(path) as workbook:
        for name in workbook.namelist():
            if not name.startswith("xl/charts/chart"):
                continue
            for line in ElementTree.fromstring(workbook.read(name)).iter(DRAWINGML + "ln"):
                fills = [child.tag.removeprefix(DRAWINGML) for child in line if child.tag in FILLS]
                if len(fills) > 1:
                    found.append(f"{name}: {fills}")
    return found


REPORTS = {
    "capability": (lambda: capability(), INFO),
    "gage r&r": (lambda: grr(), INFO),
    "crossed gage r&r": (lambda: crossed_grr(), INFO),
    "attribute agreement": (lambda: only(reference_rows()), ATTRIBUTE_CONTEXT),
}


@pytest.mark.parametrize("name", REPORTS)
def test_no_line_in_a_chart_of_the_excel_report_has_two_fills(tmp_path, name):
    make, context = REPORTS[name]
    path = export_statistical_report(tmp_path / "report.xlsx", [make()], context=context)
    with zipfile.ZipFile(path) as workbook:
        assert any(part.startswith("xl/charts/chart") for part in workbook.namelist()), "the report has no chart to check"
    assert lines_with_several_fills(path) == []


def test_the_check_notices_a_line_that_is_both_unfilled_and_filled(tmp_path):
    broken = tmp_path / "broken.xlsx"
    chart = ('<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
             'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:ln><a:noFill/><a:solidFill/></a:ln></c:chartSpace>')
    with zipfile.ZipFile(broken, "w") as workbook:
        workbook.writestr("xl/charts/chart1.xml", chart)
    assert lines_with_several_fills(broken) == ["xl/charts/chart1.xml: ['noFill', 'solidFill']"]
