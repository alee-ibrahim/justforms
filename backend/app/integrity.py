"""Submission content hash and the per-submission event hash chain (DESIGN 9.3, 9.4).

``content_hash = SHA-256(JCS({form_id, form_version_id, schema_hash, submission_id,
submitted_at, data, files: [{fileId, sha256}], signatures: [{fieldId, strokes_sha256,
received_at}]}))`` with JCS = RFC 8785. Each event stores
``hash = SHA-256(prev_hash || JCS(event without hash))``; the first event chains from the
content hash, so editing a row, deleting an event or rewriting history breaks verification.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import rfc8785
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EventType,
    FileRecord,
    FileState,
    FormVersion,
    Signature,
    Submission,
    SubmissionEvent,
)


def jcs(value: Any) -> bytes:
    return rfc8785.dumps(value)


def iso(dt: datetime) -> str:
    """Canonical timestamp text: UTC, microseconds, ``Z``."""
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def content_document(
    sub: Submission,
    schema_hash: str,
    files: list[FileRecord],
    signatures: list[Signature],
) -> dict[str, Any]:
    return {
        "form_id": str(sub.form_id),
        "form_version_id": str(sub.form_version_id),
        "schema_hash": schema_hash,
        "submission_id": str(sub.id),
        "submitted_at": iso(sub.submitted_at),
        "data": sub.data,
        "files": sorted(
            ({"fileId": str(f.id), "sha256": f.sha256 or ""} for f in files),
            key=lambda f: f["fileId"],
        ),
        "signatures": sorted(
            (
                {
                    "fieldId": s.field_id,
                    "strokes_sha256": s.strokes_sha256,
                    "received_at": iso(s.received_at),
                }
                for s in signatures
            ),
            key=lambda s: s["fieldId"],
        ),
    }


def compute_content_hash(
    sub: Submission, schema_hash: str, files: list[FileRecord], signatures: list[Signature]
) -> str:
    return hashlib.sha256(jcs(content_document(sub, schema_hash, files, signatures))).hexdigest()


async def load_parts(
    db: AsyncSession, sub: Submission
) -> tuple[str, list[FileRecord], list[Signature]]:
    version = await db.get(FormVersion, sub.form_version_id)
    files = (
        await db.scalars(
            select(FileRecord).where(
                FileRecord.submission_id == sub.id, FileRecord.state == FileState.ATTACHED
            )
        )
    ).all()
    sigs = (await db.scalars(select(Signature).where(Signature.submission_id == sub.id))).all()
    return (version.schema_hash if version else ""), list(files), list(sigs)


def _event_body(ev: SubmissionEvent) -> dict[str, Any]:
    return {
        "submission_id": str(ev.submission_id),
        "seq": ev.seq,
        "type": ev.type.value if isinstance(ev.type, EventType) else str(ev.type),
        "actor_id": str(ev.actor_id) if ev.actor_id else None,
        "payload": ev.payload,
        "created_at": iso(ev.created_at),
    }


def event_hash(prev_hash: str, ev: SubmissionEvent) -> str:
    return hashlib.sha256(bytes.fromhex(prev_hash) + jcs(_event_body(ev))).hexdigest()


async def append_event(
    db: AsyncSession,
    sub: Submission,
    type_: EventType,
    *,
    actor_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> SubmissionEvent:
    """Add the next event to the submission's chain (the caller commits).

    Serialised per submission by locking the submission row."""
    await db.execute(select(Submission.id).where(Submission.id == sub.id).with_for_update())
    last = (
        await db.execute(
            select(SubmissionEvent.seq, SubmissionEvent.hash)
            .where(SubmissionEvent.submission_id == sub.id)
            .order_by(SubmissionEvent.seq.desc())
            .limit(1)
        )
    ).first()
    prev = last.hash if last else (sub.content_hash or "0" * 64)
    ev = SubmissionEvent(
        submission_id=sub.id,
        seq=(last.seq + 1) if last else 1,
        type=type_,
        actor_id=actor_id,
        payload=payload or {},
        created_at=datetime.now(UTC),
        prev_hash=prev,
        hash="",
    )
    ev.hash = event_hash(prev, ev)
    db.add(ev)
    await db.flush()
    return ev


@dataclass
class Verification:
    content_ok: bool
    stored_hash: str | None
    computed_hash: str
    chain_ok: bool
    chain_length: int
    chain_head: str | None
    broken_at: int | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.content_ok and self.chain_ok


async def verify_submission(db: AsyncSession, sub: Submission) -> Verification:
    schema_hash, files, sigs = await load_parts(db, sub)
    computed = compute_content_hash(sub, schema_hash, files, sigs)
    problems: list[str] = []
    content_ok = sub.content_hash is not None and sub.content_hash == computed
    if not content_ok:
        problems.append("content_hash_mismatch" if sub.content_hash else "no_content_hash")
    events = (
        await db.scalars(
            select(SubmissionEvent)
            .where(SubmissionEvent.submission_id == sub.id)
            .order_by(SubmissionEvent.seq)
        )
    ).all()
    prev = sub.content_hash or "0" * 64
    broken_at: int | None = None
    for expected_seq, ev in enumerate(events, start=1):
        if ev.seq != expected_seq or ev.prev_hash != prev or event_hash(prev, ev) != ev.hash:
            broken_at = ev.seq
            break
        prev = ev.hash
    chain_ok = broken_at is None and bool(events)
    if not events:
        problems.append("no_events")
    elif broken_at is not None:
        problems.append("chain_broken")
    return Verification(
        content_ok=content_ok,
        stored_hash=sub.content_hash,
        computed_hash=computed,
        chain_ok=chain_ok,
        chain_length=len(events),
        chain_head=events[-1].hash if events else None,
        broken_at=broken_at,
        problems=problems,
    )


async def event_count(db: AsyncSession, submission_id: uuid.UUID) -> int:
    return int(
        await db.scalar(select(func.count()).where(SubmissionEvent.submission_id == submission_id))
        or 0
    )
