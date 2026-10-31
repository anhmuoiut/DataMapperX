"""Optional statistical validation: pure calculations and immutable input snapshots."""
from .acceptance import (
    acceptance,
    criterion_status,
    decision_metric,
    describe_criterion,
    metric_label,
    percentage_status,
)
from .customers import (
    BUILTIN_CUSTOMERS,
    DEFAULT_CUSTOMER,
    DEFAULT_LIMITS,
    build_criteria,
    customers_to_json,
    merge_customers,
)
from .dataset import Dataset, snapshot_from_records
from .design import DesignError, apply_design, auto_within_method, describe_design
from .engine import analyze, compute
from .evaluation import (
    Acknowledgement,
    Condition,
    EvaluatedResultSet,
    EvaluationRecord,
    EvaluationSettings,
    Severity,
    ValidationRecord,
    ValidationState,
    Verification,
    criteria_version,
    declared_conditions,
    detect_conditions,
    evaluate,
    evaluate_unjudged,
)
from .formulas import calculation_details, explain_method, format_number, formula_sections
from .importers import ImportedData, RawDataFormatError, import_rawdata_xlsx
from .models import (
    CONDITIONAL,
    CRITERION_METRICS,
    FAIL,
    NOT_EVALUATED,
    PASS,
    AnalysisConfig,
    AnalysisResult,
    Criterion,
    Issue,
    Observation,
    StatisticsResult,
)
from .normalize import normalize_records
from .study import (
    MINITAB_VERIFIED,
    PENDING_VERIFICATION,
    ResultSet,
    StaleResultError,
    StatisticalOptions,
    StatisticsPlan,
    Study,
    StudyInfo,
    StudyInputs,
)
from .validation import validate_config, validate_criteria

__all__ = ["Acknowledgement", "AnalysisConfig", "AnalysisResult", "BUILTIN_CUSTOMERS", "CONDITIONAL", "CRITERION_METRICS",
           "Condition", "Criterion", "DEFAULT_CUSTOMER", "DEFAULT_LIMITS", "Dataset", "DesignError", "EvaluatedResultSet",
           "ImportedData", "RawDataFormatError", "apply_design", "auto_within_method", "describe_design", "detect_conditions", "evaluate_unjudged",
           "import_rawdata_xlsx",
           "EvaluationRecord", "EvaluationSettings", "FAIL", "Issue", "MINITAB_VERIFIED", "NOT_EVALUATED", "Observation",
           "PASS", "PENDING_VERIFICATION", "ResultSet", "Severity", "StaleResultError", "StatisticalOptions",
           "StatisticsPlan", "StatisticsResult", "Study", "StudyInfo", "StudyInputs", "ValidationRecord", "ValidationState",
           "Verification", "acceptance", "analyze", "build_criteria", "calculation_details", "compute",
           "criteria_version", "criterion_status", "customers_to_json", "declared_conditions", "decision_metric",
           "describe_criterion", "evaluate", "explain_method", "format_number", "formula_sections", "merge_customers",
           "metric_label", "normalize_records", "percentage_status", "snapshot_from_records", "validate_config",
           "validate_criteria"]
