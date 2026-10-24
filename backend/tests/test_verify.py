"""The clean respondent PDF and the public verify page (DESIGN 9.5.2)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Submission
from app.pdf.service import generate_pdf
from app.pdf.sign import check_pdf
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.helpers import admin_client
from tests.test_signatures import _signed_form, _submit


async def _pdf(db: AsyncSession, storage: Storage, settings: Settings, sid: str) -> bytes:
    assert await generate_pdf(db, storage, settings, uuid.UUID(sid))
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None and sub.signed_pdf_key
    await db.refresh(sub)
    return await storage.read(sub.signed_pdf_key)


async def test_verify_page_and_copy_check(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me)
    sid = await _submit(client, pub, name="Aminath Ali")
    other = await _submit(client, pub, name="Hassan Ali")
    pdf = await _pdf(db, file_storage, settings, sid)
    other_pdf = await _pdf(db, file_storage, settings, other)
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None and sub.verify_token
    token = sub.verify_token
    assert len(token) >= 20
    # The token travels in the signed file (QR code); the record hashes in its metadata.
    check = await check_pdf(pdf)
    assert check.intact and check.submission_id == sid

    # The page is public: no session needed, and it never returns answers or emails.
    client.cookies.clear()
    res = await client.get(f"/api/v1/public/verify/{token}")
    assert res.status_code == 200
    assert res.headers["referrer-policy"] == "no-referrer"
    body = res.json()
    assert body["state"] == "genuine"
    assert body["reference"] == "#0001"
    assert body["issuedAt"] and body["approval"] is None
    assert "Aminath" not in res.text and "Declaration" not in res.text
    assert set(body) == {
        "state",
        "orgName",
        "brand",
        "reference",
        "issuedAt",
        "approval",
        "thaanaFontCssUrl",
    }

    async def copy(data: bytes) -> str:
        r = await client.post(f"/api/v1/public/verify/{token}/check", content=data)
        assert r.status_code == 200, r.text
        return str(r.json()["result"])

    assert await copy(pdf) == "genuine"
    assert await copy(other_pdf) == "different"
    assert await copy(b"%PDF-1.7 not really") == "not_ours"
    i = pdf.index(b"Declaration")
    assert await copy(pdf[:i] + b"Dexlaration" + pdf[i + len(b"Declaration") :]) == "modified"

    # A newer signed copy (e.g. after an approval) makes this one "older" but still genuine.
    newer = await _pdf(db, file_storage, settings, sid)
    assert newer != pdf
    assert (await db.get(Submission, uuid.UUID(sid))).verify_token == token  # type: ignore[union-attr]
    assert await copy(pdf) == "older"
    assert await copy(newer) == "genuine"

    # A record changed behind the app's back: the page and the copy check both say so.
    await db.execute(
        text(
            "UPDATE submissions SET data = jsonb_set(data, '{full_name}', '\"X\"') WHERE id = :id"
        ),
        {"id": sid},
    )
    await db.commit()
    assert (await client.get(f"/api/v1/public/verify/{token}")).json()["state"] == "changed"
    assert await copy(newer) == "changed"

    # Unknown, short and deleted: not found.
    assert (await client.get("/api/v1/public/verify/nope")).status_code == 404
    assert (await client.get(f"/api/v1/public/verify/{'x' * 22}")).status_code == 404
    await db.execute(text("UPDATE submissions SET deleted_at = now() WHERE id = :id"), {"id": sid})
    await db.commit()
    assert (await client.get(f"/api/v1/public/verify/{token}")).status_code == 404


async def test_verify_needs_a_signed_pdf(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me)
    sid = await _submit(client, pub)
    await db.execute(
        text("UPDATE submissions SET verify_token = 'abcdefghijklmnopqrstuv' WHERE id = :id"),
        {"id": sid},
    )
    await db.commit()
    # A token without a signed PDF yet is not a document anyone holds.
    assert (await client.get("/api/v1/public/verify/abcdefghijklmnopqrstuv")).status_code == 404


async def test_dhivehi_pdf_renders(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me, language="dv")
    sid = await _submit(client, pub, name="ޢާއިޝަތު ޢަލީ")
    pdf = await _pdf(db, file_storage, settings, sid)
    assert b"NotoSansThaana" in pdf
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    res = await client.get(f"/api/v1/public/verify/{sub.verify_token}")
    # The verify page is system text only (English): it no longer needs the form's language.
    assert res.json()["state"] == "genuine" and "language" not in res.json()
