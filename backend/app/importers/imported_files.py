"""Fetch the files behind imported links into storage (DESIGN 13.3, "Imported files").

``submissions.imported_links`` maps a file or signature question to the links an import
brought along. Each entry is either the link itself (a string: not fetched yet) or, once
fetched, an object::

    {"url": ..., "key": "imported/{form}/{submission}/{field}-{n}.pdf", "name": ...,
     "mime": ..., "size": ..., "sha256": ..., "kind": "file" | "signature",
     "fetchedAt": ..., ["width": ..., "height": ...]}

The column is outside the answers and the content hash, so fetching changes neither: the
files are historic copies, shown as imported. Imported signatures are images only: they get
no ``signatures`` row, no strokes and no attestation, so they are never part of the
signature audit trail.

Runs are idempotent: entries that already have a stored copy are skipped, failures stay
links and can be retried. Each submission is committed on its own, so an interrupted run
keeps what it fetched.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.importers.jotform.files import (
    SIGNATURE_MAX_BYTES,
    FileFetchError,
    fetch_file,
    signature_png,
)
from app.logic.index import FormIndex
from app.models import FormRecord, FormVersion, Submission, SubmissionSource
from app.schemas.form import FileField, Form, SignatureField
from app.services.users import audit
from app.storage import Storage
from app.uploads.service import clean_name, max_bytes
from app.uploads.sniff import SNIFF_BYTES, checked_type, extension

log = logging.getLogger(__name__)

KEY_PREFIX = "imported"
_EXT = re.compile(r"^\.[a-z0-9]{1,10}$")


# -- reading the column ----------------------------------------------------------------------


def is_stored(entry: Any) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("key"), str)


def entry_url(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("url", ""))
    return str(entry)


def pending_links(imported: dict[str, Any] | None) -> dict[str, list[str]]:
    """Links that have no stored copy (yet), by field id."""
    out: dict[str, list[str]] = {}
    for field_id, entries in (imported or {}).items():
        urls = [entry_url(e) for e in entries or [] if not is_stored(e)]
        if urls:
            out[field_id] = urls
    return out


def stored_files(imported: dict[str, Any] | None) -> list[tuple[str, int, dict[str, Any]]]:
    """``(field_id, index, entry)`` for every stored copy."""
    return [
        (field_id, i, e)
        for field_id, entries in (imported or {}).items()
        for i, e in enumerate(entries or [])
        if is_stored(e)
    ]


def stored_keys(imported: dict[str, Any] | None) -> list[str]:
    return [e["key"] for _f, _i, e in stored_files(imported)]


def stored_entry(imported: dict[str, Any] | None, field_id: str, index: int) -> dict[str, Any]:
    """The stored copy at ``field_id``/``index``, or ``KeyError``."""
    entries = (imported or {}).get(field_id) or []
    if not 0 <= index < len(entries) or not is_stored(entries[index]):
        raise KeyError(field_id)
    entry: dict[str, Any] = entries[index]
    return entry


# -- fetching --------------------------------------------------------------------------------


@dataclass
class FileResult:
    seq: int
    field_id: str
    index: int
    # fetched | skipped (already stored) | failed | pending (dry run)
    status: str
    reason: str | None = None
    kind: str | None = None
    size: int | None = None
    mime: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "fieldId": self.field_id,
            "index": self.index,
            "status": self.status,
            "reason": self.reason,
            "kind": self.kind,
            "size": self.size,
            "mime": self.mime,
        }


@dataclass
class FetchReport:
    submissions: int = 0
    results: list[FileResult] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def as_json(self) -> dict[str, Any]:
        return {
            "submissions": self.submissions,
            "counts": self.counts(),
            "files": [r.as_json() for r in self.results],
        }


def _key(form_id: uuid.UUID, sub_id: uuid.UUID, field_id: str, index: int, ext: str) -> str:
    return f"{KEY_PREFIX}/{form_id}/{sub_id}/{field_id}-{index}{ext}"


async def _fetch_one(
    storage: Storage,
    settings: Settings,
    sub: Submission,
    question: FileField | SignatureField,
    index: int,
    url: str,
    api_key: str | None,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """Download, check and store one link; the new column entry. Raises FileFetchError."""
    is_signature = isinstance(question, SignatureField)
    limit = (
        max_bytes(question, settings) if isinstance(question, FileField) else SIGNATURE_MAX_BYTES
    )
    got = await fetch_file(url, settings, api_key=api_key, max_bytes=limit, transport=transport)
    name = clean_name(got.name)
    extra: dict[str, Any] = {}
    if isinstance(question, SignatureField):
        data, width, height = signature_png(got.data)
        mime, ext = "image/png", ".png"
        if extension(name) != ".png":
            name = f"{name.rsplit('.', 1)[0] if '.' in name else name}.png"
        extra = {"width": width, "height": height}
    else:
        data = got.data
        checked = checked_type(data[:SNIFF_BYTES], name, got.mime, question.accept)
        if checked is None:
            raise FileFetchError("bad_type")
        mime = checked
        ext = extension(name) if _EXT.match(extension(name)) else ""
    key = _key(sub.form_id, sub.id, question.id, index, ext)
    await storage.put(key, data, content_type=mime, max_bytes=max(limit, len(data)))
    return {
        "url": url,
        "key": key,
        "name": name,
        "mime": mime,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "kind": "signature" if is_signature else "file",
        "fetchedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        **extra,
    }


async def fetch_form_files(
    db: AsyncSession,
    storage: Storage,
    settings: Settings,
    form_id: uuid.UUID,
    *,
    api_key: str | None,
    dry_run: bool = False,
    actor_id: uuid.UUID | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchReport:
    """Fetch every not-yet-stored link of the form's imported submissions into storage."""
    form_rec = await db.get(FormRecord, form_id)
    if form_rec is None:
        raise LookupError("form_not_found")
    subs = (
        await db.scalars(
            select(Submission)
            .where(
                Submission.form_id == form_id,
                Submission.source == SubmissionSource.JOTFORM_IMPORT,
                Submission.deleted_at.is_(None),
                Submission.imported_links.is_not(None),
            )
            .order_by(Submission.seq)
        )
    ).all()
    report = FetchReport()
    schemas: dict[uuid.UUID, FormIndex] = {}
    for sub in subs:
        if sub.form_version_id not in schemas:
            version = await db.get(FormVersion, sub.form_version_id)
            assert version is not None
            schemas[sub.form_version_id] = FormIndex.build(Form.model_validate(version.schema))
        index = schemas[sub.form_version_id]
        links: dict[str, Any] = dict(sub.imported_links or {})
        changed = False
        report.submissions += 1
        for field_id, entries in links.items():
            info = index.elements.get(field_id)
            question = info.element if info else None
            new_entries = list(entries or [])
            for i, entry in enumerate(new_entries):
                if is_stored(entry):
                    report.results.append(
                        FileResult(sub.seq, field_id, i, "skipped", "already_stored", entry["kind"])
                    )
                    continue
                if not isinstance(question, FileField | SignatureField):
                    report.results.append(FileResult(sub.seq, field_id, i, "failed", "question"))
                    continue
                kind = "signature" if isinstance(question, SignatureField) else "file"
                if dry_run:
                    report.results.append(FileResult(sub.seq, field_id, i, "pending", None, kind))
                    continue
                try:
                    stored = await _fetch_one(
                        storage, settings, sub, question, i, entry_url(entry), api_key, transport
                    )
                except FileFetchError as exc:
                    report.results.append(
                        FileResult(sub.seq, field_id, i, "failed", exc.code, kind)
                    )
                    continue
                new_entries[i] = stored
                changed = True
                report.results.append(
                    FileResult(
                        sub.seq, field_id, i, "fetched", None, kind, stored["size"], stored["mime"]
                    )
                )
            links[field_id] = new_entries
        if changed:
            sub.imported_links = links  # a new dict, so the JSONB change is saved
            await db.commit()
    if not dry_run:
        counts = report.counts()
        await audit(
            db,
            "submissions.import_files",
            org_id=form_rec.org_id,
            actor_id=actor_id,
            target_type="form",
            target_id=form_id,
            meta={"submissions": report.submissions, **counts},
        )
        await db.commit()
    log.info("imported files for form %s: %s", form_id, report.counts())
    return report
