"""The profile manager and the sample wizard in Qt (the Tk versions were tested in tests/test_ui.py the same way)."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog

from datamapperx.parsing import parse_log_file
from datamapperx.ui_qt.profile_dialog import ProfileManager
from datamapperx.ui_qt.sample_wizard import SampleWizard

from ..test_sampling import EOL_ROWS, make_ict_folder, write_results_workbook
from .support import pump


def open_wizard(app, parent, sample, **kwargs):
    done: list[tuple[str, dict]] = []
    wizard = SampleWizard(parent, lambda name, profile: done.append((name, profile)), sample=sample, **kwargs)
    wizard.present()
    pump(app, lambda: wizard.status_label.text() not in ("", "Reading the sample…") or bool(wizard.problem_label.text()))
    return wizard, done


def select_text(wizard, line: int, text: str) -> None:
    """Select ``text`` on the 1-based ``line`` of the sample, as the person does with the mouse."""
    block = wizard.viewer.document().findBlockByNumber(line - 1)
    start = block.position() + wizard._lines[line - 1].index(text)
    cursor = QTextCursor(wizard.viewer.document())
    cursor.setPosition(start)
    cursor.setPosition(start + len(text), QTextCursor.MoveMode.KeepAnchor)
    wizard.viewer.setTextCursor(cursor)


def wait_for_status(app, wizard, fragment: str) -> None:
    pump(app, lambda: fragment in wizard.status_label.text())


def rows_of(wizard):
    return [row[0] for row in wizard.table.rows()]


# ----------------------------------------------------------------------------- the profile manager
def test_profile_manager_duplicate_edit_save_delete(app, window):
    changes = []
    manager = ProfileManager(window, window.profiles, changes.append)
    manager.present()
    assert not manager.save_button.isEnabled() and manager.fields["name"].isReadOnly()  # a built-in profile is read-only

    manager.listbox.setCurrentRow(0)
    manager._duplicate()
    assert manager.get("name") == "ICT_I3070 Test Log (copy)" and manager.save_button.isEnabled()
    manager.set("name", "My ICT")
    manager.set("measure_regex", "(unclosed")
    manager._save()
    assert "My ICT" not in window.profiles and any("Invalid Regex" in text for _k, text in window.shown)

    manager.set("measure_regex", window.profiles["ICT_I3070 Test Log"]["measure_regex"])
    manager._save()
    assert "My ICT" in window.profiles and changes == ["My ICT"]
    assert manager.selected_name() == "My ICT"

    manager.listbox.setCurrentRow(list(window.profiles).index("My ICT"))
    manager._delete()
    assert "My ICT" not in window.profiles and changes[-1] is None
    manager.close()


def test_built_in_profiles_cannot_be_deleted_or_overwritten(app, window):
    manager = ProfileManager(window, window.profiles, lambda name: None)
    manager.present()
    manager.listbox.setCurrentRow(0)
    manager._delete()
    assert any("cannot be deleted" in text for _k, text in window.shown)
    manager._duplicate()
    manager.set("name", "ICT_I3070 Test Log")
    manager._save()
    assert any("Cannot override" in text for _k, text in window.shown)
    manager.set("name", "")
    manager._save()
    assert any("cannot be empty" in text for _k, text in window.shown)
    manager.close()


def test_the_profile_list_in_the_window_follows_the_manager(app, window):
    manager = ProfileManager(window, window.profiles, window._on_profiles_changed)
    manager.present()
    manager.listbox.setCurrentRow(0)
    manager._duplicate()
    manager.set("name", "Another ICT")
    manager._save()
    assert "Another ICT" in [window.profile_box.itemText(i) for i in range(window.profile_box.count())]
    assert window.profile_box.currentText() == "Another ICT"  # a saved profile becomes the chosen one, as it always did
    window._on_profile_changed()
    assert "Profile changed" in window.status_label.text() and window.hint_label.text().startswith("Text log")
    manager.listbox.setCurrentRow(list(window.profiles).index("Another ICT"))
    manager._delete()
    assert window.profile_box.currentText() != "Another ICT" and "deleted" in window.status_label.text()
    manager.close()


def test_profile_manager_regex_tester(app, window):
    manager = ProfileManager(window, window.profiles, lambda name: None)
    manager.present()
    manager.set("test_input", "{@BLOCK|R77|00|1")
    assert "Component: R77" in manager.test_result.text()
    manager.set("test_input", "{@A-RES|0|+1.5E+03{@LIM2|+2.0E+03|+1.0E+03}}")
    assert "Measured: +1.5E+03" in manager.test_result.text() and "Min: +1.0E+03" in manager.test_result.text()
    manager.set("test_input", "garbage")
    assert "not recognized" in manager.test_result.text()
    manager.set("test_input", "")
    assert manager.test_result.text() == "Result: No data"
    manager.close()


def test_the_regular_expressions_are_hidden_until_asked_for(app, window):
    manager = ProfileManager(window, window.profiles, lambda name: None)
    manager.present()
    assert not manager.advanced_frame.isVisibleTo(manager)
    manager._toggle_advanced()
    assert manager.advanced_frame.isVisibleTo(manager) and manager.advanced_toggle.text().endswith("▾")
    manager.sn_regex_text.setText("VSE\\d+")
    manager.sn_regex_text.textEdited.emit("VSE\\d+")
    assert manager.get("sn_regex") == "VSE\\d+"  # one value, shown in two places
    manager.close()


def test_built_in_profiles_cannot_be_reconfigured_by_the_wizard(app, window):
    manager = ProfileManager(window, window.profiles, lambda name: None)
    manager.present()
    assert not manager.wizard_button.isEnabled()
    manager._open_wizard()
    assert any("Duplicate first" in text for _k, text in window.shown)
    manager.close()


def test_new_profile_from_a_sample_fills_the_form_and_saves(app, window, tmp_path, monkeypatch):
    folder = tmp_path / "EOL station"
    folder.mkdir()
    path = write_results_workbook(folder / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    changes = []
    manager = ProfileManager(window, window.profiles, changes.append)
    manager.present()
    manager._new_from_sample()
    wizard = manager.findChildren(SampleWizard)[-1]
    pump(app, lambda: wizard.sample is not None and "components read" in wizard.status_label.text())
    wizard.accept()
    assert (manager.get("name"), manager.type_box.currentText(), manager.get("sn_regex"), manager.get("component_col")) == (
        "EOL station", "excel", "B1", "C")
    manager._save()
    saved = window.profiles["EOL station"]
    assert changes == ["EOL station"] and saved["data_sheet"] == "Results" and saved["skip_empty_rows"] is True
    manager.close()


def test_editing_a_regular_expression_hides_the_readable_pattern_it_no_longer_matches(app, window, tmp_path, monkeypatch):
    sample = make_ict_folder(tmp_path / "ict")[0]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(sample), "")))
    manager = ProfileManager(window, window.profiles, lambda name: None)
    manager.present()
    manager._new_from_sample()
    wizard = manager.findChildren(SampleWizard)[-1]
    pump(app, lambda: wizard.sample is not None and "components read" in wizard.status_label.text())
    wizard.accept()
    assert "Component line:  {@BLOCK|[Component]|00" in manager.summary.text() and "looks like VSE2C00000112" in manager.summary.text()
    assert manager._collect()["block_template"] == "{@BLOCK|[Component]|00"
    manager.set("block_regex", r"\{@BLOCK\|(?P<component>\w+)")
    assert "block_template" not in manager._collect() and "Component line:  regular expression" in manager.summary.text()
    manager.close()


# ----------------------------------------------------------------------------- the sample wizard
def test_wizard_reads_an_excel_sample_from_its_headings(app, window, tmp_path):
    path = write_results_workbook(tmp_path / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS, extra_graph_sheets=1)
    wizard, done = open_wizard(app, window, path)
    assert wizard.kind == "excel" and wizard.excel_panel.isVisibleTo(wizard) and not wizard.text_panel.isVisibleTo(wizard)
    assert (wizard.value("data_sheet"), wizard.value("sn_sheet"), wizard.value("sn_cell")) == ("Results", "Session", "B1")
    assert wizard.value("col_component").startswith("C") and wizard.value("col_measured").startswith("F")
    assert wizard.sn_value.text() == "→ SV3826-06310A8C6-E1"
    assert "SV3826-06310A8C6-E1" in wizard.status_label.text() and "3 components read" in wizard.status_label.text()
    assert rows_of(wizard) == ["Init, Test SIM SN", "Config, Get Portia SW Version", "DC bus voltage"]
    wizard.accept()
    name, profile = done[0]
    assert name == tmp_path.name
    assert (profile["sn_regex"], profile["data_sheet"], profile["component_col"], profile["unit_col"]) == ("B1", "Results", "C", "H")
    assert profile["skip_empty_rows"] is True


def test_wizard_updates_the_preview_when_a_column_changes_and_blocks_an_unusable_choice(app, window, tmp_path):
    path = write_results_workbook(tmp_path / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    wizard, done = open_wizard(app, window, path)
    assert wizard.table.rows()[-1][4] == "V"
    wizard.put("col_unit", "(none)")
    pump(app, lambda: wizard.table.rows() and wizard.table.rows()[-1][4] == "")
    wizard.put("col_measured", "")
    pump(app, lambda: "measured value" in wizard.problem_label.text())
    wizard.accept()
    assert done == []  # stays open until the settings are usable
    wizard.close()


def test_wizard_recognises_i3070_logs_and_shows_what_it_reads(app, window, tmp_path):
    files = make_ict_folder(tmp_path / "ict")
    wizard, done = open_wizard(app, window, files[0])
    wait_for_status(app, wizard, "components read")
    assert wizard.kind == "text" and wizard.value("block") == "{@BLOCK|[Component]|00"
    assert wizard.value("measure") == "{@A-[Unit]|[Any]|[Measured]" and wizard.value("sn_example") == "VSE2C00000112"
    assert "VSE2C00000112" in wizard.status_label.text() and "3 components read" in wizard.status_label.text()
    assert wizard.rule_status["block"].text() == "found on 3 lines"
    marked = [selection.cursor.selectedText() for selection in wizard.viewer.extraSelections()
              if selection.format.background().color().name() == "#b9d7fa"]  # the colour of a component
    assert marked == ["1%r114", "c23", "u1107"]
    pump(app, lambda: bool(wizard.folder_label.text()))
    assert wizard.folder_label.text() == "The other 3 files in this folder can be read with these settings too."
    wizard.accept()
    profile = done[0][1]
    assert profile["block_template"] == "{@BLOCK|[Component]|00" and profile["sn_example"] == "VSE2C00000112"


def test_wizard_learns_an_unknown_text_format_from_selected_text(app, window, tmp_path):
    sample = tmp_path / "UNIT-8841_run1.txt"
    sample.write_text("Board report\n\nTESTING R101\n   RESULT 4.71 V   LIMITS 4.50 .. 4.90\n\nTESTING U7 VCC\n"
                      "   RESULT 3.31 V   LIMITS 3.00 .. 3.60\n", encoding="utf-8")
    wizard, done = open_wizard(app, window, sample)
    assert "do not know this log format" in wizard.findings.text() and wizard.value("block") == ""
    wizard.accept()  # nothing to read yet
    assert "Fill in the component line" in wizard.problem_label.text() and done == []
    for line, text, blank in ((3, "R101", "Component"), (4, "4.71", "Measured"), (4, "V", "Unit"), (4, "4.50", "Min"), (4, "4.90", "Max")):
        select_text(wizard, line, text)
        wizard._mark(blank)
    assert wizard.value("block") == "TESTING [Component]"
    assert wizard.value("measure") == "RESULT [Measured] [Unit]" and wizard.value("lim2") == "LIMITS [Min] .. [Max]"
    wait_for_status(app, wizard, "2 components read")
    assert rows_of(wizard) == ["R101", "U7 VCC"] and wizard.table.rows()[1][1:] == ("3.31", "3.00", "3.60", "V")
    wizard.accept()
    profile = done[0][1]
    assert parse_log_file(sample, profile).entries["U7 VCC"].max_value == "3.60"


def test_wizard_explains_a_selection_that_cannot_be_used(app, window, tmp_path):
    wizard, _done = open_wizard(app, window, make_ict_folder(tmp_path / "ict")[0])
    cursor = wizard.viewer.textCursor()
    cursor.clearSelection()
    wizard.viewer.setTextCursor(cursor)
    wizard._mark("Component")
    assert "Select some text" in wizard.problem_label.text()
    cursor.setPosition(wizard.viewer.document().findBlockByNumber(5).position())
    cursor.setPosition(wizard.viewer.document().findBlockByNumber(7).position() + 3, QTextCursor.MoveMode.KeepAnchor)
    wizard.viewer.setTextCursor(cursor)
    wizard._mark("Component")
    assert "single line" in wizard.problem_label.text()
    wizard.put("block", "{@BLOCK|")
    pump(app, lambda: "needs [Component]" in wizard.problem_label.text())
    assert wizard.rule_status["block"].text() == "cannot use this pattern"
    wizard.close()


def test_a_sample_that_cannot_be_opened_says_so(app, window, tmp_path):
    wizard = SampleWizard(window, lambda name, profile: None)
    wizard.present()
    wizard.load_sample(tmp_path / "missing.log")
    assert "Could not open that file" in wizard.findings.text() and not wizard.accept_button.isEnabled()
    wizard.close()
