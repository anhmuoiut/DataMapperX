"""Per-user preferences, remembered between runs."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .config import DEFAULT_EXPECTED_SAMPLES, DEFAULT_REPEATS
from .paths import settings_path
from .utils import atomic_write_json

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    theme: str = "system"  # "system" | "light" | "dark"
    last_profile: str = ""
    last_folder: str = ""
    last_export_dir: str = ""
    expected_samples: str = DEFAULT_EXPECTED_SAMPLES
    repeats: str = DEFAULT_REPEATS
    geometry: str = ""
    check_updates: bool = True
    skipped_version: str = ""
    # profile name -> component names the user picked last time
    component_sets: dict[str, list[str]] = field(default_factory=dict)


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError):
        logger.warning("Ignoring unreadable settings file %s", path, exc_info=True)
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    defaults = Settings()
    accepted = {}
    for f in fields(Settings):
        value = raw.get(f.name)
        # Only accept values of the right type so a hand-edited file cannot crash the UI.
        if value is not None and isinstance(value, type(getattr(defaults, f.name))):
            accepted[f.name] = value
    return Settings(**accepted)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    try:
        atomic_write_json(path or settings_path(), asdict(settings))
    except OSError:
        logger.warning("Could not save settings", exc_info=True)
