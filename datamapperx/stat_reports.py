"""Statistical PDF and Excel reports modelled on Minitab's own reports.

A Variable Gage R&R report has, for each test item, the tables Minitab prints (ANOVA, Variance Components, Gage
Evaluation, Number of Distinct Categories) and the Gage R&R graphs. A Process Capability report has the capability
histogram with the Process Data, the Overall and Potential (Within) Capability and the Performance table. Nothing is
recalculated here: the report prints what the analysis found. PASS/FAIL, acceptance criteria and long explanations stay
in the application. Heavy export dependencies load lazily.
"""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from html import escape
from pathlib import Path

from .exporter import set_text
from .stat_charts import ChartSpec, charts_for_result, reportlab_chart
from .statistics.acceptance import metric_label

ALL_SECTIONS = ("charts", "observations")
DEFAULT_SECTIONS = ("charts",)
FOOTER = "DataMapperX · not an official Minitab report"
BLUE = "#0B5CAD"

METRIC_LABELS = {
    "sigma_within": "Within Standard Deviation", "sigma_overall": "Overall Standard Deviation",
    "cp": "Cp", "cpk": "Cpk", "pp": "Pp", "ppk": "Ppk",
    "sigma_grr": "Gage R&R Standard Deviation", "sigma_part": "Part-to-Part Standard Deviation",
    "sigma_total": "Total Standard Deviation", "percent_tolerance": "%SV/Tol",
    "percent_study_var": "%Study Var", "ndc": "NDC", "study_var": "Study Variation of Gage R&R",
    "variance_repeatability": "Repeatability Variance", "variance_part": "Part-to-Part Variance",
    "variance_total": "Total Variance",
    "sigma_reproducibility": "Reproducibility Standard Deviation",
    "sigma_repeatability": "Repeatability Standard Deviation",
    "variance_reproducibility": "Reproducibility Variance",
    "variance_grr": "Gage R&R Variance",
}
CONDITION_TITLES = {
    "acquisition_order": "Order of the readings", "repeated_measurements": "Repeated readings of one unit",
    "sample_size": "Number of observations", "process_stability": "Process stability", "normality": "Normal distribution",
    "nest_as_operator": "Nest as Operator", "one_appraiser": "One appraiser", "design_samples": "Number of parts",
    "design_operators": "Number of operators", "trial_inferred": "Trial numbers",
}
METHOD_TITLES = {
    "grr_one_way": "Gage R&R: one-way ANOVA (one appraiser)", "grr_crossed": "Gage R&R: crossed ANOVA",
    "grr_crossed_interaction_removed": "Gage R&R: crossed ANOVA, interaction removed",
    "grr_crossed_interaction_retained": "Gage R&R: crossed ANOVA, interaction retained",
    "capability_individuals": "Process capability: individuals (average moving range)",
    "capability_pooled": "Process capability: pooled subgroups",
}


# ----------------------------------------------------------------------------- what a report says about the study
@dataclass(frozen=True, slots=True)
class ReportContext:
    """What a report needs besides the results: the study information the user typed, and which items it covers."""
    info: tuple[tuple[str, str], ...] = ()  # Gage name, Date of study, Reported by, Misc: only those that were entered
    included: int = 0
    total: int = 0
    sections: tuple[str, ...] = DEFAULT_SECTIONS
    created: str = ""  # the day the report was made

    @property
    def partial(self) -> bool:
        return 0 < self.included < self.total


def report_context(study, result_set, *, included: Sequence[str] | None = None, sections: Sequence[str] = DEFAULT_SECTIONS,
                   created: str | None = None) -> ReportContext:
    """Collect what a report prints. Refuses a stale result set: a report presents results as current."""
    study.require_current(result_set)
    info = study.info
    labelled = (("Gage name", info.gage_name), ("Date of study", info.date_of_study), ("Reported by", info.reported_by),
                ("Misc", info.misc))
    names = [stat.label for stat in result_set.statistics]
    chosen = set(names if included is None else included)
    return ReportContext(info=tuple((label, value) for label, value in labelled if value), included=sum(n in chosen for n in names),
                         total=len(names), sections=tuple(s for s in ALL_SECTIONS if s in sections),
                         created=created or date.today().isoformat())


def _sections(context: ReportContext | None) -> tuple[str, ...]:
    return context.sections if context is not None else DEFAULT_SECTIONS


# ----------------------------------------------------------------------------- number formats
def display_number(value, precision: int = 3) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "N/A"
        if value != 0 and (abs(value) < 10 ** -precision or abs(value) >= 1e7):
            return f"{value:.{precision}g}"
        return f"{value:.{precision}f}"
    return str(value)


def sig6(value) -> str:
    """Six significant digits, as Minitab prints the process data (7.99423E-11, 0.000124192, 30)."""
    return f"{value:.6g}".upper()


def format_value(value, kind: str, decimals: int = 2) -> str:
    """One cell as the report shows it. ``*`` marks what is not defined, as in Minitab."""
    if isinstance(value, str):
        return value
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "*"
    if kind == "text":
        return str(value)
    if kind == "int":
        return str(int(value))
    if kind == "sig":
        return sig6(value) if not isinstance(value, str) else value
    if kind == "var":  # variance-sized numbers: 7 decimals at the default of 2, significant digits for tiny values
        return sig6(value) if value != 0 and abs(value) < 1e-5 else f"{value:.{decimals + 5}f}"
    if kind in ("pct", "ppm"):
        return f"{value:.2f}"
    if kind == "p":
        return f"{value:.3f}"
    return f"{value:.{decimals}f}"  # f, idx


def _excel_format(value, kind: str, decimals: int) -> str:
    if kind == "var":
        return "0.000000E+00" if value != 0 and abs(value) < 1e-5 else "0." + "0" * (decimals + 5)
    if kind == "sig":
        return "General"
    fixed = {"pct": "0.00", "ppm": "0.00", "p": "0.000", "int": "0"}
    return fixed.get(kind) or ("0." + "0" * decimals if decimals else "0")


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


# ----------------------------------------------------------------------------- the tables of a report
@dataclass(frozen=True, slots=True)
class ReportTable:
    title: str
    headers: tuple[str, ...]  # all empty: the table has no header row
    rows: tuple[tuple, ...]
    kinds: tuple[str, ...]  # per column: text, int, var, f, p, pct, idx, ppm, sig
    note: str = ""

    def cells(self, decimals: int) -> list[list[str]]:
        return [[format_value(v, self.kinds[i], decimals) for i, v in enumerate(row)] for row in self.rows]


def tolerance_of(result) -> float | None:
    return result.usl - result.lsl if result.usl is not None and result.lsl is not None and result.usl > result.lsl else None


def anova_tables(result) -> list[ReportTable]:
    details = result.details

    def table(title, rows, note=""):
        return ReportTable(title, ("Source", "DF", "SS", "MS", "F", "P"),
                           tuple((r["source"], r["df"], r["ss"], "" if r["ms"] is None else r["ms"], "" if r["f"] is None else r["f"],
                                  "" if r["p"] is None else r["p"]) for r in rows),
                           ("text", "int", "var", "var", "f", "p"), note)

    if not details.get("anova"):
        return []
    if not details.get("crossed"):
        return [table("One-Way ANOVA Table", details["anova"])]
    alpha = f"α to remove interaction term = {result.config.interaction_alpha:g}"
    if details.get("interaction_removed") and details.get("anova_with_interaction"):
        return [table("Two-Way ANOVA Table With Interaction", details["anova_with_interaction"], alpha),
                table("Two-Way ANOVA Table Without Interaction", details["anova"])]
    return [table("Two-Way ANOVA Table With Interaction", details["anova"], alpha)]


def _components(result) -> list[tuple[str, float | None, float | None]]:
    """The sources of variation: label, variance and standard deviation, from the analysis."""
    m, d = result.metrics, result.details

    def root(variance):
        return None if variance is None else math.sqrt(variance)

    rows = [("Total Gage R&R", m.get("variance_grr"), m.get("sigma_grr")),
            ("  Repeatability", m.get("variance_repeatability"), m.get("sigma_repeatability"))]
    if d.get("crossed"):
        rows.append(("  Reproducibility", m.get("variance_reproducibility"), m.get("sigma_reproducibility")))
        rows.append(("    Operator", d.get("variance_operator"), root(d.get("variance_operator"))))
        if not d.get("interaction_removed"):
            rows.append(("    Operator*Sample ID", d.get("variance_interaction"), root(d.get("variance_interaction"))))
    rows += [("Part-To-Part", m.get("variance_part"), m.get("sigma_part")), ("Total Variation", m.get("variance_total"), m.get("sigma_total"))]
    return rows


def variance_components_table(result) -> ReportTable:
    total = result.metrics.get("variance_total")
    rows = tuple((label, var, None if var is None or not total else 100 * var / total) for label, var, _ in _components(result))
    return ReportTable("Variance Components", ("Source", "VarComp", "%Contribution\n(of VarComp)"), rows, ("text", "var", "pct"))


def gage_evaluation_table(result) -> ReportTable:
    k, tolerance = result.config.study_factor, tolerance_of(result)
    total_sd = result.metrics.get("sigma_total")
    rows = []
    for label, _, sd in _components(result):
        study = None if sd is None else k * sd
        row = [label, sd, study, None if sd is None or not total_sd else 100 * sd / total_sd]
        if tolerance:
            row.append(None if study is None else 100 * study / tolerance)
        rows.append(tuple(row))
    headers = ("Source", "StdDev (SD)", f"Study Var\n({k:g} × SD)", "%Study Var\n(%SV)") + (("%Tolerance\n(SV/Toler)",) if tolerance else ())
    return ReportTable("Gage Evaluation", headers, tuple(rows), ("text", "var", "var", "pct") + (("pct",) if tolerance else ()))


def grr_tables(result) -> list[ReportTable]:
    return [*anova_tables(result), variance_components_table(result), gage_evaluation_table(result)]


def capability_indices(mean, lsl, usl, within, overall) -> dict[str, float | None]:
    """CPL, CPU, PPL and PPU from the mean, the limits and the two standard deviations."""
    out: dict[str, float | None] = dict.fromkeys(("cpl", "cpu", "ppl", "ppu"))
    for sigma, lower, upper in ((within, "cpl", "cpu"), (overall, "ppl", "ppu")):
        if mean is None or sigma is None or not math.isfinite(sigma) or sigma <= 0:
            continue
        if lsl is not None:
            out[lower] = (mean - lsl) / (3 * sigma)
        if usl is not None:
            out[upper] = (usl - mean) / (3 * sigma)
    return out


def _tail(z: float) -> float:
    """P(Z > z), per million."""
    return 1e6 * 0.5 * math.erfc(z / math.sqrt(2))


def capability_ppm(result) -> dict[str, tuple[float | None, float | None, float | None]]:
    """Observed, expected overall and expected within PPM below LSL, above USL and in total."""
    values = [v for o in result.observations if (v := _num(o.value)) is not None]
    mean, lsl, usl = _num(result.mean), result.lsl, result.usl

    def sides(low, high):
        parts = [p for p in (low, high) if p is not None]
        return low, high, (sum(parts) if parts else None)

    observed = sides(1e6 * sum(v < lsl for v in values) / len(values) if lsl is not None and values else None,
                     1e6 * sum(v > usl for v in values) / len(values) if usl is not None and values else None)

    def expected(sigma):
        if mean is None or sigma is None or not math.isfinite(sigma) or sigma <= 0:
            return None, None, None
        return sides(_tail((mean - lsl) / sigma) if lsl is not None else None, _tail((usl - mean) / sigma) if usl is not None else None)

    return {"observed": observed, "overall": expected(_num(result.metrics.get("sigma_overall"))),
            "within": expected(_num(result.metrics.get("sigma_within")))}


def capability_tables(result) -> list[ReportTable]:
    m = result.metrics
    within, overall = _num(m.get("sigma_within")), _num(m.get("sigma_overall"))
    idx = capability_indices(_num(result.mean), result.lsl, result.usl, within, overall)
    process = ReportTable("Process Data", ("", ""), (
        ("LSL", result.lsl), ("Target", None), ("USL", result.usl), ("Sample Mean", result.mean), ("Sample N", result.n),
        ("StDev(Overall)", overall), ("StDev(Within)", within)), ("text", "sig"))
    overall_table = ReportTable("Overall Capability", ("", ""), (
        ("Pp", m.get("pp")), ("PPL", idx["ppl"]), ("PPU", idx["ppu"]), ("Ppk", m.get("ppk")), ("Cpm", None)), ("text", "idx"))
    within_table = ReportTable("Potential (Within) Capability", ("", ""), (
        ("Cp", m.get("cp")), ("CPL", idx["cpl"]), ("CPU", idx["cpu"]), ("Cpk", m.get("cpk"))), ("text", "idx"))
    ppm = capability_ppm(result)
    performance = ReportTable("Performance", ("", "Observed", "Expected Overall", "Expected Within"), tuple(
        (name, ppm["observed"][i], ppm["overall"][i], ppm["within"][i]) for i, name in enumerate(("PPM < LSL", "PPM > USL", "PPM Total"))),
        ("text", "ppm", "ppm", "ppm"))
    return [process, overall_table, within_table, performance]


def report_charts(result, titled: bool = False) -> list[ChartSpec]:
    """The charts of one item, in the order of Minitab's Gage R&R report. The report leaves the title of the capability
    histogram to the page heading; the notes stay in the application."""
    if not result.valid:
        return []
    charts = [replace(spec, note="", title=spec.title if titled or result.method != "capability" else "")
              for spec in charts_for_result(result)]
    order = ("Components of Variation", "R Chart", "Measurement by Sample ID", "Xbar Chart", "Measurement by Operator",
             "Sample ID x Operator Interaction")
    return sorted(charts, key=lambda spec: order.index(spec.title) if spec.title in order else len(order))


def item_label(result) -> str:
    """The test item as a report names it: the tester and slot, without the operators that are listed in the tables."""
    parts = [p for p in result.system.split(" | ") if p and not p.startswith("Operators=")]
    return result.test_item + (f" [{' | '.join(parts)}]" if parts else "")


def failure(result) -> str:
    return "Analysis not available: " + "; ".join(i.message for i in result.issues if i.severity == "error")


def info_rows(result, context: ReportContext | None) -> list[tuple[str, str]]:
    """Gage name, Date of study, Reported by, Tolerance and Misc, as Minitab lists them: only what there is."""
    entered = dict(context.info) if context else {}
    rows = [(f"{label}:", entered[label]) for label in ("Gage name", "Date of study", "Reported by") if label in entered]
    tolerance = tolerance_of(result) if result.method == "grr" else None
    if tolerance is not None:
        rows.append(("Tolerance:", sig6(tolerance)))
    if "Misc" in entered:
        rows.append(("Misc:", entered["Misc"]))
    return rows


# ----------------------------------------------------------------------------- the application's own summary table
def summary_rows(results: Sequence, judged: bool = True) -> tuple[tuple[str, ...], list[tuple]]:
    """The summary table of the application. Without criteria (``judged=False``) it holds the statistics only."""
    if not results:
        raise ValueError("Run an analysis before exporting a report.")
    methods = {result.method for result in results}
    if len(methods) != 1:
        raise ValueError("A report must contain only one analysis method.")
    if results[0].method == "capability":
        headers = ("Test Item", "System", "N", "Mean", "Min", "Max", "Cp", "Cpk", "Pp", "Ppk", "Result")
        rows = [(r.test_item, r.system, r.n, r.mean, r.minimum, r.maximum,
                 *(r.metrics.get(key) for key in ("cp", "cpk", "pp", "ppk")), r.status) for r in results]
    else:
        headers = ("Test Item", "System", "%SV/Tol", "%Study Var", "NDC", "Acceptance Result", "Review", "Decision Metric")
        rows = [(r.test_item, r.system, *(r.metrics.get(key) for key in ("percent_tolerance", "percent_study_var", "ndc")),
                 r.status, review_note(r), metric_label(r.decision_metric)) for r in results]
    if not judged:
        keep = len(headers) - (1 if results[0].method == "capability" else 3)
        headers, rows = headers[:keep], [row[:keep] for row in rows]
    return headers, rows


def review_note(result) -> str:
    """Names the informational metrics that disagree with an acceptable decision (blank when none do)."""
    return ", ".join(METRIC_LABELS.get(key, key) for key in result.details.get("acceptance_conflicts", ()))


def _workbook_summary(results: Sequence) -> tuple[tuple[str, ...], list[tuple], tuple[str, ...]]:
    """One line per item for a workbook with several items: the figures Minitab reports, nothing else."""
    if results[0].method == "capability":
        return (("Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"),
                [(item_label(r), r.n, *(r.metrics.get(k) for k in ("cp", "cpk", "pp", "ppk"))) for r in results],
                ("text", "int", "idx", "idx", "idx", "idx"))
    rows = []
    for r in results:
        total, grr = r.metrics.get("variance_total"), r.metrics.get("variance_grr")
        rows.append((item_label(r), None if grr is None or not total else 100 * grr / total, r.metrics.get("percent_study_var"),
                     r.metrics.get("percent_tolerance"), r.metrics.get("ndc")))
    return (("Test Item", "%Contribution\n(Total Gage R&R)", "%Study Var", "%Tolerance", "NDC"), rows,
            ("text", "pct", "pct", "pct", "int"))


# ----------------------------------------------------------------------------- the same tables as text (the application's Details tab)
def _text_table(table: ReportTable, decimals: int) -> list[str]:
    head = [h.replace("\n", " ") for h in table.headers]
    cells = ([head] if any(head) else []) + table.cells(decimals)
    widths = [max(len(line[i]) for line in cells) for i in range(len(table.headers))]
    lines = ["  ".join(text.ljust(widths[i]) if table.kinds[i] == "text" else text.rjust(widths[i]) for i, text in enumerate(line))
             for line in cells]
    if any(head):
        lines.insert(1, "-" * len(lines[0]))
    return lines


def session_text(result, decimals: int = 2) -> str:
    """The results of one item as Minitab prints them. Everything comes from the finished analysis."""
    lines = [item_label(result), ""]
    if not result.valid:
        return "\n".join([*lines, failure(result)])
    if result.method == "grr":
        for table in grr_tables(result):
            lines += [table.title, *_text_table(table, decimals)]
            if table.note:
                lines.append(f"  {table.note}")
            lines.append("")
        lines.append(f"Number of Distinct Categories = {format_value(result.metrics.get('ndc'), 'int')}")
    else:
        lines.append("Process Capability")
        for table in capability_tables(result):
            lines += ["", table.title, *_text_table(table, decimals)]
        lines += ["", "The actual process spread is represented by 6 sigma."]
    issues = [i for i in result.issues if i.severity in ("warning", "error")]
    if issues:
        lines += ["", "Notes"] + [f"  {i.message}" for i in issues]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- Excel
def _excel_chart(ws, data_ws, spec: ChartSpec, start_col: int, anchor: str, size: tuple[float, float] = (16, 8.5)):
    from openpyxl.chart import BarChart, LineChart, Reference, ScatterChart, Series
    from openpyxl.chart.shapes import GraphicalProperties

    def write(cell, value):
        if isinstance(value, str):
            set_text(cell, value[:32767])
        else:
            cell.value = value

    if spec.categories:
        # Category charts retain actual Sample IDs and source labels in Excel.
        chart = BarChart() if spec.title == "Components of Variation" else LineChart()
        if isinstance(chart, BarChart):
            chart.type, chart.grouping, chart.overlap = "col", "clustered", 0
        chart.title, chart.x_axis.title, chart.y_axis.title = spec.title, spec.x_label, spec.y_label
        chart.style, chart.width, chart.height = 13, size[0], size[1]
        count, col = len(spec.categories), start_col
        write(data_ws.cell(1, col), "Category")
        for row, label in enumerate(spec.categories, 2):
            write(data_ws.cell(row, col), label)
        category_column = col
        for series in spec.series:
            if series.kind == "scatter":
                grouped: dict[int, list[float]] = {}
                for x, y in series.points:
                    grouped.setdefault(round(x), []).append(y)
                vectors = [[grouped.get(i + 1, [])[trial] if trial < len(grouped.get(i + 1, [])) else None
                            for i in range(count)] for trial in range(max(map(len, grouped.values()), default=0))]
            else:
                indexed = {round(x): y for x, y in series.points}
                if series.label in ("LCL", "CENTER", "UCL") and len(series.points) == 2 and series.points[0][1] == series.points[-1][1]:
                    indexed = dict.fromkeys(range(1, count + 1), series.points[0][1])
                vectors = [[indexed.get(i + 1) for i in range(count)]]
            for index, vector in enumerate(vectors):
                col += 1
                write(data_ws.cell(1, col), series.label + (f" {index + 1}" if len(vectors) > 1 else ""))
                for row, value in enumerate(vector, 2):
                    data_ws.cell(row, col, value)
                chart.add_data(Reference(data_ws, min_col=col, min_row=1, max_row=count + 1), titles_from_data=True)
                item = chart.series[-1]
                item.graphicalProperties.solidFill = series.color.lstrip("#")
                item.graphicalProperties.line.solidFill = series.color.lstrip("#")
                if series.kind == "scatter":
                    item.marker.symbol, item.marker.size = "circle", 4
                    item.marker.graphicalProperties.solidFill = series.color.lstrip("#")
                    item.graphicalProperties.line.noFill = True
        chart.set_categories(Reference(data_ws, min_col=category_column, min_row=2, max_row=count + 1))
        # Excel otherwise chooses its own label interval and may hide most serial numbers.
        chart.x_axis.tickLblSkip = 1
        chart.x_axis.tickMarkSkip = 1
        chart.x_axis.noMultiLvlLbl = True
        chart.x_axis.delete = False
        if spec.x_label == "Sample ID":
            from openpyxl.chart.text import RichText
            from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties, RichTextProperties

            chart.x_axis.txPr = RichText(
                bodyPr=RichTextProperties(rot=-2700000),
                p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(sz=650)))],
            )
        ws.add_chart(chart, anchor)
        return col + 1

    chart = ScatterChart()
    chart.title, chart.x_axis.title, chart.y_axis.title = spec.title, spec.x_label, spec.y_label
    chart.style, chart.width, chart.height = 13, size[0], size[1]
    col = start_col
    for series in spec.series:
        points = list(series.points)
        if series.kind == "bar" and points:
            # Density histogram as closed bin outlines on the same numeric x-axis as normal curves.
            spacing = min((b[0] - a[0] for a, b in zip(points, points[1:], strict=False) if b[0] > a[0]), default=1.0)
            points = [point for x, y in points for point in
                      ((x - spacing * .45, 0), (x - spacing * .45, y), (x + spacing * .45, y), (x + spacing * .45, 0))]
        if not points:
            continue
        write(data_ws.cell(1, col), series.label + " X")
        write(data_ws.cell(1, col + 1), series.label)
        for row, (x, y) in enumerate(points, 2):
            data_ws.cell(row, col, x)
            data_ws.cell(row, col + 1, y)
        item = Series(Reference(data_ws, min_col=col + 1, min_row=2, max_row=len(points) + 1),
                      Reference(data_ws, min_col=col, min_row=2, max_row=len(points) + 1), title=series.label)
        item.graphicalProperties = GraphicalProperties(ln=None)
        item.graphicalProperties.line.solidFill = series.color.lstrip("#")
        item.graphicalProperties.line.width = 18000
        if series.dash:
            item.graphicalProperties.line.dashStyle = "dash"
        if series.kind == "scatter":
            item.marker.symbol, item.marker.size = "circle", 4
            item.marker.graphicalProperties.solidFill = series.color.lstrip("#")
            item.graphicalProperties.line.noFill = True
        chart.series.append(item)
        col += 2
    ys = [y for series in spec.series for _, y in series.points]
    for label, value in spec.markers:
        write(data_ws.cell(1, col), label + " X")
        write(data_ws.cell(1, col + 1), label)
        for row, y in enumerate((0, max(ys, default=1)), 2):
            data_ws.cell(row, col, value)
            data_ws.cell(row, col + 1, y)
        item = Series(Reference(data_ws, min_col=col + 1, min_row=2, max_row=3),
                      Reference(data_ws, min_col=col, min_row=2, max_row=3), title=label)
        item.graphicalProperties.line.solidFill = "BD3434"
        item.graphicalProperties.line.dashStyle = "dash"
        chart.series.append(item)
        col += 2
    ws.add_chart(chart, anchor)
    return col


def _sheet_name(label: str, used: set[str]) -> str:
    base = "".join("_" if c in "[]:*?/\\" else c for c in label).strip() or "Item"
    name, number = base[:31], 1
    while name.casefold() in used:
        number += 1
        suffix = f" ({number})"
        name = base[:31 - len(suffix)] + suffix
    used.add(name.casefold())
    return name


def _write_table(ws, row: int, table: ReportTable, decimals: int) -> int:
    from openpyxl.styles import Alignment, Border, Font, Side

    if table.title:
        heading = ws.cell(row, 1)
        set_text(heading, table.title)
        heading.font = Font(name="Calibri", size=12, bold=True, color="0B5CAD")
        row += 1
    if any(table.headers):
        for col, text in enumerate(table.headers, 1):
            cell = ws.cell(row, col)
            set_text(cell, text)
            cell.font = Font(name="Calibri", size=10, bold=True)
            cell.alignment = Alignment(horizontal="left" if table.kinds[col - 1] == "text" else "right", vertical="bottom", wrap_text=True)
            cell.border = Border(bottom=Side(style="thin", color="404040"))
        ws.row_dimensions[row].height = 30 if any("\n" in h for h in table.headers) else 16
        row += 1
    for values in table.rows:
        for col, value in enumerate(values, 1):
            cell, kind = ws.cell(row, col), table.kinds[col - 1]
            cell.font = Font(name="Calibri", size=10)
            if value is None or (isinstance(value, float) and not math.isfinite(value)):
                cell.value, cell.alignment = "*", Alignment(horizontal="right")
            elif isinstance(value, str):
                set_text(cell, value)
                cell.alignment = Alignment(horizontal="left")
            else:
                cell.value = value  # the full value; only the display is formatted
                cell.number_format = _excel_format(value, kind, decimals)
                cell.alignment = Alignment(horizontal="right")
        row += 1
    if table.note:
        note = ws.cell(row, 1)
        set_text(note, table.note)
        note.font = Font(name="Calibri", size=9, italic=True, color="404040")
        row += 1
    return row + 1


def _export_xlsx(path: Path, results: Sequence, decimals: int, context: ReportContext | None):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    sections = _sections(context)
    workbook = Workbook()
    first = workbook.active
    used: set[str] = set()
    capability = results[0].method == "capability"
    if len(results) > 1:
        first.title = "Summary"
        used.add("summary")
        set_text(first["A1"], "Process Capability" if capability else "Variable Gage R&R")
        first["A1"].font = Font(name="Calibri", size=14, bold=True, color="0B5CAD")
        row = 2
        for label, value in context.info if context else ():
            set_text(first.cell(row, 1), f"{label}: {value}")
            row += 1
        headers, rows, kinds = _workbook_summary(results)
        _write_table(first, row + 1, ReportTable("", headers, tuple(rows), kinds), decimals)
        first.column_dimensions["A"].width = 34
        for letter in "BCDEF":
            first.column_dimensions[letter].width = 18
        first.sheet_view.showGridLines = False
    else:
        first.title = _sheet_name(item_label(results[0]), used)
    for index, result in enumerate(results):
        ws = first if len(results) == 1 else workbook.create_sheet(_sheet_name(item_label(result), used))
        heading = ws.cell(1, 1)
        set_text(heading, f"{'Process Capability Report for' if capability else 'Gage R&R for'} {item_label(result)}")
        heading.font = Font(name="Calibri", size=14, bold=True, color="0B5CAD")
        row = 2
        for label, value in info_rows(result, context):
            set_text(ws.cell(row, 1), label)
            ws.cell(row, 1).font = Font(name="Calibri", size=10, color="595959")
            set_text(ws.cell(row, 2), value)
            row += 1
        row += 1
        if not result.valid:
            set_text(ws.cell(row, 1), failure(result))
        else:
            for table in capability_tables(result) if capability else grr_tables(result):
                row = _write_table(ws, row, table, decimals)
            closing = ("The actual process spread is represented by 6 sigma." if capability else
                       f"Number of Distinct Categories = {format_value(result.metrics.get('ndc'), 'int')}")
            set_text(ws.cell(row, 1), closing)
            ws.cell(row, 1).font = Font(name="Calibri", size=10, bold=not capability, italic=capability)
        ws.column_dimensions["A"].width = 28
        for letter in "BCDEFG":
            ws.column_dimensions[letter].width = 16
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = "landscape"
        if "charts" in sections and result.valid:
            data_ws = workbook.create_sheet(_sheet_name(f"Plot data {index + 1}", used))
            data_ws.sheet_state = "hidden"
            column = 1
            for number, spec in enumerate(report_charts(result)):
                anchor = "I1" if capability else f"{'I' if number % 2 == 0 else 'R'}{1 + 17 * (number // 2)}"
                column = _excel_chart(ws, data_ws, spec, column, anchor, (18, 10) if capability else (16, 8.5))
    if "observations" in sections:
        raw = workbook.create_sheet(_sheet_name("Observations", used))
        for col, text in enumerate(("Test Item", "Sample ID", "Value", "LSL", "USL", "Trial", "Operator", "Source"), 1):
            set_text(raw.cell(1, col), text)
            raw.cell(1, col).font = Font(name="Calibri", size=10, bold=True)
        line = 2
        for result in results:
            for o in result.observations:
                for col, value in enumerate((result.label, o.sample_id, o.value, o.lsl, o.usl, o.trial, o.operator, o.source), 1):
                    if isinstance(value, str):
                        set_text(raw.cell(line, col), value[:32767])
                    else:
                        raw.cell(line, col, value)
                line += 1
        raw.freeze_panes = "A2"
    workbook.save(path)


# ----------------------------------------------------------------------------- PDF
@cache
def _pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Windows is the application's supported platform. Embed its standard Unicode font.
    normal = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    bold = normal.with_name("segoeuib.ttf")
    if normal.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("DataMapperText", str(normal)))
        pdfmetrics.registerFont(TTFont("DataMapperBold", str(bold)))
        pdfmetrics.registerFontFamily("DataMapperText", normal="DataMapperText", bold="DataMapperBold",
                                      italic="DataMapperText", boldItalic="DataMapperBold")
        return "DataMapperText", "DataMapperBold"
    return "Helvetica", "Helvetica-Bold"


def _pdf_table(table: ReportTable, decimals: int, fonts, size: float = 9):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    font, bold = fonts
    has_header = any(table.headers)
    data = ([list(table.headers)] if has_header else []) + table.cells(decimals)
    flow = Table(data, hAlign="LEFT")
    style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), size), ("LEADING", (0, 0), (-1, -1), size + 2.5),
             ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1F1F1F")), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
             ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    for col, kind in enumerate(table.kinds):
        style.append(("ALIGN", (col, 0), (col, -1), "LEFT" if kind == "text" else "RIGHT"))
    if has_header:
        style += [("FONTNAME", (0, 0), (-1, 0), bold), ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#404040"))]
    flow.setStyle(TableStyle(style))
    return flow


def _pdf_styles(fonts):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    font, bold = fonts
    return {
        "title": ParagraphStyle("Title", fontName=bold, fontSize=14, leading=18, textColor=colors.HexColor(BLUE), spaceAfter=4),
        "heading": ParagraphStyle("Heading", fontName=bold, fontSize=11.5, leading=15, textColor=colors.HexColor(BLUE),
                                  spaceBefore=11, spaceAfter=3),
        "body": ParagraphStyle("Body", fontName=font, fontSize=9, leading=12, textColor=colors.HexColor("#1F1F1F")),
        "note": ParagraphStyle("Note", fontName=font, fontSize=8, leading=10.5, textColor=colors.HexColor("#4A4A4A"), spaceBefore=3),
        "small": ParagraphStyle("Small", fontName=font, fontSize=8.5, leading=11, textColor=colors.HexColor("#595959")),
    }


def _info_flow(result, context, fonts):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    rows = info_rows(result, context)
    style = ParagraphStyle("StudyInfo", fontName=fonts[0], fontSize=9, leading=11)
    # Paragraphs wrap and split lengthy notes instead of overflowing a table cell.
    return [Paragraph(f'<font color="#595959">{escape(label)}</font> {escape(value)}', style) for label, value in rows]


def _chart_info_flow(result, context, fonts, width):
    """Compact Minitab-style study identification above the chart grid."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    entries = dict(info_rows(result, context))
    if len(entries.get("Misc:", "")) > 180:
        entries["Misc:"] = "See full notes on the statistics page."
    left = [(key, entries[key]) for key in ("Gage name:", "Date of study:") if key in entries]
    right = [(key, entries[key]) for key in ("Reported by:", "Tolerance:", "Misc:") if key in entries]
    if not left:
        left, right = right, []
    if not left and not right:
        return None
    style = ParagraphStyle("ChartStudyInfo", fontName=fonts[0], fontSize=8.5, leading=10.5)

    def entry(column, row):
        if row >= len(column):
            return ""
        label, value = column[row]
        return Paragraph(f"<b>{escape(label)}</b> {escape(value)}", style)

    flow = Table([[entry(left, row), entry(right, row)] for row in range(max(len(left), len(right)))],
                 colWidths=[width / 2] * 2, hAlign="LEFT")
    flow.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return flow


def _grr_chart_page(result, context, fonts, styles, specs, width, height):
    """Keep the four principal GRR charts, complete labels and study header on one page."""
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    header = [Paragraph(f"Gage R&amp;R (ANOVA) Report for {escape(item_label(result))}", styles["title"])]
    info = _chart_info_flow(result, context, fonts, width)
    if info is not None:
        header.append(info)
    header.append(Spacer(1, 8))
    header_height = sum(flow.wrap(width, height)[1] + flow.getSpaceBefore() + flow.getSpaceAfter() for flow in header)
    row_count = math.ceil(len(specs) / 2)
    row_height = min(240, (height - header_height - 10) / row_count)
    half = width / 2
    drawings = [reportlab_chart(spec, half - 10, row_height - 6, *fonts) for spec in specs]
    grid = [drawings[i:i + 2] + [""] * (2 - len(drawings[i:i + 2])) for i in range(0, len(drawings), 2)]
    table = Table(grid, colWidths=[half] * 2, rowHeights=[row_height] * row_count, hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return KeepTogether([*header, table])


def _grr_story(result, context, decimals, fonts, styles, width, charts, chart_size=None):
    from reportlab.platypus import NextPageTemplate, PageBreak, Paragraph, Spacer

    label = escape(item_label(result))
    story = [Paragraph(f"Gage R&amp;R for {label}", styles["title"])]
    story.extend(_info_flow(result, context, fonts))
    if not result.valid:
        return [*story, Spacer(1, 8), Paragraph(escape(failure(result)), styles["body"])]
    for table in grr_tables(result):
        story += [Paragraph(escape(table.title), styles["heading"]), _pdf_table(table, decimals, fonts)]
        if table.note:
            story.append(Paragraph(escape(table.note), styles["note"]))
    story += [Spacer(1, 8), Paragraph(f"Number of Distinct Categories = {format_value(result.metrics.get('ndc'), 'int')}", styles["body"])]
    specs = report_charts(result) if charts else []
    if specs:
        chart_width, chart_height = chart_size
        story += [NextPageTemplate("grr-charts"), PageBreak(),
                  _grr_chart_page(result, context, fonts, styles, specs[:4], chart_width, chart_height)]
        if len(specs) > 4:
            # Crossed studies retain their extra operator/interaction charts on the next page.
            story += [PageBreak(), _grr_chart_page(result, context, fonts, styles, specs[4:], chart_width, chart_height)]
        story.append(NextPageTemplate("grr-tables"))
    return story


def _capability_story(result, context, decimals, fonts, styles, width, charts):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    story = [Paragraph(f"Process Capability Report for {escape(item_label(result))}", styles["title"])]
    story.extend(_info_flow(result, context, fonts))
    if not result.valid:
        return [*story, Spacer(1, 8), Paragraph(escape(failure(result)), styles["body"])]
    process, overall, within, performance = capability_tables(result)

    def block(*tables):
        flows = []
        for table in tables:
            flows += [Paragraph(escape(table.title), styles["heading"]), _pdf_table(table, decimals, fonts)]
        return flows

    specs = report_charts(result) if charts else []
    chart = reportlab_chart(specs[0], width - 330, 225, *fonts) if specs else ""
    main = Table([[block(process), chart, block(overall, within)]], colWidths=[165, width - 330, 165], hAlign="LEFT")
    main.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return [*story, Spacer(1, 4), main, Spacer(1, 6), *block(performance), Spacer(1, 6),
            Paragraph("The actual process spread is represented by 6 sigma.", styles["note"])]


def _export_pdf(path: Path, results: Sequence, decimals: int, title: str, context: ReportContext | None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, SimpleDocTemplate

    capability = results[0].method == "capability"
    pagesize = landscape(A4) if capability else A4
    margin = 36
    doc_class = SimpleDocTemplate if capability else BaseDocTemplate
    document = doc_class(str(path), pagesize=pagesize, rightMargin=margin, leftMargin=margin, topMargin=margin,
                         bottomMargin=40, title=title, author="DataMapperX")
    fonts = _pdf_fonts()
    styles = _pdf_styles(fonts)
    width = pagesize[0] - 2 * margin
    charts = "charts" in _sections(context)
    story = []
    if context is not None and context.partial:
        story.append(Paragraph(f"Included {context.included} of {context.total} test items.", styles["small"]))
    chart_pagesize = landscape(A4)
    chart_size = (chart_pagesize[0] - 2 * margin - 12, chart_pagesize[1] - margin - 40 - 12)
    for index, result in enumerate(results):
        if index:
            story.append(PageBreak())
        if capability:
            story += _capability_story(result, context, decimals, fonts, styles, width, charts)
        else:
            story += _grr_story(result, context, decimals, fonts, styles, width, charts, chart_size)
    created = context.created if context and context.created else date.today().isoformat()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts[0], 7.5)
        canvas.setFillColor(colors.HexColor("#6B6B6B"))
        canvas.drawString(margin, 20, FOOTER)
        page_width = pagesize[0] if capability else doc.pageTemplate.pagesize[0]
        canvas.drawRightString(page_width - margin, 20, f"Created {created} · Page {doc.page}")
        canvas.restoreState()

    if capability:
        document.build(story, onFirstPage=footer, onLaterPages=footer)
    else:
        for name, size in (("grr-tables", A4), ("grr-charts", chart_pagesize)):
            frame = Frame(margin, 40, size[0] - 2 * margin, size[1] - margin - 40, id=name)
            document.addPageTemplates(PageTemplate(id=name, frames=[frame], pagesize=size, onPage=footer))
        document.build(story)


def export_statistical_report(path: str | Path, results: Sequence, *, decimals: int = 2,
                              title: str = "DataMapperX Statistical Report", context: ReportContext | None = None) -> Path:
    """Write a PDF or Excel report atomically, in the manner of Minitab's reports.

    Workbook cells keep the full value of every statistic; ``decimals`` only sets how many decimals the report shows.
    The caller owns choosing/confirming the destination using the existing app workflow.
    """
    if not results:
        raise ValueError("Run an analysis before exporting a report.")
    if len({result.method for result in results}) != 1:
        raise ValueError("A report must contain only one analysis method.")
    if not isinstance(decimals, int) or not 0 <= decimals <= 12:
        raise ValueError("Report precision must be an integer from 0 to 12.")
    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix not in (".pdf", ".xlsx"):
        raise ValueError("Statistical reports support .pdf and .xlsx files.")
    descriptor, temporary = tempfile.mkstemp(prefix=".datamapperx-stat-", suffix=suffix, dir=destination.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        if suffix == ".pdf":
            _export_pdf(temporary_path, results, decimals, title, context)
        else:
            _export_xlsx(temporary_path, results, decimals, context)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination
