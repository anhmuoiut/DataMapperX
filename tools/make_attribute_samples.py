"""Write the ten sample files of the one-time Attribute Agreement check in the real window (docs/attribute-gui-verification.md).

Usage: python tools/make_attribute_samples.py [folder]      (default: samples/attribute_gui)

``samples/`` is not part of the repository. The files are synthetic: 30 samples (the first half Standard PASS, the second half
FAIL) rated three times, with the mistakes named in the checklist.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADERS = ["Samples", "Appraisers", "Measurements", "Standard"]


def table(appraisers=("1",), trials=3, samples=30, wrong=(), standard=True, labels=("PASS", "FAIL"), unusable=False):
    """One row per assessment: (sample, appraiser, rating, standard). ``wrong`` holds (appraiser, sample number, trial) that are
    rated the other way; ``unusable`` leaves the Standard of sample 5 empty."""
    rows = []
    for who in appraisers:
        for n in range(1, samples + 1):
            truth = labels[0] if n <= samples // 2 else labels[1]
            other = labels[1] if truth == labels[0] else labels[0]
            for t in range(1, trials + 1):
                std = truth if standard and not (unusable and n == 5) else ""
                rows.append((f"VSEG{n:06d}", who, other if (who, n, t) in wrong else truth, std))
    return rows


LONG_NAMES = ("Maria Gonzalez-Hernandez", "Ng", "Operator 03 (night shift)", "Bartholomew Featherstonehaugh", "Li", "Appraiser-0006",
              "Xiaoming Zhang-Wei", "Jo", "Fatima Al-Mansouri", "Operator 10", "Zdzislaw Przybylski", "A")


def twelve_long_names():
    """Twelve appraisers with names of 1 to 29 characters: some consistently wrong on a few samples, some wrong in one trial."""
    consistent = {(LONG_NAMES[k], n, t) for k in (1, 4, 7, 10) for n in range(1, 3 + k) for t in (1, 2, 3)}
    once = {(LONG_NAMES[k], n, 1) for k in (2, 5, 8) for n in range(5, 7 + k)}
    return table(LONG_NAMES, wrong=consistent | once)


def studies() -> dict[str, list[tuple[str, str, str, str]]]:
    return {
        "1_reference": table(),
        "2_one_inconsistent_sample": table(wrong={("1", 4, 2)}),
        "3_three_appraisers": table(("Ann", "Ben", "Carla"), wrong={("Ben", n, 1) for n in range(1, 6)}
                                    | {("Carla", n, t) for n in range(1, 20) for t in (1, 2, 3)}),
        "4_no_standard": table(standard=False),
        "5_unusable_standard": table(unusable=True),
        "6_single_trial": table(trials=1),
        "7_labels_P_F": table(labels=("P", "F")),
        "8_one_category": [(s, a, "PASS", "PASS") for s, a, _rating, _standard in table()],
        "10_twelve_long_names": twelve_long_names(),
    }


def write_samples(folder: Path) -> list[Path]:
    from openpyxl import Workbook

    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in studies().items():
        path = folder / f"{name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        paths.append(path)
    book = Workbook()
    sheet = book.active
    sheet.title = "Ratings"
    sheet.append(HEADERS)
    for row in table(wrong={("1", 4, 2)}):
        sheet.append(list(row))
    notes = book.create_sheet("Notes")
    notes.append(["not ratings", "x"])
    notes.append(["a", "b"])
    book.create_sheet("Empty")
    path = folder / "9_workbook_two_sheets.xlsx"
    book.save(path)
    return [*paths, path]


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else ROOT / "samples" / "attribute_gui"
    for path in write_samples(folder):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
