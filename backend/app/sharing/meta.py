"""The ``<head>`` tags of a public form page (docs/ux/SHARING-PREVIEW-SCREENS.md 1).

Link-preview crawlers don't run scripts, so the web server puts these tags into the public form
page before sending it: it asks the API (the same request that returns the form's allowed
framing sites) and swaps the page's placeholder ``<title>`` for the answer, which travels in a
response header. Header values must be ASCII, so every character outside ASCII is written as an
HTML character reference, and every value is HTML-escaped: titles and descriptions are user
text.
"""

from __future__ import annotations

import html

from app.sharing.image import HEIGHT, WIDTH
from app.sharing.service import META_DESCRIPTION_MAX, Preview, SitePreview, shorten


def _esc(value: str) -> str:
    text = " ".join(value.split())  # no line breaks or tabs: this travels in a header
    return html.escape(text, quote=True).encode("ascii", "xmlcharrefreplace").decode("ascii")


def _tags(
    *,
    title: str,
    description: str,
    site_name: str,
    url: str | None,
    image: str,
    image_alt: str,
    image_type: str,
    locale: str,
    size: tuple[int, int] = (WIDTH, HEIGHT),
) -> str:
    desc = shorten(description, META_DESCRIPTION_MAX) if description else ""
    out = [f"<title>{_esc(title)}</title>"]
    if desc:
        out.append(f'<meta name="description" content="{_esc(desc)}">')
    if url:
        out.append(f'<link rel="canonical" href="{_esc(url)}">')
    props = [
        ("og:type", "website"),
        ("og:site_name", site_name),
        ("og:title", title),
        *([("og:description", desc)] if desc else []),
        *([("og:url", url)] if url else []),
        ("og:locale", locale),
        ("og:image", image),
        ("og:image:type", image_type),
        ("og:image:width", str(size[0])),
        ("og:image:height", str(size[1])),
        ("og:image:alt", image_alt),
    ]
    out += [f'<meta property="{k}" content="{_esc(v)}">' for k, v in props]
    names = [
        ("twitter:card", "summary_large_image"),
        ("twitter:title", title),
        *([("twitter:description", desc)] if desc else []),
        ("twitter:image", image),
        ("twitter:image:alt", image_alt),
    ]
    out += [f'<meta name="{k}" content="{_esc(v)}">' for k, v in names]
    return "".join(out)


def form_head(preview: Preview, origin: str) -> str:
    custom = preview.custom
    return _tags(
        title=preview.title,
        description=preview.description,
        site_name=preview.site_name,
        url=preview.url,
        image=f"{origin}{preview.image_path}",
        image_alt=preview.title,
        image_type="image/jpeg" if custom is not None else "image/png",
        locale=preview.locale,
        size=(custom.width, custom.height) if custom and custom.width else (WIDTH, HEIGHT),
    )


def site_head(preview: SitePreview, origin: str) -> str:
    """Unknown and unpublished forms: the site's name and card only, nothing about the form."""
    return _tags(
        title=preview.site_name,
        description="",
        site_name=preview.site_name,
        url=None,
        image=f"{origin}{preview.image_path}",
        image_alt=preview.site_name,
        image_type="image/png",
        locale="en_US",
    )
