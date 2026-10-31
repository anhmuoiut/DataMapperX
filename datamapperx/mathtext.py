r"""A small subset of LaTeX for the formulas of "About the method": parsed to a tree, written as plain text, or laid out as boxes.

Supported: ``\frac{a}{b}``, ``\sqrt{a}``, ``\bar{x}``, ``x_{i}``, ``x^{2}``, ``\sum_{i=1}^{p}``, ``\left( ... \right)``, ``\text{words}``,
``\min``, ``\max``, ``\floor``, the symbols in ``SYMBOLS`` and ``\,`` for a thin space. Spaces in the source are ignored and the binary
operators (= + - x <= >=) are spaced when written. Nothing here needs a GUI: ``ui/math_view.py`` supplies text metrics and draws the boxes.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

SYMBOLS = {"sigma": ("σ", True), "mu": ("μ", True), "alpha": ("α", True), "Gamma": ("Γ", False), "times": ("×", False),
           "cdot": ("·", False), "le": ("≤", False), "ge": ("≥", False), "pm": ("±", False)}
WORDS = ("min", "max", "floor")  # function names, written upright
PADDED = set("=+−×≤≥<>")  # binary operators get a little space around them

Node = tuple


class _Parser:
    def __init__(self, source: str):
        self.s, self.i = source, 0
        self.script = 0  # > 0 while reading a subscript or superscript

    def parse(self) -> Node:
        node = self.row()
        if self.i != len(self.s):
            raise ValueError(f"Unexpected {self.s[self.i]!r} in {self.s!r}")
        return node

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, text: str) -> None:
        if not self.s.startswith(text, self.i):
            raise ValueError(f"Expected {text!r} at {self.i} in {self.s!r}")
        self.i += len(text)

    def row(self) -> Node:
        items: list[Node] = []
        while self.i < len(self.s) and self.peek() != "}" and not self.s.startswith("\\right", self.i):
            node = self.postfix(self.atom())
            last = items[-1] if items else None
            if (last and last[0] == "t" and node[0] == "t" and last[2] == node[2]
                    and last[1][-1] not in PADDED and node[1] not in PADDED):
                items[-1] = ("t", last[1] + node[1], last[2])  # one run of text, not a box per letter
            elif node != ("space", 0):
                items.append(node)
        return ("row", tuple(items))

    def group(self) -> Node:
        if self.peek() == "{":
            self.i += 1
            inner = self.row()
            self.expect("}")
            return inner
        return ("row", (self.atom(),))  # a single token, as in x_i

    def atom(self) -> Node:
        char = self.peek()
        if not char:
            raise ValueError(f"The formula ends too soon: {self.s!r}")
        if char == "\\":
            return self.command()
        if char == "{":
            return self.group()
        if char.isalpha():  # a run of letters is one name (SS, USL, ndc) and takes the subscript that follows
            start = self.i
            while self.peek().isalpha():
                self.i += 1
            name = self.s[start:self.i]
            return ("t", name, len(name) == 1 or bool(self.script))  # a name of two letters or more is upright, except in a subscript
        self.i += 1
        if char == " ":
            return ("space", 0)
        return ("t", "−" if char == "-" else char, False)

    def command(self) -> Node:
        self.i += 1
        start = self.i
        while self.peek().isalpha():
            self.i += 1
        name = self.s[start:self.i] or self.peek()
        if self.i == start:
            self.i += 1
        if name == "frac":
            return ("frac", self.group(), self.group())
        if name in ("sqrt", "bar"):
            return (name, self.group())
        if name == "text":
            self.expect("{")
            end = self.s.index("}", self.i)
            text, self.i = self.s[self.i:end], end + 1
            return ("t", text, False)
        if name == "left":
            self.expect("(")
            inner = self.row()
            self.expect("\\right)")
            return ("paren", inner)
        if name == "sum":
            return ("sum", None, None)
        if name in (",", " "):
            return ("space", 0.2)
        if name == "quad":
            return ("space", 1.0)
        if name in SYMBOLS:
            return ("t", *SYMBOLS[name])
        if name in WORDS:
            return ("t", name, False)
        raise ValueError(f"Unknown command \\{name} in {self.s!r}")

    def postfix(self, node: Node) -> Node:
        sub = sup = None
        while self.peek() in ("_", "^") and self.peek():
            kind = self.peek()
            self.i += 1
            self.script += 1
            if kind == "_":
                sub = _labels_upright(self.group())
            else:
                sup = self.group()
            self.script -= 1
        if sub is None and sup is None:
            return node
        return ("sum", sub, sup) if node[0] == "sum" else ("script", node, sub, sup)


def _labels_upright(row: Node) -> Node:
    """Words of three letters or more in a subscript are labels (Part, Error), not products of variables."""
    return ("row", tuple(("t", n[1], False) if n[0] == "t" and n[2] and len(n[1]) > 2 and n[1].isalpha() else n for n in row[1]))


def parse(source: str) -> Node:
    return _Parser(source).parse()


# ----------------------------------------------------------------------------- plain text
def to_text(node: Node | str) -> str:
    """The formula as one line of text, for tests, copying and anywhere nothing can be drawn."""
    if isinstance(node, str):
        node = parse(node)
    kind = node[0]
    if kind == "row":
        return "".join(f" {to_text(n)} " if n[0] == "t" and n[1] in PADDED else to_text(n) for n in node[1])
    if kind == "t":
        return node[1]
    if kind == "frac":
        return f"{_wrap(node[1])}/{_wrap(node[2])}"
    if kind == "sqrt":
        return f"√({to_text(node[1])})"
    if kind == "bar":
        return to_text(node[1]) + "̄"
    if kind == "paren":
        return f"({to_text(node[1])})"
    if kind == "sum":
        return "Σ" + (f"_{_wrap(node[1])}" if node[1] else "") + (f"^{_wrap(node[2])}" if node[2] else "")
    if kind == "script":
        return to_text(node[1]) + (f"_{_wrap(node[2])}" if node[2] else "") + (f"^{_wrap(node[3])}" if node[3] else "")
    return ""


def _wrap(node: Node) -> str:
    text = to_text(node)
    return text if len(text) == 1 or text.replace(".", "").isalnum() else f"({text})"


# ----------------------------------------------------------------------------- layout
@dataclass(frozen=True)
class Box:
    """A laid-out piece of formula. ``ops`` use x from the left edge and y from the baseline (down is positive):
    ``("t", x, y, text, size, italic)`` is text whose baseline starts at (x, y); ``("l", points, width, smooth)`` is a line."""
    w: float
    asc: float
    desc: float
    ops: tuple = ()


Measure = Callable[[str, float, bool], tuple[float, float, float]]  # text, size, italic -> width, ascent, descent


def _move(box: Box, dx: float, dy: float) -> tuple:
    return tuple(("t", op[1] + dx, op[2] + dy, *op[3:]) if op[0] == "t"
                 else ("l", tuple((x + dx, y + dy) for x, y in op[1]), *op[2:]) for op in box.ops)


def layout(node: Node | str, size: float, measure: Measure) -> Box:
    """Boxes for ``node`` at ``size`` pixels. ``measure`` gives the width, ascent and descent of a text run."""
    if isinstance(node, str):
        node = parse(node)
    kind = node[0]
    axis, gap = 0.3 * size, 0.12 * size
    if kind == "t":
        width, asc, desc = measure(node[1], size, node[2])
        pad = 0.25 * size if node[1] in PADDED else 0.0
        return Box(width + 2 * pad, asc, desc, (("t", pad, 0.0, node[1], size, node[2]),))
    if kind == "space":
        return Box(node[1] * size, 0, 0)
    if kind == "row":
        x, boxes = 0.0, [layout(n, size, measure) for n in node[1]]
        ops: tuple = ()
        for box in boxes:
            ops += _move(box, x, 0.0)
            x += box.w
        return Box(x, max((b.asc for b in boxes), default=0), max((b.desc for b in boxes), default=0), ops)
    if kind == "frac":
        num, den = layout(node[1], size, measure), layout(node[2], size, measure)
        width = max(num.w, den.w) + 0.3 * size
        ops = (*_move(num, (width - num.w) / 2, -axis - gap - num.desc), *_move(den, (width - den.w) / 2, -axis + gap + den.asc),
               ("l", ((0.0, -axis), (width, -axis)), 1.0, False))
        return Box(width, axis + gap + num.desc + num.asc, max(0.0, den.asc + den.desc + gap - axis), ops)
    if kind == "sqrt":
        inner = layout(node[1], size, measure)
        radical, top = 0.8 * size, -inner.asc - 0.25 * size
        line = ((0.0, -0.3 * size), (0.3 * radical, inner.desc), (radical, top), (radical + inner.w + 2, top))
        return Box(radical + inner.w + 3, inner.asc + 0.25 * size + 1, inner.desc,
                   (*_move(inner, radical + 1, 0.0), ("l", line, 1.0, False)))
    if kind == "bar":
        inner = layout(node[1], size, measure)
        y, shift = -inner.asc - 0.1 * size, (0.2 * size if len(node[1][1]) == 1 else 0.0)  # a slanted letter's top is to the right
        return Box(inner.w, inner.asc + 0.2 * size, inner.desc,
                   (*inner.ops, ("l", ((shift, y), (inner.w + shift / 4, y)), 1.0, False)))
    if kind == "paren":
        inner = layout(node[1], size, measure)
        width, asc, desc = measure("(", size, False)
        if inner.asc + inner.desc <= 1.2 * (asc + desc):  # one line of text: the ordinary characters
            ops = (("t", 0.0, 0.0, "(", size, False), *_move(inner, width, 0.0), ("t", width + inner.w, 0.0, ")", size, False))
            return Box(2 * width + inner.w, max(asc, inner.asc), max(desc, inner.desc), ops)
        curve, top, bottom = 0.3 * size, -inner.asc - 1, inner.desc + 1
        mid = (top + bottom) / 2
        left = ("l", ((curve, top), (0.0, mid), (curve, bottom)), 1.0, True)
        right = ("l", ((curve + 2 + inner.w, top), (2 * curve + 2 + inner.w, mid), (curve + 2 + inner.w, bottom)), 1.0, True)
        return Box(2 * curve + inner.w + 2, inner.asc + 1, inner.desc + 1, (left, *_move(inner, curve + 1, 0.0), right))
    if kind == "script":
        base = layout(node[1], size, measure)
        small = 0.72 * size
        sub = layout(node[2], small, measure) if node[2] else None
        sup = layout(node[3], small, measure) if node[3] else None
        ops, width = base.ops, base.w + 1
        asc, desc, extent = base.asc, base.desc, 0.0
        if sup:
            lift = max(0.4 * size, base.asc * 0.6)
            ops += _move(sup, width, -lift)
            asc, extent = max(asc, lift + sup.asc), sup.w
        if sub:
            drop = max(0.25 * size, base.desc * 0.6 + 0.15 * size)
            ops += _move(sub, width, drop)
            desc, extent = max(desc, drop + sub.desc), max(extent, sub.w)
        return Box(width + extent, asc, desc, ops)
    if kind == "sum":
        glyph = measure("Σ", 1.5 * size, False)
        low = layout(node[1], 0.72 * size, measure) if node[1] else None
        high = layout(node[2], 0.72 * size, measure) if node[2] else None
        height = 0.75 * 1.5 * size  # about the height of a capital
        base_y = -axis + height / 2
        width = max(glyph[0], low.w if low else 0, high.w if high else 0) + 0.2 * size
        ops = (("t", (width - glyph[0]) / 2, base_y, "Σ", 1.5 * size, False),)
        asc, desc = height / 2 + axis, max(0.0, height / 2 - axis)
        if high:
            ops += _move(high, (width - high.w) / 2, base_y - height - gap - high.desc)
            asc += gap + high.asc + high.desc
        if low:
            ops += _move(low, (width - low.w) / 2, base_y + gap + low.asc)
            desc += gap + low.asc + low.desc
        return Box(width, asc, desc, ops)
    raise ValueError(f"Cannot lay out {kind!r}")
