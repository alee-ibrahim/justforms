"""Accessible colour tokens for a form theme (docs/ux/FORM-THEME-SCREENS.md section 3.1).

The admin picks light-mode colours (any subset); this module fills in the rest from JustForms'
palette, generates dark-mode values from the same hues, and adjusts anything that fails WCAG AA:

- text, muted text, primary (also link and focus colour) and error read at 4.5:1 on the sheet
  and the page background;
- input outlines (derived from the border colour) reach 3:1 against both;
- the label on a primary button (white or ink) reads at 4.5:1 on the primary.

Pure functions; the API reports each adjustment so the settings can say what changed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.branding.colors import contrast, luminance, parse_hex, to_hex
from app.schemas.theme import ThemeColors

AA = 4.5
NON_TEXT = 3.0
WHITE = "#FFFFFF"
BLACK = "#000000"

# JustForms' own palette (frontend/src/index.css, DESIGN-SYSTEM 3.1).
LIGHT = {
    "background": "#F3F5F9",
    "surface": "#FFFFFF",
    "text": "#18203A",
    "muted_text": "#5A6380",
    "border": "#DCE0EA",
    "input": "#838AA2",
    "error": "#C0362C",
    "primary": "#3B3FC1",
}
DARK = {
    "background": "#121729",
    "surface": "#1A2038",
    "text": "#E6E9F2",
    "muted_text": "#A3AAC2",
    "border": "#2C3454",
    "input": "#6B7393",
    "error": "#FF8A7A",
    "primary": "#9DA2FF",
}
INK = "#18203A"
DARK_INK = "#121729"

# -- colour maths ------------------------------------------------------------------------------


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(value: str) -> tuple[float, float, float]:
    r, g, b = (_lin(c / 255) for c in parse_hex(value))
    lv = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    mv = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    sv = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    big_l = 0.2104542553 * lv + 0.793617785 * mv - 0.0040720468 * sv
    a = 1.9779984951 * lv - 2.428592205 * mv + 0.4505937099 * sv
    bb = 0.0259040371 * lv + 0.7827717662 * mv - 0.808675766 * sv
    return big_l, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def from_oklch(big_l: float, c: float, h: float) -> str:
    a, bb = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    lv = (big_l + 0.3963377774 * a + 0.2158037573 * bb) ** 3
    mv = (big_l - 0.1055613458 * a - 0.0638541728 * bb) ** 3
    sv = (big_l - 0.0894841775 * a - 1.291485548 * bb) ** 3
    rgb = (
        4.0767416621 * lv - 3.3077115913 * mv + 0.2309699292 * sv,
        -1.2684380046 * lv + 2.6097574011 * mv - 0.3413193965 * sv,
        -0.0041960863 * lv - 0.7034186147 * mv + 1.707614701 * sv,
    )
    return to_hex(tuple(_gam(x) * 255 for x in rgb))  # type: ignore[arg-type]


def mix(a: str, b: str, t: float) -> str:
    x, y = parse_hex(a), parse_hex(b)
    return to_hex(tuple(p + (q - p) * t for p, q in zip(x, y, strict=True)))  # type: ignore[arg-type]


def is_light(value: str) -> bool:
    return luminance(value) > 0.18


def min_contrast(value: str, against: list[str]) -> float:
    return min(contrast(value, x) for x in against)


def ensure(value: str, against: list[str], ratio: float) -> str:
    """``value`` moved toward black or white (away from the surfaces) just far enough to
    read at ``ratio`` on every colour in ``against``; the best it can do if it never does."""
    if min_contrast(value, against) >= ratio:
        return value
    target = BLACK if is_light(against[0]) else WHITE
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if min_contrast(mix(value, target, mid), against) >= ratio:
            hi = mid
        else:
            lo = mid
    return mix(value, target, hi)


def foreground(primary: str, light: str = WHITE, dark: str = INK) -> str:
    return light if contrast(primary, light) >= contrast(primary, dark) else dark


def ensure_primary(value: str, against: list[str], toward: str, ink: str) -> str:
    """The primary moved toward ``toward`` until it reads on the surfaces and its label reads
    on it."""

    def ok(c: str) -> bool:
        return min_contrast(c, against) >= AA and contrast(c, foreground(c, WHITE, ink)) >= AA

    if ok(value):
        return value
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if ok(mix(value, toward, mid)):
            hi = mid
        else:
            lo = mid
    return mix(value, toward, hi)


def darkened(value: str, lightness: float, max_chroma: float) -> str:
    """The same hue at a dark-mode lightness (surfaces) or light one (text)."""
    _l, c, h = to_oklch(value)
    return from_oklch(lightness, min(c, max_chroma), h)


# -- tokens ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Adjustment:
    color: str  # ThemeColors field (camelCase in the API)
    chosen: str
    used: str
    contrast: float
    needed: float

    def as_dict(self) -> dict[str, object]:
        return {
            "color": self.color,
            "chosen": self.chosen,
            "used": self.used,
            "contrast": round(self.contrast, 2),
            "needed": self.needed,
        }


@dataclass
class ColorTokens:
    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)
    adjustments: list[Adjustment] = field(default_factory=list)
    # Resolved light values, for emails and PDFs.
    primary: str = LIGHT["primary"]
    primary_foreground: str = WHITE
    text: str = LIGHT["text"]


CAMEL = {"muted_text": "mutedText"}


def _primary_tokens(primary: str, fg: str) -> dict[str, str]:
    return {
        "--primary": primary,
        "--primary-foreground": fg,
        "--ring": primary,
        "--chart-1": primary,
    }


def resolve_colors(chosen: ThemeColors, brand_primary: str | None = None) -> ColorTokens:
    """Tokens for ``chosen`` over JustForms' palette (and the brand colour for the primary).

    Only tokens that differ from JustForms' own are emitted: no colours chosen and no brand
    colour means no tokens at all. Every token set in light mode is also set in dark mode, so
    the stylesheet's ``.dark`` block always wins over its ``:root`` block.
    """
    out = ColorTokens()
    neutrals = any(
        getattr(chosen, k) for k in ("background", "surface", "text", "muted_text", "border")
    )
    wanted_primary = (chosen.primary or brand_primary or "").upper() or None
    if not neutrals and not chosen.error and not wanted_primary:
        return out

    def note(key: str, picked: str | None, used: str, against: list[str], needed: float) -> None:
        if picked and used.upper() != picked.upper():
            out.adjustments.append(
                Adjustment(
                    CAMEL.get(key, key), picked.upper(), used, min_contrast(used, against), needed
                )
            )

    # Light mode.
    bg = (chosen.background or LIGHT["background"]).upper()
    surface = (chosen.surface or LIGHT["surface"]).upper()
    planes = [surface, bg]
    text = ensure((chosen.text or LIGHT["text"]).upper(), planes, AA)
    note("text", chosen.text, text, planes, AA)
    if chosen.muted_text:
        muted = ensure(chosen.muted_text.upper(), planes, AA)
        note("muted_text", chosen.muted_text, muted, planes, AA)
    else:
        muted = ensure(mix(text, surface, 0.32), planes, AA) if neutrals else LIGHT["muted_text"]
    border = (chosen.border or (mix(text, surface, 0.84) if neutrals else LIGHT["border"])).upper()
    input_ = ensure(
        border if chosen.border else (mix(text, surface, 0.5) if neutrals else LIGHT["input"]),
        planes,
        NON_TEXT,
    )
    error = ensure((chosen.error or LIGHT["error"]).upper(), planes, AA)
    note("error", chosen.error, error, planes, AA)
    primary_in = wanted_primary or LIGHT["primary"]
    toward = BLACK if is_light(surface) else WHITE
    primary = ensure_primary(primary_in, planes, toward, INK if is_light(surface) else DARK_INK)
    if chosen.primary:
        note("primary", chosen.primary, primary, planes, AA)
    primary_fg = foreground(primary, WHITE, INK)
    out.primary, out.primary_foreground, out.text = primary, primary_fg, text

    # Dark mode: the same hues at dark-mode lightness, checked the same way.
    d_bg = darkened(bg, 0.209, 0.04) if chosen.background else DARK["background"]
    d_surface = darkened(surface, 0.251, 0.05) if chosen.surface else DARK["surface"]
    d_planes = [d_surface, d_bg]
    d_text = ensure(darkened(text, 0.934, 0.02) if chosen.text else DARK["text"], d_planes, AA)
    if chosen.muted_text:
        d_muted = ensure(darkened(muted, 0.74, 0.04), d_planes, AA)
    else:
        d_muted = (
            ensure(mix(d_text, d_surface, 0.3), d_planes, AA) if neutrals else DARK["muted_text"]
        )
    if chosen.border:
        d_border = darkened(border, 0.333, 0.06)
    else:
        d_border = mix(d_text, d_surface, 0.82) if neutrals else DARK["border"]
    d_input = ensure(
        d_border
        if chosen.border
        else (mix(d_text, d_surface, 0.55) if neutrals else DARK["input"]),
        d_planes,
        NON_TEXT,
    )
    d_error = ensure(chosen.error.upper() if chosen.error else DARK["error"], d_planes, AA)
    d_primary_in = wanted_primary or DARK["primary"]
    d_primary = ensure_primary(d_primary_in, d_planes, WHITE, DARK_INK)
    d_primary_fg = foreground(d_primary, WHITE, DARK_INK)

    out.light.update(_primary_tokens(primary, primary_fg))
    out.dark.update(_primary_tokens(d_primary, d_primary_fg))
    out.light["--secondary"] = mix(primary, surface, 0.88)
    out.dark["--secondary"] = mix(d_primary, d_surface, 0.78)
    if chosen.error or neutrals:
        out.light["--destructive"] = error
        out.dark["--destructive"] = d_error
    if neutrals:
        for tokens, (b, s, t, m, bd, inp) in (
            (out.light, (bg, surface, text, muted, border, input_)),
            (out.dark, (d_bg, d_surface, d_text, d_muted, d_border, d_input)),
        ):
            tokens.update(
                {
                    "--background": b,
                    "--foreground": t,
                    "--card": s,
                    "--card-foreground": t,
                    "--popover": s,
                    "--popover-foreground": t,
                    "--secondary-foreground": t,
                    "--muted": b if b != s else mix(t, s, 0.94),
                    "--muted-foreground": m,
                    "--border": bd,
                    "--input": inp,
                }
            )
    # Marker (the selection wash, --accent) keeps JustForms' colours: it carries meaning.
    return out
