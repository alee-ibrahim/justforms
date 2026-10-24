"""Signature strokes: validation, canonical form and server-side rendering (DESIGN 9.2).

The client's own drawing is never trusted: the server keeps the raw strokes, hashes their
canonical JSON and re-renders them to SVG and PNG. Rendering is deterministic: the same
strokes always give byte-identical files (for a given Pillow version).
"""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass
from typing import Any

import rfc8785
from PIL import Image, ImageDraw

MIN_POINTS = 10
MAX_POINTS = 20_000
MAX_STROKES = 500
# A signature must span at least this fraction of the pad in some direction (no dots).
MIN_EXTENT = 0.05
MAX_T_MS = 3_600_000

RENDER_WIDTH = 600
INK = (24, 32, 58, 255)  # Ink #18203A
SUPERSAMPLE = 4

type Point = list[float]  # [x, y, t, pressure]


class SignatureError(ValueError):
    """Strokes the server refuses; ``code`` is the problem code for the field."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Strokes:
    strokes: list[list[Point]]
    pad_width: int
    pad_height: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(rfc8785.dumps(self.strokes)).hexdigest()

    @property
    def render_size(self) -> tuple[int, int]:
        aspect = self.pad_height / self.pad_width
        return RENDER_WIDTH, max(100, min(RENDER_WIDTH, round(RENDER_WIDTH * aspect)))


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SignatureError("signature_invalid")
    return float(value)


def _round(value: float) -> float:
    return round(value, 4)


def parse_strokes(raw: Any, pad_width: Any, pad_height: Any) -> Strokes:
    """Validate client strokes and return them in canonical form.

    Points are ``[x, y, t, pressure]`` (``[x, y, pressure]`` is accepted with ``t = 0``);
    ``x``/``y`` are fractions of the pad, ``t`` milliseconds since the first touch."""
    width = _num(pad_width)
    height = _num(pad_height)
    if not (50 <= width <= 5000 and 30 <= height <= 5000):
        raise SignatureError("signature_invalid")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_STROKES:
        raise SignatureError("signature_invalid")
    strokes: list[list[Point]] = []
    total = 0
    xs: list[float] = []
    ys: list[float] = []
    for stroke in raw:
        if not isinstance(stroke, list) or not stroke:
            raise SignatureError("signature_invalid")
        points: list[Point] = []
        for pt in stroke:
            if not isinstance(pt, list) or len(pt) not in (3, 4):
                raise SignatureError("signature_invalid")
            x, y = _num(pt[0]), _num(pt[1])
            t, p = (0.0, _num(pt[2])) if len(pt) == 3 else (_num(pt[2]), _num(pt[3]))
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 <= p <= 1 and 0 <= t <= MAX_T_MS):
                raise SignatureError("signature_invalid")
            points.append([_round(x), _round(y), int(t), _round(p)])
            xs.append(x)
            ys.append(y)
        total += len(points)
        if total > MAX_POINTS:
            raise SignatureError("signature_invalid")
        strokes.append(points)
    if total < MIN_POINTS or max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_EXTENT:
        raise SignatureError("signature_small")
    return Strokes(strokes, round(width), round(height))


def _line_width(pressure: float) -> float:
    # Same feel as the pad: 1.2-3.4 px at the pad's CSS size, scaled to the render width.
    return 1.2 + 2.2 * (pressure or 0.5)


def render_svg(s: Strokes) -> bytes:
    w, h = s.render_size
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<g fill="none" stroke="#18203a" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for stroke in s.strokes:
        pressure = sum(p[3] for p in stroke) / len(stroke)
        d = " ".join(
            f"{'M' if i == 0 else 'L'}{p[0] * w:.2f} {p[1] * h:.2f}" for i, p in enumerate(stroke)
        )
        if len(stroke) == 1:
            d += f" L{stroke[0][0] * w:.2f} {stroke[0][1] * h:.2f}"
        parts.append(f'<path stroke-width="{_line_width(pressure):.2f}" d="{d}"/>')
    parts.append("</g></svg>")
    return "\n".join(parts).encode()


def render_png(s: Strokes) -> bytes:
    w, h = s.render_size
    k = SUPERSAMPLE
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for stroke in s.strokes:
        pts = [(p[0] * w * k, p[1] * h * k, p[3]) for p in stroke]
        for i, (x, y, pressure) in enumerate(pts):
            r = _line_width(pressure) * k / 2
            draw.ellipse((x - r, y - r, x + r, y + r), fill=INK)
            if i:
                px, py, _ = pts[i - 1]
                draw.line((px, py, x, y), fill=INK, width=max(1, round(r * 2)))
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False, compress_level=9)
    return out.getvalue()
