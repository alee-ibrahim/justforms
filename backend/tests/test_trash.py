"""The trash: deleted submissions and forms can be restored for JUSTFORMS_TRASH_DAYS, then
the nightly job erases them with their files (DESIGN 14.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrity import verify_submission
from app.models import (
    AuditLog,
    FormPermission,
    FormRecord,
    FormRole,
    OrgMembership,
    OrgRole,
    Submission,
    SubmissionEvent,
    User,
)
from app.storage import Storage
from app.submissions import retention
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import Published, admin_client, field, publish


async def _seed(
    client: AsyncClient, me: dict[str, Any], n: int = 3, title: str = "Intake"
) -> Published:
    pub = await publish(client, me, [field("name", label="Name")], title=title)
    for i in range(n):
        res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": f"P{i}"}))
        assert res.status_code == 201, res.text
    return pub


async def _ids(client: AsyncClient, pub: Published) -> list[str]:
    res = await client.get(f"/api/v1/forms/{pub.id}/submissions")
    return [i["id"] for i in res.json()["items"]]


async def _stats(client: AsyncClient, pub: Published) -> dict[str, int]:
    return dict((await client.get(f"/api/v1/forms/{pub.id}/submissions/stats")).json())


async def _member(db: AsyncSession, org_id: str, email: str, role: OrgRole) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    db.add(OrgMembership(org_id=uuid.UUID(org_id), user_id=user.id, role=role))
    await db.commit()
    return user


async def test_delete_trash_restore_submissions(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me)
    ids = await _ids(client, pub)
    bulk = f"/api/v1/forms/{pub.id}/submissions/bulk"

    res = await client.post(bulk, json={"ids": ids[:2], "action": "delete"})
    assert res.json() == {"changed": 2}
    stats = await _stats(client, pub)
    assert stats["all"] == 1 and stats["deleted"] == 2

    # The trash lists them with who deleted them and when they go for good.
    res = await client.get(f"/api/v1/forms/{pub.id}/submissions/deleted")
    assert res.status_code == 200
    page = res.json()
    assert page["total"] == 2
    item = page["items"][0]
    assert item["deletedBy"]["email"] == "admin@example.org"
    deleted_at = datetime.fromisoformat(item["deletedAt"])
    purge = datetime.fromisoformat(item["purgeAt"])
    assert abs((purge - deleted_at) - timedelta(days=30)) < timedelta(seconds=1)

    # Restore one on its own (the toast's Undo), the other in bulk.
    seq = next(i["seq"] for i in page["items"] if i["id"] == ids[0])
    assert (await client.post(f"/api/v1/submissions/{ids[0]}/restore")).status_code == 204
    assert (await client.post(f"/api/v1/submissions/{ids[0]}/restore")).status_code == 404
    res = await client.post(bulk, json={"ids": ids, "action": "restore"})
    assert res.json() == {"changed": 1}  # only the one still in the trash
    stats = await _stats(client, pub)
    assert stats["all"] == 3 and stats["deleted"] == 0

    # Same reference number; the activity log records both moves and still verifies.
    detail = (await client.get(f"/api/v1/submissions/{ids[0]}")).json()
    assert detail["seq"] == seq
    types = [e["type"] for e in detail["events"]]
    assert types[:2] == ["restored", "deleted"]
    sub = await db.get(Submission, uuid.UUID(ids[0]))
    assert sub is not None
    await db.refresh(sub)
    assert sub.deleted_at is None and sub.deleted_by is None
    assert (await verify_submission(db, sub)).ok
    actions = (
        await db.scalars(select(AuditLog.action).where(AuditLog.target_id == uuid.UUID(ids[0])))
    ).all()
    assert "submission.delete" in actions and "submission.restore" in actions


async def test_deleted_submissions_hidden_everywhere(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me)
    ids = await _ids(client, pub)
    await client.post(
        f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": ids[:1], "action": "delete"}
    )
    page = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()
    assert page["total"] == 2 and ids[0] not in [i["id"] for i in page["items"]]
    forms = (await client.get(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms")).json()
    assert next(f for f in forms if f["id"] == pub.id)["submissionCount"] == 2
    # Insights count only what is not deleted.
    res = await client.get(f"/api/v1/forms/{pub.id}/insights")
    assert res.status_code == 200 and res.json()["total"] == 2
    # Restoring or erasing works on the trash only.
    res = await client.post(
        f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": ids[1:], "action": "purge"}
    )
    assert res.json() == {"changed": 0}


async def test_purge_now_and_nightly(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me, n=3)
    ids = await _ids(client, pub)
    bulk = f"/api/v1/forms/{pub.id}/submissions/bulk"
    await client.post(bulk, json={"ids": ids, "action": "delete"})

    # "Delete permanently now".
    res = await client.post(bulk, json={"ids": ids[:1], "action": "purge"})
    assert res.json() == {"changed": 1}
    assert await db.get(Submission, uuid.UUID(ids[0])) is None
    tomb = await db.scalar(
        select(AuditLog).where(
            AuditLog.action == "submission.erased", AuditLog.target_id == uuid.UUID(ids[0])
        )
    )
    assert tomb is not None and tomb.meta["reason"] == "owner"

    # Nightly: the trash period (setting), then gone.
    await db.execute(
        update(Submission)
        .where(Submission.id == uuid.UUID(ids[1]))
        .values(deleted_at=datetime.now(UTC) - timedelta(days=8))
    )
    await db.commit()
    assert await retention.purge(db, file_storage, trash_days=30) == 0
    assert await retention.purge(db, file_storage, trash_days=7) == 1
    assert await db.get(Submission, uuid.UUID(ids[1])) is None

    # A shorter retention period wins over the trash.
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"retentionDays": 5})
    assert res.status_code == 200
    await db.execute(
        update(Submission)
        .where(Submission.id == uuid.UUID(ids[2]))
        .values(submitted_at=datetime.now(UTC) - timedelta(days=4))
    )
    await db.commit()
    item = (await client.get(f"/api/v1/forms/{pub.id}/submissions/deleted")).json()["items"][0]
    purge = datetime.fromisoformat(item["purgeAt"])
    assert purge - datetime.now(UTC) < timedelta(days=2)


async def test_trash_permissions(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    app: Any,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me)
    ids = await _ids(client, pub)
    await client.post(
        f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": ids[:1], "action": "delete"}
    )
    org_id = me["orgs"][0]["id"]
    for role in ("editor", "viewer"):
        user = await _member(db, org_id, f"trash-{role}@example.org", OrgRole.MEMBER)
        db.add(FormPermission(form_id=uuid.UUID(pub.id), user_id=user.id, role=FormRole(role)))
        await db.commit()
        async with make_client(app) as other:
            await login(other, queue, user.email)
            res = await other.get(f"/api/v1/forms/{pub.id}/submissions/deleted")
            assert res.status_code == 403, role
            res = await other.post(f"/api/v1/submissions/{ids[0]}/restore")
            assert res.status_code == 403, role
            res = await other.post(
                f"/api/v1/forms/{pub.id}/submissions/bulk",
                json={"ids": ids[:1], "action": "restore"},
            )
            assert res.status_code == 403, role
            res = await other.delete(f"/api/v1/forms/{pub.id}")
            assert res.status_code == 403, role
    # A form owner who is not an admin may restore.
    owner = await _member(db, org_id, "trash-owner@example.org", OrgRole.CREATOR)
    db.add(FormPermission(form_id=uuid.UUID(pub.id), user_id=owner.id, role=FormRole.OWNER))
    await db.commit()
    async with make_client(app) as other:
        await login(other, queue, owner.email)
        assert (await other.post(f"/api/v1/submissions/{ids[0]}/restore")).status_code == 204


async def test_form_trash_restore_and_cascade(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    app: Any,
) -> None:
    me = await admin_client(client, db, settings, queue)
    org_id = me["orgs"][0]["id"]
    pub = await _seed(client, me)
    ids = await _ids(client, pub)
    # One submission was deleted on its own before the form.
    await client.post(
        f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": ids[:1], "action": "delete"}
    )
    assert (await client.delete(f"/api/v1/forms/{pub.id}")).status_code == 204
    assert (await client.get(f"/api/v1/forms/{pub.id}")).status_code == 404
    assert (await client.get(pub.base)).status_code == 404
    forms = (await client.get(f"/api/v1/orgs/{org_id}/forms")).json()
    assert pub.id not in [f["id"] for f in forms]

    trash = (await client.get(f"/api/v1/orgs/{org_id}/forms/trash")).json()
    assert [t["id"] for t in trash] == [pub.id]
    assert trash[0]["submissionCount"] == 2 and trash[0]["slugTaken"] is False
    assert trash[0]["deletedBy"]["email"] == "admin@example.org"

    # Another form takes the address meanwhile: restoring asks for a new one.
    other = await publish(client, me, [field("q")], title="Other")
    res = await client.patch(f"/api/v1/forms/{other.id}", json={"slug": pub.form["slug"]})
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/forms/{pub.id}/restore", json={})
    assert res.status_code == 409 and res.json()["detail"] == "slug_taken"
    suggestion = res.json()["suggestion"]
    assert suggestion and suggestion != pub.form["slug"]
    res = await client.post(f"/api/v1/forms/{pub.id}/restore", json={"slug": pub.form["slug"]})
    assert res.status_code == 409
    res = await client.post(f"/api/v1/forms/{pub.id}/restore", json={"slug": suggestion})
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == suggestion

    # The submissions came back with it; the one deleted on its own is still in its trash.
    stats = await _stats(client, pub)
    assert stats["all"] == 2 and stats["deleted"] == 1
    actions = (
        await db.scalars(select(AuditLog.action).where(AuditLog.target_id == uuid.UUID(pub.id)))
    ).all()
    assert "form.delete" in actions and "form.restore" in actions

    # Creators see only the deleted forms they own; admins see all.
    creator = await _member(db, org_id, "trash-creator@example.org", OrgRole.CREATOR)
    async with make_client(app) as c2:
        mine = await login(c2, queue, creator.email)
        res = await c2.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "Mine"})
        own_id = res.json()["id"]
        assert (await c2.delete(f"/api/v1/forms/{own_id}")).status_code == 204
        assert mine
        trash = (await c2.get(f"/api/v1/orgs/{org_id}/forms/trash")).json()
        assert [t["id"] for t in trash] == [own_id]
        # Not theirs: 404.
        assert (await client.delete(f"/api/v1/forms/{other.id}")).status_code == 204
        res = await c2.post(f"/api/v1/forms/{other.id}/restore", json={})
        assert res.status_code == 404
    trash = (await client.get(f"/api/v1/orgs/{org_id}/forms/trash")).json()
    assert {t["id"] for t in trash} == {own_id, other.id}
    # Admins restore forms others deleted.
    res = await client.post(f"/api/v1/forms/{own_id}/restore", json={})
    assert res.status_code == 200


async def test_form_erase_now_and_nightly(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me, n=2)
    form_id = uuid.UUID(pub.id)
    # A stored object of the form, to see it go with the form.
    key = f"og/{pub.id}/stale.png"
    await file_storage.put(key, b"x")
    assert (await client.delete(f"/api/v1/forms/{pub.id}/permanent")).status_code == 404
    await client.delete(f"/api/v1/forms/{pub.id}")
    res = await client.delete(f"/api/v1/forms/{pub.id}/permanent")
    assert res.status_code == 204
    assert await db.get(FormRecord, form_id) is None
    left = await db.scalar(
        select(func.count()).select_from(Submission).where(Submission.form_id == form_id)
    )
    assert left == 0
    assert not await file_storage.exists(key)
    tomb = await db.scalar(
        select(AuditLog).where(AuditLog.action == "form.erased", AuditLog.target_id == form_id)
    )
    assert tomb is not None and tomb.meta["submissions"] == 2

    # Nightly: a form in the trash past the period goes with its submissions.
    pub2 = await _seed(client, me, n=1, title="Second")
    await client.delete(f"/api/v1/forms/{pub2.id}")
    assert await retention.purge(db, file_storage) == 0
    await db.execute(
        update(FormRecord)
        .where(FormRecord.id == uuid.UUID(pub2.id))
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db.commit()
    assert await retention.purge(db, file_storage) == 1
    assert await db.get(FormRecord, uuid.UUID(pub2.id)) is None


async def test_restored_event_in_chain(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me, n=1)
    sid = (await _ids(client, pub))[0]
    for _ in range(2):
        await client.post(
            f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": [sid], "action": "delete"}
        )
        await client.post(f"/api/v1/submissions/{sid}/restore")
    types = (
        await db.scalars(
            select(SubmissionEvent.type)
            .where(SubmissionEvent.submission_id == uuid.UUID(sid))
            .order_by(SubmissionEvent.seq)
        )
    ).all()
    assert [t.value for t in types] == ["created", "deleted", "restored", "deleted", "restored"]
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None and (await verify_submission(db, sub)).ok


async def test_verify_page_follows_the_trash(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _seed(client, me, n=1)
    sid = uuid.UUID((await _ids(client, pub))[0])
    await db.execute(
        update(Submission)
        .where(Submission.id == sid)
        .values(verify_token="tok-" + "a" * 20, pdf_sha256="0" * 64)
    )
    await db.commit()
    url = "/api/v1/public/verify/tok-" + "a" * 20
    assert (await client.get(url)).status_code == 200
    await client.delete(f"/api/v1/forms/{pub.id}")
    assert (await client.get(url)).status_code == 404
    await client.post(f"/api/v1/forms/{pub.id}/restore", json={})
    assert (await client.get(url)).status_code == 200
