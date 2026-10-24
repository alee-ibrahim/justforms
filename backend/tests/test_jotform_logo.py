"""The Jotform form logo: finding it in the HTML and API properties, the guarded download,
cleaning (JPEG to PNG), the import report and attaching it to the created draft."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.importers.dom import parse_html
from app.importers.jotform import api_source
from app.importers.jotform import logo as jf_logo
from app.importers.jotform.convert import COVER_IMAGE
from app.importers.jotform.html_source import read_html
from app.importers.jotform.logo import LogoError, clean_logo, find_logo_url
from app.importers.jotform.logo import fetch_logo as real_fetch_logo
from app.importers.jotform.model import JfQuestion, JfSource
from app.models import Import
from app.notifications.ssrf import Target, UrlRefused
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.helpers import admin_client

LOGO_URL = "https://www.jotform.com/uploads/example/form_files/logo.png"


def image(fmt: str = "PNG", w: int = 160, h: int = 80, mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (w, h), "#0F766E").save(out, format=fmt)
    return out.getvalue()


def jotform_html(logo: str | None = LOGO_URL, *, header: bool = False) -> str:
    """A small synthetic Jotform page (generic sample content)."""
    cover = ""
    if logo and header:
        cover = (
            '<div class="form-header-group"><div class="header-logo">'
            f'<img src="{logo}" alt="" width="752" class="header-logo-top" /></div></div>'
        )
    elif logo:
        cover = (
            '<div id="formCoverLogo" class="form-cover-wrapper form-has-cover">'
            '<div class="form-page-cover-image-wrapper">'
            f'<img src="{logo}" class="form-page-cover-image" width="140" height="140" alt="" />'
            "</div></div>"
        )
    return f"""<!DOCTYPE html><html><head><title>Sample request</title></head><body>
<form class="jotform-form" action="https://submit.jotform.com/submit/200000000000077">
{cover}
<ul class="form-section page-section">
  <li id="cid_1" class="form-input-wide" data-type="control_head">
    <h1 id="header_1" class="form-header">Sample request</h1></li>
  <li class="form-line" data-type="control_textbox" id="id_3">
    <label class="form-label" id="label_3" for="input_3">Your name</label>
    <div id="cid_3" class="form-input"><input type="text" id="input_3" name="q3_yourName" /></div>
  </li>
</ul></form></body></html>"""


# -- finding it ------------------------------------------------------------------------------


def test_find_cover_and_header_logo() -> None:
    assert find_logo_url(parse_html(jotform_html())) == LOGO_URL
    header = parse_html(jotform_html("/uploads/example/head.jpg", header=True))
    assert find_logo_url(header) == "/uploads/example/head.jpg"
    assert find_logo_url(parse_html(jotform_html(None))) is None
    src = read_html(jotform_html())
    assert src.logo_url == LOGO_URL and src.cover_image
    plain = read_html(jotform_html(None))
    assert plain.logo_url is None and not plain.cover_image


def test_api_properties_logo() -> None:
    question = {"qid": "3", "type": "control_textbox", "text": "Name", "order": "1"}
    src = api_source.source_from_api(
        {"id": "1", "title": "T"}, {"3": question}, {"formCoverImg": LOGO_URL}
    )
    assert src.logo_url == LOGO_URL and src.cover_image
    assert jf_logo.api_logo_url({"logo": "javascript:alert(1)"}) is None
    assert jf_logo.api_logo_url({"formImage": {"url": "//cdn.jotfor.ms/x.png"}}) == (
        "//cdn.jotfor.ms/x.png"
    )
    assert api_source.source_from_api({"id": "1"}, {"3": question}, {}).logo_url is None


# -- download guard --------------------------------------------------------------------------

PUBLIC = "203.0.113.9"


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jotform hosts resolve to a public address; anything else to a private one."""

    async def resolve(url: str, _settings: Settings) -> Target:
        host = httpx.URL(url).host
        if host in jf_logo.ALLOWED_HOSTS:
            return Target(url=url, host=host, port=443, scheme="https", address=PUBLIC)
        raise UrlRefused("private_address")

    monkeypatch.setattr(jf_logo, "resolve", resolve)


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/uploads/logo.png":
        return httpx.Response(200, content=image())
    if path == "/uploads/hop":
        return httpx.Response(302, headers={"location": "https://cdn.jotfor.ms/uploads/logo.png"})
    if path == "/uploads/to-private":
        return httpx.Response(302, headers={"location": "https://10.0.0.5/logo.png"})
    if path == "/uploads/to-other":
        return httpx.Response(302, headers={"location": "https://example.org/logo.png"})
    if path == "/uploads/to-http":
        return httpx.Response(302, headers={"location": "http://www.jotform.com/uploads/x.png"})
    if path == "/uploads/loop":
        return httpx.Response(302, headers={"location": "/uploads/loop"})
    if path == "/uploads/big":
        return httpx.Response(200, content=b"a" * (jf_logo.MAX_BYTES + 1))
    return httpx.Response(404)


TRANSPORT = httpx.MockTransport(handler)


async def test_fetch_follows_checked_redirects(settings: Settings, guarded: None) -> None:
    seen: list[httpx.Request] = []

    def spy(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    data = await real_fetch_logo(
        "https://www.jotform.com/uploads/hop", settings, transport=httpx.MockTransport(spy)
    )
    assert data.startswith(b"\x89PNG")
    # Connects to the checked address, with the real host name.
    assert seen[0].url.host == PUBLIC and seen[0].headers["host"] == "www.jotform.com"
    assert seen[1].headers["host"] == "cdn.jotfor.ms"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://www.jotform.com/uploads/logo.png", "host"),  # not https
        ("https://example.org/uploads/logo.png", "host"),  # not a Jotform host
        ("https://10.0.0.5/uploads/logo.png", "host"),  # private address
        ("https://www.jotform.com:8443/uploads/logo.png", "host"),
        ("https://user:pw@www.jotform.com/uploads/logo.png", "host"),
        ("https://www.jotform.com/uploads/to-private", "host"),
        ("https://www.jotform.com/uploads/to-other", "host"),
        ("https://www.jotform.com/uploads/to-http", "host"),
        ("https://www.jotform.com/uploads/loop", "fetch"),  # more than 3 redirects
        ("https://www.jotform.com/uploads/big", "too_large"),
        ("https://www.jotform.com/uploads/missing", "fetch"),
    ],
)
async def test_fetch_refusals(url: str, code: str, settings: Settings, guarded: None) -> None:
    with pytest.raises(LogoError) as out:
        await real_fetch_logo(url, settings, transport=TRANSPORT)
    assert out.value.code == code


async def test_private_dns_answer_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(url: str, _settings: Settings) -> Target:
        raise UrlRefused("private_address")  # e.g. a Jotform name pointed at 127.0.0.1

    monkeypatch.setattr(jf_logo, "resolve", resolve)
    with pytest.raises(LogoError) as out:
        await real_fetch_logo(LOGO_URL, settings, transport=TRANSPORT)
    assert out.value.code == "host"


# -- cleaning --------------------------------------------------------------------------------


def test_clean_logo_converts_jpeg_webp_gif_to_png() -> None:
    for fmt in ("JPEG", "WEBP", "GIF"):
        img = clean_logo(image(fmt))
        assert img.mime == "image/png" and (img.width, img.height) == (160, 80), fmt
    big = clean_logo(image("JPEG", 3000, 1500))
    assert big.mime == "image/png" and big.width == 1024 and big.height == 512
    assert clean_logo(image("PNG")).mime == "image/png"
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'  # noqa: E501
    assert clean_logo(svg).mime == "image/svg+xml"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"not an image", "bad_type"),
        (image("BMP"), "bad_type"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>',
            "svg_unsafe",
        ),
        (image("JPEG", 4100, 20), "too_large_pixels"),
        (b"x" * (jf_logo.MAX_BYTES + 1), "too_large"),
    ],
    ids=["garbage", "bmp", "svg_unsafe", "pixels", "bytes"],
)
def test_clean_logo_refusals(raw: bytes, code: str) -> None:
    with pytest.raises(LogoError) as out:
        clean_logo(raw)
    assert out.value.code == code
    assert jf_logo.REASONS[code]


# -- the import ------------------------------------------------------------------------------


async def _preview(client: AsyncClient, me: dict[str, Any], **body: Any) -> Any:
    return await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/imports/jotform/html", json=body)


def fake_fetch(data: bytes, calls: list[str]) -> Any:
    async def fetch(url: str, _settings: Settings, **_: Any) -> bytes:
        calls.append(url)
        return data

    return fetch


async def test_import_attaches_the_logo(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    calls: list[str] = []
    monkeypatch.setattr(jf_logo, "fetch_logo", fake_fetch(image("JPEG"), calls))
    res = await _preview(client, me, html=jotform_html())
    assert res.status_code == 201, res.text
    preview = res.json()
    assert calls == [LOGO_URL]
    assert preview["report"]["logo"] == {"status": "imported", "reason": None, "source": LOGO_URL}
    assert COVER_IMAGE not in preview["report"]["dropped"]
    imp = await db.get(Import, uuid.UUID(preview["id"]))
    assert imp is not None
    temp = imp.source["logo"]["key"]
    assert temp == f"imports/{imp.id}/logo.png" and await file_storage.exists(temp)

    res = await client.post(f"/api/v1/imports/{preview['id']}/form", json={})
    assert res.status_code == 201, res.text
    form_id = res.json()["formId"]
    theme = (await client.get(f"/api/v1/forms/{form_id}/theme")).json()
    logo = theme["logo"]
    assert logo["mime"] == "image/png" and (logo["width"], logo["height"]) == (160, 80)
    assert logo["url"].startswith(f"/api/v1/public/form-logos/{form_id}/")
    assert theme["preview"]["options"]["logoOwn"] is True
    served = await client.get(logo["url"])
    assert served.status_code == 200 and served.content.startswith(b"\x89PNG")
    assert not await file_storage.exists(temp)
    await db.refresh(imp)
    assert "logo" not in imp.source


async def test_relative_logo_is_resolved_against_the_page(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    calls: list[str] = []
    monkeypatch.setattr(jf_logo, "fetch_logo", fake_fetch(image(), calls))

    async def fetch_page(url: str, _settings: Settings, **_: Any) -> tuple[str, str]:
        return "https://form.jotform.com/200000000000077", jotform_html("/uploads/a/logo.png")

    monkeypatch.setattr("app.api.v1.imports.fetch_form_html", fetch_page)
    res = await _preview(client, me, url="https://form.jotform.com/200000000000077")
    assert res.status_code == 201, res.text
    assert calls == ["https://form.jotform.com/uploads/a/logo.png"]
    assert res.json()["report"]["logo"]["status"] == "imported"


async def test_logo_not_imported_is_reported(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    # A host outside the allow-list is refused before any request (real fetcher).
    monkeypatch.setattr(jf_logo, "fetch_logo", real_fetch_logo)
    res = await _preview(client, me, html=jotform_html("https://example.org/logo.png"))
    report = res.json()["report"]
    assert report["logo"] == {
        "status": "not_imported",
        "reason": "The logo is on a host JustForms doesn't download from.",
        "source": "https://example.org/logo.png",
    }
    assert COVER_IMAGE in report["dropped"]

    monkeypatch.setattr(jf_logo, "fetch_logo", fake_fetch(b"plain text", []))
    res = await _preview(client, me, html=jotform_html())
    assert res.json()["report"]["logo"]["reason"] == (
        "The logo isn't a PNG, SVG, JPEG, WebP or GIF image."
    )
    res = await client.post(f"/api/v1/imports/{res.json()['id']}/form", json={})
    form_id = res.json()["formId"]
    assert (await client.get(f"/api/v1/forms/{form_id}/theme")).json()["logo"] is None

    res = await _preview(client, me, html=jotform_html(None))
    assert res.json()["report"]["logo"] == {"status": "none", "reason": None, "source": None}


async def test_api_import_downloads_the_logo(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    calls: list[str] = []
    monkeypatch.setattr(jf_logo, "fetch_logo", fake_fetch(image(), calls))

    async def read_form(_region: str, _key: str, form_id: str, **_: Any) -> JfSource:
        src = JfSource(title="Sample", form_id=form_id, logo_url=LOGO_URL, cover_image=True)
        src.questions = [JfQuestion(qid="3", type="control_textbox", label="Name", name="name")]
        return src

    monkeypatch.setattr(api_source, "read_form", read_form)
    res = await client.post(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/imports/jotform/api",
        json={"apiKey": "a" * 32, "formId": "200000000000077"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["report"]["logo"]["status"] == "imported" and calls == [LOGO_URL]
