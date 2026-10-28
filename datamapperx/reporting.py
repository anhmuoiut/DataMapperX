"""Human-readable explanations of what a scan found (pure functions, no UI)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .models import ScanResult
from .profiles import get_profile_extensions

_PREVIEW_ITEMS = 8


@dataclass(slots=True)
class ScanSummary:
    level: str  # "ok" | "warn" | "bad"
    headline: str
    issues: list[str] = field(default_factory=list)


def _clip(items: Sequence[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def summarize_scan(result: ScanResult, expected_sns: int, repeats: int) -> ScanSummary:
    issues: list[str] = []
    level = "ok"

    if result.cancelled:
        issues.append("The scan was cancelled; results may be incomplete.")
    if result.total_sns != expected_sns:
        issues.append(f"Expected {expected_sns} samples but found {result.total_sns}.")

    wrong = result.sns_with_wrong_repeat_count(repeats)
    if wrong:
        level = "bad"
        issues.append(f"{len(wrong)} sample(s) do not have exactly {repeats} files: {_clip(wrong)}.")
    if result.parse_warnings:
        level = "bad"
        issues.append(f"{len(result.parse_warnings)} file(s) could not be read and were skipped.")

    diag = result.diagnostics
    if diag.skipped_without_sn:
        issues.append(f"{len(diag.skipped_without_sn)} file(s) had no serial number and were skipped.")
    if not result.components and diag.files_without_components:
        level = "bad"
        issues.append("Serial numbers were found, but no components matched this profile's measurement rules.")

    if issues and level == "ok":
        level = "warn"
    if not issues:
        return ScanSummary("ok", f"Ready to export: {result.total_sns} samples × {repeats} files each.")

    headline = "Needs attention" if level == "bad" else "Check before exporting"
    return ScanSummary(level, headline, issues)


def full_report(result: ScanResult, expected_sns: int, repeats: int) -> str:
    """Everything the compact summary leaves out."""
    lines = [
        f"Samples found: {result.total_sns} (expected {expected_sns})",
        f"Files used: {result.total_files}",
        f"Components: {len(result.components)}",
    ]
    wrong = result.sns_with_wrong_repeat_count(repeats)
    if wrong:
        lines += ["", f"Samples without exactly {repeats} files:"]
        lines += [f"  • {sn}: {len(result.grouped[sn])} file(s)" for sn in wrong]
    if result.parse_warnings:
        lines += ["", "Files that could not be read:"]
        lines += [f"  • {warning}" for warning in result.parse_warnings]
    skipped = result.diagnostics.skipped_without_sn
    if skipped:
        lines += ["", "Files without a serial number (skipped):"]
        lines += [f"  • {name}" for name in skipped[:50]]
        if len(skipped) > 50:
            lines.append(f"  … and {len(skipped) - 50} more")
    if result.cancelled:
        lines += ["", "The scan was cancelled before every file was read."]
    return "\n".join(lines)


def describe_empty_scan(folder: Path, profile_name: str, profile: dict, result: ScanResult) -> str:
    """Explain why a scan produced nothing, and what to try."""
    diag = result.diagnostics
    extensions = ", ".join(diag.extensions or get_profile_extensions(profile))
    input_type = "Excel log" if diag.profile_type == "excel" else "Text log"

    lines = [
        "No valid log data found.",
        "",
        f"Selected profile: {profile_name} ({input_type})",
        f"Accepted files: {extensions}",
        f"Source folder: {folder}",
        "",
    ]
    if diag.total_file_count == 0:
        lines.append("Reason: The selected folder does not contain any files.")
    elif diag.accepted_file_count == 0:
        lines.append("Reason: No files match the selected profile's accepted file types.")
        found = ", ".join(f"{ext} ({n})" for ext, n in sorted(diag.ignored_extensions.items()))
        if found:
            lines.append(f"Files found instead: {found}")
        lines.append("Action: Choose a profile that matches these files, or select a different folder.")
    elif result.parse_warnings:
        lines.append(f"Reason: {diag.accepted_file_count} accepted file(s) were found, but none could be read.")
        lines += ["", "Problems:", *result.parse_warnings[:_PREVIEW_ITEMS]]
    elif diag.skipped_without_sn:
        lines.append(f"Reason: {diag.accepted_file_count} file(s) were read, but no serial number matched this profile.")
        lines.append("Action: Check SN_Regex / Cell in Manage Profiles, or choose the correct profile.")
        lines += ["", "Example files:", *diag.skipped_without_sn[:_PREVIEW_ITEMS]]
    elif diag.files_without_components:
        lines.append("Reason: Serial numbers were found, but no components matched this profile's measurement rules.")
        lines.append("Action: Check Name_Regex, Measure_Regex and the min/max regexes in Manage Profiles.")
        lines += ["", "Example files:", *diag.files_without_components[:_PREVIEW_ITEMS]]
    else:
        lines.append("Reason: The files were read, but no valid records were produced.")
        lines.append("Action: Verify the selected profile matches the file format.")
    return "\n".join(lines)
