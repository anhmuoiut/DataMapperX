"""The baseline comparison tolerates last-digit floating-point noise and nothing else.

Two layers: the comparison function on small structures, and a mutation check on the real engine, which nudges one
statistical constant by one part in a billion (in memory; no source is edited) and requires the baseline to notice.
"""
from __future__ import annotations

import pytest

from datamapperx.statistics import analyze, capability, grr

from .baseline_support import (
    FLOAT_REL_TOL,
    config_from_dict,
    encode,
    first_difference,
    observation_from_dict,
    result_signature,
)
from .test_regression_baseline import BASELINE


def tolerant(expected, actual):
    return first_difference(expected, actual, rel_tol=FLOAT_REL_TOL)


def ulp_up(value: float, steps: int = 2) -> float:
    import math

    for _ in range(steps):
        value = math.nextafter(value, math.inf)
    return value


# ----------------------------------------------------------------------------- what is tolerated
def test_a_difference_in_the_last_digits_of_a_float_is_tolerated():
    assert tolerant({"x": 0.001000000000000002}, {"x": 0.001000000000000001}) == ""
    assert tolerant([1.5, 2.5], [ulp_up(1.5), ulp_up(2.5, 4)]) == ""


def test_the_decimal_numbers_inside_text_may_differ_in_the_last_digits_only():
    assert tolerant("Mean=5.00000000; sigma=0.001000000000000002", "Mean=5.00000000; sigma=0.001000000000000001") == ""
    assert tolerant("F=7.70725673923162e-05 p=0.000", "F=7.70725673923164e-05 p=0.000") == ""


def test_the_comparison_is_exact_by_default():
    assert first_difference({"x": 1.0}, {"x": ulp_up(1.0, 1)}) != ""
    assert first_difference("0.1000000000000002", "0.1000000000000001") != ""


# ----------------------------------------------------------------------------- what is still caught
@pytest.mark.parametrize("expected,actual", [
    ({"x": 1.0}, {"x": 1.0 + 1e-9}),                                    # a real change, however small it looks
    ({"x": 1.0}, {"x": 1.0 + 1e-11}),
    ({"x": 0.0}, {"x": 1e-9}),                                          # something that should be zero
    ({"x": 1}, {"x": 1.0}),                                             # int versus float
    ({"x": 1}, {"x": True}),                                            # int versus bool
    ({"x": (1.0,)}, {"x": [1.0]}),                                      # tuple versus list (encoded)
    ([1.0, 2.0], [1.0]),                                                # length
    ({"x": {"__float__": "-0.0"}}, {"x": 0.0}),                         # sign of zero
    ({"x": {"__float__": "nan"}}, {"x": 1.0}),
    ({"x": {"__float__": "inf"}}, {"x": {"__float__": "-inf"}}),
    ({"x": "PASS"}, {"x": "FAIL"}),                                     # text
    ({"x": "Samples=3; n=9"}, {"x": "Samples=3; n=10"}),               # an integer inside text
    ({"x": "sigma=0.0010000"}, {"x": "sigma=0.0010001"}),               # a printed number off by 1e-4
    ({"x": "sigma=0.001"}, {"x": "gamma=0.001"}),                       # same number, different words
])
def test_everything_but_float_noise_is_still_a_difference(expected, actual):
    assert tolerant(expected, actual) != ""


def test_the_order_of_dictionary_keys_is_still_a_difference():
    """The baseline encodes a dict as a list of [key, value] pairs, so key order (which orders report rows) is compared."""
    assert tolerant(encode({"a": 1, "b": 2}), encode({"b": 2, "a": 1})) != ""
    assert tolerant(encode({"a": 1.0, "b": 2.0}), encode({"a": ulp_up(1.0), "b": ulp_up(2.0)})) == ""


# ----------------------------------------------------------------------------- the real engine
def case(name):
    return next(item for item in BASELINE["cases"] if item["name"] == name)


def signature(item):
    observations = [observation_from_dict(o) for o in item["observations"]]
    return [result_signature(r) for r in analyze(observations, config_from_dict(item["config"]))]


def test_the_untouched_engine_matches_its_baseline():
    for name in ("grr_basic", "capability_basic", "crossed_seeded_10x3x3"):
        assert tolerant(case(name)["expected"], signature(case(name))) == "", name


def test_the_baseline_notices_a_one_in_a_billion_change_to_a_gage_constant(monkeypatch):
    d2, d3 = grr.R_CONSTANTS[3]
    monkeypatch.setitem(grr.R_CONSTANTS, 3, (d2 * (1 + 1e-9), d3))
    differences = [tolerant(case(name)["expected"], signature(case(name))) for name in ("grr_basic", "crossed_seeded_10x3x3")]
    assert all(differences), differences


def test_the_baseline_notices_a_one_in_a_billion_change_to_the_capability_constant(monkeypatch):
    monkeypatch.setattr(capability, "MR_D2", capability.MR_D2 * (1 + 1e-9))
    assert tolerant(case("capability_basic")["expected"], signature(case("capability_basic"))) != ""
