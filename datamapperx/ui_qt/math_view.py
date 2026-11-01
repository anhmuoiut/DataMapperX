"""A formula painted on a widget: fractions, subscripts, roots and Greek letters, from ``mathtext`` source."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..mathtext import layout, parse
from ..palette import Palette

MATH_SIZE = 15  # pixels


class MathView(QWidget):
    def __init__(self, source: str, palette: Palette, *, size: float = MATH_SIZE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source, self._ink = source, QColor(palette.fg)
        self._fonts: dict[tuple[int, bool], QFont] = {}
        self._box = layout(parse(source), size, self._measure)
        pad = 2
        self._pad = pad
        self.setFixedSize(math.ceil(self._box.w) + 2 * pad + 1, math.ceil(self._box.asc + self._box.desc) + 2 * pad + 1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _font(self, size: float, italic: bool) -> QFont:
        key = (round(size), italic)
        if key not in self._fonts:
            font = QFont(self.font())
            font.setPixelSize(max(1, key[0]))
            font.setItalic(italic)
            self._fonts[key] = font
        return self._fonts[key]

    def _measure(self, text: str, size: float, italic: bool) -> tuple[float, float, float]:
        metrics = QFontMetricsF(self._font(size, italic))
        return metrics.horizontalAdvance(text), metrics.ascent(), metrics.descent()

    def set_palette(self, palette: Palette) -> None:
        self._ink = QColor(palette.fg)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, base = self._pad, self._pad + self._box.asc
        for op in self._box.ops:
            if op[0] == "t":
                _, x, y, text, text_size, italic = op
                painter.setFont(self._font(text_size, italic))
                painter.setPen(self._ink)
                painter.drawText(QPointF(left + x, base + y), text)
            else:
                _, points, width, _smooth = op
                pen = QPen(self._ink, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawPolyline([QPointF(left + x, base + y) for x, y in points])
        painter.end()
