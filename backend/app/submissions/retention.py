"""Erasing submissions: owner hard delete, soft-delete expiry and per-form retention
(DESIGN 14.5). Erasing removes the row (files, signatures and events cascade), every stored
object that belongs to it (imported copies included), and leaves a tombstone in ``audit_log``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.importers.imported_files import stored_keys
from app.models import FileRecord, FormRecord, Signature, Submission
from app.services.users import audit
from app.storage import Storage

log = logging.getLogger(__name__)

SOFT_DELETE_DAYS = 30


async def erase(
    db: AsyncSession,
    storage: Storage,
    sub: Submission,
    *,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Hard-delete one submission and its stored objects (the caller commits)."""
    form = await db.get(FormRecord, sub.form_id)
    keys: list[str] = []
    files = (await db.scalars(select(FileRecord).where(FileRecord.submission_id == sub.id))).all()
    keys += [f.storage_key for f in files]
    sigs = (await db.scalars(select(Signature).where(Signature.submission_id == sub.id))).all()
    for s in sigs:
        keys += [s.svg_key, s.png_key]
    if sub.signed_pdf_key:
        keys.append(sub.signed_pdf_key)
    keys += stored_keys(sub.imported_links)
    for key in keys:
        await storage.delete(key)
    await audit(
        db,
        "submission.erased",
        org_id=form.org_id if form else None,
        actor_id=actor_id,
        target_type="submission",
        target_id=sub.id,
        meta={"form_id": str(sub.form_id), "seq": sub.seq, "reason": reason},
    )
    await db.delete(sub)


async def purge(db: AsyncSession, storage: Storage, now: datetime | None = None) -> int:
    """Nightly: erase soft-deleted submissions after 30 days and submissions past their
    form's ``retentionDays``."""
    now = now or datetime.now(UTC)
    count = 0
    expired = (
        await db.scalars(
            select(Submission).where(
                Submission.deleted_at.is_not(None),
                Submission.deleted_at < now - timedelta(days=SOFT_DELETE_DAYS),
            )
        )
    ).all()
    for sub in expired:
        await erase(db, storage, sub, reason="deleted")
        count += 1
    await db.commit()

    forms = (
        await db.scalars(select(FormRecord).where(FormRecord.settings.has_key("retentionDays")))
    ).all()
    for form in forms:
        days = (form.settings or {}).get("retentionDays")
        if not isinstance(days, int) or days < 1:
            continue
        old = (
            await db.scalars(
                select(Submission).where(
                    Submission.form_id == form.id,
                    Submission.submitted_at < now - timedelta(days=days),
                )
            )
        ).all()
        for sub in old:
            await erase(db, storage, sub, reason="retention")
            count += 1
        await db.commit()
    if count:
        log.info("erased %d submissions", count)
    return count
