"""Link previews: the page tags sent to nginx, the generated and uploaded images, permissions
and caching (docs/ux/SHARING-PREVIEW-SCREENS.md)."""

from __future__ import annotations

import html
import io
import re
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRecord, FormRole, User
from app.pdf import faces
from app.sharing import image as og
from app.sharing import meta
from app.sharing import service as sharing
from app.storage import Storage
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import Published, admin_client, field, publish

# Draft Dhivehi (fixtures are drafts until checked, CLAUDE.md).
DV_TITLE = "ޚިދުމަތަށް އެދޭ ފޯމު"
HOSTILE = '"><script>alert(1)</script><meta x="'


def png(w: int, h: int, color: str = "#0F766E", mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (w, h), color).save(out, format="PNG")
    return out.getvalue()


def tags(head: str) -> dict[str, str]:
    """``{property-or-name: content}`` of the meta tags, plus title and canonical."""
    out: dict[str, str] = {}
    for kind, key, value in re.findall(r'<meta (property|name)="([^"]+)" content="([^"]*)">', head):
        del kind
        out[key] = html.unescape(value)
    title = re.search(r"<title>([^<]*)</title>", head)
    out["title"] = html.unescape(title.group(1)) if title else ""
    canonical = re.search(r'<link rel="canonical" href="([^"]*)">', head)
    out["canonical"] = html.unescape(canonical.group(1)) if canonical else ""
    return out


async def page_head(client: AsyncClient, path: str) -> str:
    res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": path})
    assert res.status_code == 204
    head = res.headers.get("x-justforms-head", "")
    assert head.isascii() and "\n" not in head
    return head


async def set_description(client: AsyncClient, form_id: str, text: str) -> None:
    draft = (await client.get(f"/api/v1/forms/{form_id}/draft")).json()
    res = await client.patch(
        f"/api/v1/forms/{form_id}/draft",
        json={
            "baseRevision": draft["revision"],
            "patch": [{"op": "add", "path": "/settings/description", "value": text}],
        },
    )
    assert res.status_code == 200, res.text
    assert (await client.post(f"/api/v1/forms/{form_id}/publish")).status_code == 200


# -- tags -------------------------------------------------------------------------------------


def _preview(title: str, description: str = "", language: str = "en") -> sharing.Preview:
    form = FormRecord(id=uuid.uuid4(), org_id=uuid.uuid4(), slug="intake", title=title, settings={})
    schema = {"settings": {"title": title, "description": description, "language": language}}
    return sharing.build(Settings(), None, form, schema)


def test_meta_escapes_user_text() -> None:
    head = meta.form_head(_preview(HOSTILE, f"**Bold** {HOSTILE}"), "https://forms.example.org")
    assert "<script" not in head and 'x="' not in head
    assert head.count("<meta") == len(re.findall(r"<meta [^<>]*>", head))
    t = tags(head)
    assert t["title"] == t["og:title"] == t["twitter:title"] == HOSTILE
    assert t["og:description"] == f"Bold {HOSTILE}"


def test_meta_writes_thaana_as_references() -> None:
    head = meta.form_head(_preview(DV_TITLE, language="dv"), "https://forms.example.org")
    assert head.isascii()
    t = tags(head)
    assert t["og:title"] == DV_TITLE and t["og:locale"] == "dv_MV"


def test_description_markdown_is_plain_and_short() -> None:
    long = "See [the guide](https://example.org) and **read it**. " + "word " * 120
    p = _preview("Intake", long)
    assert p.description.startswith("See the guide and read it.")
    assert len(p.description) <= sharing.DESCRIPTION_MAX
    t = tags(meta.form_head(p, "https://x.example"))
    assert len(t["description"]) <= sharing.META_DESCRIPTION_MAX
    assert t["description"].endswith("…")


# -- image ------------------------------------------------------------------------------------


def _dark_columns(data: bytes) -> tuple[int, int]:
    """Dark pixels in the left and right halves of the title area."""
    img = Image.open(io.BytesIO(data)).convert("L").crop((0, 180, og.WIDTH, 460))
    half = img.width // 2

    def dark(part: Image.Image) -> int:
        return sum(part.histogram()[:100])

    left = dark(img.crop((0, 0, half, img.height)))
    right = dark(img.crop((half, 0, img.width, img.height)))
    return left, right


def test_generated_image_size_and_weight() -> None:
    card = og.Card(
        title="Community service programme registration for organisations " * 3,
        description="It takes about five minutes. " * 10,
        org_name="Example Council",
        address="forms.example.org/intake",
        rtl=False,
        colors=og.Colors(primary="#0F766E"),
        logo=png(400, 120),
        logo_size=(400, 120),
    )
    data = og.render(card)
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG" and img.size == (1200, 630)
    assert len(data) < 300 * 1024
    # The band along the bottom is the primary colour.
    assert img.convert("RGB").getpixel((600, 625)) == (0x0F, 0x76, 0x6E)


def test_thaana_title_is_shaped_and_right_aligned() -> None:
    import uharfbuzz as hb

    font = hb.Font(hb.Face(hb.Blob.from_file_path(str(faces.BUNDLED_BOLD))))
    buf = hb.Buffer()
    buf.add_str(DV_TITLE)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    assert buf.direction == "rtl"
    assert all(info.codepoint != 0 for info in buf.glyph_infos)  # no missing glyphs
    data = og.render(
        og.Card(
            title=DV_TITLE,
            description=None,
            org_name="Example Council",
            address="forms.example.org/intake",
            rtl=True,
            colors=og.Colors(),
        )
    )
    left, right = _dark_columns(data)
    assert right > 50 and right > left * 3


# -- API --------------------------------------------------------------------------------------


async def _setup(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    **kw: Any,
) -> tuple[dict[str, Any], Published]:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], **kw)
    return me, pub


async def test_page_tags_for_a_published_form(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    _, pub = await _setup(client, db, settings, queue, title="Intake <b>2026</b>")
    await set_description(client, pub.id, "Tell us about **your** project.")
    slug = pub.form["slug"]
    origin = settings.public_origin
    t = tags(await page_head(client, f"/{slug}?embed=1"))
    assert t["title"] == t["og:title"] == "Intake <b>2026</b>"
    assert t["og:description"] == t["description"] == "Tell us about your project."
    assert t["og:url"] == t["canonical"] == f"{origin}/{slug}"
    assert t["og:type"] == "website" and t["og:locale"] == "en_US"
    assert t["og:site_name"]
    assert t["twitter:card"] == "summary_large_image"
    image = t["og:image"]
    assert image.startswith(f"{origin}/api/v1/public/forms/{slug}/og.png?v=")
    assert t["twitter:image"] == image
    assert (t["og:image:width"], t["og:image:height"]) == ("1200", "630")
    assert t["og:image:alt"] == "Intake <b>2026</b>"
    # Frame-ancestors still answered alongside.
    res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": f"/{slug}"})
    assert res.headers["x-justforms-frame-ancestors"] == "*"


async def test_page_tags_dhivehi_and_closed(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    _, pub = await _setup(client, db, settings, queue, title=DV_TITLE, language="dv")
    slug = pub.form["slug"]
    t = tags(await page_head(client, f"/{slug}"))
    assert t["og:title"] == DV_TITLE and t["og:locale"] == "dv_MV"
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"status": "closed"})
    assert res.status_code == 200, res.text
    assert tags(await page_head(client, f"/{slug}"))["og:title"] == DV_TITLE
    img = await client.get(f"/api/v1/public/forms/{slug}/og.png")
    assert img.status_code == 200


async def test_unknown_and_unpublished_forms_get_site_tags(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await client.post(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/forms",
        json={"title": "Secret draft title", "language": "en"},
    )
    draft = res.json()
    for path in (f"/{draft['slug']}", "/no-such-form", "/", "/a/b"):
        head = await page_head(client, path)
        assert "Secret draft" not in head and draft["slug"] not in head, path
        t = tags(head)
        assert t["og:image"].startswith(f"{settings.public_origin}/api/v1/public/og/site.png?v=")
        assert "og:url" not in t and t["canonical"] == ""
    assert (await client.get(f"/api/v1/public/forms/{draft['slug']}/og.png")).status_code == 404
    site = await client.get("/api/v1/public/og/site.png")
    assert site.status_code == 200 and Image.open(io.BytesIO(site.content)).size == (1200, 630)


async def test_generated_image_is_cached_and_versioned(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    _, pub = await _setup(client, db, settings, queue, title="Cached")
    slug = pub.form["slug"]
    url = tags(await page_head(client, f"/{slug}"))["og:image"].removeprefix(settings.public_origin)
    res = await client.get(url)
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert "immutable" in res.headers["cache-control"]
    assert res.headers["cross-origin-resource-policy"] == "cross-origin"
    assert "sandbox" in res.headers["content-security-policy"]
    img = Image.open(io.BytesIO(res.content))
    assert img.size == (1200, 630) and len(res.content) < 300 * 1024
    version = url.split("v=")[1]
    key = f"og/{pub.id}/{version}.png"
    assert await file_storage.exists(key)
    etag = res.headers["etag"]
    again = await client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304
    unversioned = await client.get(f"/api/v1/public/forms/{slug}/og.png?v=old")
    assert (
        unversioned.status_code == 200 and "immutable" not in unversioned.headers["cache-control"]
    )

    # A new title (published) is a new image at a new address; the old file goes.
    res = await client.put(f"/api/v1/forms/{pub.id}/sharing", json={"title": "Renamed"})
    assert res.status_code == 200, res.text
    url2 = tags(await page_head(client, f"/{slug}"))["og:image"].removeprefix(
        settings.public_origin
    )
    assert url2 != url
    assert (await client.get(url2)).status_code == 200
    assert not await file_storage.exists(key)


async def test_share_title_description_and_upload(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    _, pub = await _setup(client, db, settings, queue, title="Own title")
    slug = pub.form["slug"]
    base = f"/api/v1/forms/{pub.id}/sharing"
    got = (await client.get(base)).json()
    assert got["title"] is None and got["effectiveTitle"] == "Own title"
    assert got["defaultTitle"] == "Own title" and got["canEdit"] is True
    assert got["customImage"] is None and got["published"] is True
    assert (await client.get(got["imageUrl"])).status_code == 200

    res = await client.put(base, json={"title": "  Share   me ", "description": "Short."})
    out = res.json()
    assert out["title"] == "Share me" and out["effectiveDescription"] == "Short."
    t = tags(await page_head(client, f"/{slug}"))
    assert t["og:title"] == "Share me" and t["og:description"] == "Short."
    assert (await client.put(base, json={"title": "x" * 121})).status_code == 422

    # Upload: cropped to 1.91:1 from the centre, 1200x630, JPEG.
    res = await client.put(f"{base}/image", content=png(2400, 2400, mode="RGBA"))
    assert res.status_code == 200, res.text
    assert res.json()["customImage"] == {"width": 1200, "height": 630}
    t = tags(await page_head(client, f"/{slug}"))
    assert t["og:image:type"] == "image/jpeg"
    url = t["og:image"].removeprefix(settings.public_origin)
    assert f"/forms/{slug}/og.jpg?v=c" in url
    img = await client.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(img.content)).size == (1200, 630)
    form = await db.get(FormRecord, uuid.UUID(pub.id))
    assert form is not None
    await db.refresh(form)
    custom_key = form.settings["sharing"]["image"]["key"]
    assert await file_storage.exists(custom_key)

    # Small images are kept small (never scaled up) and reported as they are.
    res = await client.put(f"{base}/image", content=png(600, 400))
    assert res.json()["customImage"] == {"width": 600, "height": 315}
    assert not await file_storage.exists(custom_key)  # the replaced upload is removed
    t = tags(await page_head(client, f"/{slug}"))
    assert (t["og:image:width"], t["og:image:height"]) == ("600", "315")

    # Refused uploads.
    for body, code in (
        (b"not an image", "bad_type"),
        (png(100, 50), "too_small"),
        (b"GIF89a" + b"\x00" * 20, "bad_type"),
    ):
        res = await client.put(f"{base}/image", content=body)
        assert res.status_code == 422 and res.json()["detail"] == code

    # Back to the generated image; clearing the text goes back to the form's.
    res = await client.delete(f"{base}/image")
    assert res.status_code == 200 and res.json()["customImage"] is None
    res = await client.put(base, json={"title": "", "description": None})
    assert res.json()["title"] is None and res.json()["effectiveTitle"] == "Own title"
    t = tags(await page_head(client, f"/{slug}"))
    assert t["og:image:type"] == "image/png" and t["og:title"] == "Own title"


async def test_sharing_permissions(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    _, pub = await _setup(client, db, settings, queue)
    base = f"/api/v1/forms/{pub.id}/sharing"
    for role in ("viewer", "editor"):
        user = User(email=f"{role}@example.org")
        db.add(user)
        await db.flush()
        db.add(FormPermission(form_id=pub.id, user_id=user.id, role=FormRole(role)))
    await db.commit()
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        got = await viewer.get(base)
        assert got.status_code == 200 and got.json()["canEdit"] is False
        assert (await viewer.get(got.json()["imageUrl"])).status_code == 200
        assert (await viewer.put(base, json={"title": "x"})).status_code == 403
        assert (await viewer.put(f"{base}/image", content=png(1200, 630))).status_code == 403
        assert (await viewer.delete(f"{base}/image")).status_code == 403
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        assert (await editor.put(base, json={"title": "x"})).status_code == 200
    async with make_client(app) as anon:
        assert (await anon.get(base)).status_code == 401
        assert (await anon.get(f"{base}/image")).status_code == 401


async def test_unpublished_form_studio_preview_uses_the_draft(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await client.post(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Draft only", "language": "en"}
    )
    form = res.json()
    got = (await client.get(f"/api/v1/forms/{form['id']}/sharing")).json()
    assert got["published"] is False and got["effectiveTitle"] == "Draft only"
    img = await client.get(got["imageUrl"])
    assert img.status_code == 200 and img.headers["cache-control"] == "no-store"  # staff route


@pytest.mark.parametrize("hostile", [HOSTILE, "a\r\nX-Injected: 1", "</title><script>x</script>"])
async def test_header_injection_is_impossible(
    hostile: str,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    _, pub = await _setup(client, db, settings, queue)
    await client.put(f"/api/v1/forms/{pub.id}/sharing", json={"title": hostile})
    res = await client.get(
        "/api/v1/public/frame-ancestors", headers={"X-Original-URI": f"/{pub.form['slug']}"}
    )
    head = res.headers["x-justforms-head"]
    assert "x-injected" not in {k.lower() for k in res.headers}
    assert "<script" not in head
    assert head.count("<title>") == 1 and head.count("</title>") == 1
