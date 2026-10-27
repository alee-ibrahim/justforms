"""Access rules around live forms: staff-only forms, draft status, one response per address,
files of trashed submissions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Organization, OrgRole, Submission, User
from app.services.users import set_membership
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client, field, publish


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
