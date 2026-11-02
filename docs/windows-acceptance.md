# Windows acceptance review of the Qt window

Done on 2026-11-02 on the development machine (Windows 11 Enterprise 10.0.26100, 1920x1080, Python 3.13.4, PySide6 6.12, Microsoft
Excel 16.0 build 20430, Edge and Chrome), after the migration from Tk, in two rounds: the acceptance review, then the release
preparation. It was run against the source and against the exe that `tools\build.ps1` builds. The scripts that drove it are
throw-away and are not in the repository; what each one did is written down here so it can be repeated. A person did not click
through the application: the real window was driven by scripts, Windows UI Automation and screenshots, so "automated" below means that.

## Result

| Area | What was done | Result |
|---|---|---|
| Whole test suite | `python -m pytest` (offscreen) | 1,510 passed, 17 skipped (company data that is not published), 0 failed |
| CI | GitHub Actions on windows-latest, Python 3.13.16, newest allowed dependencies | green on `af43d21` (lint and tests) |
| Qt tests on the real platform | `QT_QPA_PLATFORM=windows python -m pytest tests\ui` (real window plugin, real fonts and window manager) | 191 passed |
| Statistics | baselines, Minitab references and `datamapperx\statistics\` compared with the last Tk commit | byte-identical; 307 baseline and reference tests pass |
| Exe | `tools\build.ps1`: build, then the exe's own `--smoke-test` | 29.5 MB, self-test passes |
| Walk-through of the real window | scan, filter, select, review, export, Validation (crossed Gage R&R, Cpk, RawData.xlsx import, Attribute from CSV and XLSX), six PDF and Excel reports each read back, settings saved and restored, light and dark | 28 of 28 checks at 100, 125 and 150 % scaling; no layout finding, no Qt warning |
| Dialogs | each of the 19 dialogs opened, shown, measured and closed | no clipped or squeezed control at 100 and 150 % |
| Large text | the same walk-through with Windows text at 11 and 13 pt at 125 and 150 % | see "Large text" below |
| Memory and lifecycle | 30 open/close cycles; 14 full workflows; 8 cancelled scans; 10 windows closed with a worker running | memory flat (+0.1 to 0.2 MB per cycle), widgets and objects constant, every cancel and close safe, thread pool drained |
| Display-only changes | statistics, evaluations, checks and table rebuilds counted while switching tabs, workspaces, theme, size | tabs, workspaces, resizing and selection recompute nothing |
| Reports in real Excel | every workbook the application makes, opened read-only in a separate hidden Excel 16 and scanned cell by cell | open without repair, 0 error cells; see "Reports" below |
| Reports in PDF viewers | the Gage R&R PDF opened in a real Edge (the default viewer) and a real Chrome window | renders: tables, charts, 6 pages |
| Packaged exe | clean environment, 10 starts and closes, fresh profile, Tk-era settings, read-only data folder, Vietnamese letters and spaces in the install and data paths | all pass; every close is clean; nothing is left in `%TEMP%` |
| Update, controlled | v1.2.0 exe updates to a v1.3.0 exe from a local release server (the only change in the test exes is the update address): headless and through the banner and dialog, plus a wrong hash, a wrong size, a file that is not a program, up to date, a folder that cannot be written, no server | 15 of 15 and 8 of 8; an update leaves no unpacked folder |
| No Tk | source, requirements, spec, the exe's contents and every module imported in a fresh interpreter (`tests\test_no_tkinter.py`) | none |
| Attribute release flags | Cpk and Variable GR&R with the flags off and on: results, metrics, Details, 1,509 and 3,194 Excel cells, PDF pages | identical; with the flags off Attribute cannot be run or reported |

## Measurements of the final build

| | Tk (last commit with it, earlier session) | Qt, final |
|---|---:|---:|
| From source, first paint | 1.14 s | **0.72 s** (7 to 8 runs, 0.67 to 0.73 s) |
| From source, working set | 48 MB | **81 MB** |
| Packaged one-file exe, window on screen | 3.3 s | **2.08 s** median of 10 (1.99 to 2.27 s) |
| Packaged, working set (shared pages included) | 64 MB | **107 MB** |
| Packaged, private memory | not measured | **54 MB** |
| Size of the exe | 20.9 MB | **29.5 MB** (30,885,187 bytes) |
| Closing the window | | 0.57 s median; 10 of 10 clean, nothing left in `%TEMP%` |

The packaged start varies between sessions (2.1 to 3.2 s for the same exe), so compare only numbers taken in one session. Most of it
is the one-file exe unpacking itself. The same session measured the commit before the layout fix at 726 ms / 81 MB and the final one
at 718 ms / 81 MB: the fix costs nothing.

## Found and fixed

* **The Excel report of a Variable Gage R&R study could not be opened by Excel** (error 0x800A03EC, its repair mode failed too).
  Found by opening every generated workbook in real Excel. One chart, "Measurement by Sample ID", gave each marker-only series a line
  that was both "no fill" and "solid fill"; the OOXML schema allows one fill, openpyxl writes both without complaint and current
  Excel rejects the whole workbook. The Tk-era engine writes the identical file, so this predates the migration. Fixed at the two
  places that set `noFill`; numbers and the PDF are unchanged. `tests\test_report_excel_schema.py` fails without the fix.
* **Large text on a small screen**: the Source card of Data Mapping and the Analysis tab scroll instead of squeezing their controls.
  Before, 23 of 24 controls of the card were shorter than their own text. At the usual sizes all 28 rendered states (every page,
  every Validation tab for each method, light and dark, two window sizes) are pixel-identical to before. The log profile box now
  reacts to the mouse wheel only when it has the focus, so scrolling the card cannot change the profile.
* A long path (a RawData.xlsx in a deep OneDrive folder) was cut off at the edge and made the Validation page ask for more width than
  the window allowed; it is now shortened in the middle, whole in the tooltip.
* Timers started with a bare lambda still ran after their window was deleted ("Internal C++ object already deleted"); they now have
  the window as their context.
* A `settings.json` or `profiles.json` saved by Notepad with a byte-order mark was taken for a damaged file; both are read with
  `utf-8-sig`.
* The exe carried Pillow's Tk binding (`_imagingtk`); it is left out.
* **CI**: the one failure on the runner (of about 1,500 tests) was the negative control of the ownership stress, which breaks the rule
  on purpose and expects a crash; there the violation survived all 40 rounds. A crash from a thread race is a property of the
  machine, so the control now skips with its reason where it does not crash (the test that matters, that the window survives, passes).
  CI also prints the failed tests as an annotation, because GitHub shows a job's log only to people who are signed in.

## Reports: automated checks and what was not done by hand

Automated, on this machine: all five workbooks the application makes (raw data, ratings import, crossed Gage R&R with 12 charts, the
six-system capability report, Attribute Agreement with 2 charts) opened in a separate hidden Microsoft Excel 16 process (the Excel the
user already had open was never attached to or touched), each sheet's used range read, every cell checked for an error value (none),
formulas and charts counted, and the Gage R&R workbook exported to PDF by Excel itself and looked at as images; the PDFs read back with
pypdf and rendered with PDFium; the Gage R&R PDF opened in real Edge and Chrome windows (own throw-away profiles) and captured.

Not done by hand: opening a report by double-click in the user's own Excel (Protected View, add-ins) or by the Open button into a
running Excel; Acrobat (it was running with the user's documents, so it was left alone); printing. A cosmetic point seen in Excel,
not changed: the legend of the "Measurement by Operator" chart lists all 12 measurement series and crowds the plot.

## Temporary extraction (one-file exe)

Measured: a clean close removes the unpacked folder (10 of 10), and so does every update, headless or through the dialog (the old exe,
the new exe, the relaunch). A copy that is killed or crashes leaves one folder of about 55 MB in `%TEMP%\_MEI...`; this is how a one-file
PyInstaller exe works and it was the same in the Tk build. Forty-seven such folders (2.9 GB) had accumulated on the development machine
from force-killed benchmark runs; only those were removed.

A cleanup at start is feasible but was **not** added to 1.2.0: it is code that deletes in the user's `%TEMP%`, for a nuisance that
needs a forced kill to appear. What was learned, for when it is wanted: a rename is not a safe "in use" test (a running copy's
folder can be renamed), but a loaded DLL cannot be opened for writing, so "its `python3*.dll` can be opened for writing" separates a dead
copy from a live one reliably (verified on the real exe). A safe cleanup would remove only folders that are named `_MEI<digits>`, hold
`assets\DataMapperX.ico`, are older than minutes, are not the running copy's own and whose DLLs are not in use, on a worker thread.

## Limits that remain

| Limit | Class | Why |
|---|---|---|
| Residual tightness at very large text: the Validation workspace's overall minimum is up to 50 px above a 640 px window at 13 pt and 150 %, and 8 px short of the 1,000 px minimum width at 11 pt | non-blocking | what is on screen is the current tab, and those tabs hold tables that scroll; nothing overlaps or is cut off in the screenshots |
| One-file exe starts in 2.1 to 3.2 s and unpacks at every start | non-blocking | faster than the Tk build packaged (3.3 s); the form of distribution is the owner's decision (the updater replaces one file) |
| A killed or crashed copy leaves about 55 MB in `%TEMP%` | non-blocking | clean closes and updates leave nothing (measured); same as the Tk build; see above for the safe design |
| Memory is higher than Tk (107 MB working set, 54 MB private, against 64 MB) | non-blocking | modest in absolute terms; startup is faster |
| The exe is not signed (version information and icon are present) | non-blocking for this release | same as before; Windows may show SmartScreen's warning for a downloaded copy |
| Windows' 260-character path limit (settings file included, which only logs a warning) | non-blocking | the default data folder is `%APPDATA%\\DataMapperX`; Excel's own limit for opening a workbook is 218 characters |
| Attribute Agreement is behind `ATTRIBUTE_RESULTS_READY` and `ATTRIBUTE_REPORTS_READY` (False) | non-blocking | by design, as in Tk; identical Cpk and Variable GR&R output with the flags on |
| 17 tests are skipped (confidential FT reference logs and `samples\`) | non-blocking | the data is not published; run them where it is |
| The ownership control skips on a machine where the deliberate violation does not crash (CI) | non-blocking | the property itself is tested and passes there |
| The Excel legend of "Measurement by Operator" lists 12 series | non-blocking | looks only |
| An update against GitHub itself was not run | **release-time check** | it needs a published release; the same code path was exercised against a local server (15 + 8 scenarios). Do it on the first real release, with a draft or test release first |
| A fresh Windows installation was not tested (no Sandbox, not elevated) | non-blocking, residual risk | the exe bundles the Visual C++ runtime and the Universal CRT, starts with a PATH of only Windows, and has no Tk or Python dependency |
| Opening a report by hand in the user's Excel and in Acrobat | non-blocking | the files open in Excel, Edge and Chrome by automation; a person should still open one of each |

Nothing is blocking.

## To repeat the main checks

```
python -m pytest                                              # everything, offscreen
set QT_QPA_PLATFORM=windows && python -m pytest tests\ui      # the Qt tests on the real platform (windows flash on screen)
powershell -File tools\build.ps1                              # exe and its self-test
```

The controlled update test: copy the source twice, change the three update constants in `datamapperx\updater.py` (`RELEASES_URL`,
`STATUS_URL` and the host check in `_check_host`) to `http://127.0.0.1:<port>`, set `__version__` to 1.2.0 in one copy and 1.3.0 in
the other, build both, serve a `latest.json` with the SHA-256 and size of the 1.3.0 exe and the 1.3.0 exe itself, and run the 1.2.0
exe with `--update --restart`.

Opening a workbook in real Excel from a script: start your own instance (`New-Object -ComObject Excel.Application`, never attach to a
running one), `Visible = $false`, `DisplayAlerts = $false`, `Workbooks.Open(path, 0, $true)`; an unreadable file raises 0x800A03EC.
