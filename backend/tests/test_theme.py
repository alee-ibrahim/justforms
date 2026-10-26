"""Form themes: colour checks, inheritance and overrides, the stylesheet, the API and theme
images (docs/ux/FORM-THEME-SCREENS.md section 3)."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding.colors import contrast
from app.config import Settings
from app.models import Organization
from app.schemas.theme import FormTheme, ThemeColors
from app.theme import images
from app.theme.colors import AA, LIGHT, NON_TEXT, resolve_colors
from app.theme.fonts import catalogue, thaana_fonts
from app.theme.resolve import merge, resolve
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field, publish

# -- colours ---------------------------------------------------------------------------------


def test_no_choices_no_tokens() -> None:
    out = resolve_colors(ThemeColors())
    assert out.light == {} and out.dark == {} and out.adjustments == []


def test_pale_primary_is_darkened_and_reported() -> None:
    out = resolve_colors(ThemeColors(primary="#FFE45C"))
    used = out.light["--primary"]
    assert contrast(used, "#FFFFFF") >= AA and contrast(used, LIGHT["background"]) >= AA
    assert contrast(used, out.light["--primary-foreground"]) >= AA
    [adj] = out.adjustments
    assert adj.color == "primary" and adj.chosen == "#FFE45C" and adj.used == used
    # Dark mode gets a light primary that reads on the dark sheet.
    assert contrast(out.dark["--primary"], "#1A2038") >= AA


def test_neutrals_are_checked_on_sheet_and_page() -> None:
    out = resolve_colors(
        ThemeColors(background="#F5EFE6", surface="#FFFDF8", text="#9A9A9A", border="#EEEEEE")
    )
    light = out.light
    for key in ("--foreground", "--muted-foreground", "--destructive", "--primary"):
        assert contrast(light[key], light["--card"]) >= AA, key
        assert contrast(light[key], light["--background"]) >= AA, key
    # Input outlines come from the border colour, raised to 3:1.
    assert contrast(light["--input"], light["--card"]) >= NON_TEXT
    assert light["--border"] == "#EEEEEE"
    assert {a.color for a in out.adjustments} == {"text"}
    # Every light token has a dark twin, so the .dark block always wins.
    assert set(out.dark) == set(light)
    for key in ("--foreground", "--muted-foreground", "--primary"):
        assert contrast(out.dark[key], out.dark["--card"]) >= AA, key


def test_dark_sheet_chosen_for_light_mode_flips_direction() -> None:
    out = resolve_colors(ThemeColors(surface="#202020", background="#101010", text="#303030"))
    assert contrast(out.light["--foreground"], "#202020") >= AA
    assert contrast(out.light["--primary"], "#202020") >= AA


def test_brand_colour_is_the_inherited_primary() -> None:
    out = resolve_colors(ThemeColors(), brand_primary="#0F766E")
    assert out.light["--primary"] == "#0F766E"
    assert resolve_colors(ThemeColors(primary="#7C3AED"), "#0F766E").light["--primary"] == "#7C3AED"


# -- inheritance -----------------------------------------------------------------------------


def test_merge_form_overrides_win_per_value() -> None:
    org = FormTheme(
        colors=ThemeColors(primary="#0F766E", surface="#FFFDF8"),
        latin_font="inter",
        radius="large",
        color_scheme="auto",
    )
    form = FormTheme(colors=ThemeColors(primary="#7C3AED"), radius="none")
    merged = merge(org, form)
    assert merged.colors.primary == "#7C3AED" and merged.colors.surface == "#FFFDF8"
    assert merged.latin_font == "inter" and merged.radius == "none"
    assert merged.color_scheme == "auto"
    # Inheriting everything gives the organisation's values back.
    assert merge(org, FormTheme()) == org


def _org() -> Organization:
    return Organization(id=uuid.uuid4(), name="Example", slug="example", settings={})


def test_resolve_defaults_and_overrides() -> None:
    settings = Settings(environment="test")
    plain = resolve(settings, _org(), FormTheme())
    assert plain.resolved.latin_font == "inter" and plain.resolved.thaana_font == "faruma"
    assert plain.resolved.color_scheme == "light"
    assert plain.imports == []  # nothing beyond what every page loads
    assert plain.variables["--radius"] == "0.5rem"

    org = FormTheme(latin_font="atkinson", thaana_font="mv-faseyha", text_size="l", radius="none")
    form = FormTheme(thaana_font="mv-a-waheed", page_width="wide", header_image="none")
    result = resolve(settings, _org(), org, form)
    assert result.variables["--df-font-latin"] == "'Atkinson Hyperlegible Next Variable'"
    assert result.variables["--df-font-thaana"] == "'MV A Waheed'"
    assert result.variables["--df-text-scale"] == "1.125"
    assert result.variables["--df-page-width"] == "48rem"
    assert result.imports[0] == "/theme-fonts/atkinson.css"
    assert "family=MV+A+Waheed" in result.imports[1]
    assert result.options()["headerImageUrl"] is None


def test_unknown_thaana_font_falls_back_and_legacy_accent_counts() -> None:
    settings = Settings(environment="test", thaana_fonts=["Faruma"])
    result = resolve(settings, _org(), FormTheme(thaana_font="gone"), legacy_accent="#0F766E")
    assert result.resolved.thaana_font == "faruma"
    assert result.colors.light["--primary"] == "#0F766E"
    # A form's own primary beats the legacy accent.
    result = resolve(
        settings,
        _org(),
        FormTheme(),
        FormTheme(colors=ThemeColors(primary="#7C3AED")),
        legacy_accent="#0F766E",
    )
    assert result.colors.light["--primary"] == "#7C3AED"


def test_css_has_imports_root_and_dark_blocks() -> None:
    settings = Settings(environment="test")
    css = resolve(
        settings, _org(), FormTheme(latin_font="noto-sans", colors=ThemeColors(primary="#0F766E"))
    ).css()
    assert css.startswith('@import url("/theme-fonts/noto-sans.css");')
    assert ":root{--df-text-scale:1;" in css and "--primary:#0F766E" in css
    assert ".dark{--primary:" in css


def test_font_catalogue_follows_settings() -> None:
    settings = Settings(environment="test")
    fonts = catalogue(settings)
    assert [f["id"] for f in fonts["latin"]][:2] == ["inter", "atkinson"]
    assert fonts["thaana"][0]["name"] == "Faruma"
    assert fonts["thaana"][-1]["id"] == "noto-sans-thaana"
    # A self-hosted stylesheet: families come from /fonts/fonts.css, no per-family URLs.
    local = Settings(environment="test", thaana_font_css_url="/fonts/faruma.css")
    assert all(f.css_url is None for f in thaana_fonts(local).values())
    # Names that could break out of CSS are dropped.
    odd = Settings(environment="test", thaana_fonts=["Faruma", "x'); color: red"])
    assert list(thaana_fonts(odd)) == ["faruma", "noto-sans-thaana"]


# -- images ----------------------------------------------------------------------------------


def _png(w: int = 40, h: int = 20, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (15, 118, 110)).save(out, format=fmt)
    return out.getvalue()


def test_images_reencoded_as_webp() -> None:
    for fmt in ("PNG", "JPEG", "WEBP"):
        img = images.clean_image(_png(fmt=fmt))
        assert img.data[8:12] == b"WEBP" and (img.width, img.height) == (40, 20)
        assert images.REF.match(img.ref)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"", "bad_type"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "bad_type"),
        (b"GIF89a" + b"\0" * 20, "bad_type"),
        (b"\0" * (images.MAX_BYTES + 1), "too_large"),
    ],
    ids=["empty", "svg", "gif", "too-large"],
)
def test_images_refused(raw: bytes, code: str) -> None:
    with pytest.raises(images.ThemeImageError) as err:
        images.clean_image(raw)
    assert err.value.code == code


def test_images_too_many_pixels() -> None:
    with pytest.raises(images.ThemeImageError) as err:
        images.clean_image(_png(4097, 10))
    assert err.value.code == "too_large_pixels"


def test_storage_key_refuses_paths() -> None:
    with pytest.raises(images.ThemeImageError):
        images.storage_key(uuid.uuid4(), "../../etc/passwd")


# -- API -------------------------------------------------------------------------------------


async def test_org_theme_api(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    got = (await client.get(f"/api/v1/orgs/{org}/form-theme")).json()
    assert got["theme"] == {"colors": {}} and got["canEdit"] is True
    assert got["fonts"]["latin"][0]["id"] == "inter"

    body = {"colors": {"primary": "#FFE45C"}, "latinFont": "atkinson", "colorScheme": "auto"}
    res = await client.put(f"/api/v1/orgs/{org}/form-theme", json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["theme"] == body
    assert out["preview"]["adjustments"][0]["color"] == "primary"
    assert out["preview"]["options"]["colorScheme"] == "auto"

    bad = await client.put(f"/api/v1/orgs/{org}/form-theme", json={"thaanaFont": "nope"})
    assert bad.status_code == 422
    bad = await client.put(f"/api/v1/orgs/{org}/form-theme", json={"radius": "huge"})
    assert bad.status_code == 422
    bad = await client.put(f"/api/v1/orgs/{org}/form-theme", json={"colors": {"text": "red"}})
    assert bad.status_code == 422


async def test_form_override_and_public_stylesheet(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    await client.put(
        f"/api/v1/orgs/{org}/form-theme",
        json={"colors": {"primary": "#0F766E"}, "thaanaFont": "mv-faseyha", "radius": "large"},
    )
    pub = await publish(client, me, [field("name")], title="Themed")
    got = (await client.get(f"/api/v1/forms/{pub.id}/theme")).json()
    assert got["theme"] == {"colors": {}}
    assert got["organisation"]["theme"]["thaanaFont"] == "mv-faseyha"
    assert got["effective"]["radius"] == "large"

    res = await client.put(
        f"/api/v1/forms/{pub.id}/theme",
        json={"thaanaFont": "mv-a-waheed", "buttonStyle": "outline"},
    )
    assert res.status_code == 200, res.text
    eff = res.json()["effective"]
    assert eff["thaanaFont"] == "mv-a-waheed" and eff["radius"] == "large"

    live = (await client.get(pub.base)).json()
    brand = live["brand"]
    assert brand["themeUrl"].startswith("/api/v1/public/forms/themed/theme.css?v=")
    assert brand["theme"]["buttonStyle"] == "outline"
    assert brand["theme"]["colorScheme"] == "light"

    css = await client.get("/api/v1/public/forms/themed/theme.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert "--primary:#0F766E" in css.text and "'MV A Waheed'" in css.text
    assert "--radius:0.875rem" in css.text
    assert css.headers["cache-control"] == "no-cache"
    again = await client.get(
        "/api/v1/public/forms/themed/theme.css", headers={"If-None-Match": css.headers["etag"]}
    )
    assert again.status_code == 304
    versioned = await client.get(brand["themeUrl"])
    assert "immutable" in versioned.headers["cache-control"]
    empty = await client.get("/api/v1/public/forms/no-such/theme.css")
    assert empty.status_code == 200 and "--" not in empty.text

    # Back to inheriting everything.
    res = await client.put(f"/api/v1/forms/{pub.id}/theme", json={})
    assert res.json()["theme"] == {"colors": {}}
    assert res.json()["effective"]["thaanaFont"] == "mv-faseyha"


async def test_preview_uses_unsaved_values(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    res = await client.post(
        "/api/v1/themes/preview",
        json={
            "orgId": org,
            "organisation": {"colors": {"surface": "#FFFDF8"}, "radius": "none"},
            "form": {"radius": "small"},
        },
    )
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    assert out["light"]["--card"] == "#FFFDF8" and out["light"]["--radius"] == "0.25rem"
    assert out["dark"]["--card"] != "#FFFDF8"
    res = await client.post("/api/v1/themes/preview", json={"orgId": str(uuid.uuid4())})
    assert res.status_code == 404


async def test_theme_image_upload_and_serve(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    res = await client.put(
        f"/api/v1/orgs/{org}/theme-images", content=_png(), headers={"Content-Type": "image/png"}
    )
    assert res.status_code == 200, res.text
    img = res.json()
    got = await client.get(img["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp"
    assert "sandbox" in got.headers["content-security-policy"]
    bad = await client.put(f"/api/v1/orgs/{org}/theme-images", content=b"not an image")
    assert bad.status_code == 422 and bad.json()["detail"] == "bad_type"
    res = await client.put(f"/api/v1/orgs/{org}/form-theme", json={"headerImage": img["ref"]})
    assert res.json()["preview"]["options"]["headerImageUrl"] == img["url"]
    missing = await client.get(f"/api/v1/public/theme-images/{org}/{'0' * 16}.webp")
    assert missing.status_code == 404
