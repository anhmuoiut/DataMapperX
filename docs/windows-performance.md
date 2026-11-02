# Windows performance of the Qt window

Measured on the development machine (Windows 11 Enterprise, Python 3.13, PySide6 6.12, project folder on OneDrive), never on a
Mac. "From source" is `python main.py`; "packaged" is the exe `tools\build.ps1` builds. Times are to the first paint of the
window (from source: after the imports, before the interpreter starts, about 30 ms; packaged: from launching the exe until a
window with the application's title exists). Medians of 5 to 6 runs unless said otherwise; the machine is noisy (±0.3 s), so
compare numbers taken in the same session. The scripts are throw-away and are not in the repository.

## Result

| | Tk (last commit with it, `9bf4758`) | Qt, finished |
|---|---:|---:|
| From source, first paint (same session, alternating) | **1.14 s**, 48 MB | **0.71 s**, 77 MB |
| From source, memory with every page built | 49 MB (Tk builds pages lazily) | 90 MB |
| Packaged one-file exe, window on screen | 3.3 s, 64 MB | **2.3 to 3.0 s**, 105 MB (2.1 to 3.2 s between sessions; see below) |
| Size of the exe | 20.9 MB | 29.5 MB |
| Packaged one-folder build (measured once, not shipped) | n/a | **1.0 s**, 51 MB, 66 MB in 115 files |

The packaged start is dominated by the one-file exe unpacking itself into a temporary folder on every launch (about 2.3 s of the
3.0 s, with the antivirus scanning each file), not by Qt. It varies more between sessions than the from-source start: the same
script gave a median of 3.0 s during the migration and 2.3 s (runs from 2.1 to 3.1 s) in the final review, so compare only
numbers taken in one session. A one-folder distribution starts in about a second, but the
self-updater (`datamapperx/updater.py`) replaces a single exe, so changing the form of distribution is a decision for the
owner and not part of this migration.

## What was found and fixed on the way

| Finding | Cost | Fix |
|---|---|---|
| `Card` created its title `QLabel` without a parent and showed it: Qt opened it as a top-level window for a moment | 0.5 s of the 1.36 s first paint of the prototype | create it with a parent |
| Pages built at start | ~0.1 s | the Review and Validation pages are built after the first paint (`MainWindow.warm_up`) |
| Glyphs the interface font lacks (☀ ☾ ✓ ⚠ ▾ ▸): Windows searches every font for each once | ~0.5 s and ~50 MB the first time any of them is drawn | widgets that must show them name `Segoe UI Symbol` in the stylesheet (it has them); everywhere else only glyphs of the interface font are used (▼ ► ‼ ●) |
| Adding the Validation page to the window loaded those fallback fonts | 54 MB and 0.9 s at the first click | the two glyphs on that page were replaced (above) |
| Updater, access, GRR and statistics imported at start | ~0.15 s | imported when first used |
| Opening the Review with a large selection (1,200 components × 120 files) computed the GRR pre-check and the data checks on the UI thread, as the Tk window did | the window was blocked for about 1 s (2.5 s in the profiler) | from 20,000 components × files (`BIG_REVIEW_CELLS`) the two computations run on a worker thread: the Review opens in 121 ms, says "Checking the data…", and fills in when ready; an answer for a selection that has since changed is dropped. Below that size nothing changes and the figures appear at once |
| Direct-to-exe size: software OpenGL (20 MB), Qt translations, unused plugins and libraries, Pillow's AVIF and WebP codecs | 42.6 MB → 29.5 MB, and less to unpack at every start | filtered in `DataMapperX.spec`; the exe's self-test fails if something needed was removed (it did once: Pillow itself is required by reportlab) |

## Not a problem

* Scanning: the scanner is unchanged. The scan runs on four workers and the interpreter's switch interval is shortened while a
  task runs. Measured on Windows with a synthetic set of 120 files and 1,200 components: the scan took 3.2 to 4.3 s and the longest
  stall of the event loop was 59 ms in one run and 256 ms in another (median 5 ms, 99th percentile 7 ms).
* Tables: `QTableView` with one text model asks only for the rows on screen, so scrolling does not depend on the number of rows.
* The window opens from the same settings, profiles and files as before.
