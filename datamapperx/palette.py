"""The colours of the light and dark themes, without any toolkit.

Both the tkinter window and the Qt prototype take their colours from here, so they cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Palette:
    mode: str
    bg: str
    surface: str
    fg: str
    muted: str
    line: str
    accent: str
    ok: str
    warn: str
    danger: str
    banner_bg: str
    banner_fg: str
    on_accent: str  # text on a filled accent (the current step, a selected row)
    soft: str  # column-heading strips and other quiet fills inside a card
    pick: str  # the row you clicked
    ok_bg: str
    ok_line: str
    warn_bg: str
    warn_line: str
    bad_bg: str
    bad_line: str


LIGHT = Palette(
    mode="light", bg="#f3f6fa", surface="#ffffff", fg="#182536", muted="#526174", line="#dce3ec", accent="#005fb8",
    ok="#167347", warn="#915900", danger="#ba2836", banner_bg="#e8f2fd", banner_fg="#164b7a",
    on_accent="#ffffff", soft="#f1f5f9", pick="#dcebfb",
    ok_bg="#e7f6ed", ok_line="#a9d9bd", warn_bg="#fff4dc", warn_line="#efd08a", bad_bg="#fdecec", bad_line="#f0b4b4",
)
DARK = Palette(
    mode="dark", bg="#151b24", surface="#1e2734", fg="#edf3fb", muted="#b0bfd0", line="#354459", accent="#73cbff",
    ok="#78d4a0", warn="#f0c475", danger="#ff9ba7", banner_bg="#203a52", banner_fg="#cdeaff",
    on_accent="#122739", soft="#263244", pick="#27435f",
    ok_bg="#173a2d", ok_line="#3c7058", warn_bg="#3b2f12", warn_line="#7a6224", bad_bg="#40191c", bad_line="#85383d",
)
