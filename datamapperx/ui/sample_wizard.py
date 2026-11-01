"""Set up a profile from a sample log, without writing a regular expression.

The person picks one example file. The app works out the layout (Excel columns, serial number cell, or the
standard test-log patterns), shows exactly which parts of the sample it reads, and lets them correct it:
for Excel by choosing columns by their headings, for text logs by selecting text in the sample and pressing
what it is.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..config import APP_TITLE, EXCEL_FILE_EXTENSIONS, TEXT_FILE_EXTENSIONS
from ..parsing import extract_sn_from_text, read_text_file
from ..patterns import (
    RULE_FOR_BLANK,
    RULES,
    TemplateError,
    compile_template,
    sn_regex_from_example,
    template_from_marks,
)
from ..profiles import PATTERN_FIELDS, patterns_from_profile, text_profile_from_patterns, validate_profile
from ..sampling import (
    Detection,
    FolderCheck,
    Highlight,
    Preview,
    WorkbookSketch,
    annotate_text,
    check_files,
    detect_excel,
    detect_text,
    is_excel,
    preview_profile,
    sibling_files,
)
from ..utils import looks_like_cell_coordinate, parse_positive_int
from .dialogs import Dialog, label
from .tasks import TaskRunner
from .widgets import DataTable, make_button, repolish

logger = logging.getLogger(__name__)

NONE_LABEL = "(none)"
MAX_VIEW_LINES = 1500
MAX_ANNOTATED_LINES = 20000
REFRESH_MS = 280
FOLDER_CHECK_FILES = 8

# Colours for the parts of the sample that the profile reads, per theme.
ROLE_COLORS = {
    "light": {
        "block": "#eaf2fc", "measure": "#edf7ef", "component": "#b9d7fa", "measured": "#b4e5c6",
        "unit": "#dccbf5", "min": "#ffd9a0", "max": "#ffc0c7", "serial": "#fff09a",
    },
    "dark": {
        "block": "#1f2f43", "measure": "#1f3328", "component": "#2a5d94", "measured": "#27663f",
        "unit": "#59447f", "min": "#80571a", "max": "#80333c", "serial": "#7d6d1a",
    },
}
ROLE_ORDER = ("block", "measure", "component", "measured", "unit", "min", "max", "serial")  # later ones paint over earlier ones
LEGEND = (("component", "Component"), ("measured", "Measured value"), ("unit", "Unit"),
          ("min", "Lower limit"), ("max", "Upper limit"), ("serial", "Serial number"))
MARK_BUTTONS = (("Component", "Component"), ("Measured value", "Measured"), ("Unit", "Unit"),
                ("Lower limit", "Min"), ("Upper limit", "Max"), ("Ignore", "Any"))
RULE_ROWS = (
    ("block", "Component line"),
    ("measure", "Measurement line"),
    ("lim2", "Limits, style A (optional)"),
    ("lim3", "Limits, style B (optional)"),
)
EXCEL_COLUMNS = (
    ("col_component", "component_col", "Component / test name", True),
    ("col_measured", "measure_col", "Measured value", True),
    ("col_min", "min_col", "Lower limit", False),
    ("col_max", "max_col", "Upper limit", False),
    ("col_unit", "unit_col", "Unit", False),
)


def _mono(size: float | None = None) -> QFont:
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    if size:
        font.setPointSizeF(size)
    return font


def _set_kind(widget: QLabel, kind: str) -> None:
    """Colour a status line: ``ok``, ``bad``, ``warn`` or the quiet default."""
    widget.setProperty("role", {"ok": "ok", "bad": "bad", "warn": "warn"}.get(kind, "muted"))
    repolish(widget)


class SampleWizard(Dialog):
    """``on_done(name, profile)`` runs when the person accepts the settings."""

    def __init__(self, parent: QWidget, on_done: Callable[[str, dict[str, Any]], None], *,
                 initial: dict[str, Any] | None = None, initial_name: str = "", sample: Path | None = None) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        super().__init__(parent, "Set up from a sample log", size=(1040, min(860, max(620, screen.height() - 90))), min_size=(940, 620))
        self.on_done = on_done
        self._initial = initial
        self._name = initial_name
        self.sample: Path | None = None
        self.siblings: list[Path] = []
        self.kind = ""
        self.sketch: WorkbookSketch | None = None
        self.detection: Detection | None = None
        self._lines: list[str] = []
        self._annotated_text = ""
        self._extensions = ",".join(TEXT_FILE_EXTENSIONS)
        self._marks: dict[str, tuple[int, list[tuple[int, int, str]]]] = {}
        self._last_rule = ""
        self._generation = 0
        self._loading = False
        self._tasks = TaskRunner(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh)

        self.rule_edits: dict[str, QLineEdit] = {key: QLineEdit() for key, _title in RULE_ROWS}
        self.sn_example = QLineEdit()  # on the text panel
        self.sn_example_excel = QLineEdit()  # the same value on the Excel panel
        self.sn_sheet, self.data_sheet = QComboBox(), QComboBox()
        self.sn_cell = QLineEdit()
        self.sn_value = label("", "muted")
        self.row_start = QSpinBox()
        self.row_start.setRange(1, 999)
        self.row_start.setValue(2)
        self.sn_mode_cell, self.sn_mode_name = QRadioButton("In a cell"), QRadioButton("In the file name, looking like")
        self.sn_mode_cell.setChecked(True)
        mode = QButtonGroup(self)
        mode.addButton(self.sn_mode_cell)
        mode.addButton(self.sn_mode_name)
        self.column_combos: dict[str, QComboBox] = {var: QComboBox() for var, *_ in EXCEL_COLUMNS}
        self.skip_empty = QCheckBox("Ignore heading rows that have no result")
        self.skip_empty.setChecked(True)
        self.rule_status = {key: label("", "muted") for key, _title in (*RULE_ROWS, ("sn_example", ""))}

        self._build()
        for edit in (*self.rule_edits.values(), self.sn_example, self.sn_example_excel, self.sn_cell):
            edit.textChanged.connect(self._on_change)
        for combo in (self.sn_sheet, self.data_sheet, *self.column_combos.values()):
            combo.currentTextChanged.connect(self._on_change)
        for toggle in (self.sn_mode_cell, self.sn_mode_name, self.skip_empty):
            toggle.toggled.connect(self._on_change)
        self.row_start.valueChanged.connect(self._on_change)
        self.data_sheet.currentTextChanged.connect(self._on_table_change)
        self.row_start.valueChanged.connect(self._on_table_change)
        self.sn_example.textEdited.connect(self.sn_example_excel.setText)
        self.sn_example_excel.textEdited.connect(self.sn_example.setText)

        if sample is not None:
            QTimer.singleShot(0, lambda: self.load_sample(sample))
        else:
            QTimer.singleShot(120, self.choose_sample)

    # ------------------------------------------------------------------ layout
    def _section(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.addWidget(label(title, "heading"))
        return card, inner

    def _build(self) -> None:
        root = self.layout_root
        root.setSpacing(10)
        top, top_layout = self._section("1   Choose one example log")
        head = QHBoxLayout()
        self.sample_label = label("", "muted", wrap=True)
        head.addWidget(self.sample_label, 1)
        self.choose_button = make_button("Choose file…", self.choose_sample)
        head.addWidget(self.choose_button)
        top_layout.addLayout(head)
        self.findings = label("", "muted", wrap=True)
        top_layout.addWidget(self.findings)
        root.addWidget(top)

        self.workspace, self.workspace_layout = self._section("2   Tell the app where the data is")
        self.placeholder = label("Pick an example log file first. The app will look at it and fill in the settings for you.", "muted",
                                 wrap=True)
        self.workspace_layout.addWidget(self.placeholder, 1)
        self.text_panel = self._build_text_panel()
        self.excel_panel = self._build_excel_panel()
        self.workspace_layout.addWidget(self.text_panel, 1)
        self.workspace_layout.addWidget(self.excel_panel, 1)
        self.text_panel.hide()
        self.excel_panel.hide()
        root.addWidget(self.workspace, 1)

        self.result = QWidget()
        result_layout = QVBoxLayout(self.result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(label("3   Check what will be read", "heading"))
        self.status_label = label("", "muted", wrap=True)
        result_layout.addWidget(self.status_label)
        self.table = DataTable(self.palette_tokens)
        self.table.setMaximumHeight(170)
        self._clear_table()
        result_layout.addWidget(self.table)
        self.folder_label = label("", "muted", wrap=True)
        result_layout.addWidget(self.folder_label)
        self._outer_index = root.count()
        root.addWidget(self.result)
        self.result.hide()

        footer = QHBoxLayout()
        self.problem_label = label("", "bad", wrap=True)
        footer.addWidget(self.problem_label, 1)
        footer.addWidget(make_button("Cancel", self.close))
        self.accept_button = make_button("Use these settings", self.accept, primary=True)
        self.accept_button.setEnabled(False)
        footer.addWidget(self.accept_button)
        root.addLayout(footer)

    def _build_text_panel(self) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        rules = QVBoxLayout()
        head = QHBoxLayout()
        head.addWidget(label("Serial number looks like"))
        head.addStretch(1)
        head.addWidget(self.rule_status["sn_example"])
        rules.addLayout(head)
        sn_row = QHBoxLayout()
        sn_row.addWidget(self.sn_example, 1)
        sn_row.addWidget(make_button("Use selection", self._mark_serial))
        rules.addLayout(sn_row)
        for key, title in RULE_ROWS:
            head = QHBoxLayout()
            head.addWidget(label(title))
            head.addStretch(1)
            head.addWidget(self.rule_status[key])
            rules.addLayout(head)
            row = QHBoxLayout()
            edit = self.rule_edits[key]
            edit.setFont(_mono(10))
            edit.textEdited.connect(lambda _text, k=key: self._marks.pop(k, None))
            row.addWidget(edit, 1)
            clear = make_button("×", lambda k=key: self._clear_rule(k))
            clear.setFixedWidth(34)
            row.addWidget(clear)
            rules.addLayout(row)
        rules.addWidget(label("A pattern is text from the log with the parts that change replaced by blanks: [Component], "
                              "[Measured], [Unit], [Min], [Max], or [Any] for a part to skip.", "muted", wrap=True))
        rules.addStretch(1)
        rules_host = QWidget()
        rules_host.setLayout(rules)
        rules_host.setFixedWidth(360)
        layout.addWidget(rules_host)

        self.text_right = QVBoxLayout()
        self.text_right.addWidget(label("Select the part of a line that changes, then press what it is:", wrap=True))
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for title, blank in MARK_BUTTONS:
            buttons.addWidget(make_button(title, lambda b=blank: self._mark(b)))
        buttons.addStretch(1)
        self.text_right.addLayout(buttons)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.viewer.setFont(_mono(10))
        self.text_right.addWidget(self.viewer, 1)
        legend = QHBoxLayout()
        self._legend_labels: list[tuple[QLabel, str]] = []
        for role, title in LEGEND:
            tag = QLabel(f" {title} ")
            self._legend_labels.append((tag, role))
            legend.addWidget(tag)
        legend.addStretch(1)
        self.text_right.addLayout(legend)
        self._paint_legend()
        layout.addLayout(self.text_right, 1)
        return panel

    def _build_excel_panel(self) -> QWidget:
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("Where is the serial number?"), 0, 0, 1, 4)
        cell_row = QHBoxLayout()
        cell_row.addWidget(self.sn_mode_cell)
        cell_row.addWidget(label("Sheet"))
        cell_row.addWidget(self.sn_sheet)
        cell_row.addWidget(label("Cell"))
        self.sn_cell.setMaximumWidth(80)
        cell_row.addWidget(self.sn_cell)
        cell_row.addWidget(self.sn_value)
        cell_row.addStretch(1)
        grid.addLayout(cell_row, 1, 0, 1, 4)
        name_row = QHBoxLayout()
        name_row.addWidget(self.sn_mode_name)
        self.sn_example_excel.setMinimumWidth(240)
        name_row.addWidget(self.sn_example_excel)
        name_row.addStretch(1)
        grid.addLayout(name_row, 2, 0, 1, 4)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        grid.addWidget(rule, 3, 0, 1, 4)
        grid.addWidget(label("Where is the table of results?"), 4, 0, 1, 4)
        table_row = QHBoxLayout()
        table_row.addWidget(label("Sheet"))
        table_row.addWidget(self.data_sheet)
        table_row.addSpacing(14)
        table_row.addWidget(label("Data starts on row"))
        table_row.addWidget(self.row_start)
        table_row.addWidget(label("The row above it should hold the column headings.", "muted"))
        table_row.addStretch(1)
        grid.addLayout(table_row, 5, 0, 1, 4)
        for index, (var, _key, title, _required) in enumerate(EXCEL_COLUMNS):
            row, base = 6 + index // 2, (index % 2) * 2
            grid.addWidget(label(title), row, base)
            grid.addWidget(self.column_combos[var], row, base + 1)
        grid.addWidget(self.skip_empty, 9, 0, 1, 4)
        grid.setRowStretch(10, 1)
        return panel

    def _paint_legend(self) -> None:
        colors = ROLE_COLORS[self.palette_tokens.mode]
        for tag, role in self._legend_labels:
            tag.setStyleSheet(f"background: {colors[role]}; color: {self.palette_tokens.fg}; padding: 1px 3px; border-radius: 2px;")

    def _clear_table(self) -> None:
        self.table.set_table(["Component", "Measured", "Min", "Max", "Unit"], [], aligns=["w", "w", "w", "w", "w"], stretch=0)

    # ------------------------------------------------------------------ values of the form
    def value(self, name: str) -> str:
        """The text of a rule, a combo or a field of the form by its name."""
        if name in self.rule_edits:
            return self.rule_edits[name].text()
        if name in self.column_combos:
            return self.column_combos[name].currentText()
        return {"sn_example": self.sn_example.text, "sn_sheet": self.sn_sheet.currentText, "sn_cell": self.sn_cell.text,
                "data_sheet": self.data_sheet.currentText, "row_start": lambda: str(self.row_start.value()),
                "sn_mode": lambda: "cell" if self.sn_mode_cell.isChecked() else "example"}[name]()

    def put(self, name: str, value: str) -> None:
        if name in self.rule_edits:
            self.rule_edits[name].setText(value)
        elif name in self.column_combos or name in ("sn_sheet", "data_sheet"):
            combo = self.column_combos.get(name) or (self.sn_sheet if name == "sn_sheet" else self.data_sheet)
            index = combo.findText(value)
            combo.setCurrentIndex(index if value and index >= 0 else -1)
        elif name == "sn_example":
            self.sn_example.setText(value)
            self.sn_example_excel.setText(value)
        elif name == "sn_cell":
            self.sn_cell.setText(value)
        elif name == "row_start":
            self.row_start.setValue(int(value) if value.isdigit() else 2)
        elif name == "sn_mode":
            (self.sn_mode_cell if value == "cell" else self.sn_mode_name).setChecked(True)

    def _letter(self, var: str) -> str:
        text = self.value(var)
        return "" if not text or text == NONE_LABEL else text.split()[0].upper()

    # ------------------------------------------------------------------ choosing and loading the sample
    def choose_sample(self) -> None:
        excel_types = " ".join(f"*{e}" for e in EXCEL_FILE_EXTENSIONS)
        text_types = " ".join(f"*{e}" for e in TEXT_FILE_EXTENSIONS)
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose one example log", "",
                                                f"Log files ({text_types} {excel_types});;All files (*.*)")
        if chosen:
            self.load_sample(Path(chosen))

    def load_sample(self, path: Path) -> None:
        self._loading = True
        try:
            siblings = sibling_files(path)
            if is_excel(path):
                sketch = WorkbookSketch.load(path)
                detection = detect_excel(path, siblings, sketch)
                kind, lines = "excel", []
            else:
                text = read_text_file(path)
                detection = detect_text(path, siblings)
                kind, sketch, lines = "text", None, text.splitlines()
        except (ValueError, OSError) as exc:
            self._loading = False
            self.findings.setText(f"Could not open that file: {str(exc).splitlines()[0]}")
            return

        self.sample, self.siblings, self.kind, self.sketch, self.detection = path, siblings, kind, sketch, detection
        self._lines = lines
        self._annotated_text = "\n".join(lines[:MAX_ANNOTATED_LINES])
        self._marks.clear()
        self.sample_label.setText(f"{path.name}    in    {path.parent}")
        self._extensions = str(detection.profile.get("file_extensions") or path.suffix.lower())
        self.placeholder.hide()
        self.text_panel.hide()
        self.excel_panel.hide()

        base = detection.profile
        custom_rules: list[str] = []
        if self._initial and self._initial.get("type", "text") == kind:
            base = self._initial
            self._extensions = str(base.get("file_extensions") or self._extensions)
            if kind == "text":
                custom_rules = patterns_from_profile(base)[1]
        self._place_result()
        if kind == "excel":
            self.excel_panel.show()
            self._show_excel(base)
        else:
            self.text_panel.show()
            self._show_text(base)

        notes = list(detection.notes) if base is detection.profile else ["Your saved settings are loaded."]
        if custom_rules:
            names = ", ".join(title for key, title in RULE_ROWS if key in custom_rules)
            notes.append(f"{names}: written as a regular expression, which cannot be shown here. It is replaced if you save.")
        self.findings.setText("  ".join([*notes, *detection.warnings]))
        _set_kind(self.findings, "warn" if detection.warnings or custom_rules else "hint")
        self._loading = False
        self.accept_button.setEnabled(True)
        self._refresh()

    def _place_result(self) -> None:
        """Text logs have the sample on screen, so the result goes right under it; Excel forms put it below."""
        self.result.setParent(None)  # leave the layout it was in
        if self.kind == "text":
            self.text_right.addWidget(self.result)
            self.table.setMaximumHeight(130)
        else:
            self.layout_root.insertWidget(2, self.result)
            self.table.setMaximumHeight(110)
        self.result.show()

    def _show_text(self, profile: dict[str, Any]) -> None:
        patterns, _custom = patterns_from_profile(profile)
        for key in PATTERN_FIELDS:
            self.put(key, patterns.get(key, ""))
        self.put("sn_example", str(profile.get("sn_example") or self._derive_example(profile)))
        self._render_viewer()

    def _show_excel(self, profile: dict[str, Any]) -> None:
        assert self.sketch is not None
        names = self.sketch.names
        for combo in (self.sn_sheet, self.data_sheet):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.blockSignals(False)
        data_sheet = str(profile.get("data_sheet") or "")
        self.put("data_sheet", data_sheet if data_sheet in names else (names[1] if len(names) > 1 else names[0]))
        self.put("row_start", str(profile.get("row_start") or "2"))
        self._fill_columns(profile)
        self.skip_empty.setChecked(profile.get("skip_empty_rows", True) is not False)

        rule = str(profile.get("sn_regex") or "").strip()
        sn_sheet = str(profile.get("sn_sheet") or "")
        self.put("sn_sheet", sn_sheet if sn_sheet in names else next((n for n in names if n != self.value("data_sheet")), names[0]))
        if looks_like_cell_coordinate(rule):
            self.put("sn_mode", "cell")
            self.put("sn_cell", rule.upper())
            self.put("sn_example", str(profile.get("sn_example") or ""))
        else:
            self.put("sn_mode", "example")
            self.put("sn_cell", "")
            self.put("sn_example", str(profile.get("sn_example") or self._derive_example(profile)))

    def _derive_example(self, profile: dict[str, Any]) -> str:
        """An example serial number for a profile that stores only a pattern: what that pattern finds in the sample."""
        rule = str(profile.get("sn_regex") or "").strip()
        if not rule or self.sample is None or looks_like_cell_coordinate(rule):
            return ""
        try:
            return extract_sn_from_text(self.sample.name, rule) or extract_sn_from_text(self._annotated_text, rule)
        except ValueError:
            return ""

    # ------------------------------------------------------------------ Excel columns
    def _fill_columns(self, profile: dict[str, Any] | None = None) -> None:
        """List the sheet's columns by heading. ``profile`` selects columns from saved letters; otherwise keep the current ones."""
        if self.sketch is None:
            return
        try:
            row_start = parse_positive_int(self.value("row_start"), "Row")
        except ValueError:
            return
        choices = self.sketch.columns(self.value("data_sheet"), row_start)
        by_letter = {c.letter: c.label for c in choices}
        labels = [c.label for c in choices]
        was_loading, self._loading = self._loading, True
        for var, key, _title, required in EXCEL_COLUMNS:
            current = str(profile.get(key) or "").upper() if profile is not None else self._letter(var)
            combo = self.column_combos[var]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(labels if required else [NONE_LABEL, *labels])
            combo.blockSignals(False)
            self.put(var, by_letter.get(current, "" if required else NONE_LABEL))
        self._loading = was_loading

    # ------------------------------------------------------------------ the sample viewer (text logs)
    def _render_viewer(self) -> None:
        shown = self._lines[:MAX_VIEW_LINES]
        text = "\n".join(shown)
        if len(self._lines) > MAX_VIEW_LINES:
            text += f"\n… showing the first {MAX_VIEW_LINES} of {len(self._lines)} lines"
        self.viewer.setPlainText(text)

    def _paint(self, marks: list[Highlight]) -> None:
        colors = ROLE_COLORS[self.palette_tokens.mode]
        document = self.viewer.document()
        by_role: dict[str, list[Highlight]] = {role: [] for role in ROLE_ORDER}
        for mark in marks:
            if mark.line < MAX_VIEW_LINES and mark.role in by_role:
                by_role[mark.role].append(mark)
        selections = []
        for role in ROLE_ORDER:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(colors[role]))
            for mark in by_role[role]:
                block = document.findBlockByNumber(mark.line)
                if not block.isValid():
                    continue
                cursor = QTextCursor(document)
                cursor.setPosition(block.position() + mark.start)
                cursor.setPosition(block.position() + mark.end, QTextCursor.MoveMode.KeepAnchor)
                extra = QTextEdit.ExtraSelection()
                extra.cursor, extra.format = cursor, fmt
                selections.append(extra)
        self.viewer.setExtraSelections(selections)

    def _selection(self) -> tuple[int, int, int]:
        """(line index, start, end) of the selected text, trimmed; raises ``TemplateError`` when it cannot be used."""
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            raise TemplateError("Select some text in the sample first.")
        document = self.viewer.document()
        first, last = document.findBlock(cursor.selectionStart()), document.findBlock(cursor.selectionEnd())
        line1, col1 = first.blockNumber(), cursor.selectionStart() - first.position()
        line2, col2 = last.blockNumber(), cursor.selectionEnd() - last.position()
        if line1 >= min(len(self._lines), MAX_VIEW_LINES):
            raise TemplateError("Select text from the log, not from this note.")
        text = self._lines[line1]
        if line2 == line1 + 1 and col2 == 0:
            col2 = len(text)
        elif line2 != line1:
            raise TemplateError("Select text within a single line.")
        chosen = text[col1:col2]
        col1 += len(chosen) - len(chosen.lstrip())
        col2 -= len(chosen) - len(chosen.rstrip())
        if col2 <= col1:
            raise TemplateError("Select some text in the sample first.")
        return line1, col1, col2

    def _limits_key(self, line_index: int) -> str:
        for key in ("lim2", "lim3"):
            state = self._marks.get(key)
            if state and state[0] == line_index:
                return key
        return next((k for k in ("lim2", "lim3") if not self.value(k).strip()), "lim2")

    def _mark(self, blank: str) -> None:
        try:
            line_index, start, end = self._selection()
            line = self._lines[line_index]
            rule = RULE_FOR_BLANK.get(blank) or self._last_rule
            if not rule:
                raise TemplateError("Mark a component or a measured value first, then use Ignore for parts that change.")
            key = {"block": "block", "measure": "measure", "limits": self._limits_key(line_index)}[rule]
            source, marks = self._marks.get(key, (line_index, []))
            if source != line_index:
                marks = []
            marks = [m for m in marks if m[2] != blank or blank == "Any"]
            marks = [m for m in marks if m[1] <= start or m[0] >= end]
            marks.append((start, end, blank))
            self.put(key, template_from_marks(line, marks, rule))
        except TemplateError as exc:
            self.problem_label.setText(str(exc))
            return
        self._marks[key] = (line_index, marks)
        self._last_rule = rule
        self.problem_label.setText("")

    def _mark_serial(self) -> None:
        try:
            line_index, start, end = self._selection()
        except TemplateError as exc:
            self.problem_label.setText(str(exc))
            return
        self.put("sn_example", self._lines[line_index][start:end])
        self.problem_label.setText("")

    def _clear_rule(self, key: str) -> None:
        self._marks.pop(key, None)
        self.put(key, "")

    # ------------------------------------------------------------------ building the profile from the form
    def collect_profile(self) -> dict[str, Any]:
        """The profile described by the form. Raises ``TemplateError`` with a message for the person."""
        return self._collect_excel() if self.kind == "excel" else self._collect_text()

    def _collect_text(self) -> dict[str, Any]:
        patterns = {key: self.value(key).strip() for key in PATTERN_FIELDS}
        if not patterns["block"] or not patterns["measure"]:
            raise TemplateError("Fill in the component line and the measurement line: select text in the sample and press a button.")
        profile = text_profile_from_patterns(patterns, self.value("sn_example"), self._extensions)
        validate_profile(profile)
        return profile

    def _collect_excel(self) -> dict[str, Any]:
        if not self._letter("col_component"):
            raise TemplateError("Choose the column that holds the test or component name.")
        if not self._letter("col_measured"):
            raise TemplateError("Choose the column that holds the measured value.")
        try:
            row_start = parse_positive_int(self.value("row_start"), "Data start row")
        except ValueError as exc:
            raise TemplateError(str(exc)) from None

        profile: dict[str, Any] = {
            "type": "excel", "file_extensions": self._extensions or ",".join(EXCEL_FILE_EXTENSIONS),
            "sn_sheet": self.value("sn_sheet"), "data_sheet": self.value("data_sheet"), "row_start": str(row_start),
            "component_col": self._letter("col_component"), "measure_col": self._letter("col_measured"),
            "min_col": self._letter("col_min"), "max_col": self._letter("col_max"), "unit_col": self._letter("col_unit"),
            "skip_empty_rows": self.skip_empty.isChecked(),
        }
        if self.value("sn_mode") == "cell":
            cell = self.value("sn_cell").strip().upper()
            if not looks_like_cell_coordinate(cell):
                raise TemplateError("Type the cell that holds the serial number, for example B1.")
            profile["sn_regex"] = cell
        else:
            example = self.value("sn_example").strip()
            try:
                profile["sn_regex"] = sn_regex_from_example(example)
            except TemplateError as exc:
                raise TemplateError(f"Serial number: {exc}") from None
            profile["sn_example"] = example
        validate_profile(profile)
        return profile

    # ------------------------------------------------------------------ live feedback
    def _on_change(self, *_args: object) -> None:
        if self._loading or self.sample is None:
            return
        self._refresh_timer.start(REFRESH_MS)

    def _on_table_change(self, *_args: object) -> None:
        if not self._loading and self.sample is not None:
            self._fill_columns()

    def _set_rule_status(self, key: str, text: str, kind: str) -> None:
        self.rule_status[key].setText(text)
        _set_kind(self.rule_status[key], kind)

    def _refresh(self) -> None:
        self._refresh_timer.stop()
        if self.sample is None:
            return
        self._generation += 1
        generation = self._generation

        if self.kind == "excel":
            self._refresh_excel_hints()
        else:
            problem = self._refresh_text_hints()
            if problem:
                self._show_problem(problem)
                return
        try:
            profile = self.collect_profile()
        except ValueError as exc:
            self._show_problem(str(exc))
            return
        self.problem_label.setText("")
        self.status_label.setText("Reading the sample…")
        sample, siblings = self.sample, self.siblings[:FOLDER_CHECK_FILES]

        def work(_report: Callable[..., None]) -> tuple[Preview, FolderCheck | None]:
            preview = preview_profile(sample, profile, limit=40)
            return preview, check_files(siblings, profile) if siblings and not preview.error else None

        self._tasks.run(
            work,
            on_success=lambda result: self._show_result(generation, *result),
            on_error=lambda exc: self._show_problem(f"Could not read the sample: {exc}") if isValid(self) else None,
        )

    def _refresh_excel_hints(self) -> None:
        assert self.sketch is not None
        if self.value("sn_mode") == "cell":
            value = self.sketch.cell(self.value("sn_sheet"), self.value("sn_cell"))
            self.sn_value.setText(f"→ {value}" if value else "→ (empty cell)")
        else:
            self.sn_value.setText("")

    def _refresh_text_hints(self) -> str:
        """Tell each rule what it matched and return a problem message when a pattern cannot be used."""
        patterns = {key: self.value(key).strip() for key in PATTERN_FIELDS}
        problem = ""
        for key, (_regex_key, rule) in PATTERN_FIELDS.items():
            try:
                compile_template(patterns[key], rule)
            except TemplateError as exc:
                self._set_rule_status(key, "cannot use this pattern", "bad")
                problem = problem or f"{RULES[rule].title.capitalize()}: {exc}"
            else:
                self._set_rule_status(key, "", "hint")
        if problem:
            return problem

        sn_example = self.value("sn_example").strip()
        if sn_example:
            try:
                sn_regex_from_example(sn_example)
                self._set_rule_status("sn_example", "", "hint")
            except TemplateError as exc:
                self._set_rule_status("sn_example", "cannot use this", "bad")
                return f"Serial number: {exc}"
        else:
            self._set_rule_status("sn_example", "optional", "hint")

        counts: dict[str, int] = {}
        try:
            full = text_profile_from_patterns(patterns, sn_example, self._extensions)
            marks = annotate_text(self._annotated_text, full)
            self._paint(marks)
            counts["block"] = sum(1 for m in marks if m.role == "block")
            counts["measure"] = sum(1 for m in marks if m.role == "measure")
            for key in ("lim2", "lim3"):
                if patterns[key]:
                    only = text_profile_from_patterns({**patterns, **{k: "" for k in ("lim2", "lim3") if k != key}}, sn_example,
                                                      self._extensions)
                    counts[key] = len({m.line for m in annotate_text(self._annotated_text, only) if m.role in ("min", "max")})
        except ValueError as exc:
            return str(exc)
        for key in PATTERN_FIELDS:
            if not patterns[key]:
                self._set_rule_status(key, "", "hint")
                continue
            found = counts.get(key, 0)
            if found:
                self._set_rule_status(key, f"found on {found:,} lines", "ok")
            else:
                self._set_rule_status(key, "not found in the sample", "bad")
        return ""

    def _show_problem(self, message: str) -> None:
        self.problem_label.setText(message)
        self.status_label.setText("")
        self.folder_label.setText("")
        self._clear_table()

    def _show_result(self, generation: int, preview: Preview, folder: FolderCheck | None) -> None:
        if generation != self._generation or not isValid(self):
            return
        if preview.error:
            self._clear_table()
            self.status_label.setText(preview.error.splitlines()[0])
            _set_kind(self.status_label, "bad")
            self.folder_label.setText("")
            return
        self.table.set_table(["Component", "Measured", "Min", "Max", "Unit"],
                             [(row.component, row.measured, row.min_value, row.max_value, row.unit) for row in preview.rows],
                             aligns=["w", "w", "w", "w", "w"], stretch=0)
        parts = [f"Serial number {preview.sn}" if preview.sn else "No serial number found", f"{preview.total:,} components read"]
        if preview.duplicates:
            parts.append(f"{preview.duplicates} appear more than once in this file")
        self.status_label.setText("  ·  ".join(parts))
        _set_kind(self.status_label, "ok" if preview.sn and preview.total > 0 else "bad")

        if folder is None:
            self.folder_label.setText("")
        elif folder.all_ok:
            others = "The other file" if folder.tried == 1 else f"The other {folder.tried} files"
            self.folder_label.setText(f"{others} in this folder can be read with these settings too.")
            _set_kind(self.folder_label, "ok")
        else:
            problems = "; ".join(folder.problems[:2])
            unreadable, total = folder.tried - folder.readable, folder.tried
            self.folder_label.setText(
                f"{unreadable} of {total} other {'file' if total == 1 else 'files'} in this folder cannot be read: {problems}")
            _set_kind(self.folder_label, "warn")

    # ------------------------------------------------------------------ finishing
    def accept(self) -> None:
        try:
            profile = self.collect_profile()
        except ValueError as exc:
            self.problem_label.setText(str(exc))
            return
        name = self._name or (self.detection.suggested_name if self.detection else "") or APP_TITLE
        callback = self.on_done
        self.close()
        callback(name, profile)

    def done(self, result: int) -> None:
        self._refresh_timer.stop()
        self._tasks.close(500)
        super().done(result)
