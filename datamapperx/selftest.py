"""``DataMapperX.exe --smoke-test``: prove a freshly built exe actually works.

PyInstaller can produce an exe that starts but is missing a bundled file (a theme, a codec, a module that is only
imported when a rarely used feature runs). This exercises everything the app needs, including the features that
load code late, and reports through the exit code because a windowed exe has no console. The release workflow
runs it before publishing anything.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class SmokeTestError(Exception):
    """Something the application needs is missing or gives a wrong answer."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeTestError(message)


def run() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="dmx_smoke_") as tmp:
            sample = _check_logic(Path(tmp))
            _check_window(sample)
    except Exception:
        logger.exception("Smoke test failed")
        return 1
    logger.info("Smoke test passed")
    return 0


def _check_logic(folder: Path) -> Path:
    """Write, scan (fast reader and the openpyxl fallback), detect a profile and export. Returns a sample workbook."""
    from openpyxl import Workbook, load_workbook

    from .exporter import generate_excel
    from .profiles import DEFAULT_PROFILES
    from .sampling import detect_excel
    from .scanner import scan_folder
    from .xlsx import OpenpyxlReader, XlsxReader

    for run_no in (1, 2):
        wb = Workbook()
        wb.active.title = "Session"
        wb.active["B2"] = "VSE000SMOKE"
        results = wb.create_sheet("Results")
        results.append(["#", "Id", "Test", "Type", "Min", "Measured", "Max", "Unit"])
        results.append([1, 1, "R1", "MinMax", 0, 1.5 * run_no, 3, "V"])
        wb.save(folder / f"VSE000SMOKE_{run_no}.xlsx")
    sample = folder / "VSE000SMOKE_1.xlsx"

    result = scan_folder(folder, dict(DEFAULT_PROFILES["Function Test Log"]))
    _require(result.total_sns == 1 and result.total_files == 2, "scan found the wrong files")

    with XlsxReader(sample) as fast, OpenpyxlReader(sample) as slow:  # the fallback is rarely used, so test it here
        _require(fast.sheet_names == slow.sheet_names == ["Session", "Results"], "the two readers disagree on sheets")
        _require(fast.grid("Results", 5, 8)[1][:6] == slow.grid("Results", 5, 8)[1][:6], "the two readers disagree on cells")

    detected = detect_excel(sample).profile
    _require(detected["data_sheet"] == "Results" and detected["measure_col"] == "F", "profile detection failed")

    output = folder / "out.xlsx"
    generate_excel(result.grouped, ["R1"], output, expected_repeated=2)
    sheet = load_workbook(output)["Raw Data"]
    _require(sheet["C2"].value == 1.5 and sheet["C3"].value == 3, "export wrote the wrong values")
    return sample


def _check_window(sample: Path) -> None:
    from .ui.main_window import MainWindow
    from .ui.profile_dialog import ProfileManager
    from .ui.sample_wizard import SampleWizard

    app = MainWindow()
    try:
        app.update()
        _require(bool(app.winfo_exists()), "the main window did not open")
        manager = ProfileManager(app, app.profiles, lambda _name: None)
        wizard = SampleWizard(app, lambda _name, _profile: None, sample=sample)
        for _ in range(5):
            app.update()
        _require(wizard.kind == "excel", "the sample wizard did not read the sample")
        wizard.destroy()
        manager.destroy()
    finally:
        app.destroy()
