"""Light / dark theming: the Fusion style, a ``QPalette`` from the shared colour tokens, and a small stylesheet.

The stylesheet only names the app's own widgets (cards, chips, the primary button, table headers). Everything else keeps
Qt's native painting, because a stylesheet on a widget class replaces that class's native drawing and costs speed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from ..palette import DARK, LIGHT, Palette

# A glyph that the interface font lacks (a check mark, a warning sign, a sun) sends Windows looking through every font for it, once,
# and that search takes about half a second and some 50 MB. Widgets that show such glyphs name the font that has them, and the
# search never happens. Elsewhere only glyphs the interface font has are used: ▼ ► ‼ ● and the arrows, not ▾ ▸ ⚠ ◆ ✔.
SYMBOL_FONT = "Segoe UI Symbol"


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
QFrame#card {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 10px; }}
QLabel {{ background: transparent; }}
QLabel#appTitle {{ font-size: 18pt; font-weight: 600; }}
QLabel#cardTitle {{ font-size: 10pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="title"] {{ font-size: 14pt; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="ok"] {{ color: {p.ok}; }}
QLabel[role="warn"] {{ color: {p.warn}; }}
QLabel[role="bad"] {{ color: {p.danger}; }}
QFrame#banner {{ background: {p.banner_bg}; border: 1px solid {p.line}; border-radius: 8px; }}
QFrame#banner QLabel {{ color: {p.banner_fg}; }}
QLabel[role="metric"] {{ font-size: 16pt; font-weight: 600; }}
QLabel[chip] {{ border: 1px solid transparent; border-radius: 10px; padding: 2px 10px; font-family: "{SYMBOL_FONT}"; }}
QPushButton[glyphs="true"] {{ font-family: "{SYMBOL_FONT}"; }}
QLabel[chip="ok"] {{ background: {p.ok_bg}; border-color: {p.ok_line}; color: {p.ok}; }}
QLabel[chip="warn"] {{ background: {p.warn_bg}; border-color: {p.warn_line}; color: {p.warn}; }}
QLabel[chip="bad"] {{ background: {p.bad_bg}; border-color: {p.bad_line}; color: {p.danger}; }}
QLabel[chip="info"] {{ background: {p.banner_bg}; border-color: {p.line}; color: {p.banner_fg}; }}
QPushButton, QToolButton {{ background: {p.surface}; color: {p.fg}; border: 1px solid {p.line};
    border-radius: 6px; padding: 5px 9px; }}
QPushButton:hover, QToolButton:hover {{ background: {p.soft}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p.muted}; }}
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
QFrame#startHero {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 16px; }}
QFrame#startCard {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 13px; }}
QFrame#startCard:hover {{ border-color: {p.accent}; }}
QFrame#choiceCard {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 10px; }}
QFrame#choiceCard:hover, QFrame#choiceCard:focus {{ border-color: {p.accent}; }}
QFrame#choiceCard[selected="true"] {{ background: {p.banner_bg}; border-color: {p.accent}; }}
QFrame#choiceCard:disabled {{ background: {p.soft}; }}
QLabel[role="kicker"] {{ color: {p.accent}; font-size: 8pt; font-weight: 700; }}
QLabel[role="intro"] {{ color: {p.muted}; font-size: 10pt; }}
QLabel[role="pill"] {{ background: {p.soft}; border: 1px solid {p.line}; border-radius: 12px; padding: 4px 11px; color: {p.muted};
    font-size: 8pt; }}
QLabel[role="choice"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[role="startTitle"] {{ font-size: 15pt; font-weight: 700; }}
QLabel[role="cardBody"] {{ color: {p.muted}; font-size: 9pt; }}
QLabel[role="stepNote"] {{ background: {p.soft}; border-radius: 5px; padding: 6px 9px; color: {p.muted}; font-size: 8pt; }}
QLabel[role="cta"] {{ color: {p.accent}; font-size: 9pt; font-weight: 700; }}
QLabel[badge] {{ background: {p.soft}; color: {p.muted}; border-radius: 9px; padding: 3px 9px; font-size: 8pt; font-weight: 700; }}
QLabel[badge="ok"] {{ background: {p.ok_bg}; color: {p.ok}; }}
QLabel[badge="warn"] {{ background: {p.warn_bg}; color: {p.warn}; }}
QLabel[badge="bad"] {{ background: {p.bad_bg}; color: {p.danger}; }}
QLabel[role="pageTitle"] {{ font-size: 14pt; font-weight: 700; }}
QLabel[role="micro"] {{ color: {p.muted}; font-size: 8pt; }}
QLabel[role="subhead"] {{ font-size: 9pt; font-weight: 700; }}
QLabel[role="note"] {{ background: {p.soft}; color: {p.muted}; border-radius: 6px; padding: 7px 10px; }}
QFrame#metricStrip {{ background: {p.soft}; border-radius: 7px; }}
QFrame#metricStrip QLabel[role="metric"] {{ font-size: 13pt; }}
QFrame#countTile {{ border-radius: 6px; }}
QFrame#countTile[kind="ok"] {{ background: {p.ok_bg}; }}
QFrame#countTile[kind="warn"] {{ background: {p.warn_bg}; }}
QFrame#countTile[kind="bad"] {{ background: {p.bad_bg}; }}
QFrame#countTile[kind="ok"] QLabel {{ color: {p.ok}; }}
QFrame#countTile[kind="warn"] QLabel {{ color: {p.warn}; }}
QFrame#countTile[kind="bad"] QLabel {{ color: {p.danger}; }}
QFrame#countTile QLabel[role="count"] {{ font-weight: 700; }}
QFrame#actionBox {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 8px; }}
QFrame#actionBox[primary="true"] {{ background: {p.banner_bg}; border-color: {p.accent}; }}
QLabel[role="actionTitle"] {{ font-size: 10pt; font-weight: 700; }}
QTabWidget#reviewTabs::pane {{ border: none; top: 2px; }}
QTabWidget#reviewTabs QTabBar::tab {{ background: {p.soft}; color: {p.muted}; border: none; border-radius: 6px; padding: 5px 12px;
    margin-right: 4px; font-weight: 600; }}
QTabWidget#reviewTabs QTabBar::tab:selected {{ background: {p.banner_bg}; color: {p.accent}; }}
QTabWidget#reviewTabs QTabBar::tab:hover:!selected {{ color: {p.fg}; }}
QTabWidget#workspaceTabs::pane {{ border: none; }}
QTabWidget#workspaceTabs > QTabBar::tab {{ background: {p.surface}; color: {p.muted}; border: 1px solid {p.line};
    border-radius: 6px; padding: 6px 13px; margin-right: 5px; font-weight: 600; }}
QTabWidget#workspaceTabs > QTabBar::tab:selected {{ background: {p.banner_bg}; border-color: {p.accent}; color: {p.accent}; }}
QTabWidget#workspaceTabs > QTabBar::tab:disabled {{ color: {p.muted}; background: {p.soft}; }}
QRadioButton#methodChoice {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: 7px;
    padding: 12px 9px; font-weight: 600; }}
QRadioButton#methodChoice:checked {{ background: {p.banner_bg}; border-color: {p.accent}; color: {p.accent}; }}
QRadioButton#methodChoice:hover {{ border-color: {p.accent}; }}
QWidget#validationWorkspace QLineEdit, QWidget#validationWorkspace QComboBox {{ border: 1px solid {p.line};
    border-radius: 5px; background: {p.surface}; color: {p.fg}; padding: 5px 7px; }}
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
