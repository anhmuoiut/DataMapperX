"""Every study identity is shown in chart axes, including compact report panels."""

from __future__ import annotations

import math
import random

import pytest

from datamapperx.stat_charts import (
    MIN_CELL_WIDTH,
    ChartSeries,
    ChartSpec,
    _bin_width,
    _histogram_range,
    _text_units,
    chart_primitives,
    charts_for_result,
    reportlab_chart,
    short_labels,
)
from datamapperx.stat_reports import report_charts
from datamapperx.statistics import AnalysisConfig, Observation, analyze


def study(count):
    samples = [f"VSEC0020{index:07d}" for index in range(count)]
    rows = [Observation("Fixture voltage", sample, 5 + index * .03 + trial * .001, 0, 20,
                        trial=str(trial), source=f"{sample}_{trial}.log")
            for index, sample in enumerate(samples) for trial in range(3)]
    return samples, analyze(rows, AnalysisConfig(method="grr"))[0]


@pytest.mark.parametrize("count", [10, 30])
@pytest.mark.parametrize("width,height", [(375, 218), (650, 280)])
def test_every_sample_label_is_emitted_in_full_and_in_study_order(count, width, height):
    samples, result = study(count)
    for chart in charts_for_result(result)[1:]:
        primitives = chart_primitives(chart, width, height)
        labels = [(coords, style) for kind, coords, style in primitives if kind == "text" and style.get("category")]
        assert [style["text"] for _, style in labels] == samples
        assert all(style["angle"] == 45 and style["anchor"] == "e" for _, style in labels)
        assert all("…" not in style["text"] for _, style in labels)
        assert all(math.isfinite(value) for _, coords, _ in primitives for value in coords)
        assert all(0 <= coords[0] <= width and 0 <= coords[1] <= height for coords, _ in labels)


def test_component_labels_also_remain_complete():
    categories = ("Gage R&R", "Repeatability", "Reproducibility", "Part-to-Part")
    chart = ChartSpec("Components of Variation", "Source", "Percent", (
        ChartSeries("%Study Var", tuple((i + 1, 25.0) for i in range(4)), kind="bar"),
    ), categories=categories)
    labels = [style["text"] for kind, _, style in chart_primitives(chart, 375, 218)
              if kind == "text" and style.get("category")]
    assert labels == list(categories)


def test_tk_renderer_applies_rotation_to_all_sample_labels():
    samples, result = study(10)
    primitives = chart_primitives(charts_for_result(result)[1], 375, 218)
    labels = [style for kind, _coords, style in primitives if kind == "text" and style["text"] in samples]
    assert [item["text"] for item in labels] == samples
    assert all(item["angle"] == 45 for item in labels)


@pytest.mark.parametrize("count", [10, 30])
def test_compact_pdf_chart_contains_every_serial_number_as_rotated_text(tmp_path, count):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    from reportlab.graphics import renderPDF

    samples, result = study(count)
    drawing = reportlab_chart(charts_for_result(result)[1], 375, 218)
    path = tmp_path / "serial-axis.pdf"
    renderPDF.drawToFile(drawing, str(path))
    reader = pypdf.PdfReader(path)
    text = reader.pages[0].extract_text()
    assert all(sample in text for sample in samples)
    assert len(reader.pages) == 1


# ----------------------------------------------------------------------------- the horizontal scale of a capability histogram
BAR, OVERALL, WITHIN = "#9DC4E8", "#C0392B", "#263746"


def histogram(low, high, mean=50.0, spread=0.05):
    rng = random.Random(3)
    rows = [Observation("C", f"S{i}", rng.gauss(mean, spread), low, high) for i in range(40)]
    return charts_for_result(analyze(rows, AnalysisConfig(method="capability"))[0])[0]


def labels(primitives):
    return [style["text"] for kind, _, style in primitives if kind == "text"]


def axes(primitives):
    left, _, _, bottom = next(c for kind, c, s in primitives if kind == "line" and s.get("color") == "#748391")
    _, _, right, _ = next(c for kind, c, s in primitives if kind == "line" and s.get("color") == "#748391" and c[1] == c[3])
    return left, right, bottom


def test_auto_scale_keeps_to_the_data_and_says_which_limit_is_off_scale():
    spec = histogram(40.0, 60.0)  # limits 200 standard deviations away
    auto, full = (chart_primitives(spec, 650, 280, scale) for scale in ("auto", "full"))
    assert "← LSL off scale" in labels(auto) and "USL off scale →" in labels(auto) and "LSL" not in labels(auto)
    assert not any(s.get("color") == "#BD3434" for kind, _, s in auto if kind == "line")  # no limit line drawn at the edge
    assert "LSL" in labels(full) and "USL" in labels(full) and not any("off scale" in text for text in labels(full))
    assert "LSL (off scale)" in labels(chart_primitives(spec, 650, 280))  # the reports are drawn as before


def test_a_limit_near_the_data_is_drawn_in_both_scales():
    spec = histogram(49.8, 50.2)
    for scale in ("auto", "full"):
        shown = labels(chart_primitives(spec, 650, 280, scale))
        assert "LSL" in shown and "USL" in shown and not any("off scale" in text for text in shown)
    assert _histogram_range(spec, "auto") == _histogram_range(spec, "full")


def test_both_scales_draw_the_same_bins_at_the_same_places():
    spec = histogram(40.0, 60.0)
    bars = next(s for s in spec.series if s.kind == "bar")
    bin_width = _bin_width(spec)
    spans = {}
    for scale in ("auto", "full"):
        primitives = chart_primitives(spec, 650, 280, scale)
        left, right, _ = axes(primitives)
        xmin, xmax = _histogram_range(spec, scale)
        rects = [c for kind, c, s in primitives if kind == "rect" and s["color"] == BAR]
        assert len(rects) == len(bars.points)
        centres = [xmin + ((c[0] + c[2]) / 2 - left) / (right - left) * (xmax - xmin) for c in rects]
        assert centres == pytest.approx([x for x, _ in bars.points], abs=bin_width * 0.02)  # where the measurements are
        spans[scale] = (xmax - xmin, right - left)
        bin_px = bin_width / (xmax - xmin) * (right - left)
        assert abs((rects[-1][2] - rects[0][0]) - len(rects) * bin_px) <= 1.0 + 1e-9  # the bars cover what the bins cover, to a pixel
    assert spans["full"][0] > 50 * spans["auto"][0]  # the same bins on a scale that holds the limits: narrow bars, not stretched ones


def test_a_missing_or_single_limit_is_handled_in_both_scales():
    one = histogram(None, 50.2)
    for scale in ("auto", "full"):
        shown = labels(chart_primitives(one, 650, 280, scale))
        assert "USL" in shown and "LSL" not in shown and not any("LSL" in text for text in shown)
    none = histogram(None, None)
    assert _histogram_range(none, "auto") == _histogram_range(none, "full")
    far = histogram(None, 90.0)
    assert "USL off scale →" in labels(chart_primitives(far, 650, 280, "auto"))
    assert not any("off scale" in text for text in labels(chart_primitives(far, 650, 280, "full")))


def test_the_legend_is_a_row_under_the_title_and_the_curves_stay_distinguishable():
    spec = histogram(49.8, 50.2)
    for width in (375, 650):
        primitives = chart_primitives(spec, width, 260, "auto")
        legend = [(c, s) for kind, c, s in primitives if kind == "text" and s["text"] in ("Overall", "Within")]
        assert [s["text"] for _, s in legend] == ["Overall", "Within"] and len({c[1] for c, _ in legend}) == 1
        assert all(0 <= c[0] <= width for c, _ in legend)
        assert axes(primitives)[1] > width - 25  # no room is kept on the right for it
    lines = {s["color"]: s.get("dash", False) for kind, c, s in primitives if kind == "line" and len(c) > 4}
    assert lines[OVERALL] is False and lines[WITHIN] is True  # a solid and a dashed curve, in two colours


# ----------------------------------------------------------------------------- charts on screen: spacing and short labels
def extent(coords, style, scale):
    """Where the (unrotated) text of a primitive reaches horizontally, estimated as the layout does."""
    x, width = coords[0], _text_units(style["text"]) * style["size"] * scale
    return {"w": (x, x + width), "e": (x - width, x), "center": (x - width / 2, x + width / 2)}[style.get("anchor", "w")]


@pytest.mark.parametrize("count", [10, 30])
@pytest.mark.parametrize("width,height", [(340, 210), (375, 218), (650, 280)])
@pytest.mark.parametrize("scale", [1.0, 1.333, 1.667])
def test_nothing_is_clipped_or_overlaps_on_screen(count, width, height, scale):
    samples, result = study(count)
    for chart in report_charts(result, titled=True):  # the charts as the window shows them
        primitives = chart_primitives(chart, width, height, compact=True, scale=scale)
        texts = [(c, s) for kind, c, s in primitives if kind == "text"]
        for coords, style in texts:
            assert all(math.isfinite(v) for v in coords) and 0 <= coords[1] <= height, style["text"]
            if not style.get("angle"):
                low, high = extent(coords, style, scale)
                assert low >= -1 and high <= width + 1, (chart.title, style["text"], low, high, width)  # legend, limits, titles: all inside
        axis = next(c for kind, c, s in primitives if kind == "line" and s.get("color") == "#748391" and c[1] == c[3])
        title = next(c for c, s in texts if s["text"] == chart.x_label)
        labels = [(c, s) for c, s in texts if s.get("category")]
        for coords, style in labels:  # the labels end above the title of the axis
            em = style["size"] * scale
            reach = coords[1] + (_text_units(style["text"]) * em + em) * math.sqrt(.5) if style["angle"] else coords[1] + em / 2
            assert reach <= title[1] - em / 2 + 1 and coords[1] >= axis[1], (chart.title, style["text"])
        legend = [c[1] for c, s in texts if s["text"] in {x.label for x in chart.series}]
        assert len(set(legend)) <= 2  # one row, or two when the width is short


def test_a_long_sample_identity_is_shortened_on_screen_but_never_in_the_data_or_the_report():
    samples, result = study(10)
    chart = charts_for_result(result)[1]
    assert chart.categories == tuple(samples)  # what the chart is made of does not change
    shown = [style["text"] for kind, _, style in chart_primitives(chart, 650, 280, compact=True) if kind == "text" and style.get("category")]
    assert shown == [f"…{sample[-4:]}" for sample in samples] and len(set(shown)) == len(samples)
    full = [style["text"] for kind, _, style in chart_primitives(chart, 650, 280) if kind == "text" and style.get("category")]
    assert full == samples  # the report keeps them in full


def test_short_labels_keep_what_tells_the_labels_apart():
    assert short_labels(["1", "2", "10"]) == ["1", "2", "10"]  # short identities stay as they are
    assert short_labels(["20240512-SN00000001", "20240512-SN00000002"]) == ["…0001", "…0002"]
    assert short_labels(["LOT2024A-001", "LOT2024A-002", "LOT2024B-001"]) == ["…A-001", "…A-002", "…B-001"]  # the tail grows until they differ
    assert short_labels(["X-VERYLONGNAME", "X-VERYLONGNAME"]) == ["X-VERYLONGNAME", "X-VERYLONGNAME"]
    assert short_labels(["A / VSEC0020000001", "B / VSEC0020000001", "A / VSEC0020000002"]) == ["A / …0001", "B / …0001", "A / …0002"]
    mixed = short_labels(["7", "VSEC0020000001", "VSEC0020000002"])
    assert mixed == ["7", "…0001", "…0002"]


def test_the_names_of_the_sources_are_never_shortened():
    samples, result = study(10)
    chart = charts_for_result(result)[0]
    shown = [style["text"] for kind, _, style in chart_primitives(chart, 340, 210, compact=True, scale=1.333)
             if kind == "text" and style.get("category")]
    assert shown == list(chart.categories) and all("…" not in text for text in shown)


def test_charts_leave_a_column_only_when_each_has_room_on_screen():
    samples, result = study(10)
    specs = charts_for_result(result)

    def title_positions(width):
        columns = max(1, min(2, int(width // MIN_CELL_WIDTH)))  # what the chart panel of the window does
        cell = width / columns
        found = {}
        for index, spec in enumerate(specs):
            x0 = (index % columns) * cell + 4
            for kind, coords, style in chart_primitives(spec, cell - 8, 200, None, True, 1.333):
                if kind == "text" and style["text"] == spec.title:
                    found[spec.title] = x0 + coords[0]
        return [found[spec.title] for spec in specs]

    narrow, wide = title_positions(500), title_positions(900)
    assert max(narrow) < 150  # one column: every title at the left
    assert max(wide) > 450  # two: the second chart of a row starts at the middle
