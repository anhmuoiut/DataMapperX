"""A circuit board for the Dashboard to stand on: dark navy, thin low-contrast traces that run horizontally, vertically and at 45
degrees, and small cyan pulses that travel along them.

The traces never move. They are worked out once for a size (``build_circuit``), drawn once into a pixmap and kept; a frame only copies
back the few small rectangles the pulses have moved through and draws the pulses on them. Nothing runs while the widget is hidden or
while animation is off. The middle of the widget, where the page puts its content, is left empty: every trace starts at the edge of
that quiet area and leaves it, so nothing is drawn behind the content. Bands at the top and bottom (the header and the status line)
are left empty too; the traces there end in pads before they reach them.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QWidget

BACKGROUND = "#0B1220"
TRACE = QColor(86, 160, 214, 70)
PAD = QColor(86, 160, 214, 115)
PULSE = QColor(77, 230, 255)
PULSE_CORE = QColor(190, 248, 255)

FRAME_MS = 40  # 25 frames a second
MAX_STEP = 0.25  # seconds; a longer stall (a window being dragged) moves the pulses by this much, not by the whole stall
QUIET_WIDTH = 1040  # the quiet area is centred and this wide (the Dashboard's column is 1000); a narrower widget is quiet right across
QUIET_HEIGHT_SHARE = 0.55  # of the height of the widget
PITCH = 9  # between the lines of a bus
LANE = 150  # the width of the strip each bus keeps to, so that no two traces cross
MIN_ROOM = 60  # a side with less room than this, between the quiet area and the edge of the widget, gets no traces
OVERSHOOT = 8  # a trace that runs off the widget runs this far past its edge
START_GAP = 4  # a trace starts this far from the quiet area, so that the ring of its pad (radius 2.6) is outside it

PULSES = 8  # at most this many at a time
TAIL = 30.0  # pixels
SPEED = (70.0, 130.0)  # pixels a second
PAUSE = (0.5, 3.0)  # seconds a pulse waits before it starts again

Point = tuple[float, float]


class Route:
    """One trace, from the quiet area outwards: its corners, and how far along the trace each one is."""

    def __init__(self, points: list[Point], ends_in_pad: bool) -> None:
        self.points = points
        self.ends_in_pad = ends_in_pad
        self.lengths = [0.0]
        for (x0, y0), (x1, y1) in pairwise(points):
            self.lengths.append(self.lengths[-1] + math.hypot(x1 - x0, y1 - y0))

    @property
    def length(self) -> float:
        return self.lengths[-1]

    def at(self, distance: float) -> Point:
        """The point ``distance`` along the trace, held to its two ends."""
        distance = min(max(distance, 0.0), self.length)
        i = min(bisect.bisect_right(self.lengths, distance), len(self.points) - 1)
        (x0, y0), (x1, y1) = self.points[i - 1], self.points[i]
        span = self.lengths[i] - self.lengths[i - 1]
        t = (distance - self.lengths[i - 1]) / span if span else 1.0
        return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t


def quiet_area(width: int, height: int, bands: tuple[int, int] = (0, 0)) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the area that is kept empty: in the middle of what is left between the two ``bands`` (their
    heights) at the top and the bottom."""
    wide = min(width, QUIET_WIDTH)
    free = max(height - sum(bands), 0)
    high = round(free * QUIET_HEIGHT_SHARE)
    left, top = (width - wide) // 2, bands[0] + (free - high) // 2
    return left, top, left + wide, top + high


def _parallel(points: list[Point], delta: float) -> list[Point]:
    """The line ``delta`` to the left of a polyline, its corners mitred. Every direction in a trace is a multiple of 45 degrees, so
    the line is one too."""
    normals = []
    for (x0, y0), (x1, y1) in pairwise(points):
        length = math.hypot(x1 - x0, y1 - y0)
        normals.append((-(y1 - y0) / length, (x1 - x0) / length))
    line = []
    for i, (x, y) in enumerate(points):
        a, b = normals[max(i - 1, 0)], normals[min(i, len(normals) - 1)]
        scale = delta / (1 + a[0] * b[0] + a[1] * b[1])
        line.append((x + (a[0] + b[0]) * scale, y + (a[1] + b[1]) * scale))
    return line


def _centre_line(rng: random.Random, room: int, low: float, high: float, ends_in_pad: bool) -> tuple[list[Point], bool]:
    """The middle line of a bus in its own frame: x runs outwards from the quiet area, y across the strip (between ``low`` and
    ``high``). It goes straight out, shifts sideways along 45-degree lines up to twice, and either leaves the widget or ends in a pad
    (which it must, when ``ends_in_pad``: there is a band where it has to stop)."""
    y = math.floor(rng.uniform(low, high)) + 0.5  # on a half pixel, so that a straight line is one sharp pixel wide
    x = float(START_GAP)
    points = [(x, y)]
    pad = rng.random() < 0.35 or ends_in_pad
    reach = room - 30 if pad else 0.9 * room  # how far out the last shift may end: a pad needs a straight run and its own room
    for _ in range(rng.choice((0, 1, 1, 2))):
        x += rng.uniform(0.12, 0.3) * room
        shift = round(rng.uniform(low, high) - y)
        shift = math.copysign(min(abs(shift), max(0.0, reach - x)), shift)
        if abs(shift) < 16:
            break
        points += [(x, y), (x + abs(shift), y + shift)]
        x += abs(shift)
        y += shift
    points.append((min(room - 5, max(x + 24, rng.uniform(0.8, 0.97) * room)) if pad else room + OVERSHOOT, y))
    return points, pad


def build_circuit(width: int, height: int, bands: tuple[int, int] = (0, 0), seed: int = 7) -> list[Route]:
    """The traces for a widget of this size, the same ones for the same size, bands and seed. Each of the four sides of the quiet
    area is cut into strips, and a bus (two to five parallel traces) goes out from the middle of most of them, keeping to its strip."""
    left, top, right, bottom = quiet_area(width, height, bands)
    rng = random.Random(seed)
    sides = (  # room, span along the side, must it end in a pad, and how a position in the bus's frame (out, across) is placed
        (top - bands[0], (left, right), bands[0] > 0, lambda out, across: (across, top - out)),
        (height - bands[1] - bottom, (left, right), bands[1] > 0, lambda out, across: (across, bottom + out)),
        (left, (top, bottom), False, lambda out, across: (left - out, across)),
        (width - right, (top, bottom), False, lambda out, across: (right + out, across)),
    )
    routes = []
    for room, (start, end), must_end, place in sides:
        if room < MIN_ROOM:
            continue
        strips = max(1, round((end - start) / LANE))
        size = (end - start) / strips
        for strip in range(strips):
            if rng.random() < 0.15:  # a gap now and then
                continue
            lines = rng.randint(2, 5)
            while lines > 2 and (lines - 1) * PITCH + 28 > size:
                lines -= 1
            half = (lines - 1) * PITCH / 2
            centre, pad = _centre_line(rng, room, start + strip * size + half + 14, start + (strip + 1) * size - half - 14, must_end)
            for i in range(lines):
                line = _parallel(centre, (i - (lines - 1) / 2) * PITCH)
                routes.append(Route([place(*p) for p in line], pad))
    return routes


@dataclass(slots=True)
class _Pulse:
    route: Route
    reverse: bool = False
    speed: float = 0.0
    travelled: float = 0.0
    wait: float = 0.0
    fade: float = 1.0
    points: list[Point] = field(default_factory=list)  # from the head back along the tail, for the frame being shown


class PcbBackground(QWidget):
    """The board. It is the size of its parent, which it follows, and lies behind everything else in it (``lower()`` is done here).
    ``bands`` says how high the bands at the top and bottom of the parent are where nothing may be drawn (the header, the status
    line), and is asked whenever the widget is drawn again."""

    def __init__(self, parent: QWidget, *, bands: Callable[[], tuple[int, int]] = lambda: (0, 0), animated: bool = True,
                 seed: int = 7) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # it only ever shows; clicks reach what is above it
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)  # every pixel is painted
        self._bands = bands
        self._seed = seed
        self._animated = animated
        self._shown = False
        self._routes: list[Route] = []
        self._pulses: list[_Pulse] = []
        self._traces = QPainterPath()
        self._pads = QPainterPath()
        self._laid_out_for: tuple = ()
        self._static: QPixmap | None = None  # the circuit as drawn, kept while the widget is on show
        self._static_for = (0, 0, 0.0)
        self._lit = QRegion()  # where the pulses were drawn in the last frame
        self._rng = random.Random(seed)
        self._clock = QElapsedTimer()
        self._last = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._advance)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.lower()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    # ---- animation -----------------------------------------------------------------------------------------------------------
    def animated(self) -> bool:
        return self._animated

    def set_animated(self, on: bool) -> None:
        """Turn the pulses on or off. Off, the circuit is drawn once and nothing runs."""
        self._animated = on
        self._sync()

    def _sync(self) -> None:
        if self._animated and self._shown:
            if not self.timer.isActive():
                self._clock.start()
                self._last = 0.0
                self.timer.start()
        elif self.timer.isActive():
            self.timer.stop()
            self.update()  # the pulses are painted over

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._shown = True
        self._sync()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._shown = False
        self._static = None  # the pixmap is the one big thing here; it is drawn again from the kept paths when the page returns
        self._sync()

    def _launch(self, pulse: _Pulse, *, first: bool = False) -> None:
        pulse.route = self._rng.choice(self._routes)
        pulse.reverse = self._rng.random() < 0.35
        pulse.speed = self._rng.uniform(*SPEED)
        pulse.travelled = 0.0
        pulse.wait = self._rng.uniform(0.0, PAUSE[1]) if first else self._rng.uniform(*PAUSE)
        pulse.fade = 1.0
        pulse.points = []

    def _place(self, pulse: _Pulse) -> QRegion:
        """Work out where the pulse is, and return the rectangle it takes up."""
        route = pulse.route
        head = route.length - pulse.travelled if pulse.reverse else pulse.travelled
        sign = 1.0 if pulse.reverse else -1.0  # the tail trails behind the head
        steps = 8
        pulse.points = [route.at(head + sign * TAIL * i / steps) for i in range(steps + 1)]
        pulse.fade = 1.0 - max(0.0, pulse.travelled - route.length) / TAIL
        xs, ys = [p[0] for p in pulse.points], [p[1] for p in pulse.points]
        return QRegion(QRect(int(min(xs)) - 7, int(min(ys)) - 7, int(max(xs) - min(xs)) + 15, int(max(ys) - min(ys)) + 15))

    def _advance(self) -> None:
        now = self._clock.elapsed() / 1000
        step = min(now - self._last, MAX_STEP)
        self._last = now
        lit = QRegion()
        for pulse in self._pulses:
            if pulse.wait > 0:
                pulse.wait -= step
                continue
            pulse.travelled += pulse.speed * step
            if pulse.travelled > pulse.route.length + TAIL:
                self._launch(pulse)
                continue
            lit = lit.united(self._place(pulse))
        self.update(self._lit.united(lit))  # what the pulses left, and what they now cover; nothing else is painted
        self._lit = lit

    # ---- drawing -------------------------------------------------------------------------------------------------------------
    def _lay_out(self) -> None:
        """The circuit for the size of the widget: the paths that are drawn, and the pulses that run on them."""
        bands = self._bands()
        self._laid_out_for = (self.width(), self.height(), bands)
        self._routes = build_circuit(self.width(), self.height(), bands, self._seed)
        self._traces, self._pads = QPainterPath(), QPainterPath()
        for route in self._routes:
            self._traces.moveTo(*route.points[0])
            for point in route.points[1:]:
                self._traces.lineTo(*point)
            self._pads.addEllipse(QPointF(*route.points[0]), 2.6, 2.6)
            if route.ends_in_pad:
                self._pads.addEllipse(QPointF(*route.points[-1]), 3.4, 3.4)
        self._rng = random.Random(self._seed + 1)
        self._pulses = []
        if self._routes:
            for _ in range(min(PULSES, max(2, len(self._routes) // 4))):
                pulse = _Pulse(self._routes[0])
                self._launch(pulse, first=True)
                self._pulses.append(pulse)
        self._lit = QRegion()

    def _draw_static(self, ratio: float) -> None:
        pixmap = QPixmap(math.ceil(self.width() * ratio), math.ceil(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(BACKGROUND))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(TRACE, 1.0))
        painter.drawPath(self._traces)
        painter.setBrush(QColor(BACKGROUND))  # a pad is a ring: the trace that ends in it does not run through
        painter.setPen(QPen(PAD, 1.0))
        painter.drawPath(self._pads)
        painter.end()
        self._static = pixmap
        self._static_for = (self.width(), self.height(), ratio)

    def paintEvent(self, event) -> None:
        if (self.width(), self.height(), self._bands()) != self._laid_out_for:
            self._lay_out()
        ratio = self.devicePixelRatioF()
        if self._static is None or self._static_for != (self.width(), self.height(), ratio):
            self._draw_static(ratio)
        painter = QPainter(self)  # Qt has limited it to the rectangles that are to be painted
        painter.drawPixmap(0, 0, self._static)
        if self.timer.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for pulse in self._pulses:
                if pulse.points and pulse.fade > 0:
                    self._paint_pulse(painter, pulse)
        painter.end()

    @staticmethod
    def _paint_pulse(painter: QPainter, pulse: _Pulse) -> None:
        points = pulse.points
        last = len(points) - 1
        for i in range(last):
            colour = QColor(PULSE)
            colour.setAlphaF(0.85 * pulse.fade * (1 - i / last) ** 1.5)
            painter.setPen(QPen(colour, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(*points[i]), QPointF(*points[i + 1]))
        head = QPointF(*points[0])
        painter.setPen(Qt.PenStyle.NoPen)
        for radius, base, colour in ((4.5, 0.22, PULSE), (1.9, 0.95, PULSE_CORE)):
            glow = QColor(colour)
            glow.setAlphaF(base * pulse.fade)
            painter.setBrush(glow)
            painter.drawEllipse(head, radius, radius)
