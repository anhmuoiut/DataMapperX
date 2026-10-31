"""The "About the method" dialog: the calculation sequence of the selected analysis, in collapsible groups of formulas."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..method_guide import Formula, Guide, Section
from .dialogs import Dialog
from .math_view import MathView

BOLD = ("Segoe UI Semibold", 10)


class MethodDialog(Dialog):
    def __init__(self, parent: tk.Misc, guide: Guide):
        super().__init__(parent, "About the method", min_size=(560, 420))
        self.guide = guide
        self.sections: dict[str, tuple[ttk.Frame, ttk.Label]] = {}
        self.opened: dict[str, bool] = {}
        self._wrapped: list[ttk.Label] = []
        outer = ttk.Frame(self, padding=(14, 12, 6, 10))
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(outer, bg=self.palette.surface, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.page = ttk.Frame(self.canvas, style="Surface.TFrame", padding=(10, 8))
        window = self.canvas.create_window(0, 0, window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._resize(window, e.width))
        self._build(guide)
        ttk.Button(outer, text="Close", style="Accent.TButton", command=self.close).grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self._bind_wheel(self.canvas)
        self._bind_wheel(self.page)
        self.present(width=780, height=700)

    # ------------------------------------------------------------------ layout
    def _resize(self, window: int, width: int) -> None:
        self.canvas.itemconfigure(window, width=width)
        for label in self._wrapped:
            label.configure(wraplength=max(200, width - 70))

    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _label(self, parent: tk.Misc, text: str, style: str = "Surface.TLabel", **options) -> ttk.Label:
        label = ttk.Label(parent, text=text, style=style, justify="left", **options)
        self._wrapped.append(label)
        return label

    # ------------------------------------------------------------------ content
    def _build(self, guide: Guide) -> None:
        ttk.Label(self.page, text=guide.title, style="Section.TLabel", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        self._label(self.page, f"Method: {guide.method}", "SurfaceHint.TLabel").pack(anchor="w", pady=(2, 0))
        self._label(self.page, guide.summary).pack(anchor="w", pady=(6, 0))
        for section in guide.sections:
            self._section(section)

    def _section(self, section: Section) -> None:
        box = ttk.Frame(self.page, style="Surface.TFrame")
        box.pack(fill="x", pady=(12, 0))
        header = ttk.Label(box, style="Section.TLabel", cursor="hand2")
        header.pack(anchor="w", fill="x")
        body = ttk.Frame(box, style="Surface.TFrame", padding=(14, 2, 0, 0))
        self.sections[section.title] = (body, header)
        header.bind("<Button-1>", lambda _e: self.toggle(section.title))
        for formula in section.formulas:
            self._formula(body, formula)
        for note in section.notes:
            self._label(body, f"•  {note}").pack(anchor="w", pady=(4, 0))
        if section.values:
            self._values(body, section.values)
        self.toggle(section.title, section.opened)

    def toggle(self, title: str, opened: bool | None = None) -> None:
        """Open or close a group of formulas (``opened`` None flips it)."""
        body, header = self.sections[title]
        self.opened[title] = opened = (not self.opened[title]) if opened is None else opened
        header.configure(text=f"{'▾' if opened else '▸'}  {title}")
        if opened:
            body.pack(fill="x", anchor="w")
        else:
            body.pack_forget()

    def _formula(self, parent: tk.Misc, formula: Formula) -> None:
        block = ttk.Frame(parent, style="Surface.TFrame")
        block.pack(fill="x", anchor="w", pady=(8, 0))
        ttk.Label(block, text=formula.name, style="Surface.TLabel", font=BOLD).pack(anchor="w")
        for line in formula.lines:
            MathView(block, line, self.palette).pack(anchor="w", padx=(14, 0), pady=1)
        self._label(block, formula.explanation).pack(anchor="w", pady=(2, 0))
        if formula.variables:
            grid = ttk.Frame(block, style="Surface.TFrame")
            grid.pack(anchor="w", padx=(14, 0), pady=(3, 0))
            ttk.Label(grid, text="where", style="SurfaceHint.TLabel").grid(row=0, column=0, sticky="ne", padx=(0, 8))
            for row, (symbol, meaning) in enumerate(formula.variables):
                MathView(grid, symbol, self.palette, size=13).grid(row=row, column=1, sticky="e", padx=(0, 6))
                ttk.Label(grid, text=meaning, style="SurfaceHint.TLabel").grid(row=row, column=2, sticky="w")

    def _values(self, parent: tk.Misc, values: tuple[tuple[str, str], ...]) -> None:
        grid = ttk.Frame(parent, style="Surface.TFrame")
        grid.pack(anchor="w", pady=(4, 0))
        for row, (symbol, value) in enumerate(values):
            if not symbol:
                self._label(grid, value).grid(row=row, column=0, columnspan=3, sticky="w")
                continue
            MathView(grid, symbol, self.palette, size=13).grid(row=row, column=0, sticky="e", padx=(0, 8))
            ttk.Label(grid, text="=", style="Surface.TLabel").grid(row=row, column=1)
            ttk.Label(grid, text=value, style="Surface.TLabel").grid(row=row, column=2, sticky="w", padx=(8, 0))
