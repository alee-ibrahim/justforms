"""Copying the files behind imported Jotform links into storage (DESIGN 13.3, "Imported
files"): the guarded download with the API key, signature images, the per-file report,
idempotent re-runs, the studio download and erasure."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.importers import service
from app.importers.imported_files import (
    fetch_form_files,
    pending_links,
    stored_files,
    stored_keys,
)
from app.importers.jotform import files as jf_files
from app.importers.jotform.files import FileFetchError, fetch_file, signature_png
from app.importers.jotform.logo import ALLOWED_HOSTS
from app.models import AuditLog, Submission
from app.notifications.ssrf import Target, UrlRefused
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.helpers import admin_client
from tests.test_imports_api import FIXTURES, _imported_form, _publish, _upload

KEY = "a" * 32
PUBLIC = "203.0.113.9"
BASE = "https://www.jotform.com/uploads/example/200000000000001"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def png(fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGBA" if fmt == "PNG" else "RGB", (300, 120), "#1E293B").save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jotform hosts resolve to a public address; anything else to a private one."""

    async def resolve(url: str, _settings: Settings) -> Target:
        host = httpx.URL(url).host
        if host in ALLOWED_HOSTS:
            return Target(url=url, host=host, port=443, scheme="https", address=PUBLIC)
        raise UrlRefused("private_address")

    monkeypatch.setattr(jf_files, "resolve", resolve)


class FakeJotform:
    """Uploads need the key; the upload host redirects to a short-lived file URL."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        host, path = request.headers["host"], request.url.path
        if host == "files.jotform.com":
            if path == "/signed/sig3.png":
                return httpx.Response(200, content=png("JPEG"), headers={"content-type": "x/y"})
            return httpx.Response(404)
        if request.headers.get("apikey") != KEY:
            return httpx.Response(302, headers={"location": "https://www.jotform.com/login/"})
        routes = {
            "/6100000000000000001/profile.pdf": httpx.Response(
                200, content=PDF, headers={"content-type": "application/octet-stream"}
            ),
            "/6100000000000000001/signature.png": httpx.Response(200, content=png()),
            "/6100000000000000002/profile.pdf": httpx.Response(200, content=b"<html>login</html>"),
            "/6100000000000000003/signature.png": httpx.Response(
                302, headers={"location": "https://files.jotform.com/signed/sig3.png"}
            ),
            "/big.pdf": httpx.Response(200, content=b"%PDF-" + b"0" * 2048),
            "/to-private": httpx.Response(302, headers={"location": "https://10.0.0.5/x.pdf"}),
            "/to-other": httpx.Response(302, headers={"location": "https://example.org/x.pdf"}),
        }
        for suffix, res in routes.items():
            if path.endswith(suffix):
                return res
        return httpx.Response(404)


# -- the download ------------------------------------------------------------------------------


async def test_key_goes_only_to_the_link_host(settings: Settings, guarded: None) -> None:
    fake = FakeJotform()
    got = await fetch_file(
        f"{BASE}/6100000000000000003/signature.png",
        settings,
        api_key=KEY,
        max_bytes=10_000_000,
        transport=httpx.MockTransport(fake),
    )
    assert got.name == "signature.png" and got.data[:3] == b"\xff\xd8\xff"
    first, second = fake.seen
    # Pinned to the checked address, with the real host name; the key in a header only.
    assert first.url.host == PUBLIC and first.headers["host"] == "www.jotform.com"
    assert first.headers["apikey"] == KEY and KEY not in str(first.url)
    assert second.headers["host"] == "files.jotform.com" and "apikey" not in second.headers


@pytest.mark.parametrize(
    ("url", "key", "code"),
    [
        (f"{BASE}/6100000000000000001/profile.pdf", None, "auth"),  # login redirect
        ("http://www.jotform.com/uploads/x.pdf", KEY, "host"),
        ("https://example.org/uploads/x.pdf", KEY, "host"),
        ("https://10.0.0.5/uploads/x.pdf", KEY, "host"),
        ("https://user:pw@www.jotform.com/uploads/x.pdf", KEY, "host"),
        ("https://www.jotform.com:8443/uploads/x.pdf", KEY, "host"),
        (f"{BASE}/to-private", KEY, "host"),
        (f"{BASE}/to-other", KEY, "host"),
        (f"{BASE}/big.pdf", KEY, "too_large"),
        (f"{BASE}/missing.pdf", KEY, "not_found"),
    ],
)
async def test_fetch_refusals(
    url: str, key: str | None, code: str, settings: Settings, guarded: None
) -> None:
    with pytest.raises(FileFetchError) as out:
        await fetch_file(
            url, settings, api_key=key, max_bytes=1024, transport=httpx.MockTransport(FakeJotform())
        )
    assert out.value.code == code


def test_signature_png_reencodes_and_refuses() -> None:
    data, w, h = signature_png(png("JPEG"))
    assert data.startswith(b"\x89PNG") and (w, h) == (300, 120)
    with pytest.raises(FileFetchError) as out:
        signature_png(b"<svg onload=alert(1)>")
    assert out.value.code == "bad_type"
    with pytest.raises(FileFetchError) as out:
        signature_png(b"0" * (jf_files.SIGNATURE_MAX_BYTES + 1))
    assert out.value.code == "too_large"


def test_column_helpers() -> None:
    column: dict[str, Any] = {
        "a": ["https://x/1", {"url": "https://x/2", "key": "imported/k", "kind": "file"}],
        "b": ["https://x/3"],
    }
    assert pending_links(column) == {"a": ["https://x/1"], "b": ["https://x/3"]}
    assert [(f, i) for f, i, _e in stored_files(column)] == [("a", 1)]
    assert stored_keys(column) == ["imported/k"]
    assert pending_links(None) == {} and stored_keys(None) == []


# -- the whole run -----------------------------------------------------------------------------


async def _imported_submissions(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    storage: Storage,
) -> tuple[str, dict[str, Submission]]:
    me = await admin_client(client, db, settings, queue)
    form_id = await _imported_form(client, me, "registration_form.html")
    await _publish(client, form_id)
    up = (
        await _upload(
            client, form_id, (FIXTURES / "registration_submissions.csv").read_bytes(), "x.csv"
        )
    ).json()
    await client.put(
        f"/api/v1/imports/{up['id']}/mapping",
        json={"columns": [c["target"] for c in up["columns"]]},
    )
    await client.post(f"/api/v1/imports/{up['id']}/start", json={})
    assert await service.run_submissions_import(db, storage, settings, uuid.UUID(up["id"]))
    rows = (
        await db.scalars(select(Submission).where(Submission.form_id == uuid.UUID(form_id)))
    ).all()
    return form_id, {str(r.external_id): r for r in rows}


async def test_fetch_run_report_rerun_download_and_erase(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    guarded: None,
) -> None:
    form_id, subs = await _imported_submissions(client, db, settings, queue, file_storage)
    fid = uuid.UUID(form_id)
    transport = httpx.MockTransport(FakeJotform())
    hashes = {k: s.content_hash for k, s in subs.items()}

    dry = await fetch_form_files(db, file_storage, settings, fid, api_key=None, dry_run=True)
    assert dry.counts() == {"pending": 4}

    report = await fetch_form_files(
        db, file_storage, settings, fid, api_key=KEY, transport=transport
    )
    assert report.counts() == {"fetched": 3, "failed": 1}
    failed = [r for r in report.results if r.status == "failed"]
    assert [(r.field_id, r.reason) for r in failed] == [("group_profile", "bad_type")]
    as_json = report.as_json()
    assert as_json["submissions"] == 3 and len(as_json["files"]) == 4
    # The report carries positions and types, never names or links.
    assert "url" not in str(as_json) and "profile.pdf" not in str(as_json)

    first = subs["6100000000000000001"]
    await db.refresh(first)
    assert first.content_hash == hashes["6100000000000000001"]
    files = {f: e for f, _i, e in stored_files(first.imported_links)}
    assert files["group_profile"]["mime"] == "application/pdf"
    assert files["group_profile"]["kind"] == "file"
    assert files["signature"]["kind"] == "signature"
    assert files["signature"]["key"].endswith("/signature-0.png")
    for e in files.values():
        assert await file_storage.exists(e["key"])
        assert e["key"].startswith(f"imported/{form_id}/{first.id}/")

    third = subs["6100000000000000003"]
    await db.refresh(third)
    sig = stored_files(third.imported_links)[0][2]
    stored = await file_storage.read(sig["key"])
    assert stored.startswith(b"\x89PNG")  # the JPEG was re-encoded

    # Studio: stored copies listed, remaining links still shown, hash chain untouched.
    detail = (await client.get(f"/api/v1/submissions/{first.id}")).json()
    assert detail["importedLinks"] is None
    kinds = {f["fieldId"]: f["kind"] for f in detail["importedFiles"]}
    assert kinds == {"group_profile": "file", "signature": "signature"}
    second = subs["6100000000000000002"]
    detail2 = (await client.get(f"/api/v1/submissions/{second.id}")).json()
    assert set(detail2["importedLinks"]) == {"group_profile"}
    assert detail2["importedFiles"] == []
    assert (await client.get(f"/api/v1/submissions/{first.id}/verify")).json()["ok"] is True

    pdf_url = next(f["url"] for f in detail["importedFiles"] if f["kind"] == "file")
    res = await client.get(pdf_url)
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.headers["content-type"] == "application/octet-stream"
    sig_url = next(f["url"] for f in detail["importedFiles"] if f["kind"] == "signature")
    res = await client.get(sig_url, params={"preview": "1"})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert "sandbox" in res.headers["content-security-policy"]
    missing = await client.get(f"/api/v1/submissions/{first.id}/imported-files/group_profile/5")
    assert missing.status_code == 404
    not_stored = await client.get(f"/api/v1/submissions/{second.id}/imported-files/group_profile/0")
    assert not_stored.status_code == 404

    # A second run skips what is stored and retries what failed.
    again = await fetch_form_files(
        db, file_storage, settings, fid, api_key=KEY, transport=transport
    )
    assert again.counts() == {"skipped": 3, "failed": 1}
    logs = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "submissions.import_files"))
    ).all()
    assert sorted(log.meta.get("fetched", 0) for log in logs) == [0, 3]

    # Erasing the submission removes its stored copies too.
    keys = stored_keys(first.imported_links)
    res = await client.delete(f"/api/v1/submissions/{first.id}", params={"hard": "true"})
    assert res.status_code == 204
    for key in keys:
        assert not await file_storage.exists(key)


async def test_other_users_cannot_download(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    guarded: None,
) -> None:
    form_id, subs = await _imported_submissions(client, db, settings, queue, file_storage)
    await fetch_form_files(
        db,
        file_storage,
        settings,
        uuid.UUID(form_id),
        api_key=KEY,
        transport=httpx.MockTransport(FakeJotform()),
    )
    first = subs["6100000000000000001"]
    url = f"/api/v1/submissions/{first.id}/imported-files/signature/0"
    assert (await client.get(url)).status_code == 200
    client.cookies.clear()
    assert (await client.get(url)).status_code in (401, 403, 404)
