"""Fill-in-the-blank patterns: a way to describe a log line without writing a regular expression.

A pattern is text copied from the log in which the parts that change are replaced by blanks in
square brackets, for example::

    {@BLOCK|[Component]|
    {@A-[Unit]|[Any]|[Measured]
    {@LIM2|[Max]|[Min]

``compile_template`` turns such a pattern into the regular expression the parser already uses, so
saved profiles keep their format and experts can still edit the regex directly.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass


class TemplateError(ValueError):
    """A pattern cannot be used. The message is written for the person who typed it."""


@dataclass(frozen=True, slots=True)
class Blank:
    name: str
    group: str | None  # named group in the regular expression; None for "ignore this part"


BLANKS: dict[str, Blank] = {
    blank.name: blank
    for blank in (
        Blank("Component", "component"),
        Blank("Measured", "measured"),
        Blank("Unit", "type"),
        Blank("Min", "min"),
        Blank("Max", "max"),
        Blank("Any", None),  # a part that changes but is not needed
    )
}
_ALIASES = {
    "name": "Component", "value": "Measured", "result": "Measured",
    "type": "Unit", "low": "Min", "lower": "Min", "high": "Max", "upper": "Max", "skip": "Any", "ignore": "Any",
}
_LOOKUP = {**{name.lower(): name for name in BLANKS}, **_ALIASES}


@dataclass(frozen=True, slots=True)
class Rule:
    """Where a pattern is used, which blanks it may contain and which one it must contain."""

    key: str
    title: str
    allowed: tuple[str, ...]
    required: tuple[str, ...]  # at least one of these
    keeps_rest_of_line: bool = False  # measurement lines hand the rest of the line to the limits patterns


RULES: dict[str, Rule] = {
    rule.key: rule
    for rule in (
        Rule("block", "component line", ("Component", "Any"), ("Component",)),
        Rule("measure", "measurement line", ("Measured", "Unit", "Any"), ("Measured",), keeps_rest_of_line=True),
        Rule("limits", "limits", ("Min", "Max", "Any"), ("Min", "Max")),
    )
}
# Which rule each blank is written into when the user marks text in a sample.
RULE_FOR_BLANK = {"Component": "block", "Measured": "measure", "Unit": "measure", "Min": "limits", "Max": "limits"}

# A value that is the last thing in a pattern stops at whitespace or common separators (a component name is
# the exception: it may contain spaces).
_TOKEN = r"[^\s|,;{}()\[\]\"']"
_BLANK_TEXT = re.compile(r"\[([^\[\]]+)\]")
_SEPARATORS = "|,;\t"


def _canonical(word: str) -> str | None:
    key = word.strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    close = difflib.get_close_matches(key, list(_LOOKUP), n=1, cutoff=0.75)
    if close:
        raise TemplateError(f"[{word}] is not a known blank. Did you mean [{_LOOKUP[close[0]]}]?")
    return None  # ordinary text that happens to be in brackets, such as "[INFO]"


Token = tuple[str, str]  # ("text", literal) or ("blank", canonical name)


def tokenize(template: str) -> list[Token]:
    tokens: list[Token] = []
    cursor = 0
    pending = ""
    for match in _BLANK_TEXT.finditer(template):
        name = _canonical(match.group(1))
        if name is None:
            continue
        pending += template[cursor : match.start()]
        if pending:
            tokens.append(("text", pending))
        pending = ""
        tokens.append(("blank", name))
        cursor = match.end()
    pending += template[cursor:]
    if pending:
        tokens.append(("text", pending))
    return tokens


def _literal(text: str) -> str:
    return "".join(r"\s+" if part.isspace() else re.escape(part) for part in re.split(r"(\s+)", text) if part)


def _blank_regex(blank: Blank, following: str | None) -> str:
    """The characters a blank may take, decided by the text that follows it in the pattern."""
    optional = blank.group is None
    count = "*" if optional else "+"
    if following is None and blank.name == "Component":
        body = "[^|{}]+"  # a name that ends the pattern runs to the next field separator (spaces are allowed)
    elif following is None:
        body = ".*" if optional else _TOKEN + "+"
    elif following[0].isspace():
        # A name may contain spaces, any other value is a single word.
        body = ".*?" if optional else (".+?" if blank.name == "Component" else r"\S+")
    elif following[0].isalnum():
        body = ".*?" if optional else ".+?"
    else:
        body = f"[^{re.escape(following[0])}]{count}"
    return f"(?P<{blank.group}>{body})" if blank.group else body


def compile_template(template: str, rule: str) -> str:
    """Return the regular expression for ``template``, or "" when the template is empty."""
    template = template.strip()
    if not template:
        return ""
    spec = RULES[rule]
    tokens = tokenize(template)

    used: list[str] = []
    for kind, value in tokens:
        if kind != "blank":
            continue
        if value not in spec.allowed:
            allowed = ", ".join(f"[{name}]" for name in spec.allowed)
            raise TemplateError(f"[{value}] cannot be used in the {spec.title} pattern. Use: {allowed}.")
        if value != "Any" and value in used:
            raise TemplateError(f"[{value}] can only be used once in a pattern.")
        used.append(value)
    if not any(name in used for name in spec.required):
        needed = " or ".join(f"[{name}]" for name in spec.required)
        raise TemplateError(
            f"The {spec.title} pattern needs {needed}. Replace the part that changes with it, for example "
            f"{_example(rule)}."
        )

    pieces: list[str] = []
    for index, (kind, value) in enumerate(tokens):
        if kind == "text":
            pieces.append(_literal(value))
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following is not None and following[0] == "blank":
            raise TemplateError(
                f"[{value}] and [{following[1]}] are next to each other. Put the text that separates them "
                "(such as | or a space) between them."
            )
        pieces.append(_blank_regex(BLANKS[value], following[1] if following else None))
    if spec.keeps_rest_of_line:
        pieces.append("(?P<tail>.*)")
    return "".join(pieces)


def _example(rule: str) -> str:
    return {"block": "{@BLOCK|[Component]|", "measure": "{@A-[Unit]|[Any]|[Measured]", "limits": "{@LIM2|[Max]|[Min]"}[rule]


# --------------------------------------------------------------------------------------------------
# Building a pattern from text the user selected in a sample
# --------------------------------------------------------------------------------------------------
Mark = tuple[int, int, str]  # (start, end, blank name) within one line


def _limits_start(line: str, first: int) -> int:
    """Limits sit inside a tag such as {@LIM2|...}, so start the pattern at that tag, not at the line start."""
    before = line[:first]
    bracket = max(before.rfind(c) for c in "{([<")
    if bracket >= 0:
        return bracket
    label = re.search(r"\S+\s*$", before)
    return label.start() if label else first


_NUMERIC_FIELD = re.compile(r"(?<=[|,;\t])[+-]?\d+(?:\.\d+)?(?=[|,;\t])")


def template_from_marks(line: str, marks: Sequence[Mark], rule: str) -> str:
    """Replace each marked span of ``line`` by its blank and trim the line down to a reusable pattern."""
    if not marks:
        raise TemplateError("Select some text first.")
    spans = sorted(marks)
    previous_end = 0
    for start, end, name in spans:
        if not 0 <= start < end <= len(line):
            raise TemplateError("The selection must be inside a single line.")
        if start < previous_end:
            raise TemplateError("Two selections overlap. Select each part separately.")
        if name not in BLANKS:
            raise TemplateError(f"[{name}] is not a known blank.")
        previous_end = end

    cursor = _limits_start(line, spans[0][0]) if rule == "limits" else len(line) - len(line.lstrip())
    pieces: list[str] = []
    for start, end, name in spans:
        literal = line[cursor:start]
        if rule == "measure":
            # A bare number between separators (a channel or status field) differs from line to line.
            literal = _NUMERIC_FIELD.sub("[Any]", literal)
        pieces.append(literal)
        pieces.append(f"[{name}]")
        cursor = end
    if rule == "block":
        pieces.append(_block_suffix(line[cursor:]))
    return "".join(pieces).strip()


_STATUS_FIELD = re.compile(r"([|,;\t])(\d+)(?=[|,;\t]|\s*$)")


def _block_suffix(rest: str) -> str:
    """What to keep after the component name.

    The separator right after it keeps a name that contains spaces from being cut short. A short number after
    that separator (``|00``) is a status, and requiring it is how failed attempts (``|01``) are left out when
    the same component was measured again. When the name is followed by a plain word (``R1 done``) that word is
    kept too: without it the name would run to the end of the line.
    """
    if rest and rest[0].isspace():
        word = re.match(r"\s+([A-Za-z_]+)(?=\s|$)", rest)
        return f" {word.group(1)}" if word else ""
    if not rest or rest[0].isalnum():
        return ""
    status = _STATUS_FIELD.match(rest)
    return status.group(0) if status else rest[0]


# --------------------------------------------------------------------------------------------------
# Serial numbers
# --------------------------------------------------------------------------------------------------
def sn_regex_from_example(example: str) -> str:
    """A pattern for serial numbers that look like ``example`` (same leading letters, same character kinds)."""
    text = example.strip()
    if not text:
        raise TemplateError("Type or select an example serial number.")
    if re.search(r"\s", text):
        raise TemplateError("A serial number cannot contain spaces. Select just the serial number.")
    letters = re.match(r"[A-Za-z]+", text)
    prefix = letters.group(0) if letters else ""
    rest = text[len(prefix) :]
    allowed = "A-Z0-9" + "".join(re.escape(c) for c in dict.fromkeys(rest) if c in "-_./")
    if not rest:
        return f"(?<![A-Z0-9])(?P<sn>{re.escape(prefix)})(?![A-Z0-9])"
    if prefix:
        return f"(?<![A-Z0-9])(?P<sn>{re.escape(prefix)}[{allowed}]+)"
    return f"(?<![A-Z0-9])(?P<sn>[{allowed}]{{{len(text)}}})(?![A-Z0-9])"
