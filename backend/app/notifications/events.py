"""Turning submission events into webhook deliveries and notification emails.

The API never sends anything itself (DESIGN 2): after committing a change it enqueues
``dispatch_event``; the worker calls :func:`dispatch` here, which writes the delivery rows
and returns the jobs to enqueue. Emails are rendered when they are sent
(:func:`render_email`), so nothing sensitive is stored in the queue or the email log.

Receipts that attach the signed PDF wait for it: on ``submission.created`` they are skipped
while the PDF is pending, and the PDF job dispatches ``submission.pdf_ready`` (or the internal
``pdf_failed``), which sends the receipt with (or without) the PDF.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    ApprovalState,
    ApprovalStep,
    EmailDelivery,
    EmailStatus,
    EventType,
    FormPermission,
    FormRecord,
    FormRole,
    FormVersion,
    NotificationRule,
    Organization,
    OrgMembership,
    OrgRole,
    PdfStatus,
    RuleType,
    StepState,
    Submission,
    SubmissionEvent,
    User,
    Webhook,
)
from app.notifications import emails
from app.notifications.webhooks import EVENTS, create_deliveries, submission_url
from app.schemas.form import EmailField, Form
from app.storage import Storage

log = logging.getLogger(__name__)

PDF_FAILED = "pdf_failed"  # internal: the receipt goes out without the PDF

# "Send test emails": each rule's email rendered with sample answers, to the person asking.
TEST_KINDS = {"test_owner_new": RuleType.OWNER_EMAIL, "test_receipt": RuleType.RESPONDENT_RECEIPT}
TEST_PREFIX = "[Test] "


def _submitted_text(when: datetime, tz: Any) -> str:
    return when.astimezone(tz).strftime("%d %b %Y %H:%M %Z")


def wording(
    rule: NotificationRule | None,
    *,
    title: str,
    reference: str,
    submitted: str,
    answers: dict[str, str],
    test: bool = False,
) -> emails.Wording:
    """The rule's custom subject and message with the placeholders filled in."""
    if rule is None:
        return emails.Wording()
    values = {"reference": reference, "form_title": title, "submitted": submitted}
    subject = emails.one_line(emails.fill(rule.subject, values, answers)) if rule.subject else None
    message = emails.fill(rule.message, values, answers).strip() if rule.message else None
    if test and subject:
        subject = TEST_PREFIX + subject
    return emails.Wording(subject=subject, message=message or None, reply_to=rule.reply_to)


@dataclass
class Jobs:
    webhook_deliveries: list[uuid.UUID] = field(default_factory=list)
    emails: list[uuid.UUID] = field(default_factory=list)


async def rules_for(db: AsyncSession, form_id: uuid.UUID) -> dict[RuleType, NotificationRule]:
    rows = await db.scalars(select(NotificationRule).where(NotificationRule.form_id == form_id))
    return {r.type: r for r in rows}


async def owner_addresses(db: AsyncSession, form: FormRecord) -> list[str]:
    """Explicit owners of the form; organisation admins when it has none."""
    owners = await db.scalars(
        select(User.email)
        .join(FormPermission, FormPermission.user_id == User.id)
        .where(FormPermission.form_id == form.id, FormPermission.role == FormRole.OWNER)
    )
    out = sorted(set(owners))
    if out:
        return out
    admins = await db.scalars(
        select(User.email)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.org_id == form.org_id, OrgMembership.role == OrgRole.ADMIN)
    )
    return sorted(set(admins))


def receipt_address(rule: NotificationRule, sub: Submission) -> str | None:
    if rule.email_field:
        value = sub.data.get(rule.email_field)
        return value.strip() if isinstance(value, str) and "@" in value else None
    return sub.respondent_email


async def _has_receipt(db: AsyncSession, sub: Submission) -> bool:
    found = await db.scalar(
        select(EmailDelivery.id).where(
            EmailDelivery.submission_id == sub.id, EmailDelivery.kind == "receipt"
        )
    )
    return found is not None


async def _outcome_due(db: AsyncSession, sub: Submission, event: str) -> bool:
    """The approval finished and its outcome email (with the PDF made after the last
    decision) hasn't gone out yet."""
    if sub.approval_state not in (ApprovalState.APPROVED, ApprovalState.REJECTED):
        return False
    if not sub.approval_outcome_to:
        return False
    sent = await db.scalar(
        select(EmailDelivery.id).where(
            EmailDelivery.submission_id == sub.id, EmailDelivery.kind == "approval_outcome"
        )
    )
    if sent is not None:
        return False
    if event == PDF_FAILED:
        return True
    last = dict(
        (
            await db.execute(
                select(SubmissionEvent.type, func.max(SubmissionEvent.seq))
                .where(
                    SubmissionEvent.submission_id == sub.id,
                    SubmissionEvent.type.in_([EventType.PDF_GENERATED, EventType.APPROVAL_DECIDED]),
                )
                .group_by(SubmissionEvent.type)
            )
        ).all()
    )
    return last.get(EventType.PDF_GENERATED, 0) > last.get(EventType.APPROVAL_DECIDED, 0)


def _email(form_id: uuid.UUID, sub_id: uuid.UUID | None, kind: str, to: str) -> EmailDelivery:
    return EmailDelivery(
        id=uuid.uuid4(), form_id=form_id, submission_id=sub_id, kind=kind, to_address=to
    )


async def dispatch(
    db: AsyncSession,
    settings: Settings,
    event: str,
    submission_id: uuid.UUID,
    *,
    extra: dict[str, Any] | None = None,
) -> Jobs:
    jobs = Jobs()
    sub = await db.get(Submission, submission_id)
    if sub is None or sub.deleted_at is not None:
        return jobs
    form = await db.get(FormRecord, sub.form_id)
    if form is None:
        return jobs
    if event in EVENTS:
        jobs.webhook_deliveries = await create_deliveries(db, settings, sub, event, extra=extra)
    rules = await rules_for(db, form.id)
    new_emails: list[EmailDelivery] = []
    owner = rules.get(RuleType.OWNER_EMAIL)
    if event == "submission.created" and owner is not None and owner.enabled:
        recipients = owner.recipients or await owner_addresses(db, form)
        new_emails += [_email(form.id, sub.id, "owner_new", to) for to in recipients]
    receipt = rules.get(RuleType.RESPONDENT_RECEIPT)
    if receipt is not None and receipt.enabled:
        to = receipt_address(receipt, sub)
        waits = receipt.attach_pdf and sub.pdf_status == PdfStatus.PENDING
        now = (event == "submission.created" and not waits) or (
            event in ("submission.pdf_ready", PDF_FAILED) and receipt.attach_pdf
        )
        if to and now and not await _has_receipt(db, sub):
            new_emails.append(_email(form.id, sub.id, "receipt", to))
    if event in ("submission.pdf_ready", PDF_FAILED) and await _outcome_due(db, sub, event):
        assert sub.approval_outcome_to
        new_emails.append(_email(form.id, sub.id, "approval_outcome", sub.approval_outcome_to))
    for row in new_emails:
        db.add(row)
    await db.commit()
    jobs.emails = [e.id for e in new_emails]
    return jobs


async def render_email(
    db: AsyncSession, settings: Settings, storage: Storage, row: EmailDelivery
) -> emails.Message | None:
    form = await db.get(FormRecord, row.form_id)
    if form is None:
        return None
    org = await db.get(Organization, form.org_id)
    from app.branding.service import email_brand, resolve

    brand = resolve(settings, org)
    org_name = brand.name
    from app.theme.resolve import form_email_brand

    eb = (
        form_email_brand(settings, org, form, None)
        if org is not None
        else email_brand(settings, brand)
    )
    if row.kind == "webhook_disabled":
        return emails.webhook_disabled_message(
            title=form.title,
            url=row.detail or "",
            failures=20,
            settings_url=emails.settings_url(settings, form.id),
        )
    if row.kind in TEST_KINDS:
        return await _test_message(db, settings, form, row.kind, org_name, eb)
    sub = await db.get(Submission, row.submission_id) if row.submission_id else None
    if sub is None or sub.deleted_at is not None:
        return None
    version = await db.get(FormVersion, sub.form_version_id)
    assert version is not None
    schema = Form.model_validate(version.schema)
    rules = await rules_for(db, form.id)
    reference = f"#{sub.seq:04d}"
    title = schema.settings.title or form.title

    def words(rule: NotificationRule | None) -> emails.Wording:
        return wording(
            rule,
            title=title,
            reference=reference,
            submitted=_submitted_text(sub.submitted_at, settings.tz),
            answers=emails.placeholder_answers(schema, sub.data),
        )

    if row.kind == "owner_new":
        rule = rules.get(RuleType.OWNER_EMAIL)
        include = bool(rule and rule.include_answers)
        return emails.owner_message(
            org_name=org_name,
            brand=eb,
            form=schema,
            title=title,
            reference=reference,
            submitted=sub.submitted_at,
            tz=settings.tz,
            url=submission_url(settings, sub),
            respondent=sub.respondent_email,
            answers=emails.answers_for_email(schema, sub.data) if include else None,
            wording=words(rule),
        )
    if row.kind == "approval_request":
        return await _approval_request(
            db, settings, row, sub, schema, org_name, title, reference, eb
        )
    if row.kind == "approval_outcome":
        pdf_file: tuple[str, bytes] | None = None
        if sub.pdf_status == PdfStatus.READY and sub.signed_pdf_key:
            pdf_file = (
                f"submission-{sub.seq:04d}.pdf",
                await storage.read(sub.signed_pdf_key),
            )
        rejected = sub.approval_state == ApprovalState.REJECTED
        reason = None
        if rejected:
            reason = await db.scalar(
                select(ApprovalStep.comment)
                .where(
                    ApprovalStep.submission_id == sub.id,
                    ApprovalStep.state == StepState.REJECTED,
                )
                .limit(1)
            )
        return emails.outcome_message(
            org_name=org_name,
            brand=eb,
            form=schema,
            title=title,
            reference=reference,
            approved=not rejected,
            comment=reason,
            pdf=pdf_file,
        )
    if row.kind == "receipt":
        rule = rules.get(RuleType.RESPONDENT_RECEIPT)
        pdf: tuple[str, bytes] | None = None
        if (
            rule is not None
            and rule.attach_pdf
            and sub.pdf_status == PdfStatus.READY
            and sub.signed_pdf_key
        ):
            pdf = (f"submission-{sub.seq:04d}.pdf", await storage.read(sub.signed_pdf_key))
        return emails.receipt_message(
            org_name=org_name,
            brand=eb,
            form=schema,
            title=title,
            reference=reference,
            submitted=sub.submitted_at,
            tz=settings.tz,
            answers=emails.answers_for_email(schema, sub.data),
            pdf=pdf,
            wording=words(rule),
        )
    return None


async def latest_schema(db: AsyncSession, form: FormRecord) -> Form:
    """The live version's schema; the draft when the form was never published."""
    if form.current_version_id is not None:
        version = await db.get(FormVersion, form.current_version_id)
        if version is not None:
            return Form.model_validate(version.schema)
    return Form.model_validate(form.draft_schema)


def sample_answers(form: Form) -> list[emails.Answer]:
    """Stand-ins for the answers in a test email: each question's label in brackets."""
    return [
        emails.Answer(el.label or key, f"[{el.label or key}]")
        for key, el in emails.placeholder_fields(form).items()
    ]


async def _test_message(
    db: AsyncSession,
    settings: Settings,
    form: FormRecord,
    kind: str,
    org_name: str,
    brand: emails.EmailBrand | None,
) -> emails.Message:
    """A rule's email rendered with sample answers. Nothing is read from submissions."""
    schema = await latest_schema(db, form)
    rule = (await rules_for(db, form.id)).get(TEST_KINDS[kind])
    title = schema.settings.title or form.title
    reference = "#0000"
    now = datetime.now(UTC)
    words = wording(
        rule,
        title=title,
        reference=reference,
        submitted=_submitted_text(now, settings.tz),
        answers={
            key: f"[{el.label or key}]" for key, el in emails.placeholder_fields(schema).items()
        },
        test=True,
    )
    if kind == "test_owner_new":
        msg = emails.owner_message(
            org_name=org_name,
            brand=brand,
            form=schema,
            title=title,
            reference=reference,
            submitted=now,
            tz=settings.tz,
            url=f"{settings.public_origin}/forms/{form.id}/submissions",
            respondent=None,
            answers=sample_answers(schema) if rule is not None and rule.include_answers else None,
            wording=words,
        )
    else:
        msg = emails.receipt_message(
            org_name=org_name,
            brand=brand,
            form=schema,
            title=title,
            reference=reference,
            submitted=now,
            tz=settings.tz,
            answers=sample_answers(schema),
            pdf=None,
            wording=words,
        )
    if not msg.subject.startswith(TEST_PREFIX):
        msg.subject = TEST_PREFIX + msg.subject
    return msg


async def _approval_request(
    db: AsyncSession,
    settings: Settings,
    row: EmailDelivery,
    sub: Submission,
    schema: Form,
    org_name: str,
    title: str,
    reference: str,
    brand: emails.EmailBrand | None = None,
) -> emails.Message | None:
    """The approver's email. Its link is minted now, so each email (and each "send again")
    carries a new link and older ones stop working."""
    from app.approvals.service import mint_link, step_count

    step = await db.get(ApprovalStep, uuid.UUID(row.detail)) if row.detail else None
    if step is None or step.state != StepState.PENDING or step.submission_id != sub.id:
        return None
    url = mint_link(settings, step)
    return emails.approval_request_message(
        org_name=org_name,
        brand=brand,
        form=schema,
        title=title,
        reference=reference,
        submitted=sub.submitted_at,
        tz=settings.tz,
        step_name=step.name,
        step=step.step,
        total=await step_count(db, sub),
        url=url,
        days=settings.approval_link_days,
    )


async def webhook_disabled(db: AsyncSession, hook: Webhook) -> list[uuid.UUID]:
    """Email the form's owners that a webhook was turned off after repeated failures."""
    form = await db.get(FormRecord, hook.form_id)
    if form is None:
        return []
    rows = [_email(form.id, None, "webhook_disabled", to) for to in await owner_addresses(db, form)]
    for r in rows:
        r.detail = hook.url[:2000]
        db.add(r)
    await db.commit()
    return [r.id for r in rows]


def mark_sent(row: EmailDelivery) -> None:
    row.status = EmailStatus.SENT
    row.sent_at = datetime.now(UTC)
    row.last_error = None


def email_fields(form: Form) -> list[EmailField]:
    from app.logic.index import FormIndex

    return [
        info.element
        for info in FormIndex.build(form).elements.values()
        if isinstance(info.element, EmailField) and info.repeater_id is None
    ]
