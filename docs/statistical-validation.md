# Statistical validation: methods and comparison status

Reviewed 30 October 2026. This implementation is not an official Minitab certification or a Jabil approval. Matching the available report precision establishes a limited comparison for the identified data and settings; it does not establish equivalence for every study design.

## Reference material reviewed

- **JABIL HCM Gage R&R Work Instruction**, document 50-TE30-GEN-INS-00046, revision I, released 13 April 2026. The supplied file is `3c5c7b1a-da86-47db-ada0-e9e2c9243bbe.pdf` (30 PDF pages, including cover and document history).
- **GR&R for FIXTURE-FT-FX-1163-M12-#01-R01 Jabil ID P42657.pdf**, study dated 22 October 2026 (9 PDF pages, with the last page blank). This is an image-only report, inspected from rendered pages. It contains five one-way ANOVA studies with 10 parts and 3 repetitions each.
- **CPK REPORT for ICT machine_MY47450178R.pdf**, report dated 31 December 2025 (7 PDF pages). This is a PDF rendition of the PowerPoint named in the request. It contains five capability plots and a summary. No PowerPoint source was supplied.

The documents are evidence and layout references. Their procedural instructions do not grant the application authority to approve equipment, change customer specifications, or publish company data. Raw logs and local rendered reference material remain local; `samples/` and `tmp/reference-review/` are excluded from Git.

## Implemented statistical model

### Normal process capability

The user chooses the within-sigma estimator explicitly. For individual observations in input order, `MR_i = abs(x_i - x_(i-1))` and `sigma_within = mean(MR_i) / 1.128` (moving range length 2). For identified rational subgroups, `d = sum(n_i - 1)`, `S_p = sqrt(sum((x_ij - mean_i)^2) / d)`, and the bias-corrected estimate is `S_p / c4(d + 1)`. The correction can be disabled. The overall estimate is the sample standard deviation across all observations, with denominator `N - 1`. The supported choices follow Minitab's [Normal Capability Analysis estimation methods](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/capability-analysis/how-to/capability-analysis/normal-capability-analysis/methods-and-formulas/methods/).

`Cp = (USL - LSL) / (6 * sigma_within)` and `Cpk` is the smaller of the available upper and lower distances from the mean divided by `3 * sigma_within`. `Pp` and `Ppk` use the overall estimate instead. Cp/Pp require both limits; one-sided Cpk/Ppk use the available side. Zero denominators produce N/A rather than infinity. The acceptance decision is based on the unrounded Cpk, strictly greater than the configured threshold (default 1.33).

Repeated measurements of one serial number are suitable part groups for a measurement-system study. They are **not automatically rational subgroups for process capability**: the user must select a subgroup field that represents the actual sampling design. Moving-range estimates depend on the observation order. A capability result does not establish process stability, independence, or normality; those assumptions require engineering review. Minitab explains this sampling distinction in [Using subgroups to assess process capability](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/capability-analysis/supporting-topics/data-and-data-assumptions/using-subgroups-to-assess-capability/).

### Variable Gage R&R: balanced one-way ANOVA

For `a` distinct parts, each with `r` repetitions, the model is `x_ij = mean + Part_i + error_ij`, with random part effects. Degrees of freedom are `a - 1` for Part, `a * (r - 1)` for Error, and `a * r - 1` for Total. The engine uses:

- `SS_Part = r * sum((mean_i - grand_mean)^2)`.
- `SS_Error = sum((x_ij - mean_i)^2)`.
- `MS = SS / DF`; `F = MS_Part / MS_Error` when its denominator is positive.
- `variance_repeatability = MS_Error`.
- `variance_part = max((MS_Part - MS_Error) / r, 0)`.
- `variance_total = variance_repeatability + variance_part`.

With one appraiser/system, `sigma_GRR = sqrt(MS_Error)` and reproducibility is not independently estimable. This is the no-operator one-way model described in Minitab's [method of analysis](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/methods-and-formulas/method-of-analysis/). Negative estimated part variance is reported as zero with an explanation, following the nonnegative component convention in Minitab's [Gage R&R table formulas](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/methods-and-formulas/gage-r-r-table/).

`StudyVar_GRR = k * sigma_GRR` (default `k = 6`), `%SV/Tol = 100 * StudyVar_GRR / (USL - LSL)`, and `%StudyVar = 100 * sigma_GRR / sigma_total`. A finite NDC is `max(1, floor(1.41 * sigma_part / sigma_GRR))`. NDC is N/A when the denominator is zero. Minitab explicitly describes [truncation and the minimum of one](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/supporting-topics/gage-r-r-and-wheeler-s-emp-studies/using-the-number-of-distinct-categories-in-a-gage-r-r-study/).

The diagnostic R and Xbar charts use a separate range-based estimate, `sigma_chart = Rbar / d2(r)`, matching the supplied report. R limits are `Rbar * max(0, 1 - 3*d3/d2)` and `Rbar * (1 + 3*d3/d2)`; Xbar limits are `grand_mean +/- 3*sigma_chart/sqrt(r)`. These chart estimates do not replace the ANOVA variance components. Minitab distinguishes [Rbar and pooled standard deviation chart estimators](https://support.minitab.com/en-us/minitab/help-and-how-to/minitab-environment/settings-and-defaults/control-charts-and-quality-tools/estimating-standard-deviation/).

### Variable Gage R&R: balanced crossed ANOVA (two or more operators)

When two or more distinct Operators measured the same Test Item on the same tester and slot, they form one crossed study instead of separate one-way studies. Separating them would drop reproducibility and can pass a gage that the crossed study rejects: on a seeded synthetic study of 10 samples x 3 operators x 3 trials with operator offsets, the three separate one-way analyses gave %StudyVar of 25.5, 25.5 and 22.5 (NDC 5, 5, 6), whereas the crossed analysis gives %StudyVar 61.4, %Contribution 37.8, %SV/Tol 29.2 and NDC 1.

For `p` samples, `o` operators and `r` repetitions, the model is `x_ijk = mean + Sample_i + Operator_j + (Sample x Operator)_ij + error_ijk` with random effects, degrees of freedom `p-1`, `o-1`, `(p-1)(o-1)` and `p*o*(r-1)`. The interaction is tested as `F = MS_Int / MS_Error` and removed when its p-value is at least `interaction_alpha` (default 0.05, Minitab's default "alpha to remove interaction term"); the reduced model pools its sum of squares into error. Variance components are:

- With interaction: `repeat = MS_Error`, `int = max((MS_Int - MS_Error)/r, 0)`, `oper = max((MS_Oper - MS_Int)/(p*r), 0)`, `part = max((MS_Part - MS_Int)/(o*r), 0)`.
- Without interaction: `repeat = MS_Pooled = (SS_Int + SS_Error)/(df_Int + df_Error)`, `oper = max((MS_Oper - MS_Pooled)/(p*r), 0)`, `part = max((MS_Part - MS_Pooled)/(o*r), 0)`.
- `reproducibility = oper + int`, `GRR = repeat + reproducibility`, `total = GRR + part`. %Contribution, Study Var, %StudyVar, %SV/Tol and NDC then use the same definitions as above.

The full ANOVA table (with the interaction) is kept in the details and reports whenever the interaction was tested and removed. Operators who did not measure every sample, or unequal repetition counts, are rejected with an explanation rather than analyzed separately; map a fixture or nest to Slot or Tester if it should be evaluated and approved on its own (work instruction 8.7.2 also allows nests to stand in for operators in a crossed study, in which case map them to Operator). The R and Xbar charts have one point per sample/operator cell, and Measurement by Operator and Sample x Operator Interaction charts are added.

**Verification status.** The formulas follow Minitab's published [method of analysis](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/methods-and-formulas/method-of-analysis/) and [Gage R&R table](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/methods-and-formulas/gage-r-r-table/) pages. They are tested against a hand-calculated example and a separately written textbook calculation (interaction sum of squares by subtraction, closed-form F(2, d) p-value) on four datasets covering retained and removed interaction and truncated components. No Minitab output for a crossed study was available, so equivalence with the Minitab software itself has not been demonstrated; exporting the Minitab session output of one real crossed study is the remaining step.

### Acceptance profiles

Each metric is displayed independently. Default percentage reference bands are `<10` PASS, `10` through `30` CONDITIONAL PASS, and `>30` FAIL. NDC is acceptable at 5 or greater. Only the explicitly selected decision metric determines the conclusion; metrics are not automatically combined.

**Customer criteria (development build; an optional layer, off by default).** Acceptance criteria sit on top of the statistics and never change a calculated value. In the Validation & Reports workspace no criteria are applied until the user chooses a customer (or a Cpk/Ppk limit for capability); without them the results and reports are statistics only. Minitab is the reference for the methods; the work instruction is background, and the presets below are only starting points taken from it. In the application, Gage R&R acceptance is chosen per customer through `AnalysisConfig.criteria`, a tuple of `Criterion(metric, enabled, pass_limit, fail_limit)` for %SV/Tol, %Study Var and NDC. For a percentage, PASS is below `pass_limit`, FAIL is above `fail_limit` and anything between is CONDITIONAL PASS; for NDC, PASS is at or above `pass_limit`, FAIL is below `fail_limit` and anything between is CONDITIONAL PASS. The overall result is the worst of the applied (`enabled`) metrics: any FAIL gives FAIL; otherwise an applied metric that cannot be evaluated gives N/A; otherwise any CONDITIONAL PASS gives CONDITIONAL PASS; otherwise PASS. Customers and their limits are edited in the Criteria dialog and stored in the user settings (`customer_criteria`, only entries that differ from the built-in presets). Built-in presets follow the supplied work instruction: SolarEdge and Zebra apply only %SV/Tol (8.6.1.1.2), SES applies NDC and %SV/Tol (8.6.1.1.3), and Jabil applies all three (8.6.1, table 8.12.2, 8.15.2). Keurig (8.6.1.1.4) and Hanwha (8.6.1.1.5) have rules that are not a per-metric worst-of (Keurig lets NDC decide only inside a %SV band), so they are left for the user to define. The work instruction is ambiguous at NDC = 4 (the label table says "> 4" for Pass and "< 4" for Fail; 8.6.1.1 says "lower than 5 is not appropriate"); the presets use 5. Without `criteria`, the earlier single decision-metric behaviour below is kept for programmatic use.

**Review flag.** The decision is never changed by another metric, but when the result is PASS or CONDITIONAL PASS and an informational metric (one that is not applied) would fail on its own limits, the result carries a warning, a **Review** column entry in the table and in the PDF/Excel summary, and a notice above the result table. This matters when a wide tolerance makes %SV/Tol small while the gage cannot tell the sampled parts apart: the supplied Meas Vin study has %SV/Tol 0.12 but %StudyVar 55.59 and a derived NDC of 2. The flag does not say the study is wrong; it says the %SV/Tol decision alone may be misleading.

The SolarEdge profile uses **only %SV/Tol** for the conclusion. %StudyVar and NDC are informational and cannot override it. This follows supplied work-instruction clauses 8.6.1.1.1 and 8.6.1.1.2 (PDF page 12; printed page 11). Clauses 8.6.1.2 and 8.6.1.3 (PDF page 13; printed page 12) define the strict 10% boundary. The older, separate `grr.py` pre-check used `<=10%`; the new statistical module applies the requested `<10%` boundary.

## Actual comparison with the supplied Gage R&R report

The repository's local `samples/Function test logfile/` contains the exact 10-part, 30-file study: its serials, chart means/ranges, ANOVA F values and evaluation figures match the supplied report. All five items were recalculated independently from the raw readings using centered sums of squares, before comparison with the new engine. No reference constants are embedded in application calculations.

| DCDC5W test item | PDF %SV/Tol | Raw-data calculation | Absolute difference from PDF | PDF %StudyVar | Raw-data calculation | Absolute difference from PDF | Derived NDC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Meas Vin | 0.12 | 0.124241592 | 0.004241592 | 55.59 | 55.592009044 | 0.002009044 | 2 |
| Meas 11V | 0.37 | 0.368380781 | 0.001619219 | 2.96 | 2.961765501 | 0.001765501 | 47 |
| Iin @ Load | 0.41 | 0.413976665 | 0.003976665 | 11.54 | 11.540687269 | 0.000687269 | 12 |
| Iin @ No Load | 0.33 | 0.326815428 | 0.003184572 | 5.02 | 5.017566152 | 0.002433848 | 28 |
| Iout | 0.27 | 0.273654304 | 0.003654304 | 20.49 | 20.493767733 | 0.003767733 | 6 |

All ten displayed percentages agree after rounding to the report's two decimals (half-unit rounding tolerance 0.005 percentage points). The raw component label for the fourth item contains two spaces between `No` and `Load`; the normalizer preserves it.

| Test item | Raw MS_Error (repeatability variance) | Raw part variance | Raw total variance | Raw F | PDF F |
| --- | ---: | ---: | ---: | ---: | ---: |
| Meas Vin | 6.860432525149114e-7 | 1.533822742945007e-6 | 2.219865995459918e-6 | 7.707256739 | 7.70726 |
| Meas 11V | 3.769566666667128e-7 | 4.293475167901274e-4 | 4.297244734567941e-4 | 3417.951242062 | 3417.95 |
| Iin @ Load | 8.675944379101934e-11 | 6.427325446140304e-9 | 6.514084889931323e-9 | 223.246426393 | 223.246 |
| Iin @ No Load | 1.128162919320367e-10 | 4.469828394097246e-8 | 4.481110023290450e-8 | 1189.612473664 | 1189.61 |
| Iout | 8.320741995352610e-11 | 1.897947495299139e-9 | 1.981154915252665e-9 | 69.429504112 | 69.4295 |

The report's ANOVA and variance tables print only seven decimal places for small numbers: several nonzero components appear as `0.0000000`. Those rounded cells cannot establish full-precision equivalence. Tests compare both the printed rounding interval and independently derived aggregate values from the raw logs. The five F statistics agree to their printed precision. Gage standard deviations also agree within half the last printed decimal (5e-8).

For Vin the independently calculated Rbar is `0.001211547851494288`, R UCL is `0.003118823299694274`, and Xbar limits are `349.9974950442964` and `349.99997403122444`, matching printed limits `0.003119`, `349.997495`, and `349.999974`.

**NDC status:** the supplied PDF does not print an NDC result. The NDC column above is an independently derived result using the documented Minitab convention, not a comparison with a displayed Minitab NDC. Exporting the original Minitab worksheet/output including NDC is still needed to close that comparison.

## Capability reference status

| Test item | Supplied PDF Cpk | Raw-data reproduction status |
| --- | ---: | --- |
| C3 | 18.42 | Unverified: original 30 observations/order/subgroup configuration unavailable |
| C4 | 196.51 | Unverified: original 30 observations/order/subgroup configuration unavailable |
| C5 | 959.42 | Unverified: original 30 observations/order/subgroup configuration unavailable |
| l5 | 96.13 | Unverified: original 30 observations/order/subgroup configuration unavailable |
| l6 | 291.86 | Unverified: original 30 observations/order/subgroup configuration unavailable |

The local ICT examples are a different 10-part/30-file study and do not contain these five component labels. Reconstructing synthetic readings from the report's rounded summary statistics would not prove equivalence. Mean, within/overall sigma, Cp/Cpk and Pp/Ppk are covered by independent known synthetic datasets instead. To complete the five report comparisons, supply the original observations, specification limits, observation order, rational subgroup IDs/size and the Minitab estimation options.

## Automated comparison and scope

`tests/test_stat_reference.py` performs optional local comparisons against the five FT items when the confidential raw folder is available. It skips with an explicit reason in a clean checkout rather than distributing company raw measurements. `DATAMAPPERX_REFERENCE_LOGS` can point to the same study in a different folder. Independent aggregate golden checks use configurable `DATAMAPPERX_REFERENCE_ABS_TOL` and `DATAMAPPERX_REFERENCE_REL_TOL`; printed-report checks use half the last displayed unit. Assertion output includes actual values, expected values and differences.

The remaining statistical tests use redistributable synthetic data and run without the reference PDFs or proprietary logfiles. UI/report tests verify that display and exports consume the same result objects; raw measurement values are not changed for report generation. The final test run and counts are recorded in the implementation handoff.

Unsupported designs include nested multi-appraiser studies, unbalanced GRR (crossed or one-way), one-sided tolerance for %SV/Tol, historical process sigma, nonnormal transformations, attribute GRR, confidence intervals and misclassification probabilities. Each tester and slot remains a separate study. Operators of the same tester and slot are analyzed together as a crossed study; one-system estimates of different testers or slots must not be represented as a pooled reproducibility estimate. Two-sided tolerance is required for GRR %SV/Tol. The existing desktop Tk application is a Windows desktop application, not a mobile website.

## Implementation map and verification

- `datamapperx/statistics/`: `Dataset`, `Study`, study design, the RawData.xlsx importer, pure normalized observation models, mapping, validation, numeric primitives, capability, one-way and crossed ANOVA, acceptance profiles and review flags, shared formula explanations and calculation details.
- `datamapperx/ui/validation_workspace.py`: the Validation & Reports workspace (Data, Analysis, Results, Report). It builds an immutable `Dataset` from the Data Mapping scan or a RawData.xlsx, keeps the settings in a `Study`, runs the statistics on a background task from a captured `StatisticsPlan`, judges them with the customer criteria (`Study.evaluate`) and marks results stale when anything the numbers depend on changed. `datamapperx/ui/validation.py` holds its dialogs (field mapping, file assignments, customer criteria, analysis conditions).
- `datamapperx/ui/main_window.py`: adds the Validation & Reports workspace beside Data Mapping while preserving selection, duplicate mapping, preview, quick pre-check, limits and raw Excel export. Data Mapping tells the workspace when its data changed (a counter, so an in-place change of a duplicate choice is seen); the workspace never writes to it.
- `datamapperx/stat_charts.py` and `datamapperx/stat_reports.py`: shared chart geometry and PDF/Excel reports modelled on Minitab's Gage R&R and Process Capability reports (ANOVA, Variance Components, Gage Evaluation, NDC and the Gage R&R graphs; Process Data, Overall and Potential (Within) Capability, Performance (PPM) and the histogram). The tables are built once from the finished result (`ReportTable`) and used by the PDF, the Excel workbook and the application's Details tab; CPL, CPU, PPL, PPU and PPM are derived from the engine's mean, sigmas and the specification limits. No PASS/FAIL, criteria or explanations are printed. Excel cells keep the full value of every statistic; atomic export.
- `tests/test_statistics.py`, `tests/test_stat_reference.py`, `tests/test_stat_reports.py`, and additional cases in `tests/test_ui.py`: independent known-data calculations, edge cases, actual reference studies, formula/report consistency, optional workflow, mapping identity, order, filtering, export, stale background answers and desktop geometry.
- `requirements.txt`, `pyproject.toml`, `DataMapperX.spec`: add ReportLab and retain its runtime resources/Pillow in packaged applications. No executable release was published.

The README documents the workflow. Existing local access/update/pre-check changes were retained. Confidential raw logs and generated review files are excluded from Git. Reports always export all analyzed item/system groups, regardless of the result-table search/filter. There is no PPTX export.

Desktop tests exercise light/dark themes and the supported 1000 × 680 layout. Direct screenshot capture through the computer-use tool timed out awaiting app approval; no screenshot-based desktop visual claim is made. Generated PDF pages were rendered and inspected directly; summary, detailed metrics, four study charts and methodology text were checked. Excel tests inspect saved values, number formats, chart objects, source identities and formula-injection protection.

Final verification: **571 tests passed, 0 skipped**, including 91 pure-engine cases, 11 comparisons with the actual FT dataset, 16 report/chart cases, and six new optional-validation UI cases. The three warnings are existing openpyxl tests intentionally using missing styles and invalid Excel dates. `python -m ruff check datamapperx tests` passed. Git's diff whitespace check passed with Windows CRLF recognized. PDF parser dependencies are included in `requirements-dev.txt` so normal developer installs exercise the PDF assertions.

Run after installing `requirements-dev.txt`: `python -m pytest` and `python -m ruff check datamapperx tests`. The confidential reference tests explicitly skip in checkouts without the original FT study; all synthetic, mapping/export and report/UI checks remain available there.

## Report runtime repair

The open source application used `DataMapperX-ui-venv`, which did not have ReportLab installed; earlier verification had supplied it through a separate test dependency directory. This caused `No module named 'reportlab'` at PDF export. The declared runtime dependencies were installed in the actual launch environment, and full capability/GRR PDF and Excel reports were generated successfully there with no test PYTHONPATH.

`tools/build.ps1` now checks the runtime dependencies before packaging. `datamapperx/selftest.py` generates and validates all four full statistical reports during the executable smoke test, so opening the application alone can no longer pass the build while PDF support is missing. Two regression tests cover successful report generation and missing ReportLab. The 25 targeted report/release/startup checks and Ruff passed.

The local `dist/DataMapperX.exe` was rebuilt with ReportLab and its dependencies. Its packaged smoke test passed, including capability and GRR PDF/Excel generation, scanning, raw export and the desktop workflow. The preceding executable is retained under the ignored `tmp/stat-runtime-backup/` directory. No release was published.
