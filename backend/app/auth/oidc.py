"""OIDC login for staff, backend-for-frontend style (DESIGN section 8.1).

The API is a confidential client: it builds the authorize redirect (state, nonce, PKCE S256
kept in Redis for 10 minutes), exchanges the code server-side and validates the ID token
(signature via JWKS, issuer, audience, nonce, expiry). No token ever reaches the browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from redis.asyncio import Redis

from app.config import Settings

STATE_TTL_SECONDS = 600
METADATA_TTL_SECONDS = 3600
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384", "EdDSA"]


class OIDCError(Exception):
    """Any failure in the login flow; the message is safe to log, never shown verbatim."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# Where people land after signing in without a ``next``: the studio home. Not "/": a browser
# can hold a cached redirect for "/" from an app that used the hostname before.
DEFAULT_NEXT = "/forms"


def safe_next(value: str | None) -> str:
    """Only allow same-origin relative paths as post-login redirects."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return DEFAULT_NEXT
    return value


class OIDCClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=10, follow_redirects=False)
        self._metadata: dict[str, Any] | None = None
        self._metadata_at = 0.0
        self._jwks: KeySet | None = None

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.public_origin}/api/v1/auth/callback"

    @property
    def issuer(self) -> str:
        assert self.settings.oidc_issuer
        return self.settings.oidc_issuer.rstrip("/")

    async def metadata(self) -> dict[str, Any]:
        if self._metadata is None or time.time() - self._metadata_at > METADATA_TTL_SECONDS:
            url = (
                self.settings.oidc_discovery_url
                or f"{self.issuer}/.well-known/openid-configuration"
            )
            try:
                res = await self.http.get(url)
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise OIDCError(f"discovery failed: {exc}") from exc
            self._metadata = res.json()
            self._metadata_at = time.time()
            self._jwks = None
        return self._metadata

    async def jwks(self, *, refresh: bool = False) -> KeySet:
        if self._jwks is None or refresh:
            meta = await self.metadata()
            try:
                res = await self.http.get(meta["jwks_uri"])
                res.raise_for_status()
            except (httpx.HTTPError, KeyError) as exc:
                raise OIDCError(f"jwks fetch failed: {exc}") from exc
            self._jwks = KeySet.import_key_set(res.json())
        return self._jwks

    async def start(
        self, redis: Redis, next_path: str | None, login_hint: str | None = None
    ) -> str:
        """Create login state and return the IdP authorize URL.

        ``login_hint`` (an invited address) pre-fills the IdP's account picker where supported.
        """
        meta = await self.metadata()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        await redis.set(
            f"oidc_state:{state}",
            json.dumps({"nonce": nonce, "verifier": verifier, "next": safe_next(next_path)}),
            ex=STATE_TTL_SECONDS,
        )
        params = {
            "response_type": "code",
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.settings.oidc_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{meta['authorization_endpoint']}?{urlencode(params)}"

    async def finish(self, redis: Redis, code: str, state: str) -> tuple[dict[str, Any], str, str]:
        """Exchange the code; return (validated ID token claims, raw id_token, next path)."""
        raw = await redis.getdel(f"oidc_state:{state}")
        if raw is None:
            raise OIDCError("unknown or expired state")
        stored = json.loads(raw)
        meta = await self.metadata()
        secret = self.settings.oidc_client_secret
        try:
            res = await self.http.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": stored["verifier"],
                    "client_id": self.settings.oidc_client_id,
                },
                auth=httpx.BasicAuth(self.settings.oidc_client_id, secret.get_secret_value())
                if secret
                else httpx.USE_CLIENT_DEFAULT,
            )
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise OIDCError(f"token exchange failed: {exc}") from exc
        id_token = res.json().get("id_token")
        if not id_token:
            raise OIDCError("token response has no id_token")
        claims = await self.validate_id_token(id_token, stored["nonce"])
        return claims, id_token, stored["next"]

    async def validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        keys = await self.jwks()
        try:
            try:
                token = jwt.decode(id_token, keys, algorithms=ID_TOKEN_ALGORITHMS)
            except (JoseError, ValueError):
                # Key rotation: refetch the JWKS once.
                keys = await self.jwks(refresh=True)
                token = jwt.decode(id_token, keys, algorithms=ID_TOKEN_ALGORITHMS)
            registry = jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self.issuer},
                sub={"essential": True},
                exp={"essential": True},
                nonce={"essential": True, "value": nonce},
            )
            registry.validate(token.claims)
        except (JoseError, ValueError) as exc:
            raise OIDCError(f"invalid id_token: {exc}") from exc
        aud = token.claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if self.settings.oidc_client_id not in audiences:
            raise OIDCError("id_token audience mismatch")
        return dict(token.claims)

    async def end_session_url(self, id_token: str | None) -> str | None:
        try:
            meta = await self.metadata()
        except OIDCError:
            return None
        endpoint = meta.get("end_session_endpoint")
        if not endpoint:
            return None
        params = {"post_logout_redirect_uri": f"{self.settings.public_origin}/login"}
        if id_token:
            params["id_token_hint"] = id_token
        else:
            params["client_id"] = self.settings.oidc_client_id
        return f"{endpoint}?{urlencode(params)}"


_client: OIDCClient | None = None


def get_oidc_client(settings: Settings) -> OIDCClient:
    global _client
    if _client is None or _client.settings is not settings:
        _client = OIDCClient(settings)
    return _client
