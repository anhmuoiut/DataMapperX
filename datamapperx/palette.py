"""The colours of the light and dark themes, without any toolkit.

The window, its stylesheet and the charts take their colours from here, so they cannot drift apart.
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
    mode="light", bg="#f3f6fb", surface="#ffffff", fg="#17293f", muted="#60758e", line="#dae4ef", accent="#0864b5",
    ok="#147d5e", warn="#aa7217", danger="#b83746", banner_bg="#eaf3ff", banner_fg="#0864b5",
    on_accent="#ffffff", soft="#f7f9fc", pick="#eaf3ff",
    ok_bg="#e9f7ef", ok_line="#a9d9bd", warn_bg="#fff3d9", warn_line="#efd08a", bad_bg="#fff0f2", bad_line="#f0b4b4",
)
DARK = Palette(
    mode="dark", bg="#0e1928", surface="#18263a", fg="#e9f1fa", muted="#a2b5ca", line="#344760", accent="#3898ee",
    ok="#78dbab", warn="#ffca78", danger="#ff8995", banner_bg="#1e3a58", banner_fg="#cdeaff",
    on_accent="#ffffff", soft="#20314a", pick="#1e3a58",
    ok_bg="#183f35", ok_line="#3c7058", warn_bg="#443521", warn_line="#7a6224", bad_bg="#472a31", bad_line="#85383d",
)
