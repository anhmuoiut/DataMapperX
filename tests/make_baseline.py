"""Write the Phase 0 regression baselines. Run once, on the pre-Phase-0 code:  python -m tests.make_baseline

This records current behaviour (statistics results with everything consumers see, and the RawData workbook). Do not run
it again to make a failing regression test pass: a difference is a behaviour change that needs an explicit decision.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from datamapperx.statistics import analyze, explain_method

from .baseline_support import (
    build_cases,
    build_config_error_cases,
    build_explain_cases,
    config_from_dict,
    dumps,
    observation_from_dict,
    rawdata_signature,
    result_signature,
)

FIXTURES = Path(__file__).parent / "fixtures" / "baseline"


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    for case in cases:
        observations = [observation_from_dict(item) for item in case["observations"]]
        case["expected"] = [result_signature(r) for r in analyze(observations, config_from_dict(case["config"]))]
    errors = build_config_error_cases()
    for case in errors:
        try:
            analyze([], config_from_dict(case["config"]))
        except ValueError as exc:
            case["message"] = str(exc)
        else:
            case["message"] = None
    explains = build_explain_cases()
    for case in explains:
        case["text"] = explain_method(config_from_dict(case["config"]))
    meta = {"generated": date.today().isoformat(), "note": "Pre-Phase-0 behaviour, not a Minitab verification.",
            "cases": len(cases)}
    (FIXTURES / "analyze_baseline.json").write_text(
        dumps({"meta": meta, "cases": cases, "config_errors": errors, "explain": explains}), encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        signature = rawdata_signature(Path(folder))
    (FIXTURES / "rawdata_baseline.json").write_text(dumps({"meta": meta, "signature": signature}), encoding="utf-8")
    print(f"{len(cases)} analysis cases, {len(errors)} config errors, {len(explains)} explanations, "
          f"{len(signature['cells'])} workbook cells -> {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
