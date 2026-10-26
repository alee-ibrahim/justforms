"""Form theme: how an organisation's forms look (docs/ux/FORM-THEME-SCREENS.md section 3).

An organisation stores defaults in ``organizations.settings["formTheme"]``; a form stores its
overrides in ``forms.settings["theme"]``. Both validate against :class:`FormTheme`, where every
value is optional: ``None`` (or missing) means *inherit* (form → organisation → JustForms'
defaults). :mod:`app.theme.resolve` turns the chain into concrete values, CSS variables and the
options pages need.

Not part of the versioned form schema: appearance changes apply to the live form when saved,
like the organisation's defaults. (The schema's legacy ``settings.theme.accent`` still counts as
the form's primary colour when the form sets none here.)
"""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
# A stored theme image (``theme/{org}/{ref}``) or "none" to switch an inherited image off.
ImageRef = Annotated[str, StringConstraints(pattern=r"^([0-9a-f]{16}\.webp|none)$")]
FontId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,59}$")]

LatinFont = Literal["inter", "atkinson", "ibm-plex-sans", "source-serif-4", "noto-sans"]
TextSize = Literal["s", "m", "l", "xl"]
HeadingScale = Literal["compact", "standard", "large"]
Radius = Literal["none", "small", "medium", "large"]
Density = Literal["compact", "comfortable", "roomy"]
ButtonStyle = Literal["filled", "outline"]
InputStyle = Literal["outlined", "filled", "underlined"]
PageWidth = Literal["narrow", "standard", "wide"]
ColorScheme = Literal["light", "dark", "auto"]
ProgressStyle = Literal["bar", "steps", "none"]
# Logical: "end" is the right edge in a left-to-right form, the left edge in a Dhivehi one.
LogoPlacement = Literal["start", "center", "end", "hidden"]
LogoSize = Literal["s", "m", "l"]

_LINK = re.compile(r"^https?://[^\s\x00-\x1f\x7f<>\"'`\\]+$", re.I)


def _check_link(value: str) -> str:
    """An absolute http(s) URL with a host: no other schemes (``javascript:``, ``data:``,
    ``mailto:``), no relative links, no whitespace or control characters."""
    if len(value) > 500 or not _LINK.match(value):
        raise ValueError("invalid_logo_link")
    try:
        host = urlsplit(value).hostname
    except ValueError:
        host = None
    if not host:
        raise ValueError("invalid_logo_link")
    return value


LogoLink = Annotated[str, AfterValidator(_check_link)]


class ThemeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class ThemeColors(ThemeModel):
    """Light-mode colours; dark values are generated. All checked for contrast (WCAG AA)."""

    primary: HexColor | None = None
    background: HexColor | None = None  # the page behind the sheet (the desk)
    surface: HexColor | None = None  # the sheet
    text: HexColor | None = None
    muted_text: HexColor | None = None
    border: HexColor | None = None
    error: HexColor | None = None


class FormTheme(ThemeModel):
    colors: ThemeColors = Field(default_factory=ThemeColors)
    latin_font: LatinFont | None = None
    thaana_font: FontId | None = None
    text_size: TextSize | None = None
    heading_scale: HeadingScale | None = None
    radius: Radius | None = None
    density: Density | None = None
    page_width: PageWidth | None = None
    button_style: ButtonStyle | None = None
    button_full_width: bool | None = None  # on phones
    input_style: InputStyle | None = None
    progress_style: ProgressStyle | None = None
    color_scheme: ColorScheme | None = None
    logo_placement: LogoPlacement | None = None
    logo_size: LogoSize | None = None
    logo_link: LogoLink | None = None  # where clicking the logo goes
    header_image: ImageRef | None = None
    background_image: ImageRef | None = None

    def dump(self) -> dict[str, object]:
        """Only the values that are set (inherit = absent)."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ResolvedTheme(ThemeModel):
    """Every value concrete, after inheritance."""

    latin_font: LatinFont = "inter"
    thaana_font: str = "faruma"
    text_size: TextSize = "m"
    heading_scale: HeadingScale = "standard"
    radius: Radius = "medium"
    density: Density = "comfortable"
    page_width: PageWidth = "standard"
    button_style: ButtonStyle = "filled"
    button_full_width: bool = True
    input_style: InputStyle = "outlined"
    progress_style: ProgressStyle = "bar"
    color_scheme: ColorScheme = "light"
    logo_placement: LogoPlacement = "start"
    logo_size: LogoSize = "m"
    logo_link: str | None = None
    header_image: str | None = None
    background_image: str | None = None
