"""``DataMapperX.exe --smoke-test``: prove a freshly built exe actually works.

PyInstaller can produce an exe that starts but is missing a bundled file (a theme, a codec).
This exercises every dependency the app needs and reports through the exit code, because a
windowed exe has no console. The release workflow runs it before publishing anything.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def run() -> int:
    try:
        _check_logic()
        _check_window()
    except Exception:
        logger.exception("Smoke test failed")
        return 1
    logger.info("Smoke test passed")
    return 0


def _check_logic() -> None:
    from openpyxl import Workbook, load_workbook

    from .exporter import generate_excel
    from .profiles import DEFAULT_PROFILES
    from .scanner import scan_folder

    with tempfile.TemporaryDirectory(prefix="dmx_smoke_") as tmp:
        folder = Path(tmp)
        for run_no in (1, 2):
            wb = Workbook()
            wb.active.title = "Session"
            wb.active["B2"] = "VSE000SMOKE"
            results = wb.create_sheet("Results")
            results.append(["", "", "Component", "", "Min", "Measured", "Max", "Unit"])
            results.append(["", "", "R1", "", 0, 1.5 * run_no, 3, "V"])
            wb.save(folder / f"VSE000SMOKE_{run_no}.xlsx")

        result = scan_folder(folder, dict(DEFAULT_PROFILES["Function Test Log"]))
        assert result.total_sns == 1 and result.total_files == 2, "scan found the wrong files"

        output = folder / "out.xlsx"
        generate_excel(result.grouped, ["R1"], output, expected_repeated=2)
        sheet = load_workbook(output)["Raw Data"]
        assert sheet["C2"].value == 1.5 and sheet["C3"].value == 3, "export wrote the wrong values"


def _check_window() -> None:
    from .ui.main_window import MainWindow

    app = MainWindow()
    try:
        app.update()
        assert app.winfo_exists()
    finally:
        app.destroy()
