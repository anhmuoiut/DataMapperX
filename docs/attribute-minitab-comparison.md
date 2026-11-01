# Attribute Agreement: comparison with Minitab

What has been compared with output Minitab itself printed, what has not, and the nine studies to run in Minitab to close the open part, the Assessment Disagreement table. Nothing in this file is a Minitab result unless it says so.

## 1. Compared and agreeing

Minitab's help page [Example of Attribute Agreement Analysis](https://support.minitab.com/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/attribute-agreement-analysis/attribute-agreement-analysis/before-you-start/example) (Textile print quality: 4 appraisers, 2 trials, 50 samples, 5 responses, known Standard) prints its whole output and offers the worksheet. `tests/reference/` holds both, and `tests/test_attribute_minitab.py` compares **290 printed figures** at the precision Minitab prints them, with no difference:

| Block | Figures |
|---|---|
| Assessment Agreement: Within Appraisers, Each Appraiser vs Standard, Between Appraisers, All Appraisers vs Standard (matched, percent, both limits of the 95 % interval) | 50 |
| Fleiss' kappa, SE, Z, P for every response and Overall: Within Appraisers, Each Appraiser vs Standard, Between Appraisers, All Appraisers vs Standard | 240 |

The example's Kendall tables (ordered categories) are out of scope. Earlier published figures also agree: the 30-of-30 reference report ((90.50, 100.00), SE 0.105409, Z 9.48683). The example has five responses, so it has no Assessment Disagreement table: nothing in it checks that table.

## 2. Assessment Disagreement: the rule that is implemented

Minitab's help ([interpret](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/attribute-agreement-analysis/attribute-agreement-analysis/interpret-the-results/all-statistics-and-graphs/assessment-disagreement/), [methods](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/attribute-agreement-analysis/attribute-agreement-analysis/methods-and-formulas/assessment-disagreement/)) says: the table appears when a reference value is given for each rating and the ratings have only 2 levels; **#Pass/Fail** is the number of samples the appraiser passed but should have failed (a false positive), **#Fail/Pass** the number failed but should have passed (a false negative), **#Mixed** the number of times the appraiser made inconsistent ratings across trials; the columns are named after the two levels. It does not say what the Percent columns are divided by.

DataMapperX (`statistics/attribute._disagreement`) classifies each sample of each appraiser once:

| Column | Counts the samples where | Percent = 100 x count / |
|---|---|---|
| #Pass/Fail | every trial is Pass and the Standard is Fail | the samples whose Standard is Fail |
| #Fail/Pass | every trial is Fail and the Standard is Pass | the samples whose Standard is Pass |
| #Mixed | the trials differ (whatever the Standard is) | all samples |

A sample matched by its Standard is in none of them, and no sample is in two. With no sample of the divisor's Standard the percent is **N/A**, never 0 or made up. No Standard, or other than two responses: no table. The columns carry the study's own response names, the later-sorted response rated against the earlier one's samples first (Fail, Pass gives #Pass/Fail, #Fail/Pass). The trial-level figure (single ratings that differ from the Standard, over all ratings, 100 x c / N, Minitab's methods page) is kept in the result details (`assessments`, `different`, `percent`) and is not in the table.

## 3. What supports it, and what does not yet

| Point | Evidence | Status |
|---|---|---|
| Per sample, once; Mixed whatever the Standard | Minitab's definitions above | consistent with them; **no printed Minitab table with its raw data was available to compare** |
| #Pass/Fail Percent over the samples whose Standard is Fail | one published example (*Six Sigma Case Studies with Minitab*, ch. 12, as quoted in the task): 10 inspected samples, #Pass/Fail 1 with Percent 25.00 | consistent if the example has 4 Standard Fail samples; the book's data could not be read, so **not checked against its data** |
| #Mixed Percent over all samples | same example: #Mixed 1 with Percent 10.00 | consistent (1 of 10) |
| #Fail/Pass Percent over the samples whose Standard is Pass | by symmetry only | **unverified** |
| N/A with no sample of the divisor's Standard | none | **unverified** (Minitab may print 0.00 or *) |
| One trial per sample (#Mixed is 0) | none | **unverified** |
| Several appraisers: one row each | the help says "for each appraiser" | unverified with output |
| Responses other than Pass and Fail: column names and their order | none | unverified |

Sources that could not be used: the book (O'Reilly refused the page, Google Books sent a bot-check), a paper that reproduces Minitab's table (not found), Minitab's blog example (its Assistant reports are images and use other definitions). `tests/test_attribute.py` tests the rule against an independent count of 150 random studies, and builds a study with the shape of the published example (10 samples, 4 with Standard Fail, one false pass, one mixed) that gives 25.00 and 10.00; neither is Minitab output.

## 4. The nine studies

`python tools/attribute_disagreement_cases.py` writes nine CSV files to `samples/attribute_minitab/` and prints what DataMapperX shows for each. All have 24 samples (S01-S14 Standard Pass, S15-S24 Standard Fail, so that the three divisors 10, 14 and 24 differ) and 3 trials. What DataMapperX shows (counts, with the percent in brackets):

| Study | Appraiser | #Pass/Fail | #Fail/Pass | #Mixed |
|---|---|---|---|---|
| A_perfect_agreement | Ann | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| B_consistent_false_pass (S15-S17 always Pass) | Ann | 3 (30.00) | 0 (0.00) | 0 (0.00) |
| C_consistent_false_fail (S01, S02 always Fail) | Ann | 0 (0.00) | 2 (14.29) | 0 (0.00) |
| D_mixed_repeated_ratings (S03, S04, S18, S19: one or two trials wrong) | Ann | 0 (0.00) | 0 (0.00) | 4 (16.67) |
| E_multiple_error_types (B, C and D together) | Ann | 3 (30.00) | 2 (14.29) | 4 (16.67) |
| F_multiple_appraisers | Ann (as E) / Ben (every Fail sample always Pass) / Carla (perfect) | 3 (30.00) / 10 (100.00) / 0 | 2 (14.29) / 0 / 0 | 4 (16.67) / 0 / 0 |
| G_missing_standard | Ann | no table | no table | no table |
| H_one_reference_category_absent (every Standard Pass; S03 always Fail, S07 mixed) | Ann | 0 (N/A) | 1 (4.17) | 1 (4.17) |
| I_every_sample_always_wrong (also the 0 % interval: DataMapperX gives (0.00, 11.73)) | Ann | 10 (100.00) | 14 (100.00) | 0 (0.00) |

Studies D, E and F separate the readings of the counts that are possible (a mixed sample counted again as Pass/Fail, counts of ratings instead of samples); B, C, F (Ben) and H the divisors; G and H the two edge cases.

To run one in Minitab: open the CSV, **Stat > Quality Tools > Attribute Agreement Analysis**; Data are arranged as **Attribute column**; Attribute column **Measurements**; Samples **Samples**; Appraisers **Appraisers**; Known standard/attribute **Standard** (leave it empty for G); "Categories of the attribute data are ordered" **unchecked**; confidence level 95 %. Copy the whole **Session window** of each study.

## 5. When Minitab's output arrives

1. Set each study's Assessment Disagreement table beside the one above. If they agree for all nine, the rule and its divisors are confirmed, edge cases included.
2. The Session outputs become `tests/reference/` files and tests in the manner of `tests/test_attribute_minitab.py`; they also compare the agreement, interval and kappa figures printed with them (kappa with two responses and imperfect agreement, the 0 % interval of study I).
3. If something differs, only `_disagreement` and its tests change.
4. Only then may `METHOD_VERIFICATION["attribute_agreement"]` (`statistics/study.py`) move from "Pending Minitab Verification", and the one sentence in About the method that says the table has not been compared with a full Minitab run goes.
