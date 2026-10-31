"""Every study identity is shown in chart axes, including compact report panels."""

from __future__ import annotations

import math

import pytest

from datamapperx.stat_charts import (
    ChartSeries,
    ChartSpec,
    chart_primitives,
    charts_for_result,
    draw_tk_chart,
    reportlab_chart,
)
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
    texts = []

    class Canvas:
        def winfo_width(self):
            return 375

        def winfo_height(self):
            return 218

        def create_text(self, *args, **kwargs):
            texts.append(kwargs)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    draw_tk_chart(Canvas(), charts_for_result(result)[1])
    labels = [item for item in texts if item["text"] in samples]
    assert [item["text"] for item in labels] == samples
    assert all(item["angle"] == 45 and isinstance(item["font"][1], int) for item in labels)


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
