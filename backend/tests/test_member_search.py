"""Type-ahead member suggestions (docs/ux/PEOPLE-SCREENS.md 6.2)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.orgs import fold, initials
from app.config import Settings
from app.models import FormPermission, FormRole, Organization, OrgRole, User
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client


async def _member(
    db: AsyncSession,
    org: Organization,
    email: str,
    name: str = "",
    role: OrgRole = OrgRole.MEMBER,
) -> User:
    user = User(email=email, display_name=name)
    db.add(user)
    await db.flush()
    await set_membership(db, org, user, role)
    await db.commit()
    return user


def test_fold_and_initials() -> None:
    assert fold("Zoë Ångström") == "zoe angstrom"
    assert initials("Aminath Ali", "a@example.org") == "AA"
    assert initials("", "hassan.rasheed@example.org") == "HR"
    assert initials("Mariyam", "m@example.org") == "M"


async def test_search_ranking_permissions_and_isolation(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "admin@example.org", "Root Admin")
    org = await ensure_default_org(db, settings)
    owner = await _member(db, org, "owner@example.org", "Aminath Ali", OrgRole.CREATOR)
    editor = await _member(db, org, "editor@example.org", "Ibrahim Naseer")
    await _member(db, org, "zoe@example.org", "Zoë Hassan")
    await _member(db, org, "ali.hassan@example.org", "Ali Hassan")
    await _member(db, org, "pct@example.org", "100% Sure")
    # Someone in another organisation (and someone in none) is never suggested.
    other = Organization(name="Second Office", slug="second")
    db.add(other)
    await db.flush()
    await _member(db, other, "hassan.other@example.org", "Hassan Other")
    db.add(User(email="hassan.none@example.org", display_name="Hassan None"))
    await db.commit()

    me = await login(client, queue, "owner@example.org")
    org_id = me["orgs"][0]["id"]
    form = (await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "F"})).json()
    db.add(FormPermission(form_id=form["id"], user_id=editor.id, role=FormRole.EDITOR))
    await db.commit()
    url = f"/api/v1/orgs/{org_id}/members/search"

    # A form owner searches for that form; access already given is marked.
    res = await client.get(url, params={"q": "hassan", "form_id": form["id"]})
    assert res.status_code == 200, res.text
    found = [m["email"] for m in res.json()]
    # Both have a word starting with it; by name. Other organisations' people never show.
    assert found == ["ali.hassan@example.org", "zoe@example.org"]
    res = await client.get(url, params={"q": "ibra", "form_id": form["id"]})
    [match] = res.json()
    assert match == {
        "userId": str(editor.id),
        "email": "editor@example.org",
        "displayName": "Ibrahim Naseer",
        "role": "member",
        "initials": "IN",
        "formRole": "editor",
    }
    res = await client.get(url, params={"q": "ADMIN@", "form_id": form["id"]})
    assert [(m["email"], m["formRole"]) for m in res.json()] == [("admin@example.org", "owner")]
    res = await client.get(url, params={"q": "aminath", "form_id": form["id"]})
    assert res.json()[0]["userId"] == str(owner.id) and res.json()[0]["formRole"] == "owner"

    # Accents and case are ignored; LIKE wildcards are literal.
    res = await client.get(url, params={"q": "ZOE", "form_id": form["id"]})
    assert [m["email"] for m in res.json()] == ["zoe@example.org"]
    res = await client.get(url, params={"q": "0%", "form_id": form["id"]})
    assert [m["email"] for m in res.json()] == ["pct@example.org"]
    res = await client.get(url, params={"q": "a_i", "form_id": form["id"]})
    assert res.json() == []
    # Exact email first, and the limit applies.
    res = await client.get(url, params={"q": "e", "form_id": form["id"]})
    assert res.status_code == 422  # at least two characters
    res = await client.get(url, params={"q": "example", "form_id": form["id"], "limit": 2})
    assert len(res.json()) == 2

    # Without a form, only org admins may search; owners of the form only, editors not.
    assert (await client.get(url, params={"q": "hassan"})).status_code == 403
    async with make_client(app) as ed:
        await login(ed, queue, "editor@example.org")
        res = await ed.get(url, params={"q": "hassan", "form_id": form["id"]})
        assert res.status_code == 403
    async with make_client(app) as admin:
        await login(admin, queue, "admin@example.org")
        res = await admin.get(url, params={"q": "hassan"})
        assert [(m["email"], m["formRole"]) for m in res.json()] == [
            ("ali.hassan@example.org", None),
            ("zoe@example.org", None),
        ]
        # The other organisation's members only show when searching that organisation.
        res = await admin.get(f"/api/v1/orgs/{other.id}/members/search", params={"q": "hassan"})
        assert [m["email"] for m in res.json()] == ["hassan.other@example.org"]

    # Another organisation, or a form of this one under another org id: not found.
    res = await client.get(f"/api/v1/orgs/{other.id}/members/search", params={"q": "hassan"})
    assert res.status_code == 404
    async with make_client(app) as outsider:
        await login(outsider, queue, "hassan.other@example.org")
        res = await outsider.get(url, params={"q": "hassan", "form_id": form["id"]})
        assert res.status_code == 404
        res = await outsider.get(
            f"/api/v1/orgs/{other.id}/members/search", params={"q": "ali", "form_id": form["id"]}
        )
        assert res.status_code == 404


async def test_search_is_rate_limited(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    settings.rate_limits = ["member_search=2/60"]
    url = f"/api/v1/orgs/{me['orgs'][0]['id']}/members/search"
    assert (await client.get(url, params={"q": "ad"})).status_code == 200
    assert (await client.get(url, params={"q": "ad"})).status_code == 200
    res = await client.get(url, params={"q": "ad"})
    assert res.status_code == 429 and res.headers["retry-after"]
