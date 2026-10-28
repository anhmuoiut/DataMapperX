"""Walk a folder, parse every matching file and group the results by serial number."""

from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .models import DuplicateGroup, LogRecord, ParsedFile, ScanDiagnostics, ScanResult
from .parsing import parse_log_file
from .profiles import compile_text_profile_regexes, get_profile_extensions, validate_profile

logger = logging.getLogger(__name__)

# (files finished, files to scan). Called from the scanning thread.
ProgressCallback = Callable[[int, int], None]


def discover_files(folder: Path, cancel_event: threading.Event | None = None) -> list[Path]:
    """All regular files below ``folder``, case-insensitively sorted, Office lock files excluded."""
    found: list[Path] = []
    for root, _dirs, names in os.walk(folder):
        if cancel_event is not None and cancel_event.is_set():
            break
        found.extend(Path(root, name) for name in names if not name.startswith("~$"))
    found.sort(key=lambda p: str(p).lower())
    return found


def _parse_safely(path: Path, profile: dict, compiled: dict | None) -> ParsedFile | Exception:
    try:
        return parse_log_file(path, profile, compiled=compiled)
    except Exception as exc:
        return exc


def scan_folder(
    folder: Path,
    profile: dict,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    max_workers: int | None = None,
) -> ScanResult:
    validate_profile(profile)

    profile_type = profile.get("type", "text")
    extensions = get_profile_extensions(profile)
    logger.info("Scanning folder: %s | profile type: %s | extensions: %s", folder, profile_type, extensions)

    compiled = compile_text_profile_regexes(profile) if profile_type == "text" else None

    candidates = discover_files(folder, cancel_event)
    files = [p for p in candidates if p.suffix.lower() in extensions]
    diagnostics = ScanDiagnostics(
        profile_type=profile_type,
        extensions=extensions,
        total_file_count=len(candidates),
        accepted_file_count=len(files),
        ignored_extensions=dict(
            sorted(Counter(p.suffix.lower() or "[no extension]" for p in candidates if p.suffix.lower() not in extensions).items())
        ),
    )

    records: list[LogRecord] = []
    parse_warnings: list[str] = []
    duplicate_groups: list[DuplicateGroup] = []
    component_counter: Counter[str] = Counter()
    cancelled = bool(cancel_event and cancel_event.is_set())

    if progress:
        progress(0, len(files))

    # Logs often sit in OneDrive / network folders where opening a file is slow, so parse a few at once.
    workers = max_workers or min(8, (os.cpu_count() or 4))
    if files and not cancelled:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan") as pool:
            futures = [pool.submit(_parse_safely, path, profile, compiled) for path in files]
            # Consume in submission order so output stays deterministic regardless of thread timing.
            for done, (path, future) in enumerate(zip(files, futures, strict=True), start=1):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    for pending in futures:
                        pending.cancel()
                    logger.info("Scan cancelled by user after %d files.", len(records))
                    break

                outcome = future.result()
                if progress:
                    progress(done, len(files))

                if isinstance(outcome, Exception):
                    logger.warning("Skipped %s: %s", path, outcome)
                    parse_warnings.append(f"{path.name}: {outcome}")
                    continue
                if not outcome.sn:
                    diagnostics.skipped_without_sn.append(path.name)
                    continue
                if not outcome.entries:
                    diagnostics.files_without_components.append(path.name)

                record = LogRecord(path=path, sn=outcome.sn, entries=outcome.entries)
                component_counter.update(outcome.entries.keys())
                for component, options in outcome.duplicates.items():
                    duplicate_groups.append(
                        DuplicateGroup(component=component, row_label=outcome.row_label, options=options, record=record)
                    )
                records.append(record)

    grouped: dict[str, list[LogRecord]] = {}
    for record in records:
        grouped.setdefault(record.sn, []).append(record)
    for sn_records in grouped.values():
        sn_records.sort(key=lambda r: r.filename.lower())

    return ScanResult(
        grouped=grouped,
        components=sorted(component_counter, key=lambda s: (s.lower(), s)),
        parse_warnings=parse_warnings,
        duplicate_groups=duplicate_groups,
        diagnostics=diagnostics,
        cancelled=cancelled,
    )
