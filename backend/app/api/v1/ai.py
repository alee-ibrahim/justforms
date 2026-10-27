"""AI assistant endpoints (DESIGN 12, 17). Editors and owners only; 404 when AI is off.

A request streams Server-Sent Events: ``message.delta`` (the AI's text), ``tool.applied`` /
``tool.error`` (one per tool call), then ``proposal`` (the suggestion), ``error``,
``cancelled`` or ``filled_in``, and finally ``done``. Nothing reaches the draft until
``apply``. Only the form's schema goes to the provider, never submissions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, StringConstraints
from sqlalchemy import select, update

from app.ai import service as ai_svc
from app.ai.images import MAX_BYTES, DocumentError, prepare
from app.ai.orchestrator import BudgetExceeded, TurnOutcome, run_request
from app.ai.providers import make_provider
from app.ai.tools import WorkingCopy, compact
from app.ai.types import AIProvider, ChatMessage, Usage
from app.api.v1.common import ApiModel
from app.api.v1.forms import DraftOut, draft_out
from app.auth.deps import DbDep, RedisDep, SettingsDep
from app.config import Settings, get_settings
from app.models import AiMessage, AiMode, AiSession, AiSessionStatus
from app.permissions import FormAccess, FormEditor
from app.ratelimit import enforce
from app.services.users import audit

log = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])

MAX_REQUEST_CHARS = 4000
_providers: dict[bool, AIProvider | None] = {}


def _provider(settings: Settings, vision: bool) -> AIProvider:
    if vision not in _providers:
        _providers[vision] = make_provider(settings, vision=vision)
    provider = _providers[vision]
    if provider is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "ai_vision_unavailable" if vision else "ai_disabled"
        )
    return provider


def get_ai_provider(settings: Annotated[Settings, Depends(get_settings)]) -> AIProvider:
    """FastAPI dependency; tests override it with a scripted provider."""
    return _provider(settings, False)


def get_vision_provider(settings: Annotated[Settings, Depends(get_settings)]) -> AIProvider:
    return _provider(settings, True)


ProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
VisionDep = Annotated[AIProvider, Depends(get_vision_provider)]


class SessionCreate(ApiModel):
    # Close the current chat and start a new one.
    fresh: bool = False


class MessageOut(ApiModel):
    id: uuid.UUID
    role: str
    content: dict[str, Any]
    created_at: datetime


class SessionOut(ApiModel):
    id: uuid.UUID
    mode: AiMode
    status: AiSessionStatus
    provider: str
    model: str
    messages: list[MessageOut] = Field(default_factory=list)
    proposal: dict[str, Any] | None = None


class MessageIn(ApiModel):
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REQUEST_CHARS)
    ]


class ApplyIn(ApiModel):
    # The revision the studio last saved (informational: the server rebases if needed).
    base_revision: int


class ApplyOut(ApiModel):
    draft: DraftOut
    session: SessionOut


async def _session_out(db: DbDep, session: AiSession) -> SessionOut:
    rows = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.session_id == session.id)
                .order_by(AiMessage.created_at, AiMessage.id)
            )
        )
        .scalars()
        .all()
    )
    return SessionOut(
        id=session.id,
        mode=session.mode,
        status=session.status,
        provider=session.provider,
        model=session.model,
        messages=[MessageOut.model_validate(m) for m in rows],
        proposal=ai_svc.proposal(session),
    )


async def _load(db: DbDep, access: FormAccess, session_id: uuid.UUID) -> AiSession:
    session = await db.get(AiSession, session_id)
    # Chats are personal: other editors of the form can't read or drive them.
    if (
        session is None
        or session.form_id != access.form.id
        or session.user_id != access.user.id
        or session.status == AiSessionStatus.CLOSED
        or session.mode == AiMode.ASK
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ai_session_not_found")
    return session


@router.post("/forms/{form_id}/ai/sessions", response_model=SessionOut)
async def open_session(
    body: SessionCreate, db: DbDep, access: FormEditor, provider: ProviderDep
) -> SessionOut:
    """The person's current chat on this form, or a new one."""
    form, user = access.form, access.user
    existing = await db.scalar(
        select(AiSession)
        .where(
            AiSession.form_id == form.id,
            AiSession.user_id == user.id,
            AiSession.status != AiSessionStatus.CLOSED,
            AiSession.mode != AiMode.ASK,
        )
        .order_by(AiSession.created_at.desc())
        .limit(1)
    )
    if existing is not None and not body.fresh:
        return await _session_out(db, existing)
    if body.fresh:
        await db.execute(
            update(AiSession)
            .where(
                AiSession.form_id == form.id,
                AiSession.user_id == user.id,
                AiSession.status != AiSessionStatus.CLOSED,
                AiSession.mode != AiMode.ASK,
            )
            .values(status=AiSessionStatus.CLOSED, working_schema=None, base_schema=None)
        )
    session = AiSession(
        org_id=form.org_id,
        form_id=form.id,
        user_id=user.id,
        provider=provider.name,
        model=provider.model,
        mode=AiMode.CREATE if ai_svc.is_empty(form.draft_schema) else AiMode.EDIT,
    )
    db.add(session)
    await db.flush()
    await audit(
        db,
        "ai.session_create",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="form",
        target_id=form.id,
        meta={"session": str(session.id), "provider": provider.name, "model": provider.model},
    )
    await db.commit()
    return await _session_out(db, session)


@router.get("/forms/{form_id}/ai/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: uuid.UUID, db: DbDep, access: FormEditor, provider: ProviderDep
) -> SessionOut:
    return await _session_out(db, await _load(db, access, session_id))


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _lock_key(session_id: uuid.UUID) -> str:
    return f"ai:lock:{session_id}"


def _cancel_key(session_id: uuid.UUID) -> str:
    return f"ai:cancel:{session_id}"


async def _limits(
    redis: RedisDep, settings: Settings, access: FormAccess, *, importing: bool
) -> None:
    await enforce(redis, settings, "ai_request", str(access.user.id))
    await enforce(redis, settings, "ai_request_org", str(access.form.org_id))
    if importing:
        await enforce(redis, settings, "ai_import", str(access.user.id))
    try:
        await ai_svc.check_budget(redis, settings, access.user.id, access.form.org_id)
    except BudgetExceeded:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "ai_budget_exceeded") from None


async def _start(
    db: DbDep,
    redis: RedisDep,
    settings: Settings,
    access: FormAccess,
    session: AiSession,
    *,
    importing: bool,
) -> tuple[WorkingCopy, int, dict[str, Any]]:
    """Take the session's lock and work out what the request starts from: the pending
    suggestion, or the draft as saved now."""
    if session.status == AiSessionStatus.PROPOSAL and session.working_schema is not None:
        assert session.base_revision is not None and session.base_schema is not None
        working = WorkingCopy(session.working_schema, flags=list(session.flags))
        base_revision, base_schema = session.base_revision, session.base_schema
    else:
        working = WorkingCopy(access.form.draft_schema)
        base_revision, base_schema = access.form.draft_revision, access.form.draft_schema
    working.importing = importing
    if len(compact(working.schema)) > settings.ai_max_form_chars:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "form_too_large")
    if not await redis.set(_lock_key(session.id), "1", nx=True, ex=settings.ai_turn_seconds + 60):
        raise HTTPException(status.HTTP_409_CONFLICT, "ai_busy")
    await redis.delete(_cancel_key(session.id))
    return working, base_revision, base_schema


def _stream(
    *,
    db: DbDep,
    redis: RedisDep,
    settings: Settings,
    access: FormAccess,
    session: AiSession,
    provider: AIProvider,
    working: WorkingCopy,
    base_revision: int,
    base_schema: dict[str, Any],
    request: ChatMessage,
    history: list[ChatMessage],
    audit_action: str,
    audit_meta: dict[str, Any],
) -> StreamingResponse:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    user_id, org_id = access.user.id, access.form.org_id
    mode: Any = (
        "import" if working.importing else ("create" if ai_svc.is_empty(working.schema) else "edit")
    )
    language = str(working.schema["settings"].get("language", "en"))

    async def emit(event: str, data: dict[str, Any]) -> None:
        await queue.put((event, data))

    async def should_cancel() -> bool:
        return bool(await redis.exists(_cancel_key(session.id)))

    async def check() -> None:
        await ai_svc.check_budget(redis, settings, user_id, org_id)

    async def charge(usage: Usage) -> None:
        await ai_svc.charge(redis, settings, user_id, org_id, usage)

    async def finish(outcome: TurnOutcome | None) -> list[bytes]:
        """Store the outcome; returns the closing events."""
        events: list[bytes] = []
        status_ = outcome.status if outcome else "cancelled"
        if outcome and outcome.status == "ok" and outcome.changed:
            session.status = AiSessionStatus.PROPOSAL
            session.base_revision = base_revision
            session.base_schema = base_schema
            session.working_schema = outcome.working.schema
            session.flags = outcome.working.flags
        session.mode = AiMode(mode)
        if outcome:
            session.tokens_in += outcome.usage.input_tokens
            session.tokens_out += outcome.usage.output_tokens
        text = outcome.text if outcome and outcome.status == "ok" else ""
        if outcome and outcome.status == "filled_in":
            text = outcome.working.filled_in or ""
        db.add(
            AiMessage(
                session_id=session.id,
                role="assistant",
                content={
                    "text": text,
                    "steps": outcome.steps if outcome else [],
                    "status": status_,
                    "error": outcome.error if outcome else None,
                    "changed": bool(outcome and outcome.changed),
                },
            )
        )
        await audit(
            db,
            audit_action,
            org_id=org_id,
            actor_id=user_id,
            target_type="form",
            target_id=access.form.id,
            meta={
                **audit_meta,
                "session": str(session.id),
                "outcome": status_,
                "error": outcome.error if outcome else None,
                "toolCalls": len(outcome.steps) if outcome else 0,
                "tokensIn": outcome.usage.input_tokens if outcome else 0,
                "tokensOut": outcome.usage.output_tokens if outcome else 0,
            },
        )
        await db.commit()
        if outcome is None:
            return events
        if outcome.status == "ok":
            prop = ai_svc.proposal(session)
            if prop is not None:
                events.append(_sse("proposal", prop))
        elif outcome.status == "error":
            events.append(_sse("error", {"code": outcome.error}))
        elif outcome.status == "cancelled":
            events.append(_sse("cancelled", {}))
        elif outcome.status == "filled_in":
            events.append(_sse("filled_in", {"note": outcome.working.filled_in}))
        events.append(
            _sse(
                "done",
                {"usage": {"in": outcome.usage.input_tokens, "out": outcome.usage.output_tokens}},
            )
        )
        return events

    async def body() -> AsyncIterator[bytes]:
        task = asyncio.create_task(
            run_request(
                provider,
                working=working,
                mode=mode,
                language=language,
                history=history,
                request=request,
                max_tool_calls=settings.ai_max_tool_calls,
                max_output_tokens=settings.ai_max_output_tokens,
                turn_seconds=settings.ai_turn_seconds,
                emit=emit,
                should_cancel=should_cancel,
                check_budget=check,
                charge=charge,
            )
        )
        finished = False
        try:
            yield b": started\n\n"
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    event, data = getter.result()
                    yield _sse(event, data)
                    continue
                getter.cancel()
                while not queue.empty():
                    event, data = queue.get_nowait()
                    yield _sse(event, data)
                break
            outcome = task.result()
            for chunk in await finish(outcome):
                yield chunk
            finished = True
        finally:
            with anyio.CancelScope(shield=True):
                if not task.done():
                    task.cancel()
                    with anyio.move_on_after(5):
                        await asyncio.gather(task, return_exceptions=True)
                if not finished:
                    # The person closed the connection (or stopped): nothing is kept.
                    try:
                        await db.rollback()
                        await finish(None)
                    except Exception:  # pragma: no cover - best effort on disconnect
                        log.exception("could not record a stopped AI request")
                await redis.delete(_lock_key(session.id))

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/forms/{form_id}/ai/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: MessageIn,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    access: FormEditor,
    provider: ProviderDep,
) -> StreamingResponse:
    session = await _load(db, access, session_id)
    await _limits(redis, settings, access, importing=False)
    history = await ai_svc.history(db, session.id)
    working, base_revision, base_schema = await _start(
        db, redis, settings, access, session, importing=False
    )
    db.add(AiMessage(session_id=session.id, role="user", content={"text": body.content}))
    await db.commit()
    return _stream(
        db=db,
        redis=redis,
        settings=settings,
        access=access,
        session=session,
        provider=provider,
        working=working,
        base_revision=base_revision,
        base_schema=base_schema,
        request=ChatMessage("user", text=body.content),
        history=history,
        audit_action="ai.request",
        audit_meta={"chars": len(body.content)},
    )


@router.post("/forms/{form_id}/ai/sessions/{session_id}/import")
async def import_document(
    session_id: uuid.UUID,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    access: FormEditor,
    provider: VisionDep,
    blank_confirmed: Annotated[bool, Query(alias="blankConfirmed")] = False,
    name: Annotated[str, Query(max_length=200)] = "",
) -> StreamingResponse:
    """Read a BLANK paper form (raw PDF/JPEG/PNG/WebP body). The person must confirm the
    document is blank; it is read in memory for this request and never stored."""
    if not blank_confirmed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "blank_confirmation_required")
    session = await _load(db, access, session_id)
    await _limits(redis, settings, access, importing=True)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    try:
        document = await asyncio.to_thread(prepare, bytes(data))
    except DocumentError as exc:
        code = (
            status.HTTP_413_CONTENT_TOO_LARGE
            if exc.code == "image_too_large"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(code, exc.code) from None
    del data
    history = await ai_svc.history(db, session.id)
    working, base_revision, base_schema = await _start(
        db, redis, settings, access, session, importing=True
    )
    attachment = {
        "name": name.strip()[:200],
        "pages": len(document.pages),
        "mime": document.mime,
    }
    db.add(
        AiMessage(
            session_id=session.id, role="user", content={"text": "", "attachment": attachment}
        )
    )
    await db.commit()
    pages = len(document.pages)
    return _stream(
        db=db,
        redis=redis,
        settings=settings,
        access=access,
        session=session,
        provider=provider,
        working=working,
        base_revision=base_revision,
        base_schema=base_schema,
        request=ChatMessage(
            "user",
            text=f"Recreate this blank paper form ({pages} page{'s' if pages != 1 else ''}).",
            images=document.pages,
        ),
        history=history,
        audit_action="ai.import",
        audit_meta={"blankConfirmed": True, "mime": document.mime, "pages": pages},
    )


@router.post("/forms/{form_id}/ai/sessions/{session_id}/cancel", status_code=204)
async def cancel(
    session_id: uuid.UUID,
    db: DbDep,
    redis: RedisDep,
    access: FormEditor,
    provider: ProviderDep,
) -> Response:
    session = await _load(db, access, session_id)
    await redis.set(_cancel_key(session.id), "1", ex=300)
    await audit(
        db,
        "ai.cancel",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=access.form.id,
        meta={"session": str(session.id)},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/forms/{form_id}/ai/sessions/{session_id}/apply", response_model=ApplyOut)
async def apply(
    session_id: uuid.UUID,
    body: ApplyIn,
    db: DbDep,
    redis: RedisDep,
    access: FormEditor,
    provider: ProviderDep,
) -> ApplyOut | JSONResponse:
    session = await _load(db, access, session_id)
    if await redis.exists(_lock_key(session.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "ai_busy")
    if session.status != AiSessionStatus.PROPOSAL or session.working_schema is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_proposal")
    form = access.form
    changed = ai_svc.changes(session.base_schema or {}, session.working_schema)
    rebased = form.draft_revision != session.base_revision
    try:
        await ai_svc.apply(db, session, form, access.user.id)
    except ai_svc.ProposalStale:
        await db.rollback()
        return JSONResponse({"detail": "proposal_stale"}, status_code=status.HTTP_409_CONFLICT)
    ai_svc.clear(session)
    db.add(
        AiMessage(
            session_id=session.id,
            role="status",
            content={"status": "applied", "revision": form.draft_revision},
        )
    )
    await audit(
        db,
        "ai.apply",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={
            "session": str(session.id),
            "revision": form.draft_revision,
            "changes": len(changed),
            "rebased": rebased,
            "clientRevision": body.base_revision,
        },
    )
    await db.commit()
    return ApplyOut(draft=await draft_out(db, form), session=await _session_out(db, session))


@router.post("/forms/{form_id}/ai/sessions/{session_id}/discard", response_model=SessionOut)
async def discard(
    session_id: uuid.UUID,
    db: DbDep,
    redis: RedisDep,
    access: FormEditor,
    provider: ProviderDep,
) -> SessionOut:
    session = await _load(db, access, session_id)
    if await redis.exists(_lock_key(session.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "ai_busy")
    if session.status == AiSessionStatus.PROPOSAL:
        ai_svc.clear(session)
        db.add(AiMessage(session_id=session.id, role="status", content={"status": "discarded"}))
        await audit(
            db,
            "ai.discard",
            org_id=access.form.org_id,
            actor_id=access.user.id,
            target_type="form",
            target_id=access.form.id,
            meta={"session": str(session.id)},
        )
        await db.commit()
    return await _session_out(db, session)
