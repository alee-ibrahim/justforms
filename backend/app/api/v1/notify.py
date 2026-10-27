"""Per-form email notifications and webhooks (DESIGN 11, 17). Owners manage them; everyone
with access to the form can read the settings (webhook secrets are never readable)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import EmailStr, Field, StringConstraints
from sqlalchemy import select

from app import ratelimit
from app.api.v1.common import ApiModel
from app.auth.deps import DbDep, RedisDep, SettingsDep
from app.ids import uuid7
from app.logic.index import FormIndex
from app.models import (
    DeliveryStatus,
    EmailDelivery,
    EmailStatus,
    FormRole,
    NotificationRule,
    RuleType,
    Webhook,
    WebhookDelivery,
)
from app.notifications import emails
from app.notifications import webhooks as wh
from app.notifications.events import TEST_KINDS, email_fields, latest_schema
from app.notifications.ssrf import UrlRefused, check_static
from app.permissions import FormAccess, FormOwner, FormViewer, has_form_role
from app.queue import JobQueue, get_queue
from app.schemas.form import Form
from app.services.users import audit

router = APIRouter(tags=["notifications"])
QueueDep = Annotated[JobQueue, Depends(get_queue)]

EventName = Literal[
    "submission.created",
    "submission.status_changed",
    "submission.comment_added",
    "submission.pdf_ready",
    "submission.approval_step",
]


# -- email notifications --------------------------------------------------------------------


MAX_RECIPIENTS = 10


class RuleOut(ApiModel):
    enabled: bool = False
    recipients: list[str] = Field(default_factory=list)
    include_answers: bool = False
    attach_pdf: bool = False
    email_field: str | None = None
    subject: str | None = None
    message: str | None = None
    reply_to: str | None = None


Subject = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class RuleIn(ApiModel):
    enabled: bool
    recipients: list[EmailStr] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    include_answers: bool = False
    attach_pdf: bool = False
    email_field: Annotated[str, StringConstraints(max_length=63)] | None = None
    # Custom wording: plain text with {reference}, {form_title}, {submitted} and
    # {answer:<question key>}; empty or missing = the built-in text.
    subject: Subject | None = None
    message: Message | None = None
    reply_to: EmailStr | None = None


class EmailFieldOut(ApiModel):
    id: str
    label: str


class EmailLogOut(ApiModel):
    id: uuid.UUID
    kind: str
    to: str
    status: EmailStatus
    attempts: int
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class NotificationsOut(ApiModel):
    smtp_enabled: bool
    # Language of the email questions' labels (the form's language).
    language: str
    owner_email: RuleOut
    respondent_receipt: RuleOut
    email_fields: list[EmailFieldOut]
    has_signature: bool
    recent: list[EmailLogOut]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}•••@{domain}" if domain else "•••"


async def _latest_schema(db: DbDep, access: FormAccess) -> Form:
    return await latest_schema(db, access.form)


def _rule_out(rule: NotificationRule | None) -> RuleOut:
    if rule is None:
        return RuleOut()
    return RuleOut(
        enabled=rule.enabled,
        recipients=list(rule.recipients or []),
        include_answers=rule.include_answers,
        attach_pdf=rule.attach_pdf,
        email_field=rule.email_field,
        subject=rule.subject,
        message=rule.message,
        reply_to=rule.reply_to,
    )


async def _notifications(db: DbDep, settings: SettingsDep, access: FormAccess) -> NotificationsOut:
    form = access.form
    rules = {
        r.type: r
        for r in await db.scalars(
            select(NotificationRule).where(NotificationRule.form_id == form.id)
        )
    }
    schema = await _latest_schema(db, access)
    owner = access.role.value == "owner"
    recent = (
        list(
            await db.scalars(
                select(EmailDelivery)
                .where(EmailDelivery.form_id == form.id)
                .order_by(EmailDelivery.created_at.desc())
                .limit(10)
            )
        )
        if owner
        else []
    )
    return NotificationsOut(
        smtp_enabled=settings.smtp_enabled,
        language=schema.settings.language,
        owner_email=_rule_out(rules.get(RuleType.OWNER_EMAIL)),
        respondent_receipt=_rule_out(rules.get(RuleType.RESPONDENT_RECEIPT)),
        email_fields=[EmailFieldOut(id=f.id, label=f.label) for f in email_fields(schema)],
        has_signature=any(
            getattr(i.element, "type", None) == "signature"
            for i in FormIndex.build(schema).elements.values()
        ),
        recent=[
            EmailLogOut(
                id=e.id,
                kind=e.kind,
                to=(
                    mask_email(e.to_address)
                    if e.kind in ("receipt", "approval_outcome", "test_receipt")
                    else e.to_address
                ),
                status=e.status,
                attempts=e.attempts,
                error=e.last_error,
                created_at=e.created_at,
                sent_at=e.sent_at,
            )
            for e in recent
        ],
    )


@router.get("/forms/{form_id}/notifications", response_model=NotificationsOut)
async def get_notifications(
    db: DbDep, settings: SettingsDep, access: FormViewer
) -> NotificationsOut:
    return await _notifications(db, settings, access)


@router.put("/forms/{form_id}/notifications/{rule_type}", response_model=NotificationsOut)
async def put_notification(
    rule_type: RuleType, body: RuleIn, db: DbDep, settings: SettingsDep, access: FormOwner
) -> NotificationsOut:
    form = access.form
    rule = await db.scalar(
        select(NotificationRule).where(
            NotificationRule.form_id == form.id, NotificationRule.type == rule_type
        )
    )
    if rule is None:
        rule = NotificationRule(form_id=form.id, type=rule_type)
        db.add(rule)
    schema = await _latest_schema(db, access)
    if rule_type == RuleType.RESPONDENT_RECEIPT and body.email_field is not None:
        ids = {f.id for f in email_fields(schema)}
        if body.email_field not in ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_email_field")
    if body.subject and ("\n" in body.subject or "\r" in body.subject):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "subject_one_line")
    for text in (body.subject, body.message):
        bad = emails.unknown_placeholder(text or "", schema)
        if bad is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "unknown_placeholder", "placeholder": bad},
            )
    rule.enabled = body.enabled
    rule.recipients = (
        list(dict.fromkeys(str(r).lower() for r in body.recipients))
        if rule_type == RuleType.OWNER_EMAIL
        else []
    )
    rule.include_answers = body.include_answers if rule_type == RuleType.OWNER_EMAIL else False
    rule.attach_pdf = body.attach_pdf if rule_type == RuleType.RESPONDENT_RECEIPT else False
    rule.email_field = body.email_field if rule_type == RuleType.RESPONDENT_RECEIPT else None
    rule.subject = body.subject or None
    rule.message = body.message or None
    rule.reply_to = str(body.reply_to).lower() if body.reply_to else None
    await audit(
        db,
        "form.notifications",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={"type": rule_type.value, "enabled": body.enabled},
    )
    await db.commit()
    return await _notifications(db, settings, access)


@router.post(
    "/forms/{form_id}/notifications/test",
    response_model=NotificationsOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_test_emails(
    db: DbDep,
    settings: SettingsDep,
    redis: RedisDep,
    queue: QueueDep,
    access: FormOwner,
) -> NotificationsOut:
    """Send both emails, with sample answers and "[Test]" in the subject, to the person
    asking (never to the configured recipients). Nothing is read from real submissions."""
    if not settings.smtp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "smtp_not_configured")
    await ratelimit.enforce(redis, settings, "notify_test", str(access.user.id))
    rows = [
        EmailDelivery(
            id=uuid.uuid4(),
            form_id=access.form.id,
            submission_id=None,
            kind=kind,
            to_address=access.user.email,
        )
        for kind in TEST_KINDS
    ]
    db.add_all(rows)
    await audit(
        db,
        "form.notifications_test",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=access.form.id,
    )
    await db.commit()
    for row in rows:
        await queue.enqueue("send_form_email", email_id=str(row.id))
    return await _notifications(db, settings, access)


# -- webhooks -------------------------------------------------------------------------------


class WebhookOut(ApiModel):
    id: uuid.UUID
    url: str
    events: list[str]
    enabled: bool
    include_sensitive: bool
    disabled_reason: str | None
    consecutive_failures: int
    rotating_until: datetime | None
    created_at: datetime


class WebhookWithSecret(ApiModel):
    webhook: WebhookOut
    secret: str


class WebhookIn(ApiModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2000)]
    events: list[EventName] = Field(min_length=1, max_length=4)
    include_sensitive: bool = False
    enabled: bool = True


class WebhookPatch(ApiModel):
    url: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2000)]
        | None
    ) = None
    events: list[EventName] | None = Field(default=None, min_length=1, max_length=4)
    include_sensitive: bool | None = None
    enabled: bool | None = None


class DeliveryOut(ApiModel):
    id: uuid.UUID
    event_id: str
    event: str
    status: DeliveryStatus
    attempt: int
    response_code: int | None
    response_snippet: str | None
    error: str | None
    duration_ms: int | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    payload: dict[str, Any]


def mask_url(url: str) -> str:
    """Scheme and host only: webhook paths and queries often carry a secret (catch URLs)."""
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"
    return f"{base}/…" if parts.path.strip("/") or parts.query or parts.fragment else base


def _hook_out(h: Webhook, *, owner: bool = True) -> WebhookOut:
    now = datetime.now(UTC)
    rotating = (
        h.previous_expires_at if h.previous_expires_at and h.previous_expires_at > now else None
    )
    return WebhookOut(
        id=h.id,
        url=h.url if owner else mask_url(h.url),
        events=list(h.events or []),
        enabled=h.enabled,
        include_sensitive=h.include_sensitive,
        disabled_reason=h.disabled_reason,
        consecutive_failures=h.consecutive_failures,
        rotating_until=rotating,
        created_at=h.created_at,
    )


def _check_url(url: str, settings: SettingsDep) -> None:
    try:
        check_static(url, settings)
    except UrlRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from exc


async def _hook(db: DbDep, access: FormAccess, webhook_id: uuid.UUID) -> Webhook:
    hook = await db.get(Webhook, webhook_id)
    if hook is None or hook.form_id != access.form.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhook_not_found")
    return hook


async def _audit(access: FormAccess, db: DbDep, action: str, hook: Webhook, **meta: Any) -> None:
    await audit(
        db,
        f"webhook.{action}",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="webhook",
        target_id=hook.id,
        meta={"url": hook.url, **meta},
    )


@router.get("/forms/{form_id}/webhooks", response_model=list[WebhookOut])
async def list_webhooks(db: DbDep, access: FormViewer) -> list[WebhookOut]:
    rows = await db.scalars(
        select(Webhook).where(Webhook.form_id == access.form.id).order_by(Webhook.created_at)
    )
    # Only owners manage webhooks; others see where they go, not the secret-bearing path.
    owner = has_form_role(access.role, FormRole.OWNER)
    return [_hook_out(h, owner=owner) for h in rows]


@router.post(
    "/forms/{form_id}/webhooks",
    response_model=WebhookWithSecret,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    body: WebhookIn, db: DbDep, settings: SettingsDep, access: FormOwner
) -> WebhookWithSecret:
    _check_url(body.url, settings)
    count = len(list(await db.scalars(select(Webhook.id).where(Webhook.form_id == access.form.id))))
    if count >= 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_many_webhooks")
    secret = wh.new_secret()
    hook = Webhook(
        id=uuid7(),
        form_id=access.form.id,
        url=body.url,
        secret_enc=wh.encrypt(settings, secret),
        events=list(dict.fromkeys(body.events)),
        include_sensitive=body.include_sensitive,
        enabled=body.enabled,
        created_by=access.user.id,
    )
    db.add(hook)
    await db.flush()
    await _audit(access, db, "create", hook, events=hook.events)
    await db.commit()
    await db.refresh(hook)
    return WebhookWithSecret(webhook=_hook_out(hook), secret=secret)


@router.patch("/forms/{form_id}/webhooks/{webhook_id}", response_model=WebhookOut)
async def patch_webhook(
    webhook_id: uuid.UUID,
    body: WebhookPatch,
    db: DbDep,
    settings: SettingsDep,
    access: FormOwner,
) -> WebhookOut:
    hook = await _hook(db, access, webhook_id)
    if body.url is not None:
        _check_url(body.url, settings)
        hook.url = body.url
    if body.events is not None:
        hook.events = list(dict.fromkeys(body.events))
    if body.include_sensitive is not None:
        hook.include_sensitive = body.include_sensitive
    if body.enabled is not None:
        hook.enabled = body.enabled
        if body.enabled:
            hook.disabled_reason = None
            hook.consecutive_failures = 0
    await _audit(access, db, "update", hook, **body.model_dump(exclude_none=True, mode="json"))
    await db.commit()
    await db.refresh(hook)
    return _hook_out(hook)


@router.delete("/forms/{form_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: uuid.UUID, db: DbDep, access: FormOwner) -> Response:
    hook = await _hook(db, access, webhook_id)
    await _audit(access, db, "delete", hook)
    await db.delete(hook)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/forms/{form_id}/webhooks/{webhook_id}/rotate-secret", response_model=WebhookWithSecret
)
async def rotate_secret(
    webhook_id: uuid.UUID, db: DbDep, settings: SettingsDep, access: FormOwner
) -> WebhookWithSecret:
    hook = await _hook(db, access, webhook_id)
    secret = wh.rotate(settings, hook, datetime.now(UTC))
    await _audit(access, db, "rotate_secret", hook)
    await db.commit()
    await db.refresh(hook)
    return WebhookWithSecret(webhook=_hook_out(hook), secret=secret)


def _delivery_out(d: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut.model_validate(d)


async def _enqueue_delivery(queue: QueueDep, row: WebhookDelivery) -> None:
    await queue.enqueue(
        "deliver_webhook", delivery_id=str(row.id), _job_id=f"whd:{row.id}:{row.attempt}"
    )


@router.post(
    "/forms/{form_id}/webhooks/{webhook_id}/test",
    response_model=DeliveryOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_test(
    webhook_id: uuid.UUID, db: DbDep, access: FormOwner, queue: QueueDep
) -> DeliveryOut:
    hook = await _hook(db, access, webhook_id)
    event_id = wh.new_event_id()
    row = WebhookDelivery(
        id=uuid7(),
        webhook_id=hook.id,
        event_id=event_id,
        event=wh.TEST_EVENT,
        payload=wh.test_payload(access.form, event_id),
        next_attempt_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _enqueue_delivery(queue, row)
    return _delivery_out(row)


@router.get("/forms/{form_id}/webhooks/{webhook_id}/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    webhook_id: uuid.UUID,
    db: DbDep,
    access: FormOwner,
    before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[DeliveryOut]:
    hook = await _hook(db, access, webhook_id)
    query = select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id)
    if before is not None:
        query = query.where(WebhookDelivery.created_at < before)
    rows = await db.scalars(query.order_by(WebhookDelivery.created_at.desc()).limit(limit))
    return [_delivery_out(d) for d in rows]


@router.post(
    "/forms/{form_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/redeliver",
    response_model=DeliveryOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def redeliver(
    webhook_id: uuid.UUID,
    delivery_id: uuid.UUID,
    db: DbDep,
    access: FormOwner,
    queue: QueueDep,
) -> DeliveryOut:
    """Send the same event (same id and body) again as a new delivery."""
    hook = await _hook(db, access, webhook_id)
    src = await db.get(WebhookDelivery, delivery_id)
    if src is None or src.webhook_id != hook.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "delivery_not_found")
    if not hook.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "webhook_off")
    row = WebhookDelivery(
        id=uuid7(),
        webhook_id=hook.id,
        event_id=src.event_id,
        event=src.event,
        payload=src.payload,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _enqueue_delivery(queue, row)
    return _delivery_out(row)
