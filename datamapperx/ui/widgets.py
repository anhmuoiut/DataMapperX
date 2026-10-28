"""Reusable widgets."""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from tkinter import ttk

from .theme import Palette


class UndoableEntry(ttk.Entry):
    """ttk.Entry with Ctrl+Z / Ctrl+Y and Ctrl+A (ttk entries have none of these)."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._history: deque[str] = deque(maxlen=100)
        self._pos = -1
        self.bind("<FocusIn>", self._sync, add="+")
        self.bind("<KeyRelease>", self._record, add="+")
        for key in ("z", "Z"):
            self.bind(f"<Control-{key}>", self.undo, add="+")
        for key in ("y", "Y"):
            self.bind(f"<Control-{key}>", self.redo, add="+")
        for key in ("a", "A"):
            self.bind(f"<Control-{key}>", self.select_all, add="+")
        self.after_idle(self.reset_undo)

    def reset_undo(self) -> None:
        self._history.clear()
        self._history.append(self.get())
        self._pos = 0

    def _sync(self, _event=None) -> None:
        # The field may have been changed from code (e.g. switching profile); do not undo into stale text.
        if self._pos < 0 or self._pos >= len(self._history) or self._history[self._pos] != self.get():
            self.reset_undo()

    def _record(self, event=None) -> None:
        if event is not None and (event.state & 0x4) and event.keysym.lower() in {"z", "y", "a", "c", "v", "x"}:
            return
        if self._pos < 0:
            self.reset_undo()
            return
        current = self.get()
        if current == self._history[self._pos]:
            return
        kept = list(self._history)[: self._pos + 1]  # drop any redo future
        self._history.clear()
        self._history.extend(kept)
        self._history.append(current)
        self._pos = len(self._history) - 1

    def _show(self, value: str) -> None:
        self.delete(0, tk.END)
        self.insert(0, value)
        self.icursor(tk.END)

    def undo(self, _event=None) -> str:
        self._sync()
        if self._pos > 0:
            self._pos -= 1
            self._show(self._history[self._pos])
        return "break"

    def redo(self, _event=None) -> str:
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self._show(self._history[self._pos])
        return "break"

    def select_all(self, _event=None) -> str:
        self.selection_range(0, tk.END)
        self.icursor(tk.END)
        return "break"


class ItemList(ttk.Frame):
    """A themed, scrollable, multi-select list of strings (a ttk replacement for tk.Listbox)."""

    def __init__(
        self,
        master,
        *,
        on_activate: Callable[[], None] | None = None,
        on_delete: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self, show="tree", selectmode="extended", style="Component.Treeview")
        self.tree.column("#0", stretch=True, minwidth=80)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        if on_activate:
            self.tree.bind("<Double-Button-1>", lambda _e: on_activate(), add="+")
            self.tree.bind("<Return>", lambda _e: on_activate(), add="+")
        if on_delete:
            self.tree.bind("<Delete>", lambda _e: on_delete(), add="+")
        self.tree.bind("<Control-a>", self._select_all)
        self.tree.bind("<Control-A>", self._select_all)
        self._placeholder = ttk.Label(self.tree, style="ListHint.TLabel", justify="center", anchor="center")
        self.tree.bind("<Configure>", self._resize_placeholder, add="+")
        self._placeholder.bind("<Button-1>", lambda _event: self.tree.focus_set())

    def _resize_placeholder(self, event=None) -> None:
        width = event.width if event is not None else self.tree.winfo_width()
        self._placeholder.configure(wraplength=max(100, width - 40))

    def _select_all(self, _event=None) -> str:
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def set_items(self, items: Sequence[str], empty_text: str = "") -> None:
        """Replace the contents. ``empty_text`` is shown in the middle of the list while it is empty."""
        # A count or theme refresh should not discard keyboard focus, selection, or scroll position.
        if self.items() != list(items):
            self.tree.delete(*self.tree.get_children())
            for index, text in enumerate(items):
                self.tree.insert("", tk.END, iid=str(index), text=text)
        if items or not empty_text:
            self._placeholder.place_forget()
        else:
            self._placeholder.configure(text=empty_text)
            self._resize_placeholder()
            self._placeholder.place(relx=0.5, rely=0.45, anchor="center", relwidth=0.86)

    def items(self) -> list[str]:
        return [self.tree.item(iid, "text") for iid in self.tree.get_children()]

    def selected_items(self) -> list[str]:
        return [self.tree.item(iid, "text") for iid in self.tree.selection()]

    def selected_indices(self) -> list[int]:
        return sorted(self.tree.index(iid) for iid in self.tree.selection())

    def select_indices(self, indices: Sequence[int]) -> None:
        children = self.tree.get_children()
        chosen = [children[i] for i in indices if 0 <= i < len(children)]
        self.tree.selection_set(chosen)
        if chosen:
            self.tree.focus(chosen[0])
            self.tree.see(chosen[0])


class ReadOnlyText(ttk.Frame):
    """Scrollable, selectable, read-only text (used for reports and release notes)."""

    def __init__(self, master, palette: Palette, *, height: int = 12, width: int = 70) -> None:
        super().__init__(master)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.text = tk.Text(
            self, wrap="word", height=height, width=width, relief="flat", borderwidth=0, padx=10, pady=8,
            bg=palette.surface, fg=palette.fg, insertbackground=palette.fg,
            highlightthickness=1, highlightbackground=palette.line, highlightcolor=palette.accent,
            font=("Segoe UI", 10),
        )
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.tag_configure("heading", font=("Segoe UI Semibold", 11), spacing1=8, spacing3=2)
        self.text.tag_configure("bullet", lmargin1=12, lmargin2=28)
        self.text.configure(state="disabled")

    def set_text(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")

    def set_markdown(self, content: str) -> None:
        """Show the small Markdown subset used in release notes: headings, bullets, **bold**, `code`."""
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        for line in content.splitlines():
            stripped = line.strip()
            plain = re.sub(r"`([^`]*)`", r"\1", re.sub(r"\*\*(.+?)\*\*", r"\1", stripped))
            if stripped.startswith("#"):
                self.text.insert(tk.END, plain.lstrip("#").strip() + "\n", "heading")
            elif stripped.startswith(("- ", "* ")):
                self.text.insert(tk.END, "•  " + plain[2:] + "\n", "bullet")
            else:
                self.text.insert(tk.END, plain + "\n")
        self.text.configure(state="disabled")


MAX_COLUMN_WIDTH = 420
_CELL_PADDING = 24  # the cell's own padding plus a little room so text is never clipped
_HEADING_PADDING = 34  # the heading is padded more (and may grow a sort arrow)


def _style_font(widget: tk.Misc, style_name: str, fallback: tuple[str, int]) -> tkfont.Font:
    spec = ttk.Style(widget).lookup(style_name, "font") or fallback
    try:
        return tkfont.Font(root=widget, font=spec)
    except tk.TclError:
        return tkfont.Font(root=widget, font=fallback)


def fit_tree_columns(
    tree: ttk.Treeview,
    headings: Mapping[str, str],
    rows: Iterable[Sequence[object]],
    *,
    min_width: int = 44,
    max_width: int = MAX_COLUMN_WIDTH,
) -> None:
    """Make every column just wide enough for its heading and its longest value.

    ``rows`` are the value tuples in column order. Only the few longest texts of a column are measured, which
    is enough to find the widest one and keeps this fast for hundreds of rows.
    """
    style = str(tree.cget("style")) or "Treeview"
    cell_font = _style_font(tree, style, ("Segoe UI", 10))
    heading_font = _style_font(tree, f"{style}.Heading", ("Segoe UI Semibold", 9))
    table = [tuple(str(value) for value in row) for row in rows]
    for index, column in enumerate(tree["columns"]):
        longest = sorted({row[index] for row in table if index < len(row)}, key=len, reverse=True)[:4]
        data = max((cell_font.measure(text) for text in longest), default=0) + _CELL_PADDING
        heading = heading_font.measure(headings.get(column, "")) + _HEADING_PADDING
        width = min(max_width, max(data, heading, min_width))
        tree.column(column, width=width, minwidth=min(width, 40), stretch=False)
