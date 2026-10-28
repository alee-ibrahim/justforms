"""``POST /api/v1/telemetry/envelope``: the browser error-report tunnel (app.telemetry.tunnel).

No cookies or session are read, and nothing is stored: the cleaned envelope goes to the
configured error tracker or nowhere. 404 when browser error reporting or the tunnel is off.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from app import ratelimit
from app.auth.deps import RedisDep, SettingsDep
from app.config import parse_dsn
from app.net import client_ip
from app.telemetry import tunnel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


async def _body(request: Request) -> bytes:
    if request.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_encoding")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > tunnel.MAX_ENVELOPE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > tunnel.MAX_ENVELOPE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    return bytes(data)


@router.post("/envelope")
async def envelope(request: Request, redis: RedisDep, settings: SettingsDep) -> Response:
    target = settings.sentry_browser if settings.sentry_browser_tunnel else None
    dsn = parse_dsn(target) if target else None
    if dsn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    await ratelimit.enforce(
        redis, settings, "telemetry_envelope", client_ip(request, settings) or "-"
    )
    data = await _body(request)
    try:
        cleaned = tunnel.clean_envelope(data, dsn)
    except tunnel.EnvelopeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_envelope") from exc
    if cleaned.items == 0:
        return Response(status_code=status.HTTP_200_OK)
    try:
        upstream = await tunnel.forward(cleaned, dsn)
    except httpx.HTTPError as exc:
        log.warning("error tracker unreachable: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "upstream_unreachable") from exc
    if upstream == status.HTTP_429_TOO_MANY_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_requests")
    if upstream >= 300:
        log.warning("error tracker answered %d", upstream)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "upstream_error")
    return Response(status_code=status.HTTP_200_OK)
