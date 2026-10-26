"""Role x endpoint matrices (DESIGN section 7): form-scoped endpoints by form role, and
organisation-scoped endpoints by organisation role (admin > creator > member)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRole, OrgRole, User
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client

FIELD = {"kind": "field", "id": "q", "type": "short_text", "label": "Q"}

# endpoint -> (method, path template, body); bodies need the current draft revision.
ENDPOINTS: dict[str, tuple[str, str, Any]] = {
    "get_form": ("GET", "/api/v1/forms/{id}", None),
    "list_versions": ("GET", "/api/v1/forms/{id}/versions", None),
    "get_draft": ("GET", "/api/v1/forms/{id}/draft", None),
    "draft_changes": ("GET", "/api/v1/forms/{id}/draft/changes", None),
    "patch_draft": (
        "PATCH",
        "/api/v1/forms/{id}/draft",
        {
            "baseRevision": 1,
            "patch": [{"op": "add", "path": "/pages/0/elements/0", "value": FIELD}],
        },
    ),
    "patch_slug": ("PATCH", "/api/v1/forms/{id}", {"slug": "renamed"}),
    "publish": ("POST", "/api/v1/forms/{id}/publish", None),
    "close_form": ("PATCH", "/api/v1/forms/{id}", {"status": "closed"}),
    "delete_form": ("DELETE", "/api/v1/forms/{id}", None),
}

ALLOWED: dict[str, set[str]] = {
    "viewer": {"get_form", "list_versions"},
    "editor": {
        "get_form",
        "list_versions",
        "get_draft",
        "draft_changes",
        "patch_draft",
        "patch_slug",
        "publish",
    },
    "owner": set(ENDPOINTS),
    "org_admin": set(ENDPOINTS),
    "superadmin": set(ENDPOINTS),
    "org_creator_no_grant": set(),
    "org_member_no_grant": set(),
    "outsider": set(),
}


async def _person(db: AsyncSession, org: Any, email: str, role: OrgRole | None) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    if role is not None:
        await set_membership(db, org, user, role)
    return user


@pytest.mark.parametrize("actor", list(ALLOWED))
@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
async def test_form_role_matrix(
    actor: str,
    endpoint: str,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    # The form belongs to its creator (owner role) in the default org.
    await create_admin(db, settings, "root@example.org")
    org = await ensure_default_org(db, settings)
    await _person(db, org, "creator@example.org", OrgRole.CREATOR)
    await db.commit()

    async with make_client(app) as owner_client:
        await login(owner_client, queue, "creator@example.org")
        res = await owner_client.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "F"})
        form_id = res.json()["id"]

    if actor == "superadmin":
        email = "root@example.org"
    else:
        email = f"{actor}@example.org"
        org_role = {
            "org_admin": OrgRole.ADMIN,
            "org_creator_no_grant": OrgRole.CREATOR,
            "org_member_no_grant": OrgRole.MEMBER,
            "viewer": OrgRole.MEMBER,
            "editor": OrgRole.MEMBER,
            "owner": OrgRole.MEMBER,
        }.get(actor)
        user = await _person(db, org, email, org_role)
        if actor in ("viewer", "editor", "owner"):
            db.add(FormPermission(form_id=form_id, user_id=user.id, role=FormRole(actor)))
        await db.commit()

    method, path, body = ENDPOINTS[endpoint]
    async with make_client(app) as c:
        await login(c, queue, email)
        res = await c.request(method, path.format(id=form_id), json=body)

    if endpoint in ALLOWED[actor]:
        assert res.status_code < 400, f"{actor} {endpoint}: {res.status_code} {res.text}"
    elif actor.endswith("_no_grant") or actor == "outsider":
        assert res.status_code == 404, f"{actor} {endpoint}: {res.status_code}"
    else:
        assert res.status_code == 403, f"{actor} {endpoint}: {res.status_code}"


# -- organisation roles ------------------------------------------------------------------------

# endpoint -> (method, path template, body). {org} is the organisation, {form} a form the
# actor can edit (shared with them as editor), {member} another member.
ORG_ENDPOINTS: dict[str, tuple[str, str, Any]] = {
    "get_org": ("GET", "/api/v1/orgs/{org}", None),
    "list_forms": ("GET", "/api/v1/orgs/{org}/forms", None),
    "create_form": ("POST", "/api/v1/orgs/{org}/forms", {"title": "New"}),
    "duplicate_form": ("POST", "/api/v1/forms/{form}/duplicate", None),
    "import_jotform": ("POST", "/api/v1/orgs/{org}/imports/jotform/html", {"html": "<p>x</p>"}),
    "get_branding": ("GET", "/api/v1/orgs/{org}/branding", None),
    "put_branding": ("PUT", "/api/v1/orgs/{org}/branding", {"displayName": "Example Office"}),
    "put_org_theme": ("PUT", "/api/v1/orgs/{org}/form-theme", {}),
    "patch_org": ("PATCH", "/api/v1/orgs/{org}", {"name": "Renamed"}),
    "list_people": ("GET", "/api/v1/orgs/{org}/people", None),
    "list_members": ("GET", "/api/v1/orgs/{org}/members", None),
    "invite": (
        "POST",
        "/api/v1/orgs/{org}/invitations",
        {"emails": ["new@example.org"], "role": "member"},
    ),
    "change_role": ("PATCH", "/api/v1/orgs/{org}/members/{member}", {"role": "creator"}),
    "remove_member": ("DELETE", "/api/v1/orgs/{org}/members/{member}", None),
}

EVERYONE = {"get_org", "list_forms", "get_branding"}
ORG_ALLOWED: dict[str, set[str]] = {
    "admin": set(ORG_ENDPOINTS),
    "superadmin": set(ORG_ENDPOINTS),
    "creator": EVERYONE | {"create_form", "duplicate_form", "import_jotform"},
    "member": EVERYONE,
}


@pytest.mark.parametrize("actor", [*ORG_ALLOWED, "outsider"])
@pytest.mark.parametrize("endpoint", list(ORG_ENDPOINTS))
async def test_org_role_matrix(
    actor: str,
    endpoint: str,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    await create_admin(db, settings, "root@example.org")
    org = await ensure_default_org(db, settings)
    await _person(db, org, "boss@example.org", OrgRole.ADMIN)
    other = await _person(db, org, "other@example.org", OrgRole.MEMBER)
    await db.commit()
    async with make_client(app) as boss:
        await login(boss, queue, "boss@example.org")
        form_id = (await boss.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "F"})).json()[
            "id"
        ]

    if actor == "superadmin":
        email = "root@example.org"
    else:
        email = f"{actor}@example.org"
        role = None if actor == "outsider" else OrgRole(actor)
        user = await _person(db, org, email, role)
        db.add(FormPermission(form_id=form_id, user_id=user.id, role=FormRole.EDITOR))
        await db.commit()

    method, path, body = ORG_ENDPOINTS[endpoint]
    async with make_client(app) as c:
        await login(c, queue, email)
        res = await c.request(
            method, path.format(org=org.id, form=form_id, member=other.id), json=body
        )

    if actor != "outsider" and endpoint in ORG_ALLOWED[actor]:
        assert res.status_code not in (401, 403, 404), (
            f"{actor} {endpoint}: {res.status_code} {res.text}"
        )
        assert res.status_code < 500
    elif endpoint == "list_forms":
        # Listing is scoped, never refused: an outsider sees only forms shared with them.
        assert res.status_code == 200
    elif endpoint == "duplicate_form":
        assert res.status_code == 403, f"{actor} {endpoint}: {res.status_code}"
    elif actor == "outsider":
        assert res.status_code in (403, 404), f"{actor} {endpoint}: {res.status_code}"
    else:
        assert res.status_code == 403, f"{actor} {endpoint}: {res.status_code} {res.text}"


async def test_only_org_members_create_forms(
    app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org = await ensure_default_org(db, settings)
    db.add(User(email="guest@example.org"))
    await db.commit()
    async with make_client(app) as c:
        await login(c, queue, "guest@example.org")
        res = await c.post(f"/api/v1/orgs/{org.id}/forms", json={"title": "F"})
        assert res.status_code == 404


async def test_member_management_is_admin_only(
    app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "root@example.org")
    org = await ensure_default_org(db, settings)
    await db.commit()
    async with make_client(app) as admin:
        await login(admin, queue, "root@example.org")
        res = await admin.post(
            f"/api/v1/orgs/{org.id}/members", json={"email": "New@Example.org", "role": "member"}
        )
        assert res.status_code == 201
        assert res.json()["email"] == "new@example.org"
        assert len((await admin.get(f"/api/v1/orgs/{org.id}/members")).json()) == 2
    async with make_client(app) as member:
        await login(member, queue, "new@example.org")
        assert (await member.get(f"/api/v1/orgs/{org.id}/members")).status_code == 403
        assert (await member.get(f"/api/v1/orgs/{org.id}")).status_code == 200
