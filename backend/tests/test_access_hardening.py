"""Access rules around live forms: staff-only forms, draft status, one response per address,
files of trashed submissions."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRole, Organization, OrgRole, Submission, User
from app.services.users import set_membership
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client, field, publish
from tests.test_uploads import ID_COPY, PDF, upload_local


async def test_staff_only_form_needs_the_forms_organisation(
    app: Any, client: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    await client.patch(f"/api/v1/forms/{pub.id}", json={"accessMode": "staff"})
    other = Organization(name="Other", slug="other")
    outsider = User(email="outsider@example.net")
    member = User(email="member@example.org")
    db.add_all([other, outsider, member])
    await db.flush()
    await set_membership(db, other, outsider, OrgRole.ADMIN)
    org = await db.get(Organization, me["orgs"][0]["id"])
    assert org is not None
    await set_membership(db, org, member, OrgRole.MEMBER)
    await db.commit()

    async with make_client(app) as c:
        await login(c, queue, "outsider@example.net")
        res = await c.get(pub.base)
        assert res.status_code == 403 and res.json()["detail"] == "not_in_organisation"
        live = (await client.get(pub.base)).json()
        res = await c.post(
            f"{pub.base}/submissions",
            json={
                "versionId": live["versionId"],
                "data": {"name": "x"},
                "uploadNonce": live["uploadNonce"],
            },
        )
        assert res.status_code == 403
    assert await db.scalar(select(func.count()).select_from(Submission)) == 0

    async with make_client(app) as c:
        await login(c, queue, "member@example.org")
        live = (await c.get(pub.base)).json()
        assert live["respondentEmail"] == "member@example.org" and live["schema"]


async def test_one_response_holds_under_concurrent_submits(
    app: Any, client: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    res = await client.patch(
        f"/api/v1/forms/{pub.id}", json={"accessMode": "otp", "otpOneResponse": True}
    )
    assert res.status_code == 200, res.text
    async with make_client(app) as public:
        res = await public.post(f"{pub.base}/otp/request", json={"email": "a@example.org"})
        assert res.status_code == 202
        res = await public.post(
            f"{pub.base}/otp/verify",
            json={"email": "a@example.org", "code": queue.last_code("a@example.org")},
        )
        auth = {"Authorization": f"Bearer {res.json()['token']}"}
        live = (await public.get(pub.base, headers=auth)).json()
        body = {
            "versionId": live["versionId"],
            "data": {"name": "A"},
            "uploadNonce": live["uploadNonce"],
        }
        results = await asyncio.gather(
            *(public.post(f"{pub.base}/submissions", json=body, headers=auth) for _ in range(5))
        )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in results]
    count = await db.scalar(
        select(func.count()).select_from(Submission).where(Submission.respondent_email.is_not(None))
    )
    assert count == 1


async def test_files_of_trashed_submissions_are_owner_only(
    app: Any, client: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name"), ID_COPY])
    ref = await upload_local(client, pub, PDF)
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body({"name": "A", "id_copy": [ref]})
    )
    assert res.status_code == 201, res.text
    sub_id = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()["items"][0]["id"]
    viewer = User(email="viewer@example.org")
    db.add(viewer)
    await db.flush()
    org = await db.get(Organization, uuid.UUID(me["orgs"][0]["id"]))
    assert org is not None
    await set_membership(db, org, viewer, OrgRole.MEMBER)
    db.add(FormPermission(form_id=uuid.UUID(pub.id), user_id=viewer.id, role=FormRole.VIEWER))
    await db.commit()
    url = f"/api/v1/files/{ref['fileId']}"
    async with make_client(app) as other:
        await login(other, queue, "viewer@example.org")
        assert (await other.get(url)).status_code == 200
        res = await client.post(
            f"/api/v1/forms/{pub.id}/submissions/bulk", json={"ids": [sub_id], "action": "delete"}
        )
        assert res.json() == {"changed": 1}
        res = await other.get(url)
        assert res.status_code == 404 and res.json()["detail"] == "file_not_found"
    # The owner still sees them in the trash.
    assert (await client.get(url)).status_code == 200
