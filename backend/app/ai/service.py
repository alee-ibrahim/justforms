"""Suggestions: what changed, language checks, applying with a rebase, and token allowances."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonpatch
import jsonpointer
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import element_label, iter_elements
from app.ai.types import ChatMessage
from app.models import ActorType, AiMessage, AiMode, AiSession, AiSessionStatus, FormRecord
from app.services import forms as form_svc

HISTORY_TURNS = 10
THAANA = re.compile(r"[ހ-޿]")
LATIN = re.compile(r"[A-Za-z]")


class ProposalStale(Exception):
    """The draft changed in the same places since the suggestion was made."""


# --------------------------------------------------------------------------------------
# What changed
# --------------------------------------------------------------------------------------


def _flat(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """id -> {el, page, parent, prev} where prev is the id of the previous sibling."""
    out: dict[str, dict[str, Any]] = {}
    for page in schema["pages"]:
        for loc in iter_elements(copy.deepcopy(page.get("elements") or []), 0, page["id"]):
            prev = loc.siblings[loc.index - 1]["id"] if loc.index > 0 else None
            out[loc.element["id"]] = {
                "el": loc.element,
                "page": page["id"],
                "parent": loc.parent_id,
                "siblings": [s["id"] for s in loc.siblings],
            }
            out[loc.element["id"]]["prev"] = prev
    return out


def _shallow(el: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in el.items() if k != "elements"}


def _order_changed(old: list[str], new: list[str]) -> set[str]:
    """Ids whose order among the siblings both lists share has changed."""
    common = set(old) & set(new)
    a = [i for i in old if i in common]
    b = [i for i in new if i in common]
    if a == b:
        return set()
    # Longest common subsequence keeps its place; everything else counts as moved.
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    keep: set[str] = set()
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            keep.add(a[i])
            i, j = i + 1, j + 1
        elif dp[i + 1][j] > dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return common - keep


def changes(base: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Plain list of changes for the suggestion card, in the new form's order."""
    out: list[dict[str, Any]] = []
    if base.get("settings") != new.get("settings"):
        out.append(
            {"kind": "settings", "id": None, "label": "", "change": "changed", "pageId": None}
        )
    old_pages = {p["id"]: (i, p) for i, p in enumerate(base["pages"])}
    moved_pages = _order_changed([p["id"] for p in base["pages"]], [p["id"] for p in new["pages"]])
    old_flat, new_flat = _flat(base), _flat(new)
    moved: set[str] = set()
    for info in new_flat.values():
        if info["el"]["id"] in old_flat:
            prev = old_flat[info["el"]["id"]]
            if (prev["page"], prev["parent"]) != (info["page"], info["parent"]):
                moved.add(info["el"]["id"])
    groups: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for eid, info in new_flat.items():
        if eid in old_flat and eid not in moved:
            prev = old_flat[eid]
            groups.setdefault((info["page"], info["parent"]), (prev["siblings"], info["siblings"]))
    for old_ids, new_ids in groups.values():
        moved |= _order_changed(old_ids, new_ids)

    for i, page in enumerate(new["pages"]):
        title = page.get("title") or f"Page {i + 1}"
        if page["id"] not in old_pages:
            out.append(
                {
                    "kind": "page",
                    "id": page["id"],
                    "label": title,
                    "change": "added",
                    "pageId": page["id"],
                }
            )
        elif _shallow(old_pages[page["id"]][1]) != _shallow(page):
            out.append(
                {
                    "kind": "page",
                    "id": page["id"],
                    "label": title,
                    "change": "changed",
                    "pageId": page["id"],
                }
            )
        elif page["id"] in moved_pages:
            out.append(
                {
                    "kind": "page",
                    "id": page["id"],
                    "label": title,
                    "change": "moved",
                    "pageId": page["id"],
                }
            )
        for loc in iter_elements(copy.deepcopy(page.get("elements") or []), i, page["id"]):
            eid = loc.element["id"]
            entry = {
                "kind": "element",
                "id": eid,
                "label": element_label(loc.element),
                "pageId": page["id"],
            }
            if eid not in old_flat:
                out.append({**entry, "change": "added"})
            elif _shallow(old_flat[eid]["el"]) != _shallow(loc.element):
                out.append({**entry, "change": "changed"})
            elif eid in moved:
                out.append({**entry, "change": "moved"})
    for eid, info in old_flat.items():
        if eid not in new_flat:
            out.append(
                {
                    "kind": "element",
                    "id": eid,
                    "label": element_label(info["el"]),
                    "change": "removed",
                    "pageId": None,
                }
            )
    for page_id, (i, page) in old_pages.items():
        if page_id not in {p["id"] for p in new["pages"]}:
            out.append(
                {
                    "kind": "page",
                    "id": page_id,
                    "label": page.get("title") or f"Page {i + 1}",
                    "change": "removed",
                    "pageId": None,
                }
            )
    return out


def _texts(el: dict[str, Any]) -> list[str]:
    texts = [
        str(el[k]) for k in ("label", "title", "text", "description", "placeholder") if el.get(k)
    ]
    texts += [str(o.get("label", "")) for o in el.get("options") or [] if isinstance(o, dict)]
    return texts


def language_flags(
    new: dict[str, Any], changed: list[dict[str, Any]], language: str
) -> list[dict[str, Any]]:
    """Added or changed questions whose text is in the wrong script for the form."""
    touched = {
        c["id"] for c in changed if c["kind"] == "element" and c["change"] in ("added", "changed")
    }
    flags: list[dict[str, Any]] = []
    for eid, info in _flat(new).items():
        if eid not in touched:
            continue
        texts = _texts(info["el"])
        if language == "dv":
            wrong = any(LATIN.search(t) and not THAANA.search(t) for t in texts)
            note = "Not written in Thaana script"
        else:
            wrong = any(THAANA.search(t) for t in texts)
            note = "Written in Thaana, but the form is in English"
        if wrong:
            flags.append({"targetId": eid, "note": note, "source": "language"})
    return flags


def proposal(session: AiSession) -> dict[str, Any] | None:
    if session.status != AiSessionStatus.PROPOSAL or session.working_schema is None:
        return None
    base = session.base_schema or session.working_schema
    new = session.working_schema
    language = str(new.get("settings", {}).get("language", "en"))
    changed = changes(base, new)
    known = (
        {c["id"] for c in changed}
        | {info["el"]["id"] for info in _flat(new).values()}
        | {p["id"] for p in new["pages"]}
    )
    flags = [f for f in session.flags if f.get("targetId") in known]
    flagged = {f["targetId"] for f in flags}
    flags += [f for f in language_flags(new, changed, language) if f["targetId"] not in flagged]
    labels = {info["el"]["id"]: element_label(info["el"]) for info in _flat(new).values()}
    for f in flags:
        f["label"] = labels.get(f["targetId"], f["targetId"])
    return {
        "baseRevision": session.base_revision,
        "schema": new,
        "changes": changed,
        "flags": flags,
        "language": language,
    }


# --------------------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------------------


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _resolve(doc: Any, path: str) -> tuple[bool, Any]:
    try:
        return True, jsonpointer.resolve_pointer(doc, path)
    except jsonpointer.JsonPointerException:
        return False, None


def guarded_patch(base: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """The patch base -> new, with ``test`` operations before each change checking that the
    draft still has, in the places the change touches, what the suggestion was made from.
    Lists are checked whole (adding or removing an item shifts the others), so a change on
    the same page as someone else's edit counts as a clash."""
    ops = jsonpatch.make_patch(base, new).patch
    sim = copy.deepcopy(base)
    out: list[dict[str, Any]] = []
    for op in ops:
        paths: list[str] = []
        kind = op["op"]
        if kind in ("replace", "remove"):
            paths.append(op["path"])
        if kind in ("add", "remove", "move"):
            paths.append(_parent(op["path"]))
        if kind in ("move", "copy"):
            paths += [op["from"], _parent(op["from"])]
        seen: set[str] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            found, value = _resolve(sim, path)
            if not found:
                continue
            if path != op.get("path") and path != op.get("from") and not isinstance(value, list):
                continue  # parents are only guarded when they are lists
            out.append({"op": "test", "path": path, "value": copy.deepcopy(value)})
        out.append(op)
        sim = jsonpatch.apply_patch(sim, [op], in_place=False)
    return out


async def apply(
    db: AsyncSession, session: AiSession, form: FormRecord, actor_id: uuid.UUID
) -> FormRecord:
    """Write the suggestion to the draft as one history entry (one Undo reverts it).

    Raises ProposalStale when the draft moved on and the suggestion no longer fits.
    """
    assert session.working_schema is not None and session.base_schema is not None
    if form.draft_revision == session.base_revision:
        patch = jsonpatch.make_patch(form.draft_schema, session.working_schema).patch
    else:
        patch = guarded_patch(session.base_schema, session.working_schema)
    try:
        await form_svc.apply_draft_patch(
            db,
            form,
            form.draft_revision,
            patch,
            actor_id,
            actor_type=ActorType.AI,
            ai_session_id=session.id,
        )
    except (form_svc.DraftPatchError, ValueError) as exc:
        raise ProposalStale from exc
    return form


def clear(session: AiSession, status: AiSessionStatus = AiSessionStatus.IDLE) -> None:
    session.status = status
    session.working_schema = None
    session.base_schema = None
    session.base_revision = None
    session.flags = []


# --------------------------------------------------------------------------------------
# Transcript and allowances
# --------------------------------------------------------------------------------------


async def history(db: AsyncSession, session_id: uuid.UUID) -> list[ChatMessage]:
    """Earlier requests and replies (text only) for context; tool details are left out."""
    rows = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.session_id == session_id)
                .order_by(AiMessage.created_at.desc(), AiMessage.id.desc())
                .limit(HISTORY_TURNS * 2)
            )
        )
        .scalars()
        .all()
    )
    out: list[ChatMessage] = []
    for row in reversed(rows):
        text = str(row.content.get("text") or "")
        if row.role == "user":
            if row.content.get("attachment"):
                text = f"[Uploaded a blank paper form: {row.content['attachment'].get('name', '')}]"
            if text:
                out.append(ChatMessage("user", text=text))
        elif row.role == "assistant" and text:
            out.append(ChatMessage("assistant", text=text))
    # Providers want the conversation to start with the person.
    while out and out[0].role != "user":
        out.pop(0)
    return out


def is_empty(schema: dict[str, Any]) -> bool:
    return not any(page.get("elements") for page in schema["pages"])


RETENTION_DAYS = 90
# What an answer becomes when submissions it may have read are erased.
REMOVED: dict[str, Any] = {
    "text": "",
    "steps": [],
    "charts": [],
    "link": None,
    "status": "removed",
    "error": None,
}


async def purge_old(db: AsyncSession, now: datetime | None = None) -> int:
    """Erase transcripts older than 90 days, and chats nobody touched since (DESIGN 6). Ask
    transcripts of a form with a retention period go when its submissions would: after
    min(90 days, retentionDays)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    result = await db.execute(delete(AiMessage).where(AiMessage.created_at < cutoff))
    count = int(getattr(result, "rowcount", 0) or 0)
    await db.execute(delete(AiSession).where(AiSession.updated_at < cutoff))
    forms = (
        await db.execute(
            select(FormRecord.id, FormRecord.settings).where(
                FormRecord.settings.has_key("retentionDays")
            )
        )
    ).all()
    for form_id, settings in forms:
        days = (settings or {}).get("retentionDays")
        if not isinstance(days, int) or days < 1 or days >= RETENTION_DAYS:
            continue
        sessions = select(AiSession.id).where(
            AiSession.form_id == form_id, AiSession.mode == AiMode.ASK
        )
        result = await db.execute(
            delete(AiMessage).where(
                AiMessage.session_id.in_(sessions),
                AiMessage.created_at < now - timedelta(days=days),
            )
        )
        count += int(getattr(result, "rowcount", 0) or 0)
    await db.commit()
    return count


async def mask_ask_answers(db: AsyncSession, form_id: uuid.UUID, since: datetime) -> None:
    """A submission was erased: Ask answers about the form written since it arrived may
    quote it (reply text, group labels), so they are replaced by "removed". The questions
    stay. The caller commits."""
    sessions = select(AiSession.id).where(
        AiSession.form_id == form_id, AiSession.mode == AiMode.ASK
    )
    await db.execute(
        update(AiMessage)
        .where(
            AiMessage.session_id.in_(sessions),
            AiMessage.role == "assistant",
            AiMessage.created_at >= since,
            AiMessage.content["status"].astext != "removed",
        )
        .values(content=REMOVED)
    )
