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

import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
# Approvals' "Send test emails": the approver's email (or, for steps decided in the studio, the
# notification), and both outcomes, to the person asking.
APPROVAL_OUTCOME_TEST_KINDS = ("test_approval_approved", "test_approval_rejected")
APPROVAL_TEST_KINDS = (
    "test_approval_request",
    "test_approval_notice",
    *APPROVAL_OUTCOME_TEST_KINDS,
)
# A member got a role on a form (Share page, "Notify by email").
FORM_SHARED = "form_shared"


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


def approval_wording(
    form: FormRecord,
    kind: str,
    *,
    title: str,
    reference: str,
    submitted: str,
    answers: dict[str, str],
    test: bool = False,
) -> emails.Wording:
    """The form's custom wording for an approval email (``kind``: request, approved or
    rejected) with the placeholders filled in. Read when the email is sent."""
    from app.approvals.config import load_config

    config = load_config(form.settings)
    values = {"reference": reference, "form_title": title, "submitted": submitted}
    subject = None
    reply_to = None
    if kind == "request":
        raw_subject, raw_message = config.request_subject, config.request_message
    else:
        raw_subject = None
        raw_message = (
            config.outcome_approved_message
            if kind == "approved"
            else config.outcome_rejected_message
        )
        reply_to = str(config.outcome_reply_to) if config.outcome_reply_to else None
    if raw_subject:
        subject = emails.one_line(emails.fill(raw_subject, values, answers))
        if test:
            subject = TEST_PREFIX + subject
    message = emails.fill(raw_message, values, answers).strip() if raw_message else None
    return emails.Wording(subject=subject, message=message or None, reply_to=reply_to)


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


# A receipt row for an address nobody confirmed (``EmailDelivery.detail``).
UNVERIFIED = "unverified"
# Receipts to unconfirmed addresses: per address and form, per hour.
RECEIPTS_PER_ADDRESS_HOUR = 3


def receipt_address(rule: NotificationRule, sub: Submission) -> str | None:
    return receipt_target(rule, sub)[0]


def receipt_target(rule: NotificationRule, sub: Submission) -> tuple[str | None, bool]:
    """Where the receipt goes and whether that address was confirmed (email code or staff
    sign-in). A typed address only counts as confirmed when it is the confirmed one."""
    confirmed = sub.respondent_email
    if not rule.email_field:
        return confirmed, confirmed is not None
    value = sub.data.get(rule.email_field)
    typed = value.strip() if isinstance(value, str) and "@" in value else None
    if typed and confirmed and typed.lower() == confirmed.lower():
        return confirmed, True
    return typed, False


async def _unverified_receipt_refused(
    db: AsyncSession, settings: Settings, form_id: uuid.UUID, to: str
) -> str | None:
    """Why a receipt to an unconfirmed address can't go now (None: it can)."""
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = select(func.count(EmailDelivery.id)).where(
        EmailDelivery.form_id == form_id,
        EmailDelivery.kind == "receipt",
        EmailDelivery.detail == UNVERIFIED,
        EmailDelivery.created_at >= since,
    )
    if (await db.scalar(recent) or 0) >= settings.receipt_unverified_per_hour:
        return "Not sent: too many receipts to unconfirmed addresses this hour"
    same = recent.where(func.lower(EmailDelivery.to_address) == to.lower())
    if (await db.scalar(same) or 0) >= RECEIPTS_PER_ADDRESS_HOUR:
        return "Not sent: too many receipts to this address this hour"
    return None


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
        to, confirmed = receipt_target(receipt, sub)
        if not confirmed and not receipt.to_unverified:
            to = None  # receipts to typed addresses are opt-in
        waits = receipt.attach_pdf and sub.pdf_status == PdfStatus.PENDING
        if not confirmed and not receipt.unverified_answers:
            waits = False  # no PDF goes to an unconfirmed address
        now = (event == "submission.created" and not waits) or (
            event in ("submission.pdf_ready", PDF_FAILED) and receipt.attach_pdf
        )
        if to and now and not await _has_receipt(db, sub):
            row = _email(form.id, sub.id, "receipt", to)
            refused = None
            if not confirmed:
                row.detail = UNVERIFIED
                refused = await _unverified_receipt_refused(db, settings, form.id, to)
            if refused:
                # Shown in the Settings page's email log, never sent.
                row.status = EmailStatus.FAILED
                row.last_error = refused
                db.add(row)
            else:
                new_emails.append(row)
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
    if row.kind in APPROVAL_TEST_KINDS:
        return await _approval_test_message(db, settings, form, row.kind, org_name, eb)
    if row.kind == FORM_SHARED:
        return await _form_shared(db, settings, form, row, org_name, eb)
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
            db, settings, row, sub, schema, org_name, title, reference, eb, form
        )
    if row.kind == "approval_notice":
        return await _approval_notice(
            db, settings, row, sub, schema, org_name, title, reference, eb, form
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
            wording=approval_wording(
                form,
                "rejected" if rejected else "approved",
                title=title,
                reference=reference,
                submitted=_submitted_text(sub.submitted_at, settings.tz),
                answers=emails.placeholder_answers(schema, sub.data),
            ),
        )
    if row.kind == "receipt":
        rule = rules.get(RuleType.RESPONDENT_RECEIPT)
        # To an address nobody confirmed: a confirmation and the reference only, unless the
        # owner allowed answers there (read now, so turning it off applies to queued emails).
        full = row.detail != UNVERIFIED or bool(rule and rule.unverified_answers)
        pdf: tuple[str, bytes] | None = None
        if (
            full
            and rule is not None
            and rule.attach_pdf
            and sub.pdf_status == PdfStatus.READY
            and sub.signed_pdf_key
        ):
            pdf = (f"submission-{sub.seq:04d}.pdf", await storage.read(sub.signed_pdf_key))
        receipt_words = (
            words(rule)
            if full
            else wording(
                rule,
                title=title,
                reference=reference,
                submitted=_submitted_text(sub.submitted_at, settings.tz),
                answers={},
            )
        )
        return emails.receipt_message(
            org_name=org_name,
            brand=eb,
            form=schema,
            title=title,
            reference=reference,
            submitted=sub.submitted_at,
            tz=settings.tz,
            answers=emails.answers_for_email(schema, sub.data) if full else [],
            pdf=pdf,
            wording=receipt_words,
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


async def _approval_test_message(
    db: AsyncSession,
    settings: Settings,
    form: FormRecord,
    kind: str,
    org_name: str,
    brand: emails.EmailBrand | None,
) -> emails.Message:
    """An approval email rendered with sample answers and the current settings. Nothing is
    read from submissions and no approver link is made: the buttons open the submissions."""
    from app.approvals.config import load_config

    schema = await latest_schema(db, form)
    config = load_config(form.settings)
    title = schema.settings.title or form.title
    reference = "#0000"
    now = datetime.now(UTC)
    sample = {key: f"[{el.label or key}]" for key, el in emails.placeholder_fields(schema).items()}
    words = approval_wording(
        form,
        "request" if kind == "test_approval_notice" else kind.removeprefix("test_approval_"),
        title=title,
        reference=reference,
        submitted=_submitted_text(now, settings.tz),
        answers=sample,
        test=True,
    )
    if kind == "test_approval_request":
        n, step = next(
            ((i, s.name) for i, s in enumerate(config.steps, start=1) if s.source != "editors"),
            (1, "Approval"),
        )
        msg = emails.approval_request_message(
            org_name=org_name,
            brand=brand,
            form=schema,
            title=title,
            reference=reference,
            submitted=now,
            tz=settings.tz,
            step_name=step,
            step=n,
            total=max(1, len(config.steps)),
            url=f"{settings.public_origin}/forms/{form.id}/submissions",
            days=settings.approval_link_days,
            wording=words,
            answers=sample_answers(schema) if config.request_include_answers else None,
        )
    elif kind == "test_approval_notice":
        n, cfg = next(
            ((i, s) for i, s in enumerate(config.steps, start=1) if s.source == "editors"),
            (1, None),
        )
        msg = emails.approval_notice_message(
            org_name=org_name,
            product=product_name(settings),
            brand=brand,
            form=schema,
            title=title,
            reference=reference,
            submitted=now,
            tz=settings.tz,
            step_name=cfg.name if cfg else "Approval",
            step=n,
            total=max(1, len(config.steps)),
            url=f"{settings.public_origin}/forms/{form.id}/submissions",
            wording=words,
            answers=sample_answers(schema) if config.request_include_answers else None,
        )
    else:
        rejected = kind == "test_approval_rejected"
        msg = emails.outcome_message(
            org_name=org_name,
            brand=brand,
            form=schema,
            title=title,
            reference=reference,
            approved=not rejected,
            comment="[The approver's comment]" if rejected else None,
            pdf=None,
            wording=words,
        )
    if not msg.subject.startswith(TEST_PREFIX):
        msg.subject = TEST_PREFIX + msg.subject
    return msg


def share_detail(row: EmailDelivery) -> dict[str, Any]:
    try:
        detail = json.loads(row.detail or "{}")
    except ValueError:
        return {}
    return detail if isinstance(detail, dict) else {}


def form_shared_row(
    form_id: uuid.UUID,
    to: User,
    *,
    sharer: User,
    upgraded: bool,
    note: str | None,
) -> EmailDelivery:
    """A queued "form shared" email. The recipient's role is read when it is sent (so a role
    changed or removed in the meantime is respected); the note is kept until then."""
    row = _email(form_id, None, FORM_SHARED, to.email)
    detail: dict[str, Any] = {"by": str(sharer.id), "user": str(to.id), "upgraded": upgraded}
    if note:
        detail["note"] = note
    row.detail = json.dumps(detail, ensure_ascii=False)
    return row


async def _form_shared(
    db: AsyncSession,
    settings: Settings,
    form: FormRecord,
    row: EmailDelivery,
    org_name: str,
    brand: emails.EmailBrand | None,
) -> emails.Message | None:
    """Nothing to send when the form was deleted or the person no longer has a role on it."""
    if form.deleted_at is not None:
        return None
    detail = share_detail(row)
    try:
        user_id = uuid.UUID(str(detail.get("user")))
    except ValueError:
        return None
    perm = await db.get(FormPermission, (form.id, user_id))
    if perm is None:
        return None
    sharer = None
    with contextlib.suppress(ValueError):
        sharer = await db.get(User, uuid.UUID(str(detail.get("by"))))
    language = str((form.draft_schema.get("settings") or {}).get("language") or "en")
    page = "submissions" if perm.role == FormRole.VIEWER else "edit"
    note = detail.get("note")
    return emails.form_shared_message(
        org_name=org_name,
        brand=brand,
        sharer=(sharer.display_name or sharer.email) if sharer else "",
        sharer_email=sharer.email if sharer else None,
        title=form.title,
        language=language,
        role=perm.role.value,
        upgraded=bool(detail.get("upgraded")),
        note=note if isinstance(note, str) and note else None,
        url=f"{settings.public_origin}/forms/{form.id}/{page}",
    )


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
    form: FormRecord | None = None,
) -> emails.Message | None:
    """The approver's email. Its link is minted now, so each email (and each "send again")
    carries a new link and older ones stop working."""
    from app.approvals.service import mint_link, step_count

    step = await db.get(ApprovalStep, uuid.UUID(row.detail)) if row.detail else None
    if (
        step is None
        or step.state != StepState.PENDING
        or step.submission_id != sub.id
        or step.source == "editors"
    ):
        return None
    url = mint_link(settings, step)
    from app.approvals.config import load_config

    config = load_config(form.settings if form is not None else None)
    words = (
        approval_wording(
            form,
            "request",
            title=title,
            reference=reference,
            submitted=_submitted_text(sub.submitted_at, settings.tz),
            answers=emails.placeholder_answers(schema, sub.data),
        )
        if form is not None
        else None
    )
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
        wording=words,
        answers=(
            emails.answers_for_email(schema, sub.data) if config.request_include_answers else None
        ),
    )


def product_name(settings: Settings) -> str:
    return settings.brand_name.strip() or "JustForms"


async def _approval_notice(
    db: AsyncSession,
    settings: Settings,
    row: EmailDelivery,
    sub: Submission,
    schema: Form,
    org_name: str,
    title: str,
    reference: str,
    brand: emails.EmailBrand | None,
    form: FormRecord,
) -> emails.Message | None:
    """ "New response to review" for a step decided in the studio: the same wording settings as
    the approver's email, a button to the submission (sign-in needed), no link to decide and no
    code. Nothing is sent once the step is no longer waiting."""
    from app.approvals.config import load_config
    from app.approvals.service import step_count

    step = await db.get(ApprovalStep, uuid.UUID(row.detail)) if row.detail else None
    if step is None or step.state != StepState.PENDING or step.submission_id != sub.id:
        return None
    config = load_config(form.settings)
    words = approval_wording(
        form,
        "request",
        title=title,
        reference=reference,
        submitted=_submitted_text(sub.submitted_at, settings.tz),
        answers=emails.placeholder_answers(schema, sub.data),
    )
    return emails.approval_notice_message(
        org_name=org_name,
        product=product_name(settings),
        brand=brand,
        form=schema,
        title=title,
        reference=reference,
        submitted=sub.submitted_at,
        tz=settings.tz,
        step_name=step.name,
        step=step.step,
        total=await step_count(db, sub),
        url=submission_url(settings, sub),
        wording=words,
        answers=(
            emails.answers_for_email(schema, sub.data) if config.request_include_answers else None
        ),
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
    forget_note(row)


def forget_note(row: EmailDelivery) -> None:
    """Drop the sharer's personal note once a "form shared" email is done with (sent, or
    failed for good): the email log never keeps message bodies."""
    if row.kind != FORM_SHARED or not row.detail:
        return
    detail = share_detail(row)
    if detail.pop("note", None) is not None:
        row.detail = json.dumps(detail)


def email_fields(form: Form) -> list[EmailField]:
    from app.logic.index import FormIndex

    return [
        info.element
        for info in FormIndex.build(form).elements.values()
        if isinstance(info.element, EmailField) and info.repeater_id is None
    ]
