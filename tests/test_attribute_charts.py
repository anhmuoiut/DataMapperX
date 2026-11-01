"""Attribute Agreement (P4): the Assessment Agreement graph, as chart data and as drawn primitives.

The two panels (Within Appraisers, Appraiser vs Standard) are plain ``ChartSpec`` objects drawn by the existing renderer, on screen
and in a PDF. Everything here is headless: the primitives are the coordinates the Tk canvas and ReportLab are given, so the
values the graph shows, and whether anything overlaps or is clipped, can be measured from them.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from datamapperx.stat_charts import (
    AGREEMENT_INTERVAL,
    AGREEMENT_PERCENT,
    AGREEMENT_PLOT_MIN,
    AGREEMENT_TITLES,
    ChartSeries,
    ChartSpec,
    _text_units,
    agreement_axis,
    agreement_chart_note,
    agreement_charts,
    agreement_extra_height,
    chart_primitives,
    charts_for_result,
    draw_tk_charts,
    reportlab_chart,
)
from datamapperx.stat_reports import report_charts
from datamapperx.statistics import AnalysisConfig
from datamapperx.statistics.attribute import agreement_interval
from datamapperx.ui.validation_workspace import ValidationWorkspace

from .test_attribute import ATTRIBUTE, only, rate, reference_rows


def appraisers_study(names, mistakes=(), trials=3, samples=30, standard=True):
    """Every appraiser rates every sample ``trials`` times, as the standard says except for the (name, sample, trial) in ``mistakes``."""
    rows = []
    for name in names:
        for number in range(1, samples + 1):
            truth = "Pass" if number <= samples // 2 else "Fail"
            other = "Fail" if truth == "Pass" else "Pass"
            rows += rate(f"S{number:02d}", [other if (name, number, t) in mistakes else truth for t in range(1, trials + 1)],
                         truth if standard else "", name)
    return rows


def values(spec):
    """(percent, lower, upper) of each appraiser, from the data of a panel."""
    percent = next(s for s in spec.series if s.kind == "scatter").points
    limits = next(s for s in spec.series if s.kind == "interval").points
    return [(p[1], low[1], high[1]) for p, low, high in zip(percent, limits[0::2], limits[1::2], strict=True)]


# ----------------------------------------------------------------------------- the data of the panels
def test_the_reference_study_gives_the_published_point_and_interval_in_both_panels():
    specs = agreement_charts(only(reference_rows(), ATTRIBUTE))
    assert [s.title for s in specs] == list(AGREEMENT_TITLES) and all(s.categories == ("1",) for s in specs)
    for spec in specs:
        (percent, lower, upper), = values(spec)
        assert (percent, round(lower, 2), upper) == (100.0, 90.50, 100.0)  # 30 of 30: 100.00 %, 95 % CI (90.50, 100.00)
        assert [s.label for s in spec.series] == ["Percent", "95% CI"] and spec.x_label == "Appraiser" and spec.y_label == "Percent"
        assert [s.color for s in spec.series] == [AGREEMENT_PERCENT, AGREEMENT_INTERVAL]


@pytest.mark.parametrize("confidence", [0.90, 0.95, 0.99])
def test_the_interval_follows_the_confidence_level_of_the_analysis(confidence):
    result = only(reference_rows(mistakes={(4, 2)}), AnalysisConfig(method="attribute", confidence=confidence))
    for spec in agreement_charts(result):
        assert next(s for s in spec.series if s.kind == "interval").label == f"{round(confidence * 100)}% CI"
        (percent, lower, upper), = values(spec)
        expected = agreement_interval(29, 30, confidence)
        assert (percent, lower, upper) == pytest.approx((100 * 29 / 30, 100 * expected[0], 100 * expected[1]), abs=1e-9)


def test_every_applicable_appraiser_is_shown_in_the_order_of_the_study():
    result = only(appraisers_study(("Ann", "Ben", "Carla"), {("Ben", n, 1) for n in range(1, 6)}), ATTRIBUTE)
    within, against = agreement_charts(result)
    assert within.categories == against.categories == ("Ann", "Ben", "Carla")
    assert [round(p, 2) for p, _, _ in values(within)] == [100.0, 83.33, 100.0] and len(values(against)) == 3
    for _percent, lower, upper in values(within):
        assert lower <= _percent <= upper


@pytest.mark.parametrize("matched,expected_lower,expected_upper", [(0, 0.0, None), (30, None, 100.0)])
def test_the_boundaries_zero_and_one_hundred_percent_are_drawn_inside_the_plot(matched, expected_lower, expected_upper):
    mistakes = {("", n, t) for n in range(1, 31) for t in (1, 2, 3)} if matched == 0 else set()
    result = only(appraisers_study(("",), mistakes), ATTRIBUTE)
    spec = agreement_charts(result)[1]  # against the Standard: 0 of 30 (every trial wrong) or 30 of 30
    (percent, lower, upper), = values(spec)
    assert percent == 100 * matched / 30
    if expected_lower is not None:
        assert lower == expected_lower and 0 < upper < 15 and upper == pytest.approx(100 * (1 - 0.05 ** (1 / 30)))
    else:
        assert upper == expected_upper and lower == pytest.approx(100 * 0.05 ** (1 / 30))
    for kwargs in ({}, {"compact": True, "scale": 1.333}):
        left, top, right, bottom = plot_rect(chart_primitives(spec, 380, 280, **kwargs))
        circles, lines = markers(chart_primitives(spec, 380, 280, **kwargs), (left, top, right, bottom))
        assert len(circles) == 1 and len(lines) == 1  # the marker at the boundary is not cut off by the edge of the plot
        low_end, high_end = agreement_axis(spec)
        assert low_end <= min(lower, percent) and high_end >= max(upper, percent)


def test_a_panel_the_study_cannot_have_is_left_out_and_the_reason_is_given():
    no_standard = only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE)
    assert [s.title for s in agreement_charts(no_standard)] == ["Within Appraisers"] and agreement_chart_note(no_standard) == ""
    one_trial = only(reference_rows(trials=1), ATTRIBUTE)
    assert [s.title for s in agreement_charts(one_trial)] == ["Appraiser vs Standard"]
    neither = only([dataclasses.replace(r, standard="") for r in reference_rows(trials=1)], ATTRIBUTE)
    assert agreement_charts(neither) == [] and "needs two or more trials" in agreement_chart_note(neither)
    broken = only(reference_rows()[:-1], ATTRIBUTE)  # could not be analysed: no chart, and no hint either (the Checks say why)
    assert charts_for_result(broken) == [] and agreement_chart_note(broken) == ""


def test_a_standard_that_cannot_be_used_leaves_its_panel_as_n_a_with_the_reason():
    rows = [dataclasses.replace(r, standard="") if r.sample_id == "S05" else r for r in reference_rows()]
    within, against = agreement_charts(only(rows, ATTRIBUTE))
    assert within.series and against.series == () and against.title == "Appraiser vs Standard"
    assert against.note == "N/A: The Standard is missing for 1 of 30 samples."
    for kwargs in ({}, {"compact": True, "scale": 1.0}):
        texts = [s["text"] for kind, _, s in chart_primitives(against, 380, 260, **kwargs) if kind == "text"]
        assert "N/A: The Standard is missing for 1 of 30 samples." in " ".join(texts)  # said in the middle of the panel, in as many lines as it takes
        assert not any(kind in ("circle",) for kind, *_ in chart_primitives(against, 380, 260, **kwargs))  # nothing is invented
    assert report_charts(only(rows, ATTRIBUTE))[1].note == against.note  # the report keeps the note; the other methods still drop theirs


def test_the_chart_data_classes_are_unchanged_so_that_the_baseline_fixtures_still_apply():
    assert [f.name for f in dataclasses.fields(ChartSpec)] == ["title", "x_label", "y_label", "series", "markers", "categories", "note", "show_y"]
    assert [f.name for f in dataclasses.fields(ChartSeries)] == ["label", "points", "color", "kind", "dash"]


def test_no_chart_of_another_method_is_made_for_ratings():
    for spec in agreement_charts(only(reference_rows(), ATTRIBUTE)):
        assert spec.title not in ("R Chart", "Xbar Chart", "Components of Variation", "Process Capability Histogram")
    assert len(charts_for_result(only(reference_rows(), ATTRIBUTE))) == 2


# ----------------------------------------------------------------------------- the drawing
def plot_rect(primitives):
    axes = [c for kind, c, s in primitives if kind == "line" and s.get("color") == "#748391" and len(c) == 4]
    left, top, _, bottom = axes[0]
    _, _, right, _ = axes[1]
    return left, top, right, bottom


def value_scale(primitives):
    """value -> pixel of the vertical axis, from the labels of its ticks."""
    ticks = []
    for kind, c, s in primitives:
        if kind == "text" and s.get("anchor") == "e" and not s.get("category"):
            try:
                ticks.append((c[1], float(s["text"])))
            except ValueError:
                continue
    (y1, v1), (y2, v2) = ticks[0], ticks[-1]
    return lambda y: v1 + (y - y1) * (v2 - v1) / (y2 - y1)


def markers(primitives, rect):
    left, top, right, bottom = rect
    circles = [c for kind, c, s in primitives if kind == "circle" and s["color"] == AGREEMENT_PERCENT
               and left <= (c[0] + c[2]) / 2 <= right and top <= (c[1] + c[3]) / 2 <= bottom]
    lines = [c for kind, c, s in primitives if kind == "line" and s["color"] == AGREEMENT_INTERVAL and c[0] == c[2]
             and left <= c[0] <= right and top <= min(c[1], c[3]) and max(c[1], c[3]) <= bottom]
    return circles, lines


@pytest.mark.parametrize("kwargs,width", [({}, 340), ({}, 520), ({"compact": True, "scale": 1.0}, 340), ({"compact": True, "scale": 1.667}, 380)])
def test_the_drawn_points_and_limits_are_where_the_values_are(kwargs, width):
    result = only(appraisers_study(("Ann", "Ben", "Carla"), {("Ben", n, 1) for n in range(1, 6)} | {("Carla", n, t) for n in range(1, 20) for t in (1, 2, 3)}), ATTRIBUTE)
    for spec in agreement_charts(result):
        primitives = chart_primitives(spec, width, 260, **kwargs)
        rect, scale = plot_rect(primitives), value_scale(primitives)
        circles, lines = markers(primitives, rect)
        assert len(circles) == len(lines) == 3  # every appraiser, once, inside the plot
        tolerance = 2 * (agreement_axis(spec)[1] - agreement_axis(spec)[0]) / (rect[3] - rect[1])  # two pixels
        for (percent, lower, upper), circle, line in zip(values(spec), sorted(circles), sorted(lines), strict=True):
            assert scale((circle[1] + circle[3]) / 2) == pytest.approx(percent, abs=tolerance)
            assert sorted(scale(y) for y in (line[1], line[3])) == pytest.approx([lower, upper], abs=tolerance)


def text_boxes(primitives, scale):
    """Where each horizontal text is, estimated as the layout does (``_text_units``), with the height of its glyphs."""
    boxes = []
    for kind, c, s in primitives:
        if kind != "text" or s.get("angle"):
            continue
        height, width = s["size"] * scale * 0.9, _text_units(s["text"]) * s["size"] * scale
        x = {"w": c[0], "e": c[0] - width, "center": c[0] - width / 2}[s.get("anchor", "w")]
        boxes.append((s["text"], (x, c[1] - height / 2, x + width, c[1] + height / 2)))
    return boxes


def overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0.5 and min(a[3], b[3]) - max(a[1], b[1]) > 0.5


@pytest.mark.parametrize("names", [("1",), ("Ann", "Ben"), ("Ann", "Ben", "Carla"), tuple(f"Appraiser {n}" for n in range(1, 7)),
                                   ("Technician North", "Technician South", "Technician East")])
@pytest.mark.parametrize("kwargs,scale", [({}, 1.0), ({"compact": True, "scale": 1.0}, 1.0), ({"compact": True, "scale": 1.333}, 1.333),
                                          ({"compact": True, "scale": 1.667}, 1.667)])
@pytest.mark.parametrize("width,height", [(340, 230), (380, 260), (520, 300)])
def test_labels_legends_and_limits_never_overlap_or_leave_the_chart(names, kwargs, scale, width, height):
    result = only(appraisers_study(names, {(names[-1], n, 1) for n in range(1, 8)}), ATTRIBUTE)
    for spec in agreement_charts(result):
        primitives = chart_primitives(spec, width, height, **kwargs)
        factor = scale if kwargs else 1.0
        boxes = text_boxes(primitives, factor)
        for number, (first_text, first) in enumerate(boxes):
            assert first[0] >= -1 and first[2] <= width + 1 and first[1] >= -1 and first[3] <= height + 1, (spec.title, first_text, first)
            for second_text, second in boxes[number + 1:]:
                assert not overlap(first, second), (spec.title, first_text, second_text)
        left, top, right, bottom = plot_rect(primitives)
        entries = [box for text, box in boxes if text == "95% CI"]
        assert len(entries) == 1 and (entries[0][0] > right or entries[0][3] < top)  # the legend is beside the plot or above it, never in it
        circles, lines = markers(primitives, (left, top, right, bottom))
        assert len(circles) == len(lines) == len(spec.categories)
        for _, box in boxes:  # no text sits on a point or a limit
            for line in lines:
                assert not (box[0] < line[0] < box[2] and box[1] < max(line[1], line[3]) and box[3] > min(line[1], line[3])
                            and box[1] > top and box[3] < bottom), "a label crosses an interval"


def test_the_legend_has_a_symbol_for_each_series_and_both_theme_independent_colours_are_kept():
    spec = agreement_charts(only(reference_rows(), ATTRIBUTE))[0]
    for kwargs in ({}, {"compact": True, "scale": 1.0}):
        primitives = chart_primitives(spec, 380, 260, **kwargs)
        rect = plot_rect(primitives)
        outside = [c for kind, c, s in primitives if kind in ("circle", "line") and s["color"] in (AGREEMENT_PERCENT, AGREEMENT_INTERVAL)
                   and not (rect[0] <= (c[0] + c[2]) / 2 <= rect[2] and rect[1] <= (c[1] + c[3]) / 2 <= rect[3])]
        colours = {s["color"] for kind, c, s in primitives if kind in ("circle", "line") and c in outside}
        assert colours == {AGREEMENT_PERCENT, AGREEMENT_INTERVAL}  # a circle and an X in the legend


def test_the_charts_are_drawn_by_the_pdf_renderer_with_the_same_primitives():
    pytest.importorskip("reportlab")
    from reportlab.graphics.shapes import Drawing

    for spec in agreement_charts(only(appraisers_study(("Ann", "Ben")), ATTRIBUTE)):
        drawing = reportlab_chart(spec, 360, 260)
        assert isinstance(drawing, Drawing) and len(drawing.contents) > 10


class Canvas:
    """A canvas that records what is drawn on it."""

    def __init__(self, width=900, height=400):
        self.size, self.texts, self.shapes = (width, height), [], []

    def winfo_width(self):
        return self.size[0]

    def winfo_height(self):
        return self.size[1]

    def winfo_fpixels(self, _unit):
        return 1.333

    def delete(self, *_):
        self.texts, self.shapes = [], []

    def configure(self, **_):
        pass

    def create_text(self, x, y, **kwargs):
        self.texts.append((x, y, kwargs))

    def create_line(self, *args, **kwargs):
        self.shapes.append(("line", args))

    def create_oval(self, *args, **kwargs):
        self.shapes.append(("circle", args))

    def create_rectangle(self, *args, **kwargs):
        self.shapes.append(("rect", args))


LONG_NAMES = ("Maria Gonzalez-Hernandez", "Ng", "Operator 03 (night shift)", "Bartholomew Featherstonehaugh", "Li", "Appraiser-0006",
              "Xiaoming Zhang-Wei", "Jo", "Fatima Al-Mansouri", "Operator 10", "Zdzislaw Przybylski", "A")
SMALLEST_CELL = (352 - 8, 210 - 6)  # the smallest panel the window draws: MIN_CELL_WIDTH and min_height, less their margins


def plot_height(spec, width, height, scale):
    """The height of the plot itself (its vertical axis), from the drawn primitives."""
    _, top, _, bottom = next(coords for kind, coords, _ in chart_primitives(spec, width, height, None, True, scale) if kind == "line")
    return bottom - top


@pytest.mark.parametrize("scale", [1.0, 1.333, 1.667])
def test_many_long_appraiser_names_make_a_panel_taller_instead_of_squeezing_its_plot_away(scale):
    spec = agreement_charts(only(appraisers_study(LONG_NAMES), ATTRIBUTE))[0]
    assert plot_height(spec, *SMALLEST_CELL, scale) < AGREEMENT_PLOT_MIN / 2  # in the smallest panel the rotated names leave next to no plot
    extra = agreement_extra_height(spec, *SMALLEST_CELL, scale)
    assert extra > 0
    assert plot_height(spec, SMALLEST_CELL[0], SMALLEST_CELL[1] + extra, scale) == pytest.approx(AGREEMENT_PLOT_MIN)
    assert agreement_extra_height(spec, SMALLEST_CELL[0], SMALLEST_CELL[1] + extra, scale) == pytest.approx(0)  # and no more than that


@pytest.mark.parametrize("scale", [1.0, 1.333, 1.667])
def test_a_few_short_names_and_every_other_panel_keep_the_height_they_are_given(scale):
    for names in (("Ann",), ("Ann", "Ben", "Carla"), ("Nguyen Van An", "Tran Thi Binh", "Operator 03")):
        for spec in agreement_charts(only(appraisers_study(names), ATTRIBUTE)):
            assert agreement_extra_height(spec, *SMALLEST_CELL, scale) == 0.0, names
    na = ChartSpec("Appraiser vs Standard", "Appraiser", "Percent", (), note="N/A: the Standard is missing")
    other = ChartSpec("Components of Variation", "x", "Percent", (ChartSeries("a", ((1, 1.0), (2, 2.0)), "#0068A8", "line"),), categories=("A", "B"))
    assert agreement_extra_height(na, *SMALLEST_CELL, scale) == 0.0 and agreement_extra_height(other, *SMALLEST_CELL, scale) == 0.0


def test_the_window_scrolls_a_tall_panel_and_keeps_the_percent_scale_readable():
    class Scrolling(Canvas):
        scrollregion = None

        def configure(self, **kwargs):
            self.scrollregion = kwargs.get("scrollregion", self.scrollregion)

    result = only(appraisers_study(LONG_NAMES), ATTRIBUTE)
    canvas = Scrolling(width=360, height=300)  # a small window: one column, each panel 210 pixels high at least
    draw_tk_charts(canvas, agreement_charts(result), columns=2, compact=True)
    assert canvas.scrollregion[3] > 2 * 210  # taller than two minimum panels: it scrolls
    for panel in (0, 1):
        ticks = sorted(y for x, y, text in canvas.texts if text["text"].isdigit() and text["anchor"] == "e" and text["angle"] == 0
                       and panel * canvas.scrollregion[3] / 2 <= y < (panel + 1) * canvas.scrollregion[3] / 2)
        assert len(ticks) >= 4 and min(b - a for a, b in zip(ticks, ticks[1:], strict=False)) >= 12  # the tick labels do not touch
    few = Scrolling(width=360, height=300)
    draw_tk_charts(few, agreement_charts(only(appraisers_study(("Ann", "Ben")), ATTRIBUTE)), columns=2, compact=True)
    assert few.scrollregion[3] == 2 * max(210, 300 / 2)  # nothing changes for the usual study


def test_the_window_draws_both_panels_side_by_side_and_says_why_when_there_is_none():
    result = only(reference_rows(), ATTRIBUTE)
    canvas = Canvas()
    draw_tk_charts(canvas, agreement_charts(result), columns=2, compact=True)
    titles = {text["text"]: x for x, _, text in canvas.texts if text["text"] in AGREEMENT_TITLES}
    assert set(titles) == set(AGREEMENT_TITLES) and titles["Appraiser vs Standard"] > canvas.size[0] / 2  # in two columns
    narrow = Canvas(width=500)
    draw_tk_charts(narrow, agreement_charts(result), columns=2, compact=True)
    assert max(x for x, _, text in narrow.texts if text["text"] in AGREEMENT_TITLES) < 150  # too narrow for two: one column

    neither = only([dataclasses.replace(r, standard="") for r in reference_rows(trials=1)], ATTRIBUTE)
    stub = SimpleNamespace(chart_canvas=Canvas(), _charts=[], chart_scale_var=SimpleNamespace(get=lambda: "auto"), _scaled=False,
                           palette=SimpleNamespace(muted="#526174"), selected_result=lambda: neither)
    ValidationWorkspace._draw_chart(stub)
    assert [kwargs["text"] for _, _, kwargs in stub.chart_canvas.texts] == [agreement_chart_note(neither)]
    stub.selected_result = lambda: result  # an item that has panels: no hint
    stub._charts = agreement_charts(result)
    stub.chart_canvas = Canvas()
    ValidationWorkspace._draw_chart(stub)
    assert "No chart applies" not in " ".join(kwargs["text"] for _, _, kwargs in stub.chart_canvas.texts)
