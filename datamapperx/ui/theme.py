"""Light / dark theming on top of the Sun Valley (Windows 11 style) ttk theme."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import ttk

import sv_ttk

from ..palette import DARK as _DARK
from ..palette import LIGHT as _LIGHT
from ..palette import Palette


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



def work_area(root: tk.Misc, anchor: tuple[int, int] | None = None) -> tuple[int, int, int, int]:
    """Return the nearest monitor's usable bounds, excluding taskbars and docked toolbars."""
    fallback = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    if sys.platform != "win32":
        return fallback
    try:
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        from_point = user32.MonitorFromPoint
        from_point.argtypes = [wintypes.POINT, wintypes.DWORD]
        from_point.restype = wintypes.HANDLE
        from_window = user32.MonitorFromWindow
        from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
        from_window.restype = wintypes.HANDLE
        get_info = user32.GetMonitorInfoW
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        get_info.restype = wintypes.BOOL

        # Selecting the nearest monitor also recovers positions saved before a monitor was disconnected.
        nearest = 2  # MONITOR_DEFAULTTONEAREST
        monitor = from_point(wintypes.POINT(*anchor), nearest) if anchor is not None else from_window(root.winfo_id(), nearest)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if monitor and get_info(monitor, ctypes.byref(info)):
            area = info.rcWork
            if area.right > area.left and area.bottom > area.top:
                return area.left, area.top, area.right, area.bottom
    except (AttributeError, OSError, tk.TclError, TypeError, ValueError):
        pass
    return fallback


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
    """App-specific surfaces and type hierarchy, keeping native controls and focus states."""
    style = ttk.Style(root)
    style.configure(".", font=("Segoe UI", 10))
    style.configure("TFrame", background=p.bg)
    style.configure("TLabel", background=p.bg, foreground=p.fg)
    style.configure("TLabelframe", background=p.bg)
    style.configure("TLabelframe.Label", background=p.bg, foreground=p.fg)
    style.configure("TPanedwindow", background=p.bg)
    style.configure("TSeparator", background=p.line)

    style.configure("Surface.TFrame", background=p.surface)
    style.configure("Surface.TLabel", background=p.surface, foreground=p.fg)
    style.configure("SurfaceMuted.TLabel", background=p.surface, foreground=p.muted)
    style.configure("SurfaceHint.TLabel", background=p.surface, foreground=p.muted, font=("Segoe UI", 9))
    style.configure("Surface.TLabelframe", background=p.surface, borderwidth=0, relief="flat")
    style.configure("Surface.TLabelframe.Label", background=p.surface, foreground=p.fg, font=("Segoe UI Semibold", 11))
    style.configure("Surface.TSeparator", background=p.line)
    style.configure("Surface.TCheckbutton", background=p.surface, foreground=p.fg)
    style.configure("Surface.Switch.TCheckbutton", background=p.surface, foreground=p.fg)
    style.configure("Surface.TRadiobutton", background=p.surface, foreground=p.fg)

    style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
    style.configure("Brand.TLabel", font=("Segoe UI Semibold", 20), foreground=p.fg)
    style.configure("Subtitle.TLabel", foreground=p.muted, font=("Segoe UI", 10))
    style.configure("Section.TLabel", background=p.surface, foreground=p.fg, font=("Segoe UI Semibold", 11))
    style.configure("Step.TLabel", background=p.surface, foreground=p.accent, font=("Segoe UI Semibold", 10))
    style.configure("Muted.TLabel", foreground=p.muted)
    style.configure("Hint.TLabel", foreground=p.muted, font=("Segoe UI", 9))
    style.configure("Metric.TLabel", background=p.surface, foreground=p.fg, font=("Segoe UI Semibold", 18))
    style.configure("MetricCaption.TLabel", background=p.surface, foreground=p.muted, font=("Segoe UI", 9))
    style.configure("Stat.TLabel", font=("Segoe UI Semibold", 16))
    style.configure("StatCaption.TLabel", foreground=p.muted, font=("Segoe UI", 9))
    style.configure("Ok.TLabel", foreground=p.ok)
    style.configure("Warn.TLabel", foreground=p.warn)
    style.configure("Bad.TLabel", foreground=p.danger)
    for name, color in (("Ok", p.ok), ("Warn", p.warn), ("Bad", p.danger)):
        style.configure(f"Surface{name}.TLabel", background=p.surface, foreground=color)

    style.configure("Banner.TFrame", background=p.banner_bg)
    style.configure("Banner.TLabel", background=p.banner_bg, foreground=p.banner_fg)

    # One button look for the whole app: the theme's own button, its filled "Accent" version for the main action of
    # a screen, and a square "Icon" version (the same button, just narrower) for arrows and the pager.
    style.configure("Icon.TButton", padding=(4, 4))
    style.configure("Pick.TLabel", background=p.pick, foreground=p.fg, padding=(10, 6))

    style.configure("Treeview", rowheight=28, background=p.surface, fieldbackground=p.surface, foreground=p.fg)
    style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), padding=(10, 8))
    style.map("Treeview", background=[("selected", p.accent)], foreground=[("selected", p.on_accent)])

    # Placeholders blend into their actual control, including when a card uses a different surface.
    style.configure("EntryHint.TLabel", background=style.lookup("TEntry", "fieldbackground") or p.surface, foreground=p.muted)
