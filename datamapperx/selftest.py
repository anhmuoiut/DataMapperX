"""``DataMapperX.exe --smoke-test``: prove a freshly built exe actually works.

PyInstaller can produce an exe that starts but is missing a bundled file (a theme, a codec, a module that is only
imported when a rarely used feature runs). This exercises everything the app needs, including the features that
load code late, and reports through the exit code because a windowed exe has no console. The release workflow
runs it before publishing anything.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
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
    _check_statistical_reports(folder / "statistical-reports")
    return sample


def _check_statistical_reports(folder: Path) -> None:
    """Exercise late-loaded PDF/Excel dependencies in the built executable too."""
    from openpyxl import load_workbook

    from .stat_reports import ALL_SECTIONS, ReportContext, export_statistical_report
    from .statistics import AnalysisConfig, Observation, analyze

    folder.mkdir(exist_ok=True)
    studies = (
        ("capability", [Observation("SMOKE_CAPABILITY", str(index), value, 0, 6)
                        for index, value in enumerate((1, 2, 3, 4, 5))], AnalysisConfig(), "Cpk", 2, 1.128, 1),
        ("grr", [Observation("SMOKE_GRR", str(part), value, 0, 20, trial=str(trial))
                 for part, values in enumerate(((1, 2, 3), (4, 5, 6), (7, 8, 9)))
                 for trial, value in enumerate(values)], AnalysisConfig(method="grr"), "Total Gage R&R", 5, 30.0, 4),
    )
    for method, rows, config, label, column, expected, chart_count in studies:
        results = analyze(rows, config)
        _require(len(results) == 1 and results[0].valid, f"{method} smoke dataset was not analyzable")
        pdf_path = export_statistical_report(folder / f"{method}.pdf", results)
        payload = pdf_path.read_bytes()
        _require(payload.startswith(b"%PDF-") and b"%%EOF" in payload[-1024:],
                 f"{method} PDF report was not generated correctly")
        workbook_path = export_statistical_report(folder / f"{method}.xlsx", results,
                                                  context=ReportContext(included=1, total=1, sections=ALL_SECTIONS))
        workbook = load_workbook(workbook_path)
        try:
            sheet = workbook[workbook.sheetnames[0]]
            found = [row for row in sheet.iter_rows(max_col=column) if str(row[0].value).strip() == label]
            actual = found[-1][column - 1].value
            _require(isinstance(actual, (int, float)) and abs(actual - expected) < 1e-9,
                     f"{method} report wrote the wrong metric: {actual!r}")
            _require(len(sheet._charts) == chart_count, f"{method} Excel report is missing study charts")
            _require(workbook["Observations"].max_row == len(rows) + 1,
                     f"{method} report did not retain its observations")
        finally:
            workbook.close()
    logger.info("Statistical report self-test passed (capability and GRR PDF/Excel)")
    _check_customer_criteria()


def _check_customer_criteria() -> None:
    """Per-customer Gage R&R acceptance: the same study gives each customer's own verdict."""
    from dataclasses import replace

    from .statistics import BUILTIN_CUSTOMERS, AnalysisConfig, Observation, analyze

    rows = [Observation("SMOKE_CUSTOMER", str(part), value, 0, 20, trial=str(trial))
            for part, values in enumerate(((1, 2, 3), (4, 5, 6), (7, 8, 9)))
            for trial, value in enumerate(values)]  # %SV/Tol 30, %Study Var 32.2, NDC 4
    expected = {"SolarEdge": "CONDITIONAL PASS", "Zebra": "CONDITIONAL PASS", "SES": "FAIL", "Jabil": "FAIL"}
    for name, status in expected.items():
        result, = analyze(rows, AnalysisConfig(method="grr", profile=name, criteria=BUILTIN_CUSTOMERS[name]))
        _require(result.status == status, f"customer {name} gave {result.status}, expected {status}")
    # A customer that applies only NDC and %SV/Tol, with its own limits, can accept the same study.
    relaxed = tuple(replace(c, enabled=c.metric != "percent_study_var",
                            pass_limit=40 if c.metric == "percent_tolerance" else 4,
                            fail_limit=50 if c.metric == "percent_tolerance" else 4) for c in BUILTIN_CUSTOMERS["Jabil"])
    result, = analyze(rows, AnalysisConfig(method="grr", profile="Smoke", criteria=relaxed))
    _require(result.status == "PASS" and result.details["acceptance_conflicts"] == ("percent_study_var",),
             f"custom customer limits gave {result.status}")
    logger.info("Customer acceptance self-test passed")


def _check_window(sample: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.profile_dialog import ProfileManager
    from .ui.sample_wizard import SampleWizard

    app = QApplication.instance() or QApplication([])
    window = MainWindow(app, background_checks=False)  # the build's check must not depend on GitHub, or on the owner's off switch
    try:
        window.show()
        app.processEvents()
        _require(window.isVisible(), "the main window did not open")
        _check_steps(app, window, sample.parent)
        _check_customer_dialog(app, window)
        manager = ProfileManager(window, window.profiles, lambda _name: None)
        manager.present()
        wizard = SampleWizard(manager, lambda _name, _profile: None, sample=sample)
        wizard.present()
        _wait(app, lambda: wizard.kind == "excel" and wizard.accept_button.isEnabled(), "the sample wizard to read the sample")
        wizard.close()
        manager.close()
        app.processEvents()
    finally:
        window.close()
        app.processEvents()


def _check_customer_dialog(app, window) -> None:
    """Open the customer criteria dialog, add a customer, apply a metric choice and save; then put everything back."""
    from .ui.validation_dialogs import CustomersDialog

    window._show_workspace("validation")
    panel = window.validation
    original_customers, original_choice = dict(panel.customers), panel.profile_var.get()
    try:
        dialog = CustomersDialog(panel)
        dialog.present()
        app.processEvents()
        dialog.new_edit.setText("Smoke customer")
        dialog.add_customer()
        for metric, applied in (("percent_tolerance", True), ("percent_study_var", False), ("ndc", True)):
            dialog.apply_checks[metric].setChecked(applied)
        dialog.pass_edits["percent_tolerance"].setText("15")
        dialog.fail_edits["percent_tolerance"].setText("25")
        app.processEvents()
        _require("PASS < 15%" in dialog.bands["percent_tolerance"].text(), "the dialog did not show the PASS/FAIL bands")
        dialog.save()
        app.processEvents()
        saved = panel.customers.get("Smoke customer")
        _require(saved is not None and [c.enabled for c in saved] == [True, False, True] and saved[0].pass_limit == 15,
                 "the customer criteria were not saved")
        _require(panel.profile_var.get() == "Smoke customer" and "Smoke customer" in window.settings.customer_criteria,
                 "the customer was not selected and remembered")
        _require(panel._evaluation_for("grr").criteria == saved, "the analysis does not use the customer's criteria")
    finally:
        panel.set_customers(original_customers, selected=original_choice)
        window._show_workspace("mapping")


def _wait(app, condition, what: str, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise SmokeTestError(f"timed out waiting for {what}")


def _check_steps(app, window, folder: Path) -> None:
    """Scan the sample files, pick the component and walk through both steps of the window."""
    from PySide6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):  # a dialog nobody can answer would hang the run
        raise SmokeTestError(f"the window showed a dialog: {args[2:3]}")

    logs = folder / "steps"  # only the two sample logs: the export written by the logic check must not be scanned
    logs.mkdir(exist_ok=True)
    for source in folder.glob("VSE000SMOKE_*.xlsx"):
        shutil.copy(source, logs / source.name)
    saved = {name: getattr(QMessageBox, name) for name in ("information", "warning", "critical", "question")}
    for name in saved:
        setattr(QMessageBox, name, staticmethod(refuse))
    try:
        window.profile_box.setCurrentText("Function Test Log")
        window.folder_edit.setText(str(logs))
        window.expected_edit.setText("1")
        window.repeats_edit.setText("2")
        window.scan_logs()
        _wait(app, lambda: not window.is_busy and window.scan_result is not None, "the scan")
        _require(window.scan_result.total_sns == 1, "the scan found the wrong files")
        window.clear_selected()  # the data folder may remember the choice from an earlier run
        _require("R1" in window.available_list.items(), "the window did not list the components")
        _require(window.available_list.table_model.row_text(0)[1:3] != ("–", "–"), "the component list did not show the limits")
        window.add_all_shown()
        _require(window.selected_components == ["R1"] and window.review_button.isEnabled(), "the component was not selected")
        window._show_step("review")
        app.processEvents()
        _require(window.step == "review" and len(window.preview_grid.rows()) == 2, "the review did not show the data")
        _require(len(window.limits_grid.rows()) == 1 and window.check_chips.chips(), "the review did not show the limits")
        window._show_workspace("validation")  # Validation & Reports analyses a copy of what was scanned
        workspace = window.validation
        _wait(app, lambda: workspace.dataset is not None and not workspace.busy, "the validation data")
        workspace.run_button.click()
        _wait(app, lambda: workspace.evaluated is not None and not workspace.running, "the validation analysis")
        _require(len(workspace.results) == 1 and workspace.results[0].test_item == "R1", "validation did not analyse the scan")
        window._show_workspace("mapping")
        for _ in range(2):  # dark and back again, so the setting it saves is the one it started with
            window._toggle_theme()
        window._show_step("select")
        app.processEvents()
        _require(window.step == "select", "could not go back to the first step")
        window.reset_workflow()
    finally:
        for name, original in saved.items():
            setattr(QMessageBox, name, original)
