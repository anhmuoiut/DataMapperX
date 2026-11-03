"""The Dashboard DataMapperX opens on: a line on what the program is for, and the two ways to start. Nothing else lives here.

The page only announces a choice (``map_requested`` / ``rawdata_requested``); what a choice does is the main window's business,
so the screens behind it are the ones that already exist.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget

from ..palette import Palette
from .dialogs import label
from .widgets import ScrollTab

TITLE = "From Raw Test Data to Reliable Insights.."
INTRO = "DataMapperX simplifies test-log mapping, statistical analysis, and report generation in one streamlined workspace."
MAP_CARD = ("Map Test Logfiles", "Extract, organize, and review tester measurements before exporting to Excel.", "Start mapping")
RAW_CARD = ("Analyze Excel Data", "Perform Cpk, Variable Gage R&R, and Attribute Agreement analysis with charts and reports.", "Start analysis")

MAX_WIDTH = 1000  # the column of the page
TITLE_PIXELS = (23, 34)  # the heading follows the width of the page between these sizes
INTRO_LINE_HEIGHT, BODY_LINE_HEIGHT = 135, 128  # percent of the font's line height
# Spacing in pixels, and a tighter one for a page too short to show it whole (a 768-pixel laptop screen), so that both cards and
# their call to action stay in view. A page that is still too short scrolls.
ROOMY = {"top": 28, "bottom": 18, "hero": (36, 30, 36, 30), "heading": 10, "hero_after": 22,
         "card": (25, 25, 25, 22), "icon": 14, "title": 6, "action": 18, "card_height": 190}
COMPACT = {"top": 10, "bottom": 6, "hero": (28, 18, 28, 18), "heading": 6, "hero_after": 12,
           "card": (22, 14, 22, 12), "icon": 8, "title": 4, "action": 10, "card_height": 0}
COMPACT_BELOW = 720  # the height of the page, in pixels, under which the tighter spacing is used


def _paragraph(text: str, line_height: int) -> str:
    return f'<p style="margin:0; line-height:{line_height}%;">{escape(text)}</p>'


def _gap(layout: QVBoxLayout, store: dict[str, QSpacerItem], name: str) -> None:
    """A vertical space whose height depends on the density in use (see ``_apply_density``), kept under ``name``."""
    item = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    layout.addItem(item)
    store[name] = item


class _Measure(QLabel):
    """A wrapping label with a maximum width. A box layout asks a label how tall it is for the width of the whole column, not for
    the narrower one the label is given, and the last lines of the text are cut off; this answers for the width it will have."""

    def __init__(self, text: str, role: str, max_width: int, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", role)
        self.setWordWrap(True)
        self.setMaximumWidth(max_width)

    def heightForWidth(self, width: int) -> int:
        return super().heightForWidth(min(width, self.maximumWidth()))


class _Hero(QFrame):
    """The introduction: a card with a pale ring in its top right corner."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startHero")
        self.palette_tokens = palette

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the surface and border come from the stylesheet
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inside = QPainterPath()
        inside.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 15, 15)
        painter.setClipPath(inside)  # the ring is cut off by the corner of the card
        ring = QColor(self.palette_tokens.banner_bg)
        ring.setAlphaF(0.65)
        painter.setPen(QPen(ring, 45))
        painter.drawEllipse(QPointF(self.width() - 55, 45), 137.5, 137.5)  # 160 px across the outside, the line 45 px wide
        painter.end()


class _IconTile(QWidget):
    """The 48-pixel tile of a card: a square with lines across it (mapping) or down it (an existing RawData file)."""

    def __init__(self, kind: str, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.palette_tokens = palette
        self.setFixedSize(48, 48)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.palette_tokens.banner_bg))
        painter.drawRoundedRect(QRectF(self.rect()), 11, 11)
        ink = QColor(self.palette_tokens.accent)
        painter.setPen(QPen(ink, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        box = QRectF(13, 13, 22, 22)
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QPen(ink, 1.6))
        for step in (1, 2, 3):
            if self.kind == "map":
                y = box.top() + box.height() * step / 4
                painter.drawLine(QPointF(box.left() + 3, y), QPointF(box.right() - 3, y))
            else:
                x = box.left() + box.width() * step / 4
                painter.drawLine(QPointF(x, box.top() + 3), QPointF(x, box.bottom() - 3))
        painter.end()


class StartCard(QFrame):
    """A whole card is the button: a click, or Enter / Space while it has the keyboard focus."""

    clicked = Signal()

    def __init__(self, kind: str, content: tuple[str, str, str], palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title, body, action = content
        self.setObjectName("startCard")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # the keyboard reaches it; a click does not leave a focus ring behind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(body)
        self.palette_tokens = palette
        self._stack = layout = QVBoxLayout(self)
        layout.setSpacing(0)
        self._gaps: dict[str, QSpacerItem] = {}
        self.icon = _IconTile(kind, palette)
        self.title = label(title, "startTitle")
        self.body = label(_paragraph(body, BODY_LINE_HEIGHT), "cardBody", wrap=True)
        self.action = label(action, "cta")
        arrow = label("→", "cta")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignLeft)
        _gap(layout, self._gaps, "icon")
        layout.addWidget(self.title)
        _gap(layout, self._gaps, "title")
        layout.addWidget(self.body)
        _gap(layout, self._gaps, "action")
        layout.addStretch(1)
        footer = QHBoxLayout()
        footer.addWidget(self.action)
        footer.addStretch(1)
        footer.addWidget(arrow)
        layout.addLayout(footer)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # a click on any part is a click on the card
        self.set_density(ROOMY)

    def set_density(self, density: dict) -> None:
        self._stack.setContentsMargins(*density["card"])
        for name, item in self._gaps.items():
            item.changeSize(0, density[name], QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._stack.invalidate()
        self.setMinimumHeight(density["card_height"])

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.icon.palette_tokens = palette
        self.icon.update()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.hasFocus():  # a ring inside the border for the keyboard (the border itself turns blue under the mouse)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(self.palette_tokens.accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 11, 11)
            painter.end()


class DashboardPage(ScrollTab):
    """The page. It scrolls when the window is too short for it (a small screen, large text) and is otherwise as the design shows."""

    map_requested = Signal()
    rawdata_requested = Signal()

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_tokens = palette
        row = QHBoxLayout(self.content)
        row.setContentsMargins(0, 0, 0, 0)
        column = QWidget()
        column.setMaximumWidth(MAX_WIDTH)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addStretch(1)
        row.addWidget(column, 1000)  # nearly all of the width, up to the column's own limit; the rest goes to the sides
        row.addStretch(1)
        self._gaps: dict[str, QSpacerItem] = {}
        self._compact: bool | None = None
        self._body = body = QVBoxLayout(column)
        body.setSpacing(0)

        self.hero = _Hero(palette)
        self._hero_layout = hero = QVBoxLayout(self.hero)
        hero.setSpacing(0)
        self.heading = _Measure(TITLE, "", 700)
        self.intro = _Measure(_paragraph(INTRO, INTRO_LINE_HEIGHT), "intro", 720)
        hero.addWidget(self.heading)
        _gap(hero, self._gaps, "heading")
        hero.addWidget(self.intro)
        body.addWidget(self.hero)

        _gap(body, self._gaps, "hero_after")
        cards = QHBoxLayout()
        cards.setSpacing(16)
        self.map_card = StartCard("map", MAP_CARD, palette)
        self.raw_card = StartCard("raw", RAW_CARD, palette)
        self.map_card.clicked.connect(self.map_requested)
        self.raw_card.clicked.connect(self.rawdata_requested)
        cards.addWidget(self.map_card, 1)
        cards.addWidget(self.raw_card, 1)
        body.addLayout(cards)
        body.insertStretch(0, 1)  # the two cards sit a little above the middle of the page, not against its top edge
        body.addStretch(2)
        self._apply_density(False)
        self._fit_heading()

    def _apply_density(self, compact: bool) -> None:
        density = COMPACT if compact else ROOMY
        self._compact = compact
        self._body.setContentsMargins(0, density["top"], 0, density["bottom"])
        self._hero_layout.setContentsMargins(*density["hero"])
        for name, item in self._gaps.items():
            item.changeSize(0, density[name], QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        for card in (self.map_card, self.raw_card):
            card.set_density(density)
        self._body.invalidate()
        self._hero_layout.invalidate()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.hero.palette_tokens = palette
        self.hero.update()
        self.map_card.set_palette(palette)
        self.raw_card.set_palette(palette)

    def _fit_heading(self) -> None:
        """As in the design, the heading grows with the page between 23 and 34 pixels."""
        low, high = TITLE_PIXELS
        font = QFont(self.heading.font())
        font.setPixelSize(round(max(low, min(high, self.width() * 0.032))))
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.8)
        if font != self.heading.font():
            self.heading.setFont(font)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_heading()
        if (self.height() < COMPACT_BELOW) != self._compact:
            self._apply_density(not self._compact)
