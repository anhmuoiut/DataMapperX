# Attribute Agreement: status and release readiness

State on 2026-11-02. This file separates three things that must not be mixed up: what **the owner has stated**, what **the repository
shows** (tests, reference files, measurements), and what **the code still says**.

## 1. Status

| | State |
|---|---|
| **Owner validation** | On 2026-11-02 the owner stated that the Attribute Agreement method has been validated and works similarly to Minitab. The repository holds no record of it: the checklist in `docs/attribute-gui-verification.md` was not filled in and no Minitab session output other than the Textile example (`tests/reference/`) was added. Nothing here claims more than the statement |
| **Release flags** `ATTRIBUTE_RESULTS_READY`, `ATTRIBUTE_REPORTS_READY` (`datamapperx/ui/validation_workspace.py`, lines 125-126) | `False` in the last commit (`aeee0fd`). **`True` in the working tree**, a staged change made by the owner, not yet committed. With `True` the window runs Attribute Agreement and makes its reports without the two environment variables. The comments on those lines ("stays False until...") are out of date |
| **Tests that assert the old state** | 5 fail because of the staged `True` (listed in `docs/README.md`, section 4). They are rewritten when the release is committed; nothing else fails |
| **Method label in the code** | `METHOD_VERIFICATION["attribute_agreement"]` (`datamapperx/statistics/study.py`) is "Pending Minitab Verification", like every method. The About the method text (`datamapperx/statistics/formulas.py`) says the Assessment Disagreement table "has not yet been compared with a full Minitab run". Neither was changed after the owner's statement; changing them is the owner's decision and follows the rule in `docs/statistical-validation.md` ("Method verification") |

## 2. What the repository shows

"Compared with Minitab" below means compared with output Minitab itself printed (`docs/attribute-minitab-comparison.md`). Nothing in the
last column is shown by the repository: it is the owner's statement.

| Feature | Automated tests | Compared with Minitab output in the repository | Owner |
|---|---|---|---|
| Ratings import (CSV/XLSX, column and category mapping, preview) | Yes | n/a (an input format) | Validated (statement) |
| Percent agreement and exact interval: Within, vs Standard, Between, All vs Standard | Yes | **Yes**: 50 printed figures of Minitab's Textile example, and 30/30, 50/50, 47/50, 37/50. The interval at 0 % is not compared | Validated (statement) |
| Fleiss' kappa, SE, Z, P: Within, vs Standard, Between, All vs Standard | Yes | **Yes**: 240 printed figures (5 responses). Two responses with imperfect agreement: not compared | Validated (statement) |
| Assessment Disagreement table: #Pass/Fail, #Fail/Pass, #Mixed, each with its Percent (per sample, once; divisors: Standard-Fail samples, Standard-Pass samples, all samples; N/A without a base) | Yes (independent count of 150 random studies, hand-counted studies, screen = PDF = workbook) | **Partly**: Minitab's definitions and one published example (#Pass/Fail 1 = 25.00, #Mixed 1 = 10.00; the book's data not readable). The #Fail/Pass divisor, N/A cells, one trial and other labels are not compared | Validated (statement) |
| Results table, Details, Checks, summary line | Yes (the real Qt workspace, headless, with the ten sample files) | n/a | Validated (statement) |
| Assessment Agreement charts | Yes (chart data, drawn primitives, panel layout) | n/a (they draw the figures above) | Validated (statement) |
| PDF report | Yes; 19 files open under strict pypdf and Ghostscript with no warning; pages looked at; rendered with PDFium | n/a | Validated (statement) |
| Excel report | Yes; 19 files pass zip, XML, content-type, relationship and chart-element-order checks and reload in openpyxl; the Attribute workbook (2 charts) also opened in a real, hidden Excel 16 without repair (`docs/windows-acceptance.md`) | n/a | Validated (statement) |
| Acceptance (optional, off by default) | Yes | n/a (the user's criterion) | Validated (statement) |
| Switching methods; Gage R&R and Capability unchanged | Yes (numbers and views in the Qt workspace, headless; baseline fixtures pinned by hash). With the flags off and on, Cpk and Variable GR&R output was identical (`docs/windows-acceptance.md`) | existing references | Validated (statement) |

## 3. Known limitations

* Assessment Disagreement: the divisor of #Fail/Pass, the N/A cell, a single trial and responses other than Pass and Fail are not
  compared with Minitab output in the repository (`docs/attribute-minitab-comparison.md`). Kendall's coefficients, Cohen's kappa and
  ordered categories are out of scope.
* The Attribute PDF was rendered and read back by tools, not opened in a PDF viewer by automation (the Gage R&R PDF was opened in Edge and
  Chrome). The workbooks were not validated against the ECMA-376 schemas (the sequence of the elements of the chart parts was).
* With about ten or more appraisers with long names, on a high-resolution screen, in a very small window, the rotated names on the
  agreement graph can touch each other. The panel is made tall enough for its plot (`agreement_extra_height`) and the canvas scrolls;
  widening the window removes the crowding. The label spacing is planned by shared code (`_category_plan`) that the Gage R&R charts
  also use, and was left alone.
* Qt: the ownership rule every widget follows is in `docs/qt-widget-ownership.md`; `tests/ui/test_ownership.py` checks it.

## 4. Commands

```
python -m pytest -o addopts=""                          # everything; the window tests run headless on Qt's offscreen platform
python -m ruff check datamapperx tests
python main.py                                          # the window (flags True in the working tree: nothing to set)
```

If the flags are `False` (the committed state), two environment variables let a window run Attribute Agreement and make its report
without changing them: `DATAMAPPERX_ATTRIBUTE_RESULTS=1` and `DATAMAPPERX_ATTRIBUTE_REPORTS=1` (`set` them first on Windows).

The window tests build real windows on the offscreen platform and take no focus. Baseline fixtures: `tests/test_baseline_integrity.py`
pins the Git blob hash and the SHA-256 of both files (`git ls-files -s tests/fixtures` shows the same blob hashes).
