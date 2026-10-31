# DataMapperX

Collects measurements from test logs - i3070 ICT text logs or Function Test Excel workbooks - and exports them as one `RawData.xlsx`, one row per log file, ready for GRR and other analysis.

![platform](https://img.shields.io/badge/platform-Windows-0078d4) ![python](https://img.shields.io/badge/python-3.11%2B-3776ab)

## Install

1. Download **`DataMapperX.exe`** from the [latest release](https://github.com/anhmuoiut/DataMapperX/releases/latest).
2. Put it in a folder you can write to (for example `C:\Tools\DataMapperX\`) and run it. There is no installer.

The app keeps itself up to date (see [Updates](#updates)), so this is the only time you download it by hand.

> Windows SmartScreen may warn about an unsigned program the first time. Choose **More info → Run anyway**.
> To check a download came from this repository's build, run
> `gh attestation verify DataMapperX.exe -R anhmuoiut/DataMapperX`.

## Use

The window has two steps, shown along the top: **Select** and **Review & Export**.

**Step 1 - Select**

1. **Source** - pick a profile, choose the folder that holds the logs, set how many samples and how many files per sample you expect, then **Scan logs**. The summary tells you immediately if a sample has the wrong number of files.
2. **Available components** - search, then press **+** at the end of a row to add that component (or double-click it, or select several and press **Add →**). Each row shows the component's Min and Max.
3. **Selected for export** - the order here is the column order in Excel. Use ↑ ↓ to reorder and **×** at the end of a row to remove it. Then press **Review & Export**.

**Step 2 - Review & Export**

- The **GRR pre-check** tab is a quick look before exporting, not a statistical conclusion: it evaluates each selected test using all serial numbers and repeated files and colours the figures against reference thresholds (Minitab itself reports the figures without a verdict). It shows **%Study Var**, **%SV/Tol** and **NDC** as numbers in colored cells. Percentages display two decimals; NDC is an integer. The color legend gives the separate thresholds: percentages **PASS ≤ 10%**, **CONDITION > 10% to 30%**, **FAIL > 30%**; NDC **PASS ≥ 5**, **FAIL < 5**. Colors use unrounded values. Undefined results show gray **N/A** with calculation notes when selected.
- The calculation follows the sample report's **one-way random-effects ANOVA by SN**, for a single operator/fixture: within-part variance is repeatability, negative part-to-part variance is set to zero, and Study Var uses 6 SD. It requires at least two SNs with the same number of repeats (at least two each). Operator reproducibility is not estimated. Missing/non-numeric readings or conflicting units are marked **Not evaluated**; invalid, missing or differing two-sided limits prevent only SV/Toler. These results help review the study before exporting; statistical FAIL/CAUTION does not prevent exporting the raw data for Minitab.
- The table is exactly what will be exported. Amber rows: a value is missing. Red rows: a sample has the wrong number of files. With more than 20 columns, ‹ › page through them (the Excel file always has every column).
- The **Limits** tab on the right lists every selected component with its Min, Max and Unit, the same limits the Excel file shows beside the data. Click a row of the table to open this tab and see that row's values next to them; a value outside its limits is marked ▲ (above max) or ▼ (below min).
- The checks at the bottom sum it up (samples found, files per sample, empty cells, rows outside their limits). **Export Excel…** is disabled while a sample has the wrong number of files. **← Back** returns to step 1.

Your last profile, folder, counts and component choices are remembered. The header has a **Dark mode / Light mode** button and the **Help** menu; the version and credit are at the bottom left of the Source card. Shortcuts: `Ctrl+O` folder · `Ctrl+Enter`/`F5` scan · `Esc` cancel · `Ctrl+E` go to Review & Export, then export.

### Validation & Reports (optional)

**Validation & Reports** is a workspace of its own, next to **Data Mapping** (the two buttons under the header, or **Validation & Reports →** on the review page). It analyses a *copy* of the data: it never changes the scan, the data preview or the Excel export, and a problem there never blocks **Export Excel…**.

The reference is **Minitab**: Variable Gage R&R (one-way ANOVA for one appraiser, crossed ANOVA with the Part × Operator interaction for several) and Normal Capability Analysis. The work instructions are background only; they do not set the method, the design of the program or any PASS/FAIL limit. The way of working follows Minitab: **select data → select analysis → run → preview the results → export a report (optional)**.

1. **Data.** Use the Data Mapping results (the scan and the test items you selected), or **Import a RawData.xlsx** written by this app. The card shows samples, readings, test items and the order of the readings. *Worksheet order* is the order of the rows of the worksheet; it is never taken for the order of measurement. The other choices (file name, timestamp from *File assignments*, or "the rows are in measurement order") are claims you make and are recorded. **Field mapping** and **File assignments** are still available for Data Mapping results.
2. **Analysis.** The **Plan** line says in words what will be run. Choose the purpose: **Variable Gage R&R** or **Process Capability**. For GRR the default is one appraiser (repeatability only); enter two or more operator names if several people measured the same samples, or tick **Nest as Operator** (each slot becomes an operator; this answers a different question and is recorded in the report). Where the data carry no Trial, repeated readings of a sample are labelled 1, 2, 3… in row order; this only organises the data and is not the order of measurement. For capability choose how Within sigma is estimated (by default from the subgroup size: the moving range for subgroups of one, the pooled standard deviation for larger subgroups).
3. **Run analysis** (always at the top). The result appears at once.
4. **Results.** The table at the top shows the figures that matter: **%SV/Tol, %Study Var, NDC** for GRR; **Cp, Cpk, Pp, Ppk** for capability. Select an item to see all its charts at once (Gage R&R: Components of Variation, R Chart, Measurement by Sample ID, Xbar Chart, and for several operators Measurement by Operator and the Sample ID x Operator interaction; capability: the histogram with the Overall and Within curves and the specification limits). **Details** shows the tables as Minitab prints them (ANOVA, Variance Components with %Contribution, Gage Evaluation with %Study Var and %Tolerance, Number of Distinct Categories; or Process Data, Overall and Potential (Within) Capability and the Performance table). One specification limit is enough: Cpk and Ppk then use that side and Cp and Pp are not defined (printed as *). **Calculation details** and **About the method** show the formulas and every parameter. Decimals (2 by default, as in Minitab) only change how numbers are shown.
5. **Report.** Everything on this tab is optional: Gage name, Date of study, Reported by and Misc are printed under the title of each item when entered, and the report records the day it was made. Choose the items (a partial report says *Included n of m test items*) and whether to include the charts (and, for Excel, the observations), then **Generate PDF…** or **Generate Excel…**. The report follows Minitab's own reports: for each test item, **Gage R&R for …** with the ANOVA table (one-way, or two-way with and without interaction), Variance Components, Gage Evaluation and the Number of Distinct Categories, followed by the Gage R&R graphs; or **Process Capability Report for …** with the histogram, Process Data, Overall and Potential (Within) Capability and the Performance (PPM) table. It carries no PASS or FAIL, criteria, notes or explanations; those stay in the application. PDF and Excel print the same results; Excel keeps the full value of every statistic, with one sheet per item.

**Notes, not confirmations.** Results are shown immediately. A note bar points out what to keep in mind: for capability that the readings are in worksheet order, that several readings of one serial number measure the measurement system as well as the process, and that stability and normality are not tested here (Minitab: check a control chart and the histogram). For GRR the notes say, for example, that one appraiser gives repeatability only and that Minitab advises at least 10 parts, 3 operators and 2 replicates. Nothing needs to be acknowledged, and the report prints the same notes.

**Acceptance criteria are optional.** By default no PASS or FAIL is given: the report shows statistics only. To add a verdict choose a **customer** (**Customers…**: for each of %SV/Tol, %Study Var and NDC tick whether it applies and set its PASS and FAIL limits) or, for capability, **Judge against a limit** (Cpk or Ppk). Criteria never change a calculated value. The built-in customers (SolarEdge, Zebra, SES, Jabil) are only starting points taken from Jabil's work instruction for reference; edit them or add your own. When a result is acceptable but a metric that is not applied would fail on its own limits, the **Review** column names it.

If you change the data or anything that decides the numbers (the operators, the within-sigma estimate, the readings per sample...), the results turn **stale**: they stay on screen for reference, a banner offers **Update results**, and nothing stale can be reported. Changing the criteria or the decimals does not make results stale. Every calculation method is listed as *Pending Minitab Verification* until its output has been compared with Minitab output; until then the program does not claim to be equivalent to Minitab.

Capability uses MR(2)/1.128 for individuals or pooled subgroup SD with c4 correction, and a separate sample SD for overall performance. GRR uses a balanced one-way random-effects ANOVA (repeatability only) for one operator, and a balanced crossed Sample ID × Operator ANOVA (Minitab's ANOVA method, interaction removed at p ≥ 0.05) when two or more operators measured the same samples, adding reproducibility, a Sample × Operator interaction table and operator charts; tester and slot are kept separate. Unbalanced GRR, nested studies, attribute studies and PPTX export are not implemented. This remains a Windows desktop application.

See [statistical methods, reference comparisons and limitations](docs/statistical-validation.md) for the actual algorithms and Minitab comparison status. The five supplied FT studies reproduce the report's printed GRR figures; the original ICT capability observations and a displayed Minitab NDC result are still needed for those comparisons. The application is not officially Minitab validated or Jabil approved.

### Profiles

A profile tells the app how to read one kind of log. Three are built in: **ICT_I3070 Test Log** (HP / Keysight i3070 text logs), **Function Test Log** and **EOL Test Log** (Excel workbooks with a *Session* and a *Results* sheet). If a scan finds nothing, the app checks whether another profile reads that folder and offers to switch.

#### Teaching the app a new log format (no regular expressions)

Open **Manage… → New**, then pick **one example log**. The app looks at it and fills in the settings; you only check and correct them.

- **Excel logs** - the results sheet, its columns (by their headings, such as *Test*, *Result*, *Min*, *Max*, *Units*) and the cell that holds the serial number are found automatically. Change any of them from a drop-down list.
- **Text logs** - a standard i3070 log is recognised straight away. For any other format, select the part of a line that changes in the sample (a component name, a measured value, a limit) and press what it is: **Component**, **Measured value**, **Unit**, **Lower limit**, **Upper limit**. The app writes the pattern for you, such as `TESTING [Component]`, and paints everything it reads on the sample so you can see it is right. A pattern is just text from the log with the changing parts replaced by blanks: `[Component]`, `[Measured]`, `[Unit]`, `[Min]`, `[Max]`, or `[Any]` for a part to skip.
- **Check** - the table shows exactly what will be read from the sample, and the app tries the same settings on other files in the folder and tells you if any cannot be read.

Limits of the pattern approach: the component line and the measurement line must be separate lines (the measurement is the next non-blank line), and a name that is followed by more fields on its line needs a separator after it so the app knows where it ends. People who prefer regular expressions can still edit them under **Advanced** in the profile editor; **Duplicate** copies a built-in profile as a starting point.

Your data lives in `%APPDATA%\DataMapperX\` (`profiles.json`, `settings.json`, `app_debug.log`); *Help → Open data folder* takes you there.

## Updates

On start-up DataMapperX reads `latest.json` from the newest GitHub release (a plain download, so it works behind corporate proxies and is not subject to API rate limits). If there is a newer version, a banner offers **Update now**. The new exe is downloaded next to the old one, its SHA-256 is checked against `latest.json`, the running exe is renamed to `.old`, the new one takes its place and starts. If anything fails the old version stays in place.

- *Skip this version* silences the banner for that version only. *Help → Check for updates at startup* turns the check off.
- The app can only replace itself when it is a `.exe` in a folder the user can write to. Otherwise the button opens the download page.
- **Forcing an update** - to stop people using a version with a known problem, put its first good version in [`MIN_SUPPORTED_VERSION`](MIN_SUPPORTED_VERSION) and publish a release. Older copies then cannot be used until they update. (If the machine is offline the check cannot run, so the app still starts.)
- Unattended: `DataMapperX.exe --update` installs a newer version and exits without opening a window (`--restart` starts it afterwards). Exit code 0 = ok, 1 = failed, 2 = this copy cannot replace itself.

## Develop

```powershell
python -m venv .venv            # keep the venv outside OneDrive if the repo lives in a synced folder
.venv\Scripts\activate
pip install -r requirements-dev.txt

python main.py                  # run from source
python -m pytest                # tests (the UI tests open real windows briefly)
python -m ruff check .          # lint
powershell -File tools\build.ps1   # build dist\DataMapperX.exe and run its self-test
```

```
main.py                 entry point (PyInstaller builds from this)
datamapperx/
  config.py             names, repo, defaults
  profiles.py           profile definitions, validation, load/save
  parsing.py            read one text / Excel log
  scanner.py            walk a folder, parse in parallel, group by SN
  exporter.py           build the workbook (the review uses the same rows)
  review.py             compare values with their limits, summarise before exporting
  reporting.py          explain scan problems in plain language
  settings.py           remembered preferences
  statistics/           Dataset, Study, statistics, evaluation (criteria) and importers; no GUI
  stat_reports.py       PDF / Excel reports from finished results (stat_charts.py draws the charts)
  updater.py            check / download / verify / install updates
  ui/                   tkinter windows, built on the sv-ttk (Windows 11) theme
    controls.py         the component lists, the step bar and the check chips
    validation_workspace.py  Validation & Reports: Data, Analysis Setup, Results, Report
tests/                  pytest suite
tools/                  build + release helpers
.github/workflows/      CI and release automation
```

## Release a new version

1. Change `__version__` in `datamapperx/_version.py`.
2. Add a `## [x.y.z] - date` section to `CHANGELOG.md` - users see these notes in the update dialog.
3. Commit, then:
   ```powershell
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```
4. The **Release** workflow checks the tag matches the code, runs lint and tests, builds the exe, runs the exe's self-test, writes `latest.json`, and publishes both. Installed copies pick it up on their next start.

## Troubleshooting

| Symptom | What to do |
|---|---|
| "Cannot access … file is locked" | Close the file in Excel and scan again. |
| "No valid log data found" | The message says why (wrong file type, no serial number, no component match). Pick the right profile or fix its regexes. |
| Something unexpected | *Help → Open log file* and send `app_debug.log`. |
| Update banner never appears | Check the machine can reach `github.com`; see the log for "Update check failed". |
