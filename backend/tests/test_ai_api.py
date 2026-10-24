"""AI assistant API: sessions, streamed requests, suggestions, apply/undo, paper forms, limits,
permissions, audit and what is (never) sent to the provider."""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.fake import ScriptedProvider, turn
from app.ai.types import ChatMessage, TurnResult
from app.api.v1.ai import get_ai_provider, get_vision_provider
from app.config import Settings
from app.models import AuditLog, FormDraftHistory, FormPermission, FormRole, User
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client, field, publish


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        oidc_issuer=None,
        public_url="http://testserver",
        ai_provider="fake",
        ai_provider_label="Test AI",
    )


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider([])


@pytest.fixture
def app(app: Any, provider: ScriptedProvider) -> Any:
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_vision_provider] = lambda: provider
    return app


def events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.split("\n\n"):
        lines = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if not line.startswith(":") and ": " in line
        )
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


async def new_form(client: AsyncClient, me: dict[str, Any], language: str = "en") -> dict[str, Any]:
    res = await client.post(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Sign-up", "language": language}
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


async def open_session(client: AsyncClient, form_id: str, **body: Any) -> dict[str, Any]:
    res = await client.post(f"/api/v1/forms/{form_id}/ai/sessions", json=body)
    assert res.status_code == 200, res.text
    return dict(res.json())


async def ask(
    client: AsyncClient, form_id: str, sid: str, text: str
) -> list[tuple[str, dict[str, Any]]]:
    res = await client.post(
        f"/api/v1/forms/{form_id}/ai/sessions/{sid}/messages", json={"content": text}
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    return events(res.text)


DRAFT_STEPS = [
    turn(
        calls=[
            ("update_settings", {"title": "Volunteer sign-up"}),
            (
                "add_field",
                {
                    "parentId": "page_1",
                    "field": {"type": "short_text", "label": "Full name", "required": True},
                },
            ),
            ("add_field", {"parentId": "page_1", "field": {"type": "email", "label": "Email"}}),
        ]
    ),
    turn("I drafted a sign-up form with name and email."),
]


async def test_meta_reports_ai_features(client: AsyncClient) -> None:
    features = (await client.get("/api/v1/meta")).json()["features"]
    assert features["ai"] is True and features["aiVision"] is True
    assert features["aiProviderLabel"] == "Test AI"


async def test_describe_to_draft_apply_and_undo(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    form = await new_form(client, me)
    fid = form["id"]
    session = await open_session(client, fid)
    assert session["mode"] == "create" and session["messages"] == [] and session["proposal"] is None
    # Opening again resumes the same chat.
    assert (await open_session(client, fid))["id"] == session["id"]

    provider.steps.extend(DRAFT_STEPS)
    evs = await ask(client, fid, session["id"], "A volunteer sign-up form")
    names = [n for n, _ in evs]
    assert names == ["tool.applied"] * 3 + ["message.delta", "proposal", "done"]
    proposal = evs[-2][1]
    assert proposal["baseRevision"] == 1 and proposal["language"] == "en"
    assert [(c["change"], c["label"]) for c in proposal["changes"]] == [
        ("changed", ""),
        ("added", "Full name"),
        ("added", "Email"),
    ]

    # Nothing reached the draft yet.
    draft = (await client.get(f"/api/v1/forms/{fid}/draft")).json()
    assert draft["revision"] == 1 and draft["schema"]["pages"][0]["elements"] == []

    # The session remembers the transcript and the suggestion.
    got = (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{session['id']}")).json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["content"]["steps"][1]["label"] == "Full name"
    assert got["proposal"]["schema"]["settings"]["title"] == "Volunteer sign-up"

    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{session['id']}/apply", json={"baseRevision": 1}
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["draft"]["revision"] == 2 and out["draft"]["canUndo"]
    assert [e["id"] for e in out["draft"]["schema"]["pages"][0]["elements"]] == [
        "full_name",
        "email",
    ]
    assert out["session"]["proposal"] is None and out["session"]["status"] == "idle"
    history = (await db.execute(select(FormDraftHistory))).scalars().all()
    assert len(history) == 1 and history[0].actor_type == "ai"
    assert str(history[0].ai_session_id) == session["id"]

    # One undo reverts the whole suggestion.
    res = await client.post(f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": 2})
    assert res.status_code == 200
    assert res.json()["schema"]["pages"][0]["elements"] == []
    assert res.json()["schema"]["settings"]["title"] == "Sign-up"

    actions = [a for (a,) in (await db.execute(select(AuditLog.action))).all()]
    assert {"ai.session_create", "ai.request", "ai.apply"} <= set(actions)
    audit_row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.request"))
    assert audit_row is not None and audit_row.meta["toolCalls"] == 3
    assert "A volunteer" not in json.dumps(audit_row.meta)


async def test_follow_up_refines_the_pending_suggestion_and_discard(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    provider.steps.extend(DRAFT_STEPS)
    await ask(client, fid, sid, "A sign-up form")
    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "add_field",
                        {
                            "parentId": "page_1",
                            "index": 2,
                            "field": {"type": "phone", "label": "Phone"},
                        },
                    )
                ]
            ),
            turn("Added a phone question."),
        ]
    )
    evs = await ask(client, fid, sid, "Add a phone number")
    proposal = dict(evs)["proposal"]
    assert proposal["baseRevision"] == 1
    assert [c["label"] for c in proposal["changes"] if c["change"] == "added"] == [
        "Full name",
        "Email",
        "Phone",
    ]
    # The earlier request and reply are sent as context.
    sent = provider.calls[-1].messages
    assert [m.text for m in sent[:2]] == [
        "A sign-up form",
        "I drafted a sign-up form with name and email.",
    ]

    res = await client.post(f"/api/v1/forms/{fid}/ai/sessions/{sid}/discard")
    assert res.status_code == 200 and res.json()["proposal"] is None
    assert res.json()["messages"][-1]["content"] == {"status": "discarded"}
    draft = (await client.get(f"/api/v1/forms/{fid}/draft")).json()
    assert draft["revision"] == 1
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/apply", json={"baseRevision": 1}
    )
    assert res.status_code == 409 and res.json()["detail"] == "no_proposal"


async def test_apply_rebases_or_reports_a_clash(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    # Two pages so edits can happen in different places.
    res = await client.patch(
        f"/api/v1/forms/{fid}/draft",
        json={
            "baseRevision": 1,
            "patch": [
                {"op": "add", "path": "/pages/0/elements/0", "value": field("a")},
                {
                    "op": "add",
                    "path": "/pages/-",
                    "value": {"id": "page_2", "elements": [field("b")]},
                },
            ],
        },
    )
    assert res.status_code == 200
    sid = (await open_session(client, fid))["id"]
    provider.steps.extend(
        [turn(calls=[("update_field", {"id": "b", "changes": {"required": True}})]), turn("Done.")]
    )
    await ask(client, fid, sid, "Make b required")
    # Someone edits page 1 meanwhile: the suggestion (page 2) still applies.
    res = await client.patch(
        f"/api/v1/forms/{fid}/draft",
        json={
            "baseRevision": 2,
            "patch": [{"op": "replace", "path": "/pages/0/elements/0/label", "value": "A!"}],
        },
    )
    assert res.status_code == 200
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/apply", json={"baseRevision": 3}
    )
    assert res.status_code == 200, res.text
    schema = res.json()["draft"]["schema"]
    assert schema["pages"][0]["elements"][0]["label"] == "A!"
    assert schema["pages"][1]["elements"][0]["required"] is True

    # Now a suggestion and a human edit on the same question clash.
    provider.steps.extend(
        [turn(calls=[("update_field", {"id": "b", "changes": {"label": "Bee"}})]), turn("Done.")]
    )
    await ask(client, fid, sid, "Rename b")
    res = await client.patch(
        f"/api/v1/forms/{fid}/draft",
        json={
            "baseRevision": 4,
            "patch": [{"op": "replace", "path": "/pages/1/elements/0/label", "value": "Human"}],
        },
    )
    assert res.status_code == 200
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/apply", json={"baseRevision": 5}
    )
    assert res.status_code == 409 and res.json()["detail"] == "proposal_stale"
    draft = (await client.get(f"/api/v1/forms/{fid}/draft")).json()
    assert draft["revision"] == 5 and draft["schema"]["pages"][1]["elements"][0]["label"] == "Human"


async def test_errors_and_validation_repair_are_streamed(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    from app.ai.types import ProviderError

    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    provider.steps.extend(
        [
            turn(
                calls=[
                    ("add_field", {"parentId": "page_9", "field": {"type": "email", "label": "E"}})
                ]
            ),
            turn(
                calls=[
                    ("add_field", {"parentId": "page_1", "field": {"type": "email", "label": "E"}})
                ]
            ),
            turn("Added."),
        ]
    )
    evs = await ask(client, fid, sid, "Add email")
    assert [n for n, _ in evs][:2] == ["tool.error", "tool.applied"]
    assert "page_9" in evs[0][1]["error"]

    provider.steps.append(ProviderError("unavailable"))
    evs = await ask(client, fid, sid, "More")
    assert evs[-2] == ("error", {"code": "provider_unavailable"})
    # The earlier suggestion survives a failed follow-up.
    got = (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{sid}")).json()
    assert got["proposal"] is not None
    assert got["messages"][-1]["content"]["status"] == "error"


async def test_stop_request_discards_the_request(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    redis: FakeAsyncRedis,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]

    async def first(_: list[ChatMessage]) -> TurnResult:
        # The person presses Stop while the provider works.
        res = await client.post(f"/api/v1/forms/{fid}/ai/sessions/{sid}/cancel")
        assert res.status_code == 204
        return turn(
            calls=[("add_field", {"parentId": "page_1", "field": {"type": "email", "label": "E"}})]
        )

    provider.steps.extend([first, turn("never")])
    evs = await ask(client, fid, sid, "Add email")
    assert [n for n, _ in evs] == ["tool.applied", "cancelled", "done"]
    got = (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{sid}")).json()
    assert got["proposal"] is None and got["messages"][-1]["content"]["status"] == "cancelled"
    # The lock is released.
    assert not await redis.exists(f"ai:lock:{sid}")


async def test_busy_session_and_size_limits(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    redis: FakeAsyncRedis,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    await redis.set(f"ai:lock:{sid}", "1")
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "x"}
    )
    assert res.status_code == 409 and res.json()["detail"] == "ai_busy"
    await redis.delete(f"ai:lock:{sid}")
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "x" * 4001}
    )
    assert res.status_code == 422
    settings.ai_max_form_chars = 1000
    res = await client.patch(
        f"/api/v1/forms/{fid}/draft",
        json={
            "baseRevision": 1,
            "patch": [{"op": "add", "path": "/settings/description", "value": "d" * 1200}],
        },
    )
    assert res.status_code == 200
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "x"}
    )
    assert res.status_code == 413 and res.json()["detail"] == "form_too_large"


async def test_rate_limit_and_daily_allowance(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    settings.ai_daily_tokens_per_user = 150
    provider.steps.extend([turn("one", tokens=(100, 60))])
    evs = await ask(client, fid, sid, "hi")
    assert evs[-1][0] == "done"
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "again"}
    )
    assert res.status_code == 429 and res.json()["detail"] == "ai_budget_exceeded"
    settings.ai_daily_tokens_per_user = 0
    settings.rate_limits = ["ai_request=1/3600"]
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "again"}
    )
    assert res.status_code == 429 and res.json()["detail"] == "too_many_requests"


async def test_permissions_and_private_sessions(
    client: AsyncClient, app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    for email, role in (
        ("viewer@example.org", FormRole.VIEWER),
        ("editor@example.org", FormRole.EDITOR),
    ):
        user = User(email=email, display_name=email)
        db.add(user)
        await db.flush()
        db.add(FormPermission(form_id=uuid.UUID(fid), user_id=user.id, role=role))
    from app.models import OrgMembership, OrgRole

    for (uid,) in (
        await db.execute(select(User.id).where(User.email != "admin@example.org"))
    ).all():
        db.add(
            OrgMembership(org_id=uuid.UUID(me["orgs"][0]["id"]), user_id=uid, role=OrgRole.MEMBER)
        )
    await db.commit()
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        res = await viewer.post(f"/api/v1/forms/{fid}/ai/sessions", json={})
        assert res.status_code == 403
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        assert (await editor.post(f"/api/v1/forms/{fid}/ai/sessions", json={})).status_code == 200
        # Another person's chat is invisible.
        res = await editor.get(f"/api/v1/forms/{fid}/ai/sessions/{sid}")
        assert res.status_code == 404
        res = await editor.post(
            f"/api/v1/forms/{fid}/ai/sessions/{sid}/messages", json={"content": "x"}
        )
        assert res.status_code == 404


async def test_fresh_session_closes_the_old_one(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    old = (await open_session(client, fid))["id"]
    new = (await open_session(client, fid, fresh=True))["id"]
    assert new != old
    assert (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{old}")).status_code == 404


async def test_ai_off_hides_everything(
    client: AsyncClient, app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    app.dependency_overrides.pop(get_ai_provider)
    settings.ai_provider = "none"
    from app.api.v1 import ai as ai_api

    ai_api._providers.clear()
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    assert (await client.get("/api/v1/meta")).json()["features"]["ai"] is False
    res = await client.post(f"/api/v1/forms/{fid}/ai/sessions", json={})
    assert res.status_code == 404 and res.json()["detail"] == "ai_disabled"
    ai_api._providers.clear()


async def test_submission_data_is_never_sent(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(
        client, me, [field("name"), field("secret_note", sensitive=True)], title="Leak test"
    )
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"name": "Zubaida Unique-Respondent", "secret_note": "PIN 99887766"}),
    )
    assert res.status_code in (200, 201), res.text
    sid = (await open_session(client, pub.id))["id"]
    provider.steps.extend([turn(calls=[("get_form", {})]), turn("Read it.")])
    await ask(client, pub.id, sid, "What does this form ask?")
    sent = provider.sent_text()
    assert "secret_note" in sent  # the form itself is sent
    assert "Zubaida" not in sent and "99887766" not in sent


def png(width: int = 60, height: int = 40) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


async def test_paper_form_import_needs_a_blank_confirmation(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me, language="dv"))["id"]
    sid = (await open_session(client, fid))["id"]
    url = f"/api/v1/forms/{fid}/ai/sessions/{sid}/import"
    res = await client.post(url, content=png(), headers={"Content-Type": "image/png"})
    assert res.status_code == 422 and res.json()["detail"] == "blank_confirmation_required"
    res = await client.post(f"{url}?blankConfirmed=true", content=b"hello world")
    assert res.status_code == 422 and res.json()["detail"] == "unsupported_file"

    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "add_field",
                        {"parentId": "page_1", "field": {"type": "short_text", "label": "ނަން"}},
                    ),
                    (
                        "add_field",
                        {"parentId": "page_1", "field": {"type": "date", "label": "Date of birth"}},
                    ),
                    (
                        "flag_uncertain",
                        {"targetId": "date_of_birth", "note": "The box was hard to read"},
                    ),
                ]
            ),
            turn("I recreated the form."),
        ]
    )
    res = await client.post(
        f"{url}?blankConfirmed=true&name=leave.png",
        content=png(3000, 1000),
        headers={"Content-Type": "image/png"},
    )
    assert res.status_code == 200, res.text
    evs = dict(events(res.text))
    flags = evs["proposal"]["flags"]
    assert flags == [
        {"targetId": "date_of_birth", "note": "The box was hard to read", "label": "Date of birth"}
    ]
    request = provider.calls[0].messages[-1]
    assert len(request.images) == 1 and request.images[0].mime == "image/jpeg"
    width = Image.open(io.BytesIO(request.images[0].data)).width
    assert width == 2048
    assert "report_filled_in" in {t.name for t in provider.calls[0].tools}
    got = (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{sid}")).json()
    assert got["messages"][-2]["content"]["attachment"] == {
        "name": "leave.png",
        "pages": 1,
        "mime": "image/png",
    }
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.import"))
    assert row is not None and row.meta["blankConfirmed"] is True and row.meta["pages"] == 1


async def test_paper_form_import_pdf_and_filled_in(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    for _ in range(2):
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        pdf.cell(text="Name: ______")
    data = bytes(pdf.output())
    me = await admin_client(client, db, settings, queue)
    fid = (await new_form(client, me))["id"]
    sid = (await open_session(client, fid))["id"]
    provider.steps.append(turn(calls=[("report_filled_in", {"note": "Answers are written in"})]))
    res = await client.post(
        f"/api/v1/forms/{fid}/ai/sessions/{sid}/import?blankConfirmed=true",
        content=data,
        headers={"Content-Type": "application/pdf"},
    )
    assert res.status_code == 200
    evs = events(res.text)
    assert ("filled_in", {"note": "Answers are written in"}) in evs
    assert len(provider.calls[0].messages[-1].images) == 2
    got = (await client.get(f"/api/v1/forms/{fid}/ai/sessions/{sid}")).json()
    assert got["proposal"] is None
