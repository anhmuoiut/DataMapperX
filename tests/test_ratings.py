"""Attribute Agreement (P2): reading a long-format ratings table, mapping its columns and categories, and the settings.

Everything here is headless: files are written to a temporary folder and read back, and the dataset that comes out is
analysed with the P1 engine.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from openpyxl import Workbook

from datamapperx.statistics import AnalysisConfig, Dataset, EvaluationSettings, StatisticalOptions, Study, analyze
from datamapperx.statistics.models import Observation
from datamapperx.statistics.ratings import (
    ImportedRatings,
    RatingsFormatError,
    RatingsMapping,
    attribute_settings,
    attribute_summary,
    attribute_warnings,
    build_ratings,
    category_mapping,
    label_counts,
    mapping_problems,
    read_ratings_table,
    suggest_mapping,
)

HEADERS = ("Samples", "Appraisers", "Measurements", "Standard")  # the worksheet of the Minitab screenshot
MAPPING = RatingsMapping(sample="Samples", rating="Measurements", appraiser="Appraisers", standard="Standard")


def reference_rows(trials=3, samples=30):
    """One row per assessment: 15 samples whose standard is PASS, then 15 whose standard is FAIL, always rated as the standard says."""
    return [(f"VSEG{n:06d}", "1", ("PASS" if n <= samples // 2 else "FAIL"), ("PASS" if n <= samples // 2 else "FAIL"))
            for n in range(1, samples + 1) for _ in range(trials)]


def write_csv(path: Path, rows, headers=HEADERS, delimiter=",", encoding="utf-8", newline="\n"):
    lines = [delimiter.join(headers), *(delimiter.join(str(c) for c in row) for row in rows)]
    path.write_bytes(newline.join(lines).encode(encoding) + newline.encode())
    return path


def write_xlsx(path: Path, rows, headers=HEADERS, sheet="Data", extra_sheets=()):
    workbook = Workbook()
    first = workbook.active
    first.title = sheet
    first.append(list(headers))
    for row in rows:
        first.append(list(row))
    for name in extra_sheets:
        other = workbook.create_sheet(name)
        other.append(["nothing", "here"])
        other.append(["a", "b"])
    workbook.save(path)
    return path


def imported(path, mapping=MAPPING, sheet=None) -> ImportedRatings:
    return build_ratings(read_ratings_table(path, sheet), mapping)


def only(observations, config=AnalysisConfig(method="attribute")):
    result, = analyze(observations, config)
    return result


def errors(result):
    return [issue.message for issue in result.issues if issue.severity == "error"]


# ----------------------------------------------------------------------------- reading CSV
@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_a_csv_is_read_whatever_separates_its_columns(tmp_path, delimiter):
    table = read_ratings_table(write_csv(tmp_path / "ratings.csv", reference_rows(), delimiter=delimiter))
    assert table.headers == HEADERS and len(table.rows) == 90 and table.rows[0] == ("VSEG000001", "1", "PASS", "PASS")
    assert table.numbers[0] == 2 and table.numbers[-1] == 91 and table.name == "ratings.csv"


def test_a_csv_with_a_byte_order_mark_or_windows_text_and_quoted_cells(tmp_path):
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbfSamples,Measurements\r\nS1,PASS\r\n")
    assert read_ratings_table(bom).headers == ("Samples", "Measurements")  # the mark is not part of the first name
    windows = tmp_path / "windows.csv"
    windows.write_bytes('Samples,Measurements\nS1,"Bestanden, ok"\nS2,Défaut\n'.encode("cp1252"))
    assert read_ratings_table(windows).rows == (("S1", "Bestanden, ok"), ("S2", "Défaut"))


def test_empty_rows_are_skipped_and_counted_but_empty_cells_stay_empty(tmp_path):
    path = tmp_path / "gaps.csv"
    path.write_text("Samples,Measurements,Standard\nS1,PASS,PASS\n\n,,\nS2,,PASS\nS3\n", encoding="utf-8")
    table = read_ratings_table(path)
    assert table.rows == (("S1", "PASS", "PASS"), ("S2", "", "PASS"), ("S3", "", "")) and table.empty_rows == 2
    assert table.numbers == (2, 5, 6)  # the row numbers are the file's own


def test_header_names_are_made_unique_and_a_blank_name_gets_a_number(tmp_path):
    path = tmp_path / "names.csv"
    path.write_text("Result,,Result,Standard,\nPASS,x,FAIL,PASS,\n", encoding="utf-8")
    assert read_ratings_table(path).headers == ("Result", "Column 2", "Result (2)", "Standard")  # the empty edge column is dropped


@pytest.mark.parametrize("content,fragment", [("", "has no data"), ("\n\n", "has no data"), ("Samples,Measurements\n", "no rows of ratings")])
def test_a_file_without_ratings_is_refused_with_a_reason(tmp_path, content, fragment):
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(RatingsFormatError, match=fragment):
        read_ratings_table(path)


def test_other_file_types_are_refused(tmp_path):
    path = tmp_path / "ratings.docx"
    path.write_text("x")
    with pytest.raises(RatingsFormatError, match="not a CSV or XLSX"):
        read_ratings_table(path)


# ----------------------------------------------------------------------------- reading XLSX
def test_an_xlsx_sheet_is_read_like_the_same_csv(tmp_path):
    rows = reference_rows()
    from_csv = imported(write_csv(tmp_path / "r.csv", rows))
    from_xlsx = imported(write_xlsx(tmp_path / "r.xlsx", rows))
    assert from_csv.dataset.fingerprint == from_xlsx.dataset.fingerprint  # the same ratings, whichever file held them
    assert (from_xlsx.samples, from_xlsx.ratings, from_xlsx.trials) == (30, 90, "3")


def test_a_workbook_with_several_sheets_reads_the_first_or_the_one_asked_for(tmp_path):
    path = write_xlsx(tmp_path / "many.xlsx", reference_rows(trials=1), extra_sheets=("Notes",))
    first = read_ratings_table(path)
    assert first.sheet == "Data" and first.sheets == ("Data", "Notes") and first.headers == HEADERS
    notes = read_ratings_table(path, "Notes")
    assert notes.sheet == "Notes" and notes.headers == ("nothing", "here") and notes.rows == (("a", "b"),)


def test_numbers_and_booleans_in_cells_read_the_same_everywhere(tmp_path):
    path = write_xlsx(tmp_path / "numbers.xlsx", [("S1", 1, 1.0, True), ("S2", 2, 0, False), ("S3", 3, 2.5, None)])
    table = read_ratings_table(path)
    assert table.rows == (("S1", "1", "1", "TRUE"), ("S2", "2", "0", "FALSE"), ("S3", "3", "2.5", ""))  # 1 and 1.0 are "1"


# ----------------------------------------------------------------------------- the mapping
def test_the_columns_of_the_minitab_worksheet_are_recognised(tmp_path):
    assert suggest_mapping(HEADERS) == {"sample": "Samples", "rating": "Measurements", "item": "", "appraiser": "Appraisers",
                                        "trial": "", "standard": "Standard"}


@pytest.mark.parametrize("headers,expected", [
    (("Sample ID", "Rating", "Operator", "Trial", "Reference", "Test Item"),
     {"sample": "Sample ID", "rating": "Rating", "appraiser": "Operator", "trial": "Trial", "standard": "Reference", "item": "Test Item"}),
    (("SN", "Result", "Inspector", "Repetition"), {"sample": "SN", "rating": "Result", "appraiser": "Inspector", "trial": "Repetition",
                                                   "standard": "", "item": ""}),
    (("a", "b"), dict.fromkeys(("sample", "rating", "item", "appraiser", "trial", "standard"), "")),
])
def test_other_names_are_suggested_and_unknown_ones_are_left_for_the_user(headers, expected):
    suggestion = suggest_mapping(headers)
    assert suggestion == {**dict.fromkeys(("sample", "rating", "item", "appraiser", "trial", "standard"), ""), **expected}
    assert len({c for c in suggestion.values() if c}) == len([c for c in suggestion.values() if c])  # no column twice


def test_a_mapping_that_cannot_be_used_is_explained(tmp_path):
    table = read_ratings_table(write_csv(tmp_path / "r.csv", reference_rows(trials=1)))
    assert mapping_problems(table, MAPPING) == []
    assert mapping_problems(table, RatingsMapping(sample="", rating="")) == ["Choose the Sample ID column.", "Choose the Rating column."]
    assert "'Nope' is not in the file" in mapping_problems(table, dataclasses.replace(MAPPING, standard="Nope"))[0]
    assert "chosen for more than one field" in mapping_problems(table, dataclasses.replace(MAPPING, standard="Measurements"))[0]
    with pytest.raises(RatingsFormatError, match="Choose the Rating column"):
        build_ratings(table, RatingsMapping(sample="Samples", rating=""))


# ----------------------------------------------------------------------------- the dataset
def test_the_minitab_layout_becomes_one_observation_per_assessment_with_numbered_trials(tmp_path):
    result = imported(write_csv(tmp_path / "Programming study.csv", reference_rows()))
    first, *_, last = result.dataset.observations
    assert (first.test_item, first.sample_id, first.value, first.standard, first.operator, first.trial) == (
        "Programming study", "VSEG000001", "PASS", "PASS", "1", "1")
    assert (last.sample_id, last.trial, last.standard) == ("VSEG000030", "3", "FAIL") and len(result.dataset) == 90
    assert result.items == ("Programming study",) and result.appraisers == 1 and result.categories == ("FAIL", "PASS")
    assert any("No Trial column" in warning for warning in result.warnings)  # the numbering is said, not silent
    assert len({o.source for o in result.dataset.observations}) == 90 and first.source == "Programming study.csv!R2"


def test_the_reference_study_read_from_a_file_gives_the_published_figures(tmp_path):
    result = only(imported(write_csv(tmp_path / "r.csv", reference_rows())).dataset.observations)
    assert result.valid and result.parts == 30 and result.repeats == 3
    within = result.details["appraisers"][0]["within"]
    assert (within["matched"], within["percent"], round(within["lower"], 2), within["upper"]) == (30, 100.0, 90.50, 100.0)
    assert round(result.details["appraisers"][0]["kappa_within"]["rows"][0]["se"], 6) == 0.105409


def test_a_trial_column_is_used_as_it_is_and_no_numbering_is_added(tmp_path):
    rows = [(s, a, r, st, t) for (s, a, r, st), t in zip(reference_rows(), [1, 2, 3] * 30, strict=True)]
    path = write_csv(tmp_path / "t.csv", rows, headers=(*HEADERS, "Trial"))
    result = imported(path, dataclasses.replace(MAPPING, trial="Trial"))
    assert [o.trial for o in result.dataset.observations[:4]] == ["1", "2", "3", "1"] and not any("No Trial" in w for w in result.warnings)
    assert only(result.dataset.observations).valid


def test_without_a_trial_column_numbering_can_be_switched_off(tmp_path):
    result = imported(write_csv(tmp_path / "n.csv", reference_rows(trials=2)), dataclasses.replace(MAPPING, assign_trials=False))
    assert {o.trial for o in result.dataset.observations} == {""}
    assert only(result.dataset.observations).valid  # the engine takes the ratings of a sample as its trials, in the order of the rows


def test_the_test_item_and_the_appraiser_come_from_their_columns_when_there_are_some(tmp_path):
    samples = [(s, r, st) for s, _a, r, st in reference_rows(trials=1, samples=10)]
    rows = [(item, s, who, r, st) for item in ("Item A", "Item B") for s, r, st in samples for who in ("Ann", "Ben") for _ in range(2)]
    path = write_csv(tmp_path / "multi.csv", rows, headers=("Item", "Samples", "Appraisers", "Measurements", "Standard"))
    result = imported(path, dataclasses.replace(MAPPING, item="Item"))
    assert result.items == ("Item A", "Item B") and len(result.dataset) == 80 and result.trials == "2"
    assert {o.operator for o in result.dataset.observations} == {"Ann", "Ben"} and result.appraisers == 2
    results = analyze(result.dataset.observations, AnalysisConfig(method="attribute"))
    assert [r.test_item for r in results] == ["Item A", "Item B"] and all(r.valid and len(r.details["appraisers"]) == 2 for r in results)


def test_the_original_labels_are_kept_unless_the_user_maps_them_to_a_category(tmp_path):
    rows = [("S1", "1", "Pass", "Pass"), ("S1", "1", "pass", "Pass"), ("S2", "1", "FAIL", "FAIL"), ("S2", "1", "Fail", "FAIL")]
    path = write_csv(tmp_path / "labels.csv", rows)
    as_given = imported(path)
    assert [o.value for o in as_given.dataset.observations] == ["Pass", "pass", "FAIL", "Fail"]  # no case folding, no renaming
    assert as_given.categories == ("FAIL", "Fail", "Pass", "pass") and not any("counted as another" in w for w in as_given.warnings)
    mapped = imported(path, dataclasses.replace(MAPPING, categories=category_mapping({"Pass": "PASS", "pass": "PASS", "Fail": "FAIL",
                                                                                      "FAIL": "FAIL", "Spare": ""})))
    assert [o.value for o in mapped.dataset.observations] == ["PASS", "PASS", "FAIL", "FAIL"]
    assert [o.standard for o in mapped.dataset.observations] == ["PASS", "PASS", "FAIL", "FAIL"]  # the standard follows the same names
    assert mapped.categories == ("FAIL", "PASS") and any("Pass → PASS" in w for w in mapped.warnings)
    assert only(mapped.dataset.observations).details["appraisers"][0]["within"]["matched"] == 2  # merged: both samples agree
    assert only(as_given.dataset.observations).details["appraisers"][0]["within"]["matched"] == 0  # as given: they do not


def test_label_counts_list_every_label_of_the_rating_and_standard_columns(tmp_path):
    table = read_ratings_table(write_csv(tmp_path / "c.csv", [("S1", "1", "P", "PASS"), ("S2", "1", "F", "PASS"), ("S3", "1", "P", "")]))
    assert label_counts(table, MAPPING) == [("P", 2), ("F", 1), ("PASS", 2)]
    assert label_counts(table, dataclasses.replace(MAPPING, standard="")) == [("P", 2), ("F", 1)]


def test_category_mapping_keeps_only_real_renames():
    assert category_mapping({"P": " PASS ", "F": "F", "X": "", "Y": "  "}) == (("P", "PASS"),)


# ----------------------------------------------------------------------------- what the analysis then says about the data
def test_empty_values_in_the_file_reach_the_analysis_as_errors_not_as_guesses(tmp_path):
    rows = reference_rows()
    rows[4] = (rows[4][0], rows[4][1], "", rows[4][3])  # a rating left empty
    result = imported(write_csv(tmp_path / "e.csv", rows))
    assert any("1 row(s) have no rating" in w for w in result.warnings)
    assert any("Missing rating for 1 assessment" in message for message in errors(only(result.dataset.observations)))
    rows = reference_rows()
    rows[7] = ("", rows[7][1], rows[7][2], rows[7][3])
    assert any("Missing Sample ID" in message for message in errors(only(imported(write_csv(tmp_path / "s.csv", rows)).dataset.observations)))


def test_duplicate_trial_ids_and_a_missing_trial_are_reported(tmp_path):
    rows = [(s, a, r, st, t) for (s, a, r, st), t in zip(reference_rows(), [1, 1, 3] * 30, strict=True)]
    path = write_csv(tmp_path / "d.csv", rows, headers=(*HEADERS, "Trial"))
    result = only(imported(path, dataclasses.replace(MAPPING, trial="Trial")).dataset.observations)
    assert any("Duplicate trial identity: VSEG000001 / 1 / 1" in message for message in errors(result))
    rows[2] = (*rows[2][:4], "")
    path = write_csv(tmp_path / "m.csv", rows, headers=(*HEADERS, "Trial"))
    assert any("Trial is missing for some ratings" in message
               for message in errors(only(imported(path, dataclasses.replace(MAPPING, trial="Trial")).dataset.observations)))


def test_inconsistent_and_partly_missing_standards_reach_the_analysis_as_a_standard_problem_not_as_a_guess(tmp_path):
    rows = reference_rows()
    rows[0] = (*rows[0][:3], "FAIL")  # the first rating of VSEG000001 names another standard than its other two
    inconsistent = only(imported(write_csv(tmp_path / "i.csv", rows)).dataset.observations)
    assert "Inconsistent Standard: samples VSEG000001" in inconsistent.details["standard_problem"]
    rows = reference_rows()
    rows[:3] = [(*row[:3], "") for row in rows[:3]]
    partial = only(imported(write_csv(tmp_path / "p.csv", rows)).dataset.observations)
    assert partial.details["standard_problem"] == "The Standard is missing for 1 of 30 samples."
    for result in (inconsistent, partial):  # the comparison with the Standard is not made; the agreement of the appraiser with itself is
        assert result.valid and result.metrics["standard_percent"] is None and result.metrics["within_percent"] == 100


def test_a_missing_standard_column_is_a_study_without_a_standard(tmp_path):
    path = write_csv(tmp_path / "ns.csv", [row[:3] for row in reference_rows()], headers=HEADERS[:3])
    result = only(imported(path, dataclasses.replace(MAPPING, standard="")).dataset.observations)
    assert result.valid and result.metrics["standard_percent"] is None and result.metrics["within_percent"] == 100


def test_an_appraiser_column_that_is_not_mapped_is_the_one_unnamed_appraiser(tmp_path):
    result = imported(write_csv(tmp_path / "a.csv", reference_rows()), dataclasses.replace(MAPPING, appraiser=""))
    assert {o.operator for o in result.dataset.observations} == {""} and result.appraisers == 1
    assert only(result.dataset.observations).details["appraisers"][0]["label"] == "1"  # shown as appraiser 1


def test_the_data_tab_summary_and_hint(tmp_path):
    rows = imported(write_csv(tmp_path / "s.csv", reference_rows())).dataset.observations
    assert attribute_summary(rows) == "Test Items 1  ·  Samples 30  ·  Appraisers 1  ·  Ratings 90  ·  Trials per Sample 3"
    assert attribute_warnings(rows) == []
    numbers = [Observation("X", f"S{i}", 1.5 + i, trial="1") for i in range(40)]
    assert "numbers with 40 different values" in attribute_warnings(numbers)[0]
    assert attribute_warnings([Observation("X", f"S{i}", i % 2, trial="1") for i in range(40)]) == []  # 0 and 1 are categories


# ----------------------------------------------------------------------------- settings and the study
@pytest.mark.parametrize("confidence,enabled,minimum,expected", [
    ("95%", False, "garbage", (0.95, None)),  # the minimum is read only when acceptance is on
    ("90%", True, "90", (0.90, 90.0)), ("99", True, " 92.5 % ", (0.99, 92.5)), ("0.95", True, "100", (0.95, 100.0))])
def test_the_attribute_settings_on_screen_become_options(confidence, enabled, minimum, expected):
    level, least = attribute_settings(confidence, enabled, minimum)
    assert level == pytest.approx(expected[0]) and least == expected[1]


@pytest.mark.parametrize("confidence,enabled,minimum,fragment", [
    ("", False, "90", "Confidence level"), ("100%", False, "90", "below 100 %"), ("20%", False, "90", "at least 50 %"),
    ("95%", True, "", "Minimum agreement: enter"), ("95%", True, "0", "above 0"), ("95%", True, "101", "at most 100"),
    ("95%", True, "nan", "above 0")])
def test_wrong_attribute_settings_say_what_to_fix(confidence, enabled, minimum, fragment):
    with pytest.raises(ValueError, match=fragment):
        attribute_settings(confidence, enabled, minimum)


def test_ratings_run_as_a_study_whose_results_follow_the_confidence_level(tmp_path):
    data = imported(write_csv(tmp_path / "study.csv", reference_rows()))
    study = Study(data.dataset, mapping={"source": "ratings", **data.record}, options=StatisticalOptions(method="attribute"))
    first = study.run_statistics()
    study.options = dataclasses.replace(study.options, confidence=0.90)
    assert study.is_stale(first)
    second = study.run_statistics()
    assert second.statistics[0].details["confidence"] == 0.90 and not study.is_stale(second)
    level, minimum = attribute_settings("90%", True, "90")
    evaluated = study.evaluate(second, EvaluationSettings(agreement_min=minimum))
    assert level == 0.90 and evaluated.results[0].status == "PASS"


def test_reading_ratings_changes_nothing_for_the_other_methods(tmp_path):
    numeric = [Observation("X", "S1", 1.5, 0, 4, trial="1"), Observation("X", "S1", 1.6, 0, 4, trial="2"),
               Observation("X", "S2", 2.5, 0, 4, trial="1"), Observation("X", "S2", 2.6, 0, 4, trial="2")]
    assert Dataset.from_observations(numeric).fingerprint == Dataset.from_observations(
        [dataclasses.replace(o, standard="") for o in numeric]).fingerprint  # a dataset without ratings is what it was
    assert analyze(numeric, AnalysisConfig(method="capability"))[0].valid
    assert analyze(numeric, AnalysisConfig(method="grr"))[0].valid
