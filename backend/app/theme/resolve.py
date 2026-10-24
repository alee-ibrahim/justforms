"""Form theme inheritance and output (docs/ux/FORM-THEME-SCREENS.md sections 3.1 and 3.5).

Chain, most specific first: the form's overrides (``forms.settings["theme"]``), the legacy
``settings.theme.accent`` of the form's live schema (primary only), the organisation's form
theme (``organizations.settings["formTheme"]``), the organisation's brand colour (primary
only), JustForms' defaults.

The result becomes:

- a stylesheet (``:root`` and ``.dark`` blocks of CSS variables plus ``@import``s of the chosen
  fonts) for the public form, approver and verify pages;
- the same variables as JSON for the studio's canvas and live previews;
- options that need markup (button and input style, progress, logo position, size, link and
  image, header image, colour mode), sent with the page data.

The logo in the options is the effective one for the form: its own logo
(``forms.settings["logo"]``, :mod:`app.theme.logo`) when it has one, else the organisation's
brand logo. It is part of the options so the theme version changes with it.

Every value in the CSS comes from validated enums, hex colours, the font catalogue or URLs
built here, never from free text.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.branding.service import resolve as resolve_brand
from app.config import Settings
from app.models import FormRecord, Organization
from app.schemas.theme import FormTheme, ResolvedTheme, ThemeColors
from app.theme.colors import ColorTokens, resolve_colors
from app.theme.fonts import LATIN, default_thaana, thaana_fonts
from app.theme.logo import FormLogo, form_logo

log = logging.getLogger(__name__)

ORG_KEY = "formTheme"
FORM_KEY = "theme"

TEXT_SCALE = {"s": "0.9375", "m": "1", "l": "1.125", "xl": "1.25"}
HEADING_SCALE = {"compact": "0.875", "standard": "1", "large": "1.15"}
RADIUS = {"none": "0rem", "small": "0.25rem", "medium": "0.5rem", "large": "0.875rem"}
GAP = {"compact": "1.5rem", "comfortable": "2rem", "roomy": "2.75rem"}
WIDTH = {"narrow": "34rem", "standard": "40rem", "wide": "48rem"}


def _load(raw: object, where: str) -> FormTheme:
    if not isinstance(raw, dict):
        return FormTheme()
    try:
        return FormTheme.model_validate(raw)
    except ValidationError:
        log.warning("ignoring an invalid stored form theme (%s)", where)
        return FormTheme()


def org_theme(org: Organization | None) -> FormTheme:
    return _load((org.settings or {}).get(ORG_KEY) if org else None, "organisation")


def form_theme(form: FormRecord | None) -> FormTheme:
    return _load((form.settings or {}).get(FORM_KEY) if form else None, "form")


def merge(*layers: FormTheme) -> FormTheme:
    """Later layers win for every value they set."""
    data: dict[str, Any] = {}
    colors: dict[str, Any] = {}
    for layer in layers:
        dumped = layer.model_dump(exclude_none=True, by_alias=False)
        colors.update(dumped.pop("colors", {}))
        data.update(dumped)
    return FormTheme.model_validate({**data, "colors": ThemeColors.model_validate(colors)})


def image_url(org_id: uuid.UUID, ref: str | None) -> str | None:
    if not ref or ref == "none":
        return None
    return f"/api/v1/public/theme-images/{org_id}/{ref}"


def _css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "") + '"'


@dataclass
class ThemeResult:
    org_id: uuid.UUID
    chosen: FormTheme  # the merged choices (what the settings show as effective)
    resolved: ResolvedTheme
    colors: ColorTokens
    variables: dict[str, str]
    imports: list[str]
    # The effective logo: the form's own (dark None) or the organisation brand's.
    logo_url: str | None = None
    logo_dark_url: str | None = None
    own_logo: FormLogo | None = field(default=None)

    def image(self, which: str) -> str | None:
        return image_url(self.org_id, getattr(self.resolved, which))

    def light(self) -> dict[str, str]:
        return {**self.variables, **self.colors.light}

    def dark(self) -> dict[str, str]:
        return {**self.variables, **self.colors.dark}

    def css(self) -> str:
        def block(selector: str, tokens: dict[str, str]) -> str:
            return selector + "{" + ";".join(f"{k}:{v}" for k, v in tokens.items()) + "}\n"

        out = "".join(f"@import url({_css_string(u)});\n" for u in self.imports)
        out += block(":root", self.light())
        if self.colors.dark:
            out += block(".dark", self.colors.dark)
        return out

    @property
    def version(self) -> str:
        options = self.options()
        return hashlib.sha256((self.css() + repr(sorted(options.items()))).encode()).hexdigest()[
            :12
        ]

    def options(self) -> dict[str, Any]:
        """What pages need beyond CSS variables (``data-df-*`` attributes, images)."""
        r = self.resolved
        return {
            "colorScheme": r.color_scheme,
            "buttonStyle": r.button_style,
            "buttonFullWidth": r.button_full_width,
            "inputStyle": r.input_style,
            "progressStyle": r.progress_style,
            "logoPlacement": r.logo_placement,
            "logoSize": r.logo_size,
            "logoLink": r.logo_link,
            "logoUrl": self.logo_url,
            "logoDarkUrl": self.logo_dark_url,
            "logoOwn": self.own_logo is not None,
            "headerImageUrl": self.image("header_image"),
            "backgroundImageUrl": self.image("background_image"),
        }

    def report(self) -> dict[str, Any]:
        """The studio's view: tokens for both modes, fonts to load, options, adjustments."""
        return {
            "light": self.light(),
            "dark": self.dark(),
            "fonts": self.imports,
            "options": self.options(),
            "resolved": self.resolved.model_dump(mode="json", by_alias=True),
            "adjustments": [a.as_dict() for a in self.colors.adjustments],
        }


def resolve(
    settings: Settings,
    org: Organization,
    *layers: FormTheme,
    legacy_accent: str | None = None,
    own_logo: FormLogo | None = None,
) -> ThemeResult:
    """The theme for ``org`` with ``layers`` on top (organisation defaults are not implied:
    pass ``org_theme(org)`` first, then the form's overrides). ``own_logo``: the form's own
    logo, which replaces the organisation's."""
    chosen = merge(*layers)
    colors = chosen.colors
    if legacy_accent and not any(layer.colors.primary for layer in layers[1:]):
        colors = colors.model_copy(update={"primary": legacy_accent})
    brand = resolve_brand(settings, org)
    tokens = resolve_colors(colors, brand.primary)

    thaana = thaana_fonts(settings)
    values = chosen.model_dump(exclude_none=True, exclude={"colors"}, by_alias=False)
    if values.get("thaana_font") not in thaana:
        values["thaana_font"] = default_thaana(settings)
    for key in ("header_image", "background_image"):
        if values.get(key) == "none":
            values[key] = None
    resolved = ResolvedTheme.model_validate(values)

    latin = LATIN[resolved.latin_font]
    thaana_font = thaana[resolved.thaana_font]
    variables = {
        "--df-text-scale": TEXT_SCALE[resolved.text_size],
        "--df-heading-scale": HEADING_SCALE[resolved.heading_scale],
        "--radius": RADIUS[resolved.radius],
        "--df-gap": GAP[resolved.density],
        "--df-page-width": WIDTH[resolved.page_width],
        "--df-font-latin": latin.family,
        "--df-font-thaana": thaana_font.family,
    }
    bg = image_url(org.id, resolved.background_image)
    if bg:
        variables["--df-desk-image"] = f"url({_css_string(bg)})"
    imports = [u for u in (latin.css_url, thaana_font.css_url) if u]
    # The default Thaana stylesheet is already linked by every page.
    if thaana_font.css_url == settings.thaana_font_css_url:
        imports = [u for u in imports if u != settings.thaana_font_css_url]
    logo_url: str | None
    logo_dark_url: str | None
    if own_logo is not None:
        logo_url, logo_dark_url = own_logo.url, None
    else:
        logo_url, logo_dark_url = brand.image_url("logo"), brand.image_url("logo_dark")
    return ThemeResult(
        org.id,
        chosen,
        resolved,
        tokens,
        variables,
        imports,
        logo_url=logo_url,
        logo_dark_url=logo_dark_url,
        own_logo=own_logo,
    )


def legacy_accent(schema: dict[str, Any] | None) -> str | None:
    accent = ((schema or {}).get("settings", {}).get("theme") or {}).get("accent")
    return accent if isinstance(accent, str) else None


def for_form(
    settings: Settings, org: Organization, form: FormRecord, schema: dict[str, Any] | None
) -> ThemeResult:
    return resolve(
        settings,
        org,
        org_theme(org),
        form_theme(form),
        legacy_accent=legacy_accent(schema),
        own_logo=form_logo(form),
    )


def form_email_brand(
    settings: Settings, org: Organization | None, form: FormRecord, schema: dict[str, Any] | None
) -> Any:
    """``email_brand`` with the button in the form theme's primary colour and the form's own
    logo when it is a PNG (mail clients don't show SVG: an SVG form logo falls back to the
    organisation's PNG logo or icon, as without one)."""
    from dataclasses import replace

    from app.branding.service import email_brand

    eb = email_brand(settings, resolve_brand(settings, org))
    own = form_logo(form)
    if own is not None and own.is_png:
        eb = replace(eb, logo_url=f"{settings.public_origin}{own.url}")
    if org is None:
        return eb
    colors = for_form(settings, org, form, schema).colors
    if not colors.light:
        return eb
    return replace(eb, button_bg=colors.primary, button_fg=colors.primary_foreground)


def page_brand(
    settings: Settings, org: Organization | None, form: FormRecord, schema: dict[str, Any] | None
) -> dict[str, Any]:
    """``brand`` for a form's public pages: the organisation's branding, with the form's own
    logo (if any) in place of the organisation's, the form's theme stylesheet as ``themeUrl``
    and its options as ``theme``."""
    brand = resolve_brand(settings, org).public()
    own = form_logo(form)
    if own is not None:
        brand = {**brand, "logoUrl": own.url, "logoDarkUrl": None}
    if org is None:
        return brand
    theme = for_form(settings, org, form, schema)
    return {
        **brand,
        "themeUrl": f"/api/v1/public/forms/{form.slug}/theme.css?v={theme.version}",
        "theme": theme.options(),
    }
