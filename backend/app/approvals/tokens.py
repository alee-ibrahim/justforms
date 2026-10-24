"""Approver session tokens.

An approver opens the emailed link, then confirms the address with a one-time code (the same
machinery as respondent codes, ``app.auth.respondent``, keyed by the step). A correct code
gives a short-lived JWT (HS256, key derived from the app secret) bound to the step and to the
current link, so sending the email again (a new link) also ends earlier sessions.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from app.config import Settings

AUDIENCE = "justforms-approver"


def _key(settings: Settings) -> OctKey:
    raw = hashlib.sha256(b"justforms:approver-token:" + settings.secret_key_bytes).digest()
    return OctKey.import_key(raw)


def issue(settings: Settings, step_id: uuid.UUID, email: str, link_hash: str) -> str:
    now = int(time.time())
    claims = {
        "aud": AUDIENCE,
        "step_id": str(step_id),
        "email": email,
        "link": link_hash[:32],
        "iat": now,
        "exp": now + settings.respondent_token_seconds,
    }
    return jwt.encode({"alg": "HS256"}, claims, _key(settings))


def check(settings: Settings, token: str, step_id: uuid.UUID, link_hash: str | None) -> bool:
    if not link_hash:
        return False
    try:
        decoded = jwt.decode(token, _key(settings), algorithms=["HS256"])
        jwt.JWTClaimsRegistry(
            aud={"essential": True, "value": AUDIENCE},
            exp={"essential": True},
            step_id={"essential": True, "value": str(step_id)},
            link={"essential": True, "value": link_hash[:32]},
        ).validate(decoded.claims)
    except (JoseError, ValueError):
        return False
    return True
