"""Organisation branding: colours, image cleaning, permissions, public endpoints, emails."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import service
from app.branding.colors import (
    AA,
    DARK_DESK,
    DARK_SHEET,
    LIGHT_DESK,
    LIGHT_SHEET,
    contrast,
    palette,
)
from app.branding.images import BrandImageError, clean_image
from app.config import Settings
from app.email import sender
from app.models import Organization, User
from app.notifications.emails import EmailBrand, code_message
from app.services.users import create_admin, ensure_default_org
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client, field, publish


def png(w: int = 128, h: int = 128, color: str = "#0F766E") -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(out, format="PNG")
    return out.getvalue()


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#0F766E"/></svg>'  # noqa: E501


# -- colours ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chosen", ["#0F766E", "#FACC15", "#FFFFFF", "#000000", "#3B3FC1", "#22C55E"]
)
def test_palette_meets_aa_in_both_modes(chosen: str) -> None:
    pal = palette(chosen)
    assert (
        min(contrast(pal.light.primary, LIGHT_SHEET), contrast(pal.light.primary, LIGHT_DESK)) >= AA
    )
    assert min(contrast(pal.dark.primary, DARK_SHEET), contrast(pal.dark.primary, DARK_DESK)) >= AA
    assert contrast(pal.light.primary, pal.light.foreground) >= AA
    assert contrast(pal.dark.primary, pal.dark.foreground) >= AA


def test_palette_reports_adjustment() -> None:
    ok = palette("#0f766e")
    assert ok.chosen == "#0F766E" and not ok.adjusted and ok.warnings == []
    light = palette("#FACC15")  # yellow: unreadable on white, must be darkened
    assert light.adjusted and "darkened_for_contrast" in light.warnings
    assert light.light.primary != "#FACC15" and light.report()["adjusted"] is True
    css = ok.css()
    assert css.startswith(":root{--primary:#0F766E;") and ".dark{--primary:" in css


def test_palette_rejects_bad_hex() -> None:
    with pytest.raises(ValueError):
        palette("teal")


# -- images -----------------------------------------------------------------------------------


def test_png_is_reencoded_and_checked() -> None:
    img = clean_image("logo", png(300, 64))
    assert img.mime == "image/png" and (img.width, img.height) == (300, 64)
    with pytest.raises(BrandImageError) as e:
        clean_image("icon", png(300, 64))
    assert e.value.code == "not_square"
    with pytest.raises(BrandImageError) as e:
        clean_image("icon", png(32, 32))
    assert e.value.code == "icon_size"
    with pytest.raises(BrandImageError) as e:
        clean_image("logo", b"GIF89a" + b"\0" * 64)
    assert e.value.code == "bad_type"
    with pytest.raises(BrandImageError) as e:
        clean_image("logo", b"\x89PNG\r\n\x1a\n" + b"\0" * (600 * 1024))
    assert e.value.code == "too_large"


def test_clean_svg_passes_through() -> None:
    img = clean_image("icon", SVG)
    assert img.mime == "image/svg+xml" and (img.width, img.height) == (64, 64)
    assert b"<rect" in img.data and b"<script" not in img.data


@pytest.mark.parametrize(
    "bad",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>alert(1)</script></svg>',  # noqa: E501
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1 1"><use xlink:href="https://evil.example/x.svg#a"/></svg>',  # noqa: E501
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><foreignObject><p>x</p></foreignObject></svg>',  # noqa: E501
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>rect{fill:red}</style></svg>',  # noqa: E501
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect style="fill:url(https://evil.example/a)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><a href="javascript:alert(1)"><rect/></a></svg>',  # noqa: E501
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="data:image/png;base64,AA"/></svg>',  # noqa: E501
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">&x;</svg>',  # noqa: E501
    ],
)
def test_unsafe_svg_is_refused(bad: bytes) -> None:
    with pytest.raises(BrandImageError) as e:
        clean_image("logo", bad)
    assert e.value.code == "svg_unsafe"


def test_svg_local_references_are_allowed() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        b'<linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient></defs>'
        b'<rect width="10" height="10" fill="url(#g)"/></svg>'
    )
    assert b'fill="url(#g)"' in clean_image("logo", svg).data


# -- resolution and emails ----------------------------------------------------------------------


def test_fallbacks_without_branding(tmp_path: Path) -> None:
    settings = Settings(environment="test", public_url="http://testserver")
    org = Organization(name="JustForms", slug="default", settings={})
    brand = service.resolve(settings, org)
    assert brand.name == "JustForms" and not brand.custom and brand.palette is None
    assert brand.public()["themeUrl"] is None and brand.powered_by
    logo = tmp_path / "logo.svg"
    logo.write_bytes(SVG)
    inst = Settings(
        environment="test",
        brand_name="Example Forms",
        brand_primary_color="#0F766E",
        brand_logo_file=logo,
        brand_powered_by="always",
    )
    brand = service.resolve(inst, org)
    assert brand.name == "Example Forms" and brand.custom and brand.primary == "#0F766E"
    assert brand.images["logo"].mime == "image/svg+xml" and not brand.can_hide_powered_by
    org.settings = {"branding": {"displayName": "Example Office", "hidePoweredBy": True}}
    brand = service.resolve(inst, org)
    assert brand.name == "Example Office" and brand.powered_by  # the instance forces it


def test_email_sender_and_brand_footer() -> None:
    assert sender("JustForms <no-reply@example.org>", None) == "JustForms <no-reply@example.org>"
    assert (
        sender("JustForms <no-reply@example.org>", "Example\r\nOffice")
        == "Example Office <no-reply@example.org>"
    )
    brand = EmailBrand(
        name="Example Office",
        logo_url="http://testserver/api/v1/public/branding/default/logo?v=1",
        support_url="https://example.org/help",
        custom=True,
        button_bg="#0F766E",
    )
    msg = code_message(
        org_name="x", title="T", language="en", code="123456", minutes=10, brand=brand
    )
    assert msg.from_name == "Example Office"
    assert (
        msg.html and 'src="http://testserver/api/v1/public/branding/default/logo?v=1"' in msg.html
    )
    assert "Sent by Example Office." in msg.html and "Powered by JustForms." in msg.html
    assert "Get help: https://example.org/help" in msg.text


# -- API --------------------------------------------------------------------------------------


async def test_branding_permissions_and_upload(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    org_id = me["orgs"][0]["id"]
    url = f"/api/v1/orgs/{org_id}/branding"
    res = await client.get(url)
    assert (
        res.status_code == 200
        and res.json()["canEdit"]
        and res.json()["effective"]["custom"] is False
    )

    res = await client.put(url, json={"primaryColor": "teal"})
    assert res.status_code == 422
    res = await client.put(url, json={"supportUrl": "javascript:alert(1)"})
    assert res.status_code == 422
    res = await client.put(
        url,
        json={
            "displayName": "Example Youth Office",
            "primaryColor": "#0f766e",
            "supportUrl": "https://example.org/help",
            "hidePoweredBy": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["primaryColor"] == "#0F766E" and body["effective"]["name"] == "Example Youth Office"
    assert body["palette"]["light"]["contrast"] >= AA

    res = await client.put(
        f"{url}/images/logo", content=png(300, 64), headers={"Content-Type": "image/png"}
    )
    assert res.status_code == 200, res.text
    logo_url = res.json()["images"]["logo"]["url"]
    res = await client.put(
        f"{url}/images/icon", content=png(300, 64), headers={"Content-Type": "image/png"}
    )
    assert res.status_code == 422 and res.json()["detail"] == "not_square"
    bad = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>x</script></svg>'
    res = await client.put(
        f"{url}/images/icon", content=bad, headers={"Content-Type": "image/svg+xml"}
    )
    assert res.status_code == 422 and res.json()["detail"] == "svg_unsafe"
    res = await client.put(
        f"{url}/images/icon", content=SVG, headers={"Content-Type": "image/svg+xml"}
    )
    assert res.status_code == 200

    # Images and the theme come from this origin, sandboxed and cacheable.
    res = await client.get(logo_url)
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert "sandbox" in res.headers["content-security-policy"]
    assert (
        res.headers["x-content-type-options"] == "nosniff"
        and "immutable" in res.headers["cache-control"]
    )
    pub = (await client.get("/api/v1/public/branding/default")).json()
    assert pub["name"] == "Example Youth Office" and pub["poweredBy"] is False
    theme = await client.get(pub["themeUrl"])
    assert theme.status_code == 200 and "--primary:#0F766E" in theme.text
    manifest = (await client.get(pub["manifestUrl"])).json()
    assert (
        manifest["name"] == "Example Youth Office"
        and manifest["icons"][0]["type"] == "image/svg+xml"
    )
    # The sign-in page (no organisation) uses the default organisation.
    assert (await client.get("/api/v1/public/branding/_")).json()["name"] == "Example Youth Office"
    assert (await client.get("/api/v1/public/branding/no-such-org")).status_code == 404

    # Public form, PDF-bound and approver responses carry the effective branding.
    pubform = await publish(client, me, [field("name")])
    live = (await client.get(pubform.base)).json()
    assert live["orgName"] == "Example Youth Office" and live["brand"]["logoUrl"] == logo_url

    res = await client.delete(f"{url}/images/logo")
    assert res.status_code == 200 and res.json()["images"]["logo"] is None
    assert (await client.get(logo_url)).status_code == 404

    # Members read; only admins change.
    org = await db.get(Organization, org_id)
    assert org is not None
    db.add(User(email="member@example.org"))
    await db.commit()
    async with make_client(app) as admin2:
        await login(admin2, queue, me["email"])
        res = await admin2.post(
            f"/api/v1/orgs/{org_id}/members", json={"email": "member@example.org"}
        )
        assert res.status_code in (200, 201)
    async with make_client(app) as member:
        await login(member, queue, "member@example.org")
        res = await member.get(url)
        assert res.status_code == 200 and res.json()["canEdit"] is False
        assert (await member.put(url, json={"displayName": "Mine"})).status_code == 403
        res = await member.put(
            f"{url}/images/logo", content=png(), headers={"Content-Type": "image/png"}
        )
        assert res.status_code == 403
    async with make_client(app) as anon:
        assert (await anon.get(url)).status_code == 401


async def test_outsiders_cannot_read_branding_settings(
    app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "root@example.org")
    org = await ensure_default_org(db, settings)
    db.add(User(email="guest@example.org"))
    await db.commit()
    async with make_client(app) as c:
        await login(c, queue, "guest@example.org")
        assert (await c.get(f"/api/v1/orgs/{org.id}/branding")).status_code == 404
        assert (await c.get("/api/v1/branding/palette?color=%230F766E")).status_code == 200
        assert (await c.get("/api/v1/branding/palette?color=red")).status_code == 422


@pytest.mark.parametrize("logo", [png(300, 64), SVG, None])
def test_pdf_header_with_logo(logo: bytes | None) -> None:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from app.pdf.render import PdfInput, render_pdf
    from app.schemas.form import Form

    form = Form.model_validate(
        {
            "settings": {"title": "Application", "language": "en"},
            "pages": [{"id": "p1", "elements": [field("name")]}],
        }
    )
    pdf = render_pdf(
        PdfInput(
            org_name="Example Office",
            form_title="Application",
            form=form,
            version=1,
            schema_hash="x",
            submission_id="00000000-0000-0000-0000-000000000000",
            seq=1,
            submitted_at=datetime(2026, 10, 23, tzinfo=UTC),
            data={"name": "Aminath"},
            content_hash="y",
            chain_head=None,
            tz=ZoneInfo("UTC"),
            verify_url="http://testserver/v/token",
            logo=logo,
            logo_size=(300, 64) if logo and logo.startswith(b"\x89PNG") else (64, 64),
            show_brand=True,
        )
    )
    assert pdf.startswith(b"%PDF")
    if logo is None:
        assert b"Example Office" in pdf or len(pdf) > 1000


async def test_sign_in_code_email_uses_the_default_organisation_brand(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await client.put(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/branding", json={"displayName": "Example Office"}
    )
    assert res.status_code == 200
    await client.post("/api/v1/auth/local/request", json={"email": me["email"]})
    function, kwargs = queue.jobs[-1]
    assert function == "send_email" and kwargs["from_name"] == "Example Office"
    assert kwargs["subject"] == "Your Example Office sign-in code"
