# Attribute Agreement: one-time check in the real window

Everything about Attribute Agreement that can be tested without a window has been (`tests/test_attribute*.py`, `tests/test_ratings.py`). The code of the workspace itself has also been run in the real Qt workspace on Qt's offscreen platform, so no window opens and no focus is taken (`tests/ui/test_validation_attribute.py`): import, mapping, Run, the Results table, Details, Checks, the charts, sorting, switching between methods and making the reports, so a missing name or a wrong call would already have been found. What is left is what only the window on a screen shows: how the import dialog, the tables, the colours and the charts look, and the PDF and Excel files opened in their own programs. This is the list to go through once. The readiness flags stay off until it has been done and approved.

Starting the application opens a window and takes the keyboard focus, so do this when that does not matter.

## 1. Start with the checks switched on

The two flags `ATTRIBUTE_RESULTS_READY` and `ATTRIBUTE_REPORTS_READY` (`datamapperx/ui/validation_workspace.py`) are False. Two environment variables let the window run Attribute Agreement and make its report without changing them:

```
DATAMAPPERX_ATTRIBUTE_RESULTS=1 DATAMAPPERX_ATTRIBUTE_REPORTS=1 .venv/bin/python main.py        # macOS
set DATAMAPPERX_ATTRIBUTE_RESULTS=1 && set DATAMAPPERX_ATTRIBUTE_REPORTS=1 && python main.py      # Windows
```

Without them, the Run button of Attribute Agreement is disabled and says that it cannot be run yet, and the PDF and Excel buttons say that its reports are not available yet. Check that first (without the variables), then restart with them.

## 2. Sample files

Run this once in the project folder (it writes ten files to `samples/attribute_gui/`, which is not part of the repository):

```
.venv/bin/python tools/make_attribute_samples.py          # macOS
python tools\make_attribute_samples.py                  # Windows
```

The first column of the table says what to expect. `tests/ui/test_attribute_samples.py` opens the same ten files the way the Import dialog does, runs them in the Qt workspace (headless) and asserts the figures, Checks and tables below, so what is left for the window is how they look and behave.

| File | What it is | Expected |
|---|---|---|
| 1_reference | 30 samples x 3 trials, one appraiser, Standard given, everything agrees | Within 100.00 %, (90.50, 100.00); kappa 1, SE 0.105409, Z 9.48683, P < 0.0001; Assessment Disagreement: all three counts 0 and 0.00 |
| 2_one_inconsistent_sample | sample 4 rated Pass, Fail, Pass | Within 96.67 %, (82.78, 99.92); vs Standard 96.67 %; Assessment Disagreement: #Mixed 1, 3.33 (the other counts 0) |
| 3_three_appraisers | Ann agrees; Ben has 5 samples rated differently in trial 1; Carla is consistently wrong on 19 samples | table: Within % and vs Standard % are N/A (one row per appraiser in the Details: Ann 30/30 and 30/30, Ben 25/30 and 25/30, Carla 30/30 and 11/30); Details also have Between Appraisers (11 of 30) and All Appraisers vs Standard (11 of 30), each with its Fleiss' kappa; Assessment Disagreement: Ann 0 / 0 / 0, Ben #Mixed 5 (16.67), Carla #PASS/FAIL 4 (26.67) and #FAIL/PASS 15 (100.00) |
| 4_no_standard | no Standard column values | Within is computed; vs Standard % is N/A; no Assessment Disagreement table; Checks: Info "Standard" |
| 5_unusable_standard | sample 5 has no Standard | Within is computed; vs Standard N/A; no Assessment Disagreement table; Checks: Critical "Standard"; item marked for review |
| 6_single_trial | one trial per sample | Within % N/A; vs Standard computed; Assessment Disagreement: all 0, #Mixed 0 with one trial; Checks: Review "Trials" |
| 7_labels_P_F | labels P and F | map P to PASS and F to FAIL in the dialog (section 4) |
| 8_one_category | every rating and Standard is PASS | kappa N/A with one explanation; Checks: Review "Categories"; no Assessment Disagreement table |
| 10_twelve_long_names | twelve appraisers, names of 1 to 29 characters ("Bartholomew Featherstonehaugh", "Ng", "A"...), a few of them wrong | table: Within %, vs Standard % and Kappa N/A; Details: a row for each of the twelve (Assessment Disagreement, for example: Ng #FAIL/PASS 3 (20.00), Li 6 (40.00), Jo 9 (60.00), Zdzislaw Przybylski 12 (80.00); Fatima Al-Mansouri #Mixed 10 (33.33)); the two chart panels (see F) |
| 9_workbook_two_sheets | the reference with one inconsistent sample, in an Excel workbook with three sheets | the Sheet box of the dialog lists Ratings, Notes and Empty |

## 3. Checklist

Tick each line; write down anything that differs from "expected".

**A. Import, mapping and preview** (Data tab, "Import ratings (CSV/XLSX)")
- [ ] The button reads "Import ratings…"; choosing 1_reference opens the dialog with Sample ID = Samples, Rating = Measurements, Appraiser = Appraisers, Known Standard = Standard, Trial = (none), Test Item = (none).
- [ ] The preview lists 90 rows (first 100 shown for longer files); the summary reads "30 samples · 1 appraiser · 3 trials per sample · 2 categories: FAIL, PASS"; the note says that the ratings were numbered 1, 2, 3.
- [ ] Setting Sample ID or Rating to (none) disables Import and says which column to choose; choosing the same column for two fields says so.
- [ ] Choosing a Trial column switches the numbering checkbox off. Setting Known Standard to (none) leaves the Standard column of the preview empty.
- [ ] 7_labels_P_F: the Categories row shows P and F with their counts; typing PASS and FAIL changes the preview and the summary; the note says "Labels counted as another category". Leaving the entries as they are keeps P and F.
- [ ] 9_workbook_two_sheets: the Sheet box lists the three sheets; choosing Notes shows its own columns; choosing Empty says that it has no data and keeps the previous sheet.
- [ ] After Import the Data tab shows "Test Items 1 · Samples 30 · Appraisers 1 · Ratings 90 · Trials per Sample 3" and the columns Test Item, Sample ID, Appraiser, Trial, Rating, Standard; the method becomes Attribute Agreement.

**B. Analysis configuration** (Analysis tab)
- [ ] Only Attribute settings are shown: Confidence level (90 %, 95 %, 99 %, default 95 %) and "Enable acceptance criteria" (off). No LSL, USL, k, NDC or Cpk settings.
- [ ] Turning acceptance on shows "Minimum agreement" with 90. An empty value, 0 or 150 shows a message and blocks Run.
- [ ] The plan line reads "1 Test Item · 30 Samples · 1 Appraiser".

**C. Run and Results table**
- [ ] The columns are Test Item, Samples, Within %, vs Standard %, Kappa, right-aligned figures, no truncated heading, no SV/Tol, Study Var, NDC, Cp or Cpk.
- [ ] The summary reads "1 item analyzed · Acceptance off". With acceptance on it reads "1 item analyzed · 1 PASS" and an Acceptance Result column appears; turning it off removes both.
- [ ] The Decimals box changes the decimals of the percentages and the kappa; the sort box offers Within %, vs Standard % and Kappa and sorts with N/A last.
- [ ] 4_no_standard with acceptance on: Overall is N/A, not PASS. 3_three_appraisers with acceptance on: FAIL.

**D. Details**
- [ ] Tables in this order, which is the order of the PDF and Excel report: Within Appraisers, Fleiss' Kappa Statistics, Each Appraiser vs Standard, Fleiss' Kappa Statistics vs Standard, Assessment Disagreement and, with several appraisers (3_three_appraisers), Between Appraisers and its kappa, All Appraisers vs Standard and its kappa. No NDC headline, no "All columns" box, aligned columns, the interval column wide enough.
- [ ] Assessment Disagreement is Minitab's table: Appraiser | #PASS/FAIL | Percent | #FAIL/PASS | Percent | #Mixed | Percent, one row for each appraiser, counts and percents in aligned columns, the values of section 2, and no note under it (a note appears only when a percent is N/A). Absent without a known Standard (4, 5) and with one response only (8). No Kendall, Cohen or ordered-category figures anywhere.
- [ ] 5_unusable_standard: no tables against the Standard, and one line "Appraiser vs Standard is N/A. The Standard is missing for 1 of 30 samples."

**E. Checks**
- [ ] The heading reads Check | Finding | Status. 1_reference: "No data issues detected." with status OK.
- [ ] Critical is red, Review amber, Info muted, in both light and dark theme; most serious first; each finding once.
- [ ] 5_unusable_standard: Critical, and the item has the warning mark and counts in "Need Review"; clicking the mark opens the Checks.

**F. Charts**
- [ ] Two panels side by side (one column when the window is narrow): Within Appraisers and Appraiser vs Standard, with a legend row (Percent, 95% CI) under each title; 1_reference shows a circle at 100 and X markers at 100 and 90.5 joined by a line.
- [ ] Nothing overlaps or is cut off at several window sizes, with 1 and with 3 appraisers (3_three_appraisers); the percent scale ends at 100.
- [ ] 4_no_standard shows only Within Appraisers; 6_single_trial only Appraiser vs Standard; 5_unusable_standard shows "N/A: The Standard is missing for 1 of 30 samples." in the second panel. An item with no panel says why.
- [ ] 10_twelve_long_names: in a small window each panel is taller than usual and the panel scrolls, so that the percent scale (ticks 60 to 100 or 90 to 100) stays readable; the rotated names may touch each other on a high-resolution screen in a very small window (a known limit: widen the window).
- [ ] The charts stay on a white background in the dark theme, as the other charts do.

**G. Reports** (Report tab; needs `DATAMAPPERX_ATTRIBUTE_REPORTS=1`)
- [ ] Generate PDF and Excel for 1_reference and 3_three_appraisers. PDF: tables in the order of section D on a portrait page, then "Assessment Agreement" with the two panels on a landscape page; no cover, no company name.
- [ ] Excel: the same tables with the interval as two numeric cells; click a cell to see the full value (for example 96.6666666666667); two charts with circle and X markers and a line between the limits, opening without a repair message in Excel.
- [ ] With acceptance on, an "Acceptance" table follows the statistics and says that it is a criterion of the user; with it off there is none.
- [ ] The figures on the screen, in the PDF and in the workbook are the same (compare the Details with both).
- [ ] Open every exported file in a real application: the PDF in your PDF viewer and the workbook in Excel. No warning, no repair or "unreadable content" message; nothing clipped or overlapping at 100 % zoom; the workbook's two charts show a circle, two X markers and a line between the limits.

**H. Switching between methods**
- [ ] With Attribute results on screen, switch to Variable Gage R&R and to Process Capability: the settings frame, the plan title, the Data tab columns and the sort box follow the method; the old results are marked as out of date and cannot be reported; running GR&R or Capability on the Data Mapping results gives what it gave before.
- [ ] Switching back to Attribute shows its import again; Run gives the results of section C.

**I. Regression sanity**
- [ ] A Variable Gage R&R run and a Process Capability run (Data Mapping results) show their own tables, Details, Checks and charts; the RawData.xlsx export of Data Mapping still works.
- [ ] Switching between the light and the dark theme keeps the compact row height of the Details and Checks tables (the style now lives in `datamapperx/ui/theme.py`, no longer in the workspace constructor).

### What was checked without a window (2026-11-01)

* The ten sample files and the nine Pass/Fail studies were run through the Qt workspace (`tests/ui/test_attribute_samples.py`): the table, Details, Checks and summary of each are those of section 2. The Details, the PDF and the workbook hold the same figures (cell by cell for the workbook, row by row for the PDF).
* The 38 PDF and Excel files of those 19 studies (re-run after the Assessment Disagreement table was changed to Minitab's) open under strict pypdf and Ghostscript with no warning (portrait pages of tables, one landscape page of charts), and the workbooks pass zip, XML, content-type, relationship and chart-element-order checks and reload in openpyxl. Pages of 1_reference, 3_three_appraisers, 5_unusable_standard, F_multiple_appraisers and H_one_reference_category_absent were looked at as images: no overlap or clipping.
* Not done: opening the files in Excel and in a PDF viewer, and everything that is how the window looks (section 3).

## 4. After the check

Record the outcome in the matrix of `docs/attribute-release-readiness.md`. If everything above holds, and only then, set the two flags to True in `datamapperx/ui/validation_workspace.py`, and run the test suite once more (`tests/test_attribute_setup.py` and `tests/test_attribute_results.py` assert the released-off state and will need that change). If anything differs, note the file, the step and what the window did.

## 5. Result log

Date: ____  Windows / macOS: ____  Build: ____

| Section | Done (yes / no) | Everything as expected? | Notes |
|---|---|---|---|
| A. Import, mapping, preview | | | |
| B. Analysis configuration | | | |
| C. Run and Results table | | | |
| D. Details | | | |
| E. Checks | | | |
| F. Charts | | | |
| G. Reports (and the files opened in Excel / a PDF viewer) | | | |
| H. Switching between methods | | | |
| I. Regression sanity | | | |

Anything that differs from "expected" (one line each; a screenshot of the window itself helps):

| # | Sample file | Step | Expected | What the window did | Light / dark |
|---|---|---|---|---|---|
| 1 | | | | | |
