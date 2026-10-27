"""arq background worker.

Run with: ``uv run arq app.worker.WorkerSettings``
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.config import get_settings
from app.db import get_sessionmaker
from app.email import send_email as smtp_send
from app.importers.service import run_submissions_import
from app.models import (
    EmailDelivery,
    EmailStatus,
    InvitationStatus,
    InviteEmailStatus,
    OrgInvitation,
)
from app.notifications import events as notify
from app.notifications import webhooks
from app.pdf.service import generate_pdf
from app.services import invitations
from app.signing.keys import ensure_key
from app.storage import get_storage
from app.submissions import retention
from app.submissions.export import build_export, purge_expired_exports
from app.uploads.service import purge_pending

log = logging.getLogger(__name__)


EMAIL_TRIES = 5


async def send_email(
    ctx: dict[str, Any],
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    from_name: str | None = None,
) -> bool:
    """Send one email. Logs never include the body (it may hold one-time codes)."""
    sent = await smtp_send(get_settings(), to, subject, text, html=html, from_name=from_name)
    log.info("email job finished (sent=%s)", sent)
    return sent


async def _enqueue(ctx: dict[str, Any], function: str, **kwargs: Any) -> None:
    await ctx["redis"].enqueue_job(function, **kwargs)


async def _enqueue_jobs(ctx: dict[str, Any], jobs: notify.Jobs) -> None:
    for delivery_id in jobs.webhook_deliveries:
        await _enqueue(
            ctx, "deliver_webhook", delivery_id=str(delivery_id), _job_id=f"whd:{delivery_id}:0"
        )
    for email_id in jobs.emails:
        await _enqueue(ctx, "send_form_email", email_id=str(email_id))


async def dispatch_event(
    ctx: dict[str, Any],
    *,
    event: str,
    submission_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Fan one submission event out to webhooks and notification emails (DESIGN 11)."""
    async with get_sessionmaker()() as db:
        jobs = await notify.dispatch(
            db, get_settings(), event, uuid.UUID(submission_id), extra=extra
        )
    await _enqueue_jobs(ctx, jobs)


async def deliver_webhook(ctx: dict[str, Any], *, delivery_id: str) -> None:
    """One delivery attempt; failures are retried 1 m, 5 m, 30 m, 2 h, 6 h, 12 h, 24 h later."""
    async with get_sessionmaker()() as db:
        retry, disabled = await webhooks.deliver(db, get_settings(), uuid.UUID(delivery_id))
        if retry is not None:
            row = await db.get(webhooks.WebhookDelivery, uuid.UUID(delivery_id))
            attempt = row.attempt if row else 0
            await _enqueue(
                ctx,
                "deliver_webhook",
                delivery_id=delivery_id,
                _defer_by=retry,
                _job_id=f"whd:{delivery_id}:{attempt}",
            )
        if disabled is not None:
            for email_id in await notify.webhook_disabled(db, disabled):
                await _enqueue(ctx, "send_form_email", email_id=str(email_id))


async def send_form_email(ctx: dict[str, Any], *, email_id: str) -> bool:
    """Send one notification email; 5 tries with exponential backoff from 30 s.

    Everything the email refers to is committed *before* it goes out: rendering an approval
    request mints a new approver link (its hash replaces the step's previous one), and that
    link must work the moment the email arrives. If the commit fails nothing is sent and the
    job is retried; a retry renders again and mints a fresh link, so a step only ever has one
    valid link (the one in the latest email), as with "send again".
    """
    settings = get_settings()
    tries = int(ctx.get("job_try", 1))
    async with get_sessionmaker()() as db:
        row = await db.get(EmailDelivery, uuid.UUID(email_id))
        if row is None or row.status == EmailStatus.SENT:
            return False
        row.attempts += 1
        try:
            msg = await notify.render_email(db, settings, get_storage(), row)
            if msg is None:
                row.status = EmailStatus.FAILED
                row.last_error = (
                    "Nothing to send any more: the access was removed or the form deleted."
                    if row.kind == notify.FORM_SHARED
                    else "Nothing to send any more: the submission was deleted or moved on."
                )
                notify.forget_note(row)
                await db.commit()
                return False
            if not settings.smtp_enabled:
                row.status = EmailStatus.FAILED
                row.last_error = "Email isn't set up on this install."
                notify.forget_note(row)
                await db.commit()
                return False
            await db.commit()  # the approver link (if any) is live before the email is sent
        except Exception as exc:
            # Nothing was sent; drop the half-made changes (including a minted link).
            await db.rollback()
            return await _email_failed(db, email_id, exc, tries, count_attempt=True)
        try:
            await smtp_send(
                settings,
                row.to_address,
                msg.subject,
                msg.text,
                html=msg.html,
                attachments=msg.attachments,
                from_name=msg.from_name,
                reply_to=msg.reply_to,
            )
        except Exception as exc:
            return await _email_failed(db, email_id, exc, tries)
        notify.mark_sent(row)
        try:
            await db.commit()
        except Exception:
            # The email went out with a committed link; retrying would only send a duplicate.
            await db.rollback()
            log.exception("notification email %s sent but not marked as sent", email_id)
        return True


async def _email_failed(
    db: AsyncSession, email_id: str, exc: Exception, tries: int, *, count_attempt: bool = False
) -> bool:
    """Record a failed try; raise ``Retry`` until the tries run out."""
    error = f"{type(exc).__name__}: {str(exc)[:300]}"
    final = tries >= EMAIL_TRIES
    try:
        row = await db.get(EmailDelivery, uuid.UUID(email_id), populate_existing=True)
        if row is not None:
            if count_attempt:
                row.attempts += 1
            row.last_error = error
            if final:
                row.status = EmailStatus.FAILED
                notify.forget_note(row)
            await db.commit()
    except Exception:
        await db.rollback()
        log.exception("could not record the failure of notification email %s", email_id)
    if not final:
        raise Retry(defer=30 * 2 ** (tries - 1)) from exc
    log.warning("notification email %s failed after %d tries", email_id, tries)
    return False


async def send_invitation_email(ctx: dict[str, Any], *, invitation_id: str) -> bool:
    """Send one invitation to join an organisation; 5 tries with backoff from 30 s.

    As with approval requests, the link is minted and committed *before* the email goes out,
    so it works the moment the email arrives; a retry mints a fresh one (only the link in the
    latest email works).
    """
    settings = get_settings()
    tries = int(ctx.get("job_try", 1))
    async with get_sessionmaker()() as db:
        inv = await db.get(OrgInvitation, uuid.UUID(invitation_id))
        if inv is None or inv.status != InvitationStatus.PENDING:
            return False
        if inv.email_status == InviteEmailStatus.SENT and inv.token_hash is not None:
            return False  # a duplicate job for an email that already went out
        try:
            if not settings.smtp_enabled:
                inv.email_status = InviteEmailStatus.FAILED
                inv.email_error = "Email isn't set up on this server."
                await db.commit()
                return False
            url = invitations.mint_link(settings, inv)
            msg = await invitations.render(db, settings, inv, url)
            await db.commit()  # the link is live before the email is sent
        except Exception as exc:
            await db.rollback()
            return await _invitation_failed(db, invitation_id, exc, tries)
        try:
            await smtp_send(
                settings,
                inv.email,
                msg.subject,
                msg.text,
                html=msg.html,
                from_name=msg.from_name,
            )
        except Exception as exc:
            return await _invitation_failed(db, invitation_id, exc, tries)
        inv.email_status = InviteEmailStatus.SENT
        inv.email_error = None
        inv.sent_at = datetime.now(UTC)
        inv.send_count += 1
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception("invitation email %s sent but not marked as sent", invitation_id)
        return True


async def _invitation_failed(
    db: AsyncSession, invitation_id: str, exc: Exception, tries: int
) -> bool:
    final = tries >= EMAIL_TRIES
    try:
        inv = await db.get(OrgInvitation, uuid.UUID(invitation_id), populate_existing=True)
        if inv is not None:
            inv.email_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if final:
                inv.email_status = InviteEmailStatus.FAILED
            await db.commit()
    except Exception:
        await db.rollback()
        log.exception("could not record the failure of invitation email %s", invitation_id)
    if not final:
        raise Retry(defer=30 * 2 ** (tries - 1)) from exc
    log.warning("invitation email %s failed after %d tries", invitation_id, tries)
    return False


async def webhook_sweeper(ctx: dict[str, Any]) -> int:
    """Every few minutes: re-enqueue deliveries whose retry job went missing."""
    async with get_sessionmaker()() as db:
        due = await webhooks.due_deliveries(db, datetime.now(UTC))
        for delivery_id in due:
            row = await db.get(webhooks.WebhookDelivery, delivery_id)
            attempt = row.attempt if row else 0
            await _enqueue(
                ctx,
                "deliver_webhook",
                delivery_id=str(delivery_id),
                _job_id=f"whd:{delivery_id}:{attempt}",
            )
    return len(due)


async def purge_pending_uploads(ctx: dict[str, Any]) -> int:
    """Nightly: uploads never attached to a submission become orphaned and are deleted."""
    async with get_sessionmaker()() as db:
        count = await purge_pending(db, get_storage(), get_settings())
    log.info("purged %d stale uploads", count)
    return count


async def nightly_cleanup(ctx: dict[str, Any]) -> None:
    """Nightly: empty the trash (forms and submissions past JUSTFORMS_TRASH_DAYS), erase
    submissions past their form's retention, drop expired export files."""
    storage = get_storage()
    async with get_sessionmaker()() as db:
        erased = await retention.purge(db, storage, trash_days=get_settings().trash_days)
        exports = await purge_expired_exports(db, storage)
        deliveries = await webhooks.purge_old(db, datetime.now(UTC))
        ai_messages = await ai_service.purge_old(db)
    log.info(
        "erased %d submissions, removed %d expired exports, %d old webhook deliveries and "
        "%d old AI messages",
        erased,
        exports,
        deliveries,
        ai_messages,
    )


async def export_submissions(ctx: dict[str, Any], *, export_id: str) -> bool:
    """Build one .xlsx export (DESIGN 15.2)."""
    async with get_sessionmaker()() as db:
        return await build_export(db, get_storage(), get_settings(), uuid.UUID(export_id))


async def import_submissions(ctx: dict[str, Any], *, import_id: str) -> bool:
    """Bring in the rows of an uploaded Jotform export (DESIGN 13.3)."""
    async with get_sessionmaker()() as db:
        return await run_submissions_import(db, get_storage(), get_settings(), uuid.UUID(import_id))


async def render_submission_pdf(ctx: dict[str, Any], *, submission_id: str) -> bool:
    """Render, sign and store one submission's PDF (DESIGN 9.5)."""
    async with get_sessionmaker()() as db:
        ok = await generate_pdf(db, get_storage(), get_settings(), uuid.UUID(submission_id))
        jobs = await notify.dispatch(
            db,
            get_settings(),
            "submission.pdf_ready" if ok else notify.PDF_FAILED,
            uuid.UUID(submission_id),
        )
    await _enqueue_jobs(ctx, jobs)
    return ok


async def startup(ctx: dict[str, Any]) -> None:
    # Create the install's PDF signing key on first start (no-op afterwards).
    settings = get_settings()
    if not settings.pdf_signing_p12:
        async with get_sessionmaker()() as db:
            await ensure_key(db, settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        send_email,
        purge_pending_uploads,
        nightly_cleanup,
        render_submission_pdf,
        export_submissions,
        import_submissions,
        dispatch_event,
        deliver_webhook,
        send_form_email,
        send_invitation_email,
        webhook_sweeper,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(webhook_sweeper, minute=set(range(0, 60, 5))),
        cron(purge_pending_uploads, hour={3}, minute={10}),
        cron(nightly_cleanup, hour={3}, minute={25}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 5
