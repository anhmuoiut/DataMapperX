"""Light / dark theming on top of the Sun Valley (Windows 11 style) ttk theme."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

import sv_ttk


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


_LIGHT = Palette(
    mode="light", bg="#fafafa", surface="#ffffff", fg="#1c1c1c", muted="#5f5f5f", line="#d0d0d0", accent="#005fb8",
    ok="#0f7b0f", warn="#9d5d00", danger="#c42b1c", banner_bg="#e5f1fb", banner_fg="#003e73",
)
_DARK = Palette(
    mode="dark", bg="#1c1c1c", surface="#2b2b2b", fg="#fafafa", muted="#a6a6a6", line="#454545", accent="#60cdff",
    ok="#6ccb5f", warn="#fce100", danger="#ff99a4", banner_bg="#0e2f44", banner_fg="#cfe9ff",
)


def system_prefers_dark() -> bool:
    """Read the Windows 'app mode' setting. Anything unexpected means light."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def resolve_mode(setting: str) -> str:
    if setting in ("light", "dark"):
        return setting
    return "dark" if system_prefers_dark() else "light"


def set_dark_titlebar(window: tk.Misc, dark: bool) -> None:
    """Ask Windows 10/11 to draw the title bar in the matching colour. Cosmetic; failures are ignored."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on early Windows 10 builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def apply_theme(root: tk.Tk, setting: str) -> Palette:
    palette = _DARK if resolve_mode(setting) == "dark" else _LIGHT
    sv_ttk.set_theme(palette.mode, root=root)
    configure_styles(root, palette)
    root.configure(bg=palette.bg)
    set_dark_titlebar(root, palette.mode == "dark")
    return palette


def configure_styles(root: tk.Tk, p: Palette) -> None:
    """App-specific styles layered over the base theme."""
    style = ttk.Style(root)
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
    style.configure("Muted.TLabel", foreground=p.muted)
    style.configure("Hint.TLabel", foreground=p.muted, font=("Segoe UI", 9))
    style.configure("Stat.TLabel", font=("Segoe UI Semibold", 16))
    style.configure("StatCaption.TLabel", foreground=p.muted, font=("Segoe UI", 8))
    style.configure("Ok.TLabel", foreground=p.ok)
    style.configure("Warn.TLabel", foreground=p.warn)
    style.configure("Bad.TLabel", foreground=p.danger)
    style.configure("Banner.TFrame", background=p.banner_bg)
    style.configure("Banner.TLabel", background=p.banner_bg, foreground=p.banner_fg)
    style.configure("Treeview", rowheight=26)
    # Hints drawn on top of an entry / list must use that widget's own background to look like part of it.
    style.configure("EntryHint.TLabel", background=style.lookup("TEntry", "fieldbackground") or p.surface, foreground=p.muted)
    style.configure("ListHint.TLabel", background=style.lookup("Treeview", "background") or p.surface, foreground=p.muted)
