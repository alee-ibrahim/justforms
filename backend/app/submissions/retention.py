"""Erasing submissions and forms: owner "delete permanently", trash expiry and per-form
retention (DESIGN 14.5). Erasing a submission removes the row (files, signatures and events
cascade), every stored object that belongs to it (imported copies included), and leaves a
tombstone in ``audit_log``. Erasing a form erases all of its submissions first, then the
form's own stored objects (logo, link previews, uploads, exports, import files) and the row.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.importers.imported_files import stored_keys
from app.models import Export, FileRecord, FormRecord, Import, Signature, Submission
from app.services.users import audit
from app.storage import Storage

log = logging.getLogger(__name__)

# Default for JUSTFORMS_TRASH_DAYS.
TRASH_DAYS = 30


def retention_days(form: FormRecord | None) -> int | None:
    days = ((form.settings if form else None) or {}).get("retentionDays")
    return days if isinstance(days, int) and days >= 1 else None


def purge_at(
    sub: Submission, form: FormRecord | None, trash_days: int = TRASH_DAYS
) -> datetime | None:
    """When the nightly job erases a deleted submission: the end of its time in the trash,
    or earlier when the form's retention period runs out first. ``None`` when not deleted.
    A submission whose form is in the trash goes with the form if that comes sooner."""
    if sub.deleted_at is None and (form is None or form.deleted_at is None):
        return None
    dates: list[datetime] = []
    if sub.deleted_at is not None:
        dates.append(sub.deleted_at + timedelta(days=trash_days))
    if form is not None and form.deleted_at is not None:
        dates.append(form.deleted_at + timedelta(days=trash_days))
    days = retention_days(form)
    if days is not None:
        dates.append(sub.submitted_at + timedelta(days=days))
    return min(dates)


def form_purge_at(form: FormRecord, trash_days: int = TRASH_DAYS) -> datetime | None:
    if form.deleted_at is None:
        return None
    return form.deleted_at + timedelta(days=trash_days)


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


async def erase_form(
    db: AsyncSession,
    storage: Storage,
    form: FormRecord,
    *,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Hard-delete a form: its submissions (each with a tombstone), its stored objects and
    the row (versions, permissions, rules and the rest cascade). Returns how many
    submissions went. The caller commits."""
    subs = (await db.scalars(select(Submission).where(Submission.form_id == form.id))).all()
    for sub in subs:
        await erase(db, storage, sub, reason=reason, actor_id=actor_id)
    await db.flush()
    # Only keys under this form's own folders: a duplicated form's settings can still name
    # the original's logo or preview, which must survive.
    keys = [
        k
        for k in (
            await db.scalars(select(FileRecord.storage_key).where(FileRecord.form_id == form.id))
        ).all()
        if k
    ]
    keys += [
        k
        for k in (
            await db.scalars(select(Export.storage_key).where(Export.form_id == form.id))
        ).all()
        if k
    ]
    imports = (await db.scalars(select(Import.id).where(Import.form_id == form.id))).all()
    for key in keys:
        await storage.delete(key)
    folders = [
        f"form-logos/{form.id}",
        f"og/{form.id}",
        f"tmp/{form.id}",
        f"files/{form.org_id}/{form.id}",
        f"pdfs/{form.id}",
        f"imported/{form.id}",
        *(f"imports/{i}" for i in imports),
    ]
    for folder in folders:
        await storage.delete_prefix(folder)
    await audit(
        db,
        "form.erased",
        org_id=form.org_id,
        actor_id=actor_id,
        target_type="form",
        target_id=form.id,
        meta={"title": form.title, "slug": form.slug, "submissions": len(subs), "reason": reason},
    )
    await db.delete(form)
    return len(subs)


async def purge(
    db: AsyncSession,
    storage: Storage,
    now: datetime | None = None,
    *,
    trash_days: int = TRASH_DAYS,
) -> int:
    """Nightly: erase submissions and forms that have been in the trash ``trash_days``, and
    submissions past their form's ``retentionDays`` (in the trash or not; the earlier date
    wins). Returns how many submissions were erased."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=trash_days)
    count = 0
    expired = (
        await db.scalars(
            select(Submission).where(
                Submission.deleted_at.is_not(None), Submission.deleted_at < cutoff
            )
        )
    ).all()
    for sub in expired:
        await erase(db, storage, sub, reason="deleted")
        count += 1
    await db.commit()

    forms = (
        await db.scalars(
            select(FormRecord).where(
                FormRecord.deleted_at.is_not(None), FormRecord.deleted_at < cutoff
            )
        )
    ).all()
    for form in forms:
        count += await erase_form(db, storage, form, reason="deleted")
        await db.commit()

    forms = (
        await db.scalars(select(FormRecord).where(FormRecord.settings.has_key("retentionDays")))
    ).all()
    for form in forms:
        days = retention_days(form)
        if days is None:
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
