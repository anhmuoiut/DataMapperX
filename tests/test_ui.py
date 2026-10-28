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
