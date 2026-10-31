"""Light / dark theming: the Fusion style, a ``QPalette`` from the shared colour tokens, and a small stylesheet.

The stylesheet only names the app's own widgets (cards, chips, the primary button, table headers). Everything else keeps
Qt's native painting, because a stylesheet on a widget class replaces that class's native drawing and costs speed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from ..palette import DARK, LIGHT, Palette


def resolve_mode(setting: str) -> str:
    """``"light"`` or ``"dark"``; ``"system"`` follows the operating system (Qt 6.5+ reports it on Windows and macOS)."""
    if setting in ("light", "dark"):
        return setting
    return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"


def make_palette(p: Palette) -> QPalette:
    colour = QColor
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.fg,
        QPalette.ColorRole.Base: p.surface, QPalette.ColorRole.AlternateBase: p.soft,
        QPalette.ColorRole.Text: p.fg, QPalette.ColorRole.Button: p.soft, QPalette.ColorRole.ButtonText: p.fg,
        QPalette.ColorRole.Highlight: p.accent, QPalette.ColorRole.HighlightedText: p.on_accent,
        QPalette.ColorRole.PlaceholderText: p.muted, QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.fg, QPalette.ColorRole.Link: p.accent, QPalette.ColorRole.BrightText: p.danger,
    }
    for role, value in roles.items():
        palette.setColor(role, colour(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, colour(p.muted))
    return palette


def stylesheet(p: Palette) -> str:
    return f"""
QFrame#card {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 8px; }}
QLabel {{ background: transparent; }}
QLabel#appTitle {{ font-size: 18pt; font-weight: 600; }}
QLabel#cardTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="metric"] {{ font-size: 16pt; font-weight: 600; }}
QLabel[chip] {{ border: 1px solid transparent; border-radius: 10px; padding: 2px 10px; }}
QLabel[chip="ok"] {{ background: {p.ok_bg}; border-color: {p.ok_line}; color: {p.ok}; }}
QLabel[chip="warn"] {{ background: {p.warn_bg}; border-color: {p.warn_line}; color: {p.warn}; }}
QLabel[chip="bad"] {{ background: {p.bad_bg}; border-color: {p.bad_line}; color: {p.danger}; }}
QLabel[chip="info"] {{ background: {p.banner_bg}; border-color: {p.line}; color: {p.banner_fg}; }}
QPushButton[primary="true"] {{ background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent};
    border-radius: 6px; padding: 6px 16px; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ border-color: {p.fg}; }}
QPushButton[primary="true"]:disabled {{ background: {p.line}; border-color: {p.line}; color: {p.muted}; }}
QPushButton[step] {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    padding: 6px 14px; color: {p.muted}; }}
QPushButton[step="current"] {{ color: {p.accent}; border-bottom-color: {p.accent}; font-weight: 600; }}
QPushButton[step="done"] {{ color: {p.fg}; }}
QPushButton[step]:disabled {{ color: {p.line}; }}
QTableView {{ background: {p.surface}; border: 1px solid {p.line}; gridline-color: {p.line};
    selection-background-color: {p.pick}; selection-color: {p.fg}; outline: 0; }}
QHeaderView::section {{ background: {p.soft}; color: {p.muted}; padding: 6px 10px; border: none;
    border-bottom: 1px solid {p.line}; font-weight: 600; }}
QProgressBar {{ background: {p.line}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
QStatusBar {{ color: {p.muted}; }}
QSplitter::handle {{ background: transparent; }}
"""


def apply_theme(app: QApplication, setting: str) -> Palette:
    """Style the whole application and return the colour tokens in use."""
    mode = resolve_mode(setting)
    palette = DARK if mode == "dark" else LIGHT
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8+: also makes the native title bar follow the choice
        hints.setColorScheme(Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    app.setPalette(make_palette(palette))
    app.setStyleSheet(stylesheet(palette))
    return palette
