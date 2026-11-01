"""Attribute Agreement (P2): what the Analysis tab reads and says, tested without building any window.

The workspace methods are plain functions, so they run on a stand-in for ``self`` that has only the variables they read. Nothing
here creates a Tk root: the real widgets are exercised only when the GUI tests are run on purpose.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from datamapperx.statistics import Dataset, EvaluationSettings, Observation, StatisticalOptions
from datamapperx.ui import validation_workspace as workspace
from datamapperx.ui.validation_workspace import ValidationWorkspace


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def stand_in(**values):
    """An object with the variables of the Analysis tab, and the workspace's own methods bound to it."""
    defaults = {"method_var": "attribute", "judge_var": False, "confidence_var": "95%", "agreement_var": "90", "profile_var": "None (statistics only)",
                "study_factor_var": "6", "repeats_var": "", "assign_var": True, "subgroup_var": False, "within_var": "auto", "index_var": "cpk",
                "threshold_var": "1.33"}
    stub = SimpleNamespace(**{name: Var(values.get(name, default)) for name, default in defaults.items()}, customers={}, dataset=None,
                           _auto_within_cache=None)
    for name in ("_evaluation_for", "_judge_for", "_read_setup", "_plan_text", "_within_key", "_auto_within"):
        setattr(stub, name, getattr(ValidationWorkspace, name).__get__(stub))
    return stub


def test_the_attribute_options_are_the_confidence_level_alone():
    options, design, evaluation, judge = stand_in(confidence_var="99%")._read_setup()
    assert options == StatisticalOptions(method="attribute", confidence=0.99) and design == {} and not judge
    assert evaluation == EvaluationSettings()  # acceptance off: no criteria, nothing to apply


def test_acceptance_is_off_until_enabled_and_then_carries_the_minimum_agreement():
    options, _design, evaluation, judge = stand_in(judge_var=True, agreement_var="92.5")._read_setup()
    assert judge and evaluation == EvaluationSettings(agreement_min=92.5) and options.confidence == 0.95
    off = stand_in(judge_var=False, agreement_var="not read when acceptance is off")
    assert off._read_setup()[2] == EvaluationSettings() and not off._judge_for("attribute")


@pytest.mark.parametrize("values,fragment", [({"judge_var": True, "agreement_var": ""}, "Minimum agreement: enter"),
                                             ({"judge_var": True, "agreement_var": "0"}, "above 0"),
                                             ({"judge_var": True, "agreement_var": "150"}, "at most 100"),
                                             ({"confidence_var": "all"}, "Confidence level")])
def test_a_setting_that_cannot_be_used_says_what_to_fix(values, fragment):
    with pytest.raises(ValueError, match=fragment):
        stand_in(**values)._read_setup()


def test_the_other_methods_read_their_own_settings_as_before():
    options, design, evaluation, judge = stand_in(method_var="grr", study_factor_var="5")._read_setup()
    assert options.method == "grr" and options.study_factor == 5.0 and design == {} and not judge and evaluation == EvaluationSettings()
    options, design, evaluation, judge = stand_in(method_var="capability", judge_var=True, threshold_var="1.5")._read_setup()
    assert options.method == "capability" and design == {"subgroup_from_sample": False} and judge
    assert evaluation == EvaluationSettings(cpk_threshold=1.5, decision_metric="cpk")


def test_the_plan_line_counts_appraisers_for_ratings_only():
    rows = tuple(Observation("Item", f"S{s}", "PASS", trial=str(t), operator=who) for s in (1, 2) for who in ("Ann", "Ben") for t in (1, 2))
    stub = stand_in()
    stub.dataset = Dataset.from_observations(rows)
    stub.study = SimpleNamespace(options=StatisticalOptions(method="attribute"))
    assert stub._plan_text() == "1 Test Item · 2 Samples · 2 Appraisers"
    stub.study = SimpleNamespace(options=StatisticalOptions(method="grr"))
    assert stub._plan_text() == "1 Test Item · 2 Samples"
    stub.study = None
    assert stub._plan_text() == ""


def test_attribute_agreement_can_be_set_up_but_not_run_until_its_results_exist():
    assert workspace.ATTRIBUTE_RESULTS_READY is False  # the next stage builds Results, Details and Checks, and turns this on
    assert "cannot be run" in workspace.ATTRIBUTE_PENDING
    assert set(workspace.METHOD_NAMES) == set(workspace.PLAN_TITLES) == {"grr", "capability", "attribute"}
    assert workspace.CONFIDENCE_LEVELS == ("90%", "95%", "99%") and workspace.CONFIDENCE_LEVELS[1] == "95%"  # 95 % is the default
    assert workspace.ATTRIBUTE_COLUMNS == ("test_item", "sample", "operator", "trial", "value", "standard")
    assert set(workspace.DISPLAY_COLUMNS) <= set(workspace.PREVIEW_COLUMNS) and "standard" in workspace.PREVIEW_COLUMNS


def test_the_ratings_study_record_is_part_of_what_the_results_depend_on():
    imported_record = {"file": "ratings.csv", "columns": {"sample": "Samples", "rating": "Rating"}, "assign_trials": True, "categories": []}
    stub = SimpleNamespace(source_var=Var("ratings"), components=(), assignments={}, file_var=Var("ratings.csv"),
                           ratings=SimpleNamespace(record=imported_record), _order_key=lambda: "worksheet")
    record = ValidationWorkspace._mapping_record(stub)
    assert record["ratings"] == imported_record and record["source"] == "ratings" and record["file"] == ""
    stub.source_var.set("file")  # the other sources keep the record they always had
    assert "ratings" not in ValidationWorkspace._mapping_record(stub)


def test_nothing_imports_a_window_by_being_imported():
    # Importing the workspace and the import dialog must not need a display: only constructing them does.
    from datamapperx.ui import ratings_import

    assert ratings_import.NONE == "(none)" and ratings_import.PREVIEW_LIMIT == 100
    assert [key for key, *_ in ratings_import.PREVIEW_COLUMNS] == ["item", "sample", "appraiser", "trial", "rating", "standard"]
    assert dataclasses.is_dataclass(StatisticalOptions)
