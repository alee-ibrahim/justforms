"""OIDC login against a fake IdP (httpx MockTransport, real RS256-signed ID tokens)."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import auth as auth_api
from app.auth.oidc import OIDCClient, safe_next
from app.config import Settings, get_settings
from app.models import OrgMembership, OrgRole, User

ISSUER = "https://idp.example.org/realms/test"
CLIENT_ID = "justforms"


class FakeIdP:
    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        self.signing_key = self.key
        self.claims: dict[str, Any] = {}
        self.nonce: str | None = None
        self.token_requests: list[dict[str, list[str]]] = []

    def id_token(self, **override: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "user-123",
            "email": "Staff@Example.org",
            "name": "Staff Member",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            **self.claims,
            **override,
        }
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, self.signing_key)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/certs",
                    "end_session_endpoint": f"{ISSUER}/logout",
                },
            )
        if url.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if url.endswith("/token"):
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            return httpx.Response(200, json={"access_token": "x", "id_token": self.id_token()})
        return httpx.Response(404)


@pytest.fixture
def oidc_settings() -> Settings:
    return Settings(
        environment="test",
        public_url="http://testserver",
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="test-secret",
        oidc_admin_groups=["justforms-admins"],
        oidc_member_groups=["justforms-users"],
    )


@pytest.fixture
def idp(app: Any, oidc_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakeIdP:
    fake = FakeIdP()
    client = OIDCClient(
        oidc_settings, httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    monkeypatch.setattr(auth_api, "get_oidc_client", lambda _settings: client)
    app.dependency_overrides[get_settings] = lambda: oidc_settings
    return fake


async def _start(client: AsyncClient, idp: FakeIdP, next_path: str = "/forms") -> str:
    res = await client.get("/api/v1/auth/login", params={"next": next_path})
    assert res.status_code == 302
    location = urlparse(res.headers["location"])
    query = parse_qs(location.query)
    assert location.path == "/realms/test/auth"
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://testserver/api/v1/auth/callback"]
    idp.nonce = query["nonce"][0]
    return query["state"][0]


async def test_oidc_login_creates_user_with_mapped_role(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession
) -> None:
    idp.claims = {"groups": ["justforms-admins"]}
    state = await _start(client, idp)
    res = await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert res.status_code == 302
    assert res.headers["location"] == "/forms"
    assert "justforms_session" in client.cookies
    # PKCE verifier and client auth were sent to the token endpoint.
    assert idp.token_requests[0]["code_verifier"]

    me = (await client.get("/api/v1/auth/me")).json()
    assert me["email"] == "staff@example.org"
    assert me["displayName"] == "Staff Member"
    assert me["orgs"][0]["role"] == "admin"

    # Local login is disabled while OIDC is configured.
    res = await client.post("/api/v1/auth/local/request", json={"email": "staff@example.org"})
    assert res.status_code == 404

    # State is single use.
    res = await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert res.headers["location"] == "/login?error=sso_failed"


async def test_user_without_mapped_group_gets_no_org_role(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession
) -> None:
    idp.claims = {"groups": ["someone-else"]}
    state = await _start(client, idp)
    await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    user = await db.scalar(select(User).where(User.email == "staff@example.org"))
    assert user is not None and user.oidc_subject == "user-123"
    assert await db.scalar(select(OrgMembership).where(OrgMembership.user_id == user.id)) is None
    assert (await client.get("/api/v1/auth/me")).json()["orgs"] == []


async def test_member_group(client: AsyncClient, idp: FakeIdP) -> None:
    idp.claims = {"groups": ["justforms-users"]}
    state = await _start(client, idp)
    await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert (await client.get("/api/v1/auth/me")).json()["orgs"][0]["role"] == OrgRole.MEMBER


async def test_creator_group(client: AsyncClient, idp: FakeIdP, oidc_settings: Settings) -> None:
    oidc_settings.oidc_creator_groups = ["justforms-builders"]
    idp.claims = {"groups": ["justforms-users", "justforms-builders"]}
    await _sign_in(client, idp)
    assert (await client.get("/api/v1/auth/me")).json()["orgs"][0]["role"] == "creator"


async def _sign_in(client: AsyncClient, idp: FakeIdP) -> None:
    state = await _start(client, idp)
    res = await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert res.status_code == 302 and res.headers["location"] == "/forms", res.headers


async def _invite(db: AsyncSession, email: str, role: OrgRole, slug: str = "default") -> Any:
    from datetime import UTC, datetime, timedelta

    from app.models import Organization, OrgInvitation

    org = await db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        org = Organization(name=slug.title(), slug=slug)
        db.add(org)
        await db.flush()
    inv = OrgInvitation(
        org_id=org.id,
        email=email,
        role=role,
        expires_at=datetime.now(UTC) + timedelta(days=14),
        form_grants=[],
    )
    db.add(inv)
    await db.commit()
    return org


async def test_invitation_accepted_at_oidc_sign_in(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession
) -> None:
    # Invited (lower case) to another organisation; the IdP sends the address in mixed case.
    # The IdP groups map nothing for this person.
    org = await _invite(db, "staff@example.org", OrgRole.CREATOR, slug="second")
    idp.claims = {"groups": ["someone-else"]}
    await _sign_in(client, idp)
    orgs = (await client.get("/api/v1/auth/me")).json()["orgs"]
    assert [(o["id"], o["role"]) for o in orgs] == [(str(org.id), "creator")]


async def test_invited_membership_survives_group_mapping(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession
) -> None:
    await _invite(db, "staff@example.org", OrgRole.MEMBER)
    idp.claims = {"groups": []}
    await _sign_in(client, idp)
    assert [o["role"] for o in (await client.get("/api/v1/auth/me")).json()["orgs"]] == ["member"]
    # Next sign-in, still in no mapped group: an admin's invitation isn't undone by the IdP.
    await _sign_in(client, idp)
    assert [o["role"] for o in (await client.get("/api/v1/auth/me")).json()["orgs"]] == ["member"]


async def test_unverified_email_does_not_accept(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession
) -> None:
    await _invite(db, "staff@example.org", OrgRole.ADMIN, slug="second")
    idp.claims = {"groups": [], "email_verified": False}
    await _sign_in(client, idp)
    assert (await client.get("/api/v1/auth/me")).json()["orgs"] == []


async def test_without_group_mapping_new_people_join_once(
    client: AsyncClient, idp: FakeIdP, db: AsyncSession, oidc_settings: Settings
) -> None:
    oidc_settings.oidc_admin_groups = []
    oidc_settings.oidc_member_groups = []
    await _sign_in(client, idp)
    me = (await client.get("/api/v1/auth/me")).json()
    assert [o["role"] for o in me["orgs"]] == ["creator"]
    # Removed by an admin: not added back at the next sign-in.
    user = await db.scalar(select(User).where(User.email == "staff@example.org"))
    assert user is not None
    membership = await db.scalar(select(OrgMembership).where(OrgMembership.user_id == user.id))
    assert membership is not None and membership.idp_managed
    await db.delete(membership)
    await db.commit()
    await _sign_in(client, idp)
    assert (await client.get("/api/v1/auth/me")).json()["orgs"] == []


async def test_default_role_none(
    client: AsyncClient, idp: FakeIdP, oidc_settings: Settings
) -> None:
    oidc_settings.oidc_admin_groups = []
    oidc_settings.oidc_member_groups = []
    oidc_settings.oidc_default_role = "none"
    await _sign_in(client, idp)
    assert (await client.get("/api/v1/auth/me")).json()["orgs"] == []


@pytest.mark.parametrize(
    "override",
    [
        {"nonce": "wrong"},
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 600},
    ],
)
async def test_bad_id_tokens_are_rejected(
    client: AsyncClient, idp: FakeIdP, override: dict[str, Any]
) -> None:
    idp.claims = override
    state = await _start(client, idp)
    res = await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert res.headers["location"] == "/login?error=sso_failed"
    assert "justforms_session" not in client.cookies


async def test_token_signed_by_unpublished_key_is_rejected(
    client: AsyncClient, idp: FakeIdP
) -> None:
    state = await _start(client, idp)
    idp.signing_key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    res = await client.get("/api/v1/auth/callback", params={"code": "abc", "state": state})
    assert res.headers["location"] == "/login?error=sso_failed"


def test_safe_next() -> None:
    assert safe_next("/forms/1") == "/forms/1"
    assert safe_next("//evil.example") == "/"
    assert safe_next("https://evil.example") == "/"
    assert safe_next("/\\evil") == "/"
    assert safe_next(None) == "/"
