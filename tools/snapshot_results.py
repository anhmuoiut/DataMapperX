"""Record, and later compare, everything the program produces from one folder of real logs.

Usage::

    python tools/snapshot_results.py snapshot --logs <folder> --profile "Function Test Log" --out <new folder> \
        [--rawdata <RawData.xlsx>] [--repeats 3]
    python tools/snapshot_results.py compare <snapshot A> <snapshot B> [--rel-tol 1e-12]

``snapshot`` runs the same path the application uses (scan, normalise, Variable Gage R&R and Process Capability, the
Study pipeline, the PDF and Excel reports, the raw Excel export and, if given, the RawData.xlsx import) and writes
``snapshot.json`` plus the generated files. Nothing is read from or written to the log folder, and ``--out`` must be a
new or empty folder outside it. Run it before a change and after it on the same logs, then ``compare``: numbers may
differ only within ``--rel-tol`` (default 1e-12); text, integers, key order and structure must match exactly.

The logs are often confidential and are never copied anywhere by this tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.baseline_support import first_difference, result_signature  # noqa: E402

GAGE = "SNAPSHOT"


def _excel_cells(path: Path) -> dict:
    from openpyxl import load_workbook

    book = load_workbook(path)
    try:
        return {sheet.title: [[None if cell is None else (cell if isinstance(cell, (int, float, str)) else str(cell))
                               for cell in row] for row in sheet.iter_rows(values_only=True)] for sheet in book.worksheets}
    finally:
        book.close()


def _pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


def _study_reports(observations, method: str, repeats: int | None, out: Path, tag: str) -> dict:
    from datamapperx.stat_reports import export_statistical_report, report_context
    from datamapperx.statistics import Dataset, StatisticalOptions, Study, StudyInfo

    dataset = Dataset.from_observations(observations, description=f"snapshot {tag}")
    options = StatisticalOptions(method=method, assign_trials=True, expected_repeats=repeats if method == "grr" else None)
    study = Study(dataset, options=options, info=StudyInfo(gage_name=GAGE))
    result_set = study.run_statistics()
    evaluated = study.evaluate(result_set, judge=False)
    context = report_context(study, result_set)
    results = list(evaluated.results)
    pdf = export_statistical_report(out / f"{tag}_report.pdf", results, context=context)
    xlsx = export_statistical_report(out / f"{tag}_report.xlsx", results, context=context)
    return {"items": len(results), "signatures": [result_signature(result) for result in results],
            "pdf_pages": _pdf_pages(pdf), "xlsx": _excel_cells(xlsx), "dataset_fingerprint": dataset.fingerprint}


def snapshot(args: argparse.Namespace) -> int:
    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder
    from datamapperx.statistics import AnalysisConfig, analyze, import_rawdata_xlsx, normalize_records

    logs, out = Path(args.logs).resolve(), Path(args.out).resolve()
    if not logs.is_dir():
        sys.exit(f"Not a folder: {logs}")
    if out == logs or logs in out.parents or out in logs.parents:
        sys.exit("--out must be outside the log folder (and not contain it).")
    if out.exists() and any(out.iterdir()):
        sys.exit(f"--out must be new or empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    scanned = scan_folder(logs, DEFAULT_PROFILES[args.profile])
    components = list(scanned.components)
    observations = normalize_records(scanned.grouped, components, assign_trials=True)
    data: dict = {
        "scan": {"profile": args.profile, "serial_numbers": scanned.total_sns, "files": scanned.total_files,
                 "components": components, "warnings": list(scanned.parse_warnings), "observations": len(observations)},
        "engine_grr": [result_signature(r) for r in analyze(
            observations, AnalysisConfig(method="grr", profile="SolarEdge", expected_repeats=args.repeats))],
        "engine_capability": [result_signature(r) for r in analyze(observations, AnalysisConfig())],
        "study_grr": _study_reports(observations, "grr", args.repeats, out, "grr"),
        "study_capability": _study_reports(observations, "capability", None, out, "capability"),
    }
    raw_path = out / "RawData_export.xlsx"
    generate_excel(scanned.grouped, components, raw_path, args.repeats)
    data["raw_export"] = _excel_cells(raw_path)

    if args.rawdata:
        imported = import_rawdata_xlsx(args.rawdata)
        results = analyze(list(imported.dataset.observations),
                          AnalysisConfig(method="grr", profile="SolarEdge", expected_repeats=args.repeats, assign_trials=True))
        data["rawdata_import"] = {"items": list(imported.items), "samples": imported.samples, "rows": imported.rows,
                                  "warnings": list(imported.warnings), "grr": [result_signature(r) for r in results]}

    (out / "snapshot.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"snapshot written to {out}")
    print(f"  {scanned.total_sns} serial numbers, {scanned.total_files} files, {len(components)} components")
    for key in ("engine_grr", "engine_capability"):
        valid = sum(1 for sig in data[key] if sig["valid"])
        print(f"  {key}: {len(data[key])} results, {valid} valid")
    return 0


def compare(args: argparse.Namespace) -> int:
    left = json.loads((Path(args.a) / "snapshot.json").read_text(encoding="utf-8"))
    right = json.loads((Path(args.b) / "snapshot.json").read_text(encoding="utf-8"))
    worst = 0
    for key in left:
        if key not in right:
            print(f"DIFF  {key}: missing from B")
            worst = 1
            continue
        found = first_difference(left[key], right[key], f"$.{key}", rel_tol=args.rel_tol)
        print(f"{'DIFF' if found else 'same'}  {key}" + (f": {found}" if found else ""))
        worst = worst or (1 if found else 0)
    for key in right:
        if key not in left:
            print(f"DIFF  {key}: missing from A")
            worst = 1
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--logs", required=True)
    snap.add_argument("--profile", default="Function Test Log")
    snap.add_argument("--out", required=True)
    snap.add_argument("--rawdata")
    snap.add_argument("--repeats", type=int, default=3)
    comp = sub.add_parser("compare")
    comp.add_argument("a")
    comp.add_argument("b")
    comp.add_argument("--rel-tol", type=float, default=1e-12)
    args = parser.parse_args(argv)
    return snapshot(args) if args.command == "snapshot" else compare(args)


if __name__ == "__main__":
    sys.exit(main())
