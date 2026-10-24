"""A form's own logo: upload and removal, permissions, public serving, theme options, the public
pages, emails and the signed PDF (docs/ux/FORM-THEME-SCREENS.md section 3)."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRecord, FormRole, Organization, Submission, User
from app.pdf.render import PdfInput, logo_box, render_pdf
from app.schemas.form import Form
from app.schemas.theme import FormTheme
from app.storage import Storage
from app.theme import logo as form_logos
from app.theme.resolve import form_email_brand, page_brand, resolve
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client, field, publish


def png(w: int = 200, h: int = 80, color: str = "#0F766E") -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(out, format="PNG")
    return out.getvalue()


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40"><rect width="120" height="40" fill="#7C3AED"/></svg>'  # noqa: E501
BAD_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>alert(1)</script></svg>'
)
PNG_HEADERS = {"Content-Type": "image/png"}
SVG_HEADERS = {"Content-Type": "image/svg+xml"}


# -- theme values ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link", ["https://example.org", "http://example.org/about?x=1", "https://example.org/a#b"]
)
def test_logo_link_accepts_http_and_https(link: str) -> None:
    assert FormTheme.model_validate({"logoLink": link}).logo_link == link


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,hi",
        "mailto:office@example.org",
        "/relative/path",
        "//example.org/x",
        "example.org",
        "https://",
        "https://example.org/a b",
        "https://example.org/\nx",
        "ftp://example.org/x",
        "https://example.org/" + "a" * 500,
    ],
)
def test_logo_link_refuses_other_links(link: str) -> None:
    with pytest.raises(ValidationError):
        FormTheme.model_validate({"logoLink": link})


def test_logo_size_and_end_placement() -> None:
    theme = FormTheme.model_validate({"logoSize": "l", "logoPlacement": "end"})
    assert theme.dump() == {"colors": {}, "logoSize": "l", "logoPlacement": "end"}
    with pytest.raises(ValidationError):
        FormTheme.model_validate({"logoSize": "xl"})
    with pytest.raises(ValidationError):
        FormTheme.model_validate({"logoPlacement": "right"})


def _org(settings: dict[str, Any] | None = None) -> Organization:
    return Organization(id=uuid.uuid4(), name="Example", slug="example", settings=settings or {})


def _form(org: Organization, logo: dict[str, Any] | None = None) -> FormRecord:
    form_id = uuid.uuid4()
    settings: dict[str, Any] = {}
    if logo is not None:
        settings["logo"] = {**logo, "key": logo.get("key") or _key(form_id, logo)}
    return FormRecord(id=form_id, org_id=org.id, slug="example-form", title="F", settings=settings)


def _key(form_id: uuid.UUID, logo: dict[str, Any]) -> str:
    ext = "png" if logo["mime"] == "image/png" else "svg"
    return f"form-logos/{form_id}/{logo['sha'][:16]}.{ext}"


PNG_LOGO = {"mime": "image/png", "sha": "a" * 64, "width": 200, "height": 80}
SVG_LOGO = {"mime": "image/svg+xml", "sha": "b" * 64, "width": 120, "height": 40}
ORG_LOGOS = {
    "branding": {
        "images": {
            kind: {"key": f"branding/x/{kind}.png", "mime": "image/png", "sha": "c" * 64}
            for kind in ("logo", "logo_dark")
        }
    }
}


def test_options_defaults_and_org_logo() -> None:
    settings = Settings(environment="test")
    plain = resolve(settings, _org(), FormTheme()).options()
    assert plain["logoSize"] == "m" and plain["logoLink"] is None
    assert plain["logoUrl"] is None and plain["logoDarkUrl"] is None
    assert plain["logoOwn"] is False

    org = _org(ORG_LOGOS)
    result = resolve(settings, org, FormTheme(logo_link="https://example.org", logo_size="s"))
    opts = result.options()
    assert opts["logoUrl"].startswith("/api/v1/public/branding/example/logo?v=")
    assert opts["logoDarkUrl"].startswith("/api/v1/public/branding/example/logo_dark?v=")
    assert opts["logoLink"] == "https://example.org" and opts["logoSize"] == "s"


def test_form_logo_replaces_the_organisation_logo() -> None:
    from app.theme.resolve import for_form

    settings = Settings(environment="test")
    org = _org(ORG_LOGOS)
    form = _form(org, PNG_LOGO)
    before = for_form(settings, org, _form(org), None)
    result = for_form(settings, org, form, None)
    opts = result.options()
    assert opts["logoUrl"] == f"/api/v1/public/form-logos/{form.id}/{'a' * 16}.png"
    assert opts["logoDarkUrl"] is None and opts["logoOwn"] is True
    # The logo is part of the version, so cached stylesheets and pages move on.
    assert result.version != before.version

    brand = page_brand(settings, org, form, None)
    assert brand["logoUrl"] == opts["logoUrl"] and brand["logoDarkUrl"] is None
    assert brand["theme"]["logoOwn"] is True
    org_brand = page_brand(settings, org, _form(org), None)
    assert org_brand["logoUrl"].startswith("/api/v1/public/branding/")
    assert org_brand["logoDarkUrl"] is not None


def test_logo_of_another_form_is_ignored() -> None:
    org = _org()
    other = uuid.uuid4()
    form = _form(org, {**PNG_LOGO, "key": f"form-logos/{other}/{'a' * 16}.png"})
    assert form_logos.form_logo(form) is None
    assert form_logos.form_logo(_form(org, {**PNG_LOGO, "mime": "text/html"})) is None


def test_email_logo_png_form_logo_and_svg_fallback() -> None:
    settings = Settings(environment="test", public_url="https://forms.example.org")
    org = _org(ORG_LOGOS)
    png_form = _form(org, PNG_LOGO)
    eb = form_email_brand(settings, org, png_form, None)
    assert eb.logo_url == (
        f"https://forms.example.org/api/v1/public/form-logos/{png_form.id}/{'a' * 16}.png"
    )
    # Mail clients don't show SVG: the organisation's PNG logo is used instead.
    svg = form_email_brand(settings, org, _form(org, SVG_LOGO), None)
    assert svg.logo_url and "/api/v1/public/branding/example/logo?v=" in svg.logo_url
    plain = form_email_brand(settings, _org(), _form(_org(), SVG_LOGO), None)
    assert plain.logo_url is None


# -- PDF -------------------------------------------------------------------------------------


def _pdf_input(**extra: Any) -> PdfInput:
    language = extra.pop("language", "en")
    form = Form.model_validate(
        {
            "settings": {"title": "Application", "language": language},
            "pages": [{"id": "p1", "elements": [field("name")]}],
        }
    )
    return PdfInput(
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
        **extra,
    )


def test_pdf_logo_size_and_placement() -> None:
    page_w, margin = 210.0, 18.0
    wide: dict[str, Any] = {"logo": b"x", "logo_size": (400, 40)}
    tall: dict[str, Any] = {"logo": b"x", "logo_size": (100, 100)}

    def box(rtl: bool = False, **kw: Any) -> tuple[float, float, float]:
        return logo_box(_pdf_input(**kw), page_w, margin, margin, rtl)

    # Height by size (square logo); "m" keeps the long-standing 9 mm.
    assert [round(box(**tall, logo_scale=s)[2], 2) for s in ("s", "m", "l")] == [7.0, 9.0, 13.0]
    # Wide logos are capped in width.
    assert box(**wide)[1] == 60.0 and box(**wide, logo_scale="l")[1] == 80.0
    x, w, _h = box(**tall)
    assert x == margin  # start = left in LTR
    assert box(rtl=True, **tall)[0] == page_w - margin - w  # start = right in RTL
    assert box(**tall, logo_placement="end")[0] == page_w - margin - w
    assert box(rtl=True, **tall, logo_placement="end")[0] == margin
    assert box(**tall, logo_placement="center")[0] == (page_w - w) / 2


@pytest.mark.parametrize("placement", ["start", "center", "end", "hidden"])
@pytest.mark.parametrize("language", ["en", "dv"])
def test_pdf_renders_with_every_placement(placement: str, language: str) -> None:
    pdf = render_pdf(
        _pdf_input(
            language=language,
            logo=png(300, 64),
            logo_size=(300, 64),
            logo_scale="l",
            logo_placement=placement,
            show_brand=True,
        )
    )
    assert pdf.startswith(b"%PDF")
    with_svg = render_pdf(_pdf_input(logo=SVG, logo_size=(120, 40), logo_placement=placement))
    assert with_svg.startswith(b"%PDF")


def test_pdf_hidden_logo_is_not_drawn() -> None:
    shown = render_pdf(_pdf_input(logo=png(300, 64), logo_size=(300, 64)))
    hidden = render_pdf(_pdf_input(logo=png(300, 64), logo_size=(300, 64), logo_placement="hidden"))
    assert b"/Subtype /Image" in shown and b"/Subtype /Image" not in hidden


# -- API -------------------------------------------------------------------------------------


async def test_upload_replace_and_revert(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], title="Logo form")
    url = f"/api/v1/forms/{pub.id}/logo"
    got = (await client.get(f"/api/v1/forms/{pub.id}/theme")).json()
    assert got["logo"] is None and got["preview"]["options"]["logoOwn"] is False

    res = await client.put(url, content=png(), headers=PNG_HEADERS)
    assert res.status_code == 200, res.text
    out = res.json()
    first = out["logo"]
    assert first["mime"] == "image/png" and (first["width"], first["height"]) == (200, 80)
    assert first["url"].startswith(f"/api/v1/public/form-logos/{pub.id}/")
    assert out["preview"]["options"]["logoUrl"] == first["url"]
    assert out["preview"]["options"]["logoOwn"] is True
    assert out["canEdit"] is True

    # Served sandboxed, readable cross-origin (mail clients), cached for a year.
    img = await client.get(first["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    csp = img.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp
    assert img.headers["x-content-type-options"] == "nosniff"
    assert img.headers["cross-origin-resource-policy"] == "cross-origin"
    assert "immutable" in img.headers["cache-control"]

    # The public form shows it (no dark variant).
    live = (await client.get(pub.base)).json()
    assert live["brand"]["logoUrl"] == first["url"] and live["brand"]["logoDarkUrl"] is None
    assert live["brand"]["theme"]["logoUrl"] == first["url"]

    # Replacing stores the new file and removes the old one.
    res = await client.put(url, content=SVG, headers=SVG_HEADERS)
    assert res.status_code == 200, res.text
    second = res.json()["logo"]
    assert second["mime"] == "image/svg+xml" and second["url"].endswith(".svg")
    svg = await client.get(second["url"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert (await client.get(first["url"])).status_code == 404
    form = await db.get(FormRecord, uuid.UUID(pub.id))
    assert form is not None
    await db.refresh(form)
    key = form.settings["logo"]["key"]
    assert await file_storage.exists(key)

    # Back to the organisation's logo.
    res = await client.delete(url)
    assert res.status_code == 200 and res.json()["logo"] is None
    assert res.json()["preview"]["options"]["logoOwn"] is False
    assert not await file_storage.exists(key)
    live = (await client.get(pub.base)).json()
    assert live["brand"]["logoUrl"] is None


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (BAD_SVG, 422, "svg_unsafe"),
        (b"GIF89a not a logo", 422, "bad_type"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', 422, "svg_no_size"),
        (png(4100, 10), 422, "too_large_pixels"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * (512 * 1024 + 1), 413, "too_large"),
    ],
    ids=["svg_unsafe", "bad_type", "svg_no_size", "too_large_pixels", "too_large"],
)
async def test_upload_refused(
    body: bytes,
    status: int,
    code: str,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    res = await client.put(f"/api/v1/forms/{pub.id}/logo", content=body)
    assert res.status_code == status and res.json()["detail"] == code
    assert (await client.get(f"/api/v1/forms/{pub.id}/theme")).json()["logo"] is None


async def test_logo_permissions(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    url = f"/api/v1/forms/{pub.id}/logo"
    for role in ("viewer", "editor"):
        user = User(email=f"{role}@example.org")
        db.add(user)
        await db.flush()
        db.add(FormPermission(form_id=pub.id, user_id=user.id, role=FormRole(role)))
    db.add(User(email="outsider@example.org"))
    await db.commit()

    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        theme = await viewer.get(f"/api/v1/forms/{pub.id}/theme")
        assert theme.status_code == 200 and theme.json()["canEdit"] is False
        assert (await viewer.put(url, content=png(), headers=PNG_HEADERS)).status_code == 403
        assert (await viewer.delete(url)).status_code == 403
    async with make_client(app) as outsider:
        await login(outsider, queue, "outsider@example.org")
        assert (await outsider.put(url, content=png(), headers=PNG_HEADERS)).status_code == 404
        assert (await outsider.delete(url)).status_code == 404
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        res = await editor.put(url, content=png(), headers=PNG_HEADERS)
        assert res.status_code == 200 and res.json()["logo"] is not None
        assert (await editor.delete(url)).status_code == 200
    async with make_client(app) as anon:
        assert (await anon.put(url, content=png(), headers=PNG_HEADERS)).status_code == 401


async def test_public_logo_names_and_missing_files(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    form_id = uuid.uuid4()
    base = f"/api/v1/public/form-logos/{form_id}"
    for name in ("logo.png", f"{'a' * 16}.webp", f"{'A' * 16}.png", "..%2Fsecret", "x"):
        assert (await client.get(f"{base}/{name}")).status_code == 404, name
    assert (await client.get(f"{base}/{'a' * 16}.png")).status_code == 404
    assert (
        await client.get(f"/api/v1/public/form-logos/not-a-uuid/{'a' * 16}.png")
    ).status_code in (
        404,
        422,
    )


async def test_duplicate_does_not_share_the_logo(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    logo = (
        await client.put(f"/api/v1/forms/{pub.id}/logo", content=png(), headers=PNG_HEADERS)
    ).json()["logo"]
    res = await client.post(f"/api/v1/forms/{pub.id}/duplicate")
    assert res.status_code == 201, res.text
    copy_id = res.json()["id"]
    assert (await client.get(f"/api/v1/forms/{copy_id}/theme")).json()["logo"] is None
    # Removing the copy's logo (none) or the original's never breaks the other.
    assert (await client.delete(f"/api/v1/forms/{copy_id}/logo")).status_code == 200
    assert (await client.get(logo["url"])).status_code == 200


async def test_preview_with_form_id(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    pub = await publish(client, me, [field("name")])
    logo = (
        await client.put(f"/api/v1/forms/{pub.id}/logo", content=png(), headers=PNG_HEADERS)
    ).json()["logo"]
    res = await client.post(
        "/api/v1/themes/preview",
        json={"orgId": org, "formId": pub.id, "form": {"logoSize": "l", "logoPlacement": "end"}},
    )
    assert res.status_code == 200, res.text
    opts = res.json()["options"]
    assert opts["logoUrl"] == logo["url"] and opts["logoOwn"] is True
    assert opts["logoSize"] == "l" and opts["logoPlacement"] == "end"
    res = await client.post("/api/v1/themes/preview", json={"orgId": org})
    assert res.json()["options"]["logoOwn"] is False
    res = await client.post(
        "/api/v1/themes/preview", json={"orgId": org, "formId": str(uuid.uuid4())}
    )
    assert res.status_code == 404

    # An organisation member without access to the form can't preview with it.
    db.add(User(email="member@example.org"))
    await db.commit()
    res = await client.post(f"/api/v1/orgs/{org}/members", json={"email": "member@example.org"})
    assert res.status_code in (200, 201)
    async with make_client(app) as member:
        await login(member, queue, "member@example.org")
        res = await member.post("/api/v1/themes/preview", json={"orgId": org, "formId": pub.id})
        assert res.status_code == 404
        res = await member.post("/api/v1/themes/preview", json={"orgId": org})
        assert res.status_code == 200


async def test_theme_saves_logo_values(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], title="Linked")
    body = {"logoSize": "s", "logoPlacement": "end", "logoLink": "https://example.org/home"}
    res = await client.put(f"/api/v1/forms/{pub.id}/theme", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["theme"] == {"colors": {}, **body}
    opts = (await client.get(pub.base)).json()["brand"]["theme"]
    assert opts["logoSize"] == "s" and opts["logoPlacement"] == "end"
    assert opts["logoLink"] == "https://example.org/home"
    bad = await client.put(f"/api/v1/forms/{pub.id}/theme", json={"logoLink": "javascript:x"})
    assert bad.status_code == 422
    org = me["orgs"][0]["id"]
    res = await client.put(f"/api/v1/orgs/{org}/form-theme", json={"logoLink": "https://a.example"})
    assert res.status_code == 200
    assert res.json()["preview"]["options"]["logoLink"] == "https://a.example"


async def test_pdf_input_uses_the_form_logo(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    from app.pdf.service import build_input

    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    raw = png(300, 64)
    res = await client.put(f"/api/v1/forms/{pub.id}/logo", content=raw, headers=PNG_HEADERS)
    assert res.status_code == 200
    await client.put(
        f"/api/v1/forms/{pub.id}/theme", json={"logoSize": "l", "logoPlacement": "center"}
    )
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": "A"}))
    assert res.status_code == 201, res.text
    sub = await db.scalar(select(Submission).where(Submission.form_id == uuid.UUID(pub.id)))
    assert sub is not None
    src = await build_input(db, file_storage, settings, sub)
    assert src.logo is not None and src.logo.startswith(b"\x89PNG")
    assert src.logo_size == (300, 64)
    assert src.logo_scale == "l" and src.logo_placement == "center"
    assert render_pdf(src).startswith(b"%PDF")

    # Without its own logo (and no organisation logo) there is none.
    await client.delete(f"/api/v1/forms/{pub.id}/logo")
    form = await db.get(FormRecord, uuid.UUID(pub.id))
    assert form is not None
    await db.refresh(form)
    src = await build_input(db, file_storage, settings, sub)
    assert src.logo is None
