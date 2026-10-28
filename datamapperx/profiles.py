"""Profile definitions: how to read one family of log files.

Profiles live in ``profiles.json`` in the user data folder. The two built-in
profiles are always restored from ``DEFAULT_PROFILES`` so they stay predictable;
anything else in the file is the user's own and is never overwritten silently.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import EXCEL_FILE_EXTENSIONS, TEXT_FILE_EXTENSIONS
from .paths import app_dir, profiles_path
from .utils import (
    atomic_write_json,
    compile_profile_regex,
    looks_like_cell_coordinate,
    normalize_excel_column,
    parse_positive_int,
    safe_text,
)

logger = logging.getLogger(__name__)

BUILT_IN_PROFILE_NAMES = ("ICT_I3070 Test Log", "Function Test Log")

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "ICT_I3070 Test Log": {
        "type": "text",
        "file_extensions": ".log,.txt,.csv",
        "sn_regex": r"(VSE[A-Z0-9]+)",
        "block_regex": r"\{@BLOCK\|(?P<component>[^|]+)\|00\b",
        "measure_regex": r"\{@A-(?P<type>[A-Z0-9]+)\|[^|]*\|(?P<measured>[+-]?\d+(?:\.\d+)?E[+-]?\d+)(?P<tail>.*)",
        "lim2_regex": r"\{@LIM2\|(?P<max>[+-]?\d+(?:\.\d+)?E[+-]?\d+)\|(?P<min>[+-]?\d+(?:\.\d+)?E[+-]?\d+)\}\}",
        "lim3_regex": r"\{@LIM3\|(?P<normal>[+-]?\d+(?:\.\d+)?E[+-]?\d+)\|(?P<max>[+-]?\d+(?:\.\d+)?E[+-]?\d+)\|(?P<min>[+-]?\d+(?:\.\d+)?E[+-]?\d+)\}\}",
    },
    "Function Test Log": {
        "type": "excel",
        "file_extensions": ".xlsx,.xlsm",
        "sn_regex": r"(VSE[A-Z0-9]+)",
        "sn_sheet": "Session",
        "data_sheet": "Results",
        "row_start": "2",
        "component_col": "C",
        "measure_col": "F",
        "min_col": "E",
        "max_col": "G",
        "unit_col": "H",
    },
}

# Names used by earlier versions of the app.
_LEGACY_NAMES = (
    ("HP3070 (Built-in)", "ICT_I3070 Test Log"),
    ("FT build", "Function Test Log"),
    ("ICT_3070", "ICT_I3070 Test Log"),
)


def get_profile_extensions(profile: dict) -> tuple[str, ...]:
    raw = profile.get("file_extensions")
    if isinstance(raw, str) and raw.strip():
        parts: list[Any] = re.split(r"[,;\s]+", raw.strip())
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = list(EXCEL_FILE_EXTENSIONS if profile.get("type") == "excel" else TEXT_FILE_EXTENSIONS)

    cleaned: list[str] = []
    for item in parts:
        item = safe_text(item).lower()
        if item:
            cleaned.append(item if item.startswith(".") else f".{item}")
    return tuple(dict.fromkeys(cleaned)) or TEXT_FILE_EXTENSIONS


def compile_text_profile_regexes(profile: dict) -> dict[str, re.Pattern[str] | None]:
    """Compile every regex of a text profile once. Raises ``ValueError`` on a bad pattern."""
    return {
        "sn_re": compile_profile_regex(profile.get("sn_regex", ""), "SN_Regex", re.IGNORECASE),
        "block_re": compile_profile_regex(profile.get("block_regex", ""), "Name_Regex", re.IGNORECASE),
        "measure_re": compile_profile_regex(profile.get("measure_regex", ""), "Measure_Regex", re.IGNORECASE),
        "lim2_re": compile_profile_regex(profile.get("lim2_regex", ""), "Min_Max_Regex1"),
        "lim3_re": compile_profile_regex(profile.get("lim3_regex", ""), "Min_Max_Regex2"),
    }


def validate_profile(profile: dict) -> None:
    profile_type = profile.get("type", "text")
    if profile_type not in ("text", "excel"):
        raise ValueError("Profile type must be either 'text' or 'excel'.")

    if profile_type == "text":
        if not safe_text(profile.get("block_regex")):
            raise ValueError("Text profile is missing Name_Regex.")
        if not safe_text(profile.get("measure_regex")):
            raise ValueError("Text profile is missing Measure_Regex.")
        compile_text_profile_regexes(profile)
        return

    parse_positive_int(profile.get("row_start", 2), "Row_Start")
    normalize_excel_column(profile.get("component_col", "A"), "Component_Col")
    normalize_excel_column(profile.get("measure_col", "B"), "Measure_Col")
    normalize_excel_column(profile.get("min_col", "C"), "Min_Col", allow_blank=True)
    normalize_excel_column(profile.get("max_col", "D"), "Max_Col", allow_blank=True)
    normalize_excel_column(profile.get("unit_col", "E"), "Unit_Col", allow_blank=True)

    sn_rule = safe_text(profile.get("sn_regex", ""))
    if sn_rule and not looks_like_cell_coordinate(sn_rule):
        compile_profile_regex(sn_rule, "SN_Regex", re.IGNORECASE)


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------
def _fresh_defaults() -> dict[str, dict[str, Any]]:
    return json.loads(json.dumps(DEFAULT_PROFILES))


def _seed_if_needed(path: Path) -> None:
    """First run only: copy a ``profiles.json`` placed next to the exe, else write defaults."""
    if path.exists():
        return
    shipped = app_dir() / "profiles.json"
    try:
        if shipped.exists() and shipped.resolve() != path.resolve():
            shutil.copy2(shipped, path)
            return
    except OSError:
        logger.warning("Could not seed profiles from %s", shipped, exc_info=True)
    try:
        atomic_write_json(path, _fresh_defaults())
    except OSError:
        logger.warning("Could not write default profiles to %s", path, exc_info=True)


def _back_up_corrupt(path: Path) -> None:
    backup = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(path, backup)
        logger.warning("profiles.json was unreadable; a copy was kept at %s", backup)
    except OSError:
        logger.warning("Could not back up unreadable profiles file", exc_info=True)


def load_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or profiles_path()
    _seed_if_needed(path)

    data: dict[str, Any] = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("profiles.json must contain a JSON object")
        data = loaded
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        logger.exception("Could not load %s", path)
        # Keep the unreadable file so the user's custom profiles are not lost when we rewrite it.
        _back_up_corrupt(path)

    changed = False
    for old_name, new_name in _LEGACY_NAMES:
        if old_name in data:
            data[new_name] = data.pop(old_name)
            changed = True

    # Built-ins first (stable order), then the user's own profiles.
    ordered: dict[str, dict[str, Any]] = {}
    for name, definition in _fresh_defaults().items():
        if data.get(name) != definition:
            changed = True
        ordered[name] = definition
    for name, definition in data.items():
        if name in ordered:
            continue
        if isinstance(definition, dict):
            ordered[name] = definition
        else:
            changed = True
            logger.warning("Ignoring malformed profile %r", name)

    if changed:
        try:
            save_profiles(ordered, path)
        except OSError:
            logger.warning("Could not save profiles to %s", path, exc_info=True)
    return ordered


def save_profiles(profiles: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    atomic_write_json(path or profiles_path(), profiles)
