# DataMapperX documentation: start here

State on **2026-11-02**. Every statement below was checked against the repository on that date; where something is the owner's statement
and not something the repository shows, it says so. If it matters, run `git status` and the tests again before relying on it.

## 1. What is in this folder

| File | What it is | Authoritative for |
|---|---|---|
| `statistical-validation.md` | The statistical methods as implemented, their formulas, the Minitab comparisons and the verification rule | Statistics. Read it before touching anything in `datamapperx/statistics/` |
| `attribute-release-readiness.md` | Attribute Agreement: owner validation, release flags, what the repository does and does not show, open items | The status of Attribute Agreement |
| `attribute-minitab-comparison.md` | What was compared with Minitab output (290 figures), the Assessment Disagreement rule, nine optional reference studies | The Minitab evidence for Attribute Agreement |
| `attribute-gui-verification.md` | Ten sample files with their expected figures and a manual walk-through of the Attribute screens | Expected Attribute results; a regression aid |
| `windows-acceptance.md` | The acceptance review of the Qt window, a snapshot at commit `aeee0fd` | What was measured and found on Windows at that commit |
| `windows-performance.md` | Start-up and memory measurements, a snapshot at commit `aeee0fd` | Performance of the Qt window at that commit |
| `qt-widget-ownership.md` | The rules every widget follows so that the garbage collector never destroys one on a worker thread | Widget lifetime (`tests/ui/test_ownership.py` enforces it) |
| `ui-redesign/DataMapperX_UX_V07.html` and `DataMapperX_UX_V07_RELEASE_NOTES.md` (in this folder) | The **current** UX reference: a standalone HTML prototype with demo data, and its design contract and integration guardrails (section 6) | The design target for further UI work. Its numbers, names and calculations are demo values, not product data; it is a visual and interaction reference only |

Not kept: screenshots (none are stored in the repository since 2026-11-02), the previous design reference `DataMapperX_UX_V6.html` (V07 is
"based on V6" and replaces it; the code comments that say "UX V6" are from Phases 1 and 2, which were built to V6), and the old design proposal for the Validation workspace
(`validation-workspace-proposal.md`, deleted: it described a plan from 30-31 October, named modules that no longer exist, and said that
phases which are built were not yet approved; what in it still holds is in `statistical-validation.md`).

## 2. Where the work stands

**Work in progress.** After this file was written (22:30), a second editor began changing UI files in the same working tree: from 22:45 `palette.py`, `theme.py`,
`widgets.py`, `main_window.py`, `validation_workspace.py`, a new `report_preview.py` and `tests/ui/test_v6_workspace.py` changed. Sections 2 and 7 describe the state
at 22:30 and may be out of date (at 23:15 the step bar already had five steps and the window titles had changed). Read `git diff HEAD --stat` before trusting them.

**Commit state.** Branch `main`, last commit `aeee0fd`. Nothing of the UI redesign is committed: the owner said not to commit or push
until they ask.

| Part | State | Where |
|---|---|---|
| Dashboard and navigation (opens on the Dashboard; two starting points; a way back from both workflows) | Done, tested, uncommitted | `datamapperx/ui/dashboard.py`, `main_window.py` (`start_mapping`, `start_rawdata_analysis`, `_show_workspace`), `validation_workspace.py` (the import hooks only), `tests/ui/test_dashboard.py` (18 tests) |
| Data Mapping and Review redesign, built to **V6** (Mapping: three panels; Review: preview, Pre-check and Limits, two ways on). Not compared with V07 | Done, tested, uncommitted | `main_window.py`, `widgets.py`, `theme.py`, `datamapperx/workflow.py`, `tests/ui/test_mapping_review.py` (36 tests), one edited test in `tests/ui/test_mapping.py` |
| Analysis and Report redesign (Phase 3) | **Not started** | `datamapperx/ui/validation_workspace.py` is the screen it would change. The V07 release notes cover its screens (Analysis, Results, Report) |

Uncommitted tracked changes (from `git diff HEAD --stat`): `datamapperx/ui/__init__.py`, `dialogs.py`, `main_window.py`, `theme.py`,
`validation_workspace.py`, `widgets.py`, `datamapperx/workflow.py`, `tests/ui/test_mapping.py`, `tests/ui/test_widgets.py`; new files:
`datamapperx/ui/dashboard.py`, `tests/ui/test_dashboard.py`, `tests/ui/test_mapping_review.py`. Untracked and not part of the application
work: `CLAUDE.md` (general working guidelines, appeared on 2026-11-02), `report/ux_redesign_capture/` (see section 7). Staged and not part
of it either: the `report/` management overview (a .docx and screenshots) and the two Attribute flags (section 4).

**Tests** (`python -m pytest -o addopts=""`, Windows, offscreen): 1,581 collected; **1,559 passed, 17 skipped, 5 failed**. The 5 failures are
all Attribute release-flag tests and are explained in section 4; no other test fails. The 17 skips are confidential FT reference logs
that are not in the repository. Ruff passes (`python -m ruff check datamapperx tests`).

## 3. Rules the owner has set for any further work

* Python and PySide6 only. Keep Light and Dark mode working. No login, audit trail or database features.
* Do not commit or push unless asked. Do not overwrite unrelated uncommitted changes.
* Statistics are not changed for a UI task: no formula, engine, baseline fixture (`tests/fixtures`, pinned by hash) or report output.
* Do not change the Attribute release flags (section 4) unless the owner says so in that task.
* Profile names are free text. Never limit them to ICT, FT or EOL (the design prototypes show names such as "EOL Test Log" only as demo data).
* Keep every screen free of text that only explains: a title, the figures, the controls and their state are enough; an explanation belongs in a tooltip.
  The owner asked for this on 2026-11-02 (the Dashboard, Data Mapping and Review were cleaned accordingly; the Validation screens were not).
* Do not hard-code demo values or special-case a screenshot. Visual acceptance is real PySide6 screenshots, taken at the target Windows
  sizes and compared with the V07 reference; passing tests alone do not show it.
* Keep the known Attribute flag failures (section 4) separate from UI work. Do not start unrelated statistical rewrites.
* Respect the existing read-only Limits table of the Review unless a separate requirement changes it.
* Existing results, selections and user data are preserved when moving between screens; replacing them needs an explicit action
  (Reset, a new scan, a new import).

## 4. Attribute Agreement, exactly

* **The owner's statement (2026-11-02):** the Attribute Agreement method has been validated by the owner and works similarly to Minitab.
  The repository holds no record of that validation (no filled-in checklist, no Minitab session outputs beyond the Textile example in
  `tests/reference/`). What the repository itself shows is in `attribute-release-readiness.md` and `attribute-minitab-comparison.md`.
* **Release flags** `ATTRIBUTE_RESULTS_READY` and `ATTRIBUTE_REPORTS_READY` (`datamapperx/ui/validation_workspace.py`): `False` up to
  1.2.0, **`True` from 1.2.1**: the owner decided on 2026-11-03 to ship Attribute Agreement enabled. Setting them back to `False`
  withholds its results and its reports again.
* **The 5 tests that asserted the flags were off** were rewritten for that release. The gates are still tested: the `unreleased`
  fixture of `tests/ui/test_validation_attribute.py` and the first test of `tests/test_attribute_results.py` switch the flags off on
  purpose. The shipped state is pinned by `test_attribute_agreement_is_released` (`tests/ui/test_validation_attribute.py`) and by that
  first test of `tests/test_attribute_results.py`.
* **What the code still says** (not changed, because it is statistics code): `METHOD_VERIFICATION["attribute_agreement"]` in
  `datamapperx/statistics/study.py` is "Pending Minitab Verification", as are all the other methods, and the About the method text of
  Attribute Agreement (`datamapperx/statistics/formulas.py`) says that the Assessment Disagreement table "has not yet been compared
  with a full Minitab run". Whether to change either is the owner's decision (open items below).

## 5. Open items

| # | Item | Who decides | Notes |
|---|---|---|---|
| 1 | Commit the Attribute release: flags `True`, rewrite the 5 tests, replace the stale comments on the two flag lines | Owner | The tests currently fail only because the flags are staged as `True` |
| 2 | Whether `METHOD_VERIFICATION["attribute_agreement"]` moves from "Pending Minitab Verification" and the "not yet compared" sentence leaves About the method | Owner | The rule (`statistical-validation.md`, "Method verification") asks for the Minitab outputs to be in `tests/reference/` and compared by tests. The owner's validation is not stored there |
| 3 | The root `README.md` says that "attribute studies ... are not implemented" and does not describe Attribute Agreement; `CHANGELOG.md` [Unreleased] does not mention the V6 screens or Attribute Agreement | Owner, at release | Outside this folder; not edited |
| 4 | Phase 3: Analysis and Report redesign, and bringing Phases 1-2 in line with V07 where the owner wants it | Owner | Same rules as section 3; the Validation screens as they are now are in `report/ux_redesign_capture/` (end of section 7) |

## 6. The design reference, V07

`DataMapperX_UX_V07_RELEASE_NOTES.md` is the owner's contract for V07 and says what the prototype is and is not; read it with the
HTML. Phases 1 and 2 were built to V6 and **have not been compared with V07**. What the release notes state for the screens that exist,
against what the application does today (the application's side was checked in the code; the HTML itself was not compared here):

| V07 release notes | The application today |
|---|---|
| A 5-step Mapping workflow and a 3-step Existing RawData workflow | Mapping has 2 steps, Select and Review Data (`StepBar` in `main_window.py`); the second Dashboard card, Analyze by Excel File, opens a dialog (Attribute, or Variable / Cpk with a RawData.xlsx); Continue opens Validation & Reports on its Analysis Setup |
| Source configuration in one horizontal bar; Available and Selected side by side | Source is the left column of three panels (Source / Available / Selected, stretch 27:68:35, 24:56:40 below 1150 px) |
| `Value (MIN/MAX)` shows components with finite numeric MIN and MAX **and MIN < MAX** | The `Value` check box (`workflow.has_numeric_limits`) needs both limits to be numbers; it does not test MIN < MAX |
| Review summary strip: Samples, Files per sample, Rows, Columns, Limits | None: the owner had the strip (four tiles), the Quick check badge, the row line of the Limits tab and the check chips under the Data Preview removed from Review Data |
| Selected: ordered names with up, down and remove, no MIN, MAX or TYPE | Number, name and remove on each row; one up / down pair in the panel footer moves the highlighted row (`ActionTable(reorder=True)` adds Alt+↑ / Alt+↓) |
| Criteria beside the screening counts; Export RawData and Continue to Analysis together below the data | Criteria is in the tab row of the Pre-check card; the two actions are two buttons in one row below the data |

## 7. Working on the UI: what to know

* **Structure.** `MainWindow` (`datamapperx/ui/main_window.py`) keeps `QStackedWidget` pages in `_pages`: `dashboard`, `select`, `review`
  and `validation` (`ValidationWorkspace`); the last two are built a moment after the first paint (`warm_up`) or when first needed. `workspace` is one of
  `dashboard`, `mapping`, `validation`; `step` is `select` or `review`. Nothing is cleared by moving between them.
* **Analyze by Excel File** (the second Dashboard card). One layout for each type, and it is the one the program writes: Variable GR&R and
  Cpk read a RawData.xlsx (the Data Mapping export, `statistics/importers.py`: no Operator or Trial column, no column mapping; Gage R&R
  operators are set in the Analysis tab, trials are numbered in row order), and Attribute reads a ratings table (the Observations sheet of
  the Excel report is read as it is; its columns are the template's, and Review columns can map other names). `datamapperx/ui/excel_analysis_dialog.py`
  only draws; `datamapperx/excel_intake.py` writes the two templates (`Attribute_Template.xlsx`, `Variable_Cpk_Template.xlsx`, each with a
  version on its Instructions sheet) and checks a file: `validate_attribute` and `validate_variable` return an `IntakeReport` (Ready for
  Analysis / Warnings Found / Invalid File, with sheet, row and column). They use the engine's own checks (`attribute_calculation`, `compute`:
  statistics only, acceptance is never asked, so a study that would FAIL is not a reason to refuse a file). A test item the engine cannot
  use is a warning while another can be analysed, as it always was. Reset (top right of the dialog) empties what the dialog remembers (type, method, file, what was found) and drops a check still reading; the data
  already open in the analysis stay until another file is continued with. The Attribute type follows `attribute_runnable()`; the flags are not
  changed here. Numeric methods have no release flag; every method is still labelled "Pending Minitab Verification" in `statistics/study.py`.
* **Shared kit** (`datamapperx/ui/widgets.py`): `Card` (`badge`, `head`, `dense`, `short_title`), `CountTile`, `ActionBox`,
  `CompactPage`, `NarrowPage`, `FlowRow`, `ElidedLabel`, `FittingLabel`, `StepBar` (`compact=True` is the pill form), `DataTable`
  (`row_lines`, `elide_middle`), `ActionTable` (`reorder`, `show_header`), `elide_middle()`. Colours come from `datamapperx/palette.py`;
  `datamapperx/ui/theme.py` holds the stylesheet (selectors by object name and `role`, `badge`, `kind` properties).
* **Verifying a layout change.** Run the real window with `QT_QPA_PLATFORM=windows`, an isolated `DATAMAPPERX_HOME`,
  `background_checks=False`, and `window.grab()`; judge the layout there. Offscreen fonts are about twice as wide and the offscreen
  window cannot be made narrower than about 1,270 px, so a test must not rely on a pixel width: assert stretch factors, rules ("on one
  line exactly when it fits") or emit the signal (`narrow_changed`). The sizes that matter are 1000x680 (the window's minimum), 1366x768,
  1360x880 (the primary comparison size) and 1920x1080, in both themes, and with larger text (the real minimum width is 911, 949 and 987 px at
  100, 125 and 150 % text).
* **Test helpers.** `tests/ui/conftest.py` (`app`, `window`), `tests/ui/support.py` (`pump`, `scan`, `ready_to_review`, `make_logs`),
  `tests.conftest.ict_block` and `write_ict_log` for synthetic logs (the serial number must look like `VSE001`). Stub
  `QFileDialog.getOpenFileName` and `getSaveFileName`: a real native dialog hangs a test.
* **Pitfalls found.** Line endings are mixed: most tracked files are LF, but 41 are CRLF (among them the `datamapperx/statistics/` modules, the root `README.md` and
  `CHANGELOG.md`, and three files in this folder). Keep each file's own endings: a Python `Path.write_text` on Windows rewrites a file as CRLF and turns the diff
  into thousands of lines, so edit with an editor tool or write bytes, and check `git ls-files --eol` and `git diff --stat`. The item view's
  own painting ignores `Qt.ElideMiddle` for long names; `elide_middle()` in the row delegate does it. A wrapping `QLabel` needs a
  `heightForWidth` it can use; an unwrapped label fixes its card's minimum width.
* **Observation of the screens before Phase 3.** `report/ux_redesign_capture/` (untracked; `CURRENT_WORKFLOW.md`, 20 screenshots, the
  script) was taken before any of this work. Its Capability, Gage R&R, Attribute and RawData screens still show the Validation screens as
  they are; its Mapping and Review screenshots (04, 04a to 04d) show the old layout and are out of date.
