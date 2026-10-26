"""Insights and "Ask your submissions" (DESIGN 15.4, 12.6, 17).

``GET /forms/{id}/insights`` summarises every question under the Submissions filters (viewers
and above, no AI involved).

``/forms/{id}/ask/...`` is the AI question box: one chat per person and form (mode ``ask``),
open to everyone who can see the submissions. A question streams Server-Sent Events:
``tool.applied`` / ``tool.error`` (one per query, with how it was counted), ``chart``,
``message.delta`` (the answer), then ``error`` or ``cancelled`` when it did not finish, and
``done``. Every endpoint answers 404 when no AI provider is configured.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import Field, StringConstraints
from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_svc
from app.ai.orchestrator import BudgetExceeded
from app.api.v1.ai import ProviderDep, _cancel_key, _lock_key, _sse
from app.api.v1.common import ApiModel
from app.api.v1.submissions import _list_filters
from app.auth.deps import DbDep, RedisDep, SettingsDep
from app.config import Settings
from app.insights import catalogue
from app.insights.ask import AskOutcome, Tools, run_ask, system_prompt, today
from app.insights.summary import summarise
from app.models import AiMessage, AiMode, AiSession, AiSessionStatus, Submission, SubmissionStatus
from app.permissions import FormAccess, FormViewer
from app.ratelimit import enforce
from app.services.users import audit
from app.submissions.query import ListFilters, apply_filters

log = logging.getLogger(__name__)

router = APIRouter(tags=["insights"])

MAX_QUESTION_CHARS = 2000
# A comment line on a quiet stream at least this often (seconds).
HEARTBEAT_SECONDS = 10.0


def read_allowed(access: FormAccess) -> bool:
    return bool((access.form.settings or {}).get("aiReadAnswers", False))


def _scope(
    form_id: uuid.UUID, filters: ListFilters, settings: Settings, cat: catalogue.Catalogue
) -> list[ColumnElement[bool]]:
    if filters == ListFilters():
        return []
    ids = apply_filters(
        select(Submission.id).where(Submission.form_id == form_id), filters, settings.tz, cat
    )
    return [Submission.id.in_(ids)]


@router.get("/forms/{form_id}/insights")
async def insights(
    db: DbDep,
    redis: RedisDep,
    access: FormViewer,
    settings: SettingsDep,
    status_: Annotated[SubmissionStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    filter_: Annotated[str | None, Query(alias="filter", max_length=4000)] = None,
    where: Annotated[str | None, Query(max_length=8000)] = None,
) -> dict[str, Any]:
    """Per-question summaries of the submissions matching the list's filters."""
    await enforce(redis, settings, "insights", str(access.user.id))
    filters = _list_filters(
        status_,
        q,
        from_,
        to,
        version,
        filter_,
        where,
    )
    cat = await catalogue.load(db, access.form)
    try:
        scope = _scope(access.form.id, filters, settings, cat)
        return await summarise(
            db, cat.for_version(filters.version), access.form.id, scope, settings.tz
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_filter") from exc


# -- Ask your submissions ---------------------------------------------------------------


class AskSessionIn(ApiModel):
    # Close the current chat and start a new one.
    fresh: bool = False


class AskMessageOut(ApiModel):
    id: uuid.UUID
    role: str
    content: dict[str, Any]
    created_at: datetime


class AskSessionOut(ApiModel):
    id: uuid.UUID | None = None
    messages: list[AskMessageOut] = Field(default_factory=list)
    # The form allows AI to read answers (Settings > AI).
    read_answers: bool = False
    provider_label: str = ""


class AskIn(ApiModel):
    content: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS),
    ]


async def _current(db: DbDep, access: FormAccess) -> AiSession | None:
    return await db.scalar(
        select(AiSession)
        .where(
            AiSession.form_id == access.form.id,
            AiSession.user_id == access.user.id,
            AiSession.mode == AiMode.ASK,
            AiSession.status != AiSessionStatus.CLOSED,
        )
        .order_by(AiSession.created_at.desc())
        .limit(1)
    )


async def _out(
    db: DbDep, access: FormAccess, settings: Settings, session: AiSession | None
) -> AskSessionOut:
    rows: list[AiMessage] = []
    if session is not None:
        rows = list(
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
    return AskSessionOut(
        id=session.id if session else None,
        messages=[AskMessageOut.model_validate(m) for m in rows],
        read_answers=read_allowed(access),
        provider_label=settings.ai_label,
    )


async def _load(db: DbDep, access: FormAccess, session_id: uuid.UUID) -> AiSession:
    session = await db.get(AiSession, session_id)
    if (
        session is None
        or session.form_id != access.form.id
        or session.user_id != access.user.id
        or session.mode != AiMode.ASK
        or session.status == AiSessionStatus.CLOSED
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ai_session_not_found")
    return session


@router.get("/forms/{form_id}/ask", response_model=AskSessionOut)
async def ask_state(
    db: DbDep, access: FormViewer, settings: SettingsDep, provider: ProviderDep
) -> AskSessionOut:
    """The person's current chat about this form's submissions (``id`` null: none yet)."""
    return await _out(db, access, settings, await _current(db, access))


@router.post("/forms/{form_id}/ask/sessions", response_model=AskSessionOut)
async def ask_open(
    body: AskSessionIn,
    db: DbDep,
    access: FormViewer,
    settings: SettingsDep,
    provider: ProviderDep,
) -> AskSessionOut:
    existing = await _current(db, access)
    if existing is not None and not body.fresh:
        return await _out(db, access, settings, existing)
    if existing is not None:
        await db.execute(
            update(AiSession)
            .where(
                AiSession.form_id == access.form.id,
                AiSession.user_id == access.user.id,
                AiSession.mode == AiMode.ASK,
                AiSession.status != AiSessionStatus.CLOSED,
            )
            .values(status=AiSessionStatus.CLOSED)
        )
    session = AiSession(
        org_id=access.form.org_id,
        form_id=access.form.id,
        user_id=access.user.id,
        provider=provider.name,
        model=provider.model,
        mode=AiMode.ASK,
    )
    db.add(session)
    await db.flush()
    await audit(
        db,
        "ai.ask_session_create",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=access.form.id,
        meta={"session": str(session.id), "provider": provider.name, "model": provider.model},
    )
    await db.commit()
    return await _out(db, access, settings, session)


@router.post("/forms/{form_id}/ask/sessions/{session_id}/messages")
async def ask_message(
    session_id: uuid.UUID,
    body: AskIn,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    access: FormViewer,
    provider: ProviderDep,
) -> StreamingResponse:
    session = await _load(db, access, session_id)
    await enforce(redis, settings, "ai_request", str(access.user.id))
    await enforce(redis, settings, "ai_request_org", str(access.form.org_id))
    # Plain values only from here on: the stream outlives this request's session, and an
    # expired ORM attribute would need IO to reload (MissingGreenlet in the generator).
    sid, user_id, org_id = session.id, access.user.id, access.form.org_id
    form_id, form_title = access.form.id, access.form.title
    question = body.content
    try:
        await ai_svc.check_budget(redis, settings, user_id, org_id)
    except BudgetExceeded:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "ai_budget_exceeded") from None
    if not await redis.set(_lock_key(sid), "1", nx=True, ex=settings.ai_turn_seconds + 60):
        raise HTTPException(status.HTTP_409_CONFLICT, "ai_busy")
    await redis.delete(_cancel_key(sid))
    try:
        cat = await catalogue.load(db, access.form)
        allowed = read_allowed(access)
        total = int(
            await db.scalar(
                select(func.count()).where(
                    Submission.form_id == form_id, Submission.deleted_at.is_(None)
                )
            )
            or 0
        )
        system = system_prompt(
            cat,
            title=form_title,
            total=total,
            read_allowed=allowed,
            provider_label=settings.ai_label,
            today=today(settings.tz),
        )
        history = await ai_svc.history(db, sid)
        db.add(AiMessage(session_id=sid, role="user", content={"text": question}))
        await db.commit()
    except BaseException:
        await redis.delete(_lock_key(sid))
        raise
    engine = db.bind
    max_tool_calls = min(settings.ai_max_tool_calls, 20)

    async def finish(work: AsyncSession, outcome: AskOutcome | None) -> list[bytes]:
        """Store the answer (or that it stopped) and audit it; returns the closing events."""
        status_ = outcome.status if outcome else "cancelled"
        if outcome:
            await work.execute(
                update(AiSession)
                .where(AiSession.id == sid)
                .values(
                    tokens_in=AiSession.tokens_in + outcome.usage.input_tokens,
                    tokens_out=AiSession.tokens_out + outcome.usage.output_tokens,
                )
            )
        ok = outcome is not None and outcome.status == "ok"
        work.add(
            AiMessage(
                session_id=sid,
                role="assistant",
                content={
                    "text": outcome.text if outcome and ok else "",
                    "steps": outcome.steps if outcome else [],
                    "charts": outcome.charts if outcome else [],
                    "link": outcome.link if outcome and ok else None,
                    "status": status_,
                    "error": outcome.error if outcome else None,
                },
            )
        )
        meta = {
            "session": str(sid),
            "chars": len(question),
            "outcome": status_,
            "error": outcome.error if outcome else None,
            "toolCalls": len(outcome.steps) if outcome else 0,
            "tokensIn": outcome.usage.input_tokens if outcome else 0,
            "tokensOut": outcome.usage.output_tokens if outcome else 0,
            "readAnswers": allowed,
        }
        await audit(
            work,
            "ai.ask",
            org_id=org_id,
            actor_id=user_id,
            target_type="form",
            target_id=form_id,
            meta=meta,
        )
        for fields, count in outcome.reads if outcome else []:
            # Which questions' answers went to the provider, and for how many submissions.
            await audit(
                work,
                "ai.read_answers",
                org_id=org_id,
                actor_id=user_id,
                target_type="form",
                target_id=form_id,
                meta={"session": str(sid), "fields": fields, "count": count},
            )
        await work.commit()
        if outcome is None:
            return []
        events: list[bytes] = []
        if outcome.status == "error":
            events.append(_sse("error", {"code": outcome.error}))
        elif outcome.status == "cancelled":
            events.append(_sse("cancelled", {}))
        events.append(
            _sse(
                "done",
                {"usage": {"in": outcome.usage.input_tokens, "out": outcome.usage.output_tokens}},
            )
        )
        return events

    async def stream() -> AsyncIterator[bytes]:
        # The answer runs in its own task with its own database session; nothing here
        # touches the request's session, which may already be closed.
        work = AsyncSession(engine, expire_on_commit=False)
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def emit(event: str, data: dict[str, Any]) -> None:
            queue.put_nowait((event, data))

        async def should_cancel() -> bool:
            return bool(await redis.exists(_cancel_key(sid)))

        async def check() -> None:
            await ai_svc.check_budget(redis, settings, user_id, org_id)

        async def charge(usage: Any) -> None:
            await ai_svc.charge(redis, settings, user_id, org_id, usage)

        tools = Tools(work, cat, form_id, tz=settings.tz, read_allowed=allowed, total=total)
        task = asyncio.create_task(
            run_ask(
                provider,
                tools,
                system=system,
                history=history,
                question=question,
                max_tool_calls=max_tool_calls,
                max_output_tokens=settings.ai_max_output_tokens,
                turn_seconds=settings.ai_turn_seconds,
                emit=emit,
                should_cancel=should_cancel,
                check_budget=check,
                charge=charge,
            )
        )
        getter: asyncio.Future[tuple[str, dict[str, Any]]] | None = None
        finished = False
        try:
            yield b": started\n\n"
            while True:
                if getter is None:
                    getter = asyncio.ensure_future(queue.get())
                waiting: set[asyncio.Future[Any]] = {getter, task}
                done, _ = await asyncio.wait(
                    waiting, timeout=HEARTBEAT_SECONDS, return_when=asyncio.FIRST_COMPLETED
                )
                if getter in done:
                    event, data = getter.result()
                    getter = None
                    yield _sse(event, data)
                    continue
                if not done:
                    # A comment keeps proxies from closing a quiet connection while it counts.
                    yield b": keep-alive\n\n"
                    continue
                break
            while not queue.empty():
                event, data = queue.get_nowait()
                yield _sse(event, data)
            try:
                outcome = task.result()
            except Exception:
                log.exception("ask: the answer failed")
                await work.rollback()
                outcome = AskOutcome(status="error", error="internal")
            for chunk in await finish(work, outcome):
                yield chunk
            finished = True
        finally:
            with anyio.CancelScope(shield=True):
                if getter is not None and not getter.done():
                    getter.cancel()
                    await asyncio.gather(getter, return_exceptions=True)
                if not task.done():
                    task.cancel()
                    with anyio.move_on_after(5):
                        await asyncio.gather(task, return_exceptions=True)
                if not finished:
                    # The person left or the connection dropped: record that it stopped.
                    try:
                        await work.rollback()
                        await finish(work, None)
                    except Exception:  # pragma: no cover - best effort on disconnect
                        log.exception("could not record a stopped question")
                await work.close()
                await redis.delete(_lock_key(sid))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/forms/{form_id}/ask/sessions/{session_id}/cancel", status_code=204)
async def ask_cancel(
    session_id: uuid.UUID,
    db: DbDep,
    redis: RedisDep,
    access: FormViewer,
    provider: ProviderDep,
) -> Response:
    session = await _load(db, access, session_id)
    await redis.set(_cancel_key(session.id), "1", ex=300)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
