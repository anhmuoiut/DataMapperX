"""Small observable values and the binders that tie them to widgets.

The Validation & Reports workspace keeps its settings in these, so that its logic reads ``var.get()`` and reacts to ``trace``
whatever shows the value. A ``Var`` is plain Python (no QObject); a binder connects it to one widget in both directions and
ignores a widget that has been deleted since.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QComboBox, QLabel, QLineEdit, QSpinBox
from shiboken6 import isValid


class Var:
    """A value that tells those who traced it when it changes (only when it really changes)."""

    def __init__(self, value: Any = "") -> None:
        self._value = value
        self._callbacks: list[Callable[[], None]] = []

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        if value != self._value:
            self._value = value
            for callback in list(self._callbacks):
                callback()

    def trace(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)


def bind_label(label: QLabel, var: Var, *, hide_empty: bool = False) -> None:
    """A label shows the text of ``var`` (and, with ``hide_empty``, is not there while the text is empty)."""

    def show() -> None:
        if isValid(label):
            text = str(var.get())
            label.setText(text)
            if hide_empty:
                label.setVisible(bool(text))

    var.trace(show)
    show()


def bind_edit(edit: QLineEdit, var: Var) -> None:
    """A line edit shows the text of ``var`` and sets it as the person types."""
    edit.setText(str(var.get()))
    edit.textChanged.connect(lambda text: var.set(text))

    def show() -> None:
        if isValid(edit) and edit.text() != var.get():
            edit.setText(str(var.get()))

    var.trace(show)


def bind_combo(combo: QComboBox, var: Var) -> None:
    """A read-only combo box chooses the text of ``var`` (the text must be one of its items)."""
    index = combo.findText(str(var.get()))
    if index >= 0:
        combo.setCurrentIndex(index)
    combo.currentTextChanged.connect(lambda text: var.set(text) if text else None)

    def show() -> None:
        if isValid(combo) and combo.currentText() != var.get():
            position = combo.findText(str(var.get()))
            if position >= 0:
                combo.setCurrentIndex(position)

    var.trace(show)


def bind_check(check: QAbstractButton, var: Var) -> None:
    check.setChecked(bool(var.get()))
    check.toggled.connect(lambda state: var.set(bool(state)))

    def show() -> None:
        if isValid(check) and check.isChecked() != bool(var.get()):
            check.setChecked(bool(var.get()))

    var.trace(show)


def bind_spin(spin: QSpinBox, var: Var) -> None:
    spin.setValue(int(var.get()))
    spin.valueChanged.connect(lambda value: var.set(str(value)))

    def show() -> None:
        try:
            value = int(var.get())
        except ValueError:
            return
        if isValid(spin) and spin.value() != value:
            spin.setValue(value)

    var.trace(show)


def bind_radios(buttons: dict[Any, QAbstractButton], var: Var, group: QButtonGroup | None = None) -> None:
    """One radio button for each value of ``var``."""
    for value, button in buttons.items():
        if group is not None:
            group.addButton(button)
        button.toggled.connect(lambda state, v=value: var.set(v) if state else None)
    buttons[var.get()].setChecked(True)

    def show() -> None:
        button = buttons.get(var.get())
        if button is not None and isValid(button) and not button.isChecked():
            button.setChecked(True)

    var.trace(show)


__all__ = ["Var", "bind_check", "bind_combo", "bind_edit", "bind_label", "bind_radios", "bind_spin"]
