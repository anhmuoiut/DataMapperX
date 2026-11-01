"""Attribute Agreement (P3): what the Results table, Details and Checks say, tested without building any window.

The content of each view is made by pure functions (``summary_rows``, ``attribute_details``, ``attribute_checks``,
``summary_line``). The workspace methods that put that content on screen are run on stand-ins for the widgets, which record what
they are told. Nothing here creates a Tk root.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from datamapperx.stat_charts import charts_for_result
from datamapperx.stat_reports import attribute_details, report_charts, summary_line, summary_number, summary_rows
from datamapperx.statistics import AnalysisConfig, Dataset, EvaluationSettings, StatisticalOptions, Study, analyze
from datamapperx.statistics.checks import (
    CAUTION,
    CRITICAL,
    INFO,
    attribute_checks,
    attribute_status_label,
    needs_attention,
    result_checks,
)
from datamapperx.ui import validation_workspace as workspace
from datamapperx.ui.validation_workspace import ValidationWorkspace

from .test_attribute import ATTRIBUTE, only, pass_only_rows, rate, reference_rows
from .test_ratings import MAPPING, imported, write_csv
from .test_ratings import reference_rows as file_rows

JUDGED = AnalysisConfig(method="attribute", agreement_min=90)


def label_of(check):
    return (check.topic, attribute_status_label(check))


# ----------------------------------------------------------------------------- the Results table
def test_the_table_has_the_five_columns_and_acceptance_only_when_it_is_on():
    result = only(reference_rows(), JUDGED)
    headers, rows = summary_rows([result], judged=True)
    assert headers == ("Test Item", "System", "Samples", "Within %", "vs Standard %", "Kappa", "Acceptance Result")
    assert rows[0][:5] == ("Programming", "", 30, 100.0, 100.0) and rows[0][5] == pytest.approx(1.0) and rows[0][6] == "PASS"
    headers, rows = summary_rows([only(reference_rows(), ATTRIBUTE)], judged=False)
    assert headers == ("Test Item", "System", "Samples", "Within %", "vs Standard %", "Kappa") and len(rows[0]) == 6  # statistics only
    assert not {"%SV/Tol", "%Study Var", "NDC", "Cp", "Cpk", "Pp", "Ppk", "Decision Metric", "Review"} & set(headers)


def test_a_figure_that_is_not_available_is_na_and_the_decimals_follow_the_setting():
    without = only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE)
    headers, (row,) = summary_rows([without], judged=False)
    shown = [summary_number(value, header, 3, "attribute") for value, header in zip(row, headers, strict=True)]
    assert shown[2:] == ["30", "100.000", "N/A", "1.000"]  # no Standard: vs Standard % is N/A, and a percentage has the chosen decimals
    assert summary_number(12.3456, "%SV/Tol", 4) == "12.35" and summary_number(12.3456, "Cpk", 4) == "12.3456"  # the other methods: as before
    assert summary_number(None, "Kappa", 3, "attribute") == "N/A"


def test_several_appraisers_have_no_single_figure_in_the_table_only_in_the_details():
    rows = [dataclasses.replace(r, operator=name, source=f"{name}/{r.source}") for name in ("Ann", "Ben") for r in reference_rows()]
    headers, (row,) = summary_rows([only(rows, ATTRIBUTE)], judged=False)
    assert row[3:] == (None, None, None)  # N/A: each appraiser's figures are in the Details


def test_the_summary_line_separates_what_was_analysed_from_acceptance_and_from_errors():
    good, also_good = only(reference_rows(), ATTRIBUTE), only(reference_rows(), ATTRIBUTE)
    broken = only([dataclasses.replace(r, value="") if i == 3 else r for i, r in enumerate(reference_rows())], ATTRIBUTE)
    assert summary_line([good], False) == "1 item analyzed · Acceptance off"  # a computed result is not "not evaluated"
    assert summary_line([good, also_good], False) == "2 items analyzed · Acceptance off"
    assert summary_line([good, broken], False, review=1) == "1 item analyzed · Acceptance off · 1 not analyzed · 1 Need Review"
    judged = only(reference_rows(), JUDGED)
    assert summary_line([judged], True) == "1 item analyzed · 1 PASS"


# ----------------------------------------------------------------------------- Details
def test_the_details_of_the_reference_study_are_the_tables_of_minitabs_report():
    tables, notes = attribute_details(only(reference_rows(), ATTRIBUTE), 2)
    assert [t.title for t in tables] == ["Within Appraisers", "Fleiss' Kappa Statistics", "Each Appraiser vs Standard",
                                         "Fleiss' Kappa Statistics vs Standard", "Assessment Disagreement"]
    within, kappa, against, kappa_standard, disagreement = tables
    assert within.headers == ("Appraiser", "Inspected", "Matched", "Agreement %", "95% CI")
    assert within.rows == (("1", "30", "30", "100.00", "(90.50, 100.00)"),) and against.rows == within.rows
    assert kappa.headers == ("Appraiser", "Response", "Kappa", "SE", "Z", "P")
    assert kappa.rows == (("1", "Fail", "1.00", "0.105409", "9.48683", "<0.0001"), ("1", "Pass", "1.00", "0.105409", "9.48683", "<0.0001"))
    assert kappa_standard.rows == kappa.rows  # two responses: no extra Overall row
    assert disagreement.headers == ("Appraiser", "#Pass/Fail", "Percent", "#Fail/Pass", "Percent", "#Mixed", "Percent")  # Minitab's table
    assert disagreement.rows == (("1", "0", "0.00", "0", "0.00", "0", "0.00"),)
    assert notes == []  # nothing needs saying: no disclaimer, and nothing is undefined


def test_the_details_follow_the_decimals_and_the_confidence_level():
    result = only(reference_rows(), AnalysisConfig(method="attribute", confidence=0.90))
    tables, _ = attribute_details(result, 4)
    assert tables[0].headers[-1] == "90% CI" and tables[0].rows[0][3:] == ("100.0000", f"({100 * 0.10 ** (1 / 30):.4f}, 100.0000)")
    assert tables[1].rows[0][2:4] == ("1.0000", "0.10540926")


def test_the_disagreement_table_counts_each_sample_once_and_divides_by_the_samples_of_its_standard():
    # sample 3 (Standard Pass) is always rated Fail; sample 20 (Standard Fail) is rated wrongly once, so its trials differ: Mixed
    result = only(reference_rows(mistakes={(3, 1), (3, 2), (3, 3), (20, 1)}), ATTRIBUTE)
    tables, notes = attribute_details(result, 2)
    disagreement = tables[-1]
    assert disagreement.title == "Assessment Disagreement"
    assert disagreement.rows == (("1", "0", "0.00", "1", f"{100 / 15:.2f}", "1", f"{100 / 30:.2f}"),)  # 15 Pass samples, 15 Fail samples, 30 samples
    assert notes == [] and attribute_details(result, 4)[0][-1].rows == (("1", "0", "0.0000", "1", f"{100 / 15:.4f}", "1", f"{100 / 30:.4f}"),)


def test_a_percent_with_nothing_to_divide_by_is_n_a_and_says_why():
    rows = pass_only_rows({3: "FFF", 7: "PFP"})  # every sample has the Standard Pass; sample 3 is always rated Fail and sample 7 once
    tables, notes = attribute_details(only(rows, ATTRIBUTE), 2)  # no sample has the Standard Fail: no false pass has a base to be a percent of
    assert tables[-1].rows == (("1", "0", "N/A", "1", f"{100 / 30:.2f}", "1", f"{100 / 30:.2f}"),)
    assert notes == ["N/A: no sample has that value as its Standard."]


def test_a_kappa_that_is_undefined_is_na_with_one_explanation():
    rows = [dataclasses.replace(row, value="Pass", standard="Pass") for row in reference_rows()]
    tables, notes = attribute_details(only(rows, ATTRIBUTE), 2)
    assert tables[1].rows == (("1", "Pass", "N/A", "N/A", "N/A", "N/A"),) and [t.title for t in tables].count("Assessment Disagreement") == 0
    assert notes == ["Kappa is N/A where a response has no variation to measure."]  # said once, for both kappa tables


def test_only_the_tables_the_study_can_support_are_shown():
    no_standard = only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE)
    assert [t.title for t in attribute_details(no_standard)[0]] == ["Within Appraisers", "Fleiss' Kappa Statistics"]
    one_trial = only(reference_rows(trials=1), ATTRIBUTE)
    assert [t.title for t in attribute_details(one_trial)[0]] == ["Each Appraiser vs Standard", "Fleiss' Kappa Statistics vs Standard",
                                                                  "Assessment Disagreement"]
    assert attribute_details(only(reference_rows()[:-1], ATTRIBUTE)) == ([], [])  # an item that could not be analysed has no tables


def test_with_more_than_two_responses_each_kappa_table_ends_with_the_overall_kappa():
    levels = ("Pass", "Fail", "Hold")
    rows = []
    for number in range(1, 31):
        standard = levels[number % 3]
        rows += rate(f"S{number:02d}", [standard if (number, t) != (7, 2) else levels[(number + 1) % 3] for t in (1, 2, 3)], standard)
    tables, notes = attribute_details(only(rows, ATTRIBUTE), 2)
    kappa = next(t for t in tables if t.title == "Fleiss' Kappa Statistics")
    assert [row[1] for row in kappa.rows] == ["Fail", "Hold", "Pass", "Overall"]
    assert not any(t.title == "Assessment Disagreement" for t in tables)  # that table needs exactly two responses
    assert not any("Pass/Fail" in note for note in notes)


def test_several_appraisers_get_their_own_rows_and_the_comparisons_between_them():
    rows = [dataclasses.replace(r, operator=name, source=f"{name}/{r.source}") for name in ("Ann", "Ben")
            for r in reference_rows(mistakes={(5, 1)} if name == "Ben" else ())]
    tables, _ = attribute_details(only(rows, ATTRIBUTE), 2)
    titles = [t.title for t in tables]
    assert titles[:2] == ["Within Appraisers", "Fleiss' Kappa Statistics"] and "Between Appraisers" in titles and "All Appraisers vs Standard" in titles
    assert [row[0] for row in tables[0].rows] == ["Ann", "Ben"] and tables[0].rows[1][2] == "29"
    assert dict((t.title, t.rows) for t in tables)["All Appraisers vs Standard"][0][:3] == ("All", "30", "29")


# ----------------------------------------------------------------------------- Checks
def test_a_study_with_nothing_to_report_has_no_findings():
    result = only(reference_rows(), ATTRIBUTE)
    assert attribute_checks(result) == [] and result_checks(result, order_known=False) == ([], [])


def test_each_limitation_is_one_finding_with_its_own_status():
    no_standard = attribute_checks(only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE))
    assert [label_of(c) for c in no_standard] == [("Standard", "Info")] and "Appraiser vs Standard is not computed" in no_standard[0].message
    one_trial = attribute_checks(only(reference_rows(trials=1), ATTRIBUTE))
    assert [label_of(c) for c in one_trial] == [("Trials", "Review")] and "at least two trials" in one_trial[0].message
    one_category = attribute_checks(only([dataclasses.replace(r, value="Pass", standard="Pass") for r in reference_rows()], ATTRIBUTE))
    assert [label_of(c) for c in one_category] == [("Categories", "Review")]  # the kappa is not reported a second time
    ratings_only_pass = attribute_checks(only([dataclasses.replace(r, value="Pass") for r in reference_rows()], ATTRIBUTE))
    assert [(c.topic, c.message) for c in ratings_only_pass] == [("Kappa", "Undefined for Within Appraisers: a response has no variation to measure.")]
    combined = attribute_checks(only([dataclasses.replace(r, standard="") for r in reference_rows(trials=1)], ATTRIBUTE))
    assert [label_of(c) for c in combined] == [("Trials", "Review"), ("Standard", "Info")]  # most serious first


@pytest.mark.parametrize("damage,topic,fragment", [
    (lambda rows: [dataclasses.replace(r, value="") if i == 5 else r for i, r in enumerate(rows)], "Rating", "Missing rating for 1 assessment"),
    (lambda rows: [dataclasses.replace(r, trial="1") if i == 1 else r for i, r in enumerate(rows)], "Trial", "Duplicate trial identity"),
    (lambda rows: [dataclasses.replace(r, trial="") if i == 3 else r for i, r in enumerate(rows)], "Trial", "Trial is missing"),
    (lambda rows: rows[:-1], "Study layout", "Every appraiser must rate every sample the same number of times"),
    (lambda rows: [dataclasses.replace(r, sample_id="") if i == 0 else r for i, r in enumerate(rows)], "Sample ID", "Missing Sample ID"),
    (lambda rows: [*rows, rows[0]], "Source", "Duplicate source")])
def test_what_prevents_the_analysis_is_critical_and_named_for_what_to_fix(damage, topic, fragment):
    result = only(damage(reference_rows()), ATTRIBUTE)
    checks = attribute_checks(result)
    assert not result.valid and checks and all(c.status == CRITICAL for c in checks)
    assert any(c.topic == topic and fragment in c.message for c in checks), [(c.topic, c.message) for c in checks]
    assert len({c.message for c in checks}) == len(checks)  # no finding twice
    assert not needs_attention(checks)  # an item that could not be analysed is counted as such in the summary, not as one to review


def test_a_standard_that_cannot_be_used_is_critical_for_the_comparison_with_it_only():
    rows = [dataclasses.replace(r, standard="") if r.sample_id == "S05" else r for r in reference_rows()]
    result = only(rows, ATTRIBUTE)
    checks = attribute_checks(result)
    assert result.valid and [label_of(c) for c in checks] == [("Standard", "Critical")]  # not "no Standard" (Info), and not the whole study
    assert checks[0].message == "Appraiser vs Standard is not computed. The Standard is missing for 1 of 30 samples."
    tables, notes = attribute_details(result)
    assert [t.title for t in tables] == ["Within Appraisers", "Fleiss' Kappa Statistics"]  # what does not depend on the Standard stays
    assert notes == ["Appraiser vs Standard is N/A. The Standard is missing for 1 of 30 samples."]
    headers, (row,) = summary_rows([result], judged=False)
    assert row[3] == 100.0 and row[4] is None  # Within % is there; vs Standard % is N/A


def test_a_study_with_no_standard_at_all_is_info_not_critical():
    result = only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE)
    checks = attribute_checks(result)
    assert [label_of(c) for c in checks] == [("Standard", "Info")] and result.details["standard_problem"] == ""
    assert not any(c.status == CRITICAL for c in checks)


def test_an_analysed_item_with_a_critical_finding_needs_review_but_an_unanalysed_one_is_counted_as_that():
    usable = only([dataclasses.replace(r, standard="") if r.sample_id == "S05" else r for r in reference_rows()], ATTRIBUTE)
    unusable = only(reference_rows()[:-1], ATTRIBUTE)
    stub = SimpleNamespace(_checks={usable.label: (attribute_checks(usable), []), unusable.label: (attribute_checks(unusable), [])})
    assert ValidationWorkspace._needs_review(stub, usable)  # analysed, with a Critical finding: marked for review
    stub._checks = {unusable.label: (attribute_checks(unusable), [])}
    assert not ValidationWorkspace._needs_review(stub, unusable)  # could not be analysed: "not analyzed" in the summary, not here
    assert not ValidationWorkspace._needs_review(SimpleNamespace(_checks={}), only(reference_rows(), ATTRIBUTE))


def test_review_marks_an_item_but_info_and_critical_do_not():
    review = attribute_checks(only(reference_rows(trials=1), ATTRIBUTE))
    info = attribute_checks(only([dataclasses.replace(r, standard="") for r in reference_rows()], ATTRIBUTE))
    assert needs_attention(review) and not needs_attention(info)
    assert [c.status for c in review + info] == [CAUTION, INFO]


def test_responses_that_differ_only_by_case_are_a_review_finding():
    rows = reference_rows()
    rows[0] = dataclasses.replace(rows[0], value="PASS")
    checks = attribute_checks(only(rows, ATTRIBUTE))  # and "PASS" is rated in one trial only, so its kappa against the standard is undefined
    assert [label_of(c) for c in checks] == [("Responses", "Review"), ("Kappa", "Review")] and "vs Standard" in checks[1].message


# ----------------------------------------------------------------------------- charts: its own two panels, and no Gage R&R charts by mistake
def test_attribute_agreement_has_its_two_agreement_panels_and_nothing_of_another_method():
    result = only(reference_rows(), ATTRIBUTE)
    assert [spec.title for spec in charts_for_result(result)] == ["Within Appraisers", "Appraiser vs Standard"]
    assert [spec.title for spec in report_charts(result, titled=True)] == ["Within Appraisers", "Appraiser vs Standard"]
    broken = only(reference_rows()[:-1], ATTRIBUTE)  # an item that could not be analysed has none
    assert charts_for_result(broken) == [] and report_charts(broken, titled=True) == []


# ----------------------------------------------------------------------------- the release switches (what the window shows is tested in tests/ui)
def test_attribute_agreement_stays_blocked_until_released_but_can_be_checked_on_purpose(monkeypatch):
    for name in (workspace.ATTRIBUTE_PREVIEW_ENV, workspace.ATTRIBUTE_REPORTS_ENV):
        monkeypatch.delenv(name, raising=False)
    assert workspace.ATTRIBUTE_RESULTS_READY is False and workspace.ATTRIBUTE_REPORTS_READY is False  # the readiness flags stay off
    assert not workspace.attribute_runnable() and "cannot be run yet" in workspace.ATTRIBUTE_PENDING
    assert not workspace.attribute_reportable() and "not available yet" in workspace.ATTRIBUTE_REPORT_PENDING
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "1")
    assert workspace.attribute_runnable() and not workspace.attribute_reportable()  # running and reporting are checked one at a time
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "1")
    assert workspace.attribute_reportable()  # to try them in the window; the released state is unchanged
    monkeypatch.setenv(workspace.ATTRIBUTE_PREVIEW_ENV, "0")
    monkeypatch.setenv(workspace.ATTRIBUTE_REPORTS_ENV, "0")
    assert not workspace.attribute_runnable() and not workspace.attribute_reportable()


# ----------------------------------------------------------------------------- from the file to the screens, on one snapshot
def test_a_ratings_file_gives_the_same_snapshot_to_the_table_the_details_and_the_checks(tmp_path):
    data = imported(write_csv(tmp_path / "study.csv", file_rows()), MAPPING)
    study = Study(data.dataset, mapping={"source": "ratings", **data.record}, options=StatisticalOptions(method="attribute"))
    result_set = study.run_statistics()
    evaluated = study.evaluate(result_set, EvaluationSettings(agreement_min=90))
    result = evaluated.results[0]
    headers, (row,) = summary_rows(list(evaluated.results), evaluated.record.judged)
    tables, _ = attribute_details(result)
    assert row[3] == float(tables[0].rows[0][3]) == 100.0  # the same figure in the table and the details
    assert attribute_checks(result) == [] and summary_line(list(evaluated.results), evaluated.record.judged) == "1 item analyzed · 1 PASS"
    unjudged = study.evaluate(result_set, judge=False)
    assert summary_line(list(unjudged.results), unjudged.record.judged) == "1 item analyzed · Acceptance off"
    assert unjudged.results[0].metrics == result.metrics  # acceptance never changes a statistic


def test_results_of_another_method_or_setting_are_stale_not_current(tmp_path):
    data = imported(write_csv(tmp_path / "stale.csv", file_rows()), MAPPING)
    study = Study(data.dataset, options=StatisticalOptions(method="attribute"))
    result_set = study.run_statistics()
    assert not study.is_stale(result_set)
    study.options = dataclasses.replace(study.options, method="grr")  # the user switched method: these results are no longer current
    assert study.is_stale(result_set)
    study.options = StatisticalOptions(method="attribute", confidence=0.99)
    assert study.stale_reasons(result_set) == ("options",)
    study.options = StatisticalOptions(method="attribute")
    study.dataset = Dataset.from_observations(reference_rows(mistakes={(3, 2)}))
    assert study.stale_reasons(result_set) == ("dataset",)
    assert analyze(reference_rows(), ATTRIBUTE)[0].valid  # nothing else changed
