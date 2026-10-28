"""Program entry point.

Command line (all optional; with none, the window opens):

    --smoke-test    start every component once and exit 0 (ok) or 1 (broken); used by the release build
    --update        check GitHub, install a newer version if there is one, and exit without opening a window
    --restart       with --update: start the new version afterwards
    --version       write the version to the log and exit
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys

from . import updater
from ._version import __version__
from .config import APP_TITLE
from .log_setup import setup_logging

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_SELF_UPDATE = 2


def _enable_dpi_awareness() -> None:
    """Render crisply on scaled displays instead of letting Windows blur the window."""
    if sys.platform != "win32":
        return
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        logger.debug("Could not set DPI awareness", exc_info=True)


def headless_update(restart: bool) -> int:
    try:
        info = updater.check_for_update()
        if info is None:
            logger.info("%s %s is up to date", APP_TITLE, __version__)
            return EXIT_OK
        if not updater.can_self_update():
            logger.error("Version %s is available but this copy cannot replace itself", info.version)
            return EXIT_CANNOT_SELF_UPDATE
        staged = updater.staging_path()
        updater.download_update(info, staged)
        updater.install_update(staged, relaunch=updater.relaunch_app if restart else None)
        logger.info("Updated %s -> %s", __version__, info.version)
        return EXIT_OK
    except updater.UpdateError as exc:
        logger.error("Update failed: %s", exc)
        return EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_TITLE, description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true", help=argparse.SUPPRESS)
    args, _unknown = parser.parse_known_args(argv)

    setup_logging()
    logger.info("%s %s starting", APP_TITLE, __version__)

    if args.version:
        print(f"{APP_TITLE} {__version__}")
        return EXIT_OK
    if args.update:
        return headless_update(args.restart)

    _enable_dpi_awareness()
    if args.smoke_test:
        from . import selftest

        return selftest.run()

    from .ui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()
    return EXIT_OK
