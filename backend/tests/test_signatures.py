"""Signatures, the content hash and event chain, and signed PDFs (DESIGN 9)."""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.config import Settings
from app.integrity import verify_submission
from app.models import (
    EventType,
    FormPermission,
    FormRole,
    PdfStatus,
    Signature,
    Submission,
    SubmissionEvent,
    User,
)
from app.pdf.service import check_pdf_against_db, generate_pdf
from app.pdf.sign import check_pdf
from app.signatures.render import SignatureError, parse_strokes, render_png, render_svg
from app.signing.keys import signing_identity
from app.storage import Storage
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import Published, admin_client, field, publish

STATEMENT = "I confirm the information in this form is true."


def strokes(n: int = 40, scale: float = 0.6) -> list[list[list[float]]]:
    """A wavy line across the pad, as the pad sends it: [x, y, t, pressure]."""
    return [
        [
            [
                round(0.1 + scale * i / n, 4),
                round(0.5 + 0.2 * math.sin(i / 3), 4),
                i * 16,
                0.5,
            ]
            for i in range(n)
        ]
    ]


def signature_value(**extra: Any) -> dict[str, Any]:
    return {
        "strokes": strokes(),
        "width": 360,
        "height": 176,
        "dpr": 3,
        "signedAt": "2026-10-23T08:15:02.000Z",
        **extra,
    }


# -- strokes and rendering -------------------------------------------------------------------


def test_strokes_are_validated() -> None:
    ok = parse_strokes(strokes(), 360, 176)
    assert ok.pad_width == 360 and len(ok.strokes[0]) == 40 and len(ok.sha256) == 64
    with pytest.raises(SignatureError) as dot:
        parse_strokes([[[0.5, 0.5, i, 0.5] for i in range(20)]], 360, 176)
    assert dot.value.code == "signature_small"
    with pytest.raises(SignatureError) as few:
        parse_strokes([[[0.1, 0.1, 0, 0.5], [0.9, 0.9, 5, 0.5]]], 360, 176)
    assert few.value.code == "signature_small"
    for bad in (
        [[[1.5, 0.5, 0, 0.5]] * 20],  # off the pad
        [[["a", 0.5, 0, 0.5]] * 20],
        [],
        "strokes",
        [[[0.1, 0.1]]],
    ):
        with pytest.raises(SignatureError) as exc:
            parse_strokes(bad, 360, 176)
        assert exc.value.code == "signature_invalid"
    with pytest.raises(SignatureError):
        parse_strokes(strokes(), 10, 176)  # impossible pad size


def test_rendering_is_deterministic() -> None:
    a = parse_strokes(strokes(), 360, 176)
    b = parse_strokes(strokes(), 360, 176)
    assert a.sha256 == b.sha256
    assert render_png(a) == render_png(b)
    assert render_svg(a) == render_svg(b)
    assert render_png(a).startswith(b"\x89PNG")
    assert b"<path" in render_svg(a)
    # Different strokes, different hash and image.
    c = parse_strokes(strokes(scale=0.7), 360, 176)
    assert c.sha256 != a.sha256 and render_png(c) != render_png(a)


# -- submit, audit trail, integrity ----------------------------------------------------------


async def _signed_form(client: AsyncClient, me: dict[str, Any], language: str = "en") -> Published:
    return await publish(
        client,
        me,
        [
            field("full_name", required=True, label="Full name"),
            field("sign", "signature", required=True, label="Signature", attestation=STATEMENT),
        ],
        title="Declaration",
        language=language,
    )


async def _submit(client: AsyncClient, pub: Published, name: str = "Aminath Ali") -> str:
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"full_name": name, "sign": signature_value()}),
        headers={"User-Agent": "TestBrowser/1.0"},
    )
    assert res.status_code == 201, res.text
    page = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()
    return str(page["items"][0]["id"])


async def test_signature_audit_trail(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me)

    # A dot is refused with the field's problem code.
    dot = {**signature_value(), "strokes": [[[0.5, 0.5, i, 0.5] for i in range(20)]]}
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body({"full_name": "A", "sign": dot})
    )
    assert res.status_code == 422
    assert res.json()["errors"] == [{"field": "sign", "code": "signature_small"}]

    sid = await _submit(client, pub)
    assert ("render_submission_pdf", {"submission_id": sid}) in queue.jobs

    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    sig_id = detail["data"]["sign"]["signatureId"]
    assert detail["pdfStatus"] == "pending"
    assert len(detail["contentHash"]) == 64
    [sig] = detail["signatures"]
    assert sig["id"] == sig_id and sig["attestation"] == STATEMENT
    assert sig["userAgent"] == "TestBrowser/1.0" and sig["ip"] == "127.0.0.1"
    assert sig["signedAt"].startswith("2026-10-23T08:15:02")
    assert [e["type"] for e in detail["events"]] == ["created"]

    row = await db.get(Signature, uuid.UUID(sig_id))
    assert row is not None and row.strokes == strokes() and row.pad_width == 360
    res = await client.get(sig["imageUrl"])
    assert res.status_code == 200 and res.content.startswith(b"\x89PNG")
    assert res.content == render_png(parse_strokes(strokes(), 360, 176))

    res = await client.get(f"/api/v1/submissions/{sid}/verify")
    assert res.json() == {
        "ok": True,
        "contentOk": True,
        "chainOk": True,
        "chainLength": 1,
        "brokenAt": None,
        "problems": [],
    }

    # Status changes extend the chain.
    res = await client.patch(f"/api/v1/submissions/{sid}", json={"status": "approved"})
    assert [e["type"] for e in res.json()["events"]] == ["status_changed", "created"]
    assert res.json()["events"][0]["payload"] == {"from": "new", "to": "approved"}
    assert (await client.get(f"/api/v1/submissions/{sid}/verify")).json()["chainLength"] == 2

    # A direct database edit of the answers breaks the content hash...
    await db.execute(
        text("UPDATE submissions SET data = jsonb_set(data, '{full_name}', '\"Someone\"')")
    )
    await db.commit()
    v = (await client.get(f"/api/v1/submissions/{sid}/verify")).json()
    assert v["ok"] is False and v["contentOk"] is False and "content_hash_mismatch" in v["problems"]


async def test_event_chain_detects_edits(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("q")])
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"q": "x"}))
    assert res.status_code == 201
    sid = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()["items"][0]["id"]
    for st in ("in_review", "approved"):
        await client.patch(f"/api/v1/submissions/{sid}", json={"status": st})
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    assert (await verify_submission(db, sub)).ok

    await db.execute(
        text(
            'UPDATE submission_events SET payload = \'{"from": "new", "to": "rejected"}\' '
            "WHERE seq = 2"
        )
    )
    await db.commit()
    v = await verify_submission(db, sub)
    assert not v.chain_ok and v.broken_at == 2 and v.content_ok

    # Deleting an event is caught too.
    await db.execute(text("DELETE FROM submission_events WHERE seq = 2"))
    await db.commit()
    assert (await verify_submission(db, sub)).broken_at == 3


# -- signed PDF ------------------------------------------------------------------------------


async def test_signed_pdf_end_to_end(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me)
    sid = await _submit(client, pub)
    assert (await client.get(f"/api/v1/submissions/{sid}/pdf")).status_code == 404

    # The worker job renders, signs and stores it.
    assert await generate_pdf(db, file_storage, settings, uuid.UUID(sid))
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["pdfStatus"] == "ready"
    assert detail["events"][0]["type"] == "pdf_generated"
    res = await client.get(f"/api/v1/submissions/{sid}/pdf")
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    pdf = res.content
    assert pdf.startswith(b"%PDF")
    assert detail["events"][0]["payload"]["sha256"] == __import__("hashlib").sha256(pdf).hexdigest()

    check = await check_pdf(pdf)
    assert check.signed and check.intact and check.covers_whole_file
    assert check.submission_id == sid and check.content_hash == detail["contentHash"]
    ident = await signing_identity(db, settings)
    assert check.signer_fingerprint == ident.fingerprint

    # Check a PDF: genuine.
    res = await client.post("/api/v1/pdf-checks", content=pdf)
    body = res.json()
    assert body["verdict"] == "genuine" and body["trustedSigner"] is True
    assert body["submission"]["seq"] == 1 and body["submission"]["formTitle"] == "Declaration"

    # Any byte edit inside the signed range breaks it.
    i = pdf.index(b"Declaration")
    edited = pdf[:i] + b"Dexlaration" + pdf[i + len(b"Declaration") :]
    assert (await client.post("/api/v1/pdf-checks", content=edited)).json()["verdict"] == "modified"
    # Appending an update after signing is reported too.
    appended = pdf + b"\n% extra\n"
    assert (await check_pdf(appended)).intact
    # Not a PDF / not signed.
    assert (await client.post("/api/v1/pdf-checks", content=b"hello")).json()["verdict"] == (
        "unsigned"
    )

    # The CLI: genuine now (exit 0), then a modified database row is detected (exit 1).
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert await cli._verify_pdf(pdf) == 0
    assert "Genuine and unchanged" in capsys.readouterr().out
    await db.execute(text("UPDATE submissions SET data = jsonb_set(data, '{full_name}', '\"X\"')"))
    await db.commit()
    assert await cli._verify_pdf(pdf) == 1
    assert "no longer matches" in capsys.readouterr().out
    report = await check_pdf_against_db(db, settings, pdf)
    assert report.verdict == "data_changed"

    # A PDF signed by some other key is not ours.
    from app.models import SigningKey

    await db.execute(text("DELETE FROM signing_keys"))
    await db.commit()
    assert (await check_pdf_against_db(db, settings, pdf)).verdict == "not_ours"
    assert (await db.scalar(select(SigningKey))) is None


async def test_dhivehi_pdf_embeds_thaana_font(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _signed_form(client, me, language="dv")
    sid = await _submit(client, pub, name="ޢާއިޝަތު ޢަލީ")
    assert await generate_pdf(db, file_storage, settings, uuid.UUID(sid))
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None and sub.signed_pdf_key
    pdf = await file_storage.read(sub.signed_pdf_key)
    assert b"NotoSansThaana" in pdf
    assert (await check_pdf(pdf)).intact


async def test_pdf_on_demand_and_permissions(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("q")])
    await client.post(f"{pub.base}/submissions", json=pub.submit_body({"q": "x"}))
    sid = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()["items"][0]["id"]
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["pdfStatus"] == "none" and detail["signatures"] == []
    assert not [j for j in queue.jobs if j[0] == "render_submission_pdf"]

    res = await client.post(f"/api/v1/submissions/{sid}/pdf")
    assert res.json() == {"pdfStatus": "pending"}
    assert ("render_submission_pdf", {"submission_id": sid}) in queue.jobs
    # Asking twice does not queue twice.
    await client.post(f"/api/v1/submissions/{sid}/pdf")
    assert len([j for j in queue.jobs if j[0] == "render_submission_pdf"]) == 1
    assert await generate_pdf(db, file_storage, settings, uuid.UUID(sid))
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    await db.refresh(sub)
    assert sub.pdf_status == PdfStatus.READY

    events = (
        await db.scalars(select(SubmissionEvent).where(SubmissionEvent.submission_id == sub.id))
    ).all()
    assert {e.type for e in events} == {EventType.CREATED, EventType.PDF_GENERATED}

    for role in ("viewer", None):
        email = f"{role or 'outsider'}@example.org"
        user = User(email=email)
        db.add(user)
        await db.flush()
        if role:
            db.add(FormPermission(form_id=pub.id, user_id=user.id, role=FormRole(role)))
        await db.commit()
        async with make_client(app) as other:
            await login(other, queue, email)
            want = 200 if role else 404
            assert (await other.get(f"/api/v1/submissions/{sid}/verify")).status_code == want
            assert (await other.get(f"/api/v1/submissions/{sid}/pdf")).status_code == want
            check = await other.post(
                "/api/v1/pdf-checks", content=await file_storage.read(sub.signed_pdf_key or "")
            )
            assert check.json()["verdict"] == ("genuine" if role else "not_found")
