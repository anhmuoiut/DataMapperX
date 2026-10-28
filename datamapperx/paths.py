"""Where the app finds its resources and keeps the user's data."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import APP_TITLE, DATA_DIR_ENV

logger = logging.getLogger(__name__)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder containing the executable (frozen) or the project root (source checkout)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Read-only bundled resource. In a PyInstaller one-file build this is ``sys._MEIPASS``."""
    base = Path(getattr(sys, "_MEIPASS", "")) if is_frozen() and hasattr(sys, "_MEIPASS") else app_dir()
    return base.joinpath(*parts)


def user_data_dir() -> Path:
    """Writable per-user folder, created on demand."""
    override = os.getenv(DATA_DIR_ENV)
    if override:
        path = Path(override)
    else:
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        path = Path(base) / APP_TITLE if base else Path.home() / f".{APP_TITLE.lower()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Could not create user data directory: %s", path, exc_info=True)
        return app_dir()
    return path


def profiles_path() -> Path:
    return user_data_dir() / "profiles.json"


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def log_path() -> Path:
    return user_data_dir() / "app_debug.log"
