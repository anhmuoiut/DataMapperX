"""The Dashboard the program opens on (UX V6) and how it leads into the two workflows that already existed.

Map Test Logfiles is Data Mapping as it was; Analyze by Excel File opens its dialog (tests/ui/test_excel_analysis.py), and the RawData.xlsx
import it used to start straight away is Validation & Reports with the file imported and its Analysis tab shown. Nothing here changes
a figure: these tests only follow where the user is taken and what is kept.
"""
from __future__ import annotations

import copy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLabel, QPushButton

from datamapperx.ui import dashboard as dashboard_module
from datamapperx.ui.dashboard import INTRO, MAP_CARD, RAW_CARD, TITLE, StartCard

from .support import pump, ready_to_review
from .test_widgets import overlapping, squeezed


def click(widget) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(widget.width() // 2, widget.height() // 2))


@pytest.fixture
def rawdata(tmp_path):
    """RawData workbooks made from synthetic logs (``good``: 3 samples, 2 readings each, 2 test items; ``other``: the first item only)
    and a workbook that is not one (``wrong``)."""
    from types import SimpleNamespace

    from openpyxl import Workbook

    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder

    from ..baseline_support import write_rawdata_logs

    logs = tmp_path / "raw_logs"
    logs.mkdir()
    write_rawdata_logs(logs)
    result = scan_folder(logs, copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"]))
    good = tmp_path / "RawData.xlsx"
    generate_excel(result.grouped, ["R1", "Long"], good, expected_repeated=2)
    other = tmp_path / "RawData_other.xlsx"
    generate_excel(result.grouped, ["R1"], other, expected_repeated=2)
    wrong = tmp_path / "wrong.xlsx"
    book = Workbook()
    book.active.append(["Name", "Value"])
    book.save(wrong)
    return SimpleNamespace(good=good, other=other, wrong=wrong)


class FileDialog:
    """Stands in for the operating system's file dialog (a real one would wait for a person): ``append(path)`` is what the user
    picks next ("" cancels; with nothing appended it cancels), and ``asked`` has one entry for every time the program asked."""

    def __init__(self) -> None:
        self.picks: list[str] = []
        self.asked: list[int] = []

    def append(self, path: str) -> None:
        self.picks.append(path)

    def __call__(self, *_args, **_kwargs) -> tuple[str, str]:
        self.asked.append(1)
        return (self.picks[-1] if self.picks else "", "")


@pytest.fixture
def chosen_file(monkeypatch):
    dialog = FileDialog()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(dialog))
    return dialog


def imported(app, window) -> None:
    ws = window.validation
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.source_var.get() == "file")


# ----------------------------------------------------------------------------- the page
def test_the_program_opens_on_the_dashboard_and_offers_exactly_two_ways_in(app, window):
    assert window.workspace == "dashboard" and window.content.currentWidget() is window.dashboard
    assert window.nav_bar.isHidden() and window.theme_button.isVisible() and window.help_button.isVisible()  # the header stays
    cards = window.dashboard.findChildren(StartCard)
    assert [card.title.text() for card in cards] == [MAP_CARD[0], RAW_CARD[0]]  # the copy is the module's own: the test pins the structure
    assert all(card.isVisible() and card.focusPolicy() == Qt.FocusPolicy.TabFocus for card in cards)
    assert [card.accessibleName() for card in cards] == [MAP_CARD[0], RAW_CARD[0]]
    assert not window.dashboard.findChildren(QPushButton)  # no login, audit or other controls: the cards are the page
    assert INTRO in window.dashboard.intro.text() and window.dashboard.heading.text() == TITLE
    assert window.status_label.text() == "Choose a starting point."
    assert window.scan_result is None and not window.selected_components and (window.validation is None or window.validation.dataset is None)


def test_the_dashboard_follows_the_theme(app, window):
    window._toggle_theme()
    assert window.palette_tokens.mode == "dark"
    assert window.dashboard.hero.palette_tokens is window.palette_tokens and window.dashboard.map_card.icon.palette_tokens is window.palette_tokens
    window._toggle_theme()
    assert window.palette_tokens.mode == "light" and window.dashboard.raw_card.palette_tokens is window.palette_tokens


def test_a_card_answers_the_keyboard_and_a_mouse_release_outside_it_does_nothing(app, window, monkeypatch):
    from datamapperx.ui.excel_analysis_dialog import ExcelAnalysisDialog

    opened = []  # the Analyze card opens its dialog (a real one is modal): count the openings
    monkeypatch.setattr(ExcelAnalysisDialog, "present", lambda self: opened.append(self))
    QTest.keyClick(window.dashboard.raw_card, Qt.Key.Key_Space)
    QTest.keyClick(window.dashboard.raw_card, Qt.Key.Key_Return)
    QTest.keyClick(window.dashboard.raw_card, Qt.Key.Key_A)  # any other key is not a click
    assert len(opened) == 2
    card = window.dashboard.raw_card
    QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(-40, -40))  # dragged off before letting go
    assert len(opened) == 2 and window.workspace == "dashboard"


def test_the_analyze_card_opens_the_excel_dialog_and_asks_for_no_file_yet(app, window, chosen_file):
    from datamapperx.ui.excel_analysis_dialog import ExcelAnalysisDialog

    card = window.dashboard.raw_card
    assert card.accessibleDescription() == RAW_CARD[1] and card.action.text() == RAW_CARD[2]
    click(card)
    dialog = window.findChildren(ExcelAnalysisDialog)[-1]
    assert dialog.isVisible() and dialog.windowTitle() == "Analyze by Excel File"
    assert chosen_file.asked == [] and window.workspace == "dashboard"  # nothing is read, and the person is still on the Dashboard
    dialog.close()


def test_the_dashboard_fits_an_ordinary_window_and_scrolls_instead_of_overlapping_in_a_short_one(app, window):
    window.resize(1360, 1000)  # roomy: the offscreen platform's fonts are wider than Windows', so it gets some margin
    QTest.qWait(150)
    bar = window.dashboard.scroll_area.verticalScrollBar()
    assert bar.maximum() == 0 and not overlapping(window.dashboard.content) and not squeezed(window.dashboard)
    assert window.dashboard._compact is False  # the spacing of the design
    window.setMinimumSize(0, 0)
    window.resize(1360, 380)
    QTest.qWait(150)
    assert window.dashboard._compact is True and bar.maximum() > 0 and not overlapping(window.dashboard.content)  # tighter, then scrolls
    window.resize(1360, 1000)
    QTest.qWait(150)
    assert window.dashboard._compact is False and bar.maximum() == 0  # and back


def test_a_wrapping_label_with_a_limit_is_measured_at_the_width_it_will_have(app):
    text = "word " * 80
    limited = dashboard_module._Measure(text, "intro", 300)
    plain = QLabel(text)
    plain.setWordWrap(True)
    # asked for 900 pixels, the limited label answers for its own 300: a plain one would answer for 900 and cut the text off
    assert limited.heightForWidth(900) == limited.heightForWidth(300) > plain.heightForWidth(900)
    limited.deleteLater()
    plain.deleteLater()


# ----------------------------------------------------------------------------- Map Test Logfiles
def test_map_test_logfiles_opens_data_mapping_as_it_was(app, window):
    click(window.dashboard.map_card)
    assert window.workspace == "mapping" and window.step == "select" and window.content.currentWidget() is window._pages["select"]
    assert window.nav_bar.isVisible() and window.step_bar.isVisible() and window.home_button.isVisible()
    assert window.mapping_switch.property("primary") is True and window.validation_switch.property("primary") is False
    assert "choose a profile and a folder" in window.status_label.text().lower()


def test_mapping_review_and_analysis_still_work_after_starting_from_the_dashboard(app, window, tmp_path):
    click(window.dashboard.map_card)
    ready_to_review(app, window, tmp_path / "logs")
    assert len(window.selected_components) == 3
    window.review_button.click()
    pump(app, lambda: window.step == "review" and not window.is_busy)
    assert window.export_button.isEnabled() and window.validate_button.isEnabled()
    window.validate_button.click()
    ws = window.validation
    pump(app, lambda: window.workspace == "validation" and ws.dataset is not None and not ws.busy)
    assert ws.source_var.get() == "mapping" and ws.tabs.currentWidget() is ws.setup_tab  # the Analysis tab opens, nothing has run
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    assert len(ws.results) == 3


# ----------------------------------------------------------------------------- the way back
def test_the_dashboard_button_leads_back_from_both_workflows_and_nothing_is_lost(app, window, tmp_path):
    click(window.dashboard.map_card)
    ready_to_review(app, window, tmp_path / "logs")
    window.review_button.click()
    pump(app, lambda: window.step == "review" and not window.is_busy)
    scan_result, selected = window.scan_result, list(window.selected_components)
    window.validate_button.click()
    ws = window.validation
    pump(app, lambda: window.workspace == "validation" and ws.dataset is not None and not ws.busy)
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    dataset, result_set = ws.dataset, ws.result_set

    assert window.home_button.isVisible()  # in Validation & Reports
    click(window.home_button)
    assert window.workspace == "dashboard" and window.content.currentWidget() is window.dashboard and window.nav_bar.isHidden()
    assert window.scan_result is scan_result and window.selected_components == selected
    assert ws.dataset is dataset and ws.result_set is result_set and not ws.stale

    click(window.dashboard.map_card)  # back into Data Mapping: the Review step it was left on, with the same scan and choice
    assert window.workspace == "mapping" and window.step == "review" and window.content.currentWidget() is window._pages["review"]
    assert window.scan_result is scan_result and window.selected_components == selected and window.export_button.isEnabled()
    click(window.home_button)  # and from Data Mapping too
    assert window.workspace == "dashboard"
    window._show_workspace("validation")
    assert window.workspace == "validation" and ws.result_set is result_set and not ws.stale  # still there to look at and report


def test_the_dashboard_button_waits_while_a_scan_or_an_export_runs(app, window):
    click(window.dashboard.map_card)
    window._set_busy(True)
    assert not window.home_button.isEnabled()
    window._set_busy(False)
    assert window.home_button.isEnabled()


def test_the_shortcuts_of_data_mapping_still_bring_it_forward_from_the_dashboard(app, window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "pick_folder", lambda: seen.append(window.workspace))
    window._in_mapping(window.pick_folder)  # what Ctrl+O does
    assert seen == ["mapping"] and window.workspace == "mapping"


# ----------------------------------------------------------------------------- a RawData.xlsx, through Analyze by Excel File
def analyze_rawdata(app, window, dialogs, chosen_file, path, method: str = "grr", *, carry_on: bool = True):
    """The way a RawData.xlsx is analysed: the second card, Variable / Cpk, the method, the file, and Continue to Analysis."""
    chosen_file.append(str(path))
    click(window.dashboard.raw_card)
    dialog = dialogs[-1]
    dialog.cards["variable"].clicked.emit()
    dialog.method_buttons[method].setChecked(True)
    dialog.choose_button.click()
    pump(app, lambda: not dialog._checking)
    if carry_on:
        dialog.continue_button.click()
    return dialog


def test_analyze_existing_rawdata_imports_the_file_and_opens_the_analysis_tab_without_running_it(app, window, rawdata, chosen_file, dialogs):
    good = rawdata.good
    analyze_rawdata(app, window, dialogs, chosen_file, good)
    assert chosen_file.asked == [1]  # the file dialog opened once, by Choose Excel File
    ws = window.validation
    assert window.workspace == "validation" and window.content.currentWidget() is ws and window.nav_bar.isVisible()
    imported(app, window)
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    assert ws.file_var.get() == str(good) and ws.study.mapping["source"] == "file" and ws.study.mapping["file"] == str(good)
    assert not ws.running and ws.result_set is None and ws.evaluated is None  # nothing was analysed
    assert ws.run_button.isEnabled() and ws.tabs.isTabEnabled(ws.tabs.indexOf(ws.setup_tab))
    assert window.scan_result is None and not window.selected_components  # Data Mapping was never needed
    assert "Test Items 2" in ws.dataset_var.get() and "Samples 3" in ws.dataset_var.get()
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    assert len(ws.results) == 2


def test_the_data_tabs_warnings_are_pointed_to_when_the_import_skips_past_it(app, window, rawdata, chosen_file, dialogs):
    analyze_rawdata(app, window, dialogs, chosen_file, rawdata.good, "capability")  # a capability study reads the worksheet order
    imported(app, window)
    ws = window.validation
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    assert "worksheet order" in ws.hint_var.get()  # the warning itself is where it always was
    assert ws.message_var.get().endswith("The Data tab lists warnings about these data.")


def test_without_warnings_the_message_after_the_import_is_the_usual_one(app, window, rawdata, chosen_file, dialogs):
    analyze_rawdata(app, window, dialogs, chosen_file, rawdata.good)
    imported(app, window)
    ws = window.validation
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    assert ws.hint_var.get() == "" and ws.message_var.get() == "Ready. Press Run analysis, or set up the study first."


def test_cancelling_the_file_dialog_changes_nothing(app, window, rawdata, chosen_file, dialogs):
    dialog = analyze_rawdata(app, window, dialogs, chosen_file, "")  # nothing picked
    assert chosen_file.asked == [1] and window.workspace == "dashboard" and dialog.state.path == "" and dialog.state.report is None
    assert window.validation is None or (window.validation.imported is None and window.validation.dataset is None)


def test_opening_the_dialog_again_with_a_rawdata_file_already_open_goes_back_to_it_and_replaces_nothing(app, window, rawdata, chosen_file, dialogs):
    analyze_rawdata(app, window, dialogs, chosen_file, rawdata.good)
    imported(app, window)
    ws = window.validation
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None)
    dataset, result_set = ws.dataset, ws.result_set
    click(window.home_button)
    assert window.workspace == "dashboard" and ws.result_set is result_set
    click(window.dashboard.raw_card)  # the dialog is as it was left: the same file, checked
    dialogs[-1].continue_button.click()
    assert window.workspace == "validation" and ws.dataset is dataset and ws.result_set is result_set and not ws.stale


def test_a_file_that_is_not_a_rawdata_workbook_is_an_invalid_file_and_nothing_is_imported(app, window, rawdata, chosen_file, dialogs):
    dialog = analyze_rawdata(app, window, dialogs, chosen_file, rawdata.wrong)
    assert dialog.status.text() == "Invalid File" and not dialog.continue_button.isEnabled()
    assert "is not a DataMapperX RawData workbook" in dialog.findings.toPlainText() and "STT and SN" in dialog.findings.toPlainText()  # as ever
    assert window.workspace == "dashboard" and (window.validation is None or window.validation.dataset is None)


def test_importing_from_the_data_tab_itself_still_stays_on_the_data_tab(app, window, rawdata, chosen_file):
    good = rawdata.good
    window._show_workspace("validation")
    ws = window.validation
    pump(app, lambda: not ws.busy)
    ws.source_radios["file"].click()
    chosen_file.append(str(good))
    ws.choose_file()
    imported(app, window)
    QTest.qWait(100)
    assert ws.tabs.currentWidget() is ws.data_tab  # only the Dashboard's import carries on to the Analysis tab


def test_a_second_import_replaces_the_data_and_the_old_results_are_marked_stale_not_reported(app, window, rawdata, chosen_file, dialogs):
    analyze_rawdata(app, window, dialogs, chosen_file, rawdata.good)
    imported(app, window)
    ws = window.validation
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    ws.run_button.click()
    pump(app, lambda: not ws.running and ws.result_set is not None and not ws.stale)
    first = ws.dataset
    click(window.home_button)
    analyze_rawdata(app, window, dialogs, chosen_file, rawdata.other)  # an explicit replacement: another workbook, one test item fewer
    pump(app, lambda: ws.file_var.get() == str(rawdata.other) and ws.dataset is not None and ws.dataset is not first and not ws.busy)
    pump(app, lambda: ws.tabs.currentWidget() is ws.setup_tab)
    assert "Test Items 1" in ws.dataset_var.get()
    assert ws.stale and not ws.pdf_button.isEnabled() and not ws.excel_button.isEnabled()  # the existing rule: a result of other data is not reported
