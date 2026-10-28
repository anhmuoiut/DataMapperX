"""Render assets/Jabil-Logo.svg into the PNG files the application shows.

Tk 8.6 cannot draw SVG, so the logo is rendered once here and the PNGs are committed. Only development needs
Pillow; the application itself does not. Run from the project folder after changing the SVG:

    python tools/make_logo_png.py

Writes assets/Jabil-Logo-<light|dark>-<height>.png. The dark variant has white letters so the logo stays
readable on a dark background; the green swoosh is kept. Heights: 38 px (normal screens) and 76 px (150% / 200%).
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "Jabil-Logo.svg"
HEIGHTS = (38, 76)
SUPERSAMPLE = 4
CURVE_STEPS = 24
LETTERS_DARK_BACKGROUND = "#ffffff"

_TOKEN = re.compile(r"([MmLlHhVvCcZz])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_ARGUMENTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Z": 0}

Point = tuple[float, float]


def parse_path(data: str) -> list[list[Point]]:
    """Flatten an SVG path made of M, L, H, V, C and Z commands into closed polygons."""
    tokens = [(m.group(1), m.group(2)) for m in _TOKEN.finditer(data)]
    polygons: list[list[Point]] = []
    current: list[Point] = []
    x = y = 0.0
    start = (0.0, 0.0)
    i = 0

    def take(count: int) -> list[float]:
        nonlocal i
        if i + count > len(tokens) or any(tokens[i + k][1] is None for k in range(count)):
            raise ValueError(f"Malformed path data near token {i}")
        values = [float(tokens[i + k][1]) for k in range(count)]
        i += count
        return values

    while i < len(tokens):
        letter = tokens[i][0]
        if letter is None:
            raise ValueError("A number appeared without a command")
        i += 1
        relative, op = letter.islower(), letter.upper()
        if op == "Z":
            if current:
                polygons.append(current)
                current = []
            x, y = start
            continue
        first = True
        while i < len(tokens) and tokens[i][0] is None:
            if not current and op != "M":
                current = [(x, y)]
            if op == "M":
                dx, dy = take(2)
                x, y = (x + dx, y + dy) if relative else (dx, dy)
                if first:
                    if current:
                        polygons.append(current)
                    current, start = [(x, y)], (x, y)
                else:
                    current.append((x, y))  # extra pairs after a moveto are linetos
            elif op == "L":
                dx, dy = take(2)
                x, y = (x + dx, y + dy) if relative else (dx, dy)
                current.append((x, y))
            elif op == "H":
                (dx,) = take(1)
                x = x + dx if relative else dx
                current.append((x, y))
            elif op == "V":
                (dy,) = take(1)
                y = y + dy if relative else dy
                current.append((x, y))
            else:  # C
                c = take(6)
                if relative:
                    c = [c[0] + x, c[1] + y, c[2] + x, c[3] + y, c[4] + x, c[5] + y]
                p0, p1, p2, p3 = (x, y), (c[0], c[1]), (c[2], c[3]), (c[4], c[5])
                for step in range(1, CURVE_STEPS + 1):
                    t = step / CURVE_STEPS
                    u = 1 - t
                    current.append((
                        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
                    ))
                x, y = p3
            first = False
    if current:
        polygons.append(current)
    return polygons


def read_svg(path: Path) -> list[tuple[list[list[Point]], str]]:
    """(polygons, fill colour) for every path of the SVG, in drawing order."""
    shapes = []
    for element in ET.parse(path).getroot().iter():
        if element.tag.endswith("path"):
            shapes.append((parse_path(element.attrib["d"]), element.attrib.get("fill", "#000000")))
    return shapes


def render(shapes: list[tuple[list[list[Point]], str]], height: int, recolor: dict[str, str] | None = None) -> Image.Image:
    """Draw the shapes cropped to their own bounds, ``height`` pixels tall, with smooth edges and no halo."""
    points = [p for polygons, _ in shapes for polygon in polygons for p in polygon]
    left, top = min(p[0] for p in points), min(p[1] for p in points)
    right, bottom = max(p[0] for p in points), max(p[1] for p in points)
    scale = height / (bottom - top)
    width = max(1, round((right - left) * scale))
    big = (width * SUPERSAMPLE, height * SUPERSAMPLE)

    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for polygons, fill in shapes:
        mask = Image.new("1", big, 0)
        for polygon in polygons:
            layer = Image.new("1", big, 0)
            ImageDraw.Draw(layer).polygon(
                [((px - left) * scale * SUPERSAMPLE, (py - top) * scale * SUPERSAMPLE) for px, py in polygon], fill=1
            )
            mask = ImageChops.logical_xor(mask, layer)  # even-odd, so the holes in A and B stay open
        alpha = mask.convert("L").resize((width, height), Image.LANCZOS)
        colour = (recolor or {}).get(fill.lower(), fill)
        layer = Image.new("RGBA", (width, height), colour)
        layer.putalpha(alpha)
        result = Image.alpha_composite(result, layer)
    return result


def main() -> int:
    shapes = read_svg(SVG)
    letters = shapes[0][1].lower()
    written = []
    for height in HEIGHTS:
        for mode, recolor in (("light", None), ("dark", {letters: LETTERS_DARK_BACKGROUND})):
            target = ROOT / "assets" / f"Jabil-Logo-{mode}-{height}.png"
            image = render(shapes, height, recolor)
            image.save(target, optimize=True)
            written.append(f"{target.name} ({image.width}x{image.height})")
    print("Wrote " + ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
