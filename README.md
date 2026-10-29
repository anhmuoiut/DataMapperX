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

- The table is exactly what will be exported. Amber rows: a value is missing. Red rows: a sample has the wrong number of files. With more than 20 columns, ‹ › page through them (the Excel file always has every column).
- The **Limits** panel on the right lists every selected component with its Min, Max and Unit, the same limits the Excel file shows beside the data. Click a row of the table to see that row's values next to them; a value outside its limits is marked ▲ (above max) or ▼ (below min).
- The checks at the bottom sum it up (samples found, files per sample, empty cells, rows outside their limits). **Export Excel…** is disabled while a sample has the wrong number of files. **← Back** returns to step 1.

Your last profile, folder, counts and component choices are remembered. The header has a **Dark mode / Light mode** button and the **Help** menu; the version and credit are at the bottom left of the Source card. Shortcuts: `Ctrl+O` folder · `Ctrl+Enter`/`F5` scan · `Esc` cancel · `Ctrl+E` go to Review & Export, then export.

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
  updater.py            check / download / verify / install updates
  ui/                   tkinter windows, built on the sv-ttk (Windows 11) theme
    controls.py         the component lists, the step bar and the check chips
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
