"""Génère l'icône de l'application (PNG 1024x1024) sans dépendance externe.

Usage : python make_icon.py sortie.png
Le script de build la convertit ensuite en .icns avec les outils macOS (sips, iconutil).
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

SIZE = 1024
MARGIN = 100  # marge transparente autour du carré arrondi (gabarit d'icône macOS)
RADIUS = 185
TOP, BOTTOM = (57, 135, 229), (16, 66, 129)  # dégradé bleu
LINE = (255, 255, 255)
ACCENT = (235, 104, 52)
POINTS = [(240, 700), (390, 560), (500, 620), (640, 430), (790, 300)]
STROKE = 34


def _rounded_rect_alpha(x: float, y: float) -> float:
    lo, hi = MARGIN, SIZE - MARGIN
    cx = min(max(x, lo + RADIUS), hi - RADIUS)
    cy = min(max(y, lo + RADIUS), hi - RADIUS)
    d = math.hypot(x - cx, y - cy) - RADIUS if (x < lo + RADIUS or x > hi - RADIUS) and (
        y < lo + RADIUS or y > hi - RADIUS) else max(lo - x, x - hi, lo - y, y - hi)
    return min(1.0, max(0.0, 0.5 - d))


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def render() -> bytes:
    segments = list(zip(POINTS, POINTS[1:]))
    end_x, end_y = POINTS[-1]
    rows = []
    for y in range(SIZE):
        row = bytearray([0])  # filtre PNG « None »
        k = (y - MARGIN) / (SIZE - 2 * MARGIN)
        base = [round(TOP[i] + (BOTTOM[i] - TOP[i]) * min(1, max(0, k))) for i in range(3)]
        for x in range(SIZE):
            a = _rounded_rect_alpha(x + 0.5, y + 0.5)
            if a == 0:
                row += b"\0\0\0\0"
                continue
            r, g, b = base
            # Courbe (anti-crénelée par couverture) ; calcul limité à sa zone.
            if 200 < x < 830 and 260 < y < 740:
                d = min(_segment_distance(x + .5, y + .5, *s[0], *s[1]) for s in segments)
                cov = min(1.0, max(0.0, STROKE / 2 + 0.5 - d))
                if cov:
                    r, g, b = (round(c * (1 - cov) + l * cov) for c, l in zip((r, g, b), LINE))
            # Point final orange, cerclé de blanc.
            dist = math.hypot(x + .5 - end_x, y + .5 - end_y)
            if dist < 62:
                ring = min(1.0, max(0.0, 62 - dist))
                r, g, b = (round(c * (1 - ring) + l * ring) for c, l in zip((r, g, b), LINE))
                dot = min(1.0, max(0.0, 44 - dist))
                r, g, b = (round(c * (1 - dot) + l * dot) for c, l in zip((r, g, b), ACCENT))
            row += bytes((r, g, b, round(255 * a)))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
    with open(out, "wb") as f:
        f.write(render())
    print(f"Icône écrite : {out}")
