"""Phase 4: webhooks (signing, retries, SSRF guard, delivery log) and notification emails."""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    DeliveryStatus,
    EmailDelivery,
    PdfStatus,
    Submission,
    Webhook,
    WebhookDelivery,
)
from app.notifications import emails, events, webhooks
from app.notifications.ssrf import UrlRefused, check_static, is_public, resolve
from app.schemas.form import Form
from app.storage import Storage
from tests.conftest import RecordingQueue, make_client
from tests.helpers import Published, admin_client, field, publish

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "spec/webhooks/signature-v1.json").read_text(encoding="utf-8"))
RECEIVER = "https://203.0.113.10/hooks/justforms"  # TEST-NET-3, allowlisted in these tests


@pytest.fixture
def hook_settings(settings: Settings) -> Settings:
    settings.webhook_allowed_cidrs = ["203.0.113.0/24"]
    return settings


def _reference_verifier() -> Any:
    spec = importlib.util.spec_from_file_location("verify", ROOT / "docs/webhooks/verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify


def test_signature_vectors_and_reference_verifier() -> None:
    body = VECTORS["body"].encode()
    h = VECTORS["headers"]
    ts = int(h["JustForms-Webhook-Timestamp"])
    assert (
        webhooks.sign(VECTORS["secret"], h["JustForms-Webhook-Id"], ts, body)
        == VECTORS["expectedSignature"]
    )
    assert (
        webhooks.signature_header(
            [VECTORS["secret"], VECTORS["previousSecret"]], h["JustForms-Webhook-Id"], ts, body
        )
        == h["JustForms-Webhook-Signature"]
    )
    verify = _reference_verifier()
    now = VECTORS["now"]
    assert verify(VECTORS["secret"], h, body, now=now)
    assert verify(VECTORS["previousSecret"], h, body, now=now)  # during a rotation
    assert webhooks.verify(VECTORS["secret"], h, body, now=now)
    assert not verify("whsec_wrong", h, body, now=now)
    assert not verify(VECTORS["secret"], h, body + b" ", now=now)
    assert not verify(VECTORS["secret"], h, body, now=ts + 301)  # replayed later


def test_ssrf_guard(settings: Settings) -> None:
    for addr in ("10.0.0.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fd00::1"):
        assert not is_public(ipaddress.ip_address(addr)), addr
    assert not is_public(ipaddress.ip_address("::ffff:10.0.0.1"))
    assert is_public(ipaddress.ip_address("93.184.216.34"))
    for url, code in [
        ("https://10.0.0.5/x", "private_address"),
        ("http://93.184.216.34/x", "https_required"),
        ("http://hooks.example.org/x", "https_required"),
        ("ftp://hooks.example.org/x", "invalid_url"),
        ("https://user:pw@hooks.example.org/x", "invalid_url"),
    ]:
        with pytest.raises(UrlRefused) as exc:
            check_static(url, settings)
        assert exc.value.code == code, url
    check_static("https://hooks.example.org/x", settings)
    allow = settings.model_copy(update={"webhook_allowed_cidrs": ["10.0.0.0/8"]})
    check_static("http://10.0.0.5/x", allow)
    check_static("http://receiver.internal/x", allow)  # checked again at delivery time


async def test_ssrf_resolve_blocks_private_names(settings: Settings) -> None:
    with pytest.raises(UrlRefused) as exc:
        await resolve("https://localhost/x", settings)
    assert exc.value.code == "private_address"
    allow = settings.model_copy(update={"webhook_allowed_cidrs": ["127.0.0.0/8", "::1/128"]})
    target = await resolve("http://localhost:9000/x", allow)
    assert ipaddress.ip_address(target.address).is_loopback and target.port == 9000


async def _setup(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> tuple[Published, dict[str, Any]]:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(
        client,
        me,
        [
            field("name", label="Full name"),
            field("email", "email", label="Email"),
            field("nid", label="National ID", sensitive=True),
        ],
        title="Applications",
    )
    return pub, me


async def _submit(client: AsyncClient, pub: Published, db: AsyncSession) -> Submission:
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"name": "Aminath", "email": "aminath@example.org", "nid": "A1"}),
    )
    assert res.status_code == 201, res.text
    sub = await db.scalar(
        select(Submission)
        .where(Submission.form_id == uuid.UUID(pub.id))
        .order_by(Submission.seq.desc())
    )
    assert sub is not None
    return sub


class Receiver:
    """A fake endpoint: records requests, answers with the scripted status codes."""

    def __init__(self, *codes: int) -> None:
        self.codes = list(codes)
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            code = self.codes.pop(0) if self.codes else 200
            if code == 0:
                raise httpx.ConnectError("refused")
            return httpx.Response(code, text="ok" if code < 300 else "down")

        return httpx.MockTransport(handle)


async def test_webhook_api_and_delivery(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    hook_settings: Settings,
    queue: RecordingQueue,
) -> None:
    settings = hook_settings
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/webhooks"
    res = await client.post(
        url, json={"url": "https://10.1.2.3/x", "events": ["submission.created"]}
    )
    assert res.status_code == 422 and res.json()["detail"] == "private_address"
    res = await client.post(
        url,
        json={"url": RECEIVER, "events": ["submission.created", "submission.pdf_ready"]},
    )
    assert res.status_code == 201, res.text
    secret = res.json()["secret"]
    hook_id = res.json()["webhook"]["id"]
    assert secret.startswith("whsec_")
    listed = (await client.get(url)).json()
    assert [h["url"] for h in listed] == [RECEIVER] and "secret" not in listed[0]
    stored = await db.get(Webhook, uuid.UUID(hook_id))
    assert stored is not None and secret.encode() not in stored.secret_enc

    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    assert len(jobs.webhook_deliveries) == 1
    receiver = Receiver(200)
    retry, disabled = await webhooks.deliver(
        db, settings, jobs.webhook_deliveries[0], transport=receiver.transport()
    )
    assert retry is None and disabled is None
    request = receiver.requests[0]
    assert request.url.host == "203.0.113.10" and request.headers["host"] == "203.0.113.10"
    body = request.content
    payload = json.loads(body)
    assert payload["type"] == "submission.created"
    assert payload["submission"]["data"]["nid"] == "[redacted]"
    assert payload["submission"]["data"]["name"] == "Aminath"
    assert payload["submission"]["reference"] == f"#{sub.seq:04d}"
    assert _reference_verifier()(secret, dict(request.headers), body)

    deliveries = (await client.get(f"{url}/{hook_id}/deliveries")).json()
    assert deliveries[0]["status"] == "succeeded" and deliveries[0]["responseCode"] == 200

    # Redeliver sends the same event id and body again.
    res = await client.post(f"{url}/{hook_id}/deliveries/{deliveries[0]['id']}/redeliver")
    assert res.status_code == 202 and res.json()["eventId"] == deliveries[0]["eventId"]
    assert queue.jobs[-1][0] == "deliver_webhook"
    # Test event.
    res = await client.post(f"{url}/{hook_id}/test")
    assert res.status_code == 202 and res.json()["event"] == "test"

    # Rotation: both signatures for 24 hours.
    rotated = (await client.post(f"{url}/{hook_id}/rotate-secret")).json()
    assert rotated["secret"] != secret and rotated["webhook"]["rotatingUntil"]
    await db.refresh(stored)  # the API rotated it in another session
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    receiver = Receiver(204)
    await webhooks.deliver(db, settings, jobs.webhook_deliveries[0], transport=receiver.transport())
    req = receiver.requests[0]
    assert req.headers["justforms-webhook-signature"].count("v1=") == 2
    verify = _reference_verifier()
    assert verify(secret, dict(req.headers), req.content)
    assert verify(rotated["secret"], dict(req.headers), req.content)

    # Status changes go only to webhooks subscribed to them.
    jobs = await events.dispatch(db, settings, "submission.status_changed", sub.id)
    assert jobs.webhook_deliveries == []

    # Viewers can't manage webhooks; owners can switch them off and delete them.
    res = await client.patch(f"{url}/{hook_id}", json={"enabled": False})
    assert res.json()["enabled"] is False
    assert (await client.delete(f"{url}/{hook_id}")).status_code == 204
    anon = make_client(app)
    assert (await anon.get(url)).status_code == 401


async def test_webhook_retries_until_receiver_recovers(
    client: AsyncClient, db: AsyncSession, hook_settings: Settings, queue: RecordingQueue
) -> None:
    """A receiver down for 3 hours gets the event once it is back (DESIGN 20, Phase 4)."""
    settings = hook_settings
    pub, _me = await _setup(client, db, settings, queue)
    res = await client.post(
        f"/api/v1/forms/{pub.id}/webhooks",
        json={"url": RECEIVER, "events": ["submission.created"]},
    )
    assert res.status_code == 201
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    delivery_id = jobs.webhook_deliveries[0]
    # Down (503, refused, 502, 504, 500) for more than three hours, then up again.
    receiver = Receiver(503, 0, 502, 504, 500, 200)
    waited = 0
    retries = []
    while True:
        retry, _disabled = await webhooks.deliver(
            db, settings, delivery_id, transport=receiver.transport()
        )
        if retry is None:
            break
        retries.append(retry)
        waited += retry
    assert retries == [60, 300, 1800, 7200, 21600]
    assert waited > 3 * 3600  # covers a 3-hour outage
    row = await db.get(WebhookDelivery, delivery_id)
    assert row is not None
    await db.refresh(row)
    assert row.status == DeliveryStatus.SUCCEEDED and row.attempt == 6
    hook = await db.get(Webhook, row.webhook_id)
    assert hook is not None and hook.consecutive_failures == 0


async def test_webhook_gives_up_and_auto_disables(
    client: AsyncClient, db: AsyncSession, hook_settings: Settings, queue: RecordingQueue
) -> None:
    settings = hook_settings
    pub, _me = await _setup(client, db, settings, queue)
    res = await client.post(
        f"/api/v1/forms/{pub.id}/webhooks",
        json={"url": RECEIVER, "events": ["submission.created"]},
    )
    hook_id = uuid.UUID(res.json()["webhook"]["id"])
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    receiver = Receiver(*([500] * 8))
    delays = []
    for _ in range(8):
        retry, _ = await webhooks.deliver(
            db, settings, jobs.webhook_deliveries[0], transport=receiver.transport()
        )
        delays.append(retry)
    assert delays == [60, 300, 1800, 7200, 21600, 43200, 86400, None]
    row = await db.get(WebhookDelivery, jobs.webhook_deliveries[0])
    assert row is not None
    await db.refresh(row)
    assert row.status == DeliveryStatus.FAILED and row.error == "http_500"
    hook = await db.get(Webhook, hook_id)
    assert hook is not None
    hook.consecutive_failures = 19
    await db.commit()
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    disabled = None
    for _ in range(8):
        _, disabled = await webhooks.deliver(
            db, settings, jobs.webhook_deliveries[0], transport=Receiver(*([500] * 8)).transport()
        )
    assert disabled is not None and disabled.enabled is False
    assert disabled.disabled_reason == "failures"
    email_ids = await events.webhook_disabled(db, disabled)
    rows = [await db.get(EmailDelivery, i) for i in email_ids]
    assert [r.to_address for r in rows if r] == ["admin@example.org"]
    msg = await events.render_email(db, settings, None, rows[0])  # type: ignore[arg-type]
    assert msg is not None and RECEIVER in msg.text
    # A private address is refused at delivery time even if it was saved earlier.
    hook.url = "https://10.9.9.9/x"
    hook.enabled = True
    await db.commit()
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    await webhooks.deliver(db, settings, jobs.webhook_deliveries[0])
    row = await db.get(WebhookDelivery, jobs.webhook_deliveries[0])
    assert row is not None
    await db.refresh(row)
    assert row.error == "private_address" and row.response_code is None


async def test_owner_email_and_receipt(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/notifications"
    info = (await client.get(url)).json()
    assert info["smtpEnabled"] is False and info["emailFields"] == [
        {"id": "email", "label": "Email"}
    ]
    res = await client.put(
        f"{url}/owner_email",
        json={"enabled": True, "recipients": ["Team@Example.org"], "includeAnswers": True},
    )
    assert res.status_code == 200 and res.json()["ownerEmail"]["recipients"] == ["team@example.org"]
    res = await client.put(
        f"{url}/respondent_receipt",
        json={"enabled": True, "emailField": "nope"},
    )
    assert res.status_code == 422
    await client.put(
        f"{url}/respondent_receipt",
        json={
            "enabled": True,
            "emailField": "email",
            "attachPdf": True,
            "toUnverified": True,
            "unverifiedAnswers": True,
        },
    )
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    rows = [await db.get(EmailDelivery, i) for i in jobs.emails]
    assert sorted((r.kind, r.to_address) for r in rows if r) == [
        ("owner_new", "team@example.org"),
        ("receipt", "aminath@example.org"),
    ]
    owner_row = next(r for r in rows if r and r.kind == "owner_new")
    msg = await events.render_email(db, settings, file_storage, owner_row)
    assert msg is not None and "Aminath" in msg.text and "A1" not in msg.text
    assert msg.html and f"open={sub.id}" in msg.html
    receipt_row = next(r for r in rows if r and r.kind == "receipt")
    msg = await events.render_email(db, settings, file_storage, receipt_row)
    assert msg is not None and msg.attachments == []  # no signature: no PDF
    # Dispatching again doesn't send a second receipt.
    again = await events.dispatch(db, settings, "submission.created", sub.id)
    assert [(await db.get(EmailDelivery, i)).kind for i in again.emails] == ["owner_new"]  # type: ignore[union-attr]


async def test_receipt_waits_for_pdf(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    await client.put(
        f"/api/v1/forms/{pub.id}/notifications/respondent_receipt",
        json={
            "enabled": True,
            "emailField": "email",
            "attachPdf": True,
            "toUnverified": True,
            "unverifiedAnswers": True,
        },
    )
    sub = await _submit(client, pub, db)
    sub.pdf_status = PdfStatus.PENDING
    await db.commit()
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    assert jobs.emails == []
    await file_storage.put("pdfs/x.pdf", b"%PDF-1.7 test", content_type="application/pdf")
    sub.pdf_status = PdfStatus.READY
    sub.signed_pdf_key = "pdfs/x.pdf"
    await db.commit()
    jobs = await events.dispatch(db, settings, "submission.pdf_ready", sub.id)
    assert len(jobs.emails) == 1
    row = await db.get(EmailDelivery, jobs.emails[0])
    assert row is not None
    msg = await events.render_email(db, settings, file_storage, row)
    assert msg is not None
    assert msg.attachments == [
        (f"submission-{sub.seq:04d}.pdf", b"%PDF-1.7 test", "application/pdf")
    ]


def test_dv_emails_are_english_with_rtl_content() -> None:
    """System wording is English for every form; only form content is Dhivehi, marked RTL."""
    form = Form.model_validate(
        {
            "schemaVersion": "1",
            "settings": {"language": "dv", "title": "ފޯމު"},
            "pages": [
                {
                    "id": "p1",
                    "elements": [
                        {"kind": "field", "id": "n", "type": "short_text", "label": "ނަން"},
                    ],
                }
            ],
        }
    )
    msg = emails.receipt_message(
        org_name="Example",
        form=form,
        title="ފޯމު",
        reference="#0001",
        submitted=datetime(2026, 10, 23, 8, 0, tzinfo=UTC),
        tz=UTC,
        answers=emails.answers_for_email(form, {"n": "ޢަލީ"}),
        pdf=None,
    )
    # The Dhivehi title is isolated (FSI ... PDI) so "(#0001)" keeps its order in the subject.
    assert msg.subject == "Your response to \u2068ފޯމު\u2069 (#0001)"
    assert msg.html and "ޢަލީ" in msg.text
    assert "Thank you. We received your response" in msg.html and "Reference: " in msg.text
    # The title and the answers carry the form's language and direction; the email is LTR.
    assert 'lang="dv" dir="rtl" align="right">ފޯމު</h1>' in msg.html
    assert 'lang="dv" dir="rtl">' in msg.html and '<html lang="en">' in msg.html
    code = emails.code_message(org_name="", title="ފޯމު", language="dv", code="123456", minutes=10)
    assert code.subject == "Your code for \u2068ފޯމު\u2069"
    assert "Your code is 123456. It works for 10 minutes." in code.text
    assert code.html and 'lang="dv" dir="rtl"' in code.html
    # No Thaana outside the form's own content.
    thaana = [c for c in code.text.replace("ފޯމު", "") if "\u0780" <= c <= "\u07bf"]
    assert thaana == []


async def test_due_deliveries_sweeper(
    client: AsyncClient, db: AsyncSession, hook_settings: Settings, queue: RecordingQueue
) -> None:
    pub, _me = await _setup(client, db, hook_settings, queue)
    await client.post(
        f"/api/v1/forms/{pub.id}/webhooks", json={"url": RECEIVER, "events": ["submission.created"]}
    )
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, hook_settings, "submission.created", sub.id)
    later = datetime.now(UTC) + timedelta(minutes=5)
    assert await webhooks.due_deliveries(db, later) == jobs.webhook_deliveries


def test_dv_approval_emails_isolate_form_content() -> None:
    form = Form.model_validate(
        {
            "schemaVersion": "1",
            "settings": {"language": "dv", "title": "ފޯމު"},
            "pages": [{"id": "p1"}],
        }
    )
    msg = emails.approval_request_message(
        org_name="Example",
        form=form,
        title="ފޯމު",
        reference="#0007",
        submitted=datetime(2026, 10, 23, 8, 0, tzinfo=UTC),
        tz=UTC,
        step_name="ވެރިޔާ",
        step=1,
        total=2,
        url="https://forms.example/a/x",
        days=7,
    )
    assert msg.subject == "Approval needed: \u2068ފޯމު\u2069 (#0007)"
    assert msg.html is not None
    assert '<bdi lang="dv" dir="rtl">ވެރިޔާ</bdi>: please approve or reject response #0007' in msg.html
    assert "Step 1 of 2." in msg.text and "Or open the response" in msg.html
    assert "https://forms.example/a/x?decision=approve" in msg.html
    out = emails.outcome_message(
        org_name="Example",
        form=form,
        title="ފޯމު",
        reference="#0007",
        approved=False,
        comment="ނުފުދޭ",
        pdf=None,
    )
    assert out.subject == "Not approved: \u2068ފޯމު\u2069 (#0007)"
    assert out.html and "Your response #0007 was not approved." in out.html
    assert 'dir="auto">ނުފުދޭ' in out.html


async def test_custom_wording_reply_to_and_placeholders(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/notifications"
    # Placeholders must name something that can be filled; sensitive answers can't be used.
    for bad in ("{answer:nid}", "{answer:nope}", "{name}"):
        res = await client.put(
            f"{url}/respondent_receipt",
            json={"enabled": True, "emailField": "email", "message": f"Hi {bad}"},
        )
        assert res.status_code == 422, bad
        assert res.json()["detail"] == {"code": "unknown_placeholder", "placeholder": bad}
    res = await client.put(
        f"{url}/respondent_receipt",
        json={"enabled": True, "emailField": "email", "subject": "Line\nbreak"},
    )
    assert res.status_code == 422
    res = await client.put(
        f"{url}/owner_email",
        json={"enabled": True, "recipients": [f"r{i}@example.org" for i in range(11)]},
    )
    assert res.status_code == 422  # at most 10 extra addresses
    res = await client.put(
        f"{url}/respondent_receipt",
        json={
            "enabled": True,
            "emailField": "email",
            "toUnverified": True,
            "unverifiedAnswers": True,
            "subject": "We received {form_title} ({reference})",
            "message": "Dear {answer:name},\n\nThank you. <b>We'll be in touch.</b>",
            "replyTo": "Team@Example.org",
        },
    )
    assert res.status_code == 200, res.text
    rule = res.json()["respondentReceipt"]
    assert rule["replyTo"] == "team@example.org" and rule["subject"].startswith("We received")
    await client.put(
        f"{url}/owner_email",
        json={
            "enabled": True,
            "recipients": ["office@example.org"],
            "subject": "New application: {answer:name} ({reference})",
        },
    )
    sub = await _submit(client, pub, db)
    jobs = await events.dispatch(db, settings, "submission.created", sub.id)
    rows = {r.kind: r for r in [await db.get(EmailDelivery, i) for i in jobs.emails] if r}
    receipt = await events.render_email(db, settings, file_storage, rows["receipt"])
    assert receipt is not None and receipt.html is not None
    ref = f"#{sub.seq:04d}"
    assert receipt.subject == f"We received Applications ({ref})"
    assert receipt.reply_to == "team@example.org"
    assert "Dear Aminath,\n\nThank you." in receipt.text and "A1" not in receipt.text
    assert "&lt;b&gt;We&#39;ll be in touch.&lt;/b&gt;" in receipt.html  # plain text, escaped
    assert "Thank you. We received your response" not in receipt.text  # replaced intro
    assert f"Reference: {ref}" in receipt.text and "Aminath" in receipt.text
    owner = await events.render_email(db, settings, file_storage, rows["owner_new"])
    assert owner is not None and owner.subject == f"New application: Aminath ({ref})"
    assert owner.reply_to is None and "A1" not in owner.text
    # Clearing the wording goes back to the built-in text.
    await client.put(f"{url}/owner_email", json={"enabled": True, "subject": "  "})
    owner = await events.render_email(db, settings, file_storage, rows["owner_new"])
    assert owner is not None and owner.subject == f"New response to Applications ({ref})"


async def test_send_test_emails(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    pub, _me = await _setup(client, db, settings, queue)
    url = f"/api/v1/forms/{pub.id}/notifications"
    assert (await client.post(f"{url}/test")).status_code == 409  # no SMTP
    settings.smtp_host = "smtp.example.org"
    await client.put(
        f"{url}/owner_email",
        json={"enabled": True, "recipients": ["office@example.org"], "includeAnswers": True},
    )
    await client.put(
        f"{url}/respondent_receipt",
        json={
            "enabled": True,
            "emailField": "email",
            "subject": "Thanks, {answer:name} ({reference})",
            "replyTo": "team@example.org",
        },
    )
    queue.jobs.clear()
    res = await client.post(f"{url}/test")
    assert res.status_code == 202, res.text
    # Both go to the person asking, never to the recipients or a submission.
    rows = list(await db.scalars(select(EmailDelivery).where(EmailDelivery.kind.like("test_%"))))
    assert sorted((r.kind, r.to_address, r.submission_id) for r in rows) == [
        ("test_owner_new", "admin@example.org", None),
        ("test_receipt", "admin@example.org", None),
    ]
    assert [j[0] for j in queue.jobs] == ["send_form_email", "send_form_email"]
    msgs = {r.kind: await events.render_email(db, settings, file_storage, r) for r in rows}
    owner, receipt = msgs["test_owner_new"], msgs["test_receipt"]
    assert owner is not None and owner.subject == "[Test] New response to Applications (#0000)"
    assert "[Full name]" in owner.text and "National ID" not in owner.text
    assert receipt is not None and receipt.subject == "[Test] Thanks, [Full name] (#0000)"
    assert receipt.reply_to == "team@example.org" and receipt.attachments == []
    log = (await client.get(url)).json()["recent"]
    assert {e["kind"] for e in log} == {"test_owner_new", "test_receipt"}
