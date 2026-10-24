"""Fonts a form theme can use (docs/ux/FORM-THEME-SCREENS.md section 3.1).

Latin: a curated set of SIL OFL families. Atkinson Hyperlegible Next is bundled with the app;
the others are built into ``/theme-fonts/{id}.css`` (``frontend/vite.config.ts``) and only
fetched by pages whose theme uses them.

Thaana: the install's list (``JUSTFORMS_THAANA_FONTS``). With a css2-style font service as
``JUSTFORMS_THAANA_FONT_CSS_URL`` each family has its own stylesheet there; otherwise the families
come from the operator's ``/fonts/fonts.css``. Noto Sans Thaana (bundled) is always offered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

from app.config import DEFAULT_THAANA_FONTS, Settings


@dataclass(frozen=True)
class Font:
    id: str
    name: str
    family: str  # CSS font-family value
    css_url: str | None  # stylesheet to load, None when bundled or operator-provided


LATIN: dict[str, Font] = {
    f.id: f
    for f in (
        Font(
            "atkinson", "Atkinson Hyperlegible Next", "'Atkinson Hyperlegible Next Variable'", None
        ),
        Font("inter", "Inter", "'Inter Variable'", "/theme-fonts/inter.css"),
        Font(
            "ibm-plex-sans",
            "IBM Plex Sans",
            "'IBM Plex Sans Variable'",
            "/theme-fonts/ibm-plex-sans.css",
        ),
        Font(
            "source-serif-4",
            "Source Serif 4",
            "'Source Serif 4 Variable'",
            "/theme-fonts/source-serif-4.css",
        ),
        Font("noto-sans", "Noto Sans", "'Noto Sans Variable'", "/theme-fonts/noto-sans.css"),
    )
}

NOTO_THAANA = Font("noto-sans-thaana", "Noto Sans Thaana", "'Noto Sans Thaana'", None)


def font_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _css2_base(settings: Settings) -> str | None:
    """``https://host/css2`` when the configured Thaana stylesheet is a css2-style API."""
    url = settings.thaana_font_css_url
    if not url.startswith("https://"):
        return None
    parts = urlsplit(url)
    if not parts.path.endswith("/css2"):
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def thaana_fonts(settings: Settings) -> dict[str, Font]:
    base = _css2_base(settings)
    out: dict[str, Font] = {}
    for name in settings.thaana_fonts or list(DEFAULT_THAANA_FONTS):
        name = name.strip()[:80]
        if not name or not re.fullmatch(r"[A-Za-z0-9 ._-]+", name):
            continue
        css = f"{base}?family={quote_plus(name)}&display=swap" if base else None
        out[font_id(name)] = Font(font_id(name), name, f"'{name}'", css)
    out[NOTO_THAANA.id] = NOTO_THAANA
    return out


def default_thaana(settings: Settings) -> str:
    return next(iter(thaana_fonts(settings)))


def font_source(settings: Settings) -> str | None:
    """The host Thaana fonts come from, for the settings description (None: this site)."""
    base = _css2_base(settings)
    return urlsplit(base).netloc if base else None


def catalogue(settings: Settings) -> dict[str, list[dict[str, str | None]]]:
    def row(f: Font) -> dict[str, str | None]:
        return {"id": f.id, "name": f.name, "family": f.family, "cssUrl": f.css_url}

    return {
        "latin": [row(f) for f in LATIN.values()],
        "thaana": [row(f) for f in thaana_fonts(settings).values()],
    }
