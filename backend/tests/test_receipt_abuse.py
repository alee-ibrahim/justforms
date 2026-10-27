"""Receipts go to confirmed addresses; typed addresses are opt-in, rate limited and get no
answers unless the owner allows them."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import EmailDelivery, EmailStatus, Submission
from app.notifications import events
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.test_notifications import _setup


async def _submit(
    client: AsyncClient, pub: Any, db: AsyncSession, email: str = "victim@example.net"
) -> Submission:
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"name": "Spam text", "email": email, "nid": "A1"}),
    )
    assert res.status_code == 201, res.text
    sub = await db.scalar(
        select(Submission)
        .where(Submission.form_id == uuid.UUID(pub.id))
        .order_by(Submission.seq.desc())
    )
    assert sub is not None
    return sub


async def _receipts(db: AsyncSession, jobs: events.Jobs) -> list[EmailDelivery]:
    rows = [await db.get(EmailDelivery, i) for i in jobs.emails]
    return [r for r in rows if r is not None and r.kind == "receipt"]


async def test_typed_address_gets_no_receipt_by_default(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/notifications/respondent_receipt"
    res = await client.put(url, json={"enabled": True, "emailField": "email"})
    rule = res.json()["respondentReceipt"]
    assert rule["toUnverified"] is False and rule["unverifiedAnswers"] is False
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    assert await _receipts(db, jobs) == []
    # Answers can't be allowed without the opt-in.
    res = await client.put(
        url, json={"enabled": True, "emailField": "email", "unverifiedAnswers": True}
    )
    assert res.json()["respondentReceipt"]["unverifiedAnswers"] is False


async def test_typed_address_receipt_is_bare_and_rate_limited(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/notifications/respondent_receipt"
    res = await client.put(
        url,
        json={
            "enabled": True,
            "emailField": "email",
            "toUnverified": True,
            "attachPdf": True,
            "message": "Hello {answer:name}",
        },
    )
    assert res.status_code == 200, res.text
    sent: list[EmailDelivery] = []
    for _ in range(4):
        sub = await _submit(client, pub, db)
        jobs = await events.dispatch(db, settings, "submission.created", sub.id)
        sent += await _receipts(db, jobs)
    # Three an hour per address; the fourth is logged as not sent.
    assert [r.to_address for r in sent] == ["victim@example.net"] * 3
    refused = await db.scalar(
        select(EmailDelivery).where(
            EmailDelivery.kind == "receipt", EmailDelivery.status == EmailStatus.FAILED
        )
    )
    assert refused is not None and "this address" in (refused.last_error or "")
    # The receipt is a confirmation with the reference: no answers, no attacker text.
    msg = await events.render_email(db, settings, file_storage, sent[0])
    assert msg is not None
    assert "Spam text" not in msg.text and "Spam text" not in (msg.html or "")
    assert "Reference: #0001" in msg.text and msg.attachments == []

    # The per-form cap applies across addresses.
    capped = settings.model_copy(update={"receipt_unverified_per_hour": 4})
    sub = await _submit(client, pub, db, email="other@example.net")
    assert (
        len(await _receipts(db, await events.dispatch(db, capped, "submission.created", sub.id)))
        == 0
    )
    other = await db.scalar(
        select(EmailDelivery).where(EmailDelivery.to_address == "other@example.net")
    )
    assert other is not None and other.status == EmailStatus.FAILED

    # With the owner's opt-in, answers go too.
    res = await client.put(
        url,
        json={
            "enabled": True,
            "emailField": "email",
            "toUnverified": True,
            "unverifiedAnswers": True,
            "message": "Hello {answer:name}",
        },
    )
    msg = await events.render_email(db, settings, file_storage, sent[0])
    assert msg is not None and "Hello Spam text" in msg.text


async def test_confirmed_address_gets_full_receipt(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    await client.patch(f"/api/v1/forms/{pub.id}", json={"accessMode": "staff"})
    url = f"/api/v1/forms/{pub.id}/notifications/respondent_receipt"
    await client.put(url, json={"enabled": True})
    live = (await client.get(pub.base)).json()
    res = await client.post(
        f"{pub.base}/submissions",
        json={
            "versionId": live["versionId"],
            "data": {"name": "Aminath", "email": "x@example.net"},
            "uploadNonce": live["uploadNonce"],
        },
    )
    assert res.status_code == 201, res.text
    sub = await db.scalar(select(Submission).where(Submission.form_id == uuid.UUID(pub.id)))
    assert sub is not None
    rows = await _receipts(db, await events.dispatch(db, settings, "submission.created", sub.id))
    assert [r.to_address for r in rows] == ["admin@example.org"] and rows[0].detail is None
    msg = await events.render_email(db, settings, file_storage, rows[0])
    assert msg is not None and "Aminath" in msg.text
