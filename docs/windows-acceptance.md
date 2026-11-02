# Windows acceptance review of the Qt window

Done on 2026-11-02 on the development machine (Windows 11 Enterprise 10.0.26100, 1920x1080, Python 3.13.4, PySide6 6.12), after the
migration from Tk. It was run against the source and against the exe that `tools\build.ps1` builds. The scripts that drove it are
throw-away and are not in the repository; what each one did is written down here so it can be repeated.

## Result

| Area | What was done | Result |
|---|---|---|
| Whole test suite | `python -m pytest` (offscreen) | 1,493 passed, 17 skipped (company data that is not published), 0 failed |
| Qt tests on the real platform | `QT_QPA_PLATFORM=windows python -m pytest tests\ui` (real window plugin, real fonts and window manager) | 186 passed |
| Statistics | baselines, Minitab references and `datamapperx\statistics\` compared with the last Tk commit | byte-identical; 307 baseline and reference tests pass |
| Lint | `ruff check .` | clean |
| Exe | `tools\build.ps1`: build, then the exe's own `--smoke-test` | 29.5 MB, self-test passes |
| Walk-through of the real window | scan, filter, select, review, export, Validation (crossed Gage R&R, Cpk, RawData.xlsx import, Attribute from CSV and XLSX), six PDF and Excel reports each read back, settings saved and restored, light and dark | 28 of 28 checks at 100, 125 and 150 % scaling; no layout finding, no Qt warning |
| Dialogs | each of the 19 dialogs opened, shown, measured and closed | no clipped or squeezed control at 100 and 150 % |
| Memory and lifecycle | 30 open/close cycles; 14 full workflows (scan, export, three analyses, four reports); 8 cancelled scans; 10 windows closed with a worker running | memory +0.1 to 0.2 MB per cycle (flat), widgets and Python objects constant, every cancel freed the window, every close was safe, thread pool drained, no Qt warning |
| Display-only changes | counted statistics, evaluations, checks and table rebuilds while switching tabs, workspaces, theme, size | tabs, workspaces, resizing and selection recompute nothing; see "Review step" below |
| Packaged exe | clean environment (PATH = Windows only), 10 starts and closes, fresh profile, Tk-era settings, read-only data folder, Vietnamese letters and spaces in install and data paths | all pass; every close is clean; nothing is left in `%TEMP%` |
| Update, controlled | a v1.2.0 exe updates to a v1.3.0 exe from a local release server (the only change in the test exes is the update address): headless and through the banner and dialog, plus a wrong hash, a wrong size, a file that is not a program, up to date, a folder that cannot be written, no server | 14 of 14 and 7 of 7 |
| Attribute release flags | Cpk and Variable GR&R with the flags off and on: results tables, metrics, Details, 1,509 and 3,194 Excel cells, PDF pages | identical; with the flags off Attribute cannot be run or reported |

## Found and fixed in the review

* A long path (a RawData.xlsx in a deep OneDrive folder) was cut off at the edge, and made the Validation page ask for more width
  than the window allowed. It is now shortened in the middle (`ElidedLabel`), whole in the tooltip. The status line does the same.
* Timers started with a bare lambda (`warm_up` and two more) still ran after their window had been deleted and raised "Internal C++
  object already deleted". They now have the window as their context and are cancelled with it. Found by opening and closing the
  window thirty times in one process; the process of the real program ends with its window, so users could not meet it.
* A `settings.json` or `profiles.json` saved by Notepad with a byte-order mark was taken for a damaged file (settings reset, profiles
  set aside). Both are now read with `utf-8-sig`. The same files behaved so in the Tk version.
* The exe carried Pillow's Tk binding (`_imagingtk`), which has no Tk to bind to. It is left out.

## Review step

Entering the Review refills its three tables every time, even when nothing changed. It was measured and left alone: 26 to 62 ms
for an ordinary selection and about 130 ms for 1,200 components over 120 files, and a cache would risk showing stale figures.

## Limits that remain

* **Very large text on a small screen.** With Windows text at about 120 % (11 pt) everything fits (8 px short at the 1,000 px
  minimum width). With 13 pt at 150 % scaling on a 1,280x720 logical screen, the Source card of Data Mapping runs out of height and
  its inputs and chips overlap. Nothing was changed for it; a scroll area around that card would be the remedy.
* **One-file exe.** It unpacks itself at every start (window in 2.1 to 3.2 s) and a copy that is killed instead of closed leaves
  about 55 MB in `%TEMP%\_MEI...`. A one-folder build starts in about a second, but the updater replaces a single file.
* **Windows' 260-character path limit.** A file whose whole path reaches 260 characters cannot be written (the settings file
  included, which is only a warning in the log). The default data folder is `%APPDATA%\DataMapperX`, far from it.
* **Not signed.** The exe has version information (1.2.0, matching `_version.py`) and an icon, but no Authenticode signature.
* **Attribute Agreement** stays behind `ATTRIBUTE_RESULTS_READY` and `ATTRIBUTE_REPORTS_READY` (both False), as in Tk.
* **Not done here.** An installation on a Windows machine that never had a developer tool (a clean environment was used instead);
  opening the reports in Excel and in a PDF viewer by hand (the files were read back with openpyxl and pypdf, and the PDFs were looked
  at as images); an update against GitHub itself, which needs a published release and was not triggered.

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
