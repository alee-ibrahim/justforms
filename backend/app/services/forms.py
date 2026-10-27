"""Form drafts, revisions and publishing."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import jsonpatch
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.config import load_config, publish_problems
from app.logic.index import FormIndex
from app.models import (
    ActorType,
    FormDraftHistory,
    FormRecord,
    FormStatus,
    FormVersion,
)
from app.schemas.form import Form
from app.schemas.rules import Issue, collect_publish_issues
from app.services import slugs

HISTORY_LIMIT = 200


class DraftConflictError(Exception):
    """The client's base revision is not the current one."""


class DraftPatchError(Exception):
    """The patch could not be applied (bad path, failed test op...)."""


class NeverPublishedError(Exception):
    """The form has no published version to go back to."""


class PublishError(Exception):
    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("form cannot be published")
        self.issues = issues


def new_draft(title: str, language: str) -> dict[str, Any]:
    draft = {
        "schemaVersion": "1",
        "settings": {"language": language, "title": title},
        "pages": [{"id": "page_1", "elements": []}],
    }
    return Form.model_validate(draft).dump()


def form_title(schema: dict[str, Any]) -> str:
    return str(schema.get("settings", {}).get("title", ""))[:500]


def schema_hash(schema: dict[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def apply_draft_patch(
    db: AsyncSession,
    form: FormRecord,
    base_revision: int,
    patch: list[dict[str, Any]],
    actor_id: uuid.UUID,
    *,
    actor_type: ActorType = ActorType.USER,
    ai_session_id: uuid.UUID | None = None,
) -> FormRecord:
    """Apply an RFC 6902 patch to the draft, validate it and record an undo entry.

    Raises DraftConflictError, DraftPatchError or pydantic.ValidationError.
    """
    if base_revision != form.draft_revision:
        raise DraftConflictError
    old = form.draft_schema
    try:
        new = jsonpatch.apply_patch(old, patch, in_place=False)
    except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException, TypeError) as exc:
        raise DraftPatchError(str(exc)) from exc
    validated = Form.model_validate(new).dump()  # raises ValidationError
    inverse = jsonpatch.make_patch(validated, old).patch
    forward = jsonpatch.make_patch(old, validated).patch

    # A new edit drops the redo stack.
    await db.execute(
        delete(FormDraftHistory).where(
            FormDraftHistory.form_id == form.id, FormDraftHistory.undone.is_(True)
        )
    )
    form.draft_revision += 1
    form.draft_schema = validated
    form.title = form_title(validated)
    await slugs.follow_title(db, form)
    db.add(
        FormDraftHistory(
            form_id=form.id,
            revision=form.draft_revision,
            patch=forward,
            inverse_patch=inverse,
            actor_type=actor_type,
            actor_id=actor_id,
            ai_session_id=ai_session_id,
        )
    )
    await db.flush()
    # Keep only the latest HISTORY_LIMIT entries per form.
    cutoff = form.draft_revision - HISTORY_LIMIT
    if cutoff > 0:
        await db.execute(
            delete(FormDraftHistory).where(
                FormDraftHistory.form_id == form.id, FormDraftHistory.revision <= cutoff
            )
        )
    return form


async def _history_entry(
    db: AsyncSession, form: FormRecord, *, undone: bool
) -> FormDraftHistory | None:
    order = FormDraftHistory.revision.asc() if undone else FormDraftHistory.revision.desc()
    return await db.scalar(
        select(FormDraftHistory)
        .where(FormDraftHistory.form_id == form.id, FormDraftHistory.undone.is_(undone))
        .order_by(order)
        .limit(1)
    )


async def history_state(db: AsyncSession, form: FormRecord) -> tuple[bool, bool]:
    """(can_undo, can_redo) for the draft."""
    rows = await db.execute(
        select(FormDraftHistory.undone, func.count())
        .where(FormDraftHistory.form_id == form.id)
        .group_by(FormDraftHistory.undone)
    )
    counts = {bool(undone): n for undone, n in rows.all()}
    return counts.get(False, 0) > 0, counts.get(True, 0) > 0


async def step_history(
    db: AsyncSession, form: FormRecord, base_revision: int, *, redo: bool
) -> bool:
    """Undo the latest edit (or redo the latest undone one). Returns False when there is
    nothing to undo/redo. Raises DraftConflictError on a stale base revision.

    Undo applies the entry's inverse patch and flags it ``undone``; redo re-applies the forward
    patch of the most recently undone entry. Both bump the draft revision like an edit.
    """
    if base_revision != form.draft_revision:
        raise DraftConflictError
    entry = await _history_entry(db, form, undone=redo)
    if entry is None:
        return False
    ops = entry.patch if redo else entry.inverse_patch
    try:
        new = jsonpatch.apply_patch(form.draft_schema, ops, in_place=False)
    except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException) as exc:
        # History no longer applies (should not happen with linear history): drop it.
        await db.execute(delete(FormDraftHistory).where(FormDraftHistory.form_id == form.id))
        raise DraftPatchError(str(exc)) from exc
    validated = Form.model_validate(new).dump()
    form.draft_schema = validated
    form.draft_revision += 1
    form.title = form_title(validated)
    await slugs.follow_title(db, form)
    await db.execute(
        update(FormDraftHistory).where(FormDraftHistory.id == entry.id).values(undone=not redo)
    )
    await db.flush()
    return True


def unflagged_sensitive(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str]]:
    """Questions marked sensitive in ``old`` that are still in ``new`` but no longer
    sensitive, as (key, label). Turning the flag off is for owners only (it changes what
    webhooks, approvers, emails and the AI receive)."""
    before = FormIndex.build(Form.model_validate(old)).elements
    after = FormIndex.build(Form.model_validate(new)).elements
    out: list[tuple[str, str]] = []
    for key, info in before.items():
        if not getattr(info.element, "sensitive", False):
            continue
        now = after.get(key)
        if now is not None and not getattr(now.element, "sensitive", False):
            out.append((key, str(getattr(now.element, "label", "") or key)))
    return out


async def live_schema(db: AsyncSession, form: FormRecord) -> tuple[int, dict[str, Any]] | None:
    """The live (latest published) version's number and document, None before the first publish."""
    if form.current_version_id is None:
        return None
    version = await db.get(FormVersion, form.current_version_id)
    return (version.version, version.schema) if version else None


async def discard_draft(
    db: AsyncSession, form: FormRecord, base_revision: int, actor_id: uuid.UUID
) -> int | None:
    """Reset the draft to the live version as one ordinary (undoable) edit.

    Returns the live version number, or None when the draft already matches it. Raises
    DraftConflictError on a stale base revision and NeverPublishedError before the first publish.
    """
    if base_revision != form.draft_revision:
        raise DraftConflictError
    live = await live_schema(db, form)
    if live is None:
        raise NeverPublishedError
    number, schema = live
    ops = jsonpatch.make_patch(form.draft_schema, schema).patch
    if not ops:
        return None
    await apply_draft_patch(db, form, base_revision, ops, actor_id)
    return number


async def publish(db: AsyncSession, form: FormRecord, actor_id: uuid.UUID) -> FormVersion:
    try:
        parsed = Form.model_validate(form.draft_schema)
    except ValidationError as exc:  # pragma: no cover - drafts are validated on save
        raise PublishError([Issue("invalid", str(exc))]) from exc
    issues = collect_publish_issues(parsed)
    # Approval steps that read the approver's address from a question need that question.
    issues += [
        Issue(f"approval_{p.code}", p.message, None)
        for p in publish_problems(load_config(form.settings), parsed)
    ]
    if issues:
        raise PublishError(issues)
    schema = parsed.dump()
    latest = await db.scalar(
        select(func.max(FormVersion.version)).where(FormVersion.form_id == form.id)
    )
    version = FormVersion(
        form_id=form.id,
        version=(latest or 0) + 1,
        schema=schema,
        schema_hash=schema_hash(schema),
        published_by=actor_id,
    )
    db.add(version)
    await db.flush()
    form.current_version_id = version.id
    if form.status == FormStatus.DRAFT:
        form.status = FormStatus.LIVE
    return version
