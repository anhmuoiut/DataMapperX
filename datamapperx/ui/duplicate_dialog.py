"""Let the user choose which occurrence to use when a component appears more than once in a file."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtWidgets import QComboBox, QGridLayout, QScrollArea, QWidget

from ..models import DuplicateGroup, Measurement
from .dialogs import Dialog, label
from .widgets import make_button


def describe_measurement(measurement: Measurement, row_label: str) -> str:
    where = row_label.rstrip("s").lower()  # "Rows" -> "row", "Lines" -> "line"
    parts = [f"{where} {measurement.source_row}" if measurement.source_row else "first match"]
    if measurement.measured:
        parts.append(f"value={measurement.measured}")
    if measurement.min_value or measurement.max_value:
        parts.append(f"min={measurement.min_value}, max={measurement.max_value}")
    if measurement.unit:
        parts.append(f"unit={measurement.unit}")
    return " | ".join(parts)


class DuplicateDialog(Dialog):
    def __init__(self, parent: QWidget, groups: Iterable[DuplicateGroup], on_close: Callable[[set[str], bool], None]) -> None:
        """``on_close(components_reviewed, applied)`` runs when the dialog closes."""
        super().__init__(parent, "Duplicate component names", size=(860, 480), min_size=(720, 360))
        self._on_close = on_close
        self._applied = False

        by_component: dict[str, list[DuplicateGroup]] = {}
        for group in groups:
            by_component.setdefault(group.component, []).append(group)
        self._components = sorted(by_component, key=str.lower)
        self._by_component = by_component

        self.layout_root.addWidget(label("Some component names appear more than once in a file.", "heading"))
        self.layout_root.addWidget(label("The first occurrence is used by default. Your choice is applied to every file with the "
                                         "same structure.", "muted", wrap=True))
        body, grid = QWidget(), QGridLayout()
        body.setLayout(grid)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        grid.setVerticalSpacing(8)
        for column, title in enumerate(("No.", "Duplicate name", "Use this occurrence")):
            grid.addWidget(label(title, "muted"), 0, column)
        self.combos: list[QComboBox] = []
        for row, component in enumerate(self._components, start=1):
            first = by_component[component][0]
            combo = QComboBox()
            combo.addItems([f"{i}. {describe_measurement(option, first.row_label)}" for i, option in enumerate(first.options, start=1)])
            grid.addWidget(label(str(row)), row, 0)
            grid.addWidget(label(component), row, 1)
            grid.addWidget(combo, row, 2)
            self.combos.append(combo)
        grid.setRowStretch(len(self._components) + 1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.layout_root.addWidget(scroll, 1)
        self.button_row(make_button("Keep defaults", self.close), make_button("Apply choices", self.apply, primary=True))

    def apply(self) -> None:
        for component, combo in zip(self._components, self.combos, strict=True):
            chosen = max(combo.currentIndex(), 0)
            for group in self._by_component[component]:
                index = chosen if chosen < len(group.options) else 0
                group.record.entries[component] = group.options[index]
        self._applied = True
        self.close()

    def done(self, result: int) -> None:
        callback, self._on_close = self._on_close, lambda *_args: None
        callback(set(self._components), self._applied)  # once: Apply closes the dialog, and so does Keep defaults
        super().done(result)
