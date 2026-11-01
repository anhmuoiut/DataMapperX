"""Create, duplicate, edit and delete scan profiles."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_TITLE, EXCEL_FILE_EXTENSIONS, TEXT_FILE_EXTENSIONS
from ..patterns import TemplateError, compile_template, sn_regex_from_example
from ..profiles import (
    BUILT_IN_PROFILE_NAMES,
    PATTERN_FIELDS,
    patterns_from_profile,
    save_profiles,
    validate_profile,
)
from .dialogs import Dialog, label
from .widgets import make_button

REGEX_HELP = (
    "Most people never need this: press 'Set up from a sample…' instead.\n\n"
    "To extract data from text logs yourself, use Python regular expressions.\n\n"
    "RECOMMENDED GROUPS\n"
    "• Name_Regex: capture the component as (?P<component>...)\n"
    "• Measure_Regex: capture the value as (?P<measured>...)\n"
    "  Optional: (?P<type>...) for the unit and (?P<tail>...) for the rest of the line (limits)\n"
    "• Min/Max regex: capture (?P<min>...) and (?P<max>...)\n\n"
    "TIP\n"
    "Select a built-in profile and press Duplicate to start from a working example, "
    "then use the live tester below to check your changes against a pasted line."
)

_TEXT_FIELDS = ("block_regex", "measure_regex", "lim2_regex", "lim3_regex")
_EXCEL_FIELDS = (
    ("sn_sheet", ""), ("data_sheet", ""), ("row_start", "2"), ("component_col", "A"),
    ("measure_col", "B"), ("min_col", "C"), ("max_col", "D"), ("unit_col", "E"),
)
_PATTERN_TITLES = (("block", "Component line"), ("measure", "Measurement line"), ("lim2", "Limits (A)"), ("lim3", "Limits (B)"))
_UNNAMED = "New profile"


def _mono() -> QFont:
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class ProfileManager(Dialog):
    def __init__(self, parent: QWidget, profiles: dict[str, dict], on_changed: Callable[[str | None], None]) -> None:
        """``profiles`` is edited in place. ``on_changed(name)`` runs after a save (name) or delete (None)."""
        super().__init__(parent, "Manage profiles", modal=False, size=(860, 640), min_size=(780, 600))
        self.profiles = profiles
        self.on_changed = on_changed
        self.original_name = ""
        self.extra: dict[str, Any] = {}  # fill-in-the-blank patterns and the example serial number of the loaded profile
        self._loading = False
        self._guarded: list[QWidget] = []  # the fields a built-in profile makes read-only

        self.fields: dict[str, QLineEdit] = {}
        for name in ("name", "extensions", "sn_regex", *_TEXT_FIELDS, *(f for f, _ in _EXCEL_FIELDS), "test_input"):
            self.fields[name] = QLineEdit()
        self.sn_regex_text = QLineEdit()  # the same value as fields["sn_regex"], shown among the regular expressions
        for name in ("sn_regex", *_TEXT_FIELDS):
            self.fields[name].setFont(_mono())
        self.sn_regex_text.setFont(_mono())
        self.type_box = QComboBox()
        self.type_box.addItems(["text", "excel"])
        self.skip_empty = QCheckBox("Ignore heading rows that have no result")
        self.skip_empty.setChecked(True)
        self.summary = label("", wrap=True)
        self.summary.setFont(_mono())
        self.test_result = label("Result: ", wrap=True)

        main = QHBoxLayout()
        main.setSpacing(14)
        main.addLayout(self._build_list())
        main.addWidget(self._build_editor(), 1)
        self.layout_root.addLayout(main, 1)

        self.type_box.currentTextChanged.connect(lambda _text: self._show_fields())
        self.sn_regex_text.textEdited.connect(lambda text: self.fields["sn_regex"].setText(text))
        self.fields["sn_regex"].textChanged.connect(lambda text: self._mirror_sn_regex(text))
        for name in ("test_input", *_TEXT_FIELDS):
            self.fields[name].textChanged.connect(lambda _text: self._evaluate_test())
        for name in (*_TEXT_FIELDS, "sn_regex"):
            self.fields[name].textChanged.connect(lambda _text: self._update_summary())

        self._refresh_list()
        if self.profiles:
            self.listbox.setCurrentRow(0)

    # ------------------------------------------------------------------ layout
    def _build_list(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.addWidget(label("Profiles", "heading"))
        self.listbox = QListWidget()
        self.listbox.setMinimumWidth(190)
        self.listbox.currentRowChanged.connect(lambda _row: self._on_select())
        column.addWidget(self.listbox, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.new_button = make_button("New", self._new_from_sample)
        self.duplicate_button = make_button("Duplicate", self._duplicate)
        self.delete_button = make_button("Delete", self._delete)
        for button in (self.new_button, self.duplicate_button, self.delete_button):
            row.addWidget(button)
        column.addLayout(row)
        return column

    def _build_editor(self) -> QGroupBox:
        box = QGroupBox("Edit profile")
        layout = QVBoxLayout(box)
        self.notice = label("", "muted", wrap=True)
        layout.addWidget(self.notice)
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        form.addWidget(label("Profile name:"), 0, 0)
        form.addWidget(self.fields["name"], 0, 1)
        form.addWidget(label("Input type:"), 1, 0)
        form.addWidget(self.type_box, 1, 1)
        form.addWidget(label("File extensions:"), 2, 0)
        form.addWidget(self.fields["extensions"], 2, 1)
        layout.addLayout(form)
        wizard = QHBoxLayout()
        self.wizard_button = make_button("Set up from a sample…", self._open_wizard, primary=True)
        wizard.addWidget(self.wizard_button)
        wizard.addWidget(label("Pick one example log and the app works out where the data is. No regular expressions needed.",
                               "muted", wrap=True), 1)
        layout.addLayout(wizard)

        self.stack_host = QWidget()
        self.stack = QStackedLayout(self.stack_host)
        self.text_frame, self.excel_frame = self._build_text_frame(), self._build_excel_frame()
        self.stack.addWidget(self.text_frame)
        self.stack.addWidget(self.excel_frame)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.stack_host)
        layout.addWidget(scroll, 1)

        self.save_button = make_button("Save profile", self._save, primary=True)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        self._guarded = [*(self.fields[n] for n in ("name", "extensions", "sn_regex", *_TEXT_FIELDS,
                                                      *(f for f, _ in _EXCEL_FIELDS))),
                         self.sn_regex_text, self.type_box, self.save_button, self.wizard_button, self.skip_empty]
        return box

    def _build_text_frame(self) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(label("What this profile reads", "heading"))
        layout.addWidget(self.summary)
        self.advanced_toggle = make_button("Advanced: regular expressions  ▸", self._toggle_advanced)
        layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced_frame = QWidget()
        adv = QGridLayout(self.advanced_frame)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setColumnStretch(1, 1)
        adv.addWidget(label("SN_Regex:"), 0, 0)
        adv.addWidget(self.sn_regex_text, 0, 1)
        adv.addWidget(make_button("Regex guide", lambda: QMessageBox.information(self, "Regex guide", REGEX_HELP)), 1, 0, 1, 2,
                      Qt.AlignmentFlag.AlignLeft)
        for row, (key, title) in enumerate((("block_regex", "Name_Regex:"), ("measure_regex", "Measure_Regex:"),
                                            ("lim2_regex", "Min_Max_Regex1:"), ("lim3_regex", "Min_Max_Regex2:")), start=2):
            adv.addWidget(label(title), row, 0)
            adv.addWidget(self.fields[key], row, 1)
        tester = QGroupBox("Live regex tester")
        tester_layout = QVBoxLayout(tester)
        tester_layout.addWidget(label("Paste a data row from a log:"))
        tester_layout.addWidget(self.fields["test_input"])
        tester_layout.addWidget(self.test_result)
        adv.addWidget(tester, 6, 0, 1, 2)
        self.advanced_frame.setVisible(False)
        layout.addWidget(self.advanced_frame)
        layout.addStretch(1)
        return frame

    def _build_excel_frame(self) -> QWidget:
        frame = QWidget()
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        titles = {"sn_sheet": "SN_Sheet:", "data_sheet": "Data_Sheet:", "row_start": "Row_Start:", "component_col": "Component_Col:",
                  "measure_col": "Measure_Col:", "min_col": "Min_Col:", "max_col": "Max_Col:", "unit_col": "Unit_Col (blank if none):"}
        grid.addWidget(label("Serial number:"), 0, 0)
        grid.addWidget(self.fields["sn_regex"], 0, 1)
        grid.addWidget(label("A cell such as B1, or a pattern for the file name. Blank: search the file name and cells.", "muted",
                             wrap=True), 1, 1)
        for row, (key, _default) in enumerate(_EXCEL_FIELDS, start=2):
            grid.addWidget(label(titles[key]), row, 0)
            grid.addWidget(self.fields[key], row, 1)
        grid.addWidget(self.skip_empty, 10, 1)
        grid.setRowStretch(11, 1)
        return frame

    def _mirror_sn_regex(self, text: str) -> None:
        if self.sn_regex_text.text() != text:
            self.sn_regex_text.setText(text)

    def _toggle_advanced(self) -> None:
        opened = not self.advanced_frame.isVisible()
        self.advanced_frame.setVisible(opened)
        self.advanced_toggle.setText("Advanced: regular expressions  " + ("▾" if opened else "▸"))

    def _show_fields(self) -> None:
        self.stack.setCurrentWidget(self.excel_frame if self.type_box.currentText() == "excel" else self.text_frame)

    # ------------------------------------------------------------------ state
    def selected_name(self) -> str | None:
        item = self.listbox.currentItem()
        return item.text() if item is not None else None

    def _refresh_list(self, select: str | None = None) -> None:
        self.listbox.blockSignals(True)
        self.listbox.clear()
        self.listbox.addItems(list(self.profiles))
        if select and select in self.profiles:
            self.listbox.setCurrentRow(list(self.profiles).index(select))
        self.listbox.blockSignals(False)

    def _set_readonly(self, readonly: bool) -> None:
        for widget in self._guarded:
            if isinstance(widget, QLineEdit):
                widget.setReadOnly(readonly)
            else:
                widget.setEnabled(not readonly)

    def set(self, name: str, value: str) -> None:
        self.fields[name].setText(value)

    def get(self, name: str) -> str:
        return self.fields[name].text()

    def _load(self, name: str, data: dict) -> None:
        self._loading = True
        self.set("name", name)
        kind = data.get("type", "text")
        self.type_box.setCurrentText(kind)
        defaults = TEXT_FILE_EXTENSIONS if kind == "text" else EXCEL_FILE_EXTENSIONS
        raw_ext = data.get("file_extensions") or ",".join(defaults)
        self.set("extensions", raw_ext if isinstance(raw_ext, str) else ",".join(raw_ext))
        self.set("sn_regex", data.get("sn_regex", ""))
        for key in _TEXT_FIELDS:
            self.set(key, data.get(key, ""))
        for key, default in _EXCEL_FIELDS:
            self.set(key, str(data.get(key, default)))
        self.skip_empty.setChecked(data.get("skip_empty_rows", True) is not False)
        self.extra = {k: data[k] for k in (*(f"{n}_template" for n in PATTERN_FIELDS), "sn_example") if data.get(k)}
        self.set("test_input", "")
        self.test_result.setText("Result: ")
        self._loading = False
        self._update_summary()
        self._show_fields()

    def _on_select(self) -> None:
        name = self.selected_name()
        if name is None or name not in self.profiles:
            return
        self.original_name = name
        self._load(name, self.profiles[name])
        built_in = name in BUILT_IN_PROFILE_NAMES
        self._set_readonly(built_in)
        self.notice.setText("Built-in profile (read-only). Press Duplicate to make an editable copy." if built_in else "")

    def _new(self) -> None:
        self.listbox.blockSignals(True)
        self.listbox.setCurrentRow(-1)
        self.listbox.clearSelection()
        self.listbox.blockSignals(False)
        self.original_name = ""
        self._load(_UNNAMED, {"type": "text", "file_extensions": ",".join(TEXT_FILE_EXTENSIONS)})
        self._set_readonly(False)
        self.notice.setText("")
        self.fields["name"].setFocus()
        self.fields["name"].selectAll()

    def _new_from_sample(self) -> None:
        """A blank profile, with the sample wizard on top. Cancelling the wizard leaves the blank form to fill in by hand."""
        self._new()
        self._open_wizard()

    def _duplicate(self) -> None:
        source = self.selected_name()
        if source is None:
            QMessageBox.information(self, APP_TITLE, "Select a profile to duplicate first.")
            return
        self.listbox.blockSignals(True)
        self.listbox.setCurrentRow(-1)
        self.listbox.clearSelection()
        self.listbox.blockSignals(False)
        self.original_name = ""
        base, n = f"{source} (copy)", 2
        new_name = base
        while new_name in self.profiles:
            new_name, n = f"{base} {n}", n + 1
        self._load(new_name, self.profiles[source])
        self._set_readonly(False)
        self.notice.setText("Editing a copy. Press Save profile to keep it.")
        self.fields["name"].setFocus()

    def _delete(self) -> None:
        name = self.selected_name()
        if name is None:
            return
        if name in BUILT_IN_PROFILE_NAMES:
            QMessageBox.critical(self, APP_TITLE, "Built-in profiles cannot be deleted.")
            return
        if QMessageBox.question(self, "Delete profile", f"Delete '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        del self.profiles[name]
        save_profiles(self.profiles)
        self._refresh_list()
        self.original_name = ""
        self.on_changed(None)
        if self.profiles:
            self.listbox.setCurrentRow(0)

    # ------------------------------------------------------------------ the sample wizard
    def _open_wizard(self) -> None:
        from .sample_wizard import SampleWizard

        if not self.wizard_button.isEnabled():
            QMessageBox.information(self, APP_TITLE, "Built-in profiles cannot be changed. Press Duplicate first.")
            return
        name = self.get("name").strip()
        try:
            current: dict[str, Any] | None = self._collect()
            if not (current.get("block_regex") or current.get("measure_regex") or current.get("component_col")):
                current = None
        except (KeyError, ValueError):
            current = None
        SampleWizard(self, self._wizard_done, initial=current, initial_name="" if name in ("", _UNNAMED) else name).present()

    def _wizard_done(self, name: str, profile: dict[str, Any]) -> None:
        keep_name = self.get("name").strip()
        if keep_name in ("", _UNNAMED) or keep_name in BUILT_IN_PROFILE_NAMES:
            keep_name = self._unused_name(name)
        self._load(keep_name, profile)
        self._set_readonly(False)
        self.notice.setText("Filled in from your sample. Check the name, then press Save profile.")

    def _unused_name(self, wanted: str) -> str:
        if wanted not in self.profiles and wanted not in BUILT_IN_PROFILE_NAMES:
            return wanted
        n = 2
        while f"{wanted} {n}" in self.profiles:
            n += 1
        return f"{wanted} {n}"

    def _update_summary(self) -> None:
        if self._loading:
            return
        try:
            data = self._collect()
        except (KeyError, ValueError):
            return
        if data.get("type") != "text":
            return
        patterns, custom = patterns_from_profile(data)
        lines = []
        for key, title in _PATTERN_TITLES:
            if key in patterns:
                lines.append(f"{title}:  {patterns[key]}")
            elif key in custom:
                lines.append(f"{title}:  regular expression (see Advanced)")
        if data.get("sn_example"):
            lines.append(f"Serial number:  looks like {data['sn_example']}")
        self.summary.setText("\n".join(lines) if lines else "Nothing set up yet. Press 'Set up from a sample…'.")

    # ------------------------------------------------------------------ save
    def _collect(self) -> dict:
        data: dict = {"type": self.type_box.currentText(), "sn_regex": self.get("sn_regex")}
        extensions = self.get("extensions").strip()
        if data["type"] == "text":
            data["file_extensions"] = extensions or ",".join(TEXT_FILE_EXTENSIONS)
            for key in _TEXT_FIELDS:
                data[key] = self.get(key)
            self._keep_matching_patterns(data)
        else:
            data["file_extensions"] = extensions or ",".join(EXCEL_FILE_EXTENSIONS)
            for key, _default in _EXCEL_FIELDS:
                data[key] = self.get(key)
            data["skip_empty_rows"] = self.skip_empty.isChecked()
            example = self.extra.get("sn_example")
            if example and self._sn_matches(example, data["sn_regex"]):
                data["sn_example"] = example
        return data

    def _keep_matching_patterns(self, data: dict) -> None:
        """Keep the readable patterns only while they still describe the regular expressions (which may have been edited)."""
        for name, (regex_key, rule) in PATTERN_FIELDS.items():
            template = self.extra.get(f"{name}_template", "")
            try:
                if template and compile_template(template, rule) == data[regex_key]:
                    data[f"{name}_template"] = template
            except TemplateError:
                pass
        example = self.extra.get("sn_example")
        if example and self._sn_matches(example, data["sn_regex"]):
            data["sn_example"] = example

    @staticmethod
    def _sn_matches(example: str, regex: str) -> bool:
        try:
            return sn_regex_from_example(example) == regex
        except TemplateError:
            return False

    def _save(self) -> None:
        name = self.get("name").strip()
        if not name:
            QMessageBox.warning(self, APP_TITLE, "Profile name cannot be empty.")
            return
        if name in BUILT_IN_PROFILE_NAMES:
            QMessageBox.warning(self, APP_TITLE, "Cannot override built-in profiles. Choose another name.")
            return
        data = self._collect()
        try:
            validate_profile(data)
        except ValueError as exc:
            QMessageBox.critical(self, APP_TITLE, str(exc))
            return
        replacing_other = name in self.profiles and name != self.original_name
        if replacing_other and QMessageBox.question(
                self, APP_TITLE, f"A profile named '{name}' already exists. Replace it?") != QMessageBox.StandardButton.Yes:
            return
        if self.original_name and self.original_name != name and self.original_name not in BUILT_IN_PROFILE_NAMES:
            self.profiles.pop(self.original_name, None)
        self.profiles[name] = data
        save_profiles(self.profiles)
        self.original_name = name
        self._refresh_list(select=name)
        self.notice.setText("")
        self.on_changed(name)
        QMessageBox.information(self, "Saved", f"Profile '{name}' saved.")

    # ------------------------------------------------------------------ live tester
    def _evaluate_test(self) -> None:
        data = self.get("test_input").strip()
        if not data:
            self.test_result.setText("Result: No data")
            return
        try:
            block_pattern, measure_pattern = self.get("block_regex").strip(), self.get("measure_regex").strip()
            if block_pattern:
                match = re.search(block_pattern, data, re.IGNORECASE)
                if match:
                    if "component" in match.groupdict():
                        self.test_result.setText(f"Result: MATCHED BLOCK - Component: {match.group('component')}")
                    elif match.groups():
                        self.test_result.setText(f"Result: MATCHED BLOCK - Component: {match.group(1)}")
                    else:
                        self.test_result.setText("Result: Matched the block but found no component group")
                    return
            if measure_pattern:
                match = re.search(measure_pattern, data, re.IGNORECASE)
                if match:
                    self.test_result.setText("Result: MATCHED MEASURE - " + self._describe_measure(match, data))
                    return
            self.test_result.setText("Result: Format not recognized with the current regexes")
        except re.error as exc:
            self.test_result.setText(f"Result: Regex error - {exc}")

    def _describe_measure(self, match: re.Match, data: str) -> str:
        groups = match.groupdict()
        parts = []
        if "measured" in groups:
            parts.append(f"Measured: {match.group('measured')}")
        elif match.groups():
            parts.append(f"Measured: {match.group(1)}")
        tail = match.group("tail") if "tail" in groups else data
        limits_found = False
        for pattern in (self.get("lim2_regex").strip(), self.get("lim3_regex").strip()):
            if not pattern:
                continue
            limit = re.search(pattern, tail or "")
            if limit:
                limits_found = True
                found = limit.groupdict()
                parts.append(f"Min: {limit.group('min')}" if "min" in found else "Min: ?")
                parts.append(f"Max: {limit.group('max')}" if "max" in found else "Max: ?")
                break
        if not parts:
            parts.append("Matched, but no measured group found")
        if not limits_found:
            parts.append("Limits: not found")
        return ", ".join(parts)
