"""Shared chart data and vector renderers for statistical preview and reports.

All statistical estimates come from ``AnalysisResult``; rendering never changes data.
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
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


AGREEMENT_TITLES = ("Within Appraisers", "Appraiser vs Standard")  # the two panels of an Attribute Agreement chart
AGREEMENT_PERCENT, AGREEMENT_INTERVAL = "#0068A8", "#C0392B"  # the percent agreement (a circle) and its confidence limits (an X)


def agreement_charts(result) -> list[ChartSpec]:
    """Minitab's Assessment Agreement graph: one panel for Within Appraisers and one for Appraiser vs Standard, each with the
    percent agreement of every appraiser and its exact confidence interval at the level of the analysis. A panel the study
    cannot have (a single trial, no Standard) is left out. A Standard that was given but cannot be used leaves its panel with an
    N/A and the reason, instead of silently dropping it. The limits of an interval are two consecutive points at one x."""
    details = result.details
    appraisers = details.get("appraisers", ())
    level = f"{100 * details.get('confidence', 0.95):g}% CI"
    specs = []
    for title, key in (AGREEMENT_TITLES[0], "within"), (AGREEMENT_TITLES[1], "standard"):
        shown = [(a["label"], a[key]) for a in appraisers if a[key]]
        if shown:
            percent = ChartSeries("Percent", tuple((i, e["percent"]) for i, (_, e) in enumerate(shown, 1)), AGREEMENT_PERCENT, "scatter")
            limits = tuple(point for i, (_, e) in enumerate(shown, 1) for point in ((i, e["lower"]), (i, e["upper"])))
            specs.append(ChartSpec(title, "Appraiser", "Percent", (percent, ChartSeries(level, limits, AGREEMENT_INTERVAL, "interval")),
                                   categories=tuple(label for label, _ in shown)))
        elif key == "standard" and details.get("standard_problem"):
            specs.append(ChartSpec(title, "Appraiser", "Percent", (), note=f"N/A: {details['standard_problem']}"))
    return specs


def agreement_chart_note(result) -> str:
    """Why an analysed Attribute Agreement item has no panel to draw (empty when it has one)."""
    if not result.valid or agreement_charts(result):
        return ""
    return "No chart applies: Within Appraisers needs two or more trials, and Appraiser vs Standard needs a Standard."


def agreement_axis(spec: ChartSpec) -> tuple[float, float]:
    """The percent scale of an agreement panel: from the lower ten that holds its lowest limit (0 when that is under 10) to 100."""
    lows = [y for series in spec.series for _, y in series.points if math.isfinite(y)]
    return (0.0 if not lows or min(lows) < 10 else float(math.floor(min(lows) / 10) * 10)), 100.0


def charts_for_result(result) -> list[ChartSpec]:
    if result.method == "attribute":
        return agreement_charts(result) if result.valid else []  # no histogram, no Gage R&R chart, no control chart applies
    if not result.valid:
        note = "Analysis unavailable: " + "; ".join(i.message for i in result.issues if i.severity == "error")
        titles = ("Process Capability Histogram",) if result.method == "capability" else (
            "Components of Variation", "R Chart", "Xbar Chart", "Measurement by Sample ID")
        return [ChartSpec(title, "", "", (), note=note) for title in titles]
    return [capability_chart(result)] if result.method == "capability" else grr_charts(result)


def _bounds(spec: ChartSpec):
    if spec.title in AGREEMENT_TITLES:  # a percent scale that ends at 100, with room for the markers at 0 and 100; one slot for each appraiser
        low, high = agreement_axis(spec)
        pad = 0.04 * (high - low)
        return 0.5, max(1, len(spec.categories)) + 0.5, low - pad, high + pad
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


MAX_DECIMALS = 15  # chart numbers are written out in full; this is where even a tiny scale stops getting more digits
X_SCALES = ("auto", "full")  # the horizontal scales of a capability histogram on screen (the report keeps its own)
AUTO_REACH = 0.5  # auto scale: a limit within this share of the width of the data (beyond its edge) is still drawn
LEGEND_HIDDEN = {"Observed", "LCL", "UCL", "CENTER", "Measurements"}
CENTER_NAMES = {"R Chart": "Rbar", "Xbar Chart": "Mean"}
SAMPLE_AXES = {"Sample ID", "SN", "Part"}  # the axes whose labels are identities of the parts
LABEL_LENGTH = 9  # characters: on screen, a longer sample identity is shortened (the report prints it in full)
_REPORT_SIZES = {"title": 11, "tick": 8, "axis": 8, "limit": 7.5, "legend": 7.5, "y": 7, "note": 6.5}  # points, as the reports draw
_SCREEN_SIZES = {"title": 10, "tick": 8, "axis": 8, "limit": 8, "legend": 8, "y": 8, "note": 7}  # whole points: the screen rounds them
MIN_CELL_WIDTH = 340  # on screen, charts go side by side only when each gets this many pixels
AGREEMENT_PLOT_MIN = 90.0  # on screen, the least height the plot of an agreement panel gets, whatever the appraisers are called (usual studies get 100 or more)


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
    sample_axis = spec.x_label in SAMPLE_AXES
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
    return [float(f"{k * step:.12g}") for k in range(first, last + 1)], step  # 12 digits drop float noise, not tiny steps


def plain_number(value: float, digits: int = 6) -> str:
    """Significant digits written out in full (0.00005, not 5E-05), as Minitab's reports print numbers."""
    return format(Decimal(f"{value:.{digits}g}"), "f") if math.isfinite(value) else str(value)


def _tick(value: float, step: float) -> str:
    """A tick label with just enough decimals to tell neighbouring ticks apart."""
    if value == 0:
        return "0"
    if step <= 0 or not math.isfinite(step):
        return plain_number(value, 4)
    return f"{value:.{max(0, min(MAX_DECIMALS, 1 - math.floor(math.log10(step))))}f}"


def _limit_decimals(values: Sequence[float]) -> int:
    """Decimals for the control limits of one chart: Minitab's 6, or more when the limits are close together or tiny."""
    distinct = sorted({v for v in values if math.isfinite(v)})
    gaps = [b - a for a, b in zip(distinct, distinct[1:], strict=False)]
    return min(MAX_DECIMALS, max(6, 2 - math.floor(math.log10(min(gaps))))) if gaps else 6


def _limit_text(name: str, value: float, decimals: int) -> str:
    """``UCL=0.003217``, ``LCL=0``: a limit as Minitab writes it beside the chart, never in scientific notation."""
    return f"{name}={0 if value == 0 else f'{value:.{decimals}f}'}"


def _bin_width(spec: ChartSpec) -> float:
    """The width of a histogram bar in the units of the measurement (the bars are drawn at the centre of their bin)."""
    centres = sorted(x for s in spec.series if s.kind == "bar" for x, _ in s.points if math.isfinite(x))
    return min((b - a for a, b in zip(centres, centres[1:], strict=False) if b > a), default=0.0)


def _histogram_range(spec: ChartSpec, scale: str) -> tuple[float, float]:
    """The horizontal range of a histogram. It always holds every bar and curve, with a margin. ``auto`` adds only the
    specification limits that lie close to them; ``full`` adds both limits, however far. The data is never stretched."""
    xs = [x for s in spec.series for x, _ in s.points if math.isfinite(x)]
    if not xs:
        return 0.0, 1.0
    low, high, half = min(xs), max(xs), _bin_width(spec) / 2
    centres = [x for s in spec.series if s.kind == "bar" for x, _ in s.points if math.isfinite(x)]
    if centres:
        low, high = min(low, min(centres) - half), max(high, max(centres) + half)
    reach = AUTO_REACH * ((high - low) or max(abs(low) * 0.01, 0.001))
    view_low, view_high = low, high
    for _, value in spec.markers:
        if math.isfinite(value) and (scale == "full" or max(low - value, value - high) <= reach):
            view_low, view_high = min(view_low, value), max(view_high, value)
    pad = 0.05 * ((view_high - view_low) or max(abs(view_low) * 0.01, 0.001))
    return view_low - pad, view_high + pad


def short_labels(labels: Sequence[str]) -> list[str]:
    """The labels as a small chart on screen shows them. A long identity keeps its tail (``VSEC0020000042`` becomes
    ``…0042``), as many characters as it takes to tell the labels apart. Only what is drawn changes, never the identity."""
    names = [str(label) for label in labels]
    if max(map(len, names), default=0) <= LABEL_LENGTH or len(set(names)) < 2:
        return names
    parts = [name.split(" / ") for name in names]
    if len(parts[0]) > 1 and len({len(p) for p in parts}) == 1:  # "operator / sample": each part is shortened on its own
        columns = [short_labels([p[i] for p in parts]) for i in range(len(parts[0]))]
        return [" / ".join(row) for row in zip(*columns, strict=True)]
    for keep in range(LABEL_LENGTH - 5, max(map(len, names)) + 1):
        tails = [name[-keep:] for name in names]
        if len(set(tails)) == len(set(names)):
            return [("…" if len(name) > keep else "") + tail for name, tail in zip(names, tails, strict=True)]
    return names


def _category_plan(names: Sequence[str], slot: float, size: float, k: float,
                   shorten: bool) -> tuple[list[str], float, int, int, float]:
    """For a chart on screen: (the labels as drawn, their angle, rows, every nth label, height under the axis).
    Labels go side by side if they fit their slot, in two staggered rows if they fit two slots, else at 45 degrees,
    and every nth one when even those would touch. Sample identities are shortened; the names of sources are not."""
    shown = short_labels(names) if shorten else [str(name) for name in names]
    em = size * k
    width = max((_text_units(name) * em for name in shown), default=0.0)
    if width + 6 <= slot:
        return shown, 0.0, 1, 1, em + 6
    if width + 6 <= 2 * slot:
        return shown, 0.0, 2, 1, 2 * em + 8
    return shown, 45.0, 1, max(1, math.ceil(1.7 * em / slot)), (width + em) * math.sqrt(.5) + 8


MARKER_KINDS = ("scatter", "interval")  # drawn as a symbol rather than a line or a bar, in the plot and in the legend


def _cross(color: str, x: float, y: float, half: float = 4.0) -> list[tuple]:
    """An X marker centred on (x, y)."""
    return [("line", (x - half, y - half, x + half, y + half), {"color": color, "width": 1.4}),
            ("line", (x - half, y + half, x + half, y - half), {"color": color, "width": 1.4})]


def _marker(series: ChartSeries, x: float, y: float) -> list[tuple]:
    """The legend symbol of a series drawn as a symbol: the circle of a percent, the X of its limits."""
    if series.kind == "scatter":
        return [("circle", (x - 3.5, y - 3.5, x + 3.5, y + 3.5), {"color": series.color})]
    return _cross(series.color, x, y)


def chart_primitives(spec: ChartSpec, width: float = 650, height: float = 280, x_scale: str | None = None,
                     compact: bool = False, scale: float = 1.0):
    """Return portable (kind, coordinates, style) tuples, using top-left coordinates.

    ``x_scale`` ("auto" or "full") is for a capability histogram on screen: it sets the horizontal range only (see
    ``_histogram_range``), draws the bars at the true width of their bins, and puts the legend in a row under the title.
    ``compact`` is for any chart on screen: the legend is a row under the title, long sample identities are shortened
    (``short_labels``), and the spacing follows the size of the text, ``scale`` being the pixels of the screen per point
    of type. Without them the chart is drawn as the reports draw it."""
    histogram = x_scale in X_SCALES
    unavailable = spec.title in AGREEMENT_TITLES and not spec.series  # an agreement panel that has only its reason to show
    k = scale if compact and scale > 0 else 1.0
    size = _SCREEN_SIZES if compact else _REPORT_SIZES
    em = size["tick"] * k

    def text_width(text: str, points: float) -> float:
        return _text_units(text) * points * k

    limits = [s for s in spec.series if s.label in ("LCL", "CENTER", "UCL") and s.points]
    entries = [s for s in spec.series if s.label not in LEGEND_HIDDEN]
    margins = [18.0]
    limit_decimals = _limit_decimals([s.points[0][1] for s in limits])
    def limit_name(series: ChartSeries) -> str:
        return CENTER_NAMES.get(spec.title, "CL") if series.label == "CENTER" else series.label

    if limits:  # on screen the room is for the longest name (Rbar=, Mean=), as the reports have always kept room for UCL=
        margins.append(12 + max(text_width(_limit_text(limit_name(s) if compact else "UCL", s.points[0][1], limit_decimals), size["limit"])
                                for s in limits))
    if entries and not histogram and not compact:
        margins.append(32 + max(text_width(s.label, size["legend"]) for s in entries))
    margin = max(margins)
    xmin, xmax, ymin, ymax = _bounds(spec)
    if histogram:
        xmin, xmax = _histogram_range(spec, x_scale)
    yticks, ystep = _ticks(ymin, ymax)

    def ytick(value: float) -> str:  # a percent scale in whole numbers, unless its step is smaller than one
        return f"{value:g}" if spec.title in AGREEMENT_TITLES and ystep >= 1 else _tick(value, ystep)

    # The vertical scale gets room for its labels, which are long when the values are tiny and written out in full.
    tick_width = max((text_width(ytick(y), size["tick"]) for y in yticks), default=0)
    left_edge = (26 + tick_width if compact else max(58.0, 10 + tick_width)) if spec.show_y else 14.0
    right = width - margin
    legend_row = bool(entries) and (histogram or compact)
    rows_of_legend, legend_at = 1, []  # the legend row wraps when the entries do not fit the width
    if legend_row:
        x0 = left_edge
        for series in entries:
            item = (16 if compact and series.kind == "bar" else 22) + text_width(series.label, size["legend"])
            if x0 > left_edge and x0 + item > width - 6:
                x0, rows_of_legend = left_edge, rows_of_legend + 1
            legend_at.append((series, x0, rows_of_legend - 1))
            x0 += item + 14
    pitch = round(12 * k)
    legend_y = round(26 + 3 * k) if compact else 27
    if legend_row:
        top = legend_y + (rows_of_legend - 1) * pitch + (em / 2 + (14 if spec.markers else 8) if compact else 17)
    else:
        top = (32 + (6 if spec.markers else 0)) if compact else 36.0
    left, top = left_edge, float(top)
    if unavailable:  # its note is said in the middle of the panel, not under it
        note_lines = []
    elif compact:  # the note runs under the whole chart, in the width the text really takes
        note_lines = textwrap.wrap(spec.note, max(20, int((width - 16) / max(1.0, text_width("n", size["note"])))))
    else:
        note_lines = textwrap.wrap(spec.note, max(30, int((right - left) / 3.4)))
    note_height = len(note_lines) * 9 + (8 if note_lines else 0)
    category_rows, category_step, shown = 1, 1, [str(name) for name in spec.categories]
    if compact:
        axis_title = height - note_height - em / 2 - 3
        slot = (right - left) / max(1, len(spec.categories))
        if spec.categories:
            shown, category_angle, category_rows, category_step, label_height = _category_plan(
                spec.categories, slot, size["tick"], k, spec.x_label in SAMPLE_AXES)
            if category_angle:
                left = max(left, max(text_width(name, size["tick"]) for name in shown) * .7 + 10)
        else:
            category_angle, label_height = 0.0, em + 6
        bottom, category_size = axis_title - em / 2 - label_height - 4, size["tick"]
    else:
        left, bottom, category_size, category_angle, category_rows = _category_layout(
            spec, width, height, left, right, note_height,
        )
    left = max(left, left_edge)
    # A very long identifier must not invert a small plot's horizontal scale.
    right = max(left + 25, right)

    def px(x):
        return left + (x - xmin) / (xmax - xmin) * (right - left)

    def py(y):
        return bottom - (y - ymin) / (ymax - ymin) * (bottom - top)
    output = [("line", (left, top, left, bottom), {"color": "#748391"}),
              ("line", (left, bottom, right, bottom), {"color": "#748391"})]
    if spec.title:
        output.insert(0, ("text", (left, 14), {"text": spec.title, "bold": True, "size": size["title"], "anchor": "w"}))
    for y in yticks:
        output.append(("line", (left, py(y), right, py(y)), {"color": "#E5EAF0"}))
        if spec.show_y:
            output.append(("text", (left - 5, py(y)), {"text": ytick(y), "size": size["tick"], "anchor": "e"}))
    if spec.categories and compact:
        for i, name in enumerate(shown):
            output.append(("line", (px(i + 1), bottom, px(i + 1), bottom + 3), {"color": "#748391"}))
            if i % category_step == 0:
                y = bottom + 6 + (0 if category_angle else em / 2 + (i % category_rows) * (em + 1))
                output.append(("text", (px(i + 1), y), {"text": name, "size": category_size, "anchor": "e" if category_angle else "center",
                                                        "angle": category_angle, "category": True}))
    elif spec.categories:
        for i, name in enumerate(spec.categories):
            output.append(("text", (px(i + 1), bottom + (8 if category_angle else 12 + 10 * (i % category_rows))),
                           {"text": str(name), "size": category_size, "anchor": "e" if category_angle else "center",
                            "angle": category_angle, "category": True}))
    elif not unavailable:
        xticks, xstep = _ticks(xmin, xmax)
        for x in xticks:
            output.append(("text", (px(x), bottom + (6 + em / 2 if compact else 12)), {"text": _tick(x, xstep), "size": size["tick"], "anchor": "center"}))
    # In an agreement panel the percent is drawn last, on top of its interval (the legend keeps the order of the series).
    drawn = sorted(spec.series, key=lambda s: s.kind == "scatter") if spec.title in AGREEMENT_TITLES else spec.series
    for series in drawn:
        points = [(px(x), py(y)) for x, y in series.points if math.isfinite(x) and math.isfinite(y)]
        if series.kind == "bar":
            bar_count = sum(item.kind == "bar" for item in spec.series)
            barwidth = min(60, (right - left) / max(2, len(points) * bar_count) * 0.6)
            if histogram and _bin_width(spec) > 0:  # the bars are the bins: as wide as the measurements make them
                bin_px = _bin_width(spec) / (xmax - xmin) * (right - left)
                barwidth = max(1.0, bin_px - (1 if bin_px > 4 else 0))
            for x, y in points:
                output.append(("rect", (x - barwidth / 2, y, x + barwidth / 2, py(0)), {"color": series.color}))
        elif series.kind == "scatter":
            radius = 3.5 if spec.title in AGREEMENT_TITLES else 2.5
            for x, y in points:
                output.append(("circle", (x - radius, y - radius, x + radius, y + radius), {"color": series.color}))
        elif series.kind == "interval":  # consecutive points at one x: a line between the two limits, each marked with an X
            for (x, low_y), (_, high_y) in zip(points[0::2], points[1::2], strict=False):
                output.append(("line", (x, low_y, x, high_y), {"color": series.color, "width": 1.4}))
                for y in (low_y, high_y):
                    output += _cross(series.color, x, y)
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
    spacing = size["limit"] * k * 1.3 if compact else 9
    for series in sorted(limits, key=lambda s: py(s.points[0][1])):  # each control limit's value at the right edge, kept apart
        value = series.points[0][1]
        name = limit_name(series)
        y = max(py(value), placed + spacing)
        placed = y
        output.append(("text", (right + 4, y), {"text": _limit_text(name, value, limit_decimals), "size": size["limit"], "anchor": "w",
                                                  "color": series.color}))
    off_scale: dict[bool, list[str]] = {True: [], False: []}  # histogram: the limits outside the range, by the side they are on
    for label, value in spec.markers:
        if xmin <= value <= xmax:
            output.append(("line", (px(value), top, px(value), bottom), {"color": "#BD3434", "width": 1.2, "dash": True}))
            output.append(("text", (px(value), top - 7), {"text": label, "size": 8, "anchor": "center", "color": "#BD3434"}))
        elif histogram:
            off_scale[value < xmin].append(label)
        else:
            edge = left if value < xmin else right
            output.append(("line", (edge, top, edge, bottom), {"color": "#BD3434", "width": 1.2, "dash": True}))
            output.append(("text", (edge, top - 7), {"text": label + " (off scale)", "size": 7,
                                                       "anchor": "w" if value < xmin else "e", "color": "#BD3434"}))
    for below, labels in off_scale.items():
        if labels:
            text = f"{', '.join(labels)} off scale"
            output.append(("text", (left if below else right, top - 7), {"text": f"← {text}" if below else f"{text} →", "size": 8,
                                                                          "anchor": "w" if below else "e", "color": "#BD3434"}))
    if legend_row:  # a row (or two) under the title: it cannot be clipped by the edge of the chart or hide a curve
        for series, x0, row in legend_at:
            y = legend_y + row * pitch
            if compact and series.kind == "bar":
                output.append(("rect", (x0, y - 3.5, x0 + 10, y + 3.5), {"color": series.color}))
                output.append(("text", (x0 + 15, y), {"text": series.label, "size": size["legend"], "anchor": "w"}))
            elif series.kind in MARKER_KINDS:
                output += _marker(series, x0 + 9, y)
                output.append(("text", (x0 + 22, y), {"text": series.label, "size": size["legend"], "anchor": "w"}))
            else:
                output.append(("line", (x0, y, x0 + 18, y), {"color": series.color, "width": 1.4, "dash": series.dash}))
                output.append(("text", (x0 + 22, y), {"text": series.label, "size": size["legend"], "anchor": "w"}))
    elif entries:  # a plain legend to the right of the plot, as in Minitab's graphs
        x0 = right + 8
        for i, series in enumerate(entries):
            y = top + 9 + i * 12
            if series.kind == "bar":
                output.append(("rect", (x0, y - 3.5, x0 + 9, y + 3.5), {"color": series.color}))
            elif series.kind in MARKER_KINDS:
                output += _marker(series, x0 + 9, y)
            else:
                output.append(("line", (x0, y, x0 + 18, y), {"color": series.color, "width": 1.4, "dash": series.dash}))
            output.append(("text", (x0 + 22, y), {"text": series.label, "size": size["legend"], "anchor": "w"}))
    if unavailable and spec.note:
        wrap = max(12, int((right - left - 16) / max(1.0, text_width("n", size["axis"]))))
        lines = textwrap.wrap(spec.note, wrap)
        for index, line in enumerate(lines):
            output.append(("text", ((left + right) / 2, (top + bottom) / 2 + (index - (len(lines) - 1) / 2) * size["axis"] * k * 1.4),
                           {"text": line, "size": size["axis"], "anchor": "center", "color": "#526174"}))
    output.append(("text", ((left + right) / 2, axis_title if compact else height - note_height - 12),
                   {"text": spec.x_label, "size": size["axis"], "anchor": "center"}))
    for line, text in enumerate(note_lines):
        output.append(("text", (left if not compact else 8, height - note_height + 4 + line * 9), {"text": text, "size": size["note"], "anchor": "w"}))
    if spec.show_y and compact:  # turned to read upward, left of the numbers; without the unit when it would not fit
        label = spec.y_label if text_width(spec.y_label, size["axis"]) <= bottom - top else spec.y_label.split(" (")[0]
        output.append(("text", (4 + em / 2, (top + bottom) / 2), {"text": label, "size": size["axis"], "anchor": "center", "angle": 90}))
    elif spec.show_y:
        output.append(("text", (left, top - 10), {"text": spec.y_label, "size": size["y"], "anchor": "w"}))
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


def _pixels_per_point(canvas) -> float:
    """How many pixels one point of type takes on this screen (1.0 on a Mac, 1.33 on Windows at 96 dpi, more when scaled)."""
    try:
        return min(3.0, max(0.75, float(canvas.winfo_fpixels("1p"))))
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return 1.0


def agreement_extra_height(spec: ChartSpec, width: float, height: float, scale: float = 1.0) -> float:
    """How much taller than ``height`` an agreement panel must be on screen for its plot to keep ``AGREEMENT_PLOT_MIN`` pixels. Many
    appraisers, or long names, take most of a small panel for their rotated labels; the panel then grows (the canvas scrolls)
    instead of squeezing the plot away. Every other panel needs nothing."""
    if spec.title not in AGREEMENT_TITLES or not spec.categories:
        return 0.0
    _, top, _, bottom = next(coords for kind, coords, _ in chart_primitives(spec, width, height, None, True, scale) if kind == "line")
    return max(0.0, AGREEMENT_PLOT_MIN - (bottom - top))  # the plot is the axis: its height does not depend on the panel's other parts


def draw_tk_charts(canvas, specs: Sequence[ChartSpec], columns: int = 2, min_height: int = 190,
                   x_scale: str | None = None, compact: bool = False) -> None:
    """Every chart of an item in a grid, as Minitab's report shows them; the canvas scrolls when they do not fit.
    ``compact`` adapts them to the screen: the charts go side by side only when each gets room (``MIN_CELL_WIDTH``), their
    spacing follows the size of the text, and long sample identities are shortened."""
    width, height = max(360, canvas.winfo_width()), max(240, canvas.winfo_height())
    canvas.delete("all")
    if not specs:
        canvas.configure(scrollregion=(0, 0, width, height))
        return
    scale = _pixels_per_point(canvas) if compact else 1.0
    if compact:
        columns, min_height = min(columns, int(width // MIN_CELL_WIDTH)), max(min_height, 210)
    columns = max(1, min(columns, len(specs)))
    rows = math.ceil(len(specs) / columns)
    cell_w, cell_h = width / columns, max(min_height, height / rows)
    if compact:
        cell_h += max((agreement_extra_height(spec, cell_w - 8, cell_h - 6, scale) for spec in specs), default=0.0)
    for index, spec in enumerate(specs):
        primitives = chart_primitives(spec, cell_w - 8, cell_h - 6, x_scale, compact, scale)
        _draw_primitives(canvas, primitives, (index % columns) * cell_w + 4, (index // columns) * cell_h)
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
