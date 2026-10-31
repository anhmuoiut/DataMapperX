"""Drive the real main window. Skipped automatically when there is no display (e.g. a bare Linux CI box)."""

from __future__ import annotations

import itertools
import time
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox

import pytest
from openpyxl import load_workbook

from datamapperx import updater
from datamapperx._version import __version__
from datamapperx.stat_reports import item_label

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
        window = MainWindow(background_checks=False)  # a test run must never depend on the network
    except tk.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    window.update()  # lets the review page build itself, as it does a moment after the real window opens
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
    _window.deiconify()  # a minimised or hidden window would make every "is it on screen" check fail
    end = time.time() + 5
    while not _window.winfo_ismapped() and time.time() < end:  # e.g. the screen was off or locked a moment ago
        _window.update()
        time.sleep(0.05)
    if not _window.winfo_ismapped():
        pytest.skip("the main window cannot be shown (the screen is locked or off)")
    _window.update()

    # Start every test from a clean slate.
    _window.settings.component_sets.clear()
    _window.settings.skipped_version = ""
    _window.settings.check_updates = True
    _window.settings.deactivated, _window.settings.deactivated_message, _window.settings.verified_at = False, "", 0.0
    _window._access_dialog = None
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
    raise AssertionError(f"timed out waiting for the UI (busy={getattr(app, 'is_busy', None)}, status={getattr(app, 'status_var', None) and app.status_var.get()!r})")


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

    app.available_list.select_indices([1, 2])  # R1, R2
    app.add_components()
    assert app.selected_components == ["R1", "R2"]
    assert app.available_list.items() == ["C1"]  # chosen ones leave the available list

    app._show_step("review")
    assert app.step == "review"
    assert len(app.preview_grid.rows()) == 6
    first = app.preview_grid.rows()[0]
    assert first[:3] == ("1", "VSE001", "VSE001_1.log") and first[3:] == ("+1.5E+00", "+1.5E+00")

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
    app.available_list.select_indices([0])
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
    app.available_list.select_indices([0, 1])
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


def test_turning_the_notice_off_hides_the_banner_but_not_a_required_update(app, monkeypatch):
    app.settings.check_updates = False
    app._on_update_checked(newer_info(), manual=False)
    app.update()
    assert not app.banner.winfo_ismapped()

    opened = []
    monkeypatch.setattr("datamapperx.ui.main_window.UpdateDialog", lambda parent, info, mandatory: opened.append(mandatory))
    app._on_update_checked(newer_info(min_supported="99.0.0"), manual=False)
    assert opened == [True]


# ----------------------------------------------------------------------------- the owner's off switch
DAY = 24 * 60 * 60


def answer_status(monkeypatch, outcome):
    """Make the status check return ``outcome`` (a Status), or fail with it (an exception)."""

    def fetch(timeout=8.0):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(updater, "fetch_status", fetch)


def check_access(app, then=None):
    """Run the background check and wait until its answer has been handled."""
    app.verify_access(then=then)
    pump(app, lambda: not app.tasks._active and app.tasks._queue.empty())
    app.update()


def test_the_window_stays_off_the_network_when_asked(app):
    assert app._enforce_access is False  # the fixture built it with background_checks=False


def test_a_switched_off_copy_shows_the_owners_message_and_runs_nothing_else(app, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Version 1.2 has a bug. Ask Man for 1.3."))
    followed = []
    check_access(app, then=lambda: followed.append("update check"))

    dialog = app._access_dialog
    assert dialog is not None and dialog.winfo_exists()
    assert "switched off" in dialog.heading.cget("text")
    assert "Ask Man for 1.3" in dialog.message.cget("text")
    assert followed == []  # no update is offered to a copy that may not run
    assert app.settings.deactivated


def test_the_off_switch_dialog_can_only_check_again_or_exit(app, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app)
    dialog = app._access_dialog
    left = []
    monkeypatch.setattr(app, "exit_app", lambda: left.append(True))

    dialog.close()  # the window's X button and Esc both end up here
    assert left == [True]
    dialog.exit_button.invoke()
    assert left == [True, True]


def test_check_again_lets_the_copy_run_once_the_owner_switches_it_back_on(app, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app)
    dialog = app._access_dialog
    assert dialog.winfo_exists()

    answer_status(monkeypatch, updater.Status(False, ""))
    dialog.check_button.invoke()
    pump(app, lambda: not dialog.winfo_exists())
    assert not app.settings.deactivated


def test_a_switched_off_copy_stays_off_when_it_cannot_reach_github(app, monkeypatch):
    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app)

    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    followed = []
    check_access(app, then=lambda: followed.append(True))
    dialog = app._access_dialog
    assert dialog.winfo_exists() and "switched off" in dialog.heading.cget("text")
    assert "no route" in dialog.detail.cget("text")
    assert followed == []


def test_no_answer_is_tolerated_inside_the_grace_period(app, monkeypatch):
    app.settings.verified_at = time.time() - 3 * DAY
    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    followed = []
    check_access(app, then=lambda: followed.append(True))
    assert app._access_dialog is None
    assert followed == [True]  # the normal update check still goes ahead
    assert not app.settings.deactivated


def test_no_answer_for_too_long_asks_for_a_connection(app, monkeypatch):
    from datamapperx import access

    app.settings.verified_at = time.time() - (access.OFFLINE_GRACE_DAYS + 2) * DAY
    answer_status(monkeypatch, updater.UpdateError("Could not reach GitHub: no route"))
    check_access(app)
    dialog = app._access_dialog
    assert dialog is not None and dialog.winfo_exists()
    assert "could not be checked" in dialog.heading.cget("text")

    answer_status(monkeypatch, updater.Status(False, ""))  # back on the network
    dialog.check_button.invoke()
    pump(app, lambda: not dialog.winfo_exists())
    assert abs(app.settings.verified_at - time.time()) < 60


def test_a_good_answer_saves_when_it_was_asked(app, monkeypatch):
    from datamapperx.settings import load_settings

    answer_status(monkeypatch, updater.Status(True, "Stopped"))
    check_access(app)
    saved = load_settings()
    assert saved.deactivated and saved.deactivated_message == "Stopped"  # so the next start is blocked before any network


def test_a_clear_answer_does_nothing_visible_when_all_is_well(app, monkeypatch):
    answer_status(monkeypatch, updater.Status(False, ""))
    followed = []
    check_access(app, then=lambda: followed.append(True))
    assert app._access_dialog is None and followed == [True]
    assert app.shown == []


# ----------------------------------------------------------------------------- the two steps
def ready_to_review(app, folder, **kwargs):
    """Logs scanned and every component added, still on the first step."""
    make_logs(folder, **kwargs)
    scan(app, folder)
    app.add_all_shown()


def test_export_action_tracks_workflow_readiness(app, tmp_path):
    assert app.export_button.instate(["disabled"]) and app.review_button.instate(["disabled"])
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    assert app.export_button.instate(["disabled"]) and app.review_button.instate(["disabled"])

    app.available_list.select_indices([0])
    app.add_components()
    assert app.export_button.instate(["!disabled"]) and app.review_button.instate(["!disabled"])
    app.clear_selected()
    assert app.export_button.instate(["disabled"]) and app.review_button.instate(["disabled"])

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
            app.add_button, app.add_all_button, app.clear_button, app.move_up_button, app.move_down_button,
            app.review_button, app.export_button, app.back_button,
        ):
            assert button.instate(["disabled"])
        for action in (
            app.add_components, app.add_all_shown, app.remove_components, lambda: app._add_at(0), lambda: app._remove_at(0),
            app.clear_selected, lambda: app.move_selected(1), app.reset_workflow, lambda: app._on_step_clicked(1),
        ):
            action()
            assert app.selected_components == selected
            assert app.available_list.items() == available
            assert app.folder_var.get() == source_folder
            assert app.step == "select"
    finally:
        app._set_busy(False)
    assert app.export_button.instate(["!disabled"])


def inside(app, widget):
    left, top = app.winfo_rootx(), app.winfo_rooty()
    right, bottom = left + app.winfo_width(), top + app.winfo_height()
    return (
        widget.winfo_ismapped()
        and left <= widget.winfo_rootx() < right and top <= widget.winfo_rooty() < bottom
        and widget.winfo_rootx() + widget.winfo_width() <= right + 1
        and widget.winfo_rooty() + widget.winfo_height() <= bottom + 1
    )


def test_compact_workspace_keeps_primary_controls_visible(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, folder)
    previous_geometry = app.geometry()
    app.geometry("1000x680+0+0")
    app.update()
    try:
        for widget in (
            app.theme_button, app.help_button, app.step_bar, app.content_frame, app.source_card, app.profile_combo,
            app.browse_button, app.expected_spin, app.repeats_spin, app.scan_button, app.reset_button,
            app.version_label, app.credit_label, app.add_button, app.add_all_button, app.clear_button,
            app.move_up_button, app.move_down_button, app.review_button, app.available_list, app.selected_list,
        ):
            assert inside(app, widget), str(widget)
        assert "files each" in app.verdict_var.get()  # the longest text the Source card shows (it wraps onto two lines)
        card_bottom = app.source_card.winfo_rooty() + app.source_card.winfo_height()
        for widget in (app.details_button, app.version_label, app.credit_label):  # nothing is clipped by the card's edge
            assert widget.winfo_rooty() + widget.winfo_height() <= card_bottom, str(widget)
        assert app.available_list._body.winfo_height() >= 2 * app.available_list.ROW_HEIGHT
        assert app.selected_list._body.winfo_height() >= 2 * app.selected_list.ROW_HEIGHT

        app._show_step("review")
        app.update()
        assert inside(app, app.grr_grid)
        assert app.grr_grid._body.winfo_height() >= 2 * app.grr_grid._row_height()
        app.review_side_tabs.select(app.limits_page)
        app.update()
        for widget in (app.preview_grid, app.limits_grid, app.check_chips, app.back_button, app.export_button):
            assert inside(app, widget), str(widget)
        for grid in (app.preview_grid, app.limits_grid):
            assert grid._body.winfo_height() >= 3 * grid._row_height()
    finally:
        app.geometry(previous_geometry)
        app.update()


def test_theme_switch_preserves_preview_and_export_order(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, folder)
    app.selected_list.select_indices([2])
    app.move_selected(-1)
    app._show_step("review")
    selected = list(app.selected_components)
    preview, limits = app.preview_grid.rows(), app.limits_grid.rows()

    for dark in (True, False):
        app.dark_var.set(dark)
        app._on_theme_toggle()
        app.update()
        assert app.selected_components == selected
        assert app.selected_list.items() == selected
        assert app.preview_grid.rows() == preview and app.limits_grid.rows() == limits
        assert app.export_button.instate(["!disabled"]) and app.step == "review"
        assert app.step_bar.palette is app.palette and app.available_list.palette is app.palette
        assert app.preview_grid.palette is app.palette and app.limits_grid.palette is app.palette


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
    folder = tmp_path / "logs"
    folder.mkdir()
    long_component = "Aux With Load [3v8], Iout (Load)"
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block(long_component, "+5.0E+00"), ict_block("R1", "+1.234567890123E+00")])
    write_ict_log(folder / "VSE002_a_much_longer_file_name_for_run_1.log", "VSE002", [ict_block(long_component, "+4.0E+00"), ict_block("R1", "+2.0E+00")])
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    app._show_step("review")
    grid = app.preview_grid
    assert len(grid.rows()) == 2

    widths = dict(zip(grid.headings(), grid.column_widths(), strict=True))
    pad = 2 * grid._px(grid._padding)
    longest_file = "VSE002_a_much_longer_file_name_for_run_1.log"
    assert grid.text_width(longest_file) <= widths["File"] <= grid.text_width(longest_file) + pad + 2
    assert widths["Serial number"] < 170  # "VSE001" does not get a fixed wide column
    heading = grid.text_width(long_component, heading=True)  # the long heading decides, its values are short
    assert heading <= widths[long_component] <= heading + pad + 8  # (a heading gets a little room to spare)
    longest_value = "+1.234567890123E+00"  # far longer than its heading "R1", so the value decides the width
    assert grid.text_width(longest_value) <= widths["R1"] <= grid.text_width(longest_value) + pad + 2
    assert widths["No."] <= 60 and all(w <= grid._px(grid.MAX_COLUMN_WIDTH) for w in widths.values())


def test_a_column_can_never_grow_past_the_maximum(app, host):
    from datamapperx.ui.controls import Column, DataGrid

    grid = DataGrid(host, app.palette)
    grid.grid(row=0, column=0, sticky="nsew")
    grid.set_table([Column("A"), Column("B")], [("x" * 500, "y")])
    widths = grid.column_widths()
    assert widths[0] == grid._px(grid.MAX_COLUMN_WIDTH) and widths[1] < 80


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


def test_version_and_credit_sit_at_the_bottom_left_of_the_source_card(app):
    from datamapperx.config import APP_CREDIT

    app.update()
    version, credit, card = app.version_label, app.credit_label, app.source_card
    assert credit.cget("text") == APP_CREDIT == "Developed by MAN TRAN"
    assert version.cget("text") == f"Version {__version__}"
    about_y = version.master.winfo_y()
    assert app.details_button.winfo_y() < about_y and version.winfo_y() == credit.winfo_y()  # one line below every control
    assert version.master.winfo_x() <= 16 and version.winfo_x() < credit.winfo_x()  # bottom left: version, then credit
    assert about_y + version.master.winfo_height() >= card.winfo_height() - 20  # pinned to the bottom edge


def test_the_header_keeps_only_the_mode_and_help_buttons_and_no_version(app):
    from tkinter import ttk

    header = app._brand_label.master
    texts = [w.cget("text") for w in header.winfo_children() + app.theme_button.master.winfo_children() if isinstance(w, (ttk.Label, ttk.Button, ttk.Menubutton))]
    assert not any(str(t).startswith("v") and t[1:2].isdigit() for t in texts)  # the version moved to the Source card
    assert app.theme_button.winfo_manager() and app.help_button.cget("text") == "Help"
    labels = [app.help_button["menu"] and app.nametowidget(app.help_button["menu"]).entrycget(i, "label")
              for i in range(app.nametowidget(app.help_button["menu"]).index("end") + 1)
              if app.nametowidget(app.help_button["menu"]).type(i) != "separator"]
    assert labels == ["Check for updates…", "Tell me about new versions", "Keyboard shortcuts", "Open data folder",
                      "Open log file", "About DataMapperX"]


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
    app._show_step("review")
    grid = app.preview_grid
    assert len(grid.rows()) == 2
    assert app.selected_components == names and len(grid.headings()) == 3 + PAGE
    assert app.pager_var.get() == "Columns 1–20 of 45" and app.pager.winfo_manager() == "grid"
    assert str(app.pager_prev.cget("state")) == "disabled" and str(app.pager_next.cget("state")) == "normal"
    assert grid.headings()[3] == "comp_00" and grid.headings()[-1] == "comp_19"
    # the missing value is on the last page, yet the whole selection is still checked for blanks
    assert "all 45 columns" in app.preview_info_var.get()
    assert ("warn", "!  1 empty cell in 1 column") in app.check_chips.chips()

    app._page_preview(1)
    pump(app, lambda: app.pager_var.get() == "Columns 21–40 of 45" and app._preview_job is None)
    assert grid.headings()[3] == "comp_20"
    assert grid.rows()[0][3:5] == ("+20.5E+00", "+21.5E+00")

    app._page_preview(1)
    pump(app, lambda: app.pager_var.get() == "Columns 41–45 of 45" and app._preview_job is None)
    assert len(grid.headings()) == 3 + 5 and str(app.pager_next.cget("state")) == "disabled"
    assert grid.rows()[1][7:8] == ("",)  # comp_44 is blank in the second file
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
    assert app.pager.winfo_manager() == "" and len(grid.headings()) == 3


def test_the_page_resets_for_a_new_scan_and_when_the_selection_shrinks(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    app._show_step("review")
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
    monkeypatch.setattr(main_window, "MainWindow", lambda **_kwargs: app)
    monkeypatch.setattr(app, "destroy", lambda: None)
    sample = selftest._check_logic(tmp_path)
    assert sample.name == "VSE000SMOKE_1.xlsx"
    selftest._check_window(sample)
    with pytest.raises(selftest.SmokeTestError):
        selftest._require(False, "boom")


# ----------------------------------------------------------------------------- the component lists (ActionList)
class _Wheel:
    def __init__(self, delta):
        self.delta = delta


_clock = itertools.count(1_000_000, 10_000)  # synthetic events get far-apart times, so none counts as a double-click


@pytest.fixture
def host(app):
    top = tk.Toplevel(app)
    top.geometry("380x300+80+80")
    top.columnconfigure(0, weight=1)
    top.rowconfigure(0, weight=1)
    yield top
    top.destroy()


def make_list(app, host, **kwargs):
    from datamapperx.ui.controls import ActionList

    calls = {"action": [], "activate": 0, "delete": 0, "select": 0}
    options = {
        "action": "add",
        "on_action": calls["action"].append,
        "on_activate": lambda: calls.__setitem__("activate", calls["activate"] + 1),
        "on_delete": lambda: calls.__setitem__("delete", calls["delete"] + 1),
        "on_select": lambda: calls.__setitem__("select", calls["select"] + 1),
    }
    lst = ActionList(host, app.palette, **{**options, **kwargs})
    lst.grid(row=0, column=0, sticky="nsew")
    app.update()
    return lst, calls


def row_y(lst, index):
    return lst.row_geometry(index)[0] + lst._row_height() // 2


def button_xy(lst, index):
    _top, x1, y1, x2, y2 = lst.row_geometry(index)
    return (x1 + x2) // 2, (y1 + y2) // 2


def press(app, lst, x, y, *, state=0, at=None):
    """A mouse press. Two presses at the same spot less than a double-click time apart (``at``) make a double-click."""
    lst._body.event_generate("<Button-1>", x=x, y=y, state=state, time=next(_clock) if at is None else at)
    app.update()


def drawn_texts(lst):
    canvas = lst._body
    return [canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text"]


def test_a_long_list_draws_only_the_rows_in_view_and_scrolls(app, host):
    lst, _ = make_list(app, host)
    lst.set_items([f"C{i}" for i in range(5000)], values=[("0", "1")] * 5000)
    app.update()
    assert len(lst._body.find_all()) < 300  # a few rows' worth, not 5000 rows' worth
    assert "C0" in drawn_texts(lst) and "C4999" not in drawn_texts(lst)

    lst._yview("scroll", 10, "units")
    app.update()
    assert "C10" in drawn_texts(lst) and "C0" not in drawn_texts(lst)
    lst._yview("moveto", 1.0)
    app.update()
    assert "C4999" in drawn_texts(lst) and lst._offset == lst._max_offset()
    lst._yview("scroll", 3, "pages")  # past the end stays at the end
    assert lst._offset == lst._max_offset()
    lst._yview("moveto", 0.0)
    assert lst._offset == 0 and "C0" in drawn_texts(lst)


def test_the_mouse_wheel_scrolls_by_whole_rows_and_stops_at_both_ends(app, host):
    lst, _ = make_list(app, host)
    lst.set_items([f"C{i}" for i in range(100)])
    lst._on_wheel(_Wheel(-120))
    assert lst._offset == lst.WHEEL_ROWS * lst._row_height()
    lst._on_wheel(_Wheel(120))
    lst._on_wheel(_Wheel(120))
    assert lst._offset == 0
    lst._on_wheel(_Wheel(-120 * 1000))
    assert lst._offset == lst._max_offset()


def test_the_scrollbar_only_shows_when_there_is_something_to_scroll(app, host):
    lst, _ = make_list(app, host)
    lst.set_items(["A", "B", "C"])
    app.update()
    assert lst._scroll.winfo_manager() == ""
    lst.set_items([f"C{i}" for i in range(100)])
    app.update()
    assert lst._scroll.winfo_manager() == "grid"
    lst.set_items(["A"])
    app.update()
    assert lst._scroll.winfo_manager() == ""


def test_clicking_selects_ctrl_toggles_shift_extends_and_empty_space_clears(app, host):
    lst, calls = make_list(app, host)
    lst.set_items([f"C{i}" for i in range(6)])
    app.update()
    press(app, lst, 40, row_y(lst, 1))
    assert lst.selected_indices() == [1] and lst.selected_items() == ["C1"]
    press(app, lst, 40, row_y(lst, 3), state=0x4)  # Ctrl
    assert lst.selected_indices() == [1, 3]
    press(app, lst, 40, row_y(lst, 3), state=0x4)
    assert lst.selected_indices() == [1]
    press(app, lst, 40, row_y(lst, 4))
    press(app, lst, 40, row_y(lst, 2), state=0x1)  # Shift: from the row you last clicked
    assert lst.selected_indices() == [2, 3, 4]
    assert calls["select"] >= 4
    press(app, lst, 40, lst._body.winfo_height() - 2)  # below the last row (6 rows of 40 px do not fill the list)
    assert lst.selected_indices() == []


def test_the_button_at_the_end_of_a_row_acts_on_that_row_only(app, host):
    lst, calls = make_list(app, host)
    lst.set_items(["A", "B", "C"])
    app.update()
    press(app, lst, *button_xy(lst, 2))
    assert calls["action"] == [2] and lst.selected_indices() == []  # a button press does not select the row
    press(app, lst, 40, row_y(lst, 0))  # the name is not a button
    assert calls["action"] == [2]
    x, y = button_xy(lst, 1)
    press(app, lst, x, y, at=5_000_000)
    press(app, lst, x, y, at=5_000_100)  # a double-click on a button counts once, so it never acts on two rows
    assert calls["action"] == [2, 1] and calls["activate"] == 0


def test_double_click_or_enter_on_a_row_activates_the_selection_and_delete_deletes(app, host):
    lst, calls = make_list(app, host)
    lst.set_items(["A", "B"])
    app.update()
    press(app, lst, 40, row_y(lst, 1), at=6_000_000)
    press(app, lst, 40, row_y(lst, 1), at=6_000_100)  # the second press of a double-click
    assert calls["activate"] == 1 and lst.selected_indices() == [1]
    lst._body.focus_force()
    app.update()
    lst._body.event_generate("<Return>")
    lst._body.event_generate("<Delete>")
    app.update()
    assert calls["activate"] == 2 and calls["delete"] == 1


def test_arrow_keys_move_and_shift_extends_ctrl_a_selects_all(app, host):
    lst, _ = make_list(app, host)
    lst.set_items([f"C{i}" for i in range(40)])
    app.update()
    lst._body.focus_force()
    app.update()
    for key in ("<Down>", "<Down>", "<Down>"):
        lst._body.event_generate(key)
    app.update()
    assert lst.selected_indices() == [2]
    lst._body.event_generate("<Shift-Down>")
    lst._body.event_generate("<Shift-Down>")
    app.update()
    assert lst.selected_indices() == [2, 3, 4]
    lst._body.event_generate("<Up>")
    app.update()
    assert lst.selected_indices() == [3]
    lst._body.event_generate("<End>")
    app.update()
    assert lst.selected_indices() == [39] and lst._offset == lst._max_offset()  # scrolled to keep it in view
    lst._body.event_generate("<Home>")
    app.update()
    assert lst.selected_indices() == [0] and lst._offset == 0
    lst._body.event_generate("<Control-a>")
    app.update()
    assert lst.selected_indices() == list(range(40))


def polygons(lst, option):
    canvas = lst._body
    return {canvas.itemcget(i, option) for i in canvas.find_all() if canvas.type(i) == "polygon"}


def test_hovering_a_button_highlights_it_and_a_remove_button_turns_red(app, host):
    add, _ = make_list(app, host)
    add.set_items(["A", "B"])
    app.update()
    x, y = button_xy(add, 1)
    add._body.event_generate("<Motion>", x=x, y=y)
    app.update()
    assert add._hover == 1 and add._hover_button and str(add._body.cget("cursor")) == "hand2"
    assert app.palette.accent in polygons(add, "outline")  # the hovered + gets the accent border
    add._body.event_generate("<Motion>", x=40, y=row_y(add, 0))
    app.update()
    assert add._hover == 0 and not add._hover_button and str(add._body.cget("cursor")) == ""
    assert app.palette.accent not in polygons(add, "outline")
    add._body.event_generate("<Leave>")
    app.update()
    assert add._hover is None

    other = tk.Toplevel(app)
    other.geometry("380x300+500+80")
    other.columnconfigure(0, weight=1)
    other.rowconfigure(0, weight=1)
    try:
        remove, _ = make_list(app, other, action="remove")
        remove.set_items(["A", "B"])
        app.update()
        assert app.palette.danger not in polygons(remove, "outline")  # red only on hover
        x, y = button_xy(remove, 0)
        remove._body.event_generate("<Motion>", x=x, y=y)
        app.update()
        assert app.palette.danger in polygons(remove, "outline") and app.palette.bad_bg in polygons(remove, "fill")
    finally:
        other.destroy()


def test_a_disabled_list_ignores_its_buttons(app, host):
    lst, calls = make_list(app, host)
    lst.set_items(["A", "B"])
    lst.set_enabled(False)
    app.update()
    press(app, lst, *button_xy(lst, 0))
    lst._body.event_generate("<Motion>", x=button_xy(lst, 0)[0], y=button_xy(lst, 0)[1])
    app.update()
    assert calls["action"] == [] and not lst._hover_button and str(lst._body.cget("cursor")) == ""
    press(app, lst, 40, row_y(lst, 0), at=7_000_000)
    press(app, lst, 40, row_y(lst, 0), at=7_000_100)
    assert calls["activate"] == 0
    lst.set_enabled(True)
    press(app, lst, *button_xy(lst, 0))
    assert calls["action"] == [0]


def test_an_empty_list_shows_its_hint_and_long_names_are_shortened(app, host):
    lst, _ = make_list(app, host)
    lst.set_items([], empty_text="Nothing here yet")
    app.update()
    assert drawn_texts(lst) == ["Nothing here yet"]
    long_name = "Aux With Load [3v8], Iout (Load) " * 8
    lst.set_items([long_name], values=[("+0.0000E+00", "+1.0000E+02")])
    app.update()
    shown = [t for t in drawn_texts(lst) if t.startswith("Aux")]
    assert shown and shown[0].endswith("…") and len(shown[0]) < len(long_name)
    assert "Nothing here yet" not in drawn_texts(lst)


def test_refreshing_with_the_same_rows_keeps_selection_and_scroll_but_new_rows_clear_the_selection(app, host):
    lst, calls = make_list(app, host)
    items = [f"C{i}" for i in range(50)]
    lst.set_items(items)
    lst.select_indices([5])
    lst._yview("scroll", 4, "units")
    before, offset = calls["select"], lst._offset
    lst.set_items(list(items))
    assert lst.selected_indices() == [5] and lst._offset == offset and calls["select"] == before
    lst.set_items(items[1:])  # a row left the list: the selection no longer points at the same rows
    assert lst.selected_indices() == [] and calls["select"] == before + 1 and lst._offset == offset
    lst.reset_view()
    assert lst._offset == 0


def test_numbers_value_headings_and_the_theme_are_drawn(app, host):
    import dataclasses

    lst, _ = make_list(app, host, numbered=True, name_heading="Component", value_headings=("Min", "Max"))
    lst.set_items(["A", "B"], values=[("0", "1"), ("2", "3")])
    app.update()
    head = [lst._head.itemcget(i, "text") for i in lst._head.find_all() if lst._head.type(i) == "text"]
    assert sorted(head) == ["Component", "Max", "Min"]
    assert {"1", "2", "A", "B", "0", "3"} <= set(drawn_texts(lst))

    lst.set_palette(dataclasses.replace(app.palette, surface="#123456", soft="#654321"))
    assert lst._body.cget("bg") == "#123456" and lst._head.cget("bg") == "#654321"


def test_an_unknown_action_is_refused(app, host):
    from datamapperx.ui.controls import ActionList

    with pytest.raises(ValueError):
        ActionList(host, app.palette, action="explode", on_action=lambda _i: None)


# ----------------------------------------------------------------------------- the step bar and the check chips
def test_the_step_bar_shows_states_and_ignores_locked_steps(app, host):
    from datamapperx.ui.controls import StepBar

    clicked = []
    bar = StepBar(host, app.palette, ("Select", "Review & Export"), clicked.append)
    bar.grid(row=0, column=0, sticky="new")
    bar.set_step(0, "current", "Folder, profile & components")
    bar.set_step(1, "locked", "Scan first")
    app.update()
    assert (bar.state(0), bar.caption(0), bar.state(1), bar.caption(1)) == (
        "current", "Folder, profile & components", "locked", "Scan first",
    )
    bar.click(1)
    assert clicked == []
    bar.set_step(1, "ready", "Go on")
    bar.click(1)
    bar.click(0)
    assert clicked == [1, 0]
    assert bar._cells[0]["frame"].cget("bg") == app.palette.accent  # the current step is filled
    bar.set_step(0, "complete", "done")
    assert bar._cells[0]["frame"].cget("bg") == app.palette.ok_bg
    bar._cells[1]["title"].event_generate("<Button-1>", x=3, y=3)  # a real click on the text reaches the step
    assert clicked == [1, 0, 1]


def test_check_chips_wrap_when_narrow_and_only_rebuild_on_change(app, host):
    from datamapperx.ui.controls import ChipRow

    row = ChipRow(host, app.palette)
    row.grid(row=0, column=0, sticky="new")
    chips = [
        ("ok", "✓  10 of 10 samples"), ("ok", "✓  3 files per sample"),
        ("warn", "!  20 empty cells in 2 columns"), ("info", "Outside min–max: rows 5, 13"),
    ]
    row.set_chips(chips)
    host.geometry("900x200")
    app.update()
    assert {label.grid_info()["row"] for _l, _t, label in row._chips} == {0}
    labels = [label for _l, _t, label in row._chips]
    host.geometry("330x200")
    app.update()
    assert len({label.grid_info()["row"] for _l, _t, label in row._chips}) >= 2 and row.chips() == chips
    row.set_chips(chips)  # unchanged: the same widgets stay
    assert [label for _l, _t, label in row._chips] == labels
    row.set_chips([("bad", "!  one")])
    assert row.chips() == [("bad", "!  one")] and not labels[0].winfo_exists()
    row.set_chips([])
    assert row.chips() == []


# ----------------------------------------------------------------------------- the two steps in the window
def click_row_button(app, lst, index):
    app.update()
    x, y = button_xy(lst, index)
    lst._body.event_generate("<Button-1>", x=x, y=y, time=next(_clock))
    app.update()


def test_plus_adds_a_component_and_x_removes_it(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    assert app.available_list.items() == ["C1", "R1", "R2"]

    click_row_button(app, app.available_list, 1)  # R1
    assert app.selected_components == ["R1"] and app.available_list.items() == ["C1", "R2"]
    click_row_button(app, app.available_list, 1)  # R2, now second in the list
    assert app.selected_components == ["R1", "R2"]

    click_row_button(app, app.selected_list, 0)  # remove R1
    assert app.selected_components == ["R2"] and app.available_list.items() == ["C1", "R1"]
    assert app.settings.component_sets[app.profile_var.get()] == ["R2"]  # remembered for next time
    assert not hasattr(app, "remove_button")  # the Remove button is gone; × and the Delete key remain

    app.selected_list.select_indices([0])
    app.remove_components()  # what the Delete key does
    assert app.selected_components == []


def test_available_rows_show_min_and_max_and_missing_limits_show_a_dash(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder, repeats=1, components=("R1", "R2"))
    write_ict_log(folder / "VSE009_1.log", "VSE009", [ict_block("NOLIM", "+1.0E+00")])
    scan(app, folder, expected=4, repeats=1)
    values = dict(zip(app.available_list.items(), app.available_list._values, strict=True))
    assert values["R1"] == ("+0.0E+00", "+9.0E+00") and values["NOLIM"] == ("–", "–")
    assert app.limits["R1"]["min"] == "+0.0E+00" and app.limits["R1"]["max"] == "+9.0E+00"
    app.reset_workflow()
    assert app.limits == {} and app.available_list._values == []


def pages(app):
    """Which step's page is laid out: (select page, review page), each "grid" or "" (hidden)."""
    return app.select_page.winfo_manager(), app.review_page.winfo_manager()


def test_the_review_step_is_locked_until_there_is_something_to_review(app, tmp_path):
    bar = app.step_bar
    assert (bar.state(0), bar.state(1)) == ("current", "locked") and "Scan" in bar.caption(1)
    app._show_step("review")
    assert app.step == "select" and "Scan a folder" in app.status_var.get()
    bar.click(1)
    assert app.step == "select"

    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder)
    scan(app, folder)
    assert bar.state(1) == "locked" and app.review_button.instate(["disabled"])
    app.add_all_shown()
    assert bar.state(1) == "ready" and app.review_button.instate(["!disabled"])

    app.review_button.invoke()
    app.update()
    assert app.step == "review" and pages(app) == ("", "grid")
    assert (bar.state(0), bar.caption(0), bar.state(1)) == ("complete", "3 components selected", "current")
    app.back_button.invoke()
    app.update()
    assert app.step == "select" and pages(app) == ("grid", "")
    assert (bar.state(0), bar.state(1)) == ("current", "ready")
    bar.click(1)
    assert app.step == "review"
    bar.click(0)
    assert app.step == "select"


def test_ctrl_e_goes_to_the_review_first_and_exports_from_there(app, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, folder)
    exported = []
    monkeypatch.setattr(app, "export_excel", lambda: exported.append(True))
    app._export_shortcut()
    assert app.step == "review" and exported == []
    app._export_shortcut()
    assert exported == [True]
    app._set_busy(True)
    try:
        app._export_shortcut()
        assert exported == [True]  # nothing while a task runs
    finally:
        app._set_busy(False)


def test_a_new_scan_or_a_reset_returns_to_the_first_step(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    ready_to_review(app, folder)
    app._show_step("review")
    scan(app, folder)
    assert app.step == "select" and pages(app) == ("grid", "")
    app._show_step("review")
    assert app.step == "review"
    app.reset_workflow()
    assert app.step == "select" and app.step_bar.state(1) == "locked"
    assert app.preview_grid.rows() == []  # the old rows are gone as well


def limit_logs(folder):
    """VSE001..3 x 2 files, limits 0..9. R1 is too high in VSE001_1 and too low in VSE003_2; R2 is missing in VSE002_1."""
    for sn in ("VSE001", "VSE002", "VSE003"):
        for run in (1, 2):
            r1 = {("VSE001", 1): "+12.0E+00", ("VSE003", 2): "-1.0E+00"}.get((sn, run), "+5.0E+00")
            blocks = [ict_block("R1", r1, "+9.0E+00", "+0.0E+00")]
            if (sn, run) != ("VSE002", 1):
                blocks.append(ict_block("R2", "+3.0E+00", "+9.0E+00", "+0.0E+00"))
            write_ict_log(folder / f"{sn}_{run}.log", sn, blocks)


def limits_rows(app):
    grid = app.limits_grid
    return list(zip(grid.rows(), grid.tags(), strict=True))


def test_the_review_compares_the_clicked_row_with_the_limits(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    scan(app, folder, expected=3, repeats=2)
    app.add_all_shown()
    app._show_step("review")
    unit = app.limits["R1"]["unit"]

    assert app.limits_title_var.get() == "Limits (2)"
    assert app.review_row_var.get() == "Row 1   ·   VSE001   ·   VSE001_1.log"
    first = limits_rows(app)
    assert first[0] == (("R1", "+12.0E+00 ▲", "+0.0E+00", "+9.0E+00", unit), "out")
    assert first[1][0][:2] == ("R2", "+3.0E+00") and first[1][1] == ""

    app.preview_grid.select(2)  # VSE002_1: R2 is missing
    assert app._review_row == 2
    row = limits_rows(app)
    assert row[0][0][1] == "+5.0E+00" and row[0][1] == ""
    assert row[1][0][1] == "–" and row[1][1] == "gap"
    assert app.review_row_var.get() == "Row 3   ·   VSE002   ·   VSE002_1.log"

    app.preview_grid.select(5)  # VSE003_2: R1 below its minimum
    assert app._review_row == 5
    assert limits_rows(app)[0][0][1] == "-1.0E+00 ▼" and limits_rows(app)[0][1] == "out"
    assert ("info", "Outside min–max: rows 1, 6") in app.check_chips.chips()

    app._show_step("select")
    app._show_step("review")  # coming back keeps the row you were looking at
    assert app._review_row == 5 and app.preview_grid.selected_index() == 5


def row_fills(grid):
    """The background colours of the rows currently drawn."""
    canvas = grid._body
    return {canvas.itemcget(i, "fill") for i in canvas.find_all() if canvas.type(i) == "rectangle"}


def grr_logs(folder):
    for part in range(3):
        for repeat in range(3):
            value = f"+{3 * part + repeat + 1}.0E+00"
            sn = f"VSE{part:03d}"
            write_ict_log(folder / f"{sn}_{repeat}.log", sn, [
                ict_block("X", value, "+2.0E+01", "+0.0E+00"),
                ict_block("Y", value, "+1.0E+02", "+0.0E+00"),
            ])


def test_grr_precheck_shows_independent_statuses_and_colors_before_export(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, folder, repeats=3)
    app.add_all_shown()
    app._show_step("review")
    app.update()
    assert app.review_side_tabs.select() == str(app.grr_page)
    assert app.grr_grid.rows() == [
        ("X", "32.16", "30.00", "4", "FAIL"),
        ("Y", "32.16", "6.00", "4", "FAIL"),
    ]
    assert app.grr_grid.cell_tags() == {  # %SV/Tol is shown but does not decide, nor is it coloured, by default
        (0, 1): "fail", (0, 2): "neutral", (0, 3): "fail", (0, 4): "fail",
        (1, 1): "fail", (1, 2): "neutral", (1, 3): "fail", (1, 4): "fail",
    }
    assert app.grr_summary_var.get() == "2 test items · not applied: %SV/Tol"
    from dataclasses import replace as replace_criterion

    defaults = app.grr_criteria
    app._set_grr_criteria(tuple(replace_criterion(c, enabled=True) for c in defaults))
    try:
        assert app.grr_grid.cell_tags() == {
            (0, 1): "fail", (0, 2): "caution", (0, 3): "fail", (0, 4): "fail",
            (1, 1): "fail", (1, 2): "pass", (1, 3): "fail", (1, 4): "fail",
        }
        assert app.grr_summary_var.get() == "2 test items"
        assert "Study Var (6 × SD): 6.00" in app.grr_detail_var.get()
        assert app.export_button.instate(["!disabled"])
        app.preview_grid._body.event_generate("<Button-1>", x=10, y=app.preview_grid._row_height() // 2)
        app.update()
        assert app.review_side_tabs.select() == str(app.limits_page)  # row 0 was already selected
        app.review_side_tabs.select(app.grr_page)
        for dark in (True, False):
            app.dark_var.set(dark)
            app._on_theme_toggle()
            app.grr_grid.select(1)
            app.update()
            assert {app.palette.bad_bg, app.palette.warn_bg, app.palette.ok_bg} <= row_fills(app.grr_grid)
        app.preview_grid.select(1)
        assert app.review_side_tabs.select() == str(app.limits_page)
    finally:
        app._set_grr_criteria(defaults)  # the window is shared by the other tests


def test_grr_precheck_recalculates_after_duplicate_choices_counts_and_reset(app, tmp_path):
    from dataclasses import replace

    folder = tmp_path / "logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, folder, repeats=3)
    app.add_all_shown()
    app._show_step("review")
    first = app.scan_result.grouped["VSE000"][0]
    first.entries["X"] = replace(first.entries["X"], measured="PASS")
    app._on_duplicates_reviewed({"X"}, True)
    pump(app, lambda: app._preview_job is None)
    assert app.grr_grid.rows()[0] == ("X", "N/A", "N/A", "N/A", "N/A")  # nothing to judge: the result is N/A, not a pass
    assert first.filename in app.grr_detail_var.get()
    assert app._grr_results[1].percent_tolerance == pytest.approx(6)
    app.repeats_var.set("4")
    pump(app, lambda: app._preview_job is None)
    assert all(row[1:] == ("N/A", "N/A", "N/A", "N/A") for row in app.grr_grid.rows())
    assert "needs 4 repeated files" in app.grr_detail_var.get()
    app.reset_workflow()
    assert app.grr_grid.rows() == [] and app.grr_summary_var.get() == ""


def test_grr_precheck_ndc_colors_and_compact_legend(app, tmp_path):
    from dataclasses import replace

    folder = tmp_path / "ndc_logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, folder, repeats=3)
    for part, records in enumerate(app.scan_result.grouped.values()):
        for record in records:
            entry = record.entries["Y"]
            record.entries["Y"] = replace(entry, measured=str(float(entry.measured) + part * 100))
    app.add_all_shown()
    app._show_step("review")
    app.update()
    assert [column.title for column in app.grr_grid._columns] == ["Test", "%Study Var", "%SV/Tol", "NDC", "Result"]
    assert app._grr_results[0].ndc < 5 <= app._grr_results[1].ndc
    assert app.grr_grid.cell_tags()[0, 3] == "fail"
    assert app.grr_grid.cell_tags()[1, 3] == "pass"
    assert [label.cget("text") for _, label, _ in app.grr_legend_tiles] == ["PASS", "CONDITION", "FAIL"]
    assert not hasattr(app, "_grr_legend_text") and len({tile.grid_info()["row"] for tile, *_ in app.grr_legend_tiles}) == 1  # one row
    previous_geometry = app.geometry()
    app.geometry("1000x680+0+0")
    try:
        for dark in (True, False):
            app.dark_var.set(dark)
            app._on_theme_toggle()
            app.update()
            assert app.grr_grid._max_xoff() == 0  # all five columns fit the narrow panel
            assert [tile.cget("bg") for tile, *_ in app.grr_legend_tiles] == [
                app.palette.ok_bg, app.palette.warn_bg, app.palette.bad_bg,
            ]
            for tile, title, _ in app.grr_legend_tiles:
                assert inside(app, tile)
                assert title.cget("bg") == tile.cget("bg")
    finally:
        app.geometry(previous_geometry)


def test_the_tables_tint_rows_with_missing_values_and_wrong_file_counts(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    write_ict_log(folder / "VSE004_1.log", "VSE004", [ict_block("R1", "+1.0E+00", "+9.0E+00", "+0.0E+00"), ict_block("R2", "+1.0E+00")])
    scan(app, folder, expected=4, repeats=2)
    app.add_all_shown()
    app._show_step("review")
    grid = app.preview_grid
    assert grid.tags() == ["", "", "missing", "", "", "", "invalid"]
    app.update()
    assert {app.palette.warn_bg, app.palette.bad_bg} <= row_fills(grid)  # the tinted rows are drawn in the tint colours
    app.dark_var.set(True)
    app._on_theme_toggle()
    app.review_side_tabs.select(app.limits_page)
    app.update()
    try:
        assert {app.palette.warn_bg, app.palette.bad_bg} <= row_fills(grid)  # recoloured with the theme
        assert app.palette.mode == "dark" and app.palette.bad_bg in row_fills(app.limits_grid)  # R1 is out of limits in row 1
    finally:
        app.dark_var.set(False)
        app._on_theme_toggle()


def test_the_checks_beside_the_export_button_summarise_the_data(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    scan(app, folder, expected=4, repeats=2)  # one sample short
    app.add_all_shown()
    app._show_step("review")
    assert app.check_chips.chips() == [
        ("warn", "!  3 of 4 samples. You will be asked to confirm"),
        ("ok", "✓  2 files per sample"),
        ("warn", "!  1 empty cell in 1 column"),
        ("info", "Outside min–max: rows 1, 6"),
    ]
    assert app.export_button.instate(["!disabled"])

    app.expected_var.set("3")
    app._refresh_checks()
    assert app.check_chips.chips()[0] == ("ok", "✓  3 of 3 samples")

    app.clear_selected()
    pump(app, lambda: app._preview_job is None)
    assert app.check_chips.chips() == []  # nothing selected, nothing to check


def test_export_is_blocked_on_the_review_while_a_sample_has_the_wrong_number_of_files(app, tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    make_logs(folder, sns=("VSE001", "VSE002"), repeats=2)
    write_ict_log(folder / "VSE003_1.log", "VSE003", [ict_block("R1", "+1.0E+00")])
    scan(app, folder, expected=3, repeats=2)
    app.add_all_shown()
    assert app.step_bar.state(1) == "warn" and "Fix" in app.step_bar.caption(1)  # visible before even going there
    app._show_step("review")
    assert ("bad", "!  VSE003 has 1 files, not 2. Export is blocked") in app.check_chips.chips()
    assert app.export_button.instate(["disabled"]) and app.step_bar.state(1) == "current"
    assert "Fix the file count" in app.step_bar.caption(1)
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: pytest.fail("blocked"))
    app.export_excel()  # still refuses if called some other way
    assert any("exactly 2 files" in message for _kind, message in app.shown)

    write_ict_log(folder / "VSE004_1.log", "VSE004", [ict_block("R1", "+1.0E+00")])
    scan(app, folder, expected=4, repeats=2)
    app._show_step("review")
    assert any(text.startswith("!  2 samples do not have 2 files (VSE003, VSE004…)") for _l, text in app.check_chips.chips())


def test_the_chosen_row_survives_paging_and_the_limits_cover_every_column(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    names = make_wide_logs(folder)
    scan(app, folder, expected=2, repeats=1)
    app.add_all_shown()
    app._show_step("review")
    app.preview_grid.select(1)
    assert app._review_row == 1
    assert app.limits_title_var.get() == "Limits (45)" and len(app.limits_grid.rows()) == 45
    app._page_preview(1)
    pump(app, lambda: app.pager_var.get() == "Columns 21–40 of 45" and app._preview_job is None)
    assert app._review_row == 1 and app.preview_grid.selected_index() == 1
    limits = app.limits_grid.rows()
    assert len(limits) == 45  # every selected column, not just the page
    assert limits[44][1] == "–"  # comp_44 is blank in the second file
    assert limits[0][0] == names[0]


def test_the_limit_columns_are_wide_enough_for_the_numbers(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    write_ict_log(folder / "VSE001_1.log", "VSE001", [ict_block("R1", "+1.2345678E+03", "+9.876543E+12", "-1.234567E-03")])
    scan(app, folder, expected=1, repeats=1)
    app.add_all_shown()
    app._show_step("review")
    grid = app.limits_grid
    width = dict(zip(grid.headings(), grid.column_widths(), strict=True))
    assert app.limits["R1"]["max"] == "+9.876543E+12" and app.limits["R1"]["min"] == "-1.234567E-03"
    assert width["Min"] >= grid.text_width("-1.234567E-03") and width["Max"] >= grid.text_width("+9.876543E+12")
    assert width["Value"] >= grid.text_width("+9.876543E+12 ▲")  # room for the mark
    assert width["Value"] >= grid.text_width("+000.0000E+00 ▲") + 2 * grid._px(grid._padding)  # and for a longer value
    app.update()
    drawn = [grid._body.itemcget(i, "text") for i in grid._body.find_all() if grid._body.type(i) == "text"]
    assert "+9.876543E+12" in drawn and "-1.234567E-03" in drawn  # not shortened with …


def test_the_mode_button_switches_the_theme_and_changes_its_label(app):
    app.dark_var.set(False)
    app._on_theme_toggle()
    assert app.theme_text_var.get() == "☾  Dark mode"
    app.theme_button.invoke()
    assert app.dark_var.get() and app.palette.mode == "dark" and app.theme_text_var.get() == "☀  Light mode"
    assert app.settings.theme == "dark"
    app.theme_button.invoke()
    assert not app.dark_var.get() and app.palette.mode == "light" and app.theme_text_var.get() == "☾  Dark mode"


def test_every_button_uses_the_one_shared_style(app):
    """Only the theme's own button, its filled Accent version and the square Icon version are used anywhere."""
    from tkinter import ttk

    allowed = {"TButton", "Accent.TButton", "Icon.TButton", "TMenubutton"}
    seen: set[str] = set()

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Button, ttk.Menubutton)):
                seen.add(str(child.cget("style")) or child.winfo_class())
            walk(child)

    walk(app)
    assert seen <= allowed, seen - allowed
    assert {"Accent.TButton", "Icon.TButton"} <= seen


def test_a_big_scan_keeps_the_lists_and_the_review_quick(app):
    """2000 components x 300 rows: the lists draw only what is in view and the review builds in well under a second."""
    from pathlib import Path

    from datamapperx.exporter import summarize_limits
    from datamapperx.models import LogRecord, Measurement, ScanDiagnostics, ScanResult

    names = [f"comp_{i:04d}" for i in range(2000)]
    grouped = {
        f"SN{n:03d}": [LogRecord(Path(f"SN{n:03d}.log"), f"SN{n:03d}", {c: Measurement(c, "5", "0", "9", "V") for c in names})]
        for n in range(300)
    }
    app.scan_result = ScanResult(grouped, names, [], [], ScanDiagnostics("text", (".log",)))
    app.limits = summarize_limits(grouped, names)
    app.expected_var.set("300")
    app.repeats_var.set("1")

    start = time.perf_counter()
    app._refresh_lists()
    lists = time.perf_counter() - start
    assert len(app.available_list.items()) == 2000 and len(app.available_list._body.find_all()) < 400
    assert lists < 1.0, f"{lists:.2f}s"

    app.available_list._yview("scroll", 30, "units")
    app.search_var.set("comp_00")  # a new filter starts again from the top
    assert app.available_list._offset == 0 and len(app.available_list.items()) == 100

    start = time.perf_counter()
    for name in names[:100]:
        app._add([name])
    adding = time.perf_counter() - start
    assert len(app.selected_components) == 100 and adding < 6.0, f"{adding:.2f}s"  # each add redraws both lists

    start = time.perf_counter()
    app._show_step("review")
    app.update()
    review = time.perf_counter() - start
    assert len(app.preview_grid.rows()) == 300 and len(app.limits_grid.rows()) == 100
    assert review < 3.0, f"{review:.2f}s"
    app.reset_workflow()


def test_the_list_scales_its_rows_and_buttons_with_the_display(app, host):
    lst, calls = make_list(app, host)
    lst._scale = 2.0  # a 200 % display
    lst.set_items(["A", "B", "C"])
    app.update()
    assert lst._row_height() == 2 * lst.ROW_HEIGHT
    top, x1, y1, x2, y2 = lst.row_geometry(1)
    assert top == lst._row_height() and x2 - x1 == y2 - y1 == 2 * lst.BUTTON_SIZE
    press(app, lst, (x1 + x2) // 2, (y1 + y2) // 2)  # the bigger button is still what a click hits
    assert calls["action"] == [1]
    assert lst._locate(40, lst._row_height() + 5) == (1, False)


# ----------------------------------------------------------------------------- the review table (DataGrid)
def make_grid(app, host, **kwargs):
    from datamapperx.ui.controls import DataGrid

    picked: list[int] = []
    grid = DataGrid(host, app.palette, on_select=picked.append, **kwargs)
    grid.grid(row=0, column=0, sticky="nsew")
    app.update()
    return grid, picked


def grid_texts(grid, canvas=None):
    canvas = canvas or grid._body
    return [canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text"]


def grid_row_y(grid, index):
    return index * grid._row_height() - grid._yoff + grid._row_height() // 2


def wide_table(rows=5000, columns=60):
    from datamapperx.ui.controls import Column

    headings = [Column("No.", "center"), Column("Serial number")] + [Column(f"comp_{c:02d}", "e") for c in range(columns)]
    return headings, [(r + 1, f"SN{r:05d}", *(f"+{r}.{c}E+00" for c in range(columns))) for r in range(rows)]


def test_a_grid_draws_only_the_rows_and_columns_in_view_and_scrolls_both_ways(app, host):
    grid, _ = make_grid(app, host)
    columns, rows = wide_table()
    grid.set_table(columns, rows)
    app.update()
    assert len(grid._body.find_all()) < 400  # a window's worth of cells, not 5000 x 62
    assert "SN00000" in grid_texts(grid) and "SN04999" not in grid_texts(grid)
    assert "comp_00" in grid_texts(grid, grid._head) and "comp_59" not in grid_texts(grid, grid._head)

    grid._yview("scroll", 100, "units")
    app.update()
    assert "SN00100" in grid_texts(grid) and "SN00000" not in grid_texts(grid)
    grid._yview("moveto", 1.0)
    app.update()
    assert "SN04999" in grid_texts(grid) and grid._yoff == grid._max_yoff()
    grid._yview("scroll", 5, "pages")  # past the end stays at the end
    assert grid._yoff == grid._max_yoff()

    grid._xview("moveto", 1.0)
    app.update()
    assert "comp_59" in grid_texts(grid, grid._head) and "comp_00" not in grid_texts(grid, grid._head)
    assert grid._xoff == grid._max_xoff() > 0
    grid.reset_view()
    app.update()
    assert grid._yoff == grid._xoff == 0 and "comp_00" in grid_texts(grid, grid._head)


def test_a_fast_wheel_is_drawn_once_per_idle_moment_so_the_table_never_lags_behind(app, host):
    grid, _ = make_grid(app, host)
    columns, rows = wide_table(rows=2000, columns=10)
    grid.set_table(columns, rows)
    app.update()
    redraws = []
    original = grid._redraw_body
    grid._redraw_body = lambda: (redraws.append(1), original())
    for _ in range(60):  # a wheel spun fast: many events before Tk gets to draw anything
        grid._on_wheel(_Wheel(-120))
    assert grid._yoff == 60 * grid.WHEEL_ROWS * grid._row_height()  # every notch counted...
    app.update()
    assert len(redraws) == 1 and "SN00180" in grid_texts(grid)  # ...and drawn together
    grid._on_wheel(_Wheel(120 * 1000))
    app.update()
    assert grid._yoff == 0 and "SN00000" in grid_texts(grid)
    grid._on_shift_wheel(_Wheel(-120))  # Shift + wheel scrolls sideways
    app.update()
    assert grid._xoff > 0


def test_clicking_a_row_selects_it_once_and_the_keyboard_moves_the_selection(app, host):
    grid, picked = make_grid(app, host)
    columns, rows = wide_table(rows=100, columns=3)
    grid.set_table(columns, rows)
    app.update()
    grid._body.event_generate("<Button-1>", x=20, y=grid_row_y(grid, 2), time=next(_clock))
    app.update()
    assert grid.selected_index() == 2 and picked == [2]
    grid._body.event_generate("<Button-1>", x=20, y=grid_row_y(grid, 2), time=next(_clock))
    assert picked == [2]  # the same row again is not a change
    grid.select(5, notify=False)
    assert grid.selected_index() == 5 and picked == [2]  # code can move the selection quietly

    grid._body.focus_force()
    app.update()
    for key in ("<Down>", "<Down>", "<Up>"):
        grid._body.event_generate(key)
    app.update()
    assert grid.selected_index() == 6 and picked[-1] == 6
    grid._body.event_generate("<End>")
    app.update()
    assert grid.selected_index() == 99 and grid._yoff == grid._max_yoff()  # scrolled to keep it in view
    grid._body.event_generate("<Home>")
    app.update()
    assert grid.selected_index() == 0 and grid._yoff == 0
    grid._body.event_generate("<Next>")
    app.update()
    assert grid.selected_index() == grid._page_rows()
    grid._body.event_generate("<Right>")
    grid._body.event_generate("<Right>")
    app.update()
    assert 0 < grid._xoff <= 2 * grid._px(grid.HORIZONTAL_STEP)  # the arrows also scroll sideways (a little here)
    grid.select(None)
    assert grid.selected_index() is None
    grid.select(10_000)  # no such row
    assert grid.selected_index() is None

    grid.set_table(columns, rows[:3])
    grid.select(1, notify=False)
    app.update()
    grid._body.event_generate("<Button-1>", x=20, y=grid._view()[1] - 5, time=next(_clock))  # below the last row
    assert grid.selected_index() == 1


def test_tagged_rows_are_tinted_and_the_selected_row_wins(app, host):
    grid, _ = make_grid(app, host)
    grid.set_table(wide_table(rows=4, columns=1)[0], wide_table(rows=4, columns=1)[1], ["", "missing", "invalid", "out"])
    app.update()
    p = app.palette
    assert {p.warn_bg, p.bad_bg} <= row_fills(grid) and p.pick not in row_fills(grid)
    ink = {grid._body.itemcget(i, "fill") for i in grid._body.find_all() if grid._body.type(i) == "text"}
    assert p.danger in ink and p.fg in ink  # red rows get red text, the others the normal text colour
    grid.select(1, notify=False)  # a tinted row that is selected shows the selection colour
    app.update()
    assert p.pick in row_fills(grid)
    grid.set_palette(__import__("dataclasses").replace(p, pick="#010203", warn_bg="#0a0b0c"))
    app.update()
    assert {"#010203"} <= row_fills(grid) and "#0a0b0c" not in row_fills(grid)  # the selected row is not amber


def test_stretching_columns_fill_a_wide_window_and_a_narrow_one_scrolls(app, host):
    from datamapperx.ui.controls import Column

    grid, _ = make_grid(app, host)
    grid.set_table([Column("Component", width=90, stretch=True), Column("Value", "e", width=100)], [("a", "1")])
    app.update()
    viewport = grid._view()[0]
    widths = grid._effective_widths(viewport)
    assert sum(widths) == viewport and widths[1] == 100 and widths[0] == viewport - 100  # no empty gap, no sideways scroll
    assert grid._max_xoff() == 0
    host.geometry("120x300")
    app.update()
    assert sum(grid._effective_widths(grid._view()[0])) == 190 and grid._max_xoff() > 0  # too narrow: scrolls instead


def test_long_text_ends_in_an_ellipsis_and_blank_cells_stay_blank(app, host):
    from datamapperx.ui.controls import Column

    grid, _ = make_grid(app, host)
    grid.set_table([Column("Name", width=120), Column("Other", width=80)], [("x" * 100, None), ("short", "ok")])
    app.update()
    texts = grid_texts(grid)
    shortened = [t for t in texts if t.startswith("xxx")]
    assert shortened and shortened[0].endswith("…") and "short" in texts and "ok" in texts
    assert grid.rows() == [("x" * 100, ""), ("short", "ok")]  # None is stored as an empty cell
    assert "" not in texts  # and nothing is drawn for it
    with pytest.raises(ValueError):
        grid.set_table([Column("A")], [("1",), ("2",)], ["only one tag"])


def test_a_table_with_no_rows_shows_its_hint_and_new_columns_start_from_the_left(app, host):
    from datamapperx.ui.controls import Column

    grid, _ = make_grid(app, host)
    grid.set_table([Column("A")], [], empty_text="Nothing to review yet")
    app.update()
    assert grid_texts(grid) == ["Nothing to review yet"] and grid.headings() == ["A"]

    columns, rows = wide_table(rows=20, columns=40)
    grid.set_table(columns, rows)
    grid._xview("moveto", 1.0)
    app.update()
    assert grid._xoff > 0 and "Nothing to review yet" not in grid_texts(grid)
    grid.set_table(columns, rows[:10])  # the same columns, fewer rows: the sideways position stays
    assert grid._xoff > 0
    grid.set_table(columns[:5], [r[:5] for r in rows])  # other columns: back to the left edge
    assert grid._xoff == 0 and grid.headings() == ["No.", "Serial number", "comp_00", "comp_01", "comp_02"]
    grid.select(15, notify=False)
    grid.set_table(columns[:5], [r[:5] for r in rows[:5]])
    assert grid.selected_index() is None  # the selected row no longer exists


def test_scrolling_down_does_not_touch_the_sideways_scrollbar(app, host):
    """A themed scrollbar repaints every time it is told something, even the same thing; that was 15 ms a step."""
    grid, _ = make_grid(app, host)
    columns, rows = wide_table(rows=500, columns=30)
    grid.set_table(columns, rows)
    app.update()
    told = {"v": 0, "h": 0}
    for name, bar in (("v", grid._vscroll), ("h", grid._hscroll)):
        original = bar.set
        bar.set = lambda *a, _n=name, _o=original: (told.__setitem__(_n, told[_n] + 1), _o(*a))
    for _ in range(5):
        grid._on_wheel(_Wheel(-120))
        app.update()
    assert told["v"] == 5 and told["h"] == 0
    grid._xview("scroll", 1, "units")
    app.update()
    assert told["h"] == 1


def test_a_big_table_scrolls_many_times_faster_than_a_themed_treeview_can(app, host):
    grid, _ = make_grid(app, host)
    columns, rows = wide_table(rows=500, columns=20)
    grid.set_table(columns[:23], [r[:23] for r in rows])
    app.update()
    start = time.perf_counter()
    for _ in range(20):
        grid._on_wheel(_Wheel(-120))
        app.update()
    per_notch = (time.perf_counter() - start) / 20
    assert per_notch < 0.08, f"{per_notch * 1000:.0f} ms per wheel notch"  # the Treeview took 120-155 ms


def test_clicking_a_row_of_the_review_table_shows_that_rows_limits(app, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    limit_logs(folder)
    scan(app, folder, expected=3, repeats=2)
    app.add_all_shown()
    app._show_step("review")
    app.update()
    grid = app.preview_grid
    assert app._review_row == 0 and "VSE001_1.log" in app.review_row_var.get()
    grid._body.event_generate("<Button-1>", x=30, y=grid_row_y(grid, 5), time=next(_clock))
    app.update()
    assert app._review_row == 5 and "VSE003_2.log" in app.review_row_var.get()
    assert limits_rows(app)[0][0][1] == "-1.0E+00 ▼"  # the clicked row's value, judged against its limits
    grid._body.event_generate("<Button-1>", x=30, y=grid_row_y(grid, 0), time=next(_clock))
    app.update()
    assert limits_rows(app)[0][0][1] == "+12.0E+00 ▲"
    app.limits_grid._on_wheel(_Wheel(-120))  # the limits panel scrolls too (nothing to scroll with 2 rows, but no error)
    app.update()


def test_the_smoke_test_can_run_again_with_a_remembered_choice_in_the_data_folder(app, tmp_path):
    """The build script reuses one data folder, so a second run finds what the first one saved."""
    from datamapperx import selftest

    selftest._check_logic(tmp_path)
    dark_before = app.dark_var.get()
    selftest._check_steps(app, tmp_path)
    assert app.settings.component_sets  # the first run left its choice behind
    selftest._check_steps(app, tmp_path)  # and the second must still pass
    assert app.dark_var.get() == dark_before and app.palette.mode == ("dark" if dark_before else "light")

# ----------------------------------------------------------------------------- Validation & Reports workspace
def showing(app, widget, expected=True):
    """Whether the widget ends up on screen (or off it, with ``expected=False``); Tk maps and unmaps a moment later."""
    end = time.time() + 3
    while widget.winfo_ismapped() != expected and time.time() < end:
        app.update()
        time.sleep(0.01)
    return widget.winfo_ismapped() == expected


def open_validation(app):
    """The workspace on a clean slate (the window is shared by every test in this module), with its data ready."""
    app._show_workspace("validation")
    ws = app.validation
    for variable, value in ((ws.source_var, "mapping"), (ws.method_var, "grr"), (ws.study_factor_var, "6"),
                            (ws.assign_var, True), (ws.order_var, "Worksheet order"), (ws.index_var, "cpk"),
                            (ws.threshold_var, "1.33"), (ws.subgroup_var, False), (ws.profile_var, "None (statistics only)"),
                            (ws.precision_var, "3"), (ws.search_var, ""), (ws.filter_var, "All results"), (ws.gage_var, ""),
                            (ws.judge_var, False),
                            (ws.by_var, ""), (ws.comments_var, ""), (ws.within_var, "Automatic (from the subgroup size)"), (ws.repeats_var, "")):
        variable.set(value)
    for name, variable in ws.sections.items():
        variable.set(name == "charts")
    ws.assignments.clear()
    ws.acknowledgements = {}
    ws.study = ws.result_set = ws.evaluated = None  # nothing left over from an earlier test
    ws._source_key = object()
    ws.on_show()
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    return ws


def run_validation(app, ws):
    ws.run_button.invoke()
    pump(app, lambda: not ws.running and ws.result_set is not None and not ws.stale)
    return ws


def test_validation_is_a_workspace_beside_data_mapping_and_leaves_the_raw_export_alone(app, tmp_path):
    from dataclasses import asdict

    folder = tmp_path / "stat_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    app._show_step("review")
    before = {str(r.path): asdict(r) for records in app.scan_result.grouped.values() for r in records}
    assert app.validate_button.instate(["!disabled"]) and app.export_button.instate(["!disabled"])
    app.validate_button.invoke()
    app.update()
    assert app.workspace == "validation" and showing(app, app.validation_page) and showing(app, app.review_page, False)
    assert showing(app, app.step_bar, False) and showing(app, app.mapping_switch)
    ws = open_validation(app)
    assert [ws.tabs.tab(t, "state") for t in (ws.data_tab, ws.setup_tab, ws.results_tab, ws.report_tab)] == [
        "normal", "normal", "disabled", "disabled"]  # the tabs open up as the work progresses
    assert all(part in ws.dataset_var.get() for part in ("Test Items 3", "Samples 3", "Total Readings 18", "Trials per Sample 2"))
    run_validation(app, ws)  # Quick Analysis: no trial step, no setup needed
    assert ws.tabs.index(ws.tabs.select()) == ws.tabs.index(ws.results_tab)
    assert len(ws.results) == 3 and all("ndc" in r.metrics for r in ws.results)
    assert len(ws.table.get_children()) == 3 and "3 items" in ws.summary_var.get()
    assert ws.tabs.tab(ws.report_tab, "state") == "normal" and ws.pdf_button.instate(["!disabled"])
    assert before == {str(r.path): asdict(r) for records in app.scan_result.grouped.values() for r in records}
    app.mapping_switch.invoke()
    app.update()
    assert app.workspace == "mapping" and app.step == "review", (app.workspace, app.step)
    assert showing(app, app.review_page) and showing(app, app.step_bar)
    assert app.export_button.instate(["!disabled"])  # Excel export never depends on validation


def test_validation_opens_with_nothing_scanned_and_data_mapping_keeps_working(app):
    ws = open_validation_without_data(app)
    assert ws.dataset is None and ws.run_button.instate(["disabled"])
    assert "No Data Mapping results" in ws.message_var.get()
    assert [ws.tabs.tab(t, "state") for t in (ws.setup_tab, ws.results_tab, ws.report_tab)] == ["disabled"] * 3
    app.mapping_switch.invoke()
    app.update()
    assert app.workspace == "mapping" and showing(app, app.select_page)


def open_validation_without_data(app):
    app._show_workspace("validation")
    ws = app.validation
    ws.source_var.set("mapping")
    ws.on_show()
    pump(app, lambda: not ws.busy)
    return ws


def test_changing_the_study_makes_results_stale_but_changing_criteria_or_decimals_does_not(app, tmp_path):
    folder = tmp_path / "stale_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    run_validation(app, ws)
    app.update()
    assert showing(app, ws.stale_banner, False) and ws.pdf_button.instate(["!disabled"])
    first = ws.result_set
    ws.profile_var.set("Jabil")  # a different customer judges the same numbers
    ws.precision_var.set("5")
    app.update()
    assert ws.result_set is first and not ws.stale and showing(app, ws.stale_banner, False)
    assert ws.results[0].config.profile == "Jabil" or ws.evaluated.record.settings.profile == "Jabil"
    ws.assign_var.set(False)  # numbering the repeated readings changes what is computed
    app.update()
    assert ws.stale and showing(app, ws.stale_banner)
    ws.assign_var.set(True)  # back to what the results were computed from: current again
    app.update()
    assert not ws.stale and showing(app, ws.stale_banner, False)
    ws.assign_var.set(False)
    app.update()
    assert ws.stale
    assert ws.pdf_button.instate(["disabled"]) and ws.excel_button.instate(["disabled"])
    assert "Update the results" in ws.report_var.get()
    assert len(ws.table.get_children()) == 3  # the old results stay on screen, for reference
    ws.update_button.invoke()
    pump(app, lambda: not ws.running and not ws.stale)
    app.update()
    assert ws.result_set is not first and ws.result_set.id == "RS-0002" and showing(app, ws.stale_banner, False)
    assert ws.pdf_button.instate(["!disabled"]) and ws.result_set.options.assign_trials is False


def test_a_result_that_finishes_after_the_study_changed_is_recorded_as_stale(app, tmp_path, monkeypatch):
    folder = tmp_path / "async_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    pending = []
    monkeypatch.setattr(ws.tasks, "run", lambda work, **callbacks: pending.append((work, callbacks)))
    ws.run_button.invoke()
    assert ws.run_button.instate(["disabled"]) and len(pending) == 1
    ws.method_var.set("capability")  # edited while the analysis is on its worker thread
    work, callbacks = pending[0]
    callbacks["on_success"](work(lambda *_: None))
    assert ws.result_set is not None and ws.result_set.options.method == "grr" and ws.stale
    assert ws.run_button.instate(["!disabled"]) and ws.pdf_button.instate(["disabled"])


def test_results_appear_at_once_with_notes_and_without_any_confirmation(app, tmp_path, monkeypatch):
    from datamapperx.ui import validation_workspace

    folder = tmp_path / "cap_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.method_var.set("capability")
    run_validation(app, ws)
    app.update()
    headers = [ws.table.heading(c)["text"] for c in ws.table["columns"]]
    assert headers == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk"]  # no criteria chosen: statistics only, no Result column
    assert "statistics only" in ws.summary_var.get() and showing(app, ws.filter_combo, False)
    assert all(r.metrics.get("cpk") is not None and r.status == "N/A" for r in ws.results)
    assert ws.pdf_button.instate(["!disabled"])  # a report never waits for a verdict or a confirmation
    assert showing(app, ws.notes_bar) and "Keep in mind" in ws.notes_var.get() and "not confirmed" not in ws.notes_var.get()
    shown = []
    monkeypatch.setattr(validation_workspace, "ReportDialog", lambda *args: shown.append(args[-1]))
    ws.notes_button.invoke()
    assert "Process stability" in shown[-1] and "Normal distribution" in shown[-1] and "do not block" in shown[-1]
    ws.judge_var.set(True)  # judging against a limit is optional and changes no number
    app.update()
    cpk = [r.metrics["cpk"] for r in ws.results]
    assert [ws.table.heading(c)["text"] for c in ws.table["columns"]][-1] == "Result"
    assert all(ws.table.item(i, "values")[-1] in ("PASS", "FAIL") for i in ws.table.get_children())
    assert [r.metrics["cpk"] for r in ws.results] == cpk and not ws.stale
    ws.judge_var.set(False)
    app.update()
    assert [ws.table.heading(c)["text"] for c in ws.table["columns"]][-1] == "Ppk" and not ws.stale
    ws.subgroup_var.set(True)  # a statistical input: the results go stale
    assert ws.stale


def test_grr_has_no_pass_or_fail_until_criteria_are_chosen(app, tmp_path):
    folder = tmp_path / "criteria_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    assert ws.profile_var.get() == "None (statistics only)"
    run_validation(app, ws)
    assert [ws.table.heading(c)["text"] for c in ws.table["columns"]] == ["Test Item", "%SV/Tol", "%Study Var", "NDC"]
    assert all(r.status == "N/A" and "ndc" in r.metrics for r in ws.results) and "statistics only" in ws.summary_var.get()
    assert "No acceptance criteria" in ws.plan_var.get()
    ws.profile_var.set("SolarEdge")  # criteria are a layer on top: the figures stay and PASS / FAIL appear
    app.update()
    assert not ws.stale and [ws.table.heading(c)["text"] for c in ws.table["columns"]][-2:] == ["Acceptance Result", "Review"]
    assert {ws.table.item(i, "values")[-2] for i in ws.table.get_children()} <= {"PASS", "CONDITIONAL PASS", "FAIL", "N/A"}
    assert "Customer criteria: SolarEdge" in ws.plan_var.get() and showing(app, ws.filter_combo)


def test_within_sigma_is_chosen_from_the_subgroup_size_unless_the_user_says_otherwise(app, tmp_path):
    folder = tmp_path / "within_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.method_var.set("capability")
    app.update()
    assert ws.study.options.within_method == "individuals" and "chosen from the subgroup size" in ws.plan_var.get()
    ws.subgroup_var.set(True)  # the two files of a serial number form a subgroup
    app.update()
    assert ws.study.options.within_method == "pooled" and "pooled standard deviation" in ws.plan_var.get()
    ws.within_var.set("Average moving range, length 2 (subgroup size 1)")
    app.update()
    assert ws.study.options.within_method == "individuals" and "chosen from the subgroup size" not in ws.plan_var.get()


def test_the_details_tab_shows_the_tables_of_the_selected_item(app, tmp_path):
    folder = tmp_path / "session_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    run_validation(app, ws)
    text = ws.session.text.get("1.0", "end")
    assert "One-Way ANOVA Table" in text and "Variance Components" in text and "%Contribution" in text and "%Tolerance" in text
    assert "Gage Evaluation" in text and "Number of Distinct Categories" in text and "Part-To-Part" in text
    ws.method_var.set("capability")
    run_validation(app, ws)
    text = ws.session.text.get("1.0", "end")
    for expected in ("Process Data", "StDev(Within)", "Potential (Within) Capability", "Overall Capability", "Ppk", "PPM < LSL"):
        assert expected in text


def test_ppk_can_be_the_decision_index_and_the_table_leaves_out_what_does_not_decide(app, tmp_path):
    folder = tmp_path / "ppk_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.method_var.set("capability")
    ws.judge_var.set(True)
    ws.index_var.set("ppk")
    ws.precision_var.set("5")  # decimals only change what is shown
    run_validation(app, ws)
    assert {r.decision_metric for r in ws.results} == {"ppk"}
    cp = ws.table.item(ws.table.get_children()[0], "values")[2]
    assert len(cp.split(".")[1]) == 5
    ws.precision_var.set("2")
    assert len(ws.table.item(ws.table.get_children()[0], "values")[2].split(".")[1]) == 2 and not ws.stale
    headers = [ws.table.heading(c)["text"] for c in ws.table["columns"]]
    assert headers == ["Test Item", "N", "Cp", "Cpk", "Pp", "Ppk", "Result"]  # Mean/Min/Max and an empty System are in the details
    ws.method_var.set("grr")
    ws.profile_var.set("SolarEdge")
    run_validation(app, ws)
    headers = [ws.table.heading(c)["text"] for c in ws.table["columns"]]
    assert headers == ["Test Item", "%SV/Tol", "%Study Var", "NDC", "Acceptance Result", "Review"]  # the three key metrics first


def test_data_mapping_changes_reach_validation_when_it_is_shown_again(app, tmp_path):
    folder = tmp_path / "change_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    run_validation(app, ws)
    assert len(ws.results) == 3
    app.mapping_switch.invoke()
    app.selected_components = ["R1", "R2"]
    app._selection_changed()
    app.validation_switch.invoke()
    pump(app, lambda: ws.dataset is not None and not ws.busy and len(ws.dataset.items) == 2)
    assert "Test Items 2" in ws.dataset_var.get() and ws.stale and showing(app, ws.stale_banner)
    assert len(ws.table.get_children()) == 3  # still the old results, marked as such
    ws.update_button.invoke()
    pump(app, lambda: not ws.running and not ws.stale)
    assert len(ws.results) == 2


def test_a_report_needs_no_study_information_and_can_cover_part_of_the_items(app, tmp_path, monkeypatch):
    folder = tmp_path / "report_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    run_validation(app, ws)
    asked = []
    outputs = [tmp_path / "bare.xlsx", tmp_path / "partial.xlsx"]
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: asked.append(kw) or str(outputs[len(asked) - 1]))
    today = date.today().strftime("%d-%m-%Y")
    assert ws.date_var.get() == today and "optional" in ws.report_tab.winfo_children()[0].winfo_children()[0].cget("text")
    ws.excel_button.invoke()  # nothing entered: the report is made all the same
    pump(app, lambda: not ws.export_busy)
    assert ws.report_var.get() == f"Saved: {outputs[0]}"
    bare = load_workbook(outputs[0])
    assert bare.sheetnames[0] == "Summary" and len(bare.sheetnames) == 7  # a summary, then a sheet and its plot data per item
    assert not any(str(c.value).startswith(("Gage name", "Reported by")) for ws_ in bare for row in ws_.iter_rows() for c in row)
    assert any(c.value == f"Date of study: {today}" for row in bare["Summary"].iter_rows() for c in row)  # today unless chosen
    bare.close()
    ws.gage_var.set("Bench DMM 7")
    ws.by_var.set("T. Man")
    ws.comments_var.set("first article")
    ws.item_list.selection_clear(0, "end")
    ws.item_list.selection_set(0)
    ws._update_coverage()
    assert ws.coverage_var.get() == "Included 1 of 3 items"
    ws.sections["observations"].set(True)
    ws.excel_button.invoke()
    pump(app, lambda: not ws.export_busy)
    assert ws.report_var.get() == f"Saved: {outputs[1]}" and ws.last_report == outputs[1] and ws.open_button.instate(["!disabled"])
    book = load_workbook(outputs[1])
    assert len(book.sheetnames) == 3 and book.sheetnames[-1] == "Observations"  # one item: its sheet, plot data, observations
    labels = {str(row[0].value): row[1].value for row in book[book.sheetnames[0]].iter_rows(min_col=1, max_col=2) if row[0].value}
    assert labels["Gage name:"] == "Bench DMM 7" and labels["Reported by:"] == "T. Man" and labels["Misc:"] == "first article"
    book.close()


def test_about_the_method_is_the_only_explanation_and_follows_the_analysis_and_the_selected_item(app, tmp_path, monkeypatch):
    from datamapperx.method_guide import guide_text
    from datamapperx.ui import validation_workspace

    folder = tmp_path / "about_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    assert not any(hasattr(ws, name) for name in ("detail_button", "issues_button", "show_details", "show_issues"))
    shown = []
    monkeypatch.setattr(validation_workspace, "MethodDialog", lambda parent, guide: shown.append(guide))
    ws.method_var.set("capability")
    ws.about_button.invoke()
    assert shown[-1].title.startswith("Process Capability") and "1.128" in guide_text(shown[-1])
    assert "Values for the selected item" not in [s.title for s in shown[-1].sections]  # nothing analysed yet
    ws.method_var.set("grr")
    ws.about_button.invoke()
    assert shown[-1].title == "Variable Gage R&R" and shown[-1].method == "One-way ANOVA (Single Tester)"
    run_validation(app, ws)
    ws.table.selection_set(ws.table.get_children()[0])
    ws.about_button.invoke()
    assert shown[-1].sections[-2].title == "Values for the selected item" and shown[-1].sections[-2].values


def test_the_about_dialog_draws_the_groups_of_formulas_and_they_can_be_closed(app):
    from datamapperx.method_guide import method_guide
    from datamapperx.statistics import AnalysisConfig
    from datamapperx.ui.math_view import MathView
    from datamapperx.ui.method_dialog import MethodDialog

    guide = method_guide(AnalysisConfig(method="grr"))
    dialog = MethodDialog(app, guide)
    app.update()
    titles = [section.title for section in guide.sections]
    assert titles[:3] == ["ANOVA calculations", "Variance components", "Key metrics"] and set(dialog.sections) == set(titles)
    body, _ = dialog.sections["Key metrics"]
    formulas = [w for w in body.winfo_children()[0].winfo_children() if isinstance(w, MathView)]
    assert formulas and all(w.winfo_reqwidth() > 10 and w.winfo_reqheight() > 10 for w in formulas)
    # tkinter finds the widget of an event with nametowidget(), which calls the widget's _root(); no attribute may hide it
    assert all(w.nametowidget(str(dialog.canvas)) is dialog.canvas for w in formulas)
    assert body.winfo_ismapped() and not dialog.sections["Known limits"][0].winfo_ismapped()
    dialog.toggle("Key metrics")
    dialog.toggle("Known limits")
    app.update()
    assert not body.winfo_ismapped() and dialog.sections["Known limits"][0].winfo_ismapped()
    dialog.close()


def test_an_invalid_item_does_not_stop_the_others_and_the_table_can_be_filtered(app, tmp_path):
    from datamapperx.models import Measurement

    folder = tmp_path / "invalid_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    record = next(iter(app.scan_result.grouped.values()))[0]
    record.entries["R1"] = Measurement("R1", "bad", "0", "9")
    app._data_changed()  # what the duplicate choice does when it changes a value
    ws = open_validation(app)
    ws.method_var.set("capability")
    run_validation(app, ws)
    assert len(ws.results) == 3 and next(r for r in ws.results if r.test_item == "R1").status == "N/A"
    assert "1 item could not be analysed" in ws.notes_var.get() and ws.notes_bar.winfo_manager()  # said where it matters
    ws.search_var.set("R1")
    assert len(ws.table.get_children()) == 1
    ws.search_var.set("")
    ws.judge_var.set(True)  # filtering by result needs criteria
    app.update()
    ws.filter_var.set("N/A")
    assert len(ws.table.get_children()) == 1  # the invalid item
    verdict = next(r.status for r in ws.results if r.valid)
    ws.filter_var.set(verdict)
    assert len(ws.table.get_children()) == len([r for r in ws.results if r.status == verdict]) == 2  # the two valid items
    app.reset_workflow()
    assert app.workspace == "mapping"


def test_mapping_assignments_and_order_apply_to_the_snapshot_and_never_to_the_scan(app, tmp_path):
    folder = tmp_path / "map_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    for records in app.scan_result.grouped.values():  # a tester and a slot for every file
        for record in records:
            ws.assignments[str(record.path)] = {"tester": "T1", "slot": "1"}
    ws.data_edited()
    pump(app, lambda: not ws.busy)
    run_validation(app, ws)
    assert all("Slot=1" in r.system and "Tester=T1" in r.system for r in ws.results)
    source = str(next(iter(app.scan_result.grouped.values()))[0].path)
    ws.assignments[source] = {**ws.assignments[source], "sample_id": "different-sample"}
    ws.data_edited()
    pump(app, lambda: not ws.busy)
    ws.update_button.invoke()
    pump(app, lambda: not ws.running and not ws.stale)
    assert any(not r.valid for r in ws.results)  # an identity edit makes the study unbalanced
    ws.assignments.clear()
    ws.method_var.set("capability")
    ws.order_var.set("Timestamp order (File assignments)")
    pump(app, lambda: not ws.busy)
    assert "ISO 8601" in ws.message_var.get() and ws.dataset is None
    for index, row in enumerate(r for records in app.scan_result.grouped.values() for r in records):
        ws.assignments[str(row.path)] = {"timestamp": f"2026-10-30T10:00:{50 - index:02d}"}
    ws.data_edited()
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    assert ws.dataset.order_basis == "acquisition" and "rows sorted by timestamp" in ws.dataset.description
    stamps = [o.timestamp for o in ws.dataset.observations if o.test_item == "R1"]
    assert stamps == sorted(stamps)
    run_validation(app, ws)
    codes = {c.code for c in ws.evaluated.record.validation.conditions}
    assert "acquisition_order" not in codes  # the rows are in measurement order, as the timestamps say


def test_a_rawdata_workbook_can_be_analysed_without_scanning_anything(app, tmp_path):
    from datamapperx.exporter import generate_excel
    from datamapperx.profiles import DEFAULT_PROFILES
    from datamapperx.scanner import scan_folder

    from .baseline_support import write_rawdata_logs

    logs = tmp_path / "raw_logs"
    logs.mkdir()
    write_rawdata_logs(logs)
    import copy

    result = scan_folder(logs, copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"]))
    workbook = tmp_path / "RawData.xlsx"
    generate_excel(result.grouped, ["R1", "Long"], workbook, expected_repeated=2)
    ws = open_validation_without_data(app)
    ws.open_file(workbook)
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.source_var.get() == "file")
    assert ws.file_var.get() == str(workbook)
    assert all(part in ws.dataset_var.get() for part in ("Test Items 2", "Samples 3", "Total Readings 12", "Trials per Sample 2"))
    assert showing(app, ws.mapping_controls, False) and showing(app, ws.file_controls)
    assert [ws.order_menu.entrycget(i, "label") for i in (1, 2)] == ["Worksheet order", "Rows are in measurement order (I confirm)"]
    assert ws.order_menu.index("end") == 2  # a file has no files of its own to order by: the header and two choices
    assert ws.preview.item(ws.preview.get_children()[0], "values")[1] == "VSE000123"  # text serial numbers, worksheet order
    ws.assign_var.set(True)
    run_validation(app, ws)
    assert len(ws.results) == 2 and ws.study.mapping["source"] == "file"
    ws.source_var.set("mapping")  # back to Data Mapping's results: nothing scanned, so no data
    pump(app, lambda: not ws.busy)
    assert ws.dataset is None and ws.run_button.instate(["disabled"])


def test_importing_a_file_that_is_not_a_rawdata_workbook_says_why(app, tmp_path):
    from openpyxl import Workbook

    wrong = tmp_path / "wrong.xlsx"
    book = Workbook()
    book.active.append(["Name", "Value"])
    book.save(wrong)
    ws = open_validation_without_data(app)
    ws.open_file(wrong)
    pump(app, lambda: not ws.busy)
    assert "STT and SN" in ws.message_var.get() and ws.dataset is None


def test_file_assignment_browsing_shows_the_logs_own_identities_and_pins_nothing(app, tmp_path):
    from datamapperx.ui.validation import AssignmentDialog

    folder = tmp_path / "assignment_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    dialog = AssignmentDialog(ws)
    try:
        dialog.files.selection_set(1)  # second file of the first sample
        dialog.select()
        assert dialog.variables["sample_id"].get() == dialog.records[1].sn and dialog.variables["trial"].get() == ""
        dialog.files.selection_clear(0, "end")
        dialog.files.selection_set(2)
        dialog.select()
        assert not dialog.pending  # browsing alone does not pin overrides
        dialog.variables["slot"].set("Nest 2")
        dialog.apply()
        assert list(ws.assignments.values()) == [{"slot": "Nest 2"}]
    finally:
        if dialog.winfo_exists():
            dialog.close()
    pump(app, lambda: not ws.busy)
    assert any(o.slot == "Nest 2" for o in ws.dataset.observations)


def test_review_notice_shows_only_for_acceptable_results_that_disagree(app, tmp_path):
    from datamapperx.statistics import Dataset, Observation

    folder = tmp_path / "review_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.profile_var.set("SolarEdge")  # the Review flag belongs to the criteria
    wide = [Observation("Wide tolerance", f"S{part}", value, -1000, 1000, trial=str(trial), source=f"w{part}{trial}")
            for part, values in enumerate(((0, 2), (0, 2)), 1) for trial, value in enumerate(values, 1)]
    clean = [Observation("Clean", f"S{part}", value, 0, 100, trial=str(trial), source=f"c{part}{trial}")
             for part, values in enumerate(((0, .1), (10, 10.1), (20, 20.2), (30, 30.1)), 1)
             for trial, value in enumerate(values, 1)]
    ws._dataset_ready(Dataset.from_observations(clean))
    run_validation(app, ws)
    app.update()
    assert showing(app, ws.review_label, False) and ws.review_var.get() == ""
    ws._dataset_ready(Dataset.from_observations(wide + clean))
    ws.update_button.invoke()
    pump(app, lambda: not ws.running and not ws.stale)
    pump(app, lambda: ws.review_label.winfo_ismapped())  # the label's wrap width settles on the next layout pass
    headers = [ws.table.heading(column)["text"] for column in ws.table["columns"]]
    assert "Review" in headers and "Review needed: 1 of 2" in ws.review_var.get()
    flagged = next(ws.table.item(i, "values") for i in ws.table.get_children() if "Wide" in ws.table.item(i, "values")[0])
    assert "NDC" in flagged[headers.index("Review")] and flagged[headers.index("Acceptance Result")] == "PASS"
    app.geometry("1000x680+0+0")
    pump(app, lambda: inside(app, ws.table) and inside(app, ws.review_label))  # still visible at the supported minimum size
    app.geometry("1360x880+0+0")
    ws._dataset_ready(Dataset.from_observations(clean))
    ws.update_button.invoke()
    pump(app, lambda: not ws.running and not ws.stale)
    app.update()
    assert showing(app, ws.review_label, False) and ws.review_var.get() == ""


def test_validation_layout_and_theme_fit_supported_desktop_size(app, tmp_path):
    folder = tmp_path / "layout_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    app.geometry("1000x680+0+0")
    ws = open_validation(app)
    ws.tabs.select(ws.data_tab)
    app.update()
    for widget in (app.mapping_switch, app.validation_switch, ws.run_button, ws.tabs, ws.preview):
        assert inside(app, widget), widget
    ws.tabs.select(ws.setup_tab)
    app.update()
    for widget in (ws.study_factor_combo, ws.criteria_button, ws.plan_label):
        assert inside(app, widget), widget
    ws.method_var.set("capability")
    run_validation(app, ws)
    app.update()
    for widget in (ws.table, ws.about_button, ws.notes_button):
        assert inside(app, widget), widget
    headers = [ws.table.heading(c)["text"] for c in ws.table["columns"]]
    assert sum(int(ws.table.column(c, "width")) for c in ws.table["columns"]) <= ws.table.winfo_width() + 4, headers  # no sideways scroll
    ws.tabs.select(ws.report_tab)
    app.update()
    for widget in (ws.pdf_button, ws.excel_button, ws.item_list, ws.info_entries["Misc"]):
        assert inside(app, widget), widget
    app.dark_var.set(True)
    app._on_theme_toggle()
    assert ws.palette is app.palette
    app.geometry("1360x880+0+0")


def test_shortcuts_of_data_mapping_bring_it_back_first(app, tmp_path):
    folder = tmp_path / "shortcut_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    open_validation(app)
    assert app.workspace == "validation"
    app._export_shortcut()  # Ctrl+E: it must not export from a screen that is not showing the data
    assert app.workspace == "mapping" and app.step == "review"
    app._show_workspace("validation")
    app._show_step("select")
    app.update()
    assert app.workspace == "mapping" and showing(app, app.select_page)


def test_every_new_study_starts_as_statistics_only_even_if_an_older_version_saved_a_customer(app, tmp_path):
    from datamapperx.settings import Settings
    from datamapperx.ui.validation_workspace import NO_CRITERIA, ValidationWorkspace

    saved = Settings()
    saved.validation_customer = "SolarEdge"  # what the previous version remembered
    fresh = ValidationWorkspace(app, app.palette, settings=saved)
    try:
        assert fresh.profile_var.get() == NO_CRITERIA and not fresh.judge_var.get()
    finally:
        fresh.destroy()
    folder = tmp_path / "criteria_reset_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.profile_var.set("SolarEdge")
    ws.method_var.set("capability")
    ws.judge_var.set(True)
    app.update()
    assert ws.profile_var.get() == "SolarEdge" and ws.judge_var.get()
    ws.method_var.set("grr")
    app.reset_workflow()  # nothing to analyse: the study is gone
    ready_to_review(app, folder)
    app._show_workspace("validation")
    pump(app, lambda: ws.dataset is not None and not ws.busy)
    assert ws.profile_var.get() == NO_CRITERIA and not ws.judge_var.get()  # the next study starts again without criteria
    run_validation(app, ws)
    assert all(r.status == "N/A" for r in ws.results) and "statistics only" in ws.summary_var.get()


def test_the_within_sigma_method_is_an_advanced_option(app, tmp_path):
    folder = tmp_path / "advanced_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    ws.method_var.set("capability")
    ws.tabs.select(ws.setup_tab)
    app.update()
    assert showing(app, ws.advanced_button) and showing(app, ws.advanced, False)
    ws.advanced_button.invoke()
    assert showing(app, ws.advanced) and "▾" in ws.advanced_button.cget("text")
    ws.advanced_button.invoke()
    assert showing(app, ws.advanced, False)


# ----------------------------------------------------------------------------- the worksheet, the checks and the order of the readings
def write_study_logs(folder, *, parts=10, operators=("Ann", "Bob", "Cy"), readings=3, by_folder=True, skip=()):
    """One log per part, operator and reading, with some spread; in a folder per operator, or all in one folder."""
    for k, operator in enumerate(operators):
        target = folder / operator if by_folder else folder
        target.mkdir(exist_ok=True)
        for part in range(1, parts + 1):
            for reading in range(readings):
                if (part, operator) in skip:
                    continue
                value = 10 + part + 0.1 * ((part * 3 + reading * 5 + k * 7) % 4)
                write_ict_log(target / f"P{part:02d}_{operator}_{reading + 1}.log", f"VSE{part:03d}",
                              [ict_block("R1", f"{value:+.5E}", "+4.0E+01", "+0.0E+00")])


def scanned_study(app, folder, *, parts=10, operators=("Ann", "Bob", "Cy"), readings=3, **kwargs):
    write_study_logs(folder, parts=parts, operators=operators, readings=readings, **kwargs)
    scan(app, folder, expected=parts, repeats=len(operators) * readings)
    app.add_all_shown()
    return open_validation(app)


def worksheet(ws, column):
    return [ws.preview.item(item, "values")[column] for item in ws.preview.get_children()]


def test_a_single_tester_study_needs_no_operators_and_the_worksheet_says_how_it_looks(app, tmp_path):
    folder = tmp_path / "one_tester"
    folder.mkdir()
    ws = scanned_study(app, folder, operators=("T1",), by_folder=False)
    ws.tabs.select(ws.setup_tab)
    app.update()
    assert not any(hasattr(ws, name) for name in ("operators_entry", "nest_check", "operator_order_combo", "folders_button"))
    assert "operator" not in ws.preview["displaycolumns"]  # nobody is named: the worksheet has no Operator column
    assert worksheet(ws, 3)[:6] == ["1", "2", "3"] * 2  # the trial each reading will get, counted per part
    assert all(part in ws.dataset_var.get() for part in ("Test Items 1", "Samples 10", "Total Readings 30", "Trials per Sample 3"))
    assert ws.hint_var.get() == "" and showing(app, ws.hint_label, False)  # balanced and complete: nothing to warn about
    run_validation(app, ws)
    assert ws.results[0].valid and not ws.results[0].details.get("crossed") and "Single-tester" in ws.plan_var.get()
    assert not any(c.code == "one_appraiser" for c in ws.evaluated.record.validation.conditions)
    assert "Operators:" not in ws.checks_view.text.get("1.0", "end")


def test_the_study_variation_factor_scales_study_var_and_tolerance_only(app, tmp_path):
    from datamapperx.method_guide import guide_text, method_guide
    from datamapperx.stat_reports import session_text

    folder = tmp_path / "factor"
    folder.mkdir()
    ws = scanned_study(app, folder, operators=("T1",), by_folder=False)
    assert ws.study_factor_var.get() == "6" and tuple(map(str, ws.study_factor_combo["values"])) == ("1", "2", "3", "4", "5", "6")
    run_validation(app, ws)
    six = dict(ws.results[0].metrics)
    assert "6 × SD" in session_text(ws.results[0])
    ws.study_factor_var.set("4")
    assert ws.stale  # the factor decides the numbers
    run_validation(app, ws)
    four = ws.results[0].metrics
    assert four["study_var"] == pytest.approx(six["study_var"] * 4 / 6) and four["percent_tolerance"] == pytest.approx(six["percent_tolerance"] * 4 / 6)
    for unchanged in ("percent_study_var", "ndc", "sigma_grr", "sigma_part", "variance_grr", "variance_part"):
        assert four[unchanged] == six[unchanged], unchanged
    assert "4 × SD" in session_text(ws.results[0]) and "Study variation: 4 × SD." in ws.plan_var.get()
    note = guide_text(method_guide(ws._config()))
    assert "uses k = 4" in note and "±3σ" in note and "Gage R&R is the repeatability" in note
    ws.study_factor_var.set("7")
    assert "from 1 to 6" in ws.setup_error and ws.run_button.instate(["disabled"])
    ws.study_factor_var.set("6")
    assert ws.setup_error == ""


def test_the_checks_tab_gives_amount_of_data_and_the_guidelines_for_gage_rr(app, tmp_path):
    folder = tmp_path / "checks_grr"
    folder.mkdir()
    ws = scanned_study(app, folder, parts=8, operators=("T1",), by_folder=False)
    run_validation(app, ws)
    shown = ws.checks_view.text.get("1.0", "end")
    assert "!  Parts: Only 8 parts" in shown and "Operators:" not in shown  # fewer than 10 parts
    assert "Guidelines (AIAG, as Minitab quotes them)" in shown and "%Study Var:" in shown and "%Contribution:" in shown
    assert "not printed in the report" in shown
    assert "with data checks to review" in ws.summary_var.get()
    folder2 = tmp_path / "checks_grr_ok"
    folder2.mkdir()
    ws = scanned_study(app, folder2, parts=12, operators=("T1",), by_folder=False)
    run_validation(app, ws)
    assert "i  Parts: 12 parts meets the usual minimum" in ws.checks_view.text.get("1.0", "end")
    assert "with data checks to review" not in ws.summary_var.get()


def test_file_time_order_sorts_by_when_each_log_was_saved_and_is_taken_as_the_order_of_measurement(app, tmp_path):
    import os

    from datamapperx.ui.validation_workspace import ORDERS

    folder = tmp_path / "timed"
    folder.mkdir()
    ws = scanned_study(app, folder, by_folder=False, operators=("Ann",), readings=9)
    paths = sorted(str(r.path) for records in app.scan_result.grouped.values() for r in records)
    for position, path in enumerate(paths):  # saved in the reverse of the name order
        os.utime(path, ns=(10**18 + (len(paths) - position) * 10**9,) * 2)
    ws.method_var.set("capability")
    assert "worksheet order" in ws.hint_var.get() and "Settings" in ws.hint_var.get()  # capability depends on the order: said once
    ws.order_var.set(ORDERS["filetime"])
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.dataset.order_basis == "acquisition")
    assert "the time each log file was saved" in ws.dataset.description
    first_files = [ws.preview.item(item, "values")[-1] for item in ws.preview.get_children()][:2]
    assert first_files[0].endswith("P10_Ann_9.log") and first_files[1].endswith("P10_Ann_8.log")  # the last name was saved first
    run_validation(app, ws)
    shown = ws.checks_view.text.get("1.0", "end")
    assert "Stability:" in shown and "Normality:" in shown and "Amount of data:" in shown
    assert "taken as the order of measurement" in shown and ws.hint_var.get() == ""  # an order was chosen: nothing to warn about
    ws.method_var.set("grr")
    assert ws.hint_var.get() == ""
    ws.method_var.set("capability")
    ws.order_var.set(ORDERS["worksheet"])
    pump(app, lambda: ws.dataset is not None and not ws.busy and ws.dataset.order_basis == "worksheet")
    run_validation(app, ws)
    assert "choose File time order" in ws.checks_view.text.get("1.0", "end")


def test_the_notes_of_a_capability_analysis_point_to_the_checks_tab_without_changing_the_noted_text(app, tmp_path, monkeypatch):
    from datamapperx.ui import validation_workspace

    folder = tmp_path / "notes"
    folder.mkdir()
    ws = scanned_study(app, folder, by_folder=False, operators=("Ann",), readings=9)
    ws.method_var.set("capability")
    run_validation(app, ws)
    shown = []
    monkeypatch.setattr(validation_workspace, "ReportDialog", lambda parent, title, heading, text: shown.append(text))
    ws.show_notes()
    assert "Stability is not tested here" in shown[0]  # the note that the report prints is unchanged
    assert "Screening in this program" in shown[0] and "not printed in the report" in shown[0]
    ws.method_var.set("grr")
    run_validation(app, ws)
    ws.show_notes()
    assert "Screening in this program" not in shown[1]


def test_the_date_of_study_is_today_and_is_chosen_from_a_calendar_in_dd_mm_yyyy(app, tmp_path):
    from datamapperx.ui.validation import DatePickerDialog

    folder = tmp_path / "date_logs"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    assert ws.date_var.get() == date.today().strftime("%d-%m-%Y") and str(ws.info_entries["Date of study"].cget("state")) == "readonly"
    assert ws.study.info.date_of_study == ws.date_var.get()
    picked = []
    dialog = DatePickerDialog(app, date(2026, 2, 27), picked.append)
    assert dialog.month_label.cget("text") == "February 2026"
    dialog._move(1)
    assert dialog.month_label.cget("text") == "March 2026"
    next(b for b in dialog.days.winfo_children() if b.cget("text") == "15").invoke()
    assert picked == [date(2026, 3, 15)] and not dialog.winfo_exists()
    ws.choose_date()  # opens the calendar on the date shown
    (dialog,) = [w for w in app.winfo_children() if isinstance(w, DatePickerDialog)]
    dialog.pick(date(2026, 1, 5))
    assert ws.date_var.get() == "05-01-2026" and ws.study.info.date_of_study == "05-01-2026"
    ws.on_show()
    assert ws.date_var.get() == "05-01-2026"  # a chosen date is kept
    ws._date_chosen = False  # the window is shared by the other tests
    ws.on_show()
    assert ws.date_var.get() == date.today().strftime("%d-%m-%Y")  # until then it is today


def test_the_data_tab_has_a_compact_summary_seven_columns_a_test_item_filter_and_marks_inferred_trials(app, tmp_path):
    folder = tmp_path / "data_tab"
    folder.mkdir()
    ready_to_review(app, folder)
    ws = open_validation(app)
    shown = tuple(ws.preview["displaycolumns"])
    assert shown == ("test_item", "sample", "trial", "value", "lsl", "usl", "unit")
    assert [ws.preview.heading(c)["text"] for c in shown] == ["Test Item", "Sample ID", "Trial", "Value", "LSL", "USL", "Unit"]
    first = ws.preview.get_children()[0]
    assert ws.preview.item(first, "values")[-1] and "ingerprint" not in ws.dataset_var.get() + ws.hint_var.get() + ws.preview_note_var.get()
    assert ws.hint_var.get() == "" and showing(app, ws.hint_label, False)  # nothing to fix, nothing said
    assert "inferred" in ws.preview.item(first, "tags") and "not the order of measurement" in ws.preview_note_var.get()
    ws.assign_var.set(False)  # without the labelling the readings have no Trial at all: that is a problem to fix
    assert "no Trial" in ws.hint_var.get() and ws.preview.item(first, "tags") == "" and showing(app, ws.hint_label)
    ws.assign_var.set(True)
    # the filter
    items = list(ws.item_filter["values"])
    rows = len(ws.preview.get_children())
    assert items[0] == "All Test Items" and ws.item_filter_var.get() == "All Test Items" and len(items) == 4 and rows == 18
    ws.item_filter_var.set(items[1])
    shown_items = {ws.preview.item(i, "values")[0] for i in ws.preview.get_children()}
    assert shown_items == {items[1]} and len(ws.preview.get_children()) == 6
    ws.item_filter_var.set("All Test Items")
    assert len(ws.preview.get_children()) == 18
    # what belongs to the source, and the order of the readings in Settings
    assert showing(app, ws.mapping_controls) and ws.order_menu.index("end") == 5 and not hasattr(ws, "order_combo")
    ws.source_var.set("file")
    assert showing(app, ws.mapping_controls, False) and showing(app, ws.file_controls)
    ws.source_var.set("mapping")
    assert showing(app, ws.mapping_controls) and showing(app, ws.file_controls, False)


def test_readings_are_shown_with_reasonable_precision_and_the_data_keep_their_own_values(app):
    ws = open_validation_without_data(app)
    assert ws._cell(0.269585132598877) == "0.269585" and ws._cell(1.5) == "1.5" and ws._cell(40) == "40"
    assert ws._cell(1e-8) == "0.00000001" and ws._cell("bad") == "bad" and ws._cell(None) == "" and ws._cell(1234567.891) == "1234567.891" and ws._cell(0.0) == "0"


def test_the_quick_check_criteria_are_set_in_a_dialog_and_applied_at_once_without_recalculating(app, tmp_path):
    from datamapperx.grr import DEFAULT_QUICK_CRITERIA
    from datamapperx.ui.dialogs import GrrCriteriaDialog

    folder = tmp_path / "criteria_logs"
    folder.mkdir()
    grr_logs(folder)
    scan(app, folder, repeats=3)
    app.add_all_shown()
    app._show_step("review")
    app.update()
    app._set_grr_criteria(DEFAULT_QUICK_CRITERIA)
    assert app.grr_criteria == DEFAULT_QUICK_CRITERIA and app.settings.quick_check_criteria == []  # the defaults are not saved
    assert [label.cget("text") for _, label, _ in app.grr_legend_tiles] == ["PASS", "CONDITION", "FAIL"]  # colour keys only
    figures = app._grr_results
    app._edit_grr_criteria()
    (dialog,) = [w for w in app.winfo_children() if isinstance(w, GrrCriteriaDialog)]
    enabled, low, high = dialog.vars["percent_tolerance"]
    enabled.set(True)  # %SV/Tol now decides too, and the percentages get their own limits
    low.set("5")
    high.set("20")
    dialog.vars["percent_study_var"][1].set("40")
    dialog.vars["percent_study_var"][2].set("20")  # PASS limit above the FAIL limit: refused, and said why
    dialog.apply()
    assert "PASS limit cannot be above" in dialog.error_var.get() and dialog.winfo_exists() and app.grr_criteria == DEFAULT_QUICK_CRITERIA
    dialog.vars["percent_study_var"][1].set("40")
    dialog.vars["percent_study_var"][2].set("60")
    dialog.vars["ndc"][1].set("2.5")
    dialog.apply()
    assert "whole number" in dialog.error_var.get()
    dialog.vars["ndc"][1].set("3")
    dialog.apply()
    assert not dialog.winfo_exists() and app._grr_results is figures  # applied at once, the figures are the same objects
    try:
        assert app.grr_grid.cell_tags() == {
            (0, 1): "pass", (0, 2): "fail", (0, 3): "pass", (0, 4): "fail",  # X: SV 32.16 under 40, Tol 30 above 20, NDC 4 from 3
            (1, 1): "pass", (1, 2): "caution", (1, 3): "pass", (1, 4): "caution",  # Y: Tol 6 is above 5 and up to 20
        }
        assert [row[-1] for row in app.grr_grid.rows()] == ["FAIL", "CONDITION"]
        assert [c["metric"] for c in app.settings.quick_check_criteria] == ["percent_study_var", "percent_tolerance", "ndc"]
        from datamapperx.grr import quick_criteria_from_json
        assert quick_criteria_from_json(app.settings.quick_check_criteria) == app.grr_criteria  # what is saved is what is read back
    finally:
        app._set_grr_criteria(DEFAULT_QUICK_CRITERIA)


def test_results_put_the_table_beside_the_charts_in_a_wide_window_and_above_them_in_a_narrow_one(app, tmp_path):
    folder = tmp_path / "results_layout"
    folder.mkdir()
    ready_to_review(app, folder)
    app.geometry("1360x880+0+0")
    ws = open_validation(app)
    run_validation(app, ws)
    app.update()
    app.update()
    table, charts = ws.table_page, ws.right_pane
    assert ws._wide and ws.split is ws.split_cols and ws.split_rows.winfo_manager() == ""
    assert table.winfo_rootx() < charts.winfo_rootx() and abs(table.winfo_rooty() - charts.winfo_rooty()) <= 2  # side by side
    assert abs(table.winfo_height() - charts.winfo_height()) <= 2 and table.winfo_height() > 400  # each with the whole height
    assert table.winfo_width() >= 380 and charts.winfo_width() > table.winfo_width()
    for widget in (ws.table, ws.chart_canvas, ws.about_button, ws.selected_label, ws.run_button):
        assert inside(app, widget), widget
    assert ws.selected_var.get() == item_label(ws.selected_result()) and ws.chart_canvas.winfo_height() > 450
    assert not any(bar.winfo_ismapped() for bar in ws.table_bars)  # nothing to scroll: the room goes to the data
    summary = ws.notes_bar.master.winfo_children()[0]
    assert str(summary.cget("textvariable")) == str(ws.summary_var) and ws.notes_bar.winfo_ismapped()  # the notes sit beside the summary
    assert abs(summary.winfo_rooty() - ws.notes_bar.winfo_rooty()) <= 12 and ws.filters.master is ws.table_page  # search and sort: above the table
    app.geometry("1000x680+0+0")
    ws.tabs.select(ws.data_tab)
    app.update()
    ws.tabs.select(ws.results_tab)
    app.update()
    app.update()
    assert not ws._wide and ws.split is ws.split_rows and ws.split_cols.winfo_manager() == ""
    assert table.winfo_rooty() < charts.winfo_rooty() and abs(table.winfo_rootx() - charts.winfo_rootx()) <= 2  # above each other
    assert table.winfo_height() >= 120 and not ws.selected_label.winfo_ismapped()
    for widget in (ws.table, ws.chart_canvas, ws.about_button):
        assert inside(app, widget), widget
    app.geometry("1360x880+0+0")
