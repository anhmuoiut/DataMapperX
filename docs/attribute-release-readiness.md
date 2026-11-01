# Attribute Agreement: release readiness

State on 2026-11-01 (P5). `ATTRIBUTE_RESULTS_READY` and `ATTRIBUTE_REPORTS_READY` (`datamapperx/ui/validation_workspace.py`) are **False**. The method is **not** marked Minitab-verified: `METHOD_VERIFICATION["attribute_agreement"]` stays "Pending Minitab Verification" while the Assessment Disagreement table has not been compared with Minitab output that comes with its raw data.

## Matrix

"Pending" means nothing against it has been found; it has not been done. GUI = the one-time check in the real window (`docs/attribute-gui-verification.md`). Minitab = compared with output Minitab itself printed (`docs/attribute-minitab-comparison.md`).

| Feature | Automated tests | GUI verified | Minitab compared | Release ready |
|---|---|---|---|---|
| Ratings import (CSV/XLSX, column and category mapping, preview) | Yes | Pending (A) | n/a (an input format) | No: needs the GUI check |
| Percent agreement and exact interval: Within, vs Standard, Between, All vs Standard | Yes | Pending (C, D) | **Yes**: 50 printed figures of Minitab's Textile example, and 30/30, 50/50, 47/50, 37/50. The interval at 0 % is not compared yet | Yes after the GUI check |
| Fleiss' kappa, SE, Z, P: Within, vs Standard, Between, All vs Standard | Yes | Pending (D) | **Yes**: 240 printed figures (5 responses). Two responses with imperfect agreement: not compared yet | Yes after the GUI check |
| Assessment Disagreement table: #Pass/Fail, #Fail/Pass, #Mixed, each with its Percent (per sample, once; divisors: Standard-Fail samples, Standard-Pass samples, all samples; N/A without a base) | Yes (independent count of 150 random studies, hand-counted studies, screen = PDF = workbook) | Pending (D) | **Partly**: Minitab's definitions and one published example (#Pass/Fail 1 = 25.00, #Mixed 1 = 10.00, the book's data not readable). #Fail/Pass divisor, N/A cells, one trial, other labels: not compared. Nine studies are ready to run in Minitab | Matches the definitions; **compare the nine studies before the reports are released** |
| Results table, Details, Checks, summary line | Yes (the real Qt workspace, headless, with ten sample files) | Pending (C, D, E) | n/a | Yes after the GUI check |
| Assessment Agreement charts | Yes (chart data, drawn primitives, panel layout) | Pending (F, light and dark, window sizes) | n/a (they draw the figures above) | Yes after the GUI check |
| PDF report | Yes; 19 files open under strict pypdf and Ghostscript with no warning; pages looked at | Pending (opened in a PDF viewer) | n/a | Yes after the viewer check |
| Excel report | Yes; 19 files pass zip, XML, content-type, relationship and chart-element-order checks and reload in openpyxl | Pending (opened in Excel) | n/a | Yes after the Excel check |
| Acceptance (optional, off by default) | Yes | Pending (B, C) | n/a (the user's criterion) | Yes after the GUI check |
| Switching methods; Gage R&R and Capability unchanged | Yes (numbers and views in the Qt workspace, headless; baseline fixtures pinned by hash) | Pending (H, I) | existing references | Yes after the GUI check |

## Recommendation

1. Keep both flags False until the checklist has been done in the real window and nothing differs from "expected".
2. Then turn **`ATTRIBUTE_RESULTS_READY`** on first (sections A to F, H and I). The Assessment Disagreement table follows Minitab's definitions and one published example; its edge cases are listed in `docs/attribute-minitab-comparison.md` and the method still says "Pending Minitab Verification".
3. Turn **`ATTRIBUTE_REPORTS_READY`** on after section G, which includes opening a PDF and a workbook in the real applications, and after the nine disagreement studies have been compared with Minitab (the reports print that table). The tests that assert the flags are off (`tests/test_attribute_setup.py`, `tests/test_attribute_results.py`) change with them.
4. Running the nine studies in Minitab is not needed to show the results on screen. It is needed before the reports are released and before the method may be called verified.

## Known limitations

* Assessment Disagreement: the divisor of #Fail/Pass, the N/A cell, a single trial and responses other than Pass and Fail are unverified (`docs/attribute-minitab-comparison.md`). Kendall's coefficients, Cohen's kappa and ordered categories are out of scope.
* Nothing was opened in Excel, a PDF viewer or the real window on screen by the automated checks. The workbooks were not validated against the ECMA-376 schemas (the sequence of the elements of the chart parts was).
* With about ten or more appraisers with long names, on a high-resolution screen, in a very small window, the rotated names on the agreement graph can touch each other. The panel is made tall enough for its plot (`agreement_extra_height`), and the canvas scrolls; widening the window removes the crowding. The label spacing is planned by shared code (`_category_plan`) that the Gage R&R charts also use, and was left alone.
* Qt: the ownership rule every widget follows is in `docs/qt-widget-ownership.md`; `tests/ui/test_ownership.py` checks it.

## Commands

```
python -m pytest tests                                  # everything; the window tests run headless on Qt's offscreen platform
.venv/bin/ruff check .
DATAMAPPERX_ATTRIBUTE_RESULTS=1 DATAMAPPERX_ATTRIBUTE_REPORTS=1 .venv/bin/python main.py   # opens the window: the one-time check
```

`tests/test_ui.py` builds real windows and takes the keyboard focus; run it when that does not matter. Baseline fixtures: `tests/test_baseline_integrity.py` pins the Git blob hash and the SHA-256 of both files (`git ls-files -s tests/fixtures` shows the same blob hashes).
