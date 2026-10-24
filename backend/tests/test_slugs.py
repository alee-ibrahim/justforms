"""Form addresses: /<slug>, unique across the install, reserved words, the live check and the
backfill migration (docs/ux/FORM-THEME-SCREENS.md section 1)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Organization, OrgMembership, OrgRole
from app.services import slugs
from app.services.users import get_user_by_email
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field, publish


def test_shape_problems() -> None:
    assert slugs.shape_problem("youth-app") is None
    assert slugs.shape_problem("Youth") == "invalid"
    assert slugs.shape_problem("-x") == "invalid"
    assert slugs.shape_problem("a" * 101) == "invalid"
    for word in ("api", "login", "forms", "settings", "assets", "fonts", "v", "a", "f"):
        assert slugs.shape_problem(word) == "reserved"


def test_slugify() -> None:
    assert slugs.slugify("Contact us!") == "contact-us"
    assert slugs.slugify("ފޯމު") == "form"  # Thaana titles fall back
    assert slugs.slugify("Café  menu") == "cafe-menu"


def test_reserved_covers_studio_routes_and_static_paths() -> None:
    """Every top-level studio route and static directory is reserved (nginx.conf, router)."""
    root = Path(__file__).resolve().parents[2] / "frontend"
    nginx = (root / "nginx.conf").read_text(encoding="utf-8")
    for word in ("login", "forms", "settings", "assets", "fonts", "theme-fonts", "api", "v", "a"):
        assert word in slugs.RESERVED
        assert re.search(rf"[/(|]{re.escape(word)}[/|)]", nginx), word
    router = (root / "src" / "router.tsx").read_text(encoding="utf-8")
    for path in ("'/login'", "'/forms'", "'/settings'"):
        assert path in router


async def test_slugs_unique_across_organisations(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    first = (
        await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Survey"})
    ).json()
    other = Organization(name="Other", slug="other")
    db.add(other)
    await db.flush()
    user = await get_user_by_email(db, "admin@example.org")
    assert user is not None
    db.add(OrgMembership(org_id=other.id, user_id=user.id, role=OrgRole.ADMIN))
    await db.commit()
    second = (await client.post(f"/api/v1/orgs/{other.id}/forms", json={"title": "Survey"})).json()
    assert first["slug"] == "survey" and second["slug"] == "survey-2"
    assert second["url"] == f"{settings.public_origin}/survey-2"

    # Renaming onto another organisation's slug is refused.
    res = await client.patch(f"/api/v1/forms/{second['id']}", json={"slug": "survey"})
    assert res.status_code == 409 and res.json()["detail"] == "slug_taken"


async def test_reserved_words_are_refused_and_skipped(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    form = (await client.post(f"/api/v1/orgs/{org}/forms", json={"title": "Login"})).json()
    assert form["slug"] == "login-2"
    res = await client.patch(f"/api/v1/forms/{form['id']}", json={"slug": "settings"})
    assert res.status_code == 422 and res.json()["detail"] == "slug_reserved"
    res = await client.post(f"/api/v1/orgs/{org}/forms", json={"title": "X", "slug": "api"})
    assert res.status_code == 422
    res = await client.post(f"/api/v1/orgs/{org}/forms", json={"title": "X", "slug": "my-x"})
    assert res.status_code == 201 and res.json()["slug"] == "my-x"


async def test_slug_check(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    form = (
        await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Survey"})
    ).json()
    ok = (await client.get("/api/v1/forms/slug-check", params={"slug": "fresh"})).json()
    assert ok["available"] is True and ok["problem"] is None
    taken = (await client.get("/api/v1/forms/slug-check", params={"slug": "survey"})).json()
    assert taken == {
        "slug": "survey",
        "available": False,
        "problem": "taken",
        "suggestion": "survey-2",
        "url": f"{settings.public_origin}/survey-2",
    }
    # A form's own slug is available to itself.
    own = await client.get(
        "/api/v1/forms/slug-check", params={"slug": "survey", "formId": form["id"]}
    )
    assert own.json()["available"] is True
    reserved = (await client.get("/api/v1/forms/slug-check", params={"slug": "forms"})).json()
    assert reserved["problem"] == "reserved" and reserved["suggestion"] == "forms-2"
    bad = (await client.get("/api/v1/forms/slug-check", params={"slug": "Hello World"})).json()
    assert bad["problem"] == "invalid" and bad["suggestion"] == "hello-world"
    client.cookies.clear()
    assert (await client.get("/api/v1/forms/slug-check", params={"slug": "x"})).status_code == 401


async def test_public_form_by_slug_only(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], title="Membership")
    assert pub.base == "/api/v1/public/forms/membership"
    assert (await client.get(pub.base)).status_code == 200
    assert (await client.get("/api/v1/public/forms/no-such-form")).status_code == 404
    assert (await client.get("/api/v1/public/forms/login")).status_code == 404
    # The old two-part API path is gone (old page links are redirected by the web server).
    old = await client.get(f"/api/v1/public/forms/{pub.form['orgSlug']}/membership")
    assert old.status_code == 404


def _migration() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261024_0010_global_form_slugs.py"
    )
    spec = importlib.util.spec_from_file_location("m0010", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_reserved_snapshot_matches() -> None:
    """The migration's snapshot was taken from the live list; it may only lag behind it."""
    assert _migration().RESERVED <= slugs.RESERVED


def test_migration_backfill_suffixes_collisions_and_reserved_words() -> None:
    rows = [(1, "survey"), (2, "survey"), (3, "login"), (4, "survey-2"), (5, "Odd Slug!"), (6, "x")]
    assert _migration().renames(rows) == {
        2: "survey-2",
        3: "login-2",
        4: "survey-2-2",
        5: "odd-slug",
    }


def test_nginx_regexes_with_braces_are_quoted() -> None:
    """nginx reads ``{`` as the start of a block: regexes with ``{0,99}`` must be quoted."""
    nginx = (Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    for line in nginx.splitlines():
        if line.strip().startswith("location ~") and "{0," in line:
            assert '"' in line, line
