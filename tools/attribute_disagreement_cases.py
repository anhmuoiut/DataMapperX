"""Controlled Pass/Fail studies for comparing Minitab's Assessment Disagreement table with DataMapperX.

Usage: python tools/attribute_disagreement_cases.py [folder]     (default: samples/attribute_minitab)

It writes one CSV per study (Samples, Appraisers, Measurements, Standard: the long format that Minitab's "Attribute column"
arrangement and the DataMapperX import both read) and prints, for every study, what DataMapperX shows in Minitab's layout, so the
Session window of Minitab can be set beside it. Every count is also made by a second, independent count straight from the
definition, and the program stops if the two differ. Nothing printed here is a Minitab result.

The rule being compared (docs/attribute-minitab-comparison.md): each sample of an appraiser is counted once, as #Pass/Fail (every
trial Pass, Standard Fail), #Fail/Pass (every trial Fail, Standard Pass) or #Mixed (the trials differ); the percents divide by the
samples whose Standard is Fail, the samples whose Standard is Pass, and all samples.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datamapperx.stat_reports import DISAGREEMENT_NA, attribute_details  # noqa: E402
from datamapperx.statistics import AnalysisConfig, Observation, analyze  # noqa: E402

PASS, FAIL, TRIALS = "Pass", "Fail", 3
SAMPLES = 24
STANDARD = {f"S{n:02d}": PASS if n <= 14 else FAIL for n in range(1, SAMPLES + 1)}  # 14 Pass and 10 Fail: the three bases differ
ALL_PASS = dict.fromkeys(STANDARD, PASS)  # no reference Fail at all


def rated(changes: dict[int, str] | None = None, standard: dict[str, str] | None = None) -> dict[str, tuple[str, ...]]:
    """Every sample rated as its Standard says, three times, except the numbered samples in ``changes`` ("PFP" = Pass, Fail, Pass)."""
    word = {"P": PASS, "F": FAIL}
    table = {sample: (value,) * TRIALS for sample, value in (standard or STANDARD).items()}
    for number, trials in (changes or {}).items():
        table[f"S{number:02d}"] = tuple(word[letter] for letter in trials)
    return table


MULTIPLE_ERRORS = {15: "PPP", 16: "PPP", 17: "PPP", 1: "FFF", 2: "FFF", 3: "PFP", 4: "FFP", 18: "FPF", 19: "PPF"}

# name: (the Standard of each sample, or None when it is not given; the trials of each appraiser)
CASES: dict[str, tuple[dict[str, str] | None, dict[str, dict[str, tuple[str, ...]]]]] = {
    "A_perfect_agreement": (STANDARD, {"Ann": rated()}),
    "B_consistent_false_pass": (STANDARD, {"Ann": rated({15: "PPP", 16: "PPP", 17: "PPP"})}),  # Fail samples always rated Pass
    "C_consistent_false_fail": (STANDARD, {"Ann": rated({1: "FFF", 2: "FFF"})}),  # Pass samples always rated Fail
    "D_mixed_repeated_ratings": (STANDARD, {"Ann": rated({3: "PFP", 4: "FFP", 18: "FPF", 19: "PPF"})}),  # one or two trials wrong, never all
    "E_multiple_error_types": (STANDARD, {"Ann": rated(MULTIPLE_ERRORS)}),
    "F_multiple_appraisers": (STANDARD, {"Ann": rated(MULTIPLE_ERRORS), "Ben": rated({n: "PPP" for n in range(15, 25)}), "Carla": rated()}),
    "G_missing_standard": (None, {"Ann": rated({3: "FFF", 15: "PPP", 4: "PFP"})}),  # no Standard column values: no table
    "H_one_reference_category_absent": (ALL_PASS, {"Ann": rated({3: "FFF", 7: "PFP"}, ALL_PASS)}),  # no Standard Fail: #Pass/Fail has no base
    "I_every_sample_always_wrong": (STANDARD, {"Ann": rated({n: "FFF" if STANDARD[f"S{n:02d}"] == PASS else "PPP" for n in range(1, SAMPLES + 1)})}),
}


def rows(name: str) -> list[tuple[str, str, str, str]]:
    standard, appraisers = CASES[name]
    return [(sample, who, rating, (standard or {}).get(sample, "")) for who, table in appraisers.items() for sample, trials in table.items()
            for rating in trials]


def write_cases(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in CASES:
        path = folder / f"{name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["Samples", "Appraisers", "Measurements", "Standard"])
            writer.writerows(rows(name))
        paths.append(path)
    return paths


def counted(table: dict[str, tuple[str, ...]], standard: dict[str, str]) -> list[tuple[int, int | None]]:
    """(count, base) of #Pass/Fail, #Fail/Pass and #Mixed of one appraiser, counted straight from the definition."""
    false_pass = false_fail = mixed = 0
    for sample, trials in table.items():
        if any(trial != trials[0] for trial in trials):
            mixed += 1
        elif trials[0] == PASS and standard[sample] == FAIL:
            false_pass += 1
        elif trials[0] == FAIL and standard[sample] == PASS:
            false_fail += 1
    return [(false_pass, sum(s == FAIL for s in standard.values())), (false_fail, sum(s == PASS for s in standard.values())), (mixed, len(table))]


def analysed(name: str):
    standard, appraisers = CASES[name]
    observations = [Observation("Case", sample, rating, trial=str(trial), operator=who, standard=(standard or {}).get(sample, ""))
                    for who, table in appraisers.items() for sample, trials in table.items() for trial, rating in enumerate(trials, 1)]
    result, = analyze(observations, AnalysisConfig(method="attribute"))
    return result


def check(name: str, result) -> None:
    """Stop when the application's counts are not the independent ones."""
    standard, appraisers = CASES[name]
    for who, item in zip(appraisers, result.details["appraisers"], strict=True):
        if standard is None or item["disagreement"] is None:
            assert standard is None, (name, who)
            continue
        shown = [(c["count"], c["base"]) for c in item["disagreement"]["columns"]]
        assert shown == counted(appraisers[who], standard), (name, who, shown)


def describe() -> str:
    lines = [f"{SAMPLES} samples: {sum(s == PASS for s in STANDARD.values())} with Standard Pass (S01-S14) and "
             f"{sum(s == FAIL for s in STANDARD.values())} with Standard Fail (S15-S24); {TRIALS} trials each.", ""]
    for name in CASES:
        result = analysed(name)
        check(name, result)
        standard, appraisers = CASES[name]
        tables, notes = attribute_details(result, 2)
        lines.append(f"{name}  (Standard: {'none' if standard is None else 'all Pass' if standard is ALL_PASS else 'S01-S14 Pass, S15-S24 Fail'})")
        table = next((t for t in tables if t.title == "Assessment Disagreement"), None)
        if table is None:
            lines += ["  no Assessment Disagreement table (needs a known Standard and exactly two responses)", ""]
            continue
        widths = [max(len(str(cell)) for cell in column) for column in zip(table.headers, *table.rows, strict=True)]
        for row in (table.headers, *table.rows):
            lines.append("  " + "  ".join(str(cell).ljust(width) if i == 0 else str(cell).rjust(width) for i, (cell, width) in enumerate(zip(row, widths, strict=True))))
        lines += [f"  {note}" for note in notes if note == DISAGREEMENT_NA]
        item = result.details["appraisers"][0]
        lines.append(f"  (Appraiser {item['label']}: Within {item['within']['percent']:.2f} ({item['within']['lower']:.2f}, {item['within']['upper']:.2f}); "
                     f"vs Standard {item['standard']['percent']:.2f} ({item['standard']['lower']:.2f}, {item['standard']['upper']:.2f}))")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else ROOT / "samples" / "attribute_minitab"
    for path in write_cases(folder):
        print(f"wrote {path}")
    print()
    print(describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
