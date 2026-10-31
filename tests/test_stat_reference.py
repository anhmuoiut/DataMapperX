"""Optional comparison with five Minitab FT studies, without redistributing company logs.

Expected aggregates were independently derived from centered sums of squares. PDF
values are rounded observations transcribed from the supplied rendered report. NDC
is not printed in that report, so its oracle is the independently verified formula.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from datamapperx.profiles import DEFAULT_PROFILES
from datamapperx.scanner import scan_folder
from datamapperx.statistics import AnalysisConfig, analyze, normalize_records

# This folder is ignored intentionally. A clean checkout runs synthetic tests and
# explicitly skips this customer-data comparison rather than inventing raw data.
DEFAULT_LOGS = Path(__file__).resolve().parents[1] / "samples" / "Function test logfile"
CASES = [
    ("DCDC5W, Meas Vin", {
        "mean": 349.9987345377604, "sigma_grr": 0.0008282772799702473,
        "sigma_part": 0.0012384759759256562, "sigma_total": 0.0014899214729172535,
        "variance_repeatability": 6.860432525149114e-7, "variance_part": 1.5338227429450067e-6,
        "variance_total": 2.219865995459918e-6, "study_var": 0.004969663679821484,
        "percent_tolerance": 0.1242415919955371, "percent_study_var": 55.59200904383823,
        "ndc": 2, "ss_part": 4.7587603332149374e-5, "ss_error": 1.3720865050298228e-5,
        "ms_part": 5.287511481349931e-6, "f": 7.70725673923162,
    }, {"tol": .12, "study": 55.59, "sigma": .0008283, "f": 7.70726, "f_step": .00001,
        "ss": (.0000476, .0000137, .0000613), "ms": (.0000053, .0000007),
        "var": (.0000007, .0000015, .0000022)}),
    ("DCDC5W, Meas 11V", {
        "mean": 12.234139666666668, "sigma_grr": 0.0006139679687627952,
        "sigma_part": 0.02072070261333161, "sigma_total": 0.020729796753870842,
        "variance_repeatability": 3.7695666666671275e-7, "variance_part": .0004293475167901274,
        "variance_total": .0004297244734567941, "study_var": .0036838078125767714,
        "percent_tolerance": .36838078125767715, "percent_study_var": 2.961765501382207,
        "ndc": 47, "ss_part": .01159577556333344, "ss_error": 7.5391333333342545e-6,
        "ms_part": .001288419507037049, "f": 3417.951242062018,
    }, {"tol": .37, "study": 2.96, "sigma": .0006140, "f": 3417.95, "f_step": .01,
        "ss": (.0115958, .0000075, .0116033), "ms": (.0012884, .0000004),
        "var": (.0000004, .0004293, .0004297)}),
    ("DCDC5W, Iin @ Load", {
        "mean": .022435439888582636, "sigma_grr": 9.31447496056645e-6,
        "sigma_part": 8.017060213158128e-5, "sigma_total": 8.070988099316789e-5,
        "variance_repeatability": 8.675944379101934e-11, "variance_part": 6.427325446140304e-9,
        "variance_total": 6.514084889931323e-9, "study_var": 5.58868497633987e-5,
        "percent_tolerance": .4139766649140643, "percent_study_var": 11.540687268953997,
        "ndc": 12, "ss_part": 1.743186220399074e-7, "ss_error": 1.735188875820387e-9,
        "ms_part": 1.9368735782211932e-8, "f": 223.24642639325947,
    }, {"tol": .41, "study": 11.54, "sigma": .0000093, "f": 223.246, "f_step": .001,
        "ss": (.0000002, .0000000, .0000002), "ms": (.0000000, .0000000),
        "var": (.0000000, .0000000, .0000000)}),
    ("DCDC5W, Iin @ No  Load", {
        "mean": .007065190614095754, "sigma_grr": 1.0621501397261909e-5,
        "sigma_part": .00021141968673936792, "sigma_total": .00021168632509660254,
        "variance_repeatability": 1.1281629193203668e-10, "variance_part": 4.469828394097246e-8,
        "variance_total": 4.48111002329045e-8, "study_var": 6.372900838357145e-5,
        "percent_tolerance": .32681542760805876, "percent_study_var": 5.017566152378908,
        "ndc": 28, "ss_part": 1.2078690130336448e-6, "ss_error": 2.2563258386407337e-9,
        "ms_part": 1.3420766811484943e-7, "f": 1189.6124736638167,
    }, {"tol": .33, "study": 5.02, "sigma": .0000106, "f": 1189.61, "f_step": .01,
        "ss": (.0000012, .0000000, .0000012), "ms": (.0000001, .0000000),
        "var": (.0000000, .0000000, .0000000)}),
    ("DCDC5W, Iout", {
        "mean": .4074859173473828, "sigma_grr": 9.12181012483411e-6,
        "sigma_part": 4.3565439229957724e-5, "sigma_total": 4.4510166425802825e-5,
        "variance_repeatability": 8.32074199535261e-11, "variance_part": 1.8979474952991393e-9,
        "variance_total": 1.9811549152526652e-9, "study_var": 5.4730860749004664e-5,
        "percent_tolerance": .2736543037450238, "percent_study_var": 20.493767732906385,
        "ndc": 6, "ss_part": 5.1993449152658493e-8, "ss_error": 1.664148399070522e-9,
        "ms_part": 5.777049905850943e-9, "f": 69.42950411246501,
    }, {"tol": .27, "study": 20.49, "sigma": .0000091, "f": 69.4295, "f_step": .0001,
        "ss": (.0000001, .0000000, .0000001), "ms": (.0000000, .0000000),
        "var": (.0000000, .0000000, .0000000)}),
]


@pytest.fixture(scope="module")
def reference_results():
    folder = Path(os.environ.get("DATAMAPPERX_REFERENCE_LOGS", str(DEFAULT_LOGS)))
    if not folder.is_dir():
        pytest.skip("Confidential FT reference logs are unavailable; see docs/statistical-validation.md")
    scanned = scan_folder(folder, DEFAULT_PROFILES["Function Test Log"])
    assert not scanned.parse_warnings, scanned.parse_warnings
    assert scanned.total_sns == 10 and scanned.total_files == 30
    results = analyze(normalize_records(scanned.grouped, [case[0] for case in CASES], assign_trials=True),
                      AnalysisConfig(method="grr", profile="SolarEdge", expected_repeats=3))
    return {result.test_item: result for result in results}


def _close(actual, expected, metric):
    relative = float(os.environ.get("DATAMAPPERX_REFERENCE_REL_TOL", "1e-9"))
    absolute = float(os.environ.get("DATAMAPPERX_REFERENCE_ABS_TOL", "1e-18"))
    assert actual is not None, f"{metric}: expected {expected!r}, actual is N/A"
    difference = abs(actual - expected)
    assert math.isclose(actual, expected, rel_tol=relative, abs_tol=absolute), (
        f"{metric}: actual={actual:.17g}, expected={expected:.17g}, absolute difference={difference:.17g}; "
        f"rel_tol={relative}, abs_tol={absolute}"
    )


def _printed(actual, printed, step, metric):
    difference = abs(actual - printed)
    assert difference <= step / 2 + step * 1e-10, (
        f"{metric}: actual={actual:.17g}, printed={printed:.17g}, absolute difference={difference:.17g}; "
        f"allowed half last printed unit={step / 2}"
    )


@pytest.mark.parametrize("item,expected,printed", CASES, ids=[case[0] for case in CASES])
def test_raw_ft_against_independent_aggregates(reference_results, item, expected, printed):
    result = reference_results[item]
    assert result.valid, [str(issue) for issue in result.issues]
    assert (result.n, result.parts, result.repeats) == (30, 10, 3)
    assert result.status == "PASS" and result.decision_metric == "percent_tolerance"
    _close(result.mean, expected["mean"], f"{item}: mean")
    for key in ("sigma_grr", "sigma_part", "sigma_total", "variance_repeatability", "variance_part",
                "variance_total", "study_var", "percent_tolerance", "percent_study_var"):
        _close(result.metrics[key], expected[key], f"{item}: {key}")
    assert result.metrics["ndc"] == expected["ndc"]
    part, error, total = result.details["anova"]
    assert (part["df"], error["df"], total["df"]) == (9, 20, 29)
    _close(part["ss"], expected["ss_part"], f"{item}: SS Part")
    _close(error["ss"], expected["ss_error"], f"{item}: SS Error")
    _close(part["ms"], expected["ms_part"], f"{item}: MS Part")
    _close(error["ms"], expected["variance_repeatability"], f"{item}: MS Error")
    _close(part["f"], expected["f"], f"{item}: F")
    assert 0 <= part["p"] < .0005  # report prints 0.000, rather than exactly zero


@pytest.mark.parametrize("item,expected,printed", CASES, ids=[case[0] for case in CASES])
def test_raw_ft_matches_available_minitab_printed_precision(reference_results, item, expected, printed):
    result = reference_results[item]
    _printed(result.metrics["percent_tolerance"], printed["tol"], .01, f"{item}: PDF %SV/Tol")
    _printed(result.metrics["percent_study_var"], printed["study"], .01, f"{item}: PDF %StudyVar")
    _printed(result.metrics["sigma_grr"], printed["sigma"], 1e-7, f"{item}: PDF sigma GRR")
    anova = result.details["anova"]
    _printed(anova[0]["f"], printed["f"], printed["f_step"], f"{item}: PDF F")
    for row, value in zip(anova, printed["ss"], strict=True):
        _printed(row["ss"], value, 1e-7, f"{item}: PDF SS {row['source']}")
    for row, value in zip(anova[:2], printed["ms"], strict=True):
        _printed(row["ms"], value, 1e-7, f"{item}: PDF MS {row['source']}")
    for key, value in zip(("variance_repeatability", "variance_part", "variance_total"), printed["var"], strict=True):
        _printed(result.metrics[key], value, 1e-7, f"{item}: PDF {key}")


def test_vin_reference_control_limits(reference_results):
    result = reference_results["DCDC5W, Meas Vin"]
    _printed(result.details["r_limits"]["center"], .001212, .000001, "Vin PDF Rbar")
    _printed(result.details["r_limits"]["ucl"], .003119, .000001, "Vin PDF R UCL")
    _printed(result.details["xbar_limits"]["lcl"], 349.997495, .000001, "Vin PDF Xbar LCL")
    _printed(result.details["xbar_limits"]["ucl"], 349.999974, .000001, "Vin PDF Xbar UCL")
