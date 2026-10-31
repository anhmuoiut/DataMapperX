"""Phase 0 regression baseline: statistics output must stay exactly as it was before the refactor.

``tests/fixtures/baseline/analyze_baseline.json`` was generated from the pre-Phase-0 code by ``tests/make_baseline.py``.
It records behaviour; it is not a Minitab verification. Compared: metrics, statuses, issues in order, details (including
key order), and what the preview, details dialog, charts and reports derive from them.

Floating-point numbers (and the decimal numbers printed inside text) are compared with a relative tolerance of
``FLOAT_REL_TOL`` (1e-12), because other CPUs and math libraries differ in the last digits of a double (seen up to 4e-15
on Apple Silicon). Everything else stays exact: text, integers, booleans, tuple versus list, key order, the sign of zero,
NaN and infinity. ``tests/test_baseline_compare.py`` proves the comparison still catches a real change.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from datamapperx.statistics import analyze, explain_method

from .baseline_support import (
    FLOAT_REL_TOL,
    config_from_dict,
    first_difference,
    observation_from_dict,
    result_signature,
)

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "baseline" / "analyze_baseline.json").read_text(encoding="utf-8"))


def test_baseline_covers_every_method_and_model():
    names = {case["name"] for case in BASELINE["cases"]}
    assert len(names) == len(BASELINE["cases"]) >= 75
    for expected in ("grr_basic", "grr_seeded_customer_Jabil", "crossed_interaction_retained", "capability_pooled",
                     "capability_30_units_x_3_individuals", "grr_empty_input"):
        assert expected in names
    assert len(BASELINE["config_errors"]) >= 20 and len(BASELINE["explain"]) >= 6


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda case: case["name"])
def test_analyze_output_is_unchanged(case):
    observations = [observation_from_dict(item) for item in case["observations"]]
    actual = [result_signature(result) for result in analyze(observations, config_from_dict(case["config"]))]
    difference = first_difference(case["expected"], actual, rel_tol=FLOAT_REL_TOL)
    if difference:
        pytest.fail(f"{case['name']}: {difference}")


@pytest.mark.parametrize("case", BASELINE["config_errors"], ids=lambda case: case["name"])
def test_invalid_configuration_messages_are_unchanged(case):
    assert case["message"] is not None
    with pytest.raises(ValueError) as caught:
        analyze([], config_from_dict(case["config"]))
    assert str(caught.value) == case["message"]


@pytest.mark.parametrize("case", BASELINE["explain"], ids=lambda case: case["name"])
def test_method_explanations_are_unchanged(case):
    assert explain_method(config_from_dict(case["config"])) == case["text"]
