"""Invitations, people management and sharing with an invite (docs/ux/PEOPLE-SCREENS.md)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import worker
from app.config import Settings
from app.models import (
    AuditLog,
    FormPermission,
    InvitationStatus,
    InviteEmailStatus,
    Organization,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    User,
)
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client

Sent = list[dict[str, Any]]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch, db_engine: Any, settings: Settings) -> Sent:
    """Run invitation emails through the real worker job, with SMTP faked."""
    out: Sent = []

    async def smtp(_settings: Settings, to: str, subject: str, text: str, **kw: Any) -> bool:
        out.append({"to": to, "subject": subject, "text": text, "html": kw.get("html")})
        return True

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    smtp_settings = settings.model_copy(update={"smtp_host": "smtp.example.org"})
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(worker, "get_settings", lambda: smtp_settings)
    monkeypatch.setattr(worker, "smtp_send", smtp)
    return out


async def deliver(queue: RecordingQueue) -> None:
    """Run (and drop) the queued invitation email jobs."""
    jobs = [kw for fn, kw in queue.jobs if fn == "send_invitation_email"]
    queue.jobs[:] = [(fn, kw) for fn, kw in queue.jobs if fn != "send_invitation_email"]
    for kw in jobs:
        await worker.send_invitation_email({"job_try": 1}, **kw)


def link_token(text: str) -> str:
    match = re.search(r"/login/invite/([A-Za-z0-9_-]+)", text)
    assert match, text
    return match.group(1)


async def setup_admin(
    db: AsyncSession, settings: Settings, client: AsyncClient, queue: RecordingQueue
) -> Organization:
    await create_admin(db, settings, "root@example.org", "Root Admin")
    org = await ensure_default_org(db, settings)
    await db.commit()
    await login(client, queue, "root@example.org")
    return org


async def add_person(
    db: AsyncSession, org: Organization, email: str, role: OrgRole, name: str = ""
) -> User:
    user = User(email=email, display_name=name)
    db.add(user)
    await db.flush()
    await set_membership(db, org, user, role)
    await db.commit()
    return user


async def invite(client: AsyncClient, org: Organization, *emails: str, role: str = "member") -> Any:
    return await client.post(
        f"/api/v1/orgs/{org.id}/invitations", json={"emails": list(emails), "role": role}
    )


async def code_login(app: Any, queue: RecordingQueue, email: str) -> tuple[AsyncClient, Any]:
    c = make_client(app)
    me = await login(c, queue, email)
    return c, me


# -- invite, email, accept ----------------------------------------------------------------------


async def test_invite_email_and_accept_with_a_code(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    sent: Sent,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await add_person(db, org, "here@example.org", OrgRole.MEMBER)

    res = await invite(
        client, org, "Ana@Example.org", "ana@example.org", "here@example.org", role="creator"
    )
    assert res.status_code == 200, res.text
    assert res.json()["results"] == [
        {"email": "ana@example.org", "outcome": "invited"},
        {"email": "here@example.org", "outcome": "already_member"},
    ]
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    [inv] = people["invitations"]
    assert (inv["email"], inv["role"], inv["state"]) == ("ana@example.org", "creator", "invited")
    assert inv["invitedByName"] == "Root Admin"
    assert {m["email"]: m["status"] for m in people["members"]} == {
        "root@example.org": "active",
        "here@example.org": "never_signed_in",
    }
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "org.invite"))

    # The worker mints the link, commits it, then sends the branded email.
    await deliver(queue)
    [mail] = sent
    assert mail["to"] == "ana@example.org"
    assert mail["subject"] == "You've been invited to JustForms"
    assert "Root Admin invited you to JustForms as a form creator." in mail["text"]
    assert "Accept the invitation" in mail["html"]
    token = link_token(mail["text"])
    link = (await client.get(f"/api/v1/public/invitations/{token}")).json()
    assert link["status"] == "pending"
    assert (link["email"], link["role"], link["invitedByName"]) == (
        "ana@example.org",
        "creator",
        "Root Admin",
    )

    # No account yet: the open invitation is enough to get a code, and the code accepts it.
    ana, me = await code_login(app, queue, "ana@example.org")
    assert [(o["id"], o["role"]) for o in me["orgs"]] == [(str(org.id), "creator")]
    assert (await client.get(f"/api/v1/public/invitations/{token}")).json()["status"] == "accepted"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "org.invite_accept"))
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    assert people["invitations"] == []
    assert any(
        m["email"] == "ana@example.org" and m["status"] == "active" for m in people["members"]
    )
    await ana.aclose()


async def test_unknown_address_gets_no_code(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await setup_admin(db, settings, client, queue)
    res = await client.post("/api/v1/auth/local/request", json={"email": "nobody@example.org"})
    assert res.status_code == 202
    assert not [
        kw for fn, kw in queue.jobs if fn == "send_email" and kw["to"] == "nobody@example.org"
    ]


async def test_invalid_and_too_many_addresses(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    assert (await invite(client, org, "not-an-email")).status_code == 422
    many = [f"p{i}@example.org" for i in range(21)]
    assert (await invite(client, org, *many)).status_code == 422
    assert (await invite(client, org)).status_code == 422


async def test_expired_invitation(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    sent: Sent,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await invite(client, org, "late@example.org")
    await deliver(queue)
    token = link_token(sent[0]["text"])
    inv = await db.scalar(select(OrgInvitation).where(OrgInvitation.email == "late@example.org"))
    assert inv is not None
    inv.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    assert (await client.get(f"/api/v1/public/invitations/{token}")).json()["status"] == "expired"
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    assert people["invitations"][0]["state"] == "expired"
    # No account and no open invitation: no code is sent.
    queue.jobs.clear()
    await client.post("/api/v1/auth/local/request", json={"email": "late@example.org"})
    assert not [kw for fn, kw in queue.jobs if fn == "send_email"]
    assert await db.scalar(select(User).where(User.email == "late@example.org")) is None

    # Resending opens it again with a new link; the old one stops working.
    res = await client.post(f"/api/v1/orgs/{org.id}/invitations/{inv.id}/resend")
    assert res.status_code == 200 and res.json()["state"] == "invited"
    await deliver(queue)
    new_token = link_token(sent[-1]["text"])
    assert new_token != token
    assert (await client.get(f"/api/v1/public/invitations/{token}")).json()["status"] == "invalid"
    link = (await client.get(f"/api/v1/public/invitations/{new_token}")).json()
    assert link["status"] == "pending"


async def test_resend_is_rate_limited(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await invite(client, org, "again@example.org")
    inv_id = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()["invitations"][0]["id"]
    url = f"/api/v1/orgs/{org.id}/invitations/{inv_id}/resend"
    for _ in range(3):
        assert (await client.post(url)).status_code == 200
    res = await client.post(url)
    assert res.status_code == 429 and "Retry-After" in res.headers


async def test_invites_are_rate_limited_per_admin(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    settings.rate_limits = ["invite_user=3/3600"]
    org = await setup_admin(db, settings, client, queue)
    assert (await invite(client, org, "a@example.org", "b@example.org")).status_code == 200
    # Two more would go over 3: refused as a whole, nothing created.
    res = await invite(client, org, "c@example.org", "d@example.org")
    assert res.status_code == 429
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    assert sorted(i["email"] for i in people["invitations"]) == ["a@example.org", "b@example.org"]


async def test_reinvite_updates_role_and_cancel(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    sent: Sent,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await invite(client, org, "bo@example.org")
    assert (await invite(client, org, "bo@example.org", role="admin")).json()["results"][0][
        "outcome"
    ] == "invited"
    [inv] = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()["invitations"]
    assert inv["role"] == "admin"
    res = await client.patch(
        f"/api/v1/orgs/{org.id}/invitations/{inv['id']}", json={"role": "creator"}
    )
    assert res.status_code == 200 and res.json()["role"] == "creator"
    await deliver(queue)
    token = link_token(sent[-1]["text"])

    assert (
        await client.delete(f"/api/v1/orgs/{org.id}/invitations/{inv['id']}")
    ).status_code == 204
    assert (await client.get(f"/api/v1/public/invitations/{token}")).json()["status"] == "invalid"
    assert (await client.get(f"/api/v1/orgs/{org.id}/people")).json()["invitations"] == []
    # A cancelled invitation gives no code and no membership.
    queue.jobs.clear()
    await client.post("/api/v1/auth/local/request", json={"email": "bo@example.org"})
    assert not [kw for fn, kw in queue.jobs if fn == "send_email"]
    row = await db.get(OrgInvitation, uuid.UUID(inv["id"]))
    assert row is not None and row.status == InvitationStatus.CANCELLED


async def test_email_not_set_up(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
    db_engine: Any,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    monkeypatch.setattr(
        worker, "get_sessionmaker", lambda: async_sessionmaker(db_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)  # no SMTP host
    await invite(client, org, "quiet@example.org")
    await deliver(queue)
    [inv] = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()["invitations"]
    assert inv["state"] == "email_failed"
    assert inv["emailError"] == "Email isn't set up on this server."
    row = await db.get(OrgInvitation, uuid.UUID(inv["id"]))
    assert row is not None and row.email_status == InviteEmailStatus.FAILED


async def test_accept_while_signed_in(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    sent: Sent,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    other_org = Organization(name="Second Office", slug="second")
    db.add(other_org)
    await db.flush()
    await add_person(db, org, "staff@example.org", OrgRole.MEMBER)
    await add_person(db, org, "else@example.org", OrgRole.MEMBER)
    # The invitee is signed in before the invitation exists.
    staff = make_client(app)
    await login(staff, queue, "staff@example.org")
    # Superadmins manage people in any organisation.
    res = await invite(client, other_org, "Staff@example.org", role="creator")
    assert res.status_code == 200
    await deliver(queue)
    assert sent[-1]["subject"] == "You've been invited to Second Office on JustForms"
    token = link_token(sent[-1]["text"])
    link = (await client.get(f"/api/v1/public/invitations/{token}")).json()
    assert (link["orgName"], link["orgSlug"]) == ("Second Office", "second")

    wrong, _ = await code_login(app, queue, "else@example.org")
    assert (await wrong.post(f"/api/v1/invitations/{token}/accept")).status_code == 403
    await wrong.aclose()

    res = await staff.post(f"/api/v1/invitations/{token}/accept")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["orgName"] == "Second Office"
    assert {(o["slug"], o["role"]) for o in body["me"]["orgs"]} == {
        ("default", "member"),
        ("second", "creator"),
    }
    # Accepting again is harmless; the link now says it was used.
    assert (await staff.post(f"/api/v1/invitations/{token}/accept")).status_code == 200
    await staff.aclose()


# -- members: roles, last admin, removal ---------------------------------------------------------


async def test_last_admin_guard(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    root = await db.scalar(select(User).where(User.email == "root@example.org"))
    assert root is not None
    url = f"/api/v1/orgs/{org.id}/members/{root.id}"
    res = await client.patch(url, json={"role": "member"})
    assert res.status_code == 409 and res.json()["detail"] == "last_admin"
    assert (await client.delete(url)).status_code == 409

    second = await add_person(db, org, "second@example.org", OrgRole.ADMIN)
    assert (await client.patch(url, json={"role": "creator"})).status_code == 200
    # Now the second admin is the last one.
    res = await client.delete(f"/api/v1/orgs/{org.id}/members/{second.id}")
    assert res.status_code == 409
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "org.member_role"))
    assert log is not None and log.meta == {"before": "admin", "role": "creator"}


async def test_removing_a_member_revokes_their_form_access(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    leaver = await add_person(db, org, "leaver@example.org", OrgRole.CREATOR)
    f1 = (await client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "One"})).json()["id"]
    f2 = (await client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "Two"})).json()["id"]
    for fid in (f1, f2):
        db.add(FormPermission(form_id=uuid.UUID(fid), user_id=leaver.id, role="viewer"))
    await db.commit()
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    assert (
        next(m for m in people["members"] if m["email"] == "leaver@example.org")["formCount"] == 2
    )

    res = await client.delete(f"/api/v1/orgs/{org.id}/members/{leaver.id}")
    assert res.status_code == 204
    assert (
        await db.scalar(select(FormPermission).where(FormPermission.user_id == leaver.id))
    ) is None
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "org.member_remove"))
    assert log is not None and log.meta["forms_revoked"] == 2
    async with make_client(app) as c:
        me = await login(c, queue, "leaver@example.org")
        assert me["orgs"] == []
        assert (await c.get(f"/api/v1/forms/{f1}")).status_code == 404
        assert (await c.get(f"/api/v1/orgs/{org.id}/forms")).json() == []


# -- sharing a form with someone new ---------------------------------------------------------------


async def test_share_with_invite(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    sent: Sent,
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await add_person(db, org, "maker@example.org", OrgRole.CREATOR)
    form = (await client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "Permit"})).json()
    url = f"/api/v1/forms/{form['id']}/permissions"
    assert (await client.get(url)).json()["canInvite"] is True

    res = await client.put(url, json={"grants": [{"email": "guest@example.org", "role": "editor"}]})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "not_a_member"
    res = await client.post(f"{url}/invite", json={"email": "Guest@example.org", "role": "editor"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [(p["email"], p["role"], p["expired"]) for p in body["pending"]] == [
        ("guest@example.org", "editor", False)
    ]
    await deliver(queue)
    assert "They shared these forms with you:" in sent[-1]["text"]
    assert "Permit" in sent[-1]["text"]

    # Inviting again for the same form only refreshes the pending invitation.
    assert (
        await client.post(f"{url}/invite", json={"email": "guest@example.org", "role": "viewer"})
    ).json()["pending"][0]["role"] == "viewer"

    async with make_client(app) as guest:
        me = await login(guest, queue, "guest@example.org")
        assert [o["role"] for o in me["orgs"]] == ["member"]
        res = await guest.get(f"/api/v1/forms/{form['id']}")
        assert res.status_code == 200 and res.json()["role"] == "viewer"
        # Members don't create forms.
        res = await guest.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "Mine"})
        assert res.status_code == 403
    assert (await client.get(url)).json()["pending"] == []

    # Owners who aren't organisation admins can't invite.
    async with make_client(app) as maker:
        await login(maker, queue, "maker@example.org")
        own = (await maker.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "Own"})).json()
        own_url = f"/api/v1/forms/{own['id']}/permissions"
        assert (await maker.get(own_url)).json()["canInvite"] is False
        res = await maker.post(
            f"{own_url}/invite", json={"email": "x@example.org", "role": "viewer"}
        )
        assert res.status_code == 403 and res.json()["detail"] == "invite_requires_admin"


async def test_remove_pending_form_access(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    form = (await client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "F"})).json()
    url = f"/api/v1/forms/{form['id']}/permissions"
    body = (
        await client.post(f"{url}/invite", json={"email": "p@example.org", "role": "viewer"})
    ).json()
    inv_id = body["pending"][0]["invitationId"]
    res = await client.delete(f"{url}/invitations/{inv_id}")
    assert res.status_code == 200 and res.json()["pending"] == []
    # The invitation to the organisation itself stays.
    people = (await client.get(f"/api/v1/orgs/{org.id}/people")).json()
    assert [i["email"] for i in people["invitations"]] == ["p@example.org"]
    assert (await client.delete(f"{url}/invitations/{inv_id}")).status_code == 404


async def test_invitation_to_an_existing_member_is_refused_from_share(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await add_person(db, org, "in@example.org", OrgRole.MEMBER)
    form = (await client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "F"})).json()
    res = await client.post(
        f"/api/v1/forms/{form['id']}/permissions/invite",
        json={"email": "in@example.org", "role": "viewer"},
    )
    assert res.status_code == 409


async def test_unknown_link(client: AsyncClient) -> None:
    res = await client.get("/api/v1/public/invitations/" + "x" * 32)
    assert res.status_code == 200 and res.json() == {"status": "invalid"} | {
        k: None for k in ("orgName", "orgSlug", "email", "role", "invitedByName", "expiresAt")
    }


async def test_membership_stays_idp_unmanaged_after_invite(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await invite(client, org, "joiner@example.org", role="creator")
    async with make_client(app) as c:
        await login(c, queue, "joiner@example.org")
    user = await db.scalar(select(User).where(User.email == "joiner@example.org"))
    assert user is not None
    membership = await db.get(OrgMembership, (org.id, user.id))
    assert membership is not None
    await db.refresh(membership)
    assert membership.role == OrgRole.CREATOR and membership.idp_managed is False


async def test_removal_and_demotion_end_the_persons_sessions(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    await add_person(db, org, "demoted@example.org", OrgRole.ADMIN)
    await add_person(db, org, "raised@example.org", OrgRole.MEMBER)
    await add_person(db, org, "leaver@example.org", OrgRole.CREATOR)
    people = {}
    for email in ("demoted@example.org", "raised@example.org", "leaver@example.org"):
        c, me = await code_login(app, queue, email)
        people[email] = (c, me["id"])
    base = f"/api/v1/orgs/{org.id}/members"
    try:
        demoted, demoted_id = people["demoted@example.org"]
        assert (await client.patch(f"{base}/{demoted_id}", json={"role": "member"})).is_success
        assert (await demoted.get("/api/v1/auth/me")).status_code == 401
        # Raising someone's role keeps them signed in.
        raised, raised_id = people["raised@example.org"]
        assert (await client.patch(f"{base}/{raised_id}", json={"role": "creator"})).is_success
        assert (await raised.get("/api/v1/auth/me")).status_code == 200
        leaver, leaver_id = people["leaver@example.org"]
        assert (await client.delete(f"{base}/{leaver_id}")).status_code == 204
        assert (await leaver.get("/api/v1/auth/me")).status_code == 401
        # The admin acting keeps their own session.
        assert (await client.get("/api/v1/auth/me")).status_code == 200
    finally:
        for c, _ in people.values():
            await c.aclose()


async def test_admin_demoting_themselves_keeps_this_session(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await setup_admin(db, settings, client, queue)
    root = await db.scalar(select(User).where(User.email == "root@example.org"))
    assert root is not None
    other, _ = await code_login(app, queue, "root@example.org")  # a second browser
    try:
        await add_person(db, org, "second@example.org", OrgRole.ADMIN)
        res = await client.patch(
            f"/api/v1/orgs/{org.id}/members/{root.id}", json={"role": "member"}
        )
        assert res.status_code == 200
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert (await other.get("/api/v1/auth/me")).status_code == 401
    finally:
        await other.aclose()
