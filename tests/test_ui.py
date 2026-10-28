"""Drive the real main window. Skipped automatically when there is no display (e.g. a bare Linux CI box)."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import filedialog, messagebox

import pytest
from openpyxl import load_workbook

from datamapperx import updater
from datamapperx._version import __version__

from .conftest import ict_block, write_ict_log

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def _window(tmp_path_factory):
    """One window for the whole module: Tk cannot reliably create a second root after destroying the first."""
    import os

    from datamapperx.config import DATA_DIR_ENV

    os.environ[DATA_DIR_ENV] = str(tmp_path_factory.mktemp("ui_userdata"))
    from datamapperx.ui.main_window import MainWindow

    try:
        window = MainWindow()
    except tk.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    yield window
    window.destroy()


@pytest.fixture
def app(_window, monkeypatch):
    # Never block on a real modal message box.
    shown: list[tuple[str, str]] = []
    for kind in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(messagebox, kind, lambda title, message, _k=kind, **kw: shown.append((_k, message)))
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    _window.shown = shown  # type: ignore[attr-defined]

    # Start every test from a clean slate.
    _window.settings.component_sets.clear()
    _window.settings.skipped_version = ""
    _window.expected_var.set("10")
    _window.repeats_var.set("3")
    _window.dark_var.set(False)
    _window.reset_workflow()
    _window.hide_update_banner()
    yield _window
    for child in _window.winfo_children():
        if isinstance(child, tk.Toplevel):
            child.destroy()
    _window.update()


def pump(app, until=lambda: True, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the UI")


def make_logs(folder, sns=("VSE001", "VSE002", "VSE003"), repeats=2, components=("R1", "R2", "C1")):
    for sn in sns:
        for run in range(repeats):
            blocks = [ict_block(c, f"+{run + 1}.5E+00", "+9.0E+00", "+0.0E+00") for c in components]
            write_ict_log(folder / f"{sn}_{run + 1}.log", sn, blocks)
    return folder


def scan(app, folder, expected=3, repeats=2):
    app.folder_var.set(str(folder))
    app.expected_var.set(str(expected))
    app.repeats_var.set(str(repeats))
    app.scan_logs()
    pump(app, lambda: not app.is_busy and app.scan_result is not None)


def test_builds_in_light_and_dark(app):
    app.update()
    assert app.winfo_exists()
    app.dark_var.set(True)
    app._on_theme_toggle()
    app.update()
    assert app.palette.mode == "dark"
    app.dark_var.set(False)
    app._on_theme_toggle()
    assert app.palette.mode == "light"


def test_scan_pick_preview_and_export(app, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)

    assert app.samples_var.get() == "3 / 3" and app.files_var.get() == "6" and app.components_var.get() == "3"
    assert app.available_list.items() == ["C1", "R1", "R2"]
    assert "Ready to export" in app.verdict_var.get()

    app.available_list.tree.selection_set(app.available_list.tree.get_children()[1:])  # R1, R2
    app.add_components()
    assert app.selected_components == ["R1", "R2"]
    assert app.available_list.items() == ["C1"]  # chosen ones leave the available list

    app._refresh_preview()
    assert len(app.preview_tree.get_children()) == 6
    first = app.preview_tree.item(app.preview_tree.get_children()[0], "values")
    assert tuple(first[:3]) == ("1", "VSE001", "VSE001_1.log") and tuple(first[3:]) == ("+1.5E+00", "+1.5E+00")

    out = tmp_path / "result.xlsx"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out))
    opened = []
    monkeypatch.setattr("datamapperx.ui.main_window.ExportDoneDialog", lambda parent, path: opened.append(path))
    app.export_excel()
    pump(app, lambda: not app.is_busy and opened)

    ws = load_workbook(out)["Raw Data"]
    assert [c.value for c in ws[1]][:4] == ["STT", "SN", "R1", "R2"]
    assert ws.max_row == 7 and ws["B2"].value == "VSE001"
    assert opened == [out]


def test_wrong_file_count_is_flagged_and_blocks_export(app, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder, sns=("VSE001", "VSE002"), repeats=2)
    write_ict_log(folder / "VSE003_1.log", "VSE003", [ict_block("R1", "+1.0E+00")])
    scan(app, folder)

    assert "VSE003" in app.verdict_var.get() and app.details_button.instate(["!disabled"])
    app.available_list.tree.selection_set(app.available_list.tree.get_children()[:1])
    app.add_components()
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: pytest.fail("must not reach the save dialog"))
    app.export_excel()
    assert any("exactly 2 files" in message for _kind, message in app.shown)


def test_empty_folder_explains_itself(app, tmp_path):
    scan(app, tmp_path)
    assert any("does not contain any files" in message for _kind, message in app.shown)
    assert app.samples_var.get() == "0 / 3"


def test_selection_is_remembered_for_the_next_scan(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    app.available_list.tree.selection_set(app.available_list.tree.get_children()[:2])
    app.add_components()
    remembered = list(app.selected_components)
    assert remembered

    app.reset_workflow()
    assert app.selected_components == []
    scan(app, folder)
    assert app.selected_components == remembered
    assert "Restored" in app.status_var.get()


def test_reorder_and_remove(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    app.add_all_shown()
    assert app.selected_components == ["C1", "R1", "R2"]

    app.selected_list.select_indices([2])
    app.move_selected(-1)
    assert app.selected_components == ["C1", "R2", "R1"]
    assert app.selected_list.selected_indices() == [1]
    app.move_selected(-1)
    app.move_selected(-1)  # already at the top: no-op, no crash
    assert app.selected_components == ["R2", "C1", "R1"]

    app.selected_list.select_indices([0, 1])
    app.remove_components()
    assert app.selected_components == ["R1"]
    app.clear_selected()
    assert app.selected_components == []


def test_filter_narrows_available_list(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    app.search_var.set("r")
    assert app.available_list.items() == ["R1", "R2"]
    assert app.available_info_var.get() == "2 of 3 shown"
    app.add_all_shown()
    assert app.selected_components == ["R1", "R2"]


def test_duplicate_components_prompt_once(app, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    for run in (1, 2):
        write_ict_log(folder / f"VSE001_{run}.log", "VSE001", [ict_block("R1", "+1.0E+00"), ict_block("R1", "+7.0E+00")])
    opened = []
    monkeypatch.setattr("datamapperx.ui.main_window.DuplicateDialog", lambda parent, groups, cb: opened.append((groups, cb)))
    scan(app, folder, expected=1)
    app.add_all_shown()
    assert len(opened) == 1 and len(opened[0][0]) == 2

    opened[0][1]({"R1"}, True)  # user closes the dialog
    app.clear_selected()
    app.add_all_shown()
    assert len(opened) == 1  # already reviewed, so not asked again


def test_every_dialog_opens_and_closes(app, tmp_path):
    from datamapperx.ui.dialogs import AboutDialog, ExportDoneDialog, ReportDialog
    from datamapperx.ui.duplicate_dialog import DuplicateDialog
    from datamapperx.ui.profile_dialog import ProfileManager
    from datamapperx.ui.update_dialog import UpdateDialog

    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.0E+00"), ict_block("R1", "+7.0E+00")])
    scan(app, folder, expected=1, repeats=1)

    info = updater.parse_manifest({"version": "9.0.0", "sha256": "0" * 64, "notes": "- new things"})
    results = []
    dialogs = [
        AboutDialog(app),
        ReportDialog(app, "t", "h", "body"),
        ExportDoneDialog(app, tmp_path / "x.xlsx"),
        DuplicateDialog(app, app.scan_result.duplicate_groups, lambda reviewed, applied: results.append(applied)),
        UpdateDialog(app, info, mandatory=False),
        ProfileManager(app, app.profiles, lambda name: None),
    ]
    app.update()
    assert all(d.winfo_exists() for d in dialogs)
    for dialog in dialogs:
        dialog.close()
    app.update()
    assert results == [False]  # closing without applying keeps defaults


def test_release_notes_render_headings_and_bullets(app):
    from datamapperx.ui.widgets import ReadOnlyText

    box = ReadOnlyText(app, app.palette)
    box.set_markdown("### New\n- **Faster** scan of `OneDrive` folders\nplain line")
    text = box.text.get("1.0", "end").strip().splitlines()
    assert text == ["New", "•  Faster scan of OneDrive folders", "plain line"]
    assert "heading" in box.text.tag_names("1.0") and "bullet" in box.text.tag_names("2.0")


def test_duplicate_dialog_applies_the_chosen_occurrence(app, tmp_path):
    from datamapperx.ui.duplicate_dialog import DuplicateDialog

    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.0E+00"), ict_block("R1", "+7.0E+00")])
    scan(app, folder, expected=1, repeats=1)
    done = []
    dialog = DuplicateDialog(app, app.scan_result.duplicate_groups, lambda reviewed, applied: done.append((reviewed, applied)))
    dialog._combos[0].current(1)
    dialog._apply()
    assert app.scan_result.grouped["VSE001"][0].entries["R1"].measured == "+7.0E+00"
    assert done == [({"R1"}, True)]


def test_profile_manager_duplicate_edit_save_delete(app):
    from datamapperx.ui.profile_dialog import ProfileManager

    changes = []
    manager = ProfileManager(app, app.profiles, changes.append)
    app.update()
    assert str(manager.save_button.cget("state")) == "disabled"  # built-in is read-only

    manager.listbox.selection_clear(0, tk.END)
    manager.listbox.selection_set(0)
    manager._on_select()
    manager._duplicate()
    assert manager.vars["name"].get() == "ICT_I3070 Test Log (copy)"
    manager.vars["name"].set("My ICT")
    manager.vars["measure_regex"].set("(unclosed")
    manager._save()
    assert "My ICT" not in app.profiles and any("Invalid Regex" in m for _k, m in app.shown)

    manager.vars["measure_regex"].set(app.profiles["ICT_I3070 Test Log"]["measure_regex"])
    manager._save()
    assert "My ICT" in app.profiles and changes == ["My ICT"]

    manager.listbox.selection_clear(0, tk.END)
    manager.listbox.selection_set(list(app.profiles).index("My ICT"))
    manager._on_select()
    manager._delete()
    assert "My ICT" not in app.profiles and changes[-1] is None
    manager.close()


def test_profile_manager_regex_tester(app):
    from datamapperx.ui.profile_dialog import ProfileManager

    manager = ProfileManager(app, app.profiles, lambda name: None)
    manager.vars["test_input"].set("{@BLOCK|R77|00|1")
    assert "Component: R77" in manager.test_result.get()
    manager.vars["test_input"].set("{@A-RES|0|+1.5E+03{@LIM2|+2.0E+03|+1.0E+03}}")
    assert "Measured: +1.5E+03" in manager.test_result.get() and "Min: +1.0E+03" in manager.test_result.get()
    manager.vars["test_input"].set("garbage")
    assert "not recognized" in manager.test_result.get()
    manager.close()


# ----------------------------------------------------------------------------- update flow in the window
def newer_info(**extra):
    return updater.parse_manifest({"version": "99.0.0", "sha256": "a" * 64, **extra})


def test_update_banner_shows_and_skip_is_remembered(app):
    app._on_update_checked(newer_info(), manual=False)
    app.update()
    assert app.banner.winfo_ismapped()
    app.skip_update("99.0.0")
    app.update()
    assert not app.banner.winfo_ismapped() and app.settings.skipped_version == "99.0.0"

    app._on_update_checked(newer_info(), manual=False)  # same version again: stays quiet
    app.update()
    assert not app.banner.winfo_ismapped()


def test_no_update_is_silent_unless_asked(app):
    app._on_update_checked(None, manual=False)
    assert app.shown == []
    app._on_update_checked(None, manual=True)
    assert any(__version__ in message for _k, message in app.shown)


def test_mandatory_update_opens_blocking_dialog(app, monkeypatch):
    opened = []
    monkeypatch.setattr("datamapperx.ui.main_window.UpdateDialog", lambda parent, info, mandatory: opened.append(mandatory))
    app._on_update_checked(newer_info(min_supported="99.0.0"), manual=False)
    assert opened == [True]


def test_failed_update_check_is_silent_at_startup(app):
    app._on_update_check_failed(updater.UpdateError("offline"), manual=False)
    assert app.shown == []


# ----------------------------------------------------------------------------- redesigned workspace

def test_export_action_tracks_workflow_readiness(app, tmp_path):
    assert app.export_button.instate(["disabled"])
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    assert app.export_button.instate(["disabled"])

    app.available_list.select_indices([0])
    app.add_components()
    assert app.export_button.instate(["!disabled"])
    app.clear_selected()
    assert app.export_button.instate(["disabled"])

    app.add_all_shown()
    assert app.export_button.instate(["!disabled"])
    app.reset_workflow()
    assert app.export_button.instate(["disabled"])


def test_busy_workspace_preserves_component_selection(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    app.available_list.select_indices([0, 1])
    app.add_components()
    app.available_list.select_indices([0])
    app.selected_list.select_indices([0])
    selected = list(app.selected_components)
    available = app.available_list.items()
    source_folder = app.folder_var.get()

    app._set_busy(True, cancellable=True)
    try:
        for button in (
            app.add_button, app.add_all_button, app.remove_button, app.clear_button,
            app.move_up_button, app.move_down_button, app.export_button,
        ):
            assert button.instate(["disabled"])
        for action in (
            app.add_components, app.add_all_shown, app.remove_components,
            app.clear_selected, lambda: app.move_selected(1), app.reset_workflow,
        ):
            action()
            assert app.selected_components == selected
            assert app.available_list.items() == available
            assert app.folder_var.get() == source_folder
    finally:
        app._set_busy(False)
    assert app.export_button.instate(["!disabled"])


def test_compact_workspace_keeps_primary_controls_visible(app):
    from tkinter import ttk

    previous_geometry = app.geometry()
    app.geometry("1000x680+0+0")
    app.update()
    try:
        left, top = app.winfo_rootx(), app.winfo_rooty()
        right, bottom = left + app.winfo_width(), top + app.winfo_height()
        for widget in (
            app.content_frame, app.source_card, app.profile_combo, app.browse_button,
            app.expected_spin, app.repeats_spin, app.scan_button, app.reset_button,
            app.add_button, app.add_all_button, app.remove_button, app.clear_button,
            app.move_up_button, app.move_down_button, app.export_button,
        ):
            assert widget.winfo_ismapped(), str(widget)
            assert left <= widget.winfo_rootx() < right, str(widget)
            assert top <= widget.winfo_rooty() < bottom, str(widget)
            assert widget.winfo_rootx() + widget.winfo_width() <= right + 1, str(widget)
            assert widget.winfo_rooty() + widget.winfo_height() <= bottom + 1, str(widget)
        style_name = str(app.preview_tree.cget("style")) or "Treeview"
        row_height = int(ttk.Style(app).lookup(style_name, "rowheight") or 26)
        assert app.preview_tree.winfo_ismapped()
        assert app.preview_tree.winfo_height() >= row_height * 3
        assert app.available_list.tree.winfo_width() > 0
        assert app.selected_list.tree.winfo_width() > 0
    finally:
        app.geometry(previous_geometry)
        app.update()


def test_theme_switch_preserves_preview_and_export_order(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    app.add_all_shown()
    app.selected_list.select_indices([2])
    app.move_selected(-1)
    app._refresh_preview()
    selected = list(app.selected_components)
    preview = [app.preview_tree.item(iid, "values") for iid in app.preview_tree.get_children()]

    for dark in (True, False):
        app.dark_var.set(dark)
        app._on_theme_toggle()
        app.update()
        assert app.selected_components == selected
        assert app.selected_list.items() == selected
        assert [app.preview_tree.item(iid, "values") for iid in app.preview_tree.get_children()] == preview
        assert app.export_button.instate(["!disabled"])


def test_available_filter_updates_add_all_without_row_selection(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    assert not app.available_list.selected_items()
    assert app.add_all_button.instate(["!disabled"])

    app.search_var.set("no-component-matches-this")
    assert app.available_list.items() == []
    assert app.add_all_button.instate(["disabled"])

    app.search_var.set("")
    assert app.available_list.items() == ["C1", "R1", "R2"]
    assert app.add_all_button.instate(["!disabled"])


def test_saved_geometry_is_clamped_to_available_display(app, monkeypatch):
    import re

    previous_setting = app.settings.geometry
    previous_geometry = app.geometry()
    previous_minimum = app.minsize()
    monkeypatch.setattr("datamapperx.ui.main_window.work_area", lambda *_args: (0, 0, 1280, 720))
    try:
        app.settings.geometry = "1900x1000+1600+900"
        app._setup_geometry()
        app.update()
        geometry = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", app.geometry())
        assert geometry is not None
        width, height, x, y = (int(value) for value in geometry.groups())
        assert x >= 0 and y >= 0
        assert x + width <= 1280
        assert y + height <= 720 - 40  # Leave room for the native title bar and borders.
    finally:
        app.settings.geometry = previous_setting
        app.minsize(*previous_minimum)
        app.geometry(previous_geometry)
        app.update()


# ----------------------------------------------------------------------------- the sample wizard
def open_wizard(app, sample, **kwargs):
    from datamapperx.ui.sample_wizard import SampleWizard

    done: list[tuple[str, dict]] = []
    wizard = SampleWizard(app, lambda name, profile: done.append((name, profile)), sample=sample, **kwargs)
    pump(app, lambda: wizard.vars["status"].get() not in ("", "Reading the sample…") or bool(wizard.vars["problem"].get()))
    return wizard, done


def select_text(wizard, line: int, text: str) -> None:
    content = wizard._lines[line - 1]
    start = content.index(text)
    wizard.viewer.tag_remove("sel", "1.0", "end")
    wizard.viewer.tag_add("sel", f"{line}.{start}", f"{line}.{start + len(text)}")


def wait_for_status(app, wizard, fragment: str) -> None:
    pump(app, lambda: fragment in wizard.vars["status"].get())


def test_wizard_reads_an_excel_sample_from_its_headings(app, tmp_path):
    from .test_sampling import EOL_ROWS, write_results_workbook

    path = write_results_workbook(tmp_path / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS, extra_graph_sheets=1)
    wizard, done = open_wizard(app, path)

    assert wizard.kind == "excel" and wizard.excel_panel.winfo_manager() == "grid" and wizard.text_panel.winfo_manager() == ""
    v = wizard.vars
    assert (v["data_sheet"].get(), v["sn_sheet"].get(), v["sn_cell"].get()) == ("Results", "Session", "B1")
    assert v["col_component"].get().startswith("C") and v["col_measured"].get().startswith("F")
    assert v["sn_value"].get() == "→ SV3826-06310A8C6-E1"
    assert "SV3826-06310A8C6-E1" in v["status"].get() and "3 components read" in v["status"].get()
    assert [wizard.table.item(i, "text") for i in wizard.table.get_children()] == [
        "Init, Test SIM SN", "Config, Get Portia SW Version", "DC bus voltage",
    ]

    wizard.accept()
    name, profile = done[0]
    assert name == tmp_path.name and not wizard.winfo_exists()
    assert (profile["sn_regex"], profile["data_sheet"], profile["component_col"], profile["unit_col"]) == ("B1", "Results", "C", "H")
    assert profile["skip_empty_rows"] is True


def test_wizard_updates_the_preview_when_a_column_changes_and_blocks_an_unusable_choice(app, tmp_path):
    from .test_sampling import EOL_ROWS, write_results_workbook

    path = write_results_workbook(tmp_path / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    wizard, done = open_wizard(app, path)
    last = wizard.table.get_children()[-1]
    assert wizard.table.item(last, "values")[3] == "V"

    wizard.vars["col_unit"].set("(none)")
    pump(app, lambda: wizard.table.get_children() and wizard.table.item(wizard.table.get_children()[-1], "values")[3] == "")

    wizard.vars["col_measured"].set("")
    pump(app, lambda: "measured value" in wizard.vars["problem"].get())
    wizard.accept()
    assert done == [] and wizard.winfo_exists()  # stays open until the settings are usable
    wizard.close()


def test_wizard_recognises_i3070_logs_and_shows_what_it_reads(app, tmp_path):
    from .test_sampling import make_ict_folder

    files = make_ict_folder(tmp_path / "ict")
    wizard, done = open_wizard(app, files[0])
    wait_for_status(app, wizard, "components read")

    assert wizard.kind == "text" and wizard.vars["block"].get() == "{@BLOCK|[Component]|00"
    assert wizard.vars["measure"].get() == "{@A-[Unit]|[Any]|[Measured]" and wizard.vars["sn_example"].get() == "VSE2C00000112"
    assert "VSE2C00000112" in wizard.vars["status"].get() and "3 components read" in wizard.vars["status"].get()
    assert wizard.rule_status["block"].get() == "found on 3 lines"
    components = wizard.viewer.tag_ranges("component")
    assert [str(wizard.viewer.get(components[i], components[i + 1])) for i in range(0, len(components), 2)] == ["1%r114", "c23", "u1107"]
    pump(app, lambda: bool(wizard.vars["folder_status"].get()))
    assert wizard.vars["folder_status"].get() == "The other 3 files in this folder can be read with these settings too."

    wizard.accept()
    profile = done[0][1]
    assert profile["block_template"] == "{@BLOCK|[Component]|00" and profile["sn_example"] == "VSE2C00000112"


def test_wizard_learns_an_unknown_text_format_from_selected_text(app, tmp_path):
    sample = tmp_path / "UNIT-8841_run1.txt"
    sample.write_text(
        "Board report\n\nTESTING R101\n   RESULT 4.71 V   LIMITS 4.50 .. 4.90\n\nTESTING U7 VCC\n   RESULT 3.31 V   LIMITS 3.00 .. 3.60\n",
        encoding="utf-8",
    )
    wizard, done = open_wizard(app, sample)
    assert "do not know this log format" in wizard.vars["findings"].get() and wizard.vars["block"].get() == ""

    wizard.accept()  # nothing to read yet
    assert "Fill in the component line" in wizard.vars["problem"].get() and done == []

    for line, text, blank in ((3, "R101", "Component"), (4, "4.71", "Measured"), (4, "V", "Unit"), (4, "4.50", "Min"), (4, "4.90", "Max")):
        select_text(wizard, line, text)
        wizard._mark(blank)
    assert wizard.vars["block"].get() == "TESTING [Component]"
    assert wizard.vars["measure"].get() == "RESULT [Measured] [Unit]" and wizard.vars["lim2"].get() == "LIMITS [Min] .. [Max]"

    wait_for_status(app, wizard, "2 components read")
    assert [wizard.table.item(i, "text") for i in wizard.table.get_children()] == ["R101", "U7 VCC"]
    assert wizard.table.item(wizard.table.get_children()[1], "values") == ("3.31", "3.00", "3.60", "V")

    wizard.accept()
    profile = done[0][1]
    from datamapperx.parsing import parse_log_file

    assert parse_log_file(sample, profile).entries["U7 VCC"].max_value == "3.60"


def test_wizard_explains_a_selection_that_cannot_be_used(app, tmp_path):
    from .test_sampling import make_ict_folder

    wizard, _done = open_wizard(app, make_ict_folder(tmp_path / "ict")[0])
    wizard.viewer.tag_remove("sel", "1.0", "end")
    wizard._mark("Component")
    assert "Select some text" in wizard.vars["problem"].get()

    wizard.viewer.tag_add("sel", "6.0", "8.5")
    wizard._mark("Component")
    assert "single line" in wizard.vars["problem"].get()

    wizard.vars["block"].set("{@BLOCK|")
    pump(app, lambda: "needs [Component]" in wizard.vars["problem"].get())
    assert wizard.rule_status["block"].get() == "cannot use this pattern"
    wizard.close()


def test_new_profile_from_a_sample_fills_the_form_and_saves(app, tmp_path, monkeypatch):
    from datamapperx.ui.profile_dialog import ProfileManager
    from datamapperx.ui.sample_wizard import SampleWizard

    from .test_sampling import EOL_ROWS, write_results_workbook

    folder = tmp_path / "EOL station"
    folder.mkdir()
    path = write_results_workbook(folder / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kwargs: str(path))

    changes = []
    manager = ProfileManager(app, app.profiles, changes.append)
    manager._new_from_sample()
    wizard = next(w for w in manager.winfo_children() if isinstance(w, SampleWizard))
    pump(app, lambda: wizard.sample is not None and "components read" in wizard.vars["status"].get())
    wizard.accept()

    v = manager.vars
    assert (v["name"].get(), v["type"].get(), v["sn_regex"].get(), v["component_col"].get()) == ("EOL station", "excel", "B1", "C")
    manager._save()
    saved = app.profiles["EOL station"]
    assert changes == ["EOL station"] and saved["data_sheet"] == "Results" and saved["skip_empty_rows"] is True
    manager.close()
    del app.profiles["EOL station"]


def test_editing_a_regular_expression_hides_the_readable_pattern_it_no_longer_matches(app, tmp_path, monkeypatch):
    from datamapperx.ui.profile_dialog import ProfileManager
    from datamapperx.ui.sample_wizard import SampleWizard

    from .test_sampling import make_ict_folder

    sample = make_ict_folder(tmp_path / "ict")[0]
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kwargs: str(sample))
    manager = ProfileManager(app, app.profiles, lambda name: None)
    manager._new_from_sample()
    wizard = next(w for w in manager.winfo_children() if isinstance(w, SampleWizard))
    pump(app, lambda: wizard.sample is not None and "components read" in wizard.vars["status"].get())
    wizard.accept()

    assert "Component line:  {@BLOCK|[Component]|00" in manager.summary.get() and "looks like VSE2C00000112" in manager.summary.get()
    assert manager._collect()["block_template"] == "{@BLOCK|[Component]|00"

    manager.vars["block_regex"].set(r"\{@BLOCK\|(?P<component>\w+)")
    assert "block_template" not in manager._collect()
    assert "Component line:  regular expression" in manager.summary.get()
    manager.close()


def test_built_in_profiles_cannot_be_reconfigured_by_the_wizard(app):
    from datamapperx.ui.profile_dialog import ProfileManager

    manager = ProfileManager(app, app.profiles, lambda name: None)
    assert str(manager.wizard_button.cget("state")) == "disabled"
    manager._open_wizard()
    assert any("Duplicate first" in message for _kind, message in app.shown)
    manager.close()


def test_an_empty_scan_offers_the_profile_that_reads_the_folder(app, tmp_path):
    from .test_sampling import EOL_ROWS, write_results_workbook

    folder = tmp_path / "eol"
    folder.mkdir()
    write_results_workbook(folder / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    original = app.profile_var.get()
    try:
        app.profile_var.set("ICT_I3070 Test Log")
        app.folder_var.set(str(folder))
        app.expected_var.set("1")
        app.repeats_var.set("1")
        app.scan_logs()
        # The first scan reads nothing; the suggested profile is accepted (the fixture answers "yes") and scans again.
        pump(app, lambda: app.profile_var.get() == "EOL Test Log" and not app.is_busy and app.scan_result is not None and bool(app.scan_result.grouped))
        assert app.scan_result.total_sns == 1 and "Init, Test SIM SN" in app.scan_result.components
    finally:
        app.profile_var.set(original)
        app._on_profile_changed()


def test_an_empty_scan_with_no_better_profile_just_explains(app, tmp_path):
    folder = tmp_path / "nothing"
    folder.mkdir()
    (folder / "notes.log").write_text("nothing to see", encoding="utf-8")
    app.profile_var.set("ICT_I3070 Test Log")
    scan(app, folder, expected=1, repeats=1)
    assert app.profile_var.get() == "ICT_I3070 Test Log" and not app.scan_result.grouped
    assert any(kind == "showwarning" for kind, _message in app.shown)


# ----------------------------------------------------------------------------- preview column widths
def test_preview_columns_are_only_as_wide_as_their_longest_value(app, tmp_path):
    from datamapperx.ui.widgets import MAX_COLUMN_WIDTH, _style_font

    folder = tmp_path / "logs"
    folder.mkdir()
    long_component = "Aux With Load [3v8], Iout (Load)"
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block(long_component, "+5.0E+00"), ict_block("R1", "+1.234567890123E+00")])
    write_ict_log(folder / "VSE002_a_much_longer_file_name_for_run_1.log", "VSE002", [ict_block(long_component, "+4.0E+00"), ict_block("R1", "+2.0E+00")])
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    pump(app, lambda: app._preview_job is None and len(app.preview_tree.get_children()) == 2)

    tree = app.preview_tree
    cell_font = _style_font(tree, "Treeview", ("Segoe UI", 10))
    heading_font = _style_font(tree, "Treeview.Heading", ("Segoe UI Semibold", 9))
    width = lambda column: int(tree.column(column, "width"))  # noqa: E731

    longest_file = "VSE002_a_much_longer_file_name_for_run_1.log"
    assert cell_font.measure(longest_file) <= width("file") <= cell_font.measure(longest_file) + 40
    assert width("sn") < 170  # "VSE001" no longer gets the old fixed 170 px
    assert heading_font.measure(long_component) <= width("c0") <= heading_font.measure(long_component) + 60
    longest_value = "+1.234567890123E+00"  # far longer than its heading "R1", so the value decides the width
    assert cell_font.measure(longest_value) <= width("c1") <= cell_font.measure(longest_value) + 40
    assert width("no") <= 60 and all(width(c) <= MAX_COLUMN_WIDTH for c in tree["columns"])


def test_a_column_can_never_grow_past_the_maximum(app):
    from tkinter import ttk

    from datamapperx.ui.widgets import MAX_COLUMN_WIDTH, fit_tree_columns

    tree = ttk.Treeview(app, columns=("a", "b"), show="headings")
    fit_tree_columns(tree, {"a": "A", "b": "B"}, [("x" * 500, "y")])
    assert int(tree.column("a", "width")) == MAX_COLUMN_WIDTH
    assert int(tree.column("b", "width")) < 80
    tree.destroy()


# ----------------------------------------------------------------------------- company logo and credit line
def test_logo_is_centred_in_the_header_and_follows_the_theme(app):
    app.update()
    label, header = app._brand_label, app._brand_label.master
    assert set(app._brand_logos) == {"light", "dark"} and label.winfo_manager() == "place"
    assert str(label.cget("image")[0])  # a ttk label reports its image as a tuple == str(app._brand_logos["light"])
    centre = label.winfo_x() + label.winfo_reqwidth() / 2
    assert abs(centre - header.winfo_width() / 2) <= 2  # centred on the window

    app.dark_var.set(True)
    app._on_theme_toggle()
    assert str(label.cget("image")[0])  # a ttk label reports its image as a tuple == str(app._brand_logos["dark"])
    app.dark_var.set(False)
    app._on_theme_toggle()
    assert str(label.cget("image")[0])  # a ttk label reports its image as a tuple == str(app._brand_logos["light"])


def test_credit_line_sits_at_the_bottom_left_of_the_source_card(app):
    from datamapperx.config import APP_CREDIT

    app.update()
    credit, card = app.credit_label, app.source_card
    assert credit.cget("text") == APP_CREDIT == "Developed by MAN TRAN"
    assert credit.winfo_y() > app.details_button.winfo_y()  # below every control of the card
    assert credit.winfo_x() <= 16  # left-aligned with the card's content (14 px padding)
    assert credit.winfo_y() + credit.winfo_height() >= card.winfo_height() - 20  # pinned to the bottom edge


def test_logo_pictures_are_shipped_for_both_themes_and_both_sizes():
    from datamapperx.paths import resource_path

    for mode in ("light", "dark"):
        for height in (38, 76):
            assert resource_path("assets", f"Jabil-Logo-{mode}-{height}.png").exists()


# ----------------------------------------------------------------------------- the preview is paged
def make_wide_logs(folder, count=45):
    names = [f"comp_{i:02d}" for i in range(count)]
    for sn, how_many in (("VSE001", count), ("VSE002", count - 1)):  # the last component is missing in the second file
        blocks = [ict_block(name, f"+{i}.5E+00", "+99E+00", "+0.0E+00") for i, name in enumerate(names[:how_many])]
        write_ict_log(folder / f"{sn}_1.log", sn, blocks)
    return names


def test_preview_draws_one_page_of_columns_and_the_export_keeps_all_of_them(app, tmp_path, monkeypatch):
    from datamapperx.config import PREVIEW_COLUMNS_PER_PAGE as PAGE

    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    pump(app, lambda: app._preview_job is None and len(app.preview_tree.get_children()) == 2)

    tree = app.preview_tree
    assert app.selected_components == names and len(tree["columns"]) == 3 + PAGE
    assert app.pager_var.get() == "Columns 1–20 of 45" and app.pager.winfo_manager() == "grid"
    assert str(app.pager_prev.cget("state")) == "disabled" and str(app.pager_next.cget("state")) == "normal"
    assert tree.heading("c0", "text") == "comp_00" and tree.heading("c19", "text") == "comp_19"
    # the missing value is on the last page, yet the whole selection is still checked for blanks
    assert "Amber" in app.preview_info_var.get() and "all 45 columns" in app.preview_info_var.get()

    app._page_preview(1)
    pump(app, lambda: app.pager_var.get() == "Columns 21–40 of 45" and app._preview_job is None)
    assert tree.heading("c0", "text") == "comp_20"
    assert tuple(tree.item(tree.get_children()[0], "values")[3:5]) == ("+20.5E+00", "+21.5E+00")

    app._page_preview(1)
    pump(app, lambda: app.pager_var.get() == "Columns 41–45 of 45" and app._preview_job is None)
    assert len(tree["columns"]) == 3 + 5 and str(app.pager_next.cget("state")) == "disabled"
    assert tuple(tree.item(tree.get_children()[1], "values")[7:8]) == ("",)  # comp_44 is blank in the second file
    app._page_preview(1)  # past the end stays on the last page
    pump(app, lambda: app._preview_job is None)
    assert app.pager_var.get() == "Columns 41–45 of 45"

    out = tmp_path / "wide.xlsx"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out))
    opened = []
    monkeypatch.setattr("datamapperx.ui.main_window.ExportDoneDialog", lambda parent, path: opened.append(path))
    app.export_excel()
    pump(app, lambda: not app.is_busy and opened)
    header = [c.value for c in load_workbook(out)["Raw Data"][1]][: 2 + 45]
    assert header == ["STT", "SN", *names]  # every column, not just the page that was on screen

    app.clear_selected()
    pump(app, lambda: app._preview_job is None)
    assert app.pager.winfo_manager() == "" and len(tree["columns"]) == 3


def test_the_page_resets_for_a_new_scan_and_when_the_selection_shrinks(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    app._page_preview(2)
    pump(app, lambda: app.pager_var.get() == "Columns 41–45 of 45" and app._preview_job is None)

    app.selected_components = names[:25]  # fewer columns: the page that no longer exists falls back to the last one
    app._refresh_preview()
    assert app.pager_var.get() == "Columns 21–25 of 25"
    app.selected_components = names[:5]
    app._refresh_preview()
    assert app._preview_page == 0 and app.pager.winfo_manager() == ""

    app.selected_components = list(names)
    app._preview_page = 2
    scan(app, folder, expected=2, repeats=1)
    assert app._preview_page == 0


# ----------------------------------------------------------------------------- closing and the self-test
def test_closing_the_window_cancels_a_scan_that_is_still_running():
    import threading
    from types import SimpleNamespace

    from datamapperx.ui.main_window import MainWindow

    calls = []
    fake = SimpleNamespace(
        _cancel=threading.Event(),
        _remember_inputs=lambda: calls.append("remember"),
        settings=SimpleNamespace(geometry=""),
        geometry=lambda: "1000x700+0+0",
        destroy=lambda: calls.append("destroy"),
    )
    import datamapperx.ui.main_window as module

    original = module.save_settings
    module.save_settings = lambda settings: calls.append("save")
    try:
        MainWindow._on_close(fake)
    finally:
        module.save_settings = original
    assert fake._cancel.is_set() and calls == ["remember", "save", "destroy"]  # cancelled before the window goes away


def test_the_smoke_test_checks_the_app_end_to_end(app, tmp_path, monkeypatch, caplog):
    from datamapperx import selftest
    from datamapperx.ui import main_window

    # reuse the already open window: the smoke test makes its own, and Tk cannot reliably host two roots
    monkeypatch.setattr(main_window, "MainWindow", lambda: app)
    monkeypatch.setattr(app, "destroy", lambda: None)
    sample = selftest._check_logic(tmp_path)
    assert sample.name == "VSE000SMOKE_1.xlsx"
    selftest._check_window(sample)
    with pytest.raises(selftest.SmokeTestError):
        selftest._require(False, "boom")
