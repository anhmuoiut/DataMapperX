"""Let the user choose which occurrence to use when a component appears more than once in a file."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk

from ..models import DuplicateGroup, Measurement
from .dialogs import Dialog


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
    def __init__(
        self,
        parent: tk.Misc,
        groups: Iterable[DuplicateGroup],
        on_close: Callable[[set[str], bool], None],
    ):
        """``on_close(components_reviewed, applied)`` runs when the dialog closes."""
        super().__init__(parent, "Duplicate component names", min_size=(720, 360))
        self._on_close = on_close

        by_component: dict[str, list[DuplicateGroup]] = {}
        for group in groups:
            by_component.setdefault(group.component, []).append(group)
        self._components = sorted(by_component, key=str.lower)
        self._by_component = by_component

        header = ttk.Frame(self, padding=(16, 14, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text="Some component names appear more than once in a file.", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(
            header,
            text="The first occurrence is used by default. Your choice is applied to every file with the same structure.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        footer = ttk.Frame(self, padding=(16, 8, 16, 14))
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Apply choices", style="Accent.TButton", command=self._apply).pack(side="right")
        ttk.Button(footer, text="Keep defaults", command=self.close).pack(side="right", padx=(0, 8))

        canvas = tk.Canvas(self, highlightthickness=0, bg=self.palette.bg)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, padding=(16, 8, 8, 8))
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(-1 * (ev.delta // 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=2)
        for col, title in enumerate(("No.", "Duplicate name", "Use this occurrence")):
            ttk.Label(body, text=title, font=("Segoe UI Semibold", 9)).grid(row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 6))

        self._combos: list[ttk.Combobox] = []
        for row, component in enumerate(self._components, start=1):
            first = by_component[component][0]
            labels = [f"{i}. {describe_measurement(option, first.row_label)}" for i, option in enumerate(first.options, start=1)]
            ttk.Label(body, text=str(row)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            ttk.Label(body, text=component).grid(row=row, column=1, sticky="w", padx=(0, 10), pady=4)
            combo = ttk.Combobox(body, values=labels, state="readonly")
            combo.current(0)
            combo.grid(row=row, column=2, sticky="ew", pady=4)
            self._combos.append(combo)

        self._applied = False
        self.present(width=860, height=480)

    def _apply(self) -> None:
        for component, combo in zip(self._components, self._combos, strict=True):
            chosen = max(combo.current(), 0)
            for group in self._by_component[component]:
                index = chosen if chosen < len(group.options) else 0
                group.record.entries[component] = group.options[index]
        self._applied = True
        self.close()

    def close(self) -> None:
        self.canvas_unbind()
        self._on_close(set(self._components), self._applied)
        self.destroy()

    def canvas_unbind(self) -> None:
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
