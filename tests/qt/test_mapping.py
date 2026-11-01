"""Data Mapping in the Qt window: scan, lists, review, export, the GRR pre-check, and the checks behind the window.

These follow the behaviours the Tk window was tested for (tests/test_ui.py), on the Qt widgets and headless.
"""
from __future__ import annotations

import time
from dataclasses import replace

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from shiboken6 import isValid

from datamapperx import access, updater
from datamapperx._version import __version__
from datamapperx.config import PREVIEW_COLUMNS_PER_PAGE as PAGE
from datamapperx.settings import load_settings
from datamapperx.ui_qt import main_window as mw
from datamapperx.ui_qt.access_dialog import AccessDialog
from datamapperx.ui_qt.dialogs import AboutDialog, ExportDoneDialog, GrrCriteriaDialog, ReportDialog
from datamapperx.ui_qt.duplicate_dialog import DuplicateDialog
from datamapperx.ui_qt.update_dialog import UpdateDialog

from ..conftest import ict_block, write_ict_log
from .support import make_logs, pump, ready_to_review, scan


class FakeDialog:
    """Stands in for a dialog class: remembers how it was made, shows nothing."""

    made: list = []

    def __init__(self, *args, **kwargs):
        type(self).made.append((args, kwargs))

    def present(self):
        pass


def fake_dialog():
    return type("Fake", (FakeDialog,), {"made": []})


# ----------------------------------------------------------------------------- the window
def test_builds_in_light_and_dark(app, window):
    assert window.palette_tokens.mode == "light" and window.theme_button.text().endswith("Dark mode")
    window._toggle_theme()
    app.processEvents()
    assert window.palette_tokens.mode == "dark" and window.theme_button.text().endswith("Light mode")
    assert window.settings.theme == "dark" and window.step_bar._palette is window.palette_tokens
    assert window.brand_logo.isVisibleTo(window) == bool(window._brand.get("dark"))
    window._toggle_theme()
    assert window.palette_tokens.mode == "light"


def test_the_header_keeps_the_mode_and_help_buttons_and_the_version_sits_in_the_source_card(app, window):
    assert window.theme_button.isVisible() and window.help_button.isVisible()
    assert __version__ not in window.findChild(type(window.theme_button).__mro__[-2], "appTitle").text()
    assert window.version_label.text().startswith(f"Version {__version__}")
    actions = [a.text() for a in window.help_button.menu().actions() if a.text()]
    assert actions[:2] == ["Check for updates…", "Tell me about new versions"] and actions[-1].startswith("About ")


def test_logo_pictures_are_shipped_for_both_themes_and_sizes():
    from datamapperx.paths import resource_path

    for mode in ("light", "dark"):
        for height in (38, 76):
            assert resource_path("assets", f"Jabil-Logo-{mode}-{height}.png").exists()
    assert resource_path("assets", "DataMapperX.ico").exists()


def test_saved_geometry_is_clamped_to_the_available_display(app, window):
    window.settings.geometry = "5000x4000+9000+9000"
    window._setup_geometry()
    area = window.screen().availableGeometry()
    assert window.width() <= area.width() and window.height() <= area.height()
    assert window.x() >= area.left() and window.y() >= area.top()
    assert mw.parse_geometry("1200x800+40+30") == (1200, 800, 40, 30) and mw.parse_geometry("garbage") is None


def test_closing_saves_the_place_and_the_inputs_and_cancels_a_running_scan(app, window, tmp_path):
    window.folder_edit.setText("C:/some/where")
    window._cancel.clear()
    window.close()
    saved = load_settings()
    assert window._cancel.is_set() and saved.last_folder == "C:/some/where"
    assert mw.parse_geometry(saved.geometry) is not None


# ----------------------------------------------------------------------------- scan, lists, export
def test_scan_pick_preview_and_export(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    assert (window.samples_value.text(), window.files_value.text(), window.components_value.text()) == ("3 / 3", "6", "3")
    assert window.available_list.items() == ["C1", "R1", "R2"]
    assert "Ready to export" in window.verdict.text()

    window.available_list.select_rows([1, 2])
    window.add_components()
    assert window.selected_components == ["R1", "R2"] and window.available_list.items() == ["C1"]

    window._show_step("review")
    assert window.step == "review" and len(window.preview_grid.rows()) == 6
    first = window.preview_grid.rows()[0]
    assert first[:3] == ("1", "VSE001", "VSE001_1.log") and first[3:] == ("+1.5E+00", "+1.5E+00")

    out = tmp_path / "result.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    opened = []
    monkeypatch.setattr(mw, "ExportDoneDialog", lambda parent, path: type("D", (), {"present": lambda self: opened.append(path)})())
    window.export_excel()
    pump(app, lambda: not window.is_busy and opened)
    sheet = load_workbook(out)["Raw Data"]
    assert [c.value for c in sheet[1]][:4] == ["STT", "SN", "R1", "R2"]
    assert sheet.max_row == 7 and sheet["B2"].value == "VSE001" and opened == [out]


def test_export_writes_the_same_workbook_as_the_core_exporter(app, window, tmp_path, monkeypatch):
    from datamapperx.exporter import generate_excel
    from datamapperx.scanner import scan_folder

    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    window._add(["R1", "R2"])
    target = tmp_path / "from_qt.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    monkeypatch.setattr(mw, "ExportDoneDialog", lambda parent, path: type("D", (), {"present": lambda self: None})())
    window.export_excel()
    pump(app, lambda: not window.is_busy and target.exists())
    reference = tmp_path / "from_core.xlsx"
    generate_excel(scan_folder(folder, window.profiles["ICT_I3070 Test Log"]).grouped, ["R1", "R2"], reference, 2)

    def cells(path):
        book = load_workbook(path)
        try:
            return [[c.value for c in row] for row in book["Raw Data"].iter_rows()]
        finally:
            book.close()

    assert cells(target) == cells(reference) and len(cells(target)) > 6


def test_wrong_file_count_is_flagged_and_blocks_export(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder, sns=("VSE001", "VSE002"), repeats=2)
    write_ict_log(folder / "VSE003_1.log", "VSE003", [ict_block("R1", "+1.0E+00")])
    scan(app, window, folder)
    assert "VSE003" in window.verdict.text() and window.details_button.isEnabled()
    window.available_list.select_rows([0])
    window.add_components()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pytest.fail("must not reach the save dialog")))
    window.export_excel()
    assert any("exactly 2 files" in text for _kind, text in window.shown)


def test_empty_folder_explains_itself(app, window, tmp_path):
    (tmp_path / "empty").mkdir()
    scan(app, window, tmp_path / "empty")
    assert any("does not contain any files" in text for _kind, text in window.shown)
    assert window.samples_value.text() == "0 / 3"


def test_an_empty_scan_offers_the_profile_that_reads_the_folder(app, window, tmp_path):
    from ..test_sampling import EOL_ROWS, write_results_workbook

    folder = tmp_path / "eol"
    folder.mkdir()
    write_results_workbook(folder / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    window.profile_box.setCurrentText("ICT_I3070 Test Log")
    window.folder_edit.setText(str(folder))
    window.expected_edit.setText("1")
    window.repeats_edit.setText("1")
    window.scan_logs()  # reads nothing; the suggestion is accepted (the fixture answers Yes) and the scan runs again
    pump(app, lambda: window.profile_box.currentText() == "EOL Test Log" and not window.is_busy
         and window.scan_result is not None and bool(window.scan_result.grouped))
    assert window.scan_result.total_sns == 1 and "Init, Test SIM SN" in window.scan_result.components


def test_an_empty_scan_with_no_better_profile_just_explains(app, window, tmp_path):
    folder = tmp_path / "nothing"
    folder.mkdir()
    (folder / "notes.log").write_text("nothing to see", encoding="utf-8")
    scan(app, window, folder, expected=1, repeats=1)
    assert window.profile_box.currentText() == "ICT_I3070 Test Log" and not window.scan_result.grouped
    assert any(kind == "warning" for kind, _text in window.shown)


def test_selection_is_remembered_for_the_next_scan(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    window.available_list.select_rows([0, 1])
    window.add_components()
    remembered = list(window.selected_components)
    assert remembered
    window.reset_workflow()
    assert window.selected_components == []
    scan(app, window, folder)
    assert window.selected_components == remembered and "Restored" in window.status_label.text()


def test_reorder_and_remove(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    window.add_all_shown()
    assert window.selected_components == ["C1", "R1", "R2"]
    window.selected_list.select_rows([2])
    window.move_selected(-1)
    assert window.selected_components == ["C1", "R2", "R1"] and window.selected_list.selected_rows() == [1]
    window.move_selected(-1)
    window.move_selected(-1)  # already at the top: no-op, no crash
    assert window.selected_components == ["R2", "C1", "R1"]
    window.selected_list.select_rows([0, 1])
    window.remove_components()
    assert window.selected_components == ["R1"]
    window.clear_selected()
    assert window.selected_components == []


def test_the_buttons_at_the_end_of_a_row_add_and_remove_that_row(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    window._add_at(1)
    assert window.selected_components == ["R1"]
    window._add_at(0)
    window._remove_at(0)
    assert window.selected_components == ["C1"] and window.available_list.items() == ["R1", "R2"]
    window._remove_at(7)  # no such row: nothing happens
    assert window.selected_components == ["C1"]


def test_the_available_rows_show_min_and_max_and_a_dash_when_there_is_no_limit(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.0E+00", "+9.0E+00", "+0.0E+00"), ict_block("X1", "+1.0E+00")])
    scan(app, window, folder, expected=1, repeats=1)
    rows = window.available_list.table_model.rows
    assert rows[0][:3] == ("R1", "+0.0E+00", "+9.0E+00") and rows[1][1:3] == ("–", "–")


def test_filter_narrows_the_available_list_and_add_all_adds_only_what_is_shown(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    assert window.add_all_button.isEnabled() and not window.available_list.selected_items()
    window.search.setText("r")
    assert window.available_list.items() == ["R1", "R2"] and window.available_info.text() == "2 of 3 shown"
    window.add_all_shown()
    assert window.selected_components == ["R1", "R2"]
    window.search.setText("no-component-matches-this")
    assert window.available_list.items() == [] and not window.add_all_button.isEnabled()
    window.search.setText("")
    assert window.available_list.items() == ["C1"] and window.add_all_button.isEnabled()


def test_the_review_step_is_locked_until_there_is_something_to_review(app, window, tmp_path):
    bar = window.step_bar
    assert (bar.state(0), bar.state(1)) == ("current", "locked") and "Scan" in bar.caption(1)
    window._show_step("review")
    assert window.step == "select" and "Scan a folder" in window.status_label.text()
    bar.click(1)
    assert window.step == "select"
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    assert bar.state(1) == "locked" and not window.review_button.isEnabled()
    window.add_all_shown()
    assert bar.state(1) == "ready" and window.review_button.isEnabled()
    window.review_button.click()
    assert window.step == "review" and window.content.currentWidget() is window._pages["review"]
    assert (bar.state(0), bar.caption(0), bar.state(1)) == ("complete", "3 components selected", "current")
    window.back_button.click()
    assert window.step == "select" and (bar.state(0), bar.state(1)) == ("current", "ready")
    bar.click(1)
    assert window.step == "review"
    bar.click(0)
    assert window.step == "select"


def test_the_step_bar_shows_states_and_ignores_locked_steps(app):
    from datamapperx.palette import LIGHT
    from datamapperx.ui_qt.widgets import StepBar

    clicked = []
    bar = StepBar(("Select", "Review & Export"), LIGHT)
    bar.clicked.connect(clicked.append)
    bar.resize(800, 54)
    bar.set_step(0, "current", "Folder, profile & components")
    bar.set_step(1, "locked", "Scan first")
    assert (bar.state(0), bar.caption(0), bar.state(1), bar.caption(1)) == ("current", "Folder, profile & components", "locked", "Scan first")
    bar.click(1)
    assert clicked == []
    bar.set_step(1, "ready", "Go on")
    bar.click(1)
    bar.click(0)
    assert clicked == [1, 0]
    image = bar.grab().toImage()
    assert image.pixelColor(6, 27).name() == LIGHT.accent  # the current step is filled
    bar.set_step(0, "complete", "done")
    assert bar.grab().toImage().pixelColor(6, 27).name() == LIGHT.ok_bg
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(700, 27))  # a real click on the second step
    assert clicked == [1, 0, 1]


def test_check_chips_wrap_when_narrow_and_only_rebuild_on_change(app):
    from PySide6.QtWidgets import QLabel

    from datamapperx.ui_qt.widgets import ChipRow

    row = ChipRow()
    chips = [("ok", "✓  10 of 10 samples"), ("ok", "✓  3 files per sample"), ("warn", "!  20 empty cells in 2 columns"),
             ("info", "Outside min–max: rows 5, 13")]
    row.set_chips(chips)
    row.resize(2400, 100)
    row.show()
    app.processEvents()
    labels = row.findChildren(QLabel)
    assert len({label.y() for label in labels}) == 1
    row.resize(330, 100)
    app.processEvents()
    assert len({label.y() for label in row.findChildren(QLabel)}) >= 2 and row.chips() == chips
    row.set_chips(chips)  # unchanged: the same widgets stay
    assert row.findChildren(QLabel) == labels
    row.set_chips([("bad", "!  one")])
    assert row.chips() == [("bad", "!  one")]
    row.set_chips([])
    assert row.chips() == []


# ----------------------------------------------------------------------------- readiness and the busy state
def test_export_action_tracks_workflow_readiness(app, window, tmp_path):
    window._show_step("select")
    assert not window.review_button.isEnabled() and not window.export_button.isEnabled()
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    assert not window.export_button.isEnabled() and not window.review_button.isEnabled()
    window.available_list.select_rows([0])
    window.add_components()
    assert window.export_button.isEnabled() and window.review_button.isEnabled()
    window.clear_selected()
    assert not window.export_button.isEnabled() and not window.review_button.isEnabled()
    window.add_all_shown()
    assert window.export_button.isEnabled()
    window.reset_workflow()
    assert not window.export_button.isEnabled()


def test_a_busy_window_keeps_the_component_selection_and_the_step(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, window, folder)
    window.available_list.select_rows([0, 1])
    window.add_components()
    window.available_list.select_rows([0])
    window.selected_list.select_rows([0])
    selected, available, source = list(window.selected_components), window.available_list.items(), window.folder_edit.text()
    window._set_busy(True, cancellable=True)
    try:
        for button in (window.add_button, window.add_all_button, window.clear_button, window.move_up_button, window.move_down_button,
                       window.review_button, window.export_button, window.back_button):
            assert not button.isEnabled()
        assert window.cancel_button.isEnabled() and window.progress.isVisibleTo(window)
        for action in (window.add_components, window.add_all_shown, window.remove_components, lambda: window._add_at(0),
                       lambda: window._remove_at(0), window.clear_selected, lambda: window.move_selected(1), window.reset_workflow,
                       lambda: window._on_step_clicked(1)):
            action()
            assert window.selected_components == selected and window.available_list.items() == available
            assert window.folder_edit.text() == source and window.step == "select"
    finally:
        window._set_busy(False)
    assert window.export_button.isEnabled() and not window.cancel_button.isEnabled()


def test_ctrl_e_goes_to_the_review_first_and_exports_from_there(app, window, tmp_path, monkeypatch):
    ready_to_review(app, window, tmp_path / "logs")
    exported = []
    monkeypatch.setattr(window, "export_excel", lambda: exported.append(True))
    window._export_shortcut()
    assert window.step == "review" and exported == []
    window._export_shortcut()
    assert exported == [True]
    window._set_busy(True)
    try:
        window._export_shortcut()
        assert exported == [True]  # nothing while a task runs
    finally:
        window._set_busy(False)


def test_a_new_scan_or_a_reset_returns_to_the_first_step(app, window, tmp_path):
    folder = tmp_path / "logs"
    ready_to_review(app, window, folder)
    window._show_step("review")
    scan(app, window, folder)
    assert window.step == "select" and window.content.currentWidget() is window._pages["select"]
    window._show_step("review")
    assert window.step == "review"
    window.reset_workflow()
    assert window.step == "select" and window.step_bar.state(1) == "locked" and window.preview_grid.rows() == []


def test_the_workspace_switch_and_the_shortcuts_that_bring_data_mapping_back(app, window, tmp_path):
    ready_to_review(app, window, tmp_path / "logs")
    window._show_workspace("validation")
    assert window.workspace == "validation" and window.validation is not None and not window.step_bar.isVisibleTo(window)
    assert window.validation_switch.property("primary") is True and window.mapping_switch.property("primary") is False
    window._in_mapping(lambda: None)
    assert window.workspace == "mapping" and window.step_bar.isVisibleTo(window)
    window._show_workspace("validation")
    window._show_step("review")  # asking for a step brings Data Mapping back as well
    assert window.workspace == "mapping" and window.step == "review"


def test_the_theme_switch_keeps_the_preview_and_the_export_order(app, window, tmp_path):
    ready_to_review(app, window, tmp_path / "logs")
    window.selected_list.select_rows([2])
    window.move_selected(-1)
    window._show_step("review")
    selected, preview, limits = list(window.selected_components), window.preview_grid.rows(), window.limits_grid.rows()
    for _ in range(2):
        window._toggle_theme()
        app.processEvents()
        assert window.selected_components == selected and window.selected_list.items() == selected
        assert window.preview_grid.rows() == preview and window.limits_grid.rows() == limits
        assert window.export_button.isEnabled() and window.step == "review"
        for table in (window.available_list, window.preview_grid, window.limits_grid, window.grr_grid):
            assert table.palette_tokens is window.palette_tokens


# ----------------------------------------------------------------------------- the review
def limit_logs(folder):
    """VSE001..3 x 2 files, limits 0..9. R1 is too high in VSE001_1 and too low in VSE003_2; R2 is missing in VSE002_1."""
    for sn in ("VSE001", "VSE002", "VSE003"):
        for run in (1, 2):
            r1 = {("VSE001", 1): "+12.0E+00", ("VSE003", 2): "-1.0E+00"}.get((sn, run), "+5.0E+00")
            blocks = [ict_block("R1", r1, "+9.0E+00", "+0.0E+00")]
            if (sn, run) != ("VSE002", 1):
                blocks.append(ict_block("R2", "+3.0E+00", "+9.0E+00", "+0.0E+00"))
            write_ict_log(folder / f"{sn}_{run}.log", sn, blocks)


def limits_rows(window):
    grid = window.limits_grid
    return list(zip(grid.rows(), grid.tags(), strict=True))


def test_the_review_compares_the_clicked_row_with_the_limits(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    scan(app, window, folder)
    window.add_all_shown()
    window._show_step("review")
    unit = window.limits["R1"]["unit"]
    assert window.limits_title.text() == "Limits (2)"
    assert window.review_row_label.text() == "Row 1   ·   VSE001   ·   VSE001_1.log"
    first = limits_rows(window)
    assert first[0] == (("R1", "+12.0E+00 ▲", "+0.0E+00", "+9.0E+00", unit), "out")
    assert first[1][0][:2] == ("R2", "+3.0E+00") and first[1][1] == ""

    window.preview_grid.select_row(2)  # VSE002_1: R2 is missing
    assert window._review_row == 2
    row = limits_rows(window)
    assert row[0][0][1] == "+5.0E+00" and row[0][1] == "" and row[1][0][1] == "–" and row[1][1] == "gap"
    assert window.review_row_label.text() == "Row 3   ·   VSE002   ·   VSE002_1.log"
    assert window.side_tabs.currentWidget() is window.limits_page  # choosing a row shows its limits

    window.preview_grid.select_row(5)  # VSE003_2: R1 below its minimum
    assert limits_rows(window)[0][0][1] == "-1.0E+00 ▼" and limits_rows(window)[0][1] == "out"
    assert ("info", "Outside min–max: rows 1, 6") in window.check_chips.chips()
    window._show_step("select")
    window._show_step("review")  # coming back keeps the row you were looking at
    assert window._review_row == 5 and window.preview_grid.selected_index() == 5


def test_the_tables_tint_rows_with_missing_values_and_wrong_file_counts(app, window, tmp_path):
    from datamapperx.ui_qt.models import TableModel

    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    write_ict_log(folder / "VSE004_1.log", "VSE004", [ict_block("R1", "+1.0E+00", "+9.0E+00", "+0.0E+00"), ict_block("R2", "+1.0E+00")])
    scan(app, window, folder, expected=4)
    window.add_all_shown()
    window._show_step("review")
    grid = window.preview_grid
    assert grid.tags() == ["", "", "missing", "", "", "", "invalid"]
    model: TableModel = grid.table_model
    assert model.data(model.index(2, 3), Qt.ItemDataRole.BackgroundRole).name() == window.palette_tokens.warn_bg
    assert model.data(model.index(6, 3), Qt.ItemDataRole.BackgroundRole).name() == window.palette_tokens.bad_bg
    window._toggle_theme()  # recoloured with the theme
    assert model.data(model.index(6, 3), Qt.ItemDataRole.BackgroundRole).name() == window.palette_tokens.bad_bg == "#40191c"


def test_the_checks_beside_the_export_button_summarise_the_data(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    scan(app, window, folder, expected=4)  # one sample short
    window.add_all_shown()
    window._show_step("review")
    assert window.check_chips.chips() == [
        ("warn", "!  3 of 4 samples. You will be asked to confirm"), ("ok", "✓  2 files per sample"),
        ("warn", "!  1 empty cell in 1 column"), ("info", "Outside min–max: rows 1, 6"),
    ]
    assert window.export_button.isEnabled()
    window.expected_edit.setText("3")
    window._refresh_checks()
    assert window.check_chips.chips()[0] == ("ok", "✓  3 of 3 samples")
    window.clear_selected()
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.check_chips.chips() == []  # nothing selected, nothing to check


def test_export_is_blocked_on_the_review_while_a_sample_has_the_wrong_number_of_files(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder, sns=("VSE001", "VSE002"), repeats=2)
    write_ict_log(folder / "VSE003_1.log", "VSE003", [ict_block("R1", "+1.0E+00")])
    scan(app, window, folder, expected=3)
    window.add_all_shown()
    assert window.step_bar.state(1) == "warn" and "Fix" in window.step_bar.caption(1)
    window._show_step("review")
    assert ("bad", "!  VSE003 has 1 files, not 2. Export is blocked") in window.check_chips.chips()
    assert not window.export_button.isEnabled() and window.step_bar.state(1) == "current"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pytest.fail("blocked")))
    window.export_excel()  # still refuses if called some other way
    assert any("exactly 2 files" in text for _kind, text in window.shown)


def make_wide_logs(folder, count=45):
    names = [f"comp_{i:02d}" for i in range(count)]
    for sn, how_many in (("VSE001", count), ("VSE002", count - 1)):  # the last component is missing in the second file
        blocks = [ict_block(name, f"+{i}.5E+00", "+99E+00", "+0.0E+00") for i, name in enumerate(names[:how_many])]
        write_ict_log(folder / f"{sn}_1.log", sn, blocks)
    return names


def test_the_preview_shows_one_page_of_columns_and_the_export_keeps_all_of_them(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, window, folder, expected=2, repeats=1)
    window.add_all_shown()
    window._show_step("review")
    grid = window.preview_grid
    assert len(grid.rows()) == 2 and window.selected_components == names and len(grid.headings()) == 3 + PAGE
    assert window.pager_label.text() == "Columns 1–20 of 45" and window.pager_label.isVisibleTo(window)
    assert not window.pager_prev.isEnabled() and window.pager_next.isEnabled()
    assert grid.headings()[3] == "comp_00" and grid.headings()[-1] == "comp_19"
    assert "all 45 columns" in window.preview_info.text()  # the missing value is on the last page, still counted
    assert ("warn", "!  1 empty cell in 1 column") in window.check_chips.chips()

    window._page_preview(1)
    pump(app, lambda: window.pager_label.text() == "Columns 21–40 of 45" and not window._preview_timer.isActive())
    assert grid.headings()[3] == "comp_20" and grid.rows()[0][3:5] == ("+20.5E+00", "+21.5E+00")
    window._page_preview(1)
    pump(app, lambda: window.pager_label.text() == "Columns 41–45 of 45" and not window._preview_timer.isActive())
    assert len(grid.headings()) == 3 + 5 and not window.pager_next.isEnabled() and grid.rows()[1][7:8] == ("",)
    window._page_preview(1)  # past the end stays on the last page
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.pager_label.text() == "Columns 41–45 of 45"

    out = tmp_path / "wide.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    opened = []
    monkeypatch.setattr(mw, "ExportDoneDialog", lambda parent, path: type("D", (), {"present": lambda self: opened.append(path)})())
    window.export_excel()
    pump(app, lambda: not window.is_busy and opened)
    assert [c.value for c in load_workbook(out)["Raw Data"][1]][: 2 + 45] == ["STT", "SN", *names]  # every column

    window.clear_selected()
    pump(app, lambda: not window._preview_timer.isActive())
    assert not window.pager_label.isVisibleTo(window) and len(grid.headings()) == 3


def test_the_chosen_row_survives_paging_and_the_limits_cover_every_column(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, window, folder, expected=2, repeats=1)
    window.add_all_shown()
    window._show_step("review")
    window.preview_grid.select_row(1)
    assert window._review_row == 1 and window.limits_title.text() == "Limits (45)" and len(window.limits_grid.rows()) == 45
    window._page_preview(1)
    pump(app, lambda: window.pager_label.text() == "Columns 21–40 of 45" and not window._preview_timer.isActive())
    assert window._review_row == 1 and window.preview_grid.selected_index() == 1
    limits = window.limits_grid.rows()
    assert len(limits) == 45 and limits[44][1] == "–" and limits[0][0] == names[0]  # comp_44 is blank in the second file


def test_the_page_resets_for_a_new_scan_and_when_the_selection_shrinks(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, window, folder, expected=2, repeats=1)
    window.add_all_shown()
    window._show_step("review")
    window._page_preview(2)
    pump(app, lambda: window.pager_label.text() == "Columns 41–45 of 45" and not window._preview_timer.isActive())
    window.selected_components = names[:25]  # fewer columns: the page that no longer exists falls back to the last one
    window._refresh_preview()
    assert window.pager_label.text() == "Columns 21–25 of 25"
    window.selected_components = names[:5]
    window._refresh_preview()
    assert window._preview_page == 0 and not window.pager_label.isVisibleTo(window)
    window.selected_components = list(names)
    window._preview_page = 2
    scan(app, window, folder, expected=2, repeats=1)
    assert window._preview_page == 0


def test_the_limit_columns_are_wide_enough_for_the_numbers(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.2345678E+03", "+9.876543E+12", "-1.234567E-03")])
    scan(app, window, folder, expected=1, repeats=1)
    window.add_all_shown()
    window._show_step("review")
    grid = window.limits_grid
    grid.resize(420, 200)
    metrics = grid.fontMetrics()
    width = dict(zip(grid.headings(), (grid.columnWidth(c) for c in range(len(grid.headings()))), strict=True))
    assert window.limits["R1"]["max"] == "+9.876543E+12" and window.limits["R1"]["min"] == "-1.234567E-03"
    assert width["Min"] >= metrics.horizontalAdvance("-1.234567E-03") and width["Max"] >= metrics.horizontalAdvance("+9.876543E+12")
    assert width["Value"] >= metrics.horizontalAdvance("+1.2345678E+03")


# ----------------------------------------------------------------------------- the GRR pre-check
def grr_logs(folder):
    for part in range(3):
        for repeat in range(3):
            value = f"+{3 * part + repeat + 1}.0E+00"
            sn = f"VSE{part:03d}"
            write_ict_log(folder / f"{sn}_{repeat}.log", sn, [ict_block("X", value, "+2.0E+01", "+0.0E+00"),
                                                            ict_block("Y", value, "+1.0E+02", "+0.0E+00")])


def test_grr_precheck_shows_independent_statuses_and_colors_before_export(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    window.add_all_shown()
    window._show_step("review")
    assert window.side_tabs.currentWidget() is window.grr_page
    assert window.grr_grid.rows() == [("X", "32.16", "30.00", "4", "FAIL"), ("Y", "32.16", "6.00", "4", "FAIL")]
    assert window.grr_grid.cell_tags() == {  # %SV/Tol is shown but does not decide, nor is it coloured, by default
        (0, 1): "fail", (0, 2): "neutral", (0, 3): "fail", (0, 4): "fail",
        (1, 1): "fail", (1, 2): "neutral", (1, 3): "fail", (1, 4): "fail"}
    assert window.grr_summary.text() == "2 test items · not applied: %SV/Tol"
    defaults = window.grr_criteria
    window._set_grr_criteria(tuple(replace(c, enabled=True) for c in defaults))
    assert window.grr_grid.cell_tags() == {
        (0, 1): "fail", (0, 2): "caution", (0, 3): "fail", (0, 4): "fail",
        (1, 1): "fail", (1, 2): "pass", (1, 3): "fail", (1, 4): "fail"}
    assert window.grr_summary.text() == "2 test items" and "Study Var (6 × SD): 6.00" in window.grr_detail.text()
    assert load_settings().quick_check_criteria  # remembered for the next start
    window.preview_grid.select_row(1)
    assert window.side_tabs.currentWidget() is window.limits_page


def test_grr_precheck_recalculates_after_duplicate_choices_counts_and_reset(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    window.add_all_shown()
    window._show_step("review")
    first = window.scan_result.grouped["VSE000"][0]
    first.entries["X"] = replace(first.entries["X"], measured="PASS")
    window._on_duplicates_reviewed({"X"}, True)
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.grr_grid.rows()[0] == ("X", "N/A", "N/A", "N/A", "N/A")  # nothing to judge: N/A, not a pass
    assert first.filename in window.grr_detail.text()
    assert window._grr_results[1].percent_tolerance == pytest.approx(6)
    window.repeats_edit.setText("4")
    pump(app, lambda: not window._preview_timer.isActive())
    assert all(row[1:] == ("N/A", "N/A", "N/A", "N/A") for row in window.grr_grid.rows())
    assert "needs 4 repeated files" in window.grr_detail.text()
    window.reset_workflow()
    assert window.grr_grid.rows() == [] and window.grr_summary.text() == ""


def test_grr_precheck_ndc_colors(app, window, tmp_path):
    folder = tmp_path / "ndc_logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    for part, records in enumerate(window.scan_result.grouped.values()):
        for record in records:
            entry = record.entries["Y"]
            record.entries["Y"] = replace(entry, measured=str(float(entry.measured) + part * 100))
    window.add_all_shown()
    window._show_step("review")
    assert window.grr_grid.headings() == ["Test", "%Study Var", "%SV/Tol", "NDC", "Result"]
    assert window._grr_results[0].ndc < 5 <= window._grr_results[1].ndc
    assert window.grr_grid.cell_tags()[0, 3] == "fail" and window.grr_grid.cell_tags()[1, 3] == "pass"


def test_the_quick_check_criteria_are_set_in_a_dialog_and_applied_at_once(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    window.add_all_shown()
    window._show_step("review")
    window.grr_criteria_button.click()
    dialog = next(d for d in window.findChildren(GrrCriteriaDialog))
    enabled, low, high = dialog.fields["percent_tolerance"]
    assert not enabled.isChecked()
    enabled.setChecked(True)
    low.setText("5")
    high.setText("40")
    dialog.apply()
    assert window.grr_grid.cell_tags()[1, 2] == "caution"  # 6 % is between 5 and 40
    bad = window.findChildren(GrrCriteriaDialog)
    for each in bad:
        each.close()
    window.grr_criteria_button.click()
    dialog = window.findChildren(GrrCriteriaDialog)[-1]
    dialog.fields["percent_tolerance"][1].setText("abc")
    dialog.apply()
    assert "enter numbers" in dialog.error.text() and window.grr_grid.cell_tags()[1, 2] == "caution"  # nothing changed
    dialog.reset()
    assert dialog.fields["percent_tolerance"][1].text() == "10" or dialog.error.text() == ""


# ----------------------------------------------------------------------------- duplicates
def duplicate_logs(folder):
    for run in (1, 2):
        write_ict_log(folder / f"VSE001_{run}.log", "VSE001", [ict_block("R1", "+1.0E+00"), ict_block("R1", "+7.0E+00")])


def test_duplicate_components_are_reviewed_once(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    duplicate_logs(folder)
    dialog = fake_dialog()
    monkeypatch.setattr(mw, "DuplicateDialog", dialog)
    scan(app, window, folder, expected=1)
    window.add_all_shown()
    assert len(dialog.made) == 1 and len(dialog.made[0][0][1]) == 2
    dialog.made[0][0][2]({"R1"}, True)  # the user closes the dialog
    window.clear_selected()
    window.add_all_shown()
    assert len(dialog.made) == 1  # already reviewed, so not asked again


def test_the_duplicate_dialog_applies_the_chosen_occurrence_and_keeps_defaults_on_close(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    duplicate_logs(folder)
    scan(app, window, folder, expected=1, repeats=1)
    window.add_all_shown()  # opens the real dialog
    dialog = window.findChildren(DuplicateDialog)[-1]
    dialog.combos[0].setCurrentIndex(1)
    dialog.apply()
    assert window.scan_result.grouped["VSE001"][0].entries["R1"].measured == "+7.0E+00"
    assert window.reviewed_duplicates == {"R1"} and "applied" in window.status_label.text()

    done = []
    other = DuplicateDialog(window, window.scan_result.duplicate_groups, lambda reviewed, applied: done.append((reviewed, applied)))
    other.present()
    other.close()
    assert done == [({"R1"}, False)]  # closing without applying keeps the defaults, and says so once


def test_a_data_change_reaches_the_validation_page_when_it_is_open(app, window, tmp_path):
    ready_to_review(app, window, tmp_path / "logs")
    window._show_workspace("validation")
    source = window.validation._source
    assert source is not None and source.components == tuple(window.selected_components)
    window._show_workspace("mapping")
    window.clear_selected()
    assert window.validation._source is None


# ----------------------------------------------------------------------------- dialogs
def test_every_dialog_opens_and_closes(app, window, tmp_path):
    from datamapperx.ui_qt.profile_dialog import ProfileManager

    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.0E+00"), ict_block("R1", "+7.0E+00")])
    scan(app, window, folder, expected=1, repeats=1)
    info = updater.parse_manifest({"version": "9.0.0", "sha256": "0" * 64, "notes": "- new things"})
    results = []
    dialogs = [AboutDialog(window), ReportDialog(window, "t", "h", "body"), ExportDoneDialog(window, tmp_path / "x.xlsx"),
               DuplicateDialog(window, window.scan_result.duplicate_groups, lambda reviewed, applied: results.append(applied)),
               UpdateDialog(window, info, mandatory=False), ProfileManager(window, window.profiles, lambda name: None),
               GrrCriteriaDialog(window, window.grr_criteria, lambda criteria: None)]
    for dialog in dialogs:
        dialog.present()
    app.processEvents()
    assert all(d.isVisible() for d in dialogs)
    for dialog in dialogs:
        dialog.close()
    app.processEvents()
    assert results == [False]


def test_the_help_menu_dialogs(app, window):
    window._show_shortcuts()
    window._show_about()
    texts = [d.windowTitle() for d in window.findChildren(ReportDialog)] + [d.windowTitle() for d in window.findChildren(AboutDialog)]
    assert "Keyboard shortcuts" in texts and f"About {mw.APP_TITLE}" in texts
    shortcuts = window.findChildren(ReportDialog)[-1].text.toPlainText()
    assert "Ctrl+E" in shortcuts and "Esc" in shortcuts


def test_release_notes_render_headings_and_bullets(app, window):
    from datamapperx.ui_qt.widgets import ReadOnlyText

    box = ReadOnlyText()
    box.set_markdown("### New\n- **Faster** scan of `OneDrive` folders\nplain line")
    assert box.toPlainText().strip().splitlines() == ["New", "•  Faster scan of OneDrive folders", "plain line"]
    first, bullet = box.document().firstBlock(), box.document().firstBlock().next()
    assert first.begin().fragment().charFormat().fontWeight() > 500 and bullet.blockFormat().leftMargin() > 0


# ----------------------------------------------------------------------------- the update flow
def newer_info(**extra):
    return updater.parse_manifest({"version": "99.0.0", "sha256": "a" * 64, **extra})


def test_update_banner_shows_and_skip_is_remembered(app, window):
    window._on_update_checked(newer_info(), manual=False)
    assert window.banner.isVisibleTo(window)
    window.skip_update("99.0.0")
    assert not window.banner.isVisibleTo(window) and window.settings.skipped_version == "99.0.0"
    window._on_update_checked(newer_info(), manual=False)  # the same version again: stays quiet
    assert not window.banner.isVisibleTo(window)


def test_no_update_is_silent_unless_asked(app, window):
    window._on_update_checked(None, manual=False)
    assert window.shown == []
    window._on_update_checked(None, manual=True)
    assert any(__version__ in text for _k, text in window.shown)


def test_a_mandatory_update_opens_a_blocking_dialog(app, window, monkeypatch):
    dialog = fake_dialog()
    monkeypatch.setattr("datamapperx.ui_qt.update_dialog.UpdateDialog", dialog)
    window._on_update_checked(newer_info(min_supported="99.0.0"), manual=False)
    assert [kwargs for _args, kwargs in dialog.made] == [{"mandatory": True}]


def test_a_failed_update_check_is_silent_at_startup(app, window):
    window._on_update_check_failed(updater.UpdateError("offline"), manual=False)
    assert window.shown == []


def test_turning_the_notice_off_hides_the_banner_but_not_a_required_update(app, window, monkeypatch):
    window.settings.check_updates = False
    window._on_update_checked(newer_info(), manual=False)
    assert not window.banner.isVisibleTo(window)
    dialog = fake_dialog()
    monkeypatch.setattr("datamapperx.ui_qt.update_dialog.UpdateDialog", dialog)
    window._on_update_checked(newer_info(min_supported="99.0.0"), manual=False)
    assert len(dialog.made) == 1
    window.auto_update_action.setChecked(False)
    window.auto_update_action.setChecked(True)
    assert window.settings.check_updates is True


def test_the_update_dialog_shows_notes_and_a_mandatory_one_can_only_update_or_exit(app, window, monkeypatch):
    exited = []
    monkeypatch.setattr(window, "exit_app", lambda: exited.append(True))
    dialog = UpdateDialog(window, newer_info(notes="### New\n- better"), mandatory=True)
    dialog.present()
    assert "better" in dialog.notes.toPlainText() and not hasattr(dialog, "later_button")
    dialog.close()  # the X button and Esc both end here
    assert exited == [True]
    optional = UpdateDialog(window, newer_info(), mandatory=False)
    optional.skip_button.click()
    assert window.settings.skipped_version == "99.0.0"


# ----------------------------------------------------------------------------- the owner's off switch
DAY = 24 * 60 * 60


def answer_status(monkeypatch, outcome):
    """Make the status check return ``outcome`` (a Status), or fail with it (an exception)."""

    def fetch(timeout=8.0):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(updater, "fetch_status", fetch)


def check_access(app, window, then=None):
    """Run the background check and wait until its answer has been handled."""
    window.verify_access(then=then)
    pump(app, lambda: not window.tasks.busy)
    app.processEvents()


def test_a_switched_off_copy_shows_the_owners_message_and_runs_nothing_else(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Version 1.2 has a bug. Ask Man for 1.3."))
    followed = []
    check_access(app, window, then=lambda: followed.append("update check"))
    dialog = window.access_dialog
    assert isinstance(dialog, AccessDialog) and dialog.isVisible()
    assert "switched off" in dialog.heading.text() and "Ask Man for 1.3" in dialog.message.text()
    assert followed == [] and window.settings.deactivated  # no update is offered to a copy that may not run


def test_the_off_switch_dialog_can_only_check_again_or_exit(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app, window)
    dialog = window.access_dialog
    left = []
    monkeypatch.setattr(window, "exit_app", lambda: left.append(True))
    dialog.close()  # the window's X button and Esc both end up here
    assert left == [True] and window.access_dialog is None
    check_access(app, window)  # asked again: back on screen
    dialog = window.access_dialog
    dialog.exit_button.click()
    assert left == [True, True]


def test_check_again_lets_the_copy_run_once_the_owner_switches_it_back_on(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app, window)
    dialog = window.access_dialog
    assert dialog.isVisible()
    answer_status(monkeypatch, updater.Status(False, ""))
    dialog.check_button.click()
    pump(app, lambda: window.access_dialog is None)
    app.processEvents()
    assert not isValid(dialog) and not window.settings.deactivated  # the dialog went away with the answer


def test_a_switched_off_copy_stays_off_when_it_cannot_reach_github(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app, window)
    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    followed = []
    check_access(app, window, then=lambda: followed.append(True))
    dialog = window.access_dialog
    assert dialog.isVisible() and "switched off" in dialog.heading.text()
    assert "no route" in dialog.detail.text() and followed == []


def test_no_answer_is_tolerated_inside_the_grace_period(app, window, monkeypatch):
    window.settings.verified_at = time.time() - 3 * DAY
    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    followed = []
    check_access(app, window, then=lambda: followed.append(True))
    assert window.access_dialog is None and followed == [True] and not window.settings.deactivated


def test_no_answer_for_too_long_asks_for_a_connection(app, window, monkeypatch):
    window.settings.verified_at = time.time() - (access.OFFLINE_GRACE_DAYS + 2) * DAY
    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    check_access(app, window)
    dialog = window.access_dialog
    assert dialog is not None and dialog.isVisible() and "could not be checked" in dialog.heading.text()
    answer_status(monkeypatch, updater.Status(False, ""))  # back on the network
    dialog.check_button.click()
    pump(app, lambda: window.access_dialog is None)
    assert abs(window.settings.verified_at - time.time()) < 60


def test_a_good_answer_is_saved_so_the_next_start_is_blocked_before_any_network(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app, window)
    saved = load_settings()
    assert saved.deactivated and saved.deactivated_message == "Stopped"


def test_a_clear_answer_does_nothing_visible_when_all_is_well(app, window, monkeypatch):
    answer_status(monkeypatch, updater.Status(False, ""))
    followed = []
    check_access(app, window, then=lambda: followed.append(True))
    assert window.access_dialog is None and followed == [True] and window.shown == []


def test_the_window_stays_off_the_network_when_asked(app, window):
    assert window._enforce_access is False  # the fixture built it with background_checks=False


def test_a_task_that_ends_after_the_window_closed_is_dropped(app, window):
    seen = []
    window.tasks.run(lambda report: time.sleep(0.05), on_success=lambda r: seen.append("late"), on_error=seen.append)
    window.close()  # waits for the worker and drops its callbacks
    app.processEvents()
    assert seen == [] and not window.tasks.busy
