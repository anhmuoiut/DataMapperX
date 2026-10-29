"""Controls drawn for this app: the component lists, the review table, the step bar and the row of check chips.

The lists put a real button at the end of every row, which ``ttk.Treeview`` cannot do, and the review table has to
scroll smoothly, which a themed Treeview does not (it repaints every cell on every step), so both are drawn on a
canvas. Only the rows (and columns) in view are drawn, so a scan with thousands of components scrolls as smoothly as one
with ten.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from tkinter import ttk

from .theme import Palette

_CTRL, _SHIFT = 0x4, 0x1  # modifier bits of a Tk event


def _rounded(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **options) -> int:
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **options)


class ActionList(ttk.Frame):
    """A scrollable, multi-select list of names with one button at the end of each row.

    ``action`` is ``"add"`` (a +) or ``"remove"`` (an ×, which turns red under the pointer). Rows can also show their
    number (``numbered``) and right-aligned value columns with headings (``value_headings``, e.g. Min and Max).
    Clicking the button calls ``on_action(row)``; double-click or Enter calls ``on_activate()`` for the selected rows
    and Delete calls ``on_delete()``. A double-click on a button counts once, so it never acts on two rows.
    """

    ROW_HEIGHT = 40
    HEAD_HEIGHT = 32
    BUTTON_SIZE = 28
    VALUE_WIDTH = 78
    WHEEL_ROWS = 3

    def __init__(
        self,
        master,
        palette: Palette,
        *,
        action: str,
        on_action: Callable[[int], None],
        on_activate: Callable[[], None] | None = None,
        on_delete: Callable[[], None] | None = None,
        on_select: Callable[[], None] | None = None,
        numbered: bool = False,
        name_heading: str = "",
        value_headings: Sequence[str] = (),
    ) -> None:
        super().__init__(master, style="Surface.TFrame")
        if action not in ("add", "remove"):
            raise ValueError(f"unknown action {action!r}")
        self.palette = palette
        self._action = action
        self._on_action, self._on_activate, self._on_delete, self._on_select = on_action, on_activate, on_delete, on_select
        self._numbered = numbered
        self._name_heading = name_heading
        self._value_headings = tuple(value_headings)
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96)

        self._font = tkfont.Font(root=self, family="Segoe UI", size=10)
        self._small = tkfont.Font(root=self, family="Segoe UI", size=9)
        self._head_font = tkfont.Font(root=self, family="Segoe UI Semibold", size=9)

        self._items: list[str] = []
        self._values: list[tuple[str, ...]] = []
        self._selected: set[int] = set()
        self._anchor: int | None = None
        self._cursor: int | None = None
        self._hover: int | None = None
        self._hover_button = False
        self._offset = 0
        self._empty_text = ""
        self._enabled = True

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._border = tk.Frame(self, bg=palette.line, padx=1, pady=1, highlightthickness=0)
        self._border.grid(row=0, column=0, sticky="nsew")
        self._border.columnconfigure(0, weight=1)
        self._border.rowconfigure(1, weight=1)

        self._head = tk.Canvas(self._border, height=self._px(self.HEAD_HEIGHT), highlightthickness=0, bd=0, bg=palette.soft)
        if name_heading or self._value_headings:
            self._head.grid(row=0, column=0, sticky="ew")
        self._body = tk.Canvas(
            self._border, width=self._px(220), height=self._px(120), highlightthickness=0, bd=0, bg=palette.surface,
            takefocus=True,
        )
        self._body.grid(row=1, column=0, sticky="nsew")
        self._scroll = ttk.Scrollbar(self._border, orient="vertical", command=self._yview)
        self._scroll.grid(row=0, column=1, rowspan=2, sticky="ns")

        body = self._body
        body.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self._head.bind("<Configure>", lambda _e: self._redraw_head(), add="+")
        body.bind("<Button-1>", self._on_press)
        body.bind("<Double-Button-1>", self._on_double)
        body.bind("<Motion>", self._on_motion)
        body.bind("<Leave>", self._on_leave)
        body.bind("<MouseWheel>", self._on_wheel)
        body.bind("<Button-4>", lambda e: self._on_wheel(e, 120))
        body.bind("<Button-5>", lambda e: self._on_wheel(e, -120))
        body.bind("<FocusIn>", lambda _e: self._border.configure(bg=self.palette.accent))
        body.bind("<FocusOut>", lambda _e: self._border.configure(bg=self.palette.line))
        for key, step in (("Up", -1), ("Down", 1)):
            body.bind(f"<{key}>", lambda _e, s=step: self._move_cursor(s, extend=False))
            body.bind(f"<Shift-{key}>", lambda _e, s=step: self._move_cursor(s, extend=True))
        body.bind("<Prior>", lambda _e: self._move_cursor(-self._page_rows(), extend=False))
        body.bind("<Next>", lambda _e: self._move_cursor(self._page_rows(), extend=False))
        body.bind("<Home>", lambda _e: self._move_cursor(-len(self._items), extend=False))
        body.bind("<End>", lambda _e: self._move_cursor(len(self._items), extend=False))
        for key in ("a", "A"):
            body.bind(f"<Control-{key}>", self._select_all)
        body.bind("<Return>", lambda _e: self._activate())
        if on_delete:
            body.bind("<Delete>", lambda _e: on_delete())

    # ------------------------------------------------------------------ public API
    def set_items(self, items: Sequence[str], empty_text: str = "", values: Sequence[Sequence[str]] | None = None) -> None:
        """Replace the rows. ``empty_text`` fills the list while it is empty; ``values`` are the value columns."""
        items = list(items)
        columns = [tuple(row) for row in values] if values is not None else [()] * len(items)
        if items == self._items and columns == self._values and empty_text == self._empty_text:
            return  # a count or theme refresh keeps focus, selection and scroll position
        changed = items != self._items
        self._items, self._values, self._empty_text = items, columns, empty_text
        if changed:
            had_selection = bool(self._selected)
            self._selected.clear()
            self._anchor = self._cursor = None
            if had_selection and self._on_select:
                self._on_select()
        self._redraw()

    def items(self) -> list[str]:
        return list(self._items)

    def selected_items(self) -> list[str]:
        return [self._items[i] for i in sorted(self._selected)]

    def selected_indices(self) -> list[int]:
        return sorted(self._selected)

    def select_indices(self, indices: Iterable[int]) -> None:
        chosen = sorted(i for i in set(indices) if 0 <= i < len(self._items))
        self._set_selection(set(chosen), anchor=chosen[0] if chosen else None, cursor=chosen[0] if chosen else None)
        if chosen:
            self._ensure_visible(chosen[0])

    def reset_view(self) -> None:
        """Back to the top (for a new filter, where the old scroll position means nothing)."""
        self._offset = 0
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            self._hover_button = False
            self._body.configure(cursor="")
            self._redraw()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._border.configure(bg=palette.accent if self.focus_displayof() is self._body else palette.line)
        self._head.configure(bg=palette.soft)
        self._body.configure(bg=palette.surface)
        self._redraw_head()
        self._redraw()

    # ------------------------------------------------------------------ geometry
    def _px(self, value: float) -> int:
        return max(1, round(value * self._scale))

    def _row_height(self) -> int:
        return self._px(self.ROW_HEIGHT)

    def _view_height(self) -> int:
        return max(1, self._body.winfo_height())

    def _page_rows(self) -> int:
        return max(1, self._view_height() // self._row_height() - 1)

    def _max_offset(self) -> int:
        return max(0, len(self._items) * self._row_height() - self._view_height())

    def _button_box(self, top: int, width: int) -> tuple[int, int, int, int]:
        size = self._px(self.BUTTON_SIZE)
        right = width - self._px(8)
        y = top + (self._row_height() - size) // 2
        return right - size, y, right, y + size

    def _value_edges(self, button_left: int) -> list[int]:
        """Right edges of the value columns, left to right."""
        step, edge = self._px(self.VALUE_WIDTH), button_left - self._px(10)
        return [edge - step * (len(self._value_headings) - 1 - k) for k in range(len(self._value_headings))]

    def _name_left(self) -> int:
        return self._px(12) + (self._px(30) if self._numbered else 0)

    def row_geometry(self, index: int) -> tuple[int, int, int, int, int]:
        """(row top, button x1, y1, x2, y2) on screen, for tests and hit-testing."""
        top = index * self._row_height() - self._offset
        return (top, *self._button_box(top, self._body.winfo_width()))

    # ------------------------------------------------------------------ drawing
    def _fit(self, text: str, font: tkfont.Font, width: int) -> str:
        if font.measure(text) <= width:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if font.measure(text[:middle] + "…") <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low] + "…"

    def _redraw_head(self) -> None:
        canvas, p = self._head, self.palette
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or not (self._name_heading or self._value_headings):
            return
        middle = height // 2
        canvas.create_text(self._name_left(), middle, text=self._name_heading, anchor="w", fill=p.muted, font=self._head_font)
        button_left = self._button_box(0, width)[0]
        for edge, heading in zip(self._value_edges(button_left), self._value_headings, strict=True):
            canvas.create_text(edge, middle, text=heading, anchor="e", fill=p.muted, font=self._head_font)
        canvas.create_line(0, height - 1, width, height - 1, fill=p.line)

    def _redraw(self) -> None:
        canvas, p = self._body, self.palette
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        self._offset = max(0, min(self._offset, self._max_offset()))
        self._update_scrollbar()
        if width <= 1:
            return
        count = len(self._items)
        if not count:
            if self._empty_text:
                canvas.create_text(
                    width / 2, height * 0.45, text=self._empty_text, fill=p.muted, font=self._font, justify="center",
                    width=max(100, width - self._px(40)),
                )
            return
        row_h = self._row_height()
        for index in range(self._offset // row_h, min(count, (self._offset + height) // row_h + 1)):
            self._draw_row(index, index * row_h - self._offset, width)

    def _draw_row(self, index: int, top: int, width: int) -> None:
        canvas, p = self._body, self.palette
        row_h = self._row_height()
        if index in self._selected:
            fill = p.pick
        elif index == self._hover:
            fill = p.soft
        else:
            fill = p.surface
        canvas.create_rectangle(0, top, width, top + row_h, fill=fill, outline="")
        canvas.create_line(0, top + row_h - 1, width, top + row_h - 1, fill=p.line)
        middle = top + row_h // 2

        x1, y1, x2, y2 = self._button_box(top, width)
        text_right = x1 - self._px(10)
        edges = self._value_edges(x1)
        if edges:
            text_right = edges[0] - self._px(self.VALUE_WIDTH) + self._px(10)
        if self._numbered:
            canvas.create_text(self._px(12) + self._px(22), middle, text=str(index + 1), anchor="e", fill=p.muted, font=self._small)
        name = self._fit(self._items[index], self._font, max(self._px(30), text_right - self._name_left() - self._px(6)))
        canvas.create_text(self._name_left(), middle, text=name, anchor="w", fill=p.fg, font=self._font)
        for edge, text in zip(edges, self._values[index], strict=False):
            canvas.create_text(edge, middle, text=text, anchor="e", fill=p.muted, font=self._small)
        self._draw_button(x1, y1, x2, y2, hot=self._enabled and index == self._hover and self._hover_button)

    def _draw_button(self, x1: int, y1: int, x2: int, y2: int, *, hot: bool) -> None:
        canvas, p = self._body, self.palette
        accent = p.danger if self._action == "remove" else p.accent
        if not self._enabled:
            border, fill, glyph = p.line, p.surface, p.muted
        elif hot:
            border, fill, glyph = accent, (p.bad_bg if self._action == "remove" else p.soft), accent
        else:
            border, fill, glyph = p.line, p.surface, p.fg
        _rounded(canvas, x1, y1, x2, y2, self._px(5), fill=fill, outline=border)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if self._action == "add":
            arm = self._px(5)
            canvas.create_line(cx - arm, cy, cx + arm, cy, fill=glyph, width=2, capstyle="round")
            canvas.create_line(cx, cy - arm, cx, cy + arm, fill=glyph, width=2, capstyle="round")
        else:
            arm = self._px(4)
            canvas.create_line(cx - arm, cy - arm, cx + arm, cy + arm, fill=glyph, width=2, capstyle="round")
            canvas.create_line(cx - arm, cy + arm, cx + arm, cy - arm, fill=glyph, width=2, capstyle="round")

    # ------------------------------------------------------------------ scrolling
    def _update_scrollbar(self) -> None:
        total = len(self._items) * self._row_height()
        view = self._view_height()
        if total <= view:
            self._scroll.set(0.0, 1.0)
            if self._scroll.winfo_manager():
                self._scroll.grid_remove()  # nothing to scroll: give the rows the full width
        else:
            self._scroll.set(self._offset / total, min(1.0, (self._offset + view) / total))
            if not self._scroll.winfo_manager():
                self._scroll.grid()

    def _scroll_to(self, offset: float) -> None:
        offset = int(max(0, min(offset, self._max_offset())))
        if offset != self._offset:
            self._offset = offset
            self._redraw()

    def _yview(self, *args) -> None:
        total = len(self._items) * self._row_height()
        if args[0] == "moveto":
            self._scroll_to(float(args[1]) * total)
        elif args[0] == "scroll":
            unit = self._row_height() if args[2] == "units" else self._view_height()
            self._scroll_to(self._offset + int(args[1]) * unit)

    def _on_wheel(self, event, delta: int | None = None) -> str:
        notches = (delta if delta is not None else event.delta) / 120
        self._scroll_to(self._offset - notches * self.WHEEL_ROWS * self._row_height())
        return "break"

    def _ensure_visible(self, index: int) -> None:
        row_h = self._row_height()
        top, bottom = index * row_h, (index + 1) * row_h
        if top < self._offset:
            self._scroll_to(top)
        elif bottom > self._offset + self._view_height():
            self._scroll_to(bottom - self._view_height())

    # ------------------------------------------------------------------ pointer
    def _locate(self, x: int, y: int) -> tuple[int | None, bool]:
        """The row under the pointer and whether the pointer is on that row's button."""
        index = (y + self._offset) // self._row_height()
        if y < 0 or not 0 <= index < len(self._items):
            return None, False
        top = index * self._row_height() - self._offset
        x1, y1, x2, y2 = self._button_box(top, self._body.winfo_width())
        return index, x1 <= x <= x2 and y1 <= y <= y2

    def _on_press(self, event) -> str:
        self._body.focus_set()
        index, on_button = self._locate(event.x, event.y)
        if index is None:
            self._set_selection(set())
            return "break"
        if on_button:
            if self._enabled:
                self._on_action(index)
            return "break"
        if event.state & _SHIFT and self._anchor is not None:
            low, high = sorted((self._anchor, index))
            self._set_selection(set(range(low, high + 1)), anchor=self._anchor, cursor=index)
        elif event.state & _CTRL:
            self._set_selection(self._selected ^ {index}, anchor=index, cursor=index)
        else:
            self._set_selection({index}, anchor=index, cursor=index)
        return "break"

    def _on_double(self, event) -> str:
        index, on_button = self._locate(event.x, event.y)
        if index is not None and not on_button:
            self._activate()
        return "break"  # the second press of a double-click on a button is not a second action

    def _on_motion(self, event) -> None:
        index, on_button = self._locate(event.x, event.y)
        on_button = on_button and self._enabled  # a disabled list has nothing to highlight
        if (index, on_button) != (self._hover, self._hover_button):
            self._hover, self._hover_button = index, on_button
            self._body.configure(cursor="hand2" if on_button else "")
            self._redraw()

    def _on_leave(self, _event) -> None:
        if self._hover is not None or self._hover_button:
            self._hover, self._hover_button = None, False
            self._body.configure(cursor="")
            self._redraw()

    # ------------------------------------------------------------------ selection and keys
    def _set_selection(self, selected: set[int], *, anchor: int | None = None, cursor: int | None = None) -> None:
        changed = selected != self._selected
        self._selected = selected
        self._anchor, self._cursor = anchor, cursor
        self._redraw()
        if changed and self._on_select:
            self._on_select()

    def _select_all(self, _event=None) -> str:
        self._set_selection(set(range(len(self._items))), anchor=0 if self._items else None, cursor=len(self._items) - 1)
        return "break"

    def _move_cursor(self, step: int, *, extend: bool) -> str:
        if not self._items:
            return "break"
        start = self._cursor if self._cursor is not None else (-1 if step > 0 else len(self._items))
        target = max(0, min(len(self._items) - 1, start + step))
        if extend and self._anchor is not None:
            low, high = sorted((self._anchor, target))
            self._set_selection(set(range(low, high + 1)), anchor=self._anchor, cursor=target)
        else:
            self._set_selection({target}, anchor=target, cursor=target)
        self._ensure_visible(target)
        return "break"

    def _activate(self) -> None:
        if self._on_activate and self._enabled:
            self._on_activate()


@dataclass(frozen=True, slots=True)
class Column:
    """One column of a ``DataGrid``."""

    title: str
    anchor: str = "w"  # "w", "e" or "center"
    width: int | None = None  # None: as wide as its heading and its longest values
    stretch: bool = False  # takes the room left over when the table is narrower than its window
    min_width: int = 44


class DataGrid(ttk.Frame):
    """A read-only table of text that scrolls smoothly however many rows and columns it has.

    ``ttk.Treeview`` repaints every visible cell, and the heading cells too, on every scroll step, which with the Sun
    Valley theme costs 100 ms or more. This grid draws plain text on a canvas and only for the rows and columns in view,
    so a step costs a few milliseconds. One row can be selected (click, or the arrow keys); rows can carry a tag that
    tints them: ``invalid`` / ``out`` (red) or ``missing`` / ``gap`` (amber).
    """

    ROW_HEIGHT = 28
    HEAD_HEIGHT = 32
    WHEEL_ROWS = 3
    MAX_COLUMN_WIDTH = 420
    HORIZONTAL_STEP = 48

    def __init__(
        self,
        master,
        palette: Palette,
        *,
        on_select: Callable[[int], None] | None = None,
        font_size: int = 10,
        row_height: int | None = None,
        padding: int = 12,
    ) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.palette = palette
        self._on_select = on_select
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self._row_design = row_height or self.ROW_HEIGHT
        self._padding = padding  # between a cell's edge and its text
        self._font = tkfont.Font(root=self, family="Segoe UI", size=font_size)
        self._head_font = tkfont.Font(root=self, family="Segoe UI Semibold", size=9)

        self._columns: list[Column] = []
        self._widths: list[int] = []
        self._rows: list[tuple[str, ...]] = []
        self._tags: list[str] = []
        self._selected: int | None = None
        self._hover: int | None = None
        self._yoff = 0
        self._xoff = 0
        self._empty_text = ""
        self._measured: dict[tuple[str, bool], int] = {}
        self._pending_see: int | None = None  # a row to bring into view as soon as the grid has a size
        self._scroll_job: str | None = None  # a scroll redraw waiting for the next idle moment
        self._bars: dict[str, tuple[float, float]] = {}  # what each scrollbar was last told

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._border = tk.Frame(self, bg=palette.line, padx=1, pady=1, highlightthickness=0)
        self._border.grid(row=0, column=0, sticky="nsew")
        self._border.columnconfigure(0, weight=1)
        self._border.rowconfigure(1, weight=1)
        self._head = tk.Canvas(self._border, height=self._px(self.HEAD_HEIGHT), highlightthickness=0, bd=0, bg=palette.soft)
        self._head.grid(row=0, column=0, sticky="ew")
        self._body = tk.Canvas(
            self._border, width=self._px(300), height=self._px(120), highlightthickness=0, bd=0, bg=palette.surface,
            takefocus=True,
        )
        self._body.grid(row=1, column=0, sticky="nsew")
        self._vscroll = ttk.Scrollbar(self._border, orient="vertical", command=self._yview)
        self._vscroll.grid(row=0, column=1, rowspan=2, sticky="ns")
        self._hscroll = ttk.Scrollbar(self._border, orient="horizontal", command=self._xview)
        self._hscroll.grid(row=2, column=0, sticky="ew")
        self._corner = tk.Frame(self._border, bg=palette.surface, highlightthickness=0, bd=0)
        self._corner.grid(row=2, column=1, sticky="nsew")

        body = self._body
        body.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self._head.bind("<Configure>", lambda _e: self._redraw_head(), add="+")
        body.bind("<Button-1>", self._on_press)
        body.bind("<Motion>", self._on_motion)
        body.bind("<Leave>", self._on_leave)
        for widget in (body, self._head):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Shift-MouseWheel>", self._on_shift_wheel)
            widget.bind("<Button-4>", lambda e: self._on_wheel(e, 120))
            widget.bind("<Button-5>", lambda e: self._on_wheel(e, -120))
        body.bind("<FocusIn>", lambda _e: self._border.configure(bg=self.palette.accent))
        body.bind("<FocusOut>", lambda _e: self._border.configure(bg=self.palette.line))
        for key, step in (("Up", -1), ("Down", 1)):
            body.bind(f"<{key}>", lambda _e, s=step: self._move(s))
        body.bind("<Prior>", lambda _e: self._move(-self._page_rows()))
        body.bind("<Next>", lambda _e: self._move(self._page_rows()))
        body.bind("<Home>", lambda _e: self._move(-len(self._rows)))
        body.bind("<End>", lambda _e: self._move(len(self._rows)))
        body.bind("<Left>", lambda _e: self._xview("scroll", -1, "units"))
        body.bind("<Right>", lambda _e: self._xview("scroll", 1, "units"))

    # ------------------------------------------------------------------ public API
    def set_table(
        self,
        columns: Sequence[Column],
        rows: Sequence[Sequence[object]],
        tags: Sequence[str] | None = None,
        empty_text: str = "",
    ) -> None:
        """Replace the whole table. ``empty_text`` fills the grid while there are no rows."""
        columns = list(columns)
        rows = [tuple("" if value is None else str(value) for value in row) for row in rows]
        if tags is not None and len(tags) != len(rows):
            raise ValueError("one tag per row is needed")
        widths = self._fit(columns, rows)
        header_changed = columns != self._columns or widths != self._widths
        if columns != self._columns:
            self._xoff = 0
        self._columns, self._rows, self._empty_text, self._widths = columns, rows, empty_text, widths
        self._tags = list(tags) if tags is not None else [""] * len(rows)
        if self._selected is not None and self._selected >= len(rows):
            self._selected = None
        self._hover = None
        self._redraw_body()
        if header_changed:
            self._redraw_head()

    def rows(self) -> list[tuple[str, ...]]:
        return list(self._rows)

    def tags(self) -> list[str]:
        return list(self._tags)

    def headings(self) -> list[str]:
        return [column.title for column in self._columns]

    def column_widths(self) -> list[int]:
        return list(self._widths)

    def selected_index(self) -> int | None:
        return self._selected

    def select(self, index: int | None, *, notify: bool = True) -> None:
        """Select a row (None for none) and scroll it into view; ``notify`` calls ``on_select`` if it changed."""
        if index is not None and not 0 <= index < len(self._rows):
            index = None
        changed = index != self._selected
        self._selected = index
        if index is not None:
            self._ensure_visible(index)
        self._redraw_body()
        if changed and notify and index is not None and self._on_select:
            self._on_select(index)

    def reset_view(self) -> None:
        self._yoff = self._xoff = 0
        self._redraw()

    def text_width(self, text: str, *, heading: bool = False) -> int:
        """Pixels the text needs, for choosing a column width."""
        key = (text, heading)
        if key not in self._measured:
            if len(self._measured) > 20000:
                self._measured.clear()
            self._measured[key] = (self._head_font if heading else self._font).measure(text)
        return self._measured[key]

    def width_for(self, title: str, texts: Sequence[str] = ()) -> int:
        """The column width that fits the heading and all of ``texts``."""
        widest = max([self.text_width(title, heading=True), *(self.text_width(text) for text in texts)])
        return widest + 2 * self._px(self._padding)

    def scaled(self, pixels: int) -> int:
        """A design pixel size for this display (it grows on a scaled, high-DPI screen)."""
        return self._px(pixels)

    def focus_body(self) -> None:
        self._body.focus_set()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._border.configure(bg=palette.accent if self.focus_displayof() is self._body else palette.line)
        self._head.configure(bg=palette.soft)
        self._body.configure(bg=palette.surface)
        self._corner.configure(bg=palette.surface)
        self._redraw()

    # ------------------------------------------------------------------ geometry
    def _px(self, value: float) -> int:
        return max(1, round(value * self._scale))

    def _row_height(self) -> int:
        return self._px(self._row_design)

    def _view(self) -> tuple[int, int]:
        return max(1, self._body.winfo_width()), max(1, self._body.winfo_height())

    def _page_rows(self) -> int:
        return max(1, self._view()[1] // self._row_height() - 1)

    def _fit(self, columns: Sequence[Column], rows: Sequence[tuple[str, ...]]) -> list[int]:
        """Each column as wide as its heading and its longest values (only the few longest are measured)."""
        padding = 2 * self._px(self._padding)
        widths = []
        for index, column in enumerate(columns):
            if column.width is not None:
                widths.append(max(self._px(column.min_width), column.width))
                continue
            longest = sorted({row[index] for row in rows if index < len(row)}, key=len, reverse=True)[:4]
            data = max((self.text_width(text) for text in longest), default=0) + padding
            heading = self.text_width(column.title, heading=True) + padding + self._px(6)
            widths.append(min(self._px(self.MAX_COLUMN_WIDTH), max(data, heading, self._px(column.min_width))))
        return widths

    def _effective_widths(self, viewport: int) -> list[int]:
        """The column widths, with the room left over given to the columns that stretch."""
        widths = list(self._widths)
        stretching = [i for i, column in enumerate(self._columns) if column.stretch]
        spare = viewport - sum(widths)
        if spare > 0 and stretching:
            share, extra = divmod(spare, len(stretching))
            for position, index in enumerate(stretching):
                widths[index] += share + (1 if position < extra else 0)
        return widths

    def _max_yoff(self) -> int:
        return max(0, len(self._rows) * self._row_height() - self._view()[1])

    def _max_xoff(self) -> int:
        width = self._view()[0]
        return max(0, sum(self._effective_widths(width)) - width)

    # ------------------------------------------------------------------ drawing
    def _fit_text(self, text: str, width: int, heading: bool = False) -> str:
        if self.text_width(text, heading=heading) <= width:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self.text_width(text[:middle] + "…", heading=heading) <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low] + "…"

    def _cell_text(self, canvas: tk.Canvas, text: str, column: Column, left: float, width: int, y: float, ink: str, font: tkfont.Font) -> None:
        pad = self._px(self._padding)
        text = self._fit_text(text, max(1, width - 2 * pad), heading=font is self._head_font)
        if column.anchor == "e":
            x, anchor = left + width - pad, "e"
        elif column.anchor == "center":
            x, anchor = left + width / 2, "center"
        else:
            x, anchor = left + pad, "w"
        canvas.tk.call(canvas._w, "create", "text", x, y, "-text", text, "-anchor", anchor, "-fill", ink, "-font", font.name)

    def _visible_columns(self, widths: list[int], view_width: int) -> list[tuple[int, int]]:
        """(column, left edge on screen) for the columns that overlap the window."""
        visible, left = [], -self._xoff
        for index, width in enumerate(widths):
            if left + width > 0 and left < view_width:
                visible.append((index, left))
            left += width
            if left >= view_width:
                break
        return visible

    def _row_colors(self, index: int) -> tuple[str, str]:
        p = self.palette
        tag = self._tags[index]
        tint, ink = {
            "invalid": (p.bad_bg, p.danger), "out": (p.bad_bg, p.danger),
            "missing": (p.warn_bg, p.fg), "gap": (p.warn_bg, p.fg),
        }.get(tag, (None, p.fg))
        if index == self._selected:
            return p.pick, ink
        if tint:
            return tint, ink
        return (p.soft if index == self._hover else p.surface), ink

    def _redraw(self) -> None:
        self._redraw_body()
        self._redraw_head()

    def _redraw_body(self) -> None:
        canvas, p = self._body, self.palette
        canvas.delete("all")
        width, height = self._view()
        if self._pending_see is not None and height >= self._row_height():
            index, self._pending_see = self._pending_see, None
            self._ensure_visible(index)
        self._yoff = max(0, min(self._yoff, self._max_yoff()))
        self._xoff = max(0, min(self._xoff, self._max_xoff()))
        self._update_scrollbars()
        if width <= 1:
            return
        if not self._rows:
            if self._empty_text:
                canvas.create_text(
                    width / 2, height * 0.45, text=self._empty_text, fill=p.muted, font=self._font, justify="center",
                    width=max(100, width - self._px(60)),
                )
            return
        row_h = self._row_height()
        widths = self._effective_widths(width)
        columns = self._visible_columns(widths, width)
        for index in range(self._yoff // row_h, min(len(self._rows), (self._yoff + height) // row_h + 1)):
            top = index * row_h - self._yoff
            fill, ink = self._row_colors(index)
            if fill != p.surface:  # a plain row is just the canvas background
                canvas.tk.call(canvas._w, "create", "rectangle", 0, top, width, top + row_h, "-fill", fill, "-outline", "")
            canvas.tk.call(canvas._w, "create", "line", 0, top + row_h - 1, width, top + row_h - 1, "-fill", p.line)
            row, middle = self._rows[index], top + row_h / 2
            for column, left in columns:
                if column < len(row) and row[column]:
                    self._cell_text(canvas, row[column], self._columns[column], left, widths[column], middle, ink, self._font)

    def _redraw_head(self) -> None:
        canvas, p = self._head, self.palette
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or not self._columns:
            return
        middle = height / 2
        widths = self._effective_widths(self._view()[0])
        for index, left in self._visible_columns(widths, width):
            self._cell_text(canvas, self._columns[index].title, self._columns[index], left, widths[index], middle, p.muted, self._head_font)
            canvas.create_line(left + widths[index] - 1, self._px(7), left + widths[index] - 1, height - self._px(7), fill=p.line)
        canvas.create_line(0, height - 1, width, height - 1, fill=p.line)

    def _update_scrollbars(self) -> None:
        width, height = self._view()
        total_h, total_w = len(self._rows) * self._row_height(), sum(self._effective_widths(width))
        vertical = (0.0, 1.0) if total_h <= height else (self._yoff / total_h, min(1.0, (self._yoff + height) / total_h))
        horizontal = (0.0, 1.0) if total_w <= width else (self._xoff / total_w, min(1.0, (self._xoff + width) / total_w))
        for name, bar, values in (("v", self._vscroll, vertical), ("h", self._hscroll, horizontal)):
            if self._bars.get(name) != values:
                self._bars[name] = values
                bar.set(*values)
        # The sideways bar only shows when the columns are wider than the window. (The vertical one always shows: if
        # it came and went, its width would change what fits sideways, and the two could keep switching each other.)
        needed = total_w > width
        if needed != bool(self._hscroll.winfo_manager()):
            if needed:
                self._hscroll.grid()
                self._corner.grid()
            else:
                self._hscroll.grid_remove()
                self._corner.grid_remove()

    # ------------------------------------------------------------------ scrolling
    def _later(self, header: bool) -> None:
        """Redraw at the next idle moment. A fast wheel sends many events; they all move the offset at once and one
        redraw shows the result, so the table never falls behind the wheel."""
        self._scroll_header = header or (self._scroll_job is not None and getattr(self, "_scroll_header", False))
        if self._scroll_job is None:
            self._scroll_job = self.after_idle(self._flush_scroll)

    def _flush_scroll(self) -> None:
        self._scroll_job = None
        self._redraw_body()
        if self._scroll_header:
            self._redraw_head()

    def _scroll_y(self, offset: float) -> None:
        offset = int(max(0, min(offset, self._max_yoff())))
        if offset != self._yoff:
            self._yoff = offset
            self._later(header=False)

    def _scroll_x(self, offset: float) -> None:
        offset = int(max(0, min(offset, self._max_xoff())))
        if offset != self._xoff:
            self._xoff = offset
            self._later(header=True)

    def _yview(self, *args) -> None:
        if args[0] == "moveto":
            self._scroll_y(float(args[1]) * len(self._rows) * self._row_height())
        elif args[0] == "scroll":
            unit = self._row_height() if args[2] == "units" else self._view()[1]
            self._scroll_y(self._yoff + int(args[1]) * unit)

    def _xview(self, *args) -> None:
        width = self._view()[0]
        if args[0] == "moveto":
            self._scroll_x(float(args[1]) * sum(self._effective_widths(width)))
        elif args[0] == "scroll":
            unit = self._px(self.HORIZONTAL_STEP) if args[2] == "units" else width
            self._scroll_x(self._xoff + int(args[1]) * unit)

    def _on_wheel(self, event, delta: int | None = None) -> str:
        self._scroll_y(self._yoff - (delta if delta is not None else event.delta) / 120 * self.WHEEL_ROWS * self._row_height())
        return "break"

    def _on_shift_wheel(self, event) -> str:
        self._scroll_x(self._xoff - event.delta / 120 * 3 * self._px(self.HORIZONTAL_STEP))
        return "break"

    def _ensure_visible(self, index: int) -> None:
        row_h = self._row_height()
        top, bottom = index * row_h, (index + 1) * row_h
        height = self._view()[1]
        if height < row_h:  # not laid out yet: do it when it is
            self._pending_see = index
            return
        if top < self._yoff:
            self._yoff = top
        elif bottom > self._yoff + height:
            self._yoff = bottom - height
        self._yoff = max(0, min(self._yoff, self._max_yoff()))

    # ------------------------------------------------------------------ pointer and keys
    def _row_at(self, y: int) -> int | None:
        index = (y + self._yoff) // self._row_height()
        return index if y >= 0 and 0 <= index < len(self._rows) else None

    def _on_press(self, event) -> str:
        self._body.focus_set()
        index = self._row_at(event.y)
        if index is not None:
            self.select(index)
        return "break"

    def _on_motion(self, event) -> None:
        index = self._row_at(event.y)
        if index != self._hover:
            self._hover = index
            self._redraw_body()

    def _on_leave(self, _event) -> None:
        if self._hover is not None:
            self._hover = None
            self._redraw_body()

    def _move(self, step: int) -> str:
        if self._rows:
            start = self._selected if self._selected is not None else (-1 if step > 0 else len(self._rows))
            self.select(max(0, min(len(self._rows) - 1, start + step)))
        return "break"


class StepBar(ttk.Frame):
    """Numbered steps side by side. Each is ``current`` (filled), ``complete`` (green), ``ready`` (outlined),
    ``warn`` (outlined in amber) or ``locked`` (grey and not clickable)."""

    def __init__(self, master, palette: Palette, titles: Sequence[str], on_select: Callable[[int], None]) -> None:
        super().__init__(master)
        self.palette = palette
        self._on_select = on_select
        self._state = ["ready"] * len(titles)
        self._caption = [""] * len(titles)
        self._cells: list[dict] = []
        self._title_font = tkfont.Font(root=self, family="Segoe UI Semibold", size=11)
        self._caption_font = tkfont.Font(root=self, family="Segoe UI", size=9)
        scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self._badge = max(1, round(28 * scale))

        for index, title in enumerate(titles):
            column = index * 2
            if index:
                ttk.Label(self, text="›", style="Muted.TLabel", font=("Segoe UI", 14)).grid(row=0, column=column - 1, padx=8)
            self.columnconfigure(column, weight=1, uniform="steps")
            frame = tk.Frame(self, bd=0, highlightthickness=1, padx=14, pady=6, takefocus=True)
            frame.grid(row=0, column=column, sticky="ew")
            badge = tk.Canvas(frame, width=self._badge, height=self._badge, bd=0, highlightthickness=0)
            badge.pack(side="left", padx=(0, 10))
            text = tk.Frame(frame, bd=0, highlightthickness=0)
            text.pack(side="left", fill="x", expand=True)
            title_label = tk.Label(text, text=title, anchor="w", font=self._title_font, bd=0, padx=0, pady=0)
            title_label.pack(fill="x")
            caption_label = tk.Label(text, anchor="w", font=self._caption_font, bd=0, padx=0, pady=0)
            caption_label.pack(fill="x")
            for widget in (frame, badge, text, title_label, caption_label):
                widget.bind("<Button-1>", lambda _e, i=index: self._click(i), add="+")
            frame.bind("<Return>", lambda _e, i=index: self._click(i))
            frame.bind("<space>", lambda _e, i=index: self._click(i))
            self._cells.append({"frame": frame, "badge": badge, "text": text, "title": title_label, "caption": caption_label})
        self._paint()

    def set_step(self, index: int, state: str, caption: str) -> None:
        if (state, caption) != (self._state[index], self._caption[index]):
            self._state[index], self._caption[index] = state, caption
            self._paint()

    def state(self, index: int) -> str:
        return self._state[index]

    def caption(self, index: int) -> str:
        return self._caption[index]

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._paint()

    def click(self, index: int) -> None:
        self._click(index)

    def _click(self, index: int) -> None:
        if self._state[index] != "locked":
            self._on_select(index)

    def _colors(self, state: str) -> dict[str, str]:
        p = self.palette
        return {
            "current": {"bg": p.accent, "line": p.accent, "title": p.on_accent, "caption": p.on_accent,
                        "badge": p.on_accent, "badge_line": p.on_accent, "badge_text": p.accent},
            "complete": {"bg": p.ok_bg, "line": p.ok_line, "title": p.ok, "caption": p.ok,
                         "badge": p.ok, "badge_line": p.ok, "badge_text": p.surface},
            "ready": {"bg": p.surface, "line": p.accent, "title": p.accent, "caption": p.accent,
                      "badge": p.surface, "badge_line": p.accent, "badge_text": p.accent},
            "warn": {"bg": p.surface, "line": p.warn_line, "title": p.warn, "caption": p.warn,
                     "badge": p.surface, "badge_line": p.warn, "badge_text": p.warn},
            "locked": {"bg": p.soft, "line": p.line, "title": p.muted, "caption": p.muted,
                       "badge": p.soft, "badge_line": p.muted, "badge_text": p.muted},
        }[state]

    def _paint(self) -> None:
        for index, cell in enumerate(self._cells):
            state = self._state[index]
            c = self._colors(state)
            cell["frame"].configure(bg=c["bg"], highlightbackground=c["line"], highlightcolor=self.palette.fg,
                                    cursor="" if state == "locked" else "hand2")
            cell["text"].configure(bg=c["bg"])
            cell["title"].configure(bg=c["bg"], fg=c["title"])
            cell["caption"].configure(bg=c["bg"], fg=c["caption"], text=self._caption[index])
            badge = cell["badge"]
            badge.configure(bg=c["bg"])
            badge.delete("all")
            size = self._badge
            badge.create_oval(2, 2, size - 2, size - 2, fill=c["badge"], outline=c["badge_line"], width=2)
            badge.create_text(size / 2, size / 2, text="✓" if state == "complete" else str(index + 1), fill=c["badge_text"],
                              font=("Segoe UI Semibold", 10))


class ChipRow(ttk.Frame):
    """Short coloured notes that wrap onto more lines when the window is narrow. Levels: ok, warn, bad, info."""

    def __init__(self, master, palette: Palette) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.palette = palette
        self._chips: list[tuple[str, str, tk.Label]] = []
        self._font = tkfont.Font(root=self, family="Segoe UI", size=9)
        self._wrapped_at = -1
        self.bind("<Configure>", lambda event: self._wrap(event.width), add="+")

    def set_chips(self, chips: Sequence[tuple[str, str]]) -> None:
        """``chips``: (level, text) pairs."""
        if [(level, text) for level, text, _ in self._chips] == list(chips):
            return
        for _level, _text, label in self._chips:
            label.destroy()
        self._chips = []
        for level, text in chips:
            label = tk.Label(self, text=text, font=self._font, padx=10, pady=3, bd=0, highlightthickness=1)
            self._chips.append((level, text, label))
        self._paint()
        self._wrapped_at = -1
        self._wrap(self.winfo_width())

    def chips(self) -> list[tuple[str, str]]:
        return [(level, text) for level, text, _ in self._chips]

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._paint()

    def _paint(self) -> None:
        p = self.palette
        colors = {
            "ok": (p.ok_bg, p.ok_line, p.ok), "warn": (p.warn_bg, p.warn_line, p.warn),
            "bad": (p.bad_bg, p.bad_line, p.danger), "info": (p.soft, p.line, p.muted),
        }
        for level, _text, label in self._chips:
            bg, line, fg = colors[level]
            label.configure(bg=bg, fg=fg, highlightbackground=line)

    def _wrap(self, width: int) -> None:
        if width <= 1 or width == self._wrapped_at or not self._chips:
            return
        self._wrapped_at = width
        gap, x, row, column = 8, 0, 0, 0
        for _level, _text, label in self._chips:
            needed = label.winfo_reqwidth() + gap
            if column and x + needed > width:
                row, column, x = row + 1, 0, 0
            label.grid(row=row, column=column, sticky="w", padx=(0, gap), pady=(0, 6))
            x += needed
            column += 1
