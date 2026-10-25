"""The forms list: owner, activity counts and permissions (docs/ux/FORMS-LIST-SCREENS.md)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ApprovalState, FormRecord, OrgRole, Submission, User
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import field, publish


async def _member(db: AsyncSession, settings: Settings, email: str, name: str) -> User:
    org = await ensure_default_org(db, settings)
    user = User(email=email, display_name=name)
    db.add(user)
    await db.flush()
    await set_membership(db, org, user, OrgRole.CREATOR)
    await db.commit()
    return user


def _by_title(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["title"]: r for r in rows}


async def test_counts_owner_and_activity(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "admin@example.org", "Root Admin")
    await _member(db, settings, "aminath@example.org", "Aminath Ali")
    me = await login(client, queue, "admin@example.org")
    org_id = me["orgs"][0]["id"]

    pub = await publish(client, me, [field("name")], title="Youth grant")
    for i in range(5):
        res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": f"P{i}"}))
        assert res.status_code == 201, res.text
    subs = (
        (await db.execute(Submission.__table__.select().order_by(Submission.seq))).mappings().all()
    )
    old, deleted, pending, reviewed = (s["id"] for s in subs[:4])
    long_ago = datetime.now(UTC) - timedelta(days=30)
    await db.execute(update(Submission).where(Submission.id == old).values(submitted_at=long_ago))
    await db.execute(
        update(Submission).where(Submission.id == deleted).values(deleted_at=datetime.now(UTC))
    )
    await db.execute(
        update(Submission)
        .where(Submission.id == pending)
        .values(approval_state=ApprovalState.PENDING, status="in_review")
    )
    await db.execute(update(Submission).where(Submission.id == reviewed).values(status="approved"))
    approvals = {
        "enabled": True,
        "steps": [{"name": "Director", "source": "fixed", "email": "director@example.org"}],
    }
    await db.execute(
        update(FormRecord)
        .where(FormRecord.id == uuid.UUID(pub.id))
        .values(settings={"approvals": approvals, "importedFrom": "jotform"})
    )
    await db.commit()

    # An unpublished edit after publishing.
    draft = (await client.get(f"/api/v1/forms/{pub.id}/draft")).json()
    res = await client.patch(
        f"/api/v1/forms/{pub.id}/draft",
        json={
            "baseRevision": draft["revision"],
            "patch": [{"op": "add", "path": "/pages/0/elements/1", "value": field("extra")}],
        },
    )
    assert res.status_code == 200, res.text

    # A Dhivehi draft owned by someone else, shared with the admin's org as admin (implicit).
    async with make_client(app) as other:
        await login(other, queue, "aminath@example.org")
        res = await other.post(
            f"/api/v1/orgs/{org_id}/forms", json={"title": "ފޯމު", "language": "dv"}
        )
        assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/orgs/{org_id}/forms")
    assert res.status_code == 200, res.text
    rows = res.json()
    # Newest edit first.
    assert [r["title"] for r in rows] == ["ފޯމު", "Youth grant"]
    grant, dv = _by_title(rows)["Youth grant"], _by_title(rows)["ފޯމު"]

    assert grant["submissionCount"] == 4  # the deleted one is left out
    assert grant["newCount"] == 2  # 4 minus in review minus approved
    assert grant["recentCount"] == 3  # minus the one from 30 days ago
    assert grant["approvalsOn"] is True
    assert grant["pendingApprovalCount"] == 1
    assert grant["lastSubmissionAt"] is not None
    assert grant["hasUnpublishedChanges"] is True
    assert grant["currentVersion"] == 1
    assert grant["importedFrom"] == "jotform"
    assert grant["language"] == "en"
    assert grant["owner"]["email"] == "admin@example.org"
    assert grant["owner"]["name"] == "Root Admin"
    assert grant["ownerCount"] == 1
    assert grant["ownedByMe"] is True
    assert grant["role"] == "owner"
    assert grant["lastEditedBy"]["email"] == "admin@example.org"

    assert dv["language"] == "dv"
    assert dv["status"] == "draft"
    assert dv["currentVersion"] is None
    assert dv["hasUnpublishedChanges"] is False
    assert dv["submissionCount"] == 0 and dv["recentCount"] == 0
    assert dv["lastSubmissionAt"] is None
    assert dv["approvalsOn"] is False
    assert dv["importedFrom"] is None
    assert dv["owner"]["name"] == "Aminath Ali"
    # Admins act as owner of every form, but don't own it explicitly.
    assert dv["role"] == "owner" and dv["ownedByMe"] is False
    # Never edited: the creation counts as the last edit.
    assert dv["lastEditedBy"]["email"] == "aminath@example.org"
    assert dv["lastEditedAt"] == dv["createdAt"]

    # Publishing the edit clears the unpublished flag.
    assert (await client.post(f"/api/v1/forms/{pub.id}/publish")).status_code == 200
    grant = _by_title((await client.get(f"/api/v1/orgs/{org_id}/forms")).json())["Youth grant"]
    assert grant["hasUnpublishedChanges"] is False
    assert grant["currentVersion"] == 2


async def test_members_see_only_their_forms_and_owner_choice(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "admin@example.org", "Root Admin")
    await _member(db, settings, "owner@example.org", "Aminath Ali")
    await _member(db, settings, "viewer@example.org", "Ibrahim Naseer")
    await _member(db, settings, "zz-coowner@example.org", "Co Owner")

    me = await login(client, queue, "owner@example.org")
    org_id = me["orgs"][0]["id"]
    shared = (await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "Shared"})).json()
    await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "Private"})
    grants = [
        {"email": "zz-coowner@example.org", "role": "owner"},
        {"email": "owner@example.org", "role": "owner"},
        {"email": "viewer@example.org", "role": "viewer"},
    ]
    res = await client.put(f"/api/v1/forms/{shared['id']}/permissions", json={"grants": grants})
    assert res.status_code == 200, res.text

    rows = _by_title((await client.get(f"/api/v1/orgs/{org_id}/forms")).json())
    assert set(rows) == {"Shared", "Private"}
    # The creator is shown while they are an owner, even with other owners added later.
    assert rows["Shared"]["owner"]["email"] == "owner@example.org"
    assert rows["Shared"]["ownerCount"] == 2
    assert rows["Shared"]["ownedByMe"] is True

    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        res = await viewer.get(f"/api/v1/orgs/{org_id}/forms")
        assert res.status_code == 200
        only = res.json()
        assert [r["title"] for r in only] == ["Shared"]
        assert only[0]["role"] == "viewer"
        assert only[0]["ownedByMe"] is False
        assert only[0]["owner"]["name"] == "Aminath Ali"

    # Once the creator is no longer an owner, the earliest remaining owner is shown.
    res = await client.put(
        f"/api/v1/forms/{shared['id']}/permissions",
        json={
            "grants": [
                {"email": "zz-coowner@example.org", "role": "owner"},
                {"email": "owner@example.org", "role": "editor"},
            ]
        },
    )
    assert res.status_code == 200, res.text
    row = _by_title((await client.get(f"/api/v1/orgs/{org_id}/forms")).json())["Shared"]
    assert row["owner"]["email"] == "zz-coowner@example.org"
    assert row["ownerCount"] == 1
    assert row["ownedByMe"] is False
    assert row["role"] == "editor"


async def test_list_query_count_does_not_grow_with_forms(
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    me = await login(client, queue, "admin@example.org")
    org_id = me["orgs"][0]["id"]
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    async def listed() -> int:
        statements.clear()
        event.listen(db_engine.sync_engine, "before_cursor_execute", count)
        try:
            assert (await client.get(f"/api/v1/orgs/{org_id}/forms")).status_code == 200
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", count)
        return len(statements)

    await publish(client, me, [field("a")], title="One")
    one = await listed()
    for i in range(4):
        await publish(client, me, [field("a")], title=f"More {i}")
    assert await listed() == one
