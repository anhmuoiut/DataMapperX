"""Reusable widgets."""

from __future__ import annotations

import re
import tkinter as tk
from collections import deque
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

    def set_parts(self, parts) -> None:
        """Show (text, tag) pieces one after the other; the caller configures the tags with ``text.tag_configure``."""
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        for content, tag in parts:
            self.text.insert(tk.END, content, tag or ())
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
