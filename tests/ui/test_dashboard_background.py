"""The circuit board the Dashboard stands on (datamapperx/ui/pcb_background.py): what is drawn, that it runs only while it is seen,
and that the header and the status line sit on it without anything else in the window changing.

The first tests need no window: they look at the traces themselves. The rest use the main window.
"""
from __future__ import annotations

import math
from itertools import pairwise

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from datamapperx.ui.pcb_background import (
    BACKGROUND,
    FRAME_MS,
    START_GAP,
    PcbBackground,
    Route,
    build_circuit,
    quiet_area,
)


def has_light_lettering(pixmap) -> bool:
    """Whether a logo has pale lettering (the variant for a dark surface): the mean lightness of its solid pixels."""
    image = pixmap.toImage()
    shades = [c.lightness() for x in range(0, image.width(), 2) for y in range(0, image.height(), 2)
              if (c := image.pixelColor(x, y)).alpha() > 200]
    return sum(shades) / len(shades) > 150


SIZES = [(1360, 814, (66, 0)), (1920, 950, (66, 22)), (1000, 614, (66, 22)), (1400, 700, (0, 0))]


# ----------------------------------------------------------------------------- the traces
@pytest.mark.parametrize(("width", "height", "bands"), SIZES)
def test_every_trace_runs_horizontally_vertically_or_at_45_degrees(width, height, bands):
    routes = build_circuit(width, height, bands)
    assert routes
    for route in routes:
        for (x0, y0), (x1, y1) in pairwise(route.points):
            dx, dy = abs(x1 - x0), abs(y1 - y0)
            assert dx > 1e-6 or dy > 1e-6
            assert dx < 1e-6 or dy < 1e-6 or abs(dx - dy) < 1e-6, ((x0, y0), (x1, y1))


@pytest.mark.parametrize(("width", "height", "bands"), SIZES)
def test_nothing_is_drawn_in_the_quiet_area_or_in_the_bands(width, height, bands):
    left, top, right, bottom = quiet_area(width, height, bands)
    for route in build_circuit(width, height, bands):
        for x, y in route.points:
            assert not (left + 1e-6 < x < right - 1e-6 and top + 1e-6 < y < bottom - 1e-6), (x, y)  # the content's area
            # the header and the status line (where there is none, a trace runs off the window's edge)
            assert (not bands[0] or y >= bands[0]) and (not bands[1] or y <= height - bands[1]), (x, y)


def test_traces_that_meet_a_band_end_in_a_pad_before_it():
    zone_top = quiet_area(1360, 814, (66, 22))[1]
    top = [r for r in build_circuit(1360, 814, (66, 22)) if abs(r.points[0][1] - (zone_top - START_GAP)) < 1e-6]  # start at its top edge
    assert top and all(r.ends_in_pad for r in top)


def test_the_same_size_gives_the_same_circuit_and_a_seed_gives_another():
    first, again = build_circuit(1360, 814, (66, 22)), build_circuit(1360, 814, (66, 22))
    assert [r.points for r in first] == [r.points for r in again]
    assert [r.points for r in first] != [r.points for r in build_circuit(1360, 814, (66, 22), seed=8)]


def test_a_widget_too_small_for_traces_gets_none_and_does_not_fail():
    assert build_circuit(300, 200, (66, 22)) == []
    assert build_circuit(0, 0) == []


def test_a_point_along_a_route_follows_its_corners_and_is_held_to_its_ends():
    route = Route([(0, 0), (10, 0), (20, 10)], ends_in_pad=False)
    assert route.length == pytest.approx(10 + 10 * math.sqrt(2))
    assert route.at(-5) == (0, 0) and route.at(999) == (20, 10)
    assert route.at(5) == pytest.approx((5, 0))
    assert route.at(10 + math.sqrt(2) * 5) == pytest.approx((15, 5))


# ----------------------------------------------------------------------------- in the window
def test_the_board_is_the_window_behind_everything_and_lets_clicks_through(app, window):
    canvas = window.canvas
    window.resize(1400, 900)
    app.processEvents()
    assert canvas.geometry() == window.rect() and canvas.isVisible()
    assert canvas.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    siblings = [c for c in window.children() if isinstance(c, QWidget)]
    assert siblings.index(canvas) == 0  # the lowest: the header, the pages and the status line are all above it


def test_the_board_runs_on_the_dashboard_and_stops_while_it_is_hidden(app, window):
    canvas = window.canvas
    assert window.workspace == "dashboard" and canvas.timer.isActive()
    QTest.qWait(3 * FRAME_MS)  # a pixmap is made on the first paint
    assert canvas._static is not None
    window._show_workspace("mapping")
    assert not canvas.isVisible() and not canvas.timer.isActive()
    assert canvas._static is None  # the one big thing it holds is given back while it is not seen
    window._show_workspace("dashboard")
    assert canvas.isVisible() and canvas.timer.isActive()
    QTest.qWait(3 * FRAME_MS)
    assert canvas._static is not None


def test_it_runs_at_24_to_30_frames_a_second():
    assert 24 <= 1000 / FRAME_MS <= 30


def test_animation_can_be_switched_off_completely_and_on_again(app, window):
    canvas = window.canvas
    assert canvas.animated()
    canvas.set_animated(False)
    assert canvas.isVisible() and not canvas.timer.isActive()
    window._show_workspace("mapping")
    window._show_workspace("dashboard")
    assert canvas.isVisible() and not canvas.timer.isActive()  # coming back does not start it
    canvas.set_animated(True)
    assert canvas.timer.isActive()


def test_a_board_made_still_never_starts(app):
    parent = QWidget()
    parent.resize(600, 400)
    board = PcbBackground(parent, animated=False)
    parent.show()
    app.processEvents()
    assert board.isVisible() and not board.timer.isActive() and board.geometry() == parent.rect()
    parent.close()
    parent.deleteLater()


def test_the_pulses_move_and_the_circuit_does_not(app, window):
    canvas = window.canvas
    window.resize(1400, 900)
    QTest.qWait(3 * FRAME_MS)
    routes = [list(r.points) for r in canvas._routes]
    for pulse in canvas._pulses:
        pulse.wait = 0.0
    QTest.qWait(80)
    canvas._advance()
    before = [(p.travelled, tuple(p.points)) for p in canvas._pulses]
    QTest.qWait(120)
    canvas._advance()
    after = [(p.travelled, tuple(p.points)) for p in canvas._pulses]
    moved = sum(1 for (t0, _), (t1, _) in zip(before, after, strict=True) if t1 > t0)
    assert moved >= len(canvas._pulses) - 2 and moved > 0  # (one that has just reached the end starts over)
    assert [list(r.points) for r in canvas._routes] == routes


def test_a_frame_repaints_only_small_rectangles_where_the_pulses_are(app, window):
    canvas = window.canvas
    window.resize(1400, 900)
    QTest.qWait(3 * FRAME_MS)
    for pulse in canvas._pulses:
        pulse.wait = 0.0
    QTest.qWait(80)
    canvas._advance()
    area = sum(r.width() * r.height() for r in canvas._lit)
    assert 0 < area < 0.1 * canvas.width() * canvas.height()


def test_the_content_area_and_the_branding_band_stay_flat_navy(app, window):
    canvas = window.canvas
    window.resize(1400, 900)
    QTest.qWait(3 * FRAME_MS)
    for pulse in canvas._pulses:
        pulse.wait = 0.0
    for _ in range(6):
        QTest.qWait(40)
        canvas._advance()
    image = canvas.grab().toImage()
    top, bottom = canvas._bands()
    left, q_top, right, q_bottom = quiet_area(canvas.width(), canvas.height(), (top, bottom))
    for name, rect in {"the content area": QRect(left, q_top, right - left, q_bottom - q_top),
                       "the header": QRect(0, 0, canvas.width(), top),
                       "the status line": QRect(0, canvas.height() - bottom, canvas.width(), bottom)}.items():
        flat = QImage(rect.size(), image.format())
        flat.fill(QColor(BACKGROUND))
        assert image.copy(rect) == flat, f"something is drawn on {name}"
    blank = QImage(image.size(), image.format())  # and the board is not simply blank
    blank.fill(QColor(BACKGROUND))
    assert image != blank


def test_in_the_light_theme_the_header_and_status_line_wear_dark_colours_only_on_the_dashboard(app, window):
    assert has_light_lettering(window._brand["dark"]) and not has_light_lettering(window._brand["light"])  # the helper tells them apart
    assert window.palette_tokens.mode == "light" and window.workspace == "dashboard"
    assert window.header.styleSheet() and window.statusBar().styleSheet()
    assert has_light_lettering(window.brand_logo.pixmap())  # it is on navy
    window._show_workspace("mapping")
    assert not window.header.styleSheet() and not window.statusBar().styleSheet()
    assert not has_light_lettering(window.brand_logo.pixmap())
    window._show_workspace("dashboard")
    assert window.header.styleSheet() and has_light_lettering(window.brand_logo.pixmap())


def test_in_the_dark_theme_the_header_is_left_as_it_is_and_the_theme_can_be_changed_on_the_dashboard(app, window):
    window._toggle_theme()  # to dark, on the Dashboard
    app.processEvents()
    assert window.palette_tokens.mode == "dark" and not window.header.styleSheet() and window.canvas.isVisible()
    assert has_light_lettering(window.brand_logo.pixmap())
    window._toggle_theme()  # and back
    app.processEvents()
    assert window.palette_tokens.mode == "light" and window.header.styleSheet()
    assert has_light_lettering(window.brand_logo.pixmap())
