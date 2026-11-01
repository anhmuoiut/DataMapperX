"""The Qt widgets, the table model, the theme and the background runner, each on its own."""
from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleFactory

from datamapperx.palette import DARK, LIGHT
from datamapperx.stat_charts import chart_primitives, charts_for_result
from datamapperx.statistics import AnalysisConfig, analyze, normalize_records
from datamapperx.ui_qt.models import TableModel
from datamapperx.ui_qt.tasks import TaskRunner
from datamapperx.ui_qt.theme import apply_theme, make_palette, resolve_mode
from datamapperx.ui_qt.widgets import ActionTable, ChartPanel

from ..conftest import ict_block, write_ict_log
from .support import pump


# ----------------------------------------------------------------------------- theme
def test_the_palette_comes_from_the_shared_colour_tokens(app):
    for tokens in (LIGHT, DARK):
        palette = make_palette(tokens)
        assert palette.window().color().name() == tokens.bg and palette.base().color().name() == tokens.surface
        assert palette.highlight().color().name() == tokens.accent
    assert resolve_mode("light") == "light" and resolve_mode("dark") == "dark"
    assert apply_theme(app, "dark").mode == "dark"
    assert app.palette().window().color().name() == DARK.bg and "QFrame#card" in app.styleSheet()
    styles = QStyleFactory.keys()  # a list of style names
    assert "Fusion" in styles
    apply_theme(app, "light")
    assert app.palette().window().color().name() == LIGHT.bg


# ----------------------------------------------------------------------------- the table model
def test_the_model_serves_text_alignment_and_tints_for_visible_cells_only(app):
    model = TableModel(LIGHT)
    model.set_table(["A", "B"], [(1, 2.5), ("x", None)], tags=["invalid", ""], aligns=["w", "e"], cell_tags={(1, 0): "pass"})
    assert (model.rowCount(), model.columnCount()) == (2, 2)
    index = model.index
    assert model.data(index(0, 1)) == "2.5" and model.data(index(1, 1)) == "" and model.data(index(0, 0)) == "1"
    assert model.data(index(0, 0), Qt.ItemDataRole.BackgroundRole).name() == LIGHT.bad_bg
    assert model.data(index(1, 0), Qt.ItemDataRole.BackgroundRole).name() == LIGHT.ok_bg  # a cell tag wins over the row's
    assert model.data(index(1, 1), Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(index(0, 1), Qt.ItemDataRole.TextAlignmentRole) & int(Qt.AlignmentFlag.AlignRight)
    assert model.headerData(1, Qt.Orientation.Horizontal) == "B"
    model.set_palette(DARK)
    assert model.data(index(0, 0), Qt.ItemDataRole.BackgroundRole).name() == DARK.bad_bg


# ----------------------------------------------------------------------------- background tasks
def test_results_are_delivered_on_the_ui_thread_and_the_work_runs_elsewhere(app):
    runner, seen = TaskRunner(), {}
    main = threading.get_ident()
    runner.run(lambda report: (report(1, 2), threading.get_ident())[1],
               on_progress=lambda *a: seen.setdefault("progress", (a, threading.get_ident())),
               on_success=lambda worker: seen.update(done=threading.get_ident(), worker=worker),
               on_error=lambda exc: seen.update(error=exc))
    pump(app, lambda: "done" in seen)
    assert seen["done"] == main and seen["worker"] != main
    assert seen["progress"] == ((1, 2), main) and not runner.busy


def test_the_gil_switch_interval_is_shortened_only_while_a_task_runs(app):
    before, runner, seen = sys.getswitchinterval(), TaskRunner(), {}
    runner.run(lambda report: sys.getswitchinterval(), on_success=lambda inside: seen.update(inside=inside),
               on_error=lambda exc: seen.update(error=exc))
    pump(app, lambda: "inside" in seen or "error" in seen)
    assert seen["inside"] < before and sys.getswitchinterval() == before


def test_an_error_in_the_work_reaches_on_error_and_never_gets_lost(app):
    runner, seen = TaskRunner(), []
    runner.run(lambda report: 1 / 0, on_success=lambda _r: seen.append("ok"), on_error=seen.append)
    pump(app, lambda: bool(seen))
    assert isinstance(seen[0], ZeroDivisionError)


# ----------------------------------------------------------------------------- action list
def table_of_three(kind="add", **options):
    table = ActionTable(LIGHT, kind=kind, name_heading="Component", **options)
    table.resize(420, 300)
    table.set_items(["A", "B", "C"], values=[("1", "2")] * 3 if kind == "add" else None)
    table.show()
    return table


def test_each_click_on_a_button_acts_on_its_own_row_even_when_clicks_are_quick(app):
    table = table_of_three(value_headings=("Min", "Max"))
    pressed = []
    table.action.connect(pressed.append)
    button = lambda row: table.visualRect(table.model().index(row, 3)).center()  # noqa: E731
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=button(1))
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=button(2))  # straight after, on another row
    assert pressed == [1, 2]
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(table.model().index(0, 0)).center())
    assert pressed == [1, 2]  # a click on the name is a selection, not an action
    assert table.selected_rows() == [0]
    table.close()


def test_enter_and_a_double_click_on_a_name_activate_the_selected_rows_but_not_a_double_click_on_a_button(app):
    table = table_of_three("remove", numbered=True)  # columns: No., Component, button
    activated, deleted = [], []
    table.activated_rows.connect(activated.append)
    table.delete_pressed.connect(lambda: deleted.append(True))
    table.select_rows([0, 2])
    table.doubleClicked.emit(table.model().index(0, 1))
    assert activated == [[0, 2]]
    table.doubleClicked.emit(table.model().index(0, 2))  # the button column
    assert activated == [[0, 2]]
    QTest.keyClick(table, Qt.Key.Key_Return)
    assert activated == [[0, 2], [0, 2]]
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert deleted == [True]
    table.close()


def test_an_empty_list_says_why(app):
    table = ActionTable(LIGHT, kind="add", name_heading="Component")
    table.resize(300, 200)
    table.set_items([], empty_text="Scan a folder to list\nits components here.")
    image = table.grab().toImage()
    muted = sum(1 for x in range(0, image.width(), 2) for y in range(60, image.height(), 2)
                if image.pixelColor(QPoint(x, y)).name() != image.pixelColor(QPoint(2, 100)).name())
    assert muted > 30  # the hint text was painted into the empty viewport


# ----------------------------------------------------------------------------- charts
def test_every_chart_of_an_item_is_painted(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for s in range(4):
        for t in range(3):
            write_ict_log(folder / f"S{s}_{t}.log", f"VSE{s:03d}", [ict_block("Alpha", f"{10 + s + t * 0.01:+.5E}", "+2.0E+01", "+0.0E+00")])
    from datamapperx.scanner import scan_folder

    scan = scan_folder(folder, __import__("datamapperx.profiles", fromlist=["load_profiles"]).load_profiles()["ICT_I3070 Test Log"])
    result = analyze(normalize_records(scan.grouped, ["Alpha"], assign_trials=True), AnalysisConfig(method="grr", expected_repeats=3))[0]
    specs = charts_for_result(result)
    assert len(specs) == 4 and all(chart_primitives(spec, 400, 220) for spec in specs)
    panel = ChartPanel()
    panel.resize(900, 700)
    panel.set_specs(specs)
    image = panel.grab().toImage()
    dark = sum(1 for x in range(0, image.width(), 3) for y in range(0, image.height(), 3) if image.pixelColor(QPoint(x, y)).lightness() < 200)
    assert dark > 200  # lines, bars and text were drawn on the white background
