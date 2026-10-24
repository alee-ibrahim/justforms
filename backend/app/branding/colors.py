"""Accessible theme tokens from one brand colour (docs/ux/BRANDING-SCREENS.md section 1).

The studio and the forms are themed by shadcn CSS variables. An organisation picks one
primary colour; this module turns it into the light and dark values of ``--primary``,
``--primary-foreground``, ``--ring``, ``--sidebar-primary`` (+ foreground) and ``--chart-1``,
adjusting the colour until it meets WCAG AA:

- light: the primary reads at 4.5:1 on the sheet (white) and on the desk, since it is also
  link and focus colour;
- dark: the same against the dark sheet and desk;
- the foreground (text on primary buttons) is white or ink, whichever reaches 4.5:1.

Pure functions, no I/O; the API reports what was adjusted so the Settings form can say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Surfaces from frontend/src/index.css (oklch tokens converted to sRGB).
LIGHT_SHEET = "#FFFFFF"
LIGHT_DESK = "#F3F5F9"
DARK_SHEET = "#1A2038"
DARK_DESK = "#121729"
WHITE = "#FFFFFF"
INK = "#18203A"  # light-mode foreground
DARK_INK = "#121729"  # text on a light (dark-mode) primary

AA = 4.5


def parse_hex(value: str) -> tuple[int, int, int]:
    if not HEX.match(value):
        raise ValueError("colour must be #RRGGBB")
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in rgb))


def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    r, g, b = parse_hex(value)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(value: str, target: str, t: float) -> str:
    a, b = parse_hex(value), parse_hex(target)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(a, b, strict=True)))  # type: ignore[arg-type]


def _toward(value: str, target: str, ok: object) -> str:
    """The smallest mix of ``value`` toward ``target`` (black or white) that satisfies ``ok``."""
    assert callable(ok)
    if ok(value):
        return value
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if ok(_mix(value, target, mid)):
            hi = mid
        else:
            lo = mid
    return _mix(value, target, hi)


def _foreground(primary: str, light: str, dark: str) -> str:
    return light if contrast(primary, light) >= contrast(primary, dark) else dark


@dataclass(frozen=True)
class Mode:
    primary: str
    foreground: str
    on_sheet: float  # contrast of primary on the sheet
    on_primary: float  # contrast of the foreground on primary

    def tokens(self) -> dict[str, str]:
        return {
            "--primary": self.primary,
            "--primary-foreground": self.foreground,
            "--ring": self.primary,
            "--sidebar-primary": self.primary,
            "--sidebar-primary-foreground": self.foreground,
            "--sidebar-ring": self.primary,
            "--chart-1": self.primary,
        }


@dataclass(frozen=True)
class Palette:
    chosen: str
    light: Mode
    dark: Mode
    warnings: list[str] = field(default_factory=list)

    @property
    def adjusted(self) -> bool:
        return self.light.primary != self.chosen

    def css(self) -> str:
        """``:root`` and ``.dark`` blocks; values are validated hex, nothing user-typed."""

        def block(sel: str, mode: Mode) -> str:
            body = ";".join(f"{k}:{v}" for k, v in mode.tokens().items())
            return f"{sel}{{{body}}}"

        return block(":root", self.light) + block(".dark", self.dark) + "\n"

    def report(self) -> dict[str, object]:
        return {
            "chosen": self.chosen,
            "adjusted": self.adjusted,
            "light": {
                "primary": self.light.primary,
                "foreground": self.light.foreground,
                "contrast": round(self.light.on_sheet, 2),
                "foregroundContrast": round(self.light.on_primary, 2),
            },
            "dark": {
                "primary": self.dark.primary,
                "foreground": self.dark.foreground,
                "contrast": round(self.dark.on_sheet, 2),
                "foregroundContrast": round(self.dark.on_primary, 2),
            },
            "warnings": self.warnings,
        }


def palette(chosen: str) -> Palette:
    """Light and dark tokens for ``chosen`` (#RRGGBB), adjusted to meet AA."""
    chosen = chosen.upper()
    parse_hex(chosen)
    warnings: list[str] = []

    # Light: darken until it reads on both the sheet and the desk, and a white or ink label
    # reads on it.
    def light_ok(c: str) -> bool:
        fg = _foreground(c, WHITE, INK)
        return (
            min(contrast(c, LIGHT_SHEET), contrast(c, LIGHT_DESK)) >= AA and contrast(c, fg) >= AA
        )

    light = _toward(chosen, "#000000", light_ok)
    if light != chosen:
        warnings.append("darkened_for_contrast")
    light_fg = _foreground(light, WHITE, INK)

    # Dark: lighten the chosen colour until it reads on the dark sheet and desk.
    def dark_ok(c: str) -> bool:
        fg = _foreground(c, WHITE, DARK_INK)
        return min(contrast(c, DARK_SHEET), contrast(c, DARK_DESK)) >= AA and contrast(c, fg) >= AA

    dark = _toward(chosen, "#FFFFFF", dark_ok)
    dark_fg = _foreground(dark, WHITE, DARK_INK)
    return Palette(
        chosen=chosen,
        light=Mode(light, light_fg, contrast(light, LIGHT_SHEET), contrast(light, light_fg)),
        dark=Mode(dark, dark_fg, contrast(dark, DARK_SHEET), contrast(dark, dark_fg)),
        warnings=warnings,
    )
