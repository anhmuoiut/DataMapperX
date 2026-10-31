# DataMapperX → PySide6: Migration Plan

**Status:** the original proposal. Phases 0 and 1 have since been approved and done: see [PYSide6_PHASE1_REPORT.md](PYSide6_PHASE1_REPORT.md) for their results. Where Phase 1 measured something this plan had estimated, §0 and §4.4 are corrected in place. The full migration (Phases 2 to 4) still awaits approval.
**Basis:** commit `4ec1bb2` (v1.2.0), reviewed 2026-10-31. The brief calls the product "DataMatrix"; the repository is **DataMapperX**.
**Evidence labels:** *Measured* = run on an Apple Silicon Mac (Python 3.12, Tk 9.0, PySide6 6.12.0, Qt 6.12.0). *Estimate* = derived from measurements. *Unverified* = could not be checked here. **Nothing was measured on Windows**, the delivery platform, so every size/startup figure is a relative indicator until Phase 1 repeats it there.

---

## 0. Summary

**Verdict: feasible and worth a gated prototype, not yet worth committing to the full rewrite.** The statistical engine is already independent of the GUI, so accuracy risk is low. The cost is a full rewrite of the 6,221-line `datamapperx/ui/` package plus most of the 2,745-line `tests/test_ui.py`.

Three findings the brief did not anticipate:

1. **Attribute Gage R&R does not exist in this codebase.** `README.md` and `docs/statistical-validation.md` list it as unsupported. What can be "preserved" is Process Capability (Cp/Cpk/Pp/Ppk), Variable Gage R&R (one-way and crossed ANOVA), and the PASS/FAIL criteria layer. Attribute GRR would be new statistical work and is out of scope here.
2. **The statistical regression baseline is red on this Mac: 37 of 78 cases fail.** All 37 are floating-point noise (largest relative difference 4e-15, in the 16th significant digit; no string, integer or structural difference). The test compares bit-for-bit. It must be made architecture-tolerant *before* it can guard a migration (Phase 0).
3. **PySide6 is not a performance win by itself, and it costs package size.** Measured: bare-window startup and memory are equal to tkinter's. A packaged Qt app is roughly **2× larger** than today's (**corrected after Phase 1**: measured on a real build of the prototype, 40 → 88 MB uncompressed and about 17 → 33 MB compressed; the first draft of this plan overstated the compressed size, see §4.4). It is the main cost for a one-file exe with self-update, and still far below 150 MB.

Existing pieces the migration must carry over untouched: the remote kill-switch (`access.py` + `status.json`), the self-updater (`updater.py`, `MIN_SUPPORTED_VERSION`), and the `--smoke-test` / `--update` command line. All three are already GUI-agnostic.

**Decisions needed from you:** see §6.4.

---

## 1. Current architecture assessment

### 1.1 Layout (lines of Python)

| Layer | Contents | Lines | GUI-free? |
|---|---|---:|---|
| Core | config, models, profiles, parsing, scanner, exporter, review, sampling, patterns, xlsx, settings, paths, access, updater | ~3,670 | yes |
| Statistics | `statistics/` (Dataset, Study, capability, one-way + crossed GRR, acceptance, evaluation, importers) | 2,280 | yes, pure Python, no numpy |
| Reports | `stat_reports.py` (PDF via reportlab, Excel via openpyxl), `stat_charts.py` | 1,319 | yes, except 3 Tk draw functions |
| UI | `datamapperx/ui/` (13 files) | 6,221 | no, all tkinter |
| Tests | 858 tests, 8,266 lines (`test_ui.py`: 120 tests, 2,745 lines) | | |

Runtime dependencies are only `openpyxl`, `sv-ttk`, `reportlab`. This is already lean; the plan keeps it that way.

### 1.2 What is good and should be kept

- **Engine/UI separation.** Only `app.py` and `selftest.py` import `ui/`. Statistics, parsing, scanning, export and reports can be exercised without a window.
- **Charts are backend-neutral.** `stat_charts.chart_primitives()` produces drawing primitives that Tk Canvas and reportlab both render. A Qt renderer is one more consumer (~100 lines).
- **Immutable analysis snapshots** (`Dataset`, `Study`, `AnalysisResult`) are consumed identically by preview, details and exports.
- **Long-running work already runs off the UI thread** (scan, export, analysis, report, update check) behind one interface, `TaskRunner.run(work, on_success, on_error, on_progress)`.
- **Heavy imports are lazy** (`openpyxl` loads on export; the review and validation pages build on first use).
- **A strong test net exists** (§5.3).

### 1.3 What hurts maintainability

| Issue | Evidence |
|---|---|
| `MainWindow` is a god object: ~100 methods mixing widgets, workflow state, scan/export orchestration, access check and update check | `ui/main_window.py`, 1,544 lines |
| Business logic lives in UI modules | `MappingSource`, `reorder_dataset`, `build_mapping_dataset`, `_int_field` in `ui/validation_workspace.py` (pure, no tk) |
| State lives in tk Variables, so tests assert on widget state (`app.samples_var.get()`) | 59 Variable uses in the two big windows; most of `test_ui.py` |
| ~850 lines of custom Canvas widgets exist only to work around `ttk.Treeview` repaint cost | `DataGrid` (~450), `ActionList` (~400) in `ui/controls.py` |
| Windows-only code paths for DPI, dark-mode detection, title-bar colour | `ctypes.windll`, `winreg`, `DwmSetWindowAttribute` in `app.py`, `ui/theme.py` |
| GC workaround so worker threads don't finalise Tk objects | `ui/tasks.py` |
| Core module contains toolkit code | `draw_tk_chart(s)` in `stat_charts.py` |

### 1.4 Performance baseline (Measured, tkinter app)

| Workload | Time |
|---|---:|
| App start to first paint (import 75 ms + build 465 ms); 227 modules; **200 MB RSS** | ~540 ms |
| Scan 30 text logs × 500 components | 68 ms |
| Scan 30 Excel logs × 500 rows | 230 ms |
| Export `RawData.xlsx`, 30 × 300 | 235 ms |
| Analyse 300 items, one-way GRR (10 samples × 3) | 42 ms |
| Analyse 100 items, crossed GRR (3 operators) | 43 ms |
| Analyse 300 items, capability (30 readings) | 35 ms |
| PDF report, 20 GRR items with charts | 246 ms |
| Excel report, 20 GRR items with charts | 193 ms |

**Conclusion: there is no backend hot spot to optimise.** Anything a migration claims to speed up must be the interface, and the interface is already smooth (the changelog documents the custom grid fix).

### 1.5 State of the safety net on this Mac (Measured)

`684 passed, 37 failed` (non-UI, 3.7 s); full suite `802 passed, 39 failed, 17 skipped` (85 s).

- 37 failures: the bit-exact baseline (above).
- 2 UI failures are macOS-specific and unrelated to statistics: the window-geometry test assumes room for a 40 px title bar (the window lands 33 px down under the Mac menu bar), and the GRR legend-colour test reads back a different tile colour on macOS than the one the app sets.
- 17 skips: all need the confidential `samples/` folder (gitignored). This includes the **11 tests that compare the engine with the five supplied GRR report studies**, the strongest accuracy check in the project. They must be run on a machine that has `samples/`.
- Cause of the float noise is *Unverified*: it may be CPU architecture or math-library behaviour (this Mac is Apple Silicon; CI is Windows x86-64) or Python 3.12 vs CI's 3.13. It could not be told apart here.

---

## 2. Recommended PySide6 stack

### 2.1 Choices

| Area | Recommendation | Why / rejected alternatives |
|---|---|---|
| Binding | **`PySide6-Essentials`** (QtCore, QtGui, QtWidgets, QtTest) | The full `PySide6` wheel adds WebEngine, Charts, 3D, etc., none needed. |
| UI technology | **Qt Widgets**, not QML/Qt Quick | Dense forms and tables; QML adds a GPU scene graph and more modules for no benefit here. |
| Styling | **Fusion style + `QPalette` built from the existing `Palette` tokens + one small QSS file only for custom named widgets** (card, step bar, chip, banner) | Reuses the current light/dark colours. Applying QSS to every widget disables the native style and costs speed, so keep it scoped. |
| Third-party UI kits (qt-material, qdarktheme, QFluentWidgets, …) | **Not used** | Extra dependency, licence review, and resource cost with no capability the brief needs. |
| Dark mode | `QStyleHints.setColorScheme()` for system/Light/Dark | Verified present in Qt 6.12. Replaces the `winreg` + `ctypes` code. |
| Windows 11 look | Evaluate Qt's native `windows11` style in Phase 1 | *Unverified*: it is not available on macOS builds, so it could not be checked here. |
| Tables | `QTableView` + one read-only `QAbstractTableModel` | Replaces `DataGrid`; rows are virtual, so cost does not grow with row count. Row/cell tags map to `BackgroundRole`. |
| Add/remove list (+ / ×) | `QListView`/`QTableView` + a paint/click **delegate** | Replaces `ActionList`; avoids one widget per row. |
| Charts | Paint existing `chart_primitives()` with `QPainter` in a plain `QWidget` | No `QtCharts`, no matplotlib. PDF and Excel keep using reportlab/openpyxl unchanged. |
| Background work | `QThreadPool` + `QRunnable`, results delivered by signals | Keep the same `run(work, on_success, on_error, on_progress)` signature so call sites barely change; the GC workaround disappears. |
| Tests | `pytest` + `QT_QPA_PLATFORM=offscreen` + `QtTest` | Headless: UI tests stop opening real windows. No `pytest-qt` needed at first. |
| Python | Keep `>=3.11` | PySide6 6.12 ran on 3.12 here; CI uses 3.13. |

Dependency change: remove `sv-ttk`; add `PySide6-Essentials`. `openpyxl` and `reportlab` stay.

### 2.2 Reuse / migrate / retire

| Keep unchanged | Adapt lightly | Rewrite (port) | Retire |
|---|---|---|---|
| config, models, profiles, parsing, scanner, exporter, review, reporting, sampling, patterns, xlsx, utils, paths, log_setup, settings, access, updater, `grr.py`, `statistics/*`, `stat_reports.py`, `status.json`, `MIN_SUPPORTED_VERSION` | `app.py` (QApplication; drop DPI ctypes), `selftest.py` (build Qt windows), `stat_charts.py` (move Tk drawing out, add QPainter drawer), `settings.py` (window geometry: `saveGeometry`) | `ui/main_window.py`, `validation_workspace.py`, `controls.py` (StepBar, ChipRow), `sample_wizard.py`, `profile_dialog.py`, `validation.py`, `dialogs.py`, `update_dialog.py`, `duplicate_dialog.py`, `access_dialog.py` | `sv_ttk`, `ui/theme.py` Windows hooks, `ui/tasks.py` GC hack, `DataGrid`/`ActionList` canvas code, `UndoableEntry` (QLineEdit has undo) |

Rule: **no formula, constant, rounding or report layout changes.** The statistics, `stat_reports.py` tables and chart primitives are not edited.

### 2.3 Target structure (no new framework)

```
datamapperx/
  (core, statistics, reports: unchanged)
  workflow.py        NEW  scan/selection/preview/export state and logic extracted from MainWindow; no widgets
  ui/                     Qt views: windows, dialogs, 8 small reusable widgets, models, one theme module + styles.qss
```

No MVC/MVVM framework, no dependency injection, no plugin system.

---

## 3. UI/UX improvements

Keep the workflow and information architecture exactly: **Select → Review & Export**, plus **Validation & Reports** (Data, Analysis, Results, Report). The migration is not the time to redesign behaviour.

- **Shell:** `QMainWindow` with a slim header (title, Dark/Light toggle, Help menu), a `QStackedWidget` (Data Mapping | Validation & Reports), and a `QStatusBar` with progress. Resizable `QSplitter` panes; layout remembered with `saveGeometry()/saveState()`.
- **Compact and consistent:** one spacing scale (4/8/12 px), one system UI font (drop hard-coded Segoe UI so Windows and macOS both look native), 28 px table rows, one primary-button style, tinted status chips (PASS/CONDITION/FAIL/missing) reusing the current colours.
- **Reusable kit (8 widgets):** `Card`, `StepBar`, `Chip`, `Banner`, `DataTable` (+ model), `ActionListView`, `ReadOnlyText`, `Dialog` base.
- **Native behaviour:** platform file dialogs, native menus, automatic per-monitor HiDPI, system dark mode, existing shortcuts (Ctrl+O, Ctrl+Enter/F5, Esc, Ctrl+E) via `QAction`.
- **Sample wizard:** text highlighting via `QPlainTextEdit` extra selections instead of tk tags.
- **Deliberately not done:** animations, translucency/blur, custom title bars, QML.
- **Optional, later, as a separate decision:** lift the 500-row / 20-column preview limits (`config.PREVIEW_ROW_LIMIT`, `PREVIEW_COLUMNS_PER_PAGE`). A virtual model makes this cheap, but it changes behaviour, so it is not part of the port.

---

## 4. Performance optimisation opportunities

### 4.1 Toolkit comparison (Measured)

| | tkinter | Qt |
|---|---:|---:|
| Bare window, start to shown | 279–312 ms, 105 MB | 265–300 ms, 103 MB |
| Qt: import + `QApplication` + table window to first paint | n/a | ~90 + ~105 + ~160 ms, 113 MB |
| Table with 100,000 × 20 cells: `setModel` | n/a (paged to 500 rows) | 38 ms, 132 MB |
| Table paint cost per scroll step | ~15 ms | ~18 ms for 500 rows and for 100,000 rows |

Reading this honestly: the toolkits start equally fast; Qt's table paint cost **does not grow with row count**; scroll timings on macOS were dominated by display sync and **should not be read as a win for either side**. The full-app Qt startup cannot be known until the prototype exists; expect "about the same as today", not a large gain.

### 4.2 Worth doing (in order of value)

1. **Model/view tables with cached strings.** Return only the roles used (`Display`, `Alignment`, `Background`); format values once, not in `data()`.
2. **Keep lazy construction.** Build the Review and Validation pages and rarely used dialogs on first show; import only `QtCore/QtGui/QtWidgets` (avoid `QtNetwork`, `QtSvg`).
3. **Keep heavy imports lazy** (`openpyxl`, `reportlab`, statistics) so startup does not pay for them.
4. **Charts:** render each `ChartSpec` to a cached `QPixmap`, and re-render only after a resize settles.
5. **Package trimming (Measured in Phase 1: −10 MB):** remove Qt's translations (7 MB) and the image-format plugins (2.6 MB; PNG is built into QtGui). Excluding the `QtNetwork`/`QtDBus`/`QtSvg` modules saved only 3 MB, because PyInstaller's PySide6 hook still bundles those frameworks.

### 4.3 Not worth doing

Scanning, statistics and report generation (§1.4: 35–250 ms for realistic loads). Parallelising or rewriting them would add risk for no visible gain.

### 4.4 Packaging (Measured on macOS, PyInstaller one-dir, same excludes as `DataMapperX.spec`)

> **Correction.** The first draft of this section compared `zip -r` sizes. On macOS, `zip -r` follows the symlinks inside
> Qt's frameworks and stores their contents twice, so it overstated the compressed Qt size (74 MB instead of about 33 MB).
> The table below replaces it. Uncompressed size comes from `du` (symlinks counted once); compressed size from `tar.gz`
> (symlinks preserved), the better proxy for a Windows one-file exe, which has no such duplicates.

| Build (a real window, built from its entry point) | Folder | Files | Compressed (tar.gz) |
|---|---:|---:|---:|
| **Current DataMapperX (tkinter)** | **40 MB** | 474 | **17 MB** |
| Qt prototype, default PyInstaller hooks | 91 MB | 272 | 33 MB |
| Qt prototype, unused Qt modules excluded | 88 MB | 266 | 33 MB |
| Qt prototype, plus Qt translations and image plugins removed | 78 MB | 156 | 30 MB |

Qt costs about **+13 to +16 MB compressed** and roughly doubles the uncompressed folder. It also ships *fewer* files than
tkinter (156 to 272 against 474). `DataMapperX.spec` optimises for few files (antivirus scans each extracted file) and a
small download (the updater fetches the whole exe), so this still touches the existing design, but it is a modest change
and well inside the 150 MB target. Windows will differ (DLLs instead of frameworks, a one-file exe unpacks to a temporary
folder on every start); Gate 1 must repeat the measurement there.

---

## 5. Migration steps and risks

### 5.1 Sequence

Work on a branch; the tkinter app stays shippable until cutover. Each phase ends at a gate (§5.3 layers) and nothing proceeds on a red gate.

| Phase | Work | Size |
|---|---|---|
| **0. Make the safety net trustworthy** *(needs your approval, touches tests only)* | Make the baseline test compare floats with a tight tolerance (relative 1e-12) while staying exact for strings, ints, tuples, key order and structure. Never regenerate the fixtures. Prove it still has teeth by flipping a constant (e.g. a `d2` value) and confirming failure. Run the 11 reference tests on a machine with `samples/` and record the result as the pre-migration anchor. | small |
| **0b. Decouple (on tkinter, under the 120 existing UI tests)** | Move the pure helpers out of `validation_workspace.py`; move `draw_tk_chart(s)` out of `stat_charts.py`; extract `workflow.py` from `MainWindow`. Behaviour-preserving. | medium |
| **1. Prototype (spike)** | `QApplication` bootstrap, theme from `Palette`, `StepBar`, `DataTable` model, `QThreadPool` runner, Step 1 screen on real scan data. Build with PyInstaller **on Windows** and measure. | small |
| *Gate 1: go / no-go* | Proposed thresholds (adjust to taste): packaged size ≤ 2.5× today after trimming; cold start of the one-file exe ≤ 1.5× today; RSS ≤ today; smooth scrolling at 100k rows; antivirus does not flag the build. | |
| **2. Data Mapping** | Step 1 and Step 2 screens, profile manager, sample wizard, duplicate / update / access / about / export-done dialogs, and the shared widget kit. | largest (≈ 70% of UI lines) |
| **3. Validation & Reports** | Data, Analysis, Results (QPainter charts), Report; criteria dialogs. | large (≈ 25% of UI lines) |
| **4. Cutover** | New entry point, update `DataMapperX.spec` (hidden imports, excludes, icon), CI (add `QT_QPA_PLATFORM=offscreen`), README, `--smoke-test` in Qt; delete tkinter, `sv-ttk`, `tasks.py` GC hack. | small |

Effort *(rough, order-of-magnitude, not a commitment)*: on the order of 1.5–2 months for one developer; the UI is ~6,200 lines to rewrite and ~2,700 lines of UI tests to port, partly offset by ~850 lines of custom canvas code that Qt provides. AI assistance shortens writing, but review and Windows verification do not shrink in proportion.

### 5.2 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| One-file startup (unpacking ~80 MB on every start) and antivirus on Windows | Medium | Medium | Measure at Gate 1; trim Qt; fall back to one-dir distribution if the gate fails. Size itself is no longer a concern (§4.4). |
| Subtle UI behaviour drift (duplicate-component flow, access gating, update flow, validation staleness) | Medium | Medium | Map each of the 120 UI tests to a Qt test and track them in a table; use README/CHANGELOG as a feature checklist. |
| UI test rewrite is large | Certain | Medium | Phase 0b first: most assertions move to widget-free `workflow` tests. |
| Statistical drift | Low | High | Engine untouched; layered gates (§5.3). |
| Bit-exact baseline stays fragile across machines | Certain until fixed | Medium | Phase 0. |
| Self-update with a larger exe | Low | Medium | Updater logic unchanged; test download/replace at the new size. |
| PySide6 licensing (LGPL v3) | Low | Medium | Normally fine for an internal tool using dynamic linking, but confirm with whoever owns licensing at your company; this is not legal advice. |
| macOS vs Windows visual differences | Medium | Low | Windows is the delivery platform; Mac is for development unless you say otherwise (§6.4). |

### 5.3 Regression protection for statistical accuracy

| Layer | What | When |
|---|---|---|
| 1. Engine and report tests (≈ 640 passing today, none edited) | `test_statistics` (58), `test_study` (18), `test_grr` (20), `test_workspace_logic` (29), `test_stat_reports` (31), `test_dataset`, … | every commit |
| 2. Baseline (78 cases) | Full `analyze()` output, details text, charts, summary rows, exact structure; tolerance fix in Phase 0 | every commit |
| 3. Reference studies (11 tests) | Engine vs the five supplied GRR report studies, needs `samples/` | before Phase 1, at each gate, at cutover, on a machine that has the data |
| 4. Report golden check | Generate PDF/Excel from fixed inputs before and after; compare Excel cell values exactly and PDF text with `pypdf` (already a dev dependency) | each gate |
| 5. Display = result | New tests: every figure in the Qt results table equals the formatted engine value; chart items drawn = primitives produced | Phases 2–3 |
| 6. Packaged smoke test | `DataMapperX.exe --smoke-test` already builds all four statistical reports, scans and exports | every build |

Hard rules: no edits to the statistics modules or to `tests/fixtures/baseline/*.json`; the migration branch may not change any layer-1 or layer-3 test.

---

## 6. Claude's independent recommendations

### 6.1 Where I agree and differ with the brief

- **PySide6 + Qt Widgets + light QSS: agreed.** I found no better lighter option within PySide6; QML and third-party kits are heavier and unnecessary.
- **"Fast startup, low memory":** PySide6 does not deliver this by itself (§4.1). Treat them as "no regression" goals, and treat package size as the real cost.
- **"Preserve Attribute Gage R&R":** it does not exist (§0). Treated as out of scope.
- **Distribution:** nothing is implemented now. The only design constraint carried forward is that `access.py`, `updater.py`, `status.json` and the CLI flags stay GUI-independent, which they already are.

### 6.2 Recommended course

1. **Approve Phase 0 and Phase 1 only.** Both are small and reversible, and they answer the two real unknowns (package size on Windows, trustworthy baseline). Decide on Phases 2–4 at Gate 1.
2. **Extract `workflow.py` while still on tkinter** (Phase 0b). It turns the Qt port into a thin view layer and lets most UI tests run without widgets. The alternative, a direct port, is faster to start but leaves the `MainWindow` coupling in place; I would not choose it.
3. **Do not add `pytest-qt`, Qt Charts, matplotlib or any theme library.** `QtTest` and `QPainter` are enough.
4. **Keep the 500-row / 20-column preview limits at first.** Lifting them is a feature change, not a port.
5. **Keep one-file distribution until measured**, then decide one-file vs one-dir on data.

### 6.3 Not verified here

Windows size, startup and antivirus behaviour; the Qt `windows11` style; the cause of the float differences (architecture vs Python version); whether all 120 UI tests port one-to-one; PySide6 licensing for your distribution.

### 6.4 Decisions needed

1. Approve **Phase 0** (loosen float comparison in the baseline test; extract pure logic)? It edits tests and moves code, but changes no calculation.
2. Is **macOS a delivery target** or only your development machine? This decides CI and styling effort.
3. Confirm **Attribute Gage R&R is out of scope**.
4. Acceptable **exe size and startup** on Windows (to set Gate 1 numbers)?
5. Do you have a **Windows machine with `samples/`** for the reference-study runs and the Gate 1 measurements?

---

### Appendix: how the figures were produced

Benchmarks ran from scripts kept outside the repository (scratch directory): `bench_tk.py`, `bench_qt.py`, `bench_qt_paint.py`, `bench_workload.py`, and PyInstaller builds with the same excludes as `DataMapperX.spec`. Start-up figures are medians of five runs after a warm-up. Synthetic data followed realistic sizes (10 samples × 3 repeats, 300 to 500 test items). Float differences were classified by walking the baseline JSON against current output. The scripts can be added under `tools/` if you want them kept.
