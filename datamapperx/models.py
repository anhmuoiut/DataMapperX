"""Plain data containers passed between the parser, scanner, exporter and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Measurement:
    component: str
    measured: str
    min_value: str = ""
    max_value: str = ""
    unit: str = ""
    source_row: str = ""


@dataclass(slots=True)
class ParsedFile:
    """What a parser extracted from one file."""

    sn: str
    entries: dict[str, Measurement]
    # component -> every occurrence (including the first one that went into ``entries``)
    duplicates: dict[str, list[Measurement]]
    row_label: str = "Rows"


@dataclass(slots=True)
class LogRecord:
    path: Path
    sn: str
    entries: dict[str, Measurement] = field(default_factory=dict)

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(slots=True)
class DuplicateGroup:
    """A component that appears more than once in a single file."""

    component: str
    row_label: str
    options: list[Measurement]
    record: LogRecord


@dataclass(slots=True)
class ScanDiagnostics:
    profile_type: str
    extensions: tuple[str, ...]
    total_file_count: int = 0
    accepted_file_count: int = 0
    ignored_extensions: dict[str, int] = field(default_factory=dict)
    skipped_without_sn: list[str] = field(default_factory=list)
    files_without_components: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScanResult:
    grouped: dict[str, list[LogRecord]]
    components: list[str]
    parse_warnings: list[str]
    duplicate_groups: list[DuplicateGroup]
    diagnostics: ScanDiagnostics
    cancelled: bool = False

    @property
    def total_sns(self) -> int:
        return len(self.grouped)

    @property
    def total_files(self) -> int:
        return sum(len(records) for records in self.grouped.values())

    def sns_with_wrong_repeat_count(self, expected: int) -> list[str]:
        return [sn for sn, records in sorted(self.grouped.items()) if len(records) != expected]
