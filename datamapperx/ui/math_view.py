"""A formula drawn on a canvas: fractions, subscripts, roots and Greek letters, from ``mathtext`` source."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont

from ..mathtext import layout, parse
from ..palette import Palette

MATH_SIZE = 15  # pixels


class MathView(tk.Canvas):
    def __init__(self, parent: tk.Misc, source: str, palette: Palette, *, size: float = MATH_SIZE, background: str | None = None):
        self._font_master, self._fonts = parent, {}  # not _root: tkinter's widgets have a method of that name
        self._family = tkfont.nametofont("TkDefaultFont", root=parent).actual("family")
        box = layout(parse(source), size, self._measure)
        pad = 2
        super().__init__(parent, width=math.ceil(box.w) + 2 * pad + 1, height=math.ceil(box.asc + box.desc) + 2 * pad + 1,
                         bg=background or palette.surface, highlightthickness=0, borderwidth=0)
        self.source = source
        left, base = pad, pad + box.asc
        for op in box.ops:
            if op[0] == "t":
                _, x, y, text, text_size, italic = op
                self.create_text(left + x, base + y + self._font(text_size, italic).metrics("descent"), text=text, anchor="sw",
                                 font=self._font(text_size, italic), fill=palette.fg)
            else:
                _, points, width, smooth = op
                self.create_line(*(c for x, y in points for c in (left + x, base + y)), width=width, fill=palette.fg,
                                 smooth=smooth, capstyle="round")

    def _font(self, size: float, italic: bool) -> tkfont.Font:
        key = (round(size), italic)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(self._font_master, family=self._family, size=-key[0], slant="italic" if italic else "roman")
        return self._fonts[key]

    def _measure(self, text: str, size: float, italic: bool) -> tuple[float, float, float]:
        font = self._font(size, italic)
        metrics = font.metrics()
        return font.measure(text), metrics["ascent"], metrics["descent"]
