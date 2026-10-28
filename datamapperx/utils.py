"""Small helpers shared by several modules."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_positive_int(value: Any, label: str, min_value: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if parsed < min_value:
        raise ValueError(f"{label} must be at least {min_value}.")
    return parsed


def looks_like_cell_coordinate(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{1,3}\d{1,7}", safe_text(value)))


def column_number(letters: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27."""
    number = 0
    for char in letters.upper():
        number = number * 26 + ord(char) - 64
    return number


def column_letter(number: int) -> str:
    """1 -> 'A', 27 -> 'AA'."""
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def normalize_excel_column(value: Any, label: str, allow_blank: bool = False) -> str:
    col = safe_text(value).upper()
    if not col and allow_blank:
        return ""
    if not re.fullmatch(r"[A-Z]{1,3}", col):
        raise ValueError(f"{label} must be an Excel column letter, for example A, B, AA.")
    return col


def compile_profile_regex(pattern: Any, label: str, flags: int = 0) -> re.Pattern[str] | None:
    pattern = safe_text(pattern)
    if not pattern:
        return None
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid Regex in {label}: {exc}") from exc


def group_value(match: re.Match[str], name: str, *, fallback_first: bool = False) -> str:
    """Return a named group, optionally falling back to the first positional group."""
    if name in match.groupdict():
        return match.group(name) or ""
    if fallback_first and match.groups():
        return match.group(1) or ""
    return ""


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash can never leave a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=4, ensure_ascii=False))
