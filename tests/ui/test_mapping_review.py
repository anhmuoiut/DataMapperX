"""Phase 2 (UX V6): the Mapping and Review screens.

What these follow is that the screens say and show more, and that nothing they did before changed: the scan, the lists, the order of
the columns, the Pre-check figures, the criteria, the limits and the export are the ones tested in test_mapping.py. Here: the three
panels and their badges, the name Review Data, the summary above the data, the Pre-check counts agreeing with its table, the two ways
on that do not need each other, what a short window gives up, and the Criteria dialog.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QFileDialog, QLabel, QPushButton

from datamapperx.palette import DARK, LIGHT
from datamapperx.ui import main_window as mw
from datamapperx.ui.dialogs import GrrCriteriaDialog
from datamapperx.ui.theme import stylesheet
from datamapperx.ui.widgets import ActionTable, Card, DataTable, FlowRow, _RowLines

from ..conftest import ict_block, write_ict_log
from .support import pump, ready_to_review, scan
from .test_mapping import grr_logs


def reviewing(app, window, tmp_path, folder="logs"):
    """Three samples of two files, three components added, on the Review step."""
    ready_to_review(app, window, tmp_path / folder)
    window._show_step("review")
    pump(app, lambda: not window._preview_timer.isActive() and not window.is_busy)
    return window


def texts(widget) -> list[str]:
    return [w.text() for kind in (QLabel, QPushButton) for w in widget.findChildren(kind)]


# ----------------------------------------------------------------------------- the Mapping screen
def test_the_mapping_screen_has_the_three_panels_of_the_design(app, window, tmp_path):
    window._show_workspace("mapping")
    cards = window._pages["select"].findChildren(Card)
    assert [c.title.text() for c in cards] == ["01 · Source", "02 · Available Measurements", "03 · Selected Measurements"]
    assert not hasattr(window, "select_note") and not hasattr(window, "hint_label")  # no line that only explains
    panels = window._pages["select"].layout().itemAt(1).layout()  # the row of the three, under the title
    window.setMinimumSize(0, 0)
    window.resize(1500, 900)
    QTest.qWait(200)
    page = window._pages["select"]
    assert not page.narrow and [panels.stretch(i) for i in range(3)] == [27, 68, 35]  # the design's 270 : 680 : 350 (the pixels: see the screenshots)
    page.narrow_changed.emit(True)  # a narrow page: the Selected list, with its number, ↑ ↓ and × beside every name, gets more of it
    assert [panels.stretch(i) for i in range(3)] == [24, 56, 40]
    page.narrow_changed.emit(False)
    assert [panels.stretch(i) for i in range(3)] == [27, 68, 35]
    assert window.available_list.table_model.headings == ["Component", "Min", "Max", ""]  # MIN / MAX kept
    assert 28 <= window.available_list.verticalHeader().defaultSectionSize() <= 32  # compact, and a little taller than a data table's


def level_of(window, widget) -> int:
    """The height, in the window, of the middle of a widget: two widgets with the same value are on one line."""
    return widget.mapTo(window, widget.rect().center()).y()


def left_of(window, widget) -> int:
    return widget.mapTo(window, widget.rect().topLeft()).x()


def valued_logs(folder):
    """Three samples of two files: X with a Min and a Max, Text with none (a check that has no numbers), HalfOpen with only a Max."""
    folder.mkdir(exist_ok=True)
    for sn in ("VSE001", "VSE002", "VSE003"):
        for run in (1, 2):
            write_ict_log(folder / f"{sn}_{run}.log", sn, [ict_block("X", f"+{run}.5E+00", "+9.0E+00", "+0.0E+00"),
                                                         ict_block("Text", f"+{run}.0E+00"),
                                                         ict_block("HalfOpen", f"+{run}.0E+00", "+9.0E+00", None)])
    return folder


def test_the_available_header_is_one_line_with_the_value_filter_and_the_count_is_in_the_footer(app, window, tmp_path):
    window._show_workspace("mapping")
    valued = valued_logs(tmp_path / "logs")
    scan(app, window, valued)
    QTest.qWait(150)
    assert window.value_filter.text() == "Value"  # exactly
    assert window.value_filter.toolTip() == "Show only components with numeric MIN and MAX limits."
    assert window.available_info.text() == "3 available"
    title = next(c.title for c in window._pages["select"].findChildren(Card) if c.title.text().startswith("02"))
    assert title.text() == "02 · Available Measurements"
    assert abs(level_of(window, window.value_filter) - level_of(window, title)) <= 8  # the same line as the title, not a row of their own
    assert left_of(window, title) < left_of(window, window.value_filter)
    card = window._pages["select"].findChildren(Card)[1]
    assert level_of(window, window.available_info) > level_of(window, window.available_list)  # the count is under the list, not in the header
    assert abs(level_of(window, window.available_info) - level_of(window, window.add_button)) <= 2  # level with the ways to add
    assert left_of(window, window.available_info) - left_of(window, card) < 24 and left_of(window, window.available_info) < left_of(window, window.add_all_button)


def _luminance(colour) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green()) + 0.0722 * channel(colour.blue())


def _edge_contrast(window, against) -> float:
    """The strongest contrast, against the card, of anything drawn in the box of the Value check box (as the user sees it)."""
    QTest.qWait(100)
    top = window.value_filter.mapTo(window, QPoint(0, 0))
    image = window.grab(QRect(top.x(), top.y(), 18, window.value_filter.height())).toImage()
    base = _luminance(QColor(against))
    best = 1.0
    for x in range(image.width()):
        for y in range(image.height()):
            other = _luminance(image.pixelColor(x, y))
            best = max(best, (max(base, other) + 0.05) / (min(base, other) + 0.05))
    return best


def test_the_unchecked_value_box_can_be_seen_in_the_dark_theme_and_nothing_else_changes(app, window, tmp_path):
    window._show_workspace("mapping")
    assert not window.value_filter.isChecked()
    window._toggle_theme()
    assert window.palette_tokens.mode == "dark"
    assert _edge_contrast(window, DARK.surface) >= 3.0  # the least a user interface part needs to be told from its ground (WCAG 1.4.11)
    window.value_filter.setPalette(QPalette())  # what it was: the same widget with the application's colours
    assert _edge_contrast(window, DARK.surface) < 1.6  # so the check above does see the edge, and not something else
    window._style_value_filter()
    # nothing else was touched: the other check boxes, the light theme, and what the box does
    window.grr_criteria_button.click()
    dialog = window.findChildren(GrrCriteriaDialog)[-1]
    assert all(box.palette().window().color().name() == DARK.bg for box in dialog.findChildren(QCheckBox))
    dialog.close()
    window._toggle_theme()
    assert window.palette_tokens.mode == "light" and window.value_filter.palette().window().color().name() == LIGHT.bg
    window._toggle_theme()
    assert window.value_filter.palette().window().color().name() == DARK.muted  # and it follows the theme back again
    window.value_filter.setChecked(True)
    assert window.value_filter.isChecked() and window.value_filter.text() == "Value"


def test_the_value_filter_lists_only_components_with_a_numeric_min_and_max_and_changes_nothing_else(app, window, tmp_path):
    window._show_workspace("mapping")
    scan(app, window, valued_logs(tmp_path / "logs"))
    assert sorted(window.available_list.items()) == ["HalfOpen", "Text", "X"]
    window.value_filter.setChecked(True)
    assert window.available_list.items() == ["X"] and window.available_info.text() == "1 of 3 shown"
    window.search.setText("zzz")
    assert window.available_list.items() == [] and window.available_info.text() == "0 of 3 shown"  # the search still narrows it
    window.search.setText("")
    window._add_at(0)  # + on the one shown
    assert window.selected_components == ["X"] and window.available_list.items() == [] and window.available_info.text() == "0 of 2 shown"
    window.value_filter.setChecked(False)
    assert sorted(window.available_list.items()) == ["HalfOpen", "Text"] and window.available_info.text() == "2 available"
    window._add(["Text"])  # a component without limits is still selectable, and stays selected when the filter is on
    window.value_filter.setChecked(True)
    assert window.selected_components == ["X", "Text"] and window.selected_list.items() == ["X", "Text"]
    window.add_all_shown()  # "shown": with the filter on, nothing is left to add (HalfOpen has only a Max)
    assert window.selected_components == ["X", "Text"]
    window.reset_workflow()
    assert not window.value_filter.isChecked()  # a new start has no filter


def test_the_value_filter_is_the_logic_of_workflow_and_needs_both_limits_to_be_numbers():
    from datamapperx.workflow import available_view, has_numeric_limits

    limits = {"A": {"min": "+1.0E+00", "max": "+2.0E+00"}, "B": {"min": "–", "max": "+2.0E+00"}, "C": {"min": "x", "max": "y"}, "D": {}}
    assert [has_numeric_limits(limits, name) for name in "ABCDE"] == [True, False, False, False, False]
    everything = ["A", "B", "C", "D"]
    view = available_view(everything, [], "", numeric_only=True, limits=limits)
    assert view.items == ["A"] and view.info == "1 of 4 shown" and view.filtering and view.empty_text == "No component matches the filter."
    assert available_view(everything, [], "", limits=limits).items == everything  # off by default: as before
    assert available_view(everything, ["A"], "", numeric_only=True, limits=limits).items == []  # what is selected is not listed


def test_the_mapping_panels_keep_related_controls_on_one_line(app, window, tmp_path):
    window._show_workspace("mapping")
    scan(app, window, valued_logs(tmp_path / "logs"))
    QTest.qWait(150)
    assert abs(level_of(window, window.expected_edit) - level_of(window, window.repeats_edit)) <= 2  # side by side
    assert left_of(window, window.expected_edit) < left_of(window, window.repeats_edit)
    assert len({level_of(window, b) for b in (window.scan_button, window.cancel_button, window.reset_button)}) == 1  # the scan's three
    assert len({level_of(window, v) for v in (window.samples_value, window.files_value, window.components_value)}) == 1  # Samples/Files/Fields
    # as in the design: the ways to add under the Available list, Clear and the way on under the Selected list, the two rows level
    assert level_of(window, window.add_button) == level_of(window, window.add_all_button)
    assert abs(level_of(window, window.add_button) - level_of(window, window.review_button)) <= 2  # the two footers are level
    for footer_item in (window.available_info, window.selected_info, window.move_up_button, window.move_down_button):
        assert abs(level_of(window, footer_item) - level_of(window, window.review_button)) <= 2  # the counts and ↑ ↓ are on the same line
    assert left_of(window, window.add_all_button) < left_of(window, window.add_button)
    assert level_of(window, window.add_button) > level_of(window, window.available_list)  # under the list, not above it
    # and Clear selection is level with the search of the Available list, so that both lists start level
    assert abs(level_of(window, window.search) - level_of(window, window.clear_button)) <= 2
    assert window.review_button.isVisibleTo(window)


def test_each_selected_row_has_its_number_and_its_remove_button_only(app, window, tmp_path):
    window._show_workspace("mapping")
    scan(app, window, valued_logs(tmp_path / "logs"))
    window.add_all_shown()
    names = list(window.selected_components)
    table = window.selected_list
    assert len(names) == 3 and not table.horizontalHeader().isVisibleTo(window)  # the names only: no heading strip, no Min / Max / Type
    assert table.table_model.headings == [" No.", "Component", ""]  # a number, a name and ×: no ↑ ↓ on the rows
    assert table.table_model.rows[0][0] == "1" and table.items() == names
    remove = table._button_column
    assert remove == 2

    def press(row: int, column: int) -> None:
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(table.model().index(row, column)).center())

    n0, n1, n2 = names
    table.select_rows([1, 2])  # Alt+Up moves what is highlighted, several rows at once
    QTest.keyClick(table, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert window.selected_components == [n1, n2, n0] and table.selected_rows() == [0, 1]
    press(1, remove)  # the × of a row removes that row, and its name is available again
    assert window.selected_components == [n1, n0] and n2 in window.available_list.items()
    activated = []
    table.activated_rows.connect(activated.append)
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(table.model().index(0, remove)).center())
    assert activated == []  # a double click on a button is not "remove the highlighted rows"


def test_one_up_down_pair_under_the_selected_list_moves_the_highlighted_row(app, window, tmp_path):
    window._show_workspace("mapping")
    scan(app, window, valued_logs(tmp_path / "logs"))
    window.add_all_shown()
    n0, n1, n2 = names = list(window.selected_components)
    table, up, down = window.selected_list, window.move_up_button, window.move_down_button
    arrows = [b for b in window._pages["select"].findChildren(QPushButton) if b.text() in ("↑", "↓")]
    assert sorted(b.text() for b in arrows) == ["↑", "↓"]  # exactly one pair on the page
    assert level_of(window, up) > level_of(window, table) and left_of(window, up) < left_of(window, down) < left_of(window, window.review_button)
    assert window.selected_info.text() == "3 selected" and left_of(window, window.selected_info) < left_of(window, up)

    def click(button) -> None:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert not up.isEnabled() and not down.isEnabled()  # no row is highlighted
    table.select_rows([0])
    assert not up.isEnabled() and down.isEnabled()  # the first place has nowhere to go up
    table.select_rows([2])
    assert up.isEnabled() and not down.isEnabled()  # nor the last down
    click(down)
    assert window.selected_components == names  # a disabled button does nothing
    table.select_rows([1])
    assert up.isEnabled() and down.isEnabled()
    click(up)
    assert window.selected_components == [n1, n0, n2] and table.selected_rows() == [0]  # the row that moved stays highlighted
    assert [row[0] for row in table.table_model.rows] == ["1", "2", "3"] and table.items() == [n1, n0, n2]  # numbered again at once
    assert not up.isEnabled() and down.isEnabled()
    click(down)
    click(down)
    assert window.selected_components == [n0, n2, n1] and table.selected_rows() == [2] and not down.isEnabled()
    window._remove_at(0)  # the highlight goes with the list that changed: nothing to move
    assert not up.isEnabled() and not down.isEnabled() and window.selected_info.text() == "2 selected"
    window.clear_selected()
    assert window.selected_info.text() == "No columns selected" and window.selected_components == []


def test_a_narrow_page_says_so_at_its_threshold(app):
    from datamapperx.ui.widgets import NarrowPage

    page, seen = NarrowPage(1150), []
    page.narrow_changed.connect(seen.append)
    page.resize(1300, 300)
    page.show()
    QTest.qWait(50)
    assert not page.narrow and seen == []
    page.resize(1000, 300)
    QTest.qWait(50)
    assert page.narrow and seen == [True]
    page.resize(1149, 300)
    page.resize(1150, 300)
    QTest.qWait(50)
    assert not page.narrow and seen == [True, False]  # at the threshold itself it is roomy
    page.close()


def test_the_step_bar_is_a_row_of_small_pills_at_the_right_of_the_navigation(app, window, tmp_path):
    window._show_workspace("mapping")
    bar = window.step_bar
    window.setMinimumSize(0, 0)
    window.resize(1400, 900)  # wide enough for the offscreen font, which is wider than the interface font
    QTest.qWait(150)
    assert bar._compact and bar.height() == bar.PILL_HEIGHT and bar.height() < 40  # not the two boxes of 54 pixels
    assert left_of(window, bar) > left_of(window, window.home_button) + window.home_button.width()  # right of the Dashboard button
    assert abs(level_of(window, bar) - level_of(window, window.home_button)) <= 4  # one row with it
    assert (bar.state(0), bar.state(1)) == ("current", "locked") and "Scan" in bar.caption(1)  # the captions are kept, as tooltips
    cells = bar._cells()
    first, second = cells[0], cells[1]
    assert len(cells) == 5 and first.right() < second.left() and cells[-1].right() <= bar.width()  # Mapping to Report, in one row
    clicked = []
    bar.clicked.connect(clicked.append)
    bar.set_step(1, "ready", "Check the values, then export or analyze")
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=second.center().toPoint())
    assert clicked == [1]
    big = window.step_bar.__class__(("Select", "Review Data"), window.palette_tokens)  # the large form is still there for other uses
    assert not big._compact and big.height() == 54


def test_a_long_name_is_shortened_in_the_middle_and_keeps_its_end(app):
    from PySide6.QtGui import QFontMetrics

    from datamapperx.ui.widgets import elide_middle

    metrics = QFontMetrics(app.font())
    name = "Aux With Load [3v8], Vin (No Load)"
    assert elide_middle(metrics, name, metrics.horizontalAdvance(name)) == name  # it fits: untouched
    for width in (110, 140, 170):
        shown = elide_middle(metrics, name, width)
        assert shown.count("…") == 1 and metrics.horizontalAdvance(shown) <= width
        head, tail = shown.split("…")
        assert name.startswith(head) and name.endswith(tail) and len(tail) > len(head)  # more of the end than of the start
    other = "Aux With Load [3v8], Iin (No Load)"
    width = metrics.horizontalAdvance(name) * 0.8  # a fifth too long, in whatever font: the "V" and the "I" are in the part kept
    assert elide_middle(metrics, name, width) != elide_middle(metrics, other, width)  # two names that differ near the end stay apart
    assert elide_middle(metrics, name, 3) == "…"


def test_the_names_of_the_lists_are_shortened_in_the_middle_only_where_asked(app, window, tmp_path):
    from PySide6.QtCore import Qt as QtCore

    assert window.selected_list.textElideMode() == QtCore.TextElideMode.ElideMiddle
    assert window.available_list.textElideMode() == QtCore.TextElideMode.ElideMiddle
    for table in (window.preview_grid, window.grr_grid, window.limits_grid):
        assert table.textElideMode() == QtCore.TextElideMode.ElideMiddle
    window._show_workspace("validation")
    assert window.validation.preview.textElideMode() != QtCore.TextElideMode.ElideMiddle  # the other screens are as they were


def test_a_page_header_is_its_title_and_its_state_and_nothing_that_only_explains(app, window, tmp_path):
    window._show_workspace("mapping")
    header = window._pages["select"].layout().itemAt(0).widget()
    assert header.height() < 40  # one line
    assert [w.text() for w in header.findChildren(QLabel) if w.text()] == ["Select measurements", "No scan yet"]  # the title and the badge
    reviewing(app, window, tmp_path)
    review_header = window._pages["review"].layout().itemAt(0).widget()
    assert [w.text() for w in review_header.findChildren(QLabel) if w.text()] == ["Review Data", window.review_badge.text()]


def test_what_a_profile_reads_is_on_its_tooltip_and_the_order_hint_on_the_list(app, window, tmp_path):
    window._show_workspace("mapping")
    assert window.profile_box.toolTip().startswith(("Text log", "Excel log")) and "files:" in window.profile_box.toolTip()
    assert "column order of RawData.xlsx" in window.selected_list.viewport().toolTip()


def test_the_review_has_no_summary_bar_quick_check_row_line_or_check_badges(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    QTest.qWait(150)
    page = window._pages["review"]
    shown = texts(page)
    for caption in ("Samples", "Files / sample", "Selected measurements", "Specification limits", "Quick check"):
        assert caption not in shown  # the summary bar and the badge of the Data quality & settings card
    assert not any(text.startswith(("Row 1", "✓", "!  ")) for text in shown)  # the row line of the Limits and the badges under the data
    assert not any(hasattr(window, name) for name in ("stat_tiles", "review_row_label", "check_chips"))
    assert not window.legend_row.isVisibleTo(window)  # nothing is tinted in this dataset, so no key to the tints


def test_the_criteria_button_is_on_the_line_of_the_precheck_heading_and_only_there(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    QTest.qWait(150)
    assert window.side_tabs.currentWidget() is window.grr_page and window.grr_criteria_button.isVisibleTo(window)
    tabs = window.side_tabs.tabBar()
    assert abs(level_of(window, window.grr_criteria_button) - level_of(window, tabs)) <= 6  # one line with the tabs
    assert left_of(window, window.grr_criteria_button) > left_of(window, tabs) + tabs.width() - 4  # at the right of them
    window.side_tabs.setCurrentWidget(window.limits_page)  # the criteria are the Pre-check's: not offered beside the Limits
    assert not window.grr_criteria_button.isVisibleTo(window)
    window.side_tabs.setCurrentWidget(window.grr_page)
    assert window.grr_criteria_button.isVisibleTo(window)
    window.grr_criteria_button.click()
    assert window.findChildren(GrrCriteriaDialog)


def test_the_review_card_has_the_design_header_and_its_tabs(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    QTest.qWait(150)
    card = window.side_tabs.parent()
    while not isinstance(card, Card):
        card = card.parent()
    assert card.title.text() == "Data quality & settings" and card.badge is None
    assert window.side_tabs.tabText(0) == "GR&&R pre-check" and window.side_tabs.tabText(1) == "Limits (LSL / USL)"
    assert level_of(window, card.title) < level_of(window, window.side_tabs.tabBar()) < level_of(window, window.grr_grid)  # title, tabs, table
    heading = window.grr_page.findChildren(FlowRow)[0]
    assert [w.text() for w in heading.findChildren(QLabel)] == ["Total Gage R&R · Screening"]  # the heading is one line now
    window.side_tabs.setCurrentWidget(window.limits_page)  # the switch works both ways
    assert window.limits_grid.isVisibleTo(window) and not window.grr_grid.isVisibleTo(window)
    window.side_tabs.setCurrentWidget(window.grr_page)
    assert window.grr_grid.isVisibleTo(window) and not window.limits_grid.isVisibleTo(window)


def test_the_key_to_the_tints_is_there_only_for_the_tints_there_are(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for sn in ("VSE001", "VSE002", "VSE003"):
        for run in (1, 2):
            blocks = [ict_block("X", f"+{run}.5E+00", "+9.0E+00", "+0.0E+00")]
            if (sn, run) != ("VSE002", 2):
                blocks.append(ict_block("Y", f"+{run}.5E+00", "+9.0E+00", "+0.0E+00"))  # one file has no Y: a value is missing
            write_ict_log(folder / f"{sn}_{run}.log", sn, blocks)
    scan(app, window, folder)
    window.add_all_shown()
    window._show_step("review")
    pump(app, lambda: not window._preview_timer.isActive())
    assert not hasattr(window, "preview_note")  # the line under the title is gone: the hover and the Limits tab say it
    assert window.legend_row.isVisibleTo(window)
    assert window.legend_chips["missing"].isVisibleTo(window) and not window.legend_chips["invalid"].isVisibleTo(window)
    window.repeats_edit.setText("5")  # no sample has five files: every row is tinted as the wrong count
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.legend_chips["invalid"].isVisibleTo(window) and not window.legend_chips["missing"].isVisibleTo(window)
    window.repeats_edit.setText("2")  # the right count again, and nothing chosen: no value can be missing either
    window.clear_selected()
    pump(app, lambda: not window._preview_timer.isActive())
    assert not window.legend_row.isVisibleTo(window)  # nothing tinted, no key


def test_the_precheck_detail_is_two_short_lines_at_most(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    window.add_all_shown()
    window._show_step("review")
    detail = window.grr_detail.text()
    assert detail.count("\n") <= 1 and "samples × 3 repeats" in detail and "Study Var (6 × SD)" in detail  # the figures keep their words
    assert detail.splitlines()[0].count("  ·  ") == 2  # the name, the design and the Study Var on one line


def test_the_dense_widgets_are_opt_in(app):
    card, plain = Card("T", head=True, dense=True), Card("T")
    assert card.head is not None and plain.head is None and card.badge is None
    assert card.layout().contentsMargins().top() < plain.layout().contentsMargins().top() and card.body.spacing() < plain.body.spacing()


def test_the_badges_say_what_the_scan_found_and_how_many_are_available_and_selected(app, window, tmp_path):
    window._show_workspace("mapping")
    assert window.scan_badge.text() == "No scan yet" and window.scan_badge.property("badge") == "neutral"
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, window, folder)
    window.clear_selected()
    assert window.scan_badge.text() == "Scan completed" and window.scan_badge.property("badge") == "ok"
    assert window.available_info.text() == "3 available"
    assert window.selected_info.text() == "No columns selected"
    window._add_at(0)
    assert window.available_info.text() == "2 available"
    assert window.selected_info.text() == "1 selected"
    window.search.setText("zzz")
    assert " of " in window.available_info.text()  # "0 of 2 shown" while searching
    window.search.setText("")
    window.reset_workflow()
    assert window.scan_badge.text() == "No scan yet" and window.available_info.isHidden()  # nothing to count


def test_adding_removing_ordering_and_bulk_actions_work_as_before(app, window, tmp_path):
    window._show_workspace("mapping")
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, window, folder)
    window.clear_selected()
    listed = window.available_list.items()
    assert sorted(listed) == ["C1", "R1", "R2"]
    window.add_all_shown()
    assert window.selected_components == listed  # in the order the list showed them
    first, second, third = listed
    window.selected_list.select_rows([2])
    window.move_selected(-1)
    assert window.selected_components == [first, third, second] and window.selected_list.items() == [first, third, second]
    window._remove_at(0)  # the × button
    assert window.selected_components == [third, second] and window.available_info.text() == "1 available"
    window._add_at(0)  # the + button
    assert window.selected_components == [third, second, first]
    window.clear_selected()
    assert window.selected_components == [] and not window.review_button.isEnabled()
    assert window.clear_button.text() == "Clear selection"


# ----------------------------------------------------------------------------- the name Review Data
def test_review_and_export_is_called_review_data_everywhere(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    assert window.step_bar._titles == ["Mapping", "Review & Pre-check", "Analyze", "Results", "Report"]
    assert window.review_button.text().startswith("Review Data")
    assert not any("Review & Export" in text for text in texts(window)) and not any("Review & Export" in k + v for k, v in mw.SHORTCUTS)
    assert window.step_bar.caption(1) == "Check the values, then export or analyze" and window.step_bar.state(1) == "current"
    assert not hasattr(window, "review_note") and window.back_button.text().endswith("Edit selection")
    window.back_button.click()  # the way back to the selection
    assert window.step == "select" and window.content.currentWidget() is window._pages["select"]


def test_the_state_beside_the_title_is_read_from_the_scan_and_the_choice(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for sn in ("VSE001", "VSE002", "VSE003"):
        for run in (1, 2):
            write_ict_log(folder / f"{sn}_{run}.log", sn, [ict_block("X", f"+{run}.5E+00", "+9.0E+00", "+0.0E+00"),
                                                         ict_block("NoLimits", f"+{run}.0E+00")])
    scan(app, window, folder)
    window.add_all_shown()
    window._show_step("review")
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.review_badge.text() == "Dataset ready" and window.review_badge.property("badge") == "ok"
    assert window.review_count.text() == "6 rows"  # the preview's count is a badge, without its brackets


def test_a_wrong_file_count_is_said_beside_the_title_and_blocks_only_the_export(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    window.repeats_edit.setText("5")  # the samples have two files each
    pump(app, lambda: not window._preview_timer.isActive())
    assert window.review_badge.text() == "File count needs fixing" and window.review_badge.property("badge") == "warn"
    assert not window.export_button.isEnabled()
    assert window.validate_button.isEnabled()  # the analysis does not wait for a file that cannot be saved
    window.validate_button.click()
    assert window.workspace == "validation"


# ----------------------------------------------------------------------------- the Pre-check counts
def test_the_precheck_counts_agree_with_its_table_under_every_criteria(app, window, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, window, folder, repeats=3)
    window.add_all_shown()
    window._show_step("review")

    def counts() -> dict[str, str]:
        return {name: tile.count.text() for name, tile in window.grr_counts.items()}

    def from_table() -> dict[str, str]:
        results = [row[-1] for row in window.grr_grid.rows()]
        return {name: str(results.count(name)) for name in ("PASS", "CONDITION", "FAIL")}

    assert counts() == from_table() == {"PASS": "0", "CONDITION": "0", "FAIL": "2"}  # %Study Var 32 against FAIL above 30
    study, tolerance, ndc = window.grr_criteria
    window._set_grr_criteria((replace(study, pass_limit=20.0, fail_limit=40.0), tolerance, replace(ndc, enabled=False)))
    assert counts() == from_table() == {"PASS": "0", "CONDITION": "2", "FAIL": "0"}
    window._set_grr_criteria((replace(study, pass_limit=40.0, fail_limit=50.0), tolerance, replace(ndc, enabled=False)))
    assert counts() == from_table() == {"PASS": "2", "CONDITION": "0", "FAIL": "0"}
    window._set_grr_criteria((replace(study, enabled=False), tolerance, replace(ndc, enabled=False)))  # nothing decides
    assert counts() == {"PASS": "0", "CONDITION": "0", "FAIL": "0"} and all(row[-1] == "—" for row in window.grr_grid.rows())
    window.clear_selected()
    pump(app, lambda: not window._preview_timer.isActive())
    assert all(tile.count.text() == "–" for tile in window.grr_counts.values())  # no tests: no counts, not zeros


def test_the_precheck_is_called_a_screening_and_runs_no_analysis(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    assert any("Screening" in text for text in texts(window.grr_page)) and "quick check" in window.side_tabs.tabToolTip(0)
    assert window.validation is None or window.validation.result_set is None  # looking at the Pre-check analysed nothing


# ----------------------------------------------------------------------------- the two ways on
def test_continue_to_analysis_and_export_need_neither_the_other(app, window, tmp_path, monkeypatch):
    reviewing(app, window, tmp_path)
    assert window.export_button.text() == "Export RawData.xlsx…" and window.validate_button.text().startswith("Continue to Analysis")
    assert window.export_button.accessibleName() == "Export RawData.xlsx" and window.validate_button.accessibleName() == "Continue to Analysis"
    assert window.export_button.isEnabled() and window.validate_button.isEnabled()
    assert window.validate_button.property("primary") is True and not window.export_button.property("primary")  # the one for when in doubt

    # on to the analysis without exporting anything
    saved: list[str] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: saved.append("asked") or ("", "")))
    window.validate_button.click()
    pump(app, lambda: window.validation is not None and not window.validation.preparing)
    assert window.workspace == "validation" and saved == [] and window.validation.dataset is not None

    # and back, then export without going on to the analysis
    window._show_workspace("mapping")
    assert window.step == "review" and window.export_button.isEnabled()
    out = tmp_path / "RawData.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(mw, "ExportDoneDialog", lambda parent, path: type("D", (), {"present": lambda self: None})())
    window.export_button.click()
    pump(app, lambda: out.exists() and not window.is_busy)
    assert window.workspace == "mapping" and window.step == "review"  # saving the file is not a step towards the analysis


def test_the_two_ways_on_are_two_buttons_in_one_row_with_nothing_but_a_tooltip(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    QTest.qWait(150)
    assert not hasattr(window, "action_boxes")
    export, analyze = window.export_button, window.validate_button
    assert export.property("primary") is None and analyze.property("primary") is True  # the one for when in doubt
    assert "No analysis needed" in export.toolTip() and "No export needed" in analyze.toolTip()
    assert abs(level_of(window, export) - level_of(window, analyze)) <= 1 and left_of(window, export) < left_of(window, analyze)
    assert export.height() == analyze.height()  # one height


# ----------------------------------------------------------------------------- a short window
def test_a_short_window_keeps_the_two_ways_on_and_gives_up_only_the_lines_that_only_explain(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    window.setMinimumSize(0, 0)
    review = window._pages["review"]
    window.resize(1360, 1000)
    QTest.qWait(200)
    assert review.compact is False
    window.resize(1360, 400)
    QTest.qWait(200)
    assert review.compact is True
    assert window.export_button.isVisibleTo(window) and window.validate_button.isVisibleTo(window)  # the two ways on stay
    window.resize(1360, 1000)
    QTest.qWait(200)
    assert review.compact is False


def test_the_smallest_window_is_still_roomy_and_keeps_the_two_ways_on_in_one_row(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    window.resize(1000, 680)  # the smallest the window goes (set by the window itself)
    QTest.qWait(250)
    review = window._pages["review"]
    assert review.compact is False  # 680 tall leaves the page about 530
    assert level_of(window, window.export_button) == level_of(window, window.validate_button)
    assert window.validate_button.mapTo(window, window.validate_button.rect().bottomLeft()).y() < window.height()


def test_a_line_with_something_to_say_is_never_left_out_of_a_short_window(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    window.setMinimumSize(0, 0)
    window.resize(1360, 400)
    QTest.qWait(200)
    assert window._pages["review"].compact
    window.review_count.setText("5000 rows")
    window.preview_info.setText("Showing 300 of 5000 rows.")  # the preview is cut short: that is said
    window._sync_review_extras()
    assert not window.preview_info.isHidden()
    window.preview_info.setText("5000 rows.")  # the badge says as much already
    window._sync_review_extras()
    assert window.preview_info.isHidden()
    window._grr_note = False
    window._sync_review_extras()
    assert window.grr_detail.isHidden()
    window._grr_note = True  # a note on how a test was judged
    window._sync_review_extras()
    assert not window.grr_detail.isHidden()


# ----------------------------------------------------------------------------- the Criteria dialog
def test_the_criteria_dialog_explains_the_rule_and_keeps_its_choices(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    window.grr_criteria_button.click()
    dialog = window.findChildren(GrrCriteriaDialog)[-1]
    shown = texts(dialog)
    assert "GR&R Pre-check · Quick Check criteria" in shown
    assert any("does not change formal GR&R calculations" in text for text in shown)
    assert any("never counts as a PASS" in text and "up to FAIL is CONDITION" in text for text in shown)  # the rule as the code has it
    assert {"Reset to defaults", "Cancel", "Apply criteria"} <= set(shown)
    study = dialog.fields["percent_study_var"]
    assert study[0].isChecked() and study[1].text() == "10" and study[2].text() == "30"  # the defaults, in the fields as before
    study[1].setText("12")
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Apply criteria").click()
    assert window.grr_criteria[0].pass_limit == 12.0


# ----------------------------------------------------------------------------- what is new is opt-in, and themed
def test_row_lines_and_taller_rows_are_for_these_screens_only(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    for table in (window.preview_grid, window.grr_grid, window.limits_grid):
        assert isinstance(table, DataTable) and isinstance(table.itemDelegate(), _RowLines)
    for table in (window.available_list, window.selected_list):
        assert isinstance(table, ActionTable) and isinstance(table.itemDelegateForColumn(0), _RowLines)
    assert window.grr_grid.verticalHeader().defaultSectionSize() == mw.REVIEW_ROW_HEIGHT
    window._show_workspace("validation")
    plain = window.validation.preview  # the data table of Validation & Reports is as it was
    assert not isinstance(plain.itemDelegate(), _RowLines) and plain.verticalHeader().defaultSectionSize() == 28


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_new_parts_are_styled_in_both_themes(palette):
    css = stylesheet(palette)
    for rule in (f'QLabel[badge="ok"] {{ background: {palette.ok_bg}; color: {palette.ok}; }}',
                 f'QLabel[badge="bad"] {{ background: {palette.bad_bg}; color: {palette.danger}; }}',
                 f'QFrame#countTile[kind="warn"] {{ background: {palette.warn_bg}; }}',
                 f'QFrame#actionBox[primary="true"] {{ background: {palette.banner_bg}; border-color: {palette.accent}; }}',
                 f'QTabWidget#reviewTabs QTabBar::tab:selected {{ background: {palette.banner_bg}; color: {palette.accent}; }}'):
        assert rule in css


def test_the_theme_switch_reaches_the_review_and_keeps_its_data(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    rows, counts = window.preview_grid.rows(), {n: t.count.text() for n, t in window.grr_counts.items()}
    window._toggle_theme()
    assert window.palette_tokens.mode == "dark" and window.preview_grid.palette_tokens is window.palette_tokens
    assert window.grr_grid.palette_tokens is window.palette_tokens and window.limits_grid.palette_tokens is window.palette_tokens
    assert window.preview_grid.rows() == rows and {n: t.count.text() for n, t in window.grr_counts.items()} == counts
    window._toggle_theme()
    assert window.palette_tokens.mode == "light"


def test_the_dashboard_round_trip_keeps_the_review_as_it_was(app, window, tmp_path):
    reviewing(app, window, tmp_path)
    shown = (window.review_badge.text(), window.review_count.text())
    selected = list(window.selected_components)
    window.home_button.click()
    assert window.workspace == "dashboard"
    window.dashboard.map_card.clicked.emit()
    assert window.workspace == "mapping" and window.step == "review" and window.content.currentWidget() is window._pages["review"]
    assert (window.review_badge.text(), window.review_count.text()) == shown
    assert window.selected_components == selected
    assert window.export_button.isEnabled() and window.validate_button.isEnabled()
