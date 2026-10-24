"""Respondent uploads: start, receive (local backend), check and attach (DESIGN section 10).

Flow: ``start_upload`` creates a ``pending`` row for ``tmp/{form_id}/{file_id}`` and returns
an upload target (presigned POST on ``s3``; the API's own PUT URL plus a short-lived token on
``local``). On submit, ``check_files`` confirms every referenced file belongs to this form,
question and upload session, stats the object, sniffs its magic bytes against the question's
``accept`` list and hashes it; ``attach_files`` then moves the objects under
``files/{org_id}/{form_id}/{submission_id}/`` and marks the rows ``attached``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ids import uuid7
from app.logic.index import FormIndex
from app.models import FileRecord, FileState, FormRecord
from app.schemas.form import FileField, Form
from app.storage import ObjectNotFoundError, Storage
from app.uploads import sniff

UPLOAD_TOKEN_HEADER = "X-Upload-Token"
MAX_NAME = 255


class UploadError(Exception):
    """An upload request the server refuses; ``code`` is returned to the client."""

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def new_nonce() -> str:
    """Per-page-load upload session nonce handed out with the public form."""
    return secrets.token_urlsafe(24)


def nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def file_field(form: Form, field_id: str) -> FileField | None:
    info = FormIndex.build(form).elements.get(field_id)
    return info.element if info and isinstance(info.element, FileField) else None


def max_bytes(field: FileField, settings: Settings) -> int:
    limit_mb = settings.max_upload_mb
    if field.max_size_mb is not None:
        limit_mb = min(limit_mb, field.max_size_mb)
    return limit_mb * 1024 * 1024


def clean_name(name: str) -> str:
    """A display name safe to store and echo: no paths, no control characters."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return (base or "file")[:MAX_NAME]


# -- local upload tokens --------------------------------------------------------------------


def _sign(settings: Settings, payload: str) -> str:
    digest = hmac.new(settings.secret_key_bytes, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def upload_token(settings: Settings, file_id: uuid.UUID, now: float | None = None) -> str:
    expires = int((now or time.time()) + settings.upload_url_ttl_seconds)
    return f"{expires}.{_sign(settings, f'upload:{file_id}:{expires}')}"


def check_upload_token(settings: Settings, file_id: uuid.UUID, token: str) -> bool:
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(settings, f"upload:{file_id}:{expires}"))


# -- start ----------------------------------------------------------------------------------


@dataclass
class UploadTarget:
    file_id: uuid.UUID
    method: str  # "PUT" (through the API) or "POST" (presigned, multipart form)
    url: str
    fields: dict[str, str]
    headers: dict[str, str]


async def start_upload(
    db: AsyncSession,
    storage: Storage,
    settings: Settings,
    *,
    form_record: FormRecord,
    form: Form,
    field_id: str,
    name: str,
    size: int,
    mime: str,
    nonce: str,
) -> UploadTarget:
    field = file_field(form, field_id)
    if field is None:
        raise UploadError("unknown_field")
    name = clean_name(name)
    mime = (mime or "application/octet-stream").strip().lower()[:255]
    limit = max_bytes(field, settings)
    if size < 1:
        raise UploadError("file_empty")
    if size > limit:
        raise UploadError("file_too_large", 413)
    if not sniff.accepts(field.accept, name, mime):
        raise UploadError("file_type")
    file_id = uuid7()
    key = f"tmp/{form_record.id}/{file_id}"
    db.add(
        FileRecord(
            id=file_id,
            org_id=form_record.org_id,
            form_id=form_record.id,
            field_id=field_id,
            storage_key=key,
            original_name=name,
            mime=mime,
            size=size,
            max_size=limit,
            upload_session=nonce_hash(nonce),
        )
    )
    await db.flush()
    presigned = await storage.presign_upload(
        key,
        content_type=mime,
        max_bytes=limit,
        expires_in=settings.upload_url_ttl_seconds,
    )
    if presigned is not None:
        return UploadTarget(file_id, "POST", presigned.url, presigned.fields, {})
    return UploadTarget(
        file_id,
        "PUT",
        f"/api/v1/public/uploads/{file_id}",
        {},
        {UPLOAD_TOKEN_HEADER: upload_token(settings, file_id)},
    )


# -- submit: check and attach ---------------------------------------------------------------


@dataclass
class FileProblem:
    field: str
    code: str
    repeater: str | None = None
    row: int | None = None

    def as_error(self) -> dict[str, Any]:
        out: dict[str, Any] = {"field": self.field, "code": self.code}
        if self.repeater is not None:
            out.update(repeater=self.repeater, row=self.row)
        return out


@dataclass
class _Slot:
    """Where a file answer sits in the submission data."""

    field: FileField
    value: Any
    repeater: str | None
    row: int | None


def _slots(form: Form, data: dict[str, Any]) -> list[_Slot]:
    index = FormIndex.build(form)
    slots: list[_Slot] = []
    for info in index.elements.values():
        if not isinstance(info.element, FileField):
            continue
        if info.repeater_id is None:
            if info.id in data:
                slots.append(_Slot(info.element, data[info.id], None, None))
            continue
        rows = data.get(info.repeater_id)
        if isinstance(rows, list):
            for i, row in enumerate(rows):
                if isinstance(row, dict) and info.id in row:
                    slots.append(_Slot(info.element, row[info.id], info.repeater_id, i))
    return slots


def _file_ids(value: Any) -> list[uuid.UUID] | None:
    """The file ids of a file answer, or ``None`` if the value is malformed."""
    if not isinstance(value, list):
        return None
    ids: list[uuid.UUID] = []
    for item in value:
        raw = item.get("fileId") if isinstance(item, dict) else None
        if not isinstance(raw, str):
            return None
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            return None
    return ids


@dataclass
class CheckedFiles:
    records: dict[uuid.UUID, FileRecord]
    problems: list[FileProblem]


async def _hash(storage: Storage, key: str) -> str:
    digest = hashlib.sha256()
    async for chunk in storage.iter_chunks(key):
        digest.update(chunk)
    return digest.hexdigest()


async def check_files(
    db: AsyncSession,
    storage: Storage,
    *,
    form_record: FormRecord,
    form: Form,
    data: dict[str, Any],
    nonce: str | None,
) -> CheckedFiles:
    """Verify every file referenced by ``data`` (already stripped of hidden answers).

    Records that pass get their final ``size``, ``mime`` and ``sha256``; nothing is moved yet.
    """
    slots = _slots(form, data)
    wanted: dict[uuid.UUID, _Slot] = {}
    problems: list[FileProblem] = []
    for slot in slots:
        ids = _file_ids(slot.value)
        if ids is None:
            problems.append(FileProblem(slot.field.id, "file_invalid", slot.repeater, slot.row))
            continue
        if len(ids) > slot.field.max_files:
            problems.append(FileProblem(slot.field.id, "too_many_files", slot.repeater, slot.row))
            continue
        for fid in ids:
            if fid in wanted:  # the same upload used twice
                problems.append(FileProblem(slot.field.id, "file_invalid", slot.repeater, slot.row))
            wanted[fid] = slot
    if not wanted:
        return CheckedFiles({}, problems)
    rows = (await db.scalars(select(FileRecord).where(FileRecord.id.in_(wanted)))).all()
    records = {r.id: r for r in rows}
    session = nonce_hash(nonce) if nonce else None
    for fid, slot in wanted.items():
        rec = records.get(fid)

        def fail(code: str, slot: _Slot = slot) -> None:
            problems.append(FileProblem(slot.field.id, code, slot.repeater, slot.row))

        if (
            rec is None
            or rec.form_id != form_record.id
            or rec.field_id != slot.field.id
            or rec.state != FileState.PENDING
            or session is None
            or not hmac.compare_digest(rec.upload_session, session)
        ):
            fail("file_missing")
            continue
        try:
            info = await storage.stat(rec.storage_key)
        except ObjectNotFoundError:
            fail("file_missing")
            continue
        if info.size < 1 or info.size > rec.max_size:
            fail("file_too_large" if info.size > rec.max_size else "file_missing")
            continue
        head = await storage.read(rec.storage_key, length=sniff.SNIFF_BYTES)
        stored_type = sniff.checked_type(head, rec.original_name, rec.mime, slot.field.accept)
        if stored_type is None:
            fail("file_type")
            continue
        rec.size = info.size
        rec.mime = stored_type
        rec.sha256 = await _hash(storage, rec.storage_key)
    return CheckedFiles(records, problems)


def file_ref(rec: FileRecord) -> dict[str, Any]:
    """The answer value stored for one file (DESIGN 4.5)."""
    return {"fileId": str(rec.id), "name": rec.original_name, "size": rec.size, "mime": rec.mime}


def with_file_refs(form: Form, data: dict[str, Any], records: dict[uuid.UUID, FileRecord]) -> None:
    """Replace client-sent file values with the server's own metadata, in place."""
    for slot in _slots(form, data):
        ids = _file_ids(slot.value) or []
        refs = [file_ref(records[i]) for i in ids if i in records]
        target = data if slot.repeater is None else data[slot.repeater][slot.row]
        target[slot.field.id] = refs


async def attach_files(
    storage: Storage,
    records: dict[uuid.UUID, FileRecord],
    *,
    submission_id: uuid.UUID,
) -> None:
    """Move checked files to their permanent keys and mark them attached."""
    now = datetime.now(UTC)
    for rec in records.values():
        dst = f"files/{rec.org_id}/{rec.form_id}/{submission_id}/{rec.id}"
        await storage.move(rec.storage_key, dst)
        rec.storage_key = dst
        rec.submission_id = submission_id
        rec.state = FileState.ATTACHED
        rec.uploaded_at = rec.uploaded_at or now


# -- cleanup --------------------------------------------------------------------------------


async def purge_pending(db: AsyncSession, storage: Storage, settings: Settings) -> int:
    """Mark stale ``pending`` uploads ``orphaned`` and delete their objects."""
    cutoff = datetime.now(UTC) - timedelta(hours=settings.pending_upload_ttl_hours)
    stale = (
        await db.scalars(
            select(FileRecord).where(
                FileRecord.state == FileState.PENDING, FileRecord.created_at < cutoff
            )
        )
    ).all()
    for rec in stale:
        await storage.delete(rec.storage_key)
    if stale:
        await db.execute(
            update(FileRecord)
            .where(FileRecord.id.in_([r.id for r in stale]))
            .values(state=FileState.ORPHANED)
        )
    await db.commit()
    return len(stale)
