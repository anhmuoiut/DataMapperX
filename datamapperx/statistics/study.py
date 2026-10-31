"""Study state: what the statistics depend on, the result sets computed from it, and when those are stale.

A study holds a dataset, how it was mapped, the study design and the statistical options. Those decide the numbers, and
together they are the *statistical inputs*. A result set remembers the inputs it was computed from. Anything that is not
a statistical input (study information, criteria, acknowledgements, display decimals, report layout) can change without
making a result set stale. Stale result sets stay available for reference but are never current.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any

from .dataset import Dataset
from .design import apply_design, relevant_design
from .evaluation import (
    Acknowledgement,
    EvaluatedResultSet,
    EvaluationSettings,
    ValidationRecord,
    build_record,
    combine_config,
    detect_conditions,
    evaluate_unjudged,
    validate_evaluation_settings,
)
from .evaluation import evaluate as evaluate_statistics
from .models import STATISTICAL_FIELDS, AnalysisConfig, Observation, StatisticsResult

# ----------------------------------------------------------------------------- statistical options


@dataclass(frozen=True, slots=True)
class StatisticalOptions:
    """The fields of ``AnalysisConfig`` that decide the numbers (see ``models.STATISTICAL_FIELDS``)."""
    method: str = "capability"
    within_method: str = "individuals"
    use_unbiasing: bool = True
    study_factor: float = 6.0
    expected_repeats: int | None = None
    assign_trials: bool = False
    interaction_alpha: float = 0.05

    def relevant(self) -> dict[str, Any]:
        """The options that can change what the chosen method reports; changing any other one cannot.

        ``assign_trials`` counts for both methods because every result echoes it in its details.
        """
        names = (("method", "within_method", "use_unbiasing", "assign_trials") if self.method == "capability" else
                 ("method", "study_factor", "expected_repeats", "assign_trials", "interaction_alpha"))
        return {name: getattr(self, name) for name in names}

    def to_config(self) -> AnalysisConfig:
        return AnalysisConfig(**{name: getattr(self, name) for name in STATISTICAL_FIELDS})


def validate_statistical_options(options) -> None:
    """The statistical checks of ``validate_config`` (it accepts a config or ``StatisticalOptions``), same messages."""
    if options.method not in {"capability", "grr"}:
        raise ValueError("Select capability or grr; attribute studies are unsupported.")
    if options.within_method not in {"individuals", "pooled"}:
        raise ValueError("Within sigma method must be individuals or pooled.")
    value = options.study_factor
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("study_factor must be positive and finite.")
    alpha = options.interaction_alpha
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise ValueError("interaction_alpha must be greater than 0 and less than 1.")
    repeats = options.expected_repeats
    if repeats is not None and (not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 2):
        raise ValueError("Expected repetitions must be an integer of at least two.")


# ----------------------------------------------------------------------------- method verification

PENDING_VERIFICATION = "Pending Minitab Verification"
MINITAB_VERIFIED = "Minitab Verified"

# Whether a calculation method has been compared with Minitab output. This describes the method, not any dataset.
# A method moves to MINITAB_VERIFIED only after every Golden Test case for it passes (docs/validation-workspace-proposal.md).
METHOD_VERIFICATION: dict[str, str] = {
    "grr_one_way": PENDING_VERIFICATION,
    "grr_crossed": PENDING_VERIFICATION,
    "grr_crossed_interaction_removed": PENDING_VERIFICATION,
    "grr_crossed_interaction_retained": PENDING_VERIFICATION,
    "capability_individuals": PENDING_VERIFICATION,
    "capability_pooled": PENDING_VERIFICATION,
}


def method_key(stat: StatisticsResult, options: StatisticalOptions) -> str:
    if options.method == "capability":
        return f"capability_{options.within_method}"
    if not stat.facts.get("crossed"):
        return "grr_one_way"
    removed = stat.details.get("interaction_removed")
    return "grr_crossed" if removed is None else f"grr_crossed_interaction_{'removed' if removed else 'retained'}"


def method_verification(key: str) -> str:
    """Unknown methods are never reported as verified."""
    return METHOD_VERIFICATION.get(key, PENDING_VERIFICATION)


# ----------------------------------------------------------------------------- inputs, info, result sets


def _hash_json(value) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StudyInputs:
    """A hash for each thing the statistics depend on, so a stale result can say which one changed."""
    dataset: str
    mapping: str
    design: str
    options: str

    @property
    def combined(self) -> str:
        return "inputs-v1:" + hashlib.sha256("\x1f".join((self.dataset, self.mapping, self.design, self.options)).encode()).hexdigest()

    def differences(self, other: StudyInputs) -> tuple[str, ...]:
        return tuple(f.name for f in fields(self) if getattr(self, f.name) != getattr(other, f.name))


@dataclass(frozen=True, slots=True)
class StudyInfo:
    """Identification of the study for the report. Not a statistical input: editing it never makes results stale."""
    gage_name: str = ""
    date_of_study: str = ""
    reported_by: str = ""
    misc: str = ""
    gage_resolution: str = ""
    equipment_id: str = ""
    product: str = ""
    workcell: str = ""


@dataclass(frozen=True, slots=True)
class ResultSet:
    """Statistics computed from one state of the study's inputs."""
    id: str
    inputs: StudyInputs
    options: StatisticalOptions
    statistics: tuple[StatisticsResult, ...]
    method_verification: tuple[tuple[str, str], ...]  # method key -> verification status, for the methods used
    design: dict[str, Any] = field(default_factory=dict, compare=False)  # the part of the study design that mattered


@dataclass(frozen=True, slots=True)
class StatisticsPlan:
    """Everything one statistics run needs, taken from the study at one moment. ``execute`` touches no study state, so
    it can run on a worker thread while the study is edited; the result set records the inputs the plan was made from."""
    options: StatisticalOptions
    inputs: StudyInputs
    observations: tuple[Observation, ...]
    design: dict[str, Any] = field(default_factory=dict, compare=False)

    def execute(self) -> ResultSet:
        from .engine import compute  # the engine imports this module for its validation

        statistics = tuple(compute(self.observations, self.options.to_config()))
        keys = dict.fromkeys(method_key(stat, self.options) for stat in statistics)
        return ResultSet("", self.inputs, self.options, statistics, tuple((key, method_verification(key)) for key in keys),
                         dict(self.design))


class StaleResultError(RuntimeError):
    """A result set is being used as current although its inputs have changed."""


class Study:
    """The dataset, mapping, design and options; the result sets computed from them; and everything around them."""

    def __init__(self, dataset: Dataset, *, mapping: Mapping[str, Any] | None = None, design: Mapping[str, Any] | None = None,
                 options: StatisticalOptions | None = None, evaluation: EvaluationSettings | None = None,
                 info: StudyInfo | None = None):
        self.dataset = dataset
        self.mapping: dict[str, Any] = dict(mapping or {})
        self.design: dict[str, Any] = dict(design or {})
        self.options = options or StatisticalOptions()
        self.evaluation = evaluation or EvaluationSettings()  # criteria: not a statistical input
        self.info = info or StudyInfo()  # not a statistical input
        self.result_sets: list[ResultSet] = []

    # -- inputs and staleness
    def inputs(self) -> StudyInputs:
        return StudyInputs(self.dataset.fingerprint, _hash_json(self.mapping),
                           _hash_json(relevant_design(self.design, self.options.method)), _hash_json(self.options.relevant()))

    def analysis_observations(self) -> tuple[Observation, ...]:
        """The observations that are analysed: the dataset with the study design applied (the dataset is untouched)."""
        return apply_design(self.dataset.observations, self.design, self.options.method)

    def stale_reasons(self, result_set: ResultSet) -> tuple[str, ...]:
        """Which statistical inputs differ from the ones the result set was computed from (empty when current)."""
        return result_set.inputs.differences(self.inputs())

    def is_stale(self, result_set: ResultSet) -> bool:
        return bool(self.stale_reasons(result_set))

    def require_current(self, result_set: ResultSet) -> ResultSet:
        """For anything that presents results as current, such as a report."""
        reasons = self.stale_reasons(result_set)
        if reasons:
            raise StaleResultError(f"Result set {result_set.id} is stale: {', '.join(reasons)} changed since it was computed.")
        return result_set

    # -- statistics and evaluation
    def plan_statistics(self) -> StatisticsPlan:
        """Capture the current inputs (call on the thread that edits the study). Raises when the study cannot be analysed."""
        validate_statistical_options(self.options)
        return StatisticsPlan(self.options, self.inputs(), self.analysis_observations(),
                              relevant_design(self.design, self.options.method))

    def adopt(self, result_set: ResultSet) -> ResultSet:
        """Number a finished result set and keep it with the study."""
        result_set = replace(result_set, id=f"RS-{len(self.result_sets) + 1:04d}")
        self.result_sets.append(result_set)
        return result_set

    def run_statistics(self) -> ResultSet:
        return self.adopt(self.plan_statistics().execute())

    def evaluate(self, result_set: ResultSet, settings: EvaluationSettings | None = None,
                 acknowledgements: Iterable[Acknowledgement] = (), *, judge: bool = True) -> EvaluatedResultSet:
        """Put finished statistics beside acceptance criteria. Never recomputes them, so changing the criteria cannot change
        a metric. With ``judge=False`` no criteria are applied at all and the results are statistics only."""
        settings = settings or self.evaluation
        method = result_set.options.method
        config = combine_config(result_set.options, settings)
        if judge:
            validate_evaluation_settings(settings, method)
            results = evaluate_statistics(result_set.statistics, config)
        else:
            results = [evaluate_unjudged(stat, config) for stat in result_set.statistics]
        conditions = detect_conditions(result_set.statistics, method, self.dataset.order_basis, result_set.design)
        validation = ValidationRecord(conditions, tuple(acknowledgements))
        record = build_record(method, settings, validation, result_set.inputs.combined, judge)
        return EvaluatedResultSet(result_set.id, record, tuple(results))


__all__ = ["METHOD_VERIFICATION", "MINITAB_VERIFIED", "PENDING_VERIFICATION", "ResultSet", "StaleResultError",
           "StatisticalOptions", "StatisticsPlan", "Study", "StudyInfo", "StudyInputs", "method_key", "method_verification",
           "validate_statistical_options"]
