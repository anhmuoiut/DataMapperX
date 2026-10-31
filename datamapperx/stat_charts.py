"""Shared chart data and vector renderers for statistical preview and reports.

All statistical estimates come from ``AnalysisResult``; rendering never changes data.
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChartSeries:
    label: str
    points: tuple[tuple[float, float], ...]
    color: str = "#0068A8"
    kind: str = "line"  # line, marked (line with point markers), scatter, bar
    dash: bool = False


@dataclass(frozen=True)
class ChartSpec:
    title: str
    x_label: str
    y_label: str
    series: tuple[ChartSeries, ...]
    markers: tuple[tuple[str, float], ...] = ()  # vertical specification markers
    categories: tuple[str, ...] = ()
    note: str = ""
    show_y: bool = True  # Minitab's capability histogram has no vertical scale


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _normal(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi))


def capability_chart(result) -> ChartSpec:
    values = [v for observation in result.observations if (v := _number(observation.value)) is not None]
    if not values:
        return ChartSpec("Process Capability Histogram", "Measurement", "Density", (), note="No valid measurements.")
    low, high = min(values), max(values)
    span = high - low
    if not math.isfinite(span):
        return ChartSpec("Process Capability Histogram", "Measurement", "Density", (), note="Range cannot be plotted.")
    if span == 0:
        span = max(abs(low) * 0.01, 0.001)
        low, high = low - span / 2, high + span / 2
    bins = min(30, max(5, math.ceil(math.sqrt(len(values)))))
    width = (high - low) / bins
    if width == 0:
        return ChartSpec("Process Capability Histogram", "Measurement", "Density", (), note="Range is below plotting precision.")
    counts = [0] * bins
    for value in values:
        counts[min(bins - 1, max(0, int((value - low) / width)))] += 1
    series = [ChartSeries("Measurements", tuple((low + (i + 0.5) * width, c / (len(values) * width))
                                                for i, c in enumerate(counts)), "#9DC4E8", "bar")]
    mean = _number(result.mean)
    if mean is not None:
        for key, label, color, dash in (("sigma_overall", "Overall", "#C0392B", False), ("sigma_within", "Within", "#263746", True)):
            sigma = _number(result.metrics.get(key))
            if sigma is not None and sigma > 0:
                curve_low = min(low, mean - 3.5 * sigma)
                curve_high = max(high, mean + 3.5 * sigma)
                if math.isfinite(curve_low) and math.isfinite(curve_high):
                    points = tuple((x, _normal(x, mean, sigma)) for i in range(101)
                                   if math.isfinite(x := curve_low + (curve_high - curve_low) * i / 100))
                    series.append(ChartSeries(label, points, color, dash=dash))
    markers = tuple((label, value) for label, raw in (("LSL", result.lsl), ("USL", result.usl))
                    if (value := _number(raw)) is not None)
    return ChartSpec("Process Capability Histogram", f"Measurement ({result.unit})" if result.unit else "Measurement",
                     "Density", tuple(series), markers, note="Normal curves are model estimates; stability and normality must be assessed.",
                     show_y=False)


OPERATOR_COLORS = ("#0068A8", "#B45C00", "#63946A", "#7A4FA3", "#B34545", "#4F8A8B")


def grr_charts(result) -> list[ChartSpec]:
    metrics = result.metrics
    crossed = bool(result.details.get("crossed"))
    total = _number(metrics.get("variance_total"))
    total_sigma = _number(metrics.get("sigma_total"))
    tolerance = result.usl - result.lsl if result.usl is not None and result.lsl is not None else None
    sources = [("Gage R&R", "variance_grr", "sigma_grr"), ("Repeat", "variance_repeatability", "sigma_repeatability")]
    if crossed:
        sources.append(("Reprod", "variance_reproducibility", "sigma_reproducibility"))
    sources.append(("Part-to-Part", "variance_part", "sigma_part"))
    component_series = []
    for offset, label, color in ((-.24, "%Contribution", "#6E9BD1"), (0, "%Study Var", "#D9534F"),
                                 (.24, "%Tolerance", "#F0C419")):
        points = []
        for i, (_, variance_key, sigma_key) in enumerate(sources):
            variance, sigma = _number(metrics.get(variance_key)), _number(metrics.get(sigma_key))
            if label == "%Contribution":
                value = 100 * variance / total if total and variance is not None else None
            elif label == "%Study Var":
                value = 100 * sigma / total_sigma if total_sigma and sigma is not None else None
            else:  # %Tolerance
                value = 100 * result.config.study_factor * sigma / tolerance if tolerance and tolerance > 0 and sigma is not None else None
            if value is not None and math.isfinite(value):
                points.append((i + 1 + offset, value))
        component_series.append(ChartSeries(label, tuple(points), color, "bar"))
    component_chart = ChartSpec("Components of Variation", "Source", "Percent", tuple(component_series),
                               categories=tuple(name for name, _, _ in sources),
                               note=("Gage R&R = repeatability + reproducibility (operator and Sample x Operator)." if crossed else
                                     "Gage R&R equals repeatability in this one-way model; reproducibility is not estimated."))
    parts = result.details.get("part_summaries", ())
    # A one-way part is one point; a crossed study has one point per Sample ID and Operator cell.
    categories = tuple(f"{part['operator']} / {part['sample_id']}" if part.get("operator") else str(part["sample_id"]) for part in parts)
    ranges = tuple((i + 1, value) for i, part in enumerate(parts) if (value := _number(part.get("range"))) is not None)
    means = tuple((i + 1, value) for i, part in enumerate(parts) if (value := _number(part.get("mean"))) is not None)
    count = max(1, len(parts))

    def controls(name, values, key):
        plotted = [ChartSeries("Observed", values)]
        for limit, color in (("lcl", "#B34545"), ("center", "#63946A"), ("ucl", "#B34545")):
            value = _number(result.details.get(key, {}).get(limit))
            if value is not None:
                plotted.append(ChartSeries(limit.upper(), ((1, value), (count, value)), color))
        return ChartSpec(name, "Sample ID", f"Measurement ({result.unit})" if result.unit else "Measurement",
                         tuple(plotted), categories=categories)

    samples = tuple(dict.fromkeys(str(part["sample_id"]) for part in parts))
    sample_index = {name: i + 1 for i, name in enumerate(samples)}
    by_part = tuple((sample_index[str(part["sample_id"])], value) for part in parts for raw in part.get("values", ())
                    if (value := _number(raw)) is not None)
    cell_means: dict[str, list[float]] = {name: [] for name in samples}
    for part in parts:
        if (value := _number(part.get("mean"))) is not None:
            cell_means[str(part["sample_id"])].append(value)
    sample_means = tuple((sample_index[name], math.fsum(group) / len(group)) for name, group in cell_means.items() if group)
    charts = [component_chart, controls("R Chart", ranges, "r_limits"), controls("Xbar Chart", means, "xbar_limits"),
              ChartSpec("Measurement by Sample ID", "Sample ID", "Measurement", (
                  ChartSeries("Measurements", by_part, "#0068A8", "scatter"), ChartSeries("Sample means", sample_means, "#B45C00"),
              ), categories=samples)]
    if crossed:
        operators = tuple(dict.fromkeys(str(part["operator"]) for part in parts))
        operator_index = {name: i + 1 for i, name in enumerate(operators)}
        by_operator = tuple((operator_index[str(part["operator"])], value) for part in parts for raw in part.get("values", ())
                            if (value := _number(raw)) is not None)
        operator_means = []
        for name in operators:
            group = [value for part in parts if str(part["operator"]) == name and (value := _number(part.get("mean"))) is not None]
            if group:
                operator_means.append((operator_index[name], math.fsum(group) / len(group)))
        interaction = tuple(
            ChartSeries(name, tuple((sample_index[str(part["sample_id"])], value) for part in parts
                                    if str(part["operator"]) == name and (value := _number(part.get("mean"))) is not None),
                        OPERATOR_COLORS[i % len(OPERATOR_COLORS)], "marked")
            for i, name in enumerate(operators))
        unit = f"Measurement ({result.unit})" if result.unit else "Measurement"
        charts.extend([
            ChartSpec("Measurement by Operator", "Operator", unit, (
                ChartSeries("Measurements", by_operator, "#0068A8", "scatter"),
                ChartSeries("Operator means", tuple(operator_means), "#B45C00", "marked")), categories=operators),
            ChartSpec("Sample ID x Operator Interaction", "Sample ID", f"Mean {unit}", interaction, categories=samples,
                      note="Roughly parallel lines mean no operator-by-sample interaction; crossing lines suggest one."),
        ])
    return charts


def charts_for_result(result) -> list[ChartSpec]:
    if not result.valid:
        note = "Analysis unavailable: " + "; ".join(i.message for i in result.issues if i.severity == "error")
        titles = ("Process Capability Histogram",) if result.method == "capability" else (
            "Components of Variation", "R Chart", "Xbar Chart", "Measurement by Sample ID")
        return [ChartSpec(title, "", "", (), note=note) for title in titles]
    return [capability_chart(result)] if result.method == "capability" else grr_charts(result)


def _bounds(spec: ChartSpec):
    points = [point for series in spec.series for point in series.points
              if all(math.isfinite(value) for value in point)]
    if not points:
        return 0.0, 1.0, 0.0, 1.0
    xs, ys = zip(*points, strict=True)
    xmin, xmax = min(xs), max(xs)
    # Very distant limits are annotated in the legend, without crushing the histogram.
    dx = xmax - xmin
    if spec.markers:
        near = [v for _, v in spec.markers if xmin - 2 * dx <= v <= xmax + 2 * dx]
        xmin, xmax = min([xmin, *near]), max([xmax, *near])
    ymin, ymax = min(ys), max(ys)
    bars = any(series.kind == "bar" for series in spec.series)
    non_negative = bars or ymin >= 0
    if bars:
        ymin = min(0, ymin)
    dx, dy = xmax - xmin, ymax - ymin
    if dx == 0:
        dx = max(abs(xmin) * 0.01, 0.001)
    if dy == 0:
        dy = max(abs(ymin) * 0.01, 0.001)
    low = ymin - 0.06 * dy
    return xmin - 0.06 * dx, xmax + 0.06 * dx, (max(0.0, low) if non_negative else low), ymax + 0.12 * dy


LEGEND_HIDDEN = {"Observed", "LCL", "UCL", "CENTER", "Measurements"}
CENTER_NAMES = {"R Chart": "Rbar", "Xbar Chart": "Mean"}


def _text_units(label: str) -> float:
    """Conservative font-independent text width in ems, without importing a GUI/PDF library."""
    return sum(.3 if char in " il.,:;'|" else .9 if char in "MW@#" else .64 if char.isupper() else .57
               for char in str(label))


def _category_layout(spec: ChartSpec, width: float, height: float, left: float, right: float,
                     note_height: float) -> tuple[float, float, float, float, int]:
    """Return left margin, plot bottom, label size, angle and horizontal label rows.

    Sample identities are never abbreviated or sampled. Rotating the full text about
    its right end leaves the last characters immediately below their plotted sample.
    """
    base_bottom = height - (note_height + 38)
    if not spec.categories:
        return left, base_bottom, 8.0, 0.0, 1
    count = len(spec.categories)
    longest = max(_text_units(name) for name in spec.categories)
    sample_axis = spec.x_label in {"Sample ID", "SN", "Part"}
    available = max(1.0, right - left)
    angle = 45.0 if sample_axis or longest * 7.5 > available / count else 0.0
    if angle:
        size = 7.5
        sine = math.sqrt(.5)
        for _ in range(3):
            # Parallel 45-degree baselines need their font height between neighbours.
            slot = max(1.0, right - left) / max(1, count - 1)
            size = min(7.5, max(4.5, slot * sine / 1.1))
            projected = (longest * size + size) * sine
            left = max(left, projected + 7)
        # Retain a useful plot area when labels are unusually long. Rendering keeps
        # every complete label, using a smaller font rather than clipping its text.
        vertical_budget = max(8.0, height - 36 - 58 - note_height - 30)
        size = min(size, vertical_budget / max(1.0, (longest + 1) * sine))
        projected = (longest * size + size) * sine
        left = max(58.0 if spec.show_y else 14.0, projected + 7)
        bottom = height - (note_height + projected + 30)
        return left, max(55.0, bottom), size, angle, 1
    # Short component/source names fit horizontally; all of them are still emitted.
    rows = 2 if longest * 7.5 > available / count else 1
    return left, height - (note_height + 38 + 10 * (rows - 1)), 7.5, 0.0, rows


def _ticks(low: float, high: float) -> tuple[list[float], float]:
    """Round tick positions (1, 2 or 5 times a power of ten) inside the axis, and their spacing."""
    span = high - low
    if span <= 0 or not math.isfinite(span):
        return [low], 0.0
    raw = span / 4
    exponent = math.floor(math.log10(raw))
    fraction = raw / 10 ** exponent
    step = (1 if fraction < 1.5 else 2 if fraction < 3.5 else 5 if fraction < 7.5 else 10) * 10 ** exponent
    first, last = math.ceil(low / step - 1e-9), math.floor(high / step + 1e-9)
    return [round(k * step, 12) for k in range(first, last + 1)], step


def _tick(value: float, step: float) -> str:
    """A tick label with just enough decimals to tell neighbouring ticks apart."""
    if value == 0:
        return "0"
    if step <= 0 or not math.isfinite(step):
        return f"{value:.4g}"
    decimals = max(0, min(10, 1 - math.floor(math.log10(step))))
    return f"{value:.{decimals}f}" if abs(value) >= 1e-4 or decimals <= 6 else f"{value:.3g}"


def chart_primitives(spec: ChartSpec, width: float = 650, height: float = 280):
    """Return portable (kind, coordinates, style) tuples, using top-left coordinates."""
    limits = [s for s in spec.series if s.label in ("LCL", "CENTER", "UCL") and s.points]
    entries = [s for s in spec.series if s.label not in LEGEND_HIDDEN]
    margins = [18.0]
    if limits:
        margins.append(12 + 7.5 * max(_text_units(f"UCL={s.points[0][1]:.6g}") for s in limits))
    if entries:
        margins.append(32 + 7.5 * max(_text_units(s.label) for s in entries))
    margin = max(margins)
    left, top, right = (58.0 if spec.show_y else 14.0), 36.0, width - margin
    note_lines = textwrap.wrap(spec.note, max(30, int((right - left) / 3.4)))
    note_height = len(note_lines) * 9 + (8 if note_lines else 0)
    left, bottom, category_size, category_angle, rows = _category_layout(
        spec, width, height, left, right, note_height,
    )
    # A very long identifier must not invert a small plot's horizontal scale.
    right = max(left + 25, right)
    xmin, xmax, ymin, ymax = _bounds(spec)

    def px(x):
        return left + (x - xmin) / (xmax - xmin) * (right - left)

    def py(y):
        return bottom - (y - ymin) / (ymax - ymin) * (bottom - top)
    output = [("line", (left, top, left, bottom), {"color": "#748391"}),
              ("line", (left, bottom, right, bottom), {"color": "#748391"})]
    if spec.title:
        output.insert(0, ("text", (left, 14), {"text": spec.title, "bold": True, "size": 11, "anchor": "w"}))
    yticks, ystep = _ticks(ymin, ymax)
    for y in yticks:
        output.append(("line", (left, py(y), right, py(y)), {"color": "#E5EAF0"}))
        if spec.show_y:
            output.append(("text", (left - 5, py(y)), {"text": _tick(y, ystep), "size": 8, "anchor": "e"}))
    if spec.categories:
        for i, name in enumerate(spec.categories):
            output.append(("text", (px(i + 1), bottom + (8 if category_angle else 12 + 10 * (i % rows))),
                           {"text": str(name), "size": category_size, "anchor": "e" if category_angle else "center",
                            "angle": category_angle, "category": True}))
    else:
        xticks, xstep = _ticks(xmin, xmax)
        for x in xticks:
            output.append(("text", (px(x), bottom + 12), {"text": _tick(x, xstep), "size": 8, "anchor": "center"}))
    for series in spec.series:
        points = [(px(x), py(y)) for x, y in series.points if math.isfinite(x) and math.isfinite(y)]
        if series.kind == "bar":
            bar_count = sum(item.kind == "bar" for item in spec.series)
            barwidth = min(60, (right - left) / max(2, len(points) * bar_count) * 0.6)
            for x, y in points:
                output.append(("rect", (x - barwidth / 2, y, x + barwidth / 2, py(0)), {"color": series.color}))
        elif series.kind == "scatter":
            for x, y in points:
                output.append(("circle", (x - 2.5, y - 2.5, x + 2.5, y + 2.5), {"color": series.color}))
        elif len(points) > 1:
            output.append(("line", tuple(c for point in points for c in point),
                           {"color": series.color, "width": 1.4, "dash": series.dash}))
            if series.label in ("Observed", "Sample means") or series.kind == "marked":
                for x, y in points:
                    output.append(("circle", (x - 2, y - 2, x + 2, y + 2), {"color": series.color}))
        elif points:
            x, y = points[0]
            output.append(("circle", (x - 2, y - 2, x + 2, y + 2), {"color": series.color}))
    placed = -1e9
    for series in sorted(limits, key=lambda s: py(s.points[0][1])):  # each control limit's value at the right edge, kept apart
        value = series.points[0][1]
        name = CENTER_NAMES.get(spec.title, "CL") if series.label == "CENTER" else series.label
        y = max(py(value), placed + 9)
        placed = y
        output.append(("text", (right + 4, y), {"text": f"{name}={value:.6g}", "size": 7.5, "anchor": "w", "color": series.color}))
    for label, value in spec.markers:
        if xmin <= value <= xmax:
            output.append(("line", (px(value), top, px(value), bottom), {"color": "#BD3434", "width": 1.2, "dash": True}))
            output.append(("text", (px(value), top - 7), {"text": label, "size": 8, "anchor": "center", "color": "#BD3434"}))
        else:
            edge = left if value < xmin else right
            output.append(("line", (edge, top, edge, bottom), {"color": "#BD3434", "width": 1.2, "dash": True}))
            output.append(("text", (edge, top - 7), {"text": label + " (off scale)", "size": 7,
                                                       "anchor": "w" if value < xmin else "e", "color": "#BD3434"}))
    if entries:  # a plain legend to the right of the plot, as in Minitab's graphs
        x0 = right + 8
        for i, series in enumerate(entries):
            y = top + 9 + i * 12
            if series.kind == "bar":
                output.append(("rect", (x0, y - 3.5, x0 + 9, y + 3.5), {"color": series.color}))
            else:
                output.append(("line", (x0, y, x0 + 18, y), {"color": series.color, "width": 1.4, "dash": series.dash}))
            output.append(("text", (x0 + 22, y), {"text": series.label, "size": 7.5, "anchor": "w"}))
    output.append(("text", ((left + right) / 2, height - note_height - 12),
                   {"text": spec.x_label, "size": 8, "anchor": "center"}))
    for line, text in enumerate(note_lines):
        output.append(("text", (left, height - note_height + 4 + line * 9), {"text": text, "size": 6.5, "anchor": "w"}))
    if spec.show_y:
        output.append(("text", (left, top - 10), {"text": spec.y_label, "size": 7, "anchor": "w"}))
    return output


def _draw_primitives(canvas, primitives, dx: float = 0.0, dy: float = 0.0) -> None:
    for kind, coords, style in primitives:
        coords = tuple(value + (dx if i % 2 == 0 else dy) for i, value in enumerate(coords))
        color = style.get("color", "#263746")
        if kind == "text":
            canvas.create_text(*coords, text=style["text"], fill=color, anchor=style.get("anchor", "w"),
                               angle=style.get("angle", 0),
                               font=("Segoe UI", max(1, round(style.get("size", 9))), "bold" if style.get("bold") else "normal"))
        elif kind == "line":
            canvas.create_line(*coords, fill=color, width=style.get("width", 1), dash=(5, 3) if style.get("dash") else ())
        elif kind == "rect":
            canvas.create_rectangle(*coords, fill=color, outline="")
        elif kind == "circle":
            canvas.create_oval(*coords, fill=color, outline="")


def draw_tk_chart(canvas, spec: ChartSpec, width: int | None = None, height: int | None = None) -> None:
    width, height = width or max(360, canvas.winfo_width()), height or max(240, canvas.winfo_height())
    canvas.delete("all")
    _draw_primitives(canvas, chart_primitives(spec, width, height))


def draw_tk_charts(canvas, specs: Sequence[ChartSpec], columns: int = 2, min_height: int = 190) -> None:
    """Every chart of an item in a grid, as Minitab's report shows them; the canvas scrolls when they do not fit."""
    width, height = max(360, canvas.winfo_width()), max(240, canvas.winfo_height())
    canvas.delete("all")
    if not specs:
        canvas.configure(scrollregion=(0, 0, width, height))
        return
    columns = max(1, min(columns, len(specs)))
    rows = math.ceil(len(specs) / columns)
    cell_w, cell_h = width / columns, max(min_height, height / rows)
    for index, spec in enumerate(specs):
        _draw_primitives(canvas, chart_primitives(spec, cell_w - 8, cell_h - 6), (index % columns) * cell_w + 4, (index // columns) * cell_h)
    canvas.configure(scrollregion=(0, 0, width, rows * cell_h))


def reportlab_chart(spec: ChartSpec, width: float = 650, height: float = 280,
                    font_name: str = "Helvetica", bold_font: str = "Helvetica-Bold"):
    """Convert the shared primitives into a vector PDF drawing, importing ReportLab lazily."""
    from reportlab.graphics.shapes import Circle, Drawing, Group, Line, PolyLine, Rect, String
    from reportlab.lib.colors import HexColor

    drawing = Drawing(width, height)
    for kind, coords, style in chart_primitives(spec, width, height):
        color = HexColor(style.get("color", "#263746"))
        if kind == "text":
            anchor = {"w": "start", "e": "end", "center": "middle"}.get(style.get("anchor"), "start")
            label = String(0, 0, str(style["text"]), fillColor=color,
                           fontName=bold_font if style.get("bold") else font_name,
                           fontSize=style.get("size", 9), textAnchor=anchor)
            group = Group(label)
            group.translate(coords[0], height - coords[1] - 3)
            group.rotate(style.get("angle", 0))
            drawing.add(group)
        elif kind == "line":
            points = [v if i % 2 == 0 else height - v for i, v in enumerate(coords)]
            dash = [5, 3] if style.get("dash") else None
            if len(points) == 4:
                drawing.add(Line(*points, strokeColor=color, strokeWidth=style.get("width", 1), strokeDashArray=dash))
            else:
                drawing.add(PolyLine(points, strokeColor=color, strokeWidth=style.get("width", 1), strokeDashArray=dash))
        elif kind == "rect":
            x1, y1, x2, y2 = coords
            drawing.add(Rect(x1, height - max(y1, y2), x2 - x1, abs(y2 - y1), fillColor=color, strokeColor=None))
        elif kind == "circle":
            x1, y1, x2, y2 = coords
            drawing.add(Circle((x1 + x2) / 2, height - (y1 + y2) / 2, (x2 - x1) / 2,
                               fillColor=color, strokeColor=None))
    return drawing
