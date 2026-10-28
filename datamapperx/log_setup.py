"""Logging configuration (rotating file so the log can never grow without bound)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_path

_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    handlers: list[logging.Handler] = []
    try:
        handlers.append(RotatingFileHandler(log_path(), maxBytes=512_000, backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    # A windowed PyInstaller build has no stderr; only attach the console handler when it exists.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(level=level, format=_FORMAT, handlers=handlers)
