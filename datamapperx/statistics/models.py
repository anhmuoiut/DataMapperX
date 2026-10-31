"""Data contracts shared by statistics, UI, charts and report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS = "PASS"
CONDITIONAL = "CONDITIONAL PASS"
FAIL = "FAIL"
NOT_EVALUATED = "N/A"
MR_D2 = 1.128
NDC_FACTOR = 1.41
# Every Gage R&R result carries the same keys, whichever model produced it.
GRR_METRICS = ("sigma_grr", "sigma_part", "sigma_total", "percent_tolerance", "percent_study_var", "ndc",
               "variance_repeatability", "variance_part", "variance_total", "study_var", "sigma_reproducibility",
               "sigma_repeatability", "variance_reproducibility", "variance_grr")


@dataclass(frozen=True, slots=True)
class Observation:
    test_item: str
    sample_id: str
    value: Any
    lsl: Any = None
    usl: Any = None
    trial: str = ""
    tester: str = ""
    operator: str = ""
    slot: str = ""
    timestamp: str = ""
    unit: str = ""
    source: str = ""
    subgroup: str = ""


CRITERION_METRICS = ("percent_tolerance", "percent_study_var", "ndc")


@dataclass(frozen=True, slots=True)
class Criterion:
    """One acceptance rule of a customer: a metric, whether it decides, and its PASS / FAIL limits.

    Percentages (lower is better): PASS below ``pass_limit``, FAIL above ``fail_limit``, CONDITIONAL PASS between.
    NDC (higher is better): PASS at or above ``pass_limit``, FAIL below ``fail_limit``, CONDITIONAL PASS between.
    A metric that is not applied is informational only.
    """
    metric: str
    enabled: bool = True
    pass_limit: float = 10.0
    fail_limit: float = 30.0


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    method: str = "capability"
    within_method: str = "individuals"
    cpk_threshold: float = 1.33
    profile: str = "SolarEdge"
    decision_metric: str = "percent_tolerance"
    percent_pass: float = 10.0
    percent_fail: float = 30.0
    ndc_min: int = 5
    study_factor: float = 6.0
    expected_repeats: int | None = None
    assign_trials: bool = False
    precision: int = 3
    use_unbiasing: bool = True
    # Crossed Gage R&R only: Minitab removes the Sample x Operator term when its p-value reaches this level.
    interaction_alpha: float = 0.05
    # Gage R&R acceptance per customer. When set, the overall result is the worst of the applied criteria and
    # profile / decision_metric / percent_pass / percent_fail / ndc_min are ignored.
    criteria: tuple[Criterion, ...] | None = None


# Every AnalysisConfig field is exactly one of these. Statistical fields decide the numbers; evaluation fields decide
# PASS/FAIL from those numbers; display fields only change how they are shown.
STATISTICAL_FIELDS = ("method", "within_method", "use_unbiasing", "study_factor", "expected_repeats", "assign_trials",
                      "interaction_alpha")
EVALUATION_FIELDS = ("cpk_threshold", "profile", "decision_metric", "percent_pass", "percent_fail", "ndc_min", "criteria")
DISPLAY_FIELDS = ("precision",)


def statistical_config(config: AnalysisConfig) -> AnalysisConfig:
    """The statistical options of ``config`` with every evaluation and display field at its default."""
    return AnalysisConfig(**{name: getattr(config, name) for name in STATISTICAL_FIELDS})


@dataclass(frozen=True, slots=True)
class Issue:
    severity: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    method: str
    test_item: str
    system: str
    n: int
    parts: int
    repeats: int | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    lsl: float | None
    usl: float | None
    unit: str
    metrics: dict[str, float | int | None]
    status: str
    decision_metric: str
    issues: tuple[Issue, ...]
    details: dict[str, Any]
    observations: tuple[Observation, ...]
    config: AnalysisConfig = field(default_factory=AnalysisConfig)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def label(self) -> str:
        return self.test_item + (f" [{self.system}]" if self.system else "")


@dataclass(frozen=True, slots=True)
class StatisticsResult:
    """The statistics of one test item/system, before any acceptance criteria are applied.

    It depends only on the observations and the statistical options. ``facts`` holds the counts, limits and trial
    assignment flag that ``evaluate`` copies into the details, in the order the details have always listed them.
    """
    method: str
    test_item: str
    system: str
    n: int
    parts: int
    repeats: int | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    lsl: float | None
    usl: float | None
    unit: str
    metrics: dict[str, float | int | None]
    issues: tuple[Issue, ...]
    details: dict[str, Any]
    facts: dict[str, Any]
    observations: tuple[Observation, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def label(self) -> str:
        return self.test_item + (f" [{self.system}]" if self.system else "")
