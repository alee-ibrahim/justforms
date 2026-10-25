"""Correcting imported submissions: exact submit times and reference numbers in time order
(DESIGN 13.3, "Correcting an import").

``submitted_at`` is part of a submission's content hash and the first event chains from that
hash, so it never changes on a row, and neither is the event history rewritten. Instead an
imported row that nobody has worked on yet is **rebuilt**: the old row is removed (with an
audit entry naming its replacement) and a new row is created with the corrected time and
number, a fresh content hash and a ``created`` event that records where it came from
(``rebuiltFrom``, ``previousSeq``, ``previousSubmittedAt``, ``timeSource``).

Only untouched imported rows qualify: the ``created`` event and nothing else, no PDF or
verify page, no approval, no uploaded files or drawn signatures, no email or webhook
deliveries. If any imported row on the form has moved on, nothing is changed. The imported
rows keep the reference numbers they already occupy, handed out again oldest first, so
numbers of live submissions are never touched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrity import append_event, compute_content_hash, iso
from app.models import (
    ApprovalStep,
    EmailDelivery,
    EventType,
    FileRecord,
    FormRecord,
    FormVersion,
    PdfStatus,
    Signature,
    Submission,
    SubmissionEvent,
    SubmissionSource,
)
from app.services.users import audit

_COPIED = (
    "form_version_id",
    "status",
    "language",
    "data",
    "ip",
    "user_agent",
    "respondent_email",
    "source",
    "external_id",
    "imported_links",
    "search_text",
)


class RebuildRefused(Exception):
    """Some imported rows have been worked on; ``blocked`` counts them by reason."""

    def __init__(self, blocked: dict[str, int]) -> None:
        super().__init__(", ".join(f"{k}: {v}" for k, v in sorted(blocked.items())))
        self.blocked = blocked


@dataclass
class RebuildReport:
    rows: int = 0
    retimed: int = 0
    renumbered: int = 0
    # Imported rows without an exact time (kept as they were).
    missing_time: int = 0
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "retimed": self.retimed,
            "renumbered": self.renumbered,
            "missingTime": self.missing_time,
            "changes": self.changes,
        }


async def _blocked(db: AsyncSession, subs: list[Submission]) -> dict[str, int]:
    ids = [s.id for s in subs]
    out: dict[str, int] = {}

    def add(reason: str, n: int) -> None:
        if n:
            out[reason] = out.get(reason, 0) + n

    add(
        "pdf_or_verify_page",
        sum(1 for s in subs if s.pdf_status != PdfStatus.NONE or s.verify_token),
    )
    add("approval", sum(1 for s in subs if s.approval_state is not None))
    events = await db.execute(
        select(SubmissionEvent.submission_id, func.count())
        .where(SubmissionEvent.submission_id.in_(ids))
        .group_by(SubmissionEvent.submission_id)
    )
    counts = dict(events.all())
    add("activity", sum(1 for i in ids if counts.get(i, 0) != 1))
    created = await db.scalar(
        select(func.count())
        .select_from(SubmissionEvent)
        .where(
            SubmissionEvent.submission_id.in_(ids),
            SubmissionEvent.seq == 1,
            SubmissionEvent.type == EventType.CREATED,
        )
    )
    add("activity", len(ids) - int(created or 0))
    for reason, model, column in (
        ("files", FileRecord, FileRecord.submission_id),
        ("signatures", Signature, Signature.submission_id),
        ("approval", ApprovalStep, ApprovalStep.submission_id),
        ("deliveries", EmailDelivery, EmailDelivery.submission_id),
    ):
        n = await db.scalar(select(func.count()).select_from(model).where(column.in_(ids)))
        add(reason, int(n or 0))
    return out


async def rebuild_imported(
    db: AsyncSession,
    form_id: uuid.UUID,
    times: dict[str, datetime],
    *,
    time_source: str,
    dry_run: bool = False,
    actor_id: uuid.UUID | None = None,
) -> RebuildReport:
    """Re-time (from ``times``: Jotform submission id -> UTC) and renumber, oldest first,
    the form's imported submissions. Raises :class:`RebuildRefused`; the caller commits."""
    form_rec = await db.get(FormRecord, form_id)
    if form_rec is None:
        raise LookupError("form_not_found")
    # Serialise with live submissions (reference numbers) on the same form.
    await db.execute(select(FormRecord.id).where(FormRecord.id == form_id).with_for_update())
    subs = list(
        (
            await db.scalars(
                select(Submission)
                .where(
                    Submission.form_id == form_id,
                    Submission.source == SubmissionSource.JOTFORM_IMPORT,
                )
                .order_by(Submission.seq)
            )
        ).all()
    )
    report = RebuildReport(rows=len(subs))
    if not subs:
        return report
    if any(s.deleted_at is not None for s in subs):
        raise RebuildRefused({"deleted": sum(1 for s in subs if s.deleted_at is not None)})
    blocked = await _blocked(db, subs)
    if blocked:
        raise RebuildRefused(blocked)

    def new_time(s: Submission) -> datetime:
        return times.get(s.external_id or "", s.submitted_at)

    report.missing_time = sum(1 for s in subs if (s.external_id or "") not in times)
    slots = sorted(s.seq for s in subs)
    ordered = sorted(subs, key=lambda s: (new_time(s), s.seq))
    plan = [(s, slots[i], new_time(s)) for i, s in enumerate(ordered)]
    plan = [(s, seq, at) for s, seq, at in plan if seq != s.seq or at != s.submitted_at]
    report.retimed = sum(1 for s, _seq, at in plan if at != s.submitted_at)
    report.renumbered = sum(1 for s, seq, _at in plan if seq != s.seq)
    if dry_run or not plan:
        report.changes = [
            {"seq": s.seq, "newSeq": seq, "retimed": at != s.submitted_at} for s, seq, at in plan
        ]
        return report

    # Keep what each old row carries, then remove the old rows (events cascade) before the
    # new ones take their numbers.
    carried: list[tuple[Submission, dict[str, Any], dict[str, Any], int, datetime]] = []
    for s, seq, at in plan:
        values = {name: getattr(s, name) for name in _COPIED}
        first = await db.scalar(
            select(SubmissionEvent).where(
                SubmissionEvent.submission_id == s.id, SubmissionEvent.seq == 1
            )
        )
        carried.append((s, values, dict(first.payload) if first else {}, seq, at))
    old_rows = {s.id: (s.seq, s.submitted_at) for s, *_rest in carried}
    for s, *_rest in carried:
        await db.delete(s)
    await db.flush()

    versions: dict[uuid.UUID, str] = {}
    for old, values, payload, seq, at in carried:
        old_seq, old_at = old_rows[old.id]
        new = Submission(form_id=form_id, seq=seq, submitted_at=at.astimezone(UTC), **values)
        db.add(new)
        await db.flush()
        vid = values["form_version_id"]
        if vid not in versions:
            version = await db.get(FormVersion, vid)
            versions[vid] = version.schema_hash if version else ""
        new.content_hash = compute_content_hash(new, versions[vid], [], [])
        await append_event(
            db,
            new,
            EventType.CREATED,
            payload={
                **payload,
                "seq": seq,
                "rebuiltFrom": str(old.id),
                "previousSeq": old_seq,
                "previousSubmittedAt": iso(old_at),
                "timeSource": time_source if (old.external_id or "") in times else "unchanged",
            },
        )
        await audit(
            db,
            "submission.import_rebuilt",
            org_id=form_rec.org_id,
            actor_id=actor_id,
            target_type="submission",
            target_id=old.id,
            meta={
                "formId": str(form_id),
                "newId": str(new.id),
                "seq": old_seq,
                "newSeq": seq,
                "submittedAt": iso(old_at),
                "newSubmittedAt": iso(new.submitted_at),
                "timeSource": time_source,
            },
        )
        report.changes.append(
            {"seq": old_seq, "newSeq": seq, "retimed": new.submitted_at != old_at}
        )
    return report
