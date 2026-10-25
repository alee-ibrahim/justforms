"""Import jobs: create a draft form from a Jotform preview, and bring submissions in from an
uploaded export (DESIGN 13.1, 13.3)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.answers import search_text
from app.branding.images import BrandImageError, clean_image
from app.config import Settings
from app.importers.jotform import api_source
from app.importers.jotform.submissions import (
    IGNORE,
    RowResult,
    Table,
    convert_row,
    importable_fields,
    read_table,
)
from app.integrity import append_event, compute_content_hash
from app.models import (
    EventType,
    FormPermission,
    FormRecord,
    FormRole,
    FormVersion,
    Import,
    ImportKind,
    ImportStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
)
from app.schemas.form import Form
from app.services import forms as form_svc
from app.services import slugs
from app.services.users import audit
from app.storage import Storage, StorageError
from app.theme import logo as form_logos

log = logging.getLogger(__name__)
BATCH = 500
# Problem rows kept in the report (the counts are always complete).
REPORT_ROWS = 200


async def create_form(
    db: AsyncSession,
    imp: Import,
    user_id: uuid.UUID,
    *,
    title: str | None,
    language: str | None,
    storage: Storage | None = None,
) -> FormRecord:
    """Turn a form-import preview into a new draft form owned by ``user_id``. The logo kept
    with the preview (``source["logo"]``) becomes the form's own logo; the caller deletes
    the preview's copy after committing."""
    schema: dict[str, Any] = dict(imp.source["form"])
    settings = dict(schema["settings"])
    if title:
        settings["title"] = title
    if language:
        settings["language"] = language
    schema["settings"] = settings
    draft = Form.model_validate(schema).dump()
    record_settings: dict[str, Any] = {"importedFrom": "jotform"}
    if imp.source.get("jotformFormId"):
        record_settings["jotformFormId"] = str(imp.source["jotformFormId"])
    if imp.source.get("captcha"):
        record_settings["captcha"] = "auto"
    form = FormRecord(
        org_id=imp.org_id,
        slug=await slugs.unique_slug(db, slugs.slugify(form_svc.form_title(draft))),
        title=form_svc.form_title(draft),
        draft_schema=draft,
        created_by=user_id,
        settings=record_settings,
    )
    db.add(form)
    await db.flush()
    db.add(FormPermission(form_id=form.id, user_id=user_id, role=FormRole.OWNER))
    logo = imp.source.get("logo")
    if storage is not None and isinstance(logo, dict) and logo.get("key"):
        entry = await _attach_logo(storage, form.id, str(logo["key"]))
        if entry is not None:
            form.settings = {**record_settings, form_logos.FORM_KEY: entry}
        imp.source = {k: v for k, v in imp.source.items() if k != "logo"}
    imp.form_id = form.id
    imp.status = ImportStatus.DONE
    await audit(
        db,
        "form.import",
        org_id=imp.org_id,
        actor_id=user_id,
        target_type="form",
        target_id=form.id,
        meta={"importId": str(imp.id), "kind": imp.kind.value},
    )
    return form


async def _attach_logo(
    storage: Storage, form_id: uuid.UUID, temp_key: str
) -> dict[str, Any] | None:
    """Store the preview's logo as ``form_id``'s own (cleaned again: it is read back from
    storage). None when it is gone or no longer passes."""
    try:
        img = clean_image("logo", await storage.read(temp_key))
    except (BrandImageError, StorageError, OSError):
        log.warning("import logo %s is missing or invalid; skipped", temp_key)
        return None
    return await form_logos.store(storage, form_id, img)


# -- submissions -----------------------------------------------------------------------------


async def _existing_ids(db: AsyncSession, form_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(
        select(Submission.external_id).where(
            Submission.form_id == form_id,
            Submission.source == SubmissionSource.JOTFORM_IMPORT,
            Submission.external_id.is_not(None),
        )
    )
    return {r for r in rows if r}


async def _import_rows(
    db: AsyncSession,
    settings: Settings,
    imp: Import,
    table: Table,
) -> dict[str, Any]:
    form_rec = await db.get(FormRecord, imp.form_id)
    version = await db.get(FormVersion, uuid.UUID(imp.source["versionId"]))
    if form_rec is None or version is None:
        raise RuntimeError("form or version gone")
    form = Form.model_validate(version.schema)
    fields = {f.id: f for f in importable_fields(form)}
    mapping: list[str] = list(imp.mapping.get("columns", []))
    mapping += [IGNORE] * (len(table.headers) - len(mapping))
    order = str(imp.mapping.get("dateOrder", "auto"))
    status = SubmissionStatus(imp.mapping.get("status", SubmissionStatus.NEW.value))
    has_id = "meta:external_id" in mapping
    seen = await _existing_ids(db, form_rec.id)
    now = datetime.now(UTC)

    imported = skipped_duplicate = skipped_empty = 0
    dropped: dict[str, int] = {}
    problem_rows: list[dict[str, Any]] = []
    links_count = 0

    # Convert every row first: reference numbers then go out oldest first.
    rows: list[tuple[int, RowResult]] = []
    for number, row in enumerate(table.rows, start=2):  # row 1 is the header
        res = convert_row(row, mapping, fields, settings.tz, order)
        for col, code, text in res.problems:
            header = table.headers[col] or f"Column {col + 1}"
            dropped[header] = dropped.get(header, 0) + 1
            if len(problem_rows) < REPORT_ROWS:
                problem_rows.append(
                    {"row": number, "column": header, "problem": code, "value": text}
                )
        if res.external_id and res.external_id in seen:
            skipped_duplicate += 1
            continue
        if not res.data and not res.links:
            skipped_empty += 1
            continue
        if res.external_id:
            seen.add(res.external_id)
        rows.append((number, res))

    # Exact submit times from Jotform's API when a key is configured (exports carry dates
    # only, or times in the account's zone); the file's value stays the fallback.
    exact, times_report = await exact_times(settings, form_rec)
    exact_used = 0
    for _number, res in rows:
        at = exact.get(res.external_id or "")
        if at is not None:
            res.submitted_at = at
            exact_used += 1
    rows.sort(key=lambda r: (r[1].submitted_at or now, r[0]))

    # Serialise reference numbers with live submissions on the same form.
    await db.execute(select(FormRecord.id).where(FormRecord.id == form_rec.id).with_for_update())
    last = await db.scalar(
        select(func.max(Submission.seq)).where(Submission.form_id == form_rec.id)
    )
    seq = last or 0
    pending = 0
    for done, (number, res) in enumerate(rows, start=1):
        seq += 1
        submitted = res.submitted_at.astimezone(UTC) if res.submitted_at else now
        sub = Submission(
            form_id=form_rec.id,
            form_version_id=version.id,
            seq=seq,
            status=status,
            language=form.settings.language,
            data=res.data,
            submitted_at=submitted,
            ip=res.ip,
            source=SubmissionSource.JOTFORM_IMPORT,
            external_id=res.external_id,
            imported_links=res.links or None,
            search_text=search_text(form, res.data),
        )
        db.add(sub)
        await db.flush()
        sub.content_hash = compute_content_hash(sub, version.schema_hash, [], [])
        payload: dict[str, Any] = {
            "seq": seq,
            "version": version.version,
            "imported": True,
            "importId": str(imp.id),
            "sourceRowNumber": number,
        }
        if res.external_id:
            payload["jotformSubmissionId"] = res.external_id
            if res.external_id in exact:
                payload["timeSource"] = "jotform_api"
        await append_event(db, sub, EventType.CREATED, payload=payload)
        imported += 1
        links_count += sum(len(v) for v in res.links.values())
        pending += 1
        if pending >= BATCH:
            imp.stats = {**imp.stats, "rowsDone": done}
            await db.flush()
            pending = 0

    return {
        "rowsTotal": len(table.rows),
        "imported": imported,
        "skippedDuplicate": skipped_duplicate,
        "skippedEmpty": skipped_empty,
        "cellsDropped": sum(dropped.values()),
        "droppedByColumn": dropped,
        "links": links_count,
        "problemRows": problem_rows,
        "dedupe": has_id,
        "exactTimes": {**times_report, "used": exact_used},
    }


def jotform_form_id(form_rec: FormRecord) -> str | None:
    value = (form_rec.settings or {}).get("jotformFormId")
    return str(value) if value else None


async def exact_times(
    settings: Settings, form_rec: FormRecord, jotform_id: str | None = None
) -> tuple[dict[str, datetime], dict[str, Any]]:
    """Jotform submission id -> exact submit time (UTC) through the API, when a key is set
    and the form's Jotform id is known. Never raises: the report says why times are missing."""
    form_ref = jotform_id or jotform_form_id(form_rec)
    if settings.jotform_api_key is None or not form_ref:
        reason = "no_key" if settings.jotform_api_key is None else "no_jotform_form_id"
        return {}, {"source": "file", "reason": reason}
    try:
        times = await api_source.submission_times(
            settings.jotform_api_region,
            settings.jotform_api_key.get_secret_value(),
            form_ref,
            tz=ZoneInfo(settings.jotform_api_timezone),
        )
    except api_source.JotformApiError as exc:
        log.warning("Jotform submission times unavailable: %s", exc.code)
        return {}, {"source": "file", "reason": f"api_{exc.code}"}
    return times, {"source": "jotform_api", "found": len(times)}


async def run_submissions_import(
    db: AsyncSession, storage: Storage, settings: Settings, import_id: uuid.UUID
) -> bool:
    """Worker job: read the stored file and insert the rows. Idempotent per Jotform
    submission id; one transaction, so a failure leaves no partial import."""
    imp = await db.get(Import, import_id)
    if imp is None or imp.kind != ImportKind.JOTFORM_SUBMISSIONS:
        return False
    if imp.status != ImportStatus.RUNNING or not imp.source_key:
        return False
    key = imp.source_key
    try:
        data = await storage.read(key)
        table = read_table(data, str(imp.source.get("filename", "")))
        report = await _import_rows(db, settings, imp, table)
        imp.report = report
        imp.stats = {"rowsDone": report["rowsTotal"], "imported": report["imported"]}
        imp.status = ImportStatus.DONE
        imp.source_key = None
        await audit(
            db,
            "submissions.import",
            org_id=imp.org_id,
            actor_id=imp.created_by,
            target_type="form",
            target_id=imp.form_id,
            meta={"importId": str(imp.id), "imported": report["imported"]},
        )
        await db.commit()
    except Exception:
        log.exception("submission import %s failed", import_id)
        await db.rollback()
        imp = await db.get(Import, import_id)
        if imp is not None:
            imp.status = ImportStatus.FAILED
            imp.report = {"error": "The file could not be imported. Nothing was added."}
            await db.commit()
        return False
    await storage.delete(key)
    return True
