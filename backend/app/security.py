"""Security headers on every API response (DESIGN 14.4).

API responses are JSON or file downloads, never pages, so the policy is as strict as it gets.
Responses that set their own ``Content-Security-Policy`` (image previews) keep it. The pages
themselves get their headers from nginx (``frontend/nginx.conf``).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS: dict[bytes, bytes] = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
    b"x-frame-options": b"DENY",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'; sandbox",
    b"cross-origin-resource-policy": b"same-origin",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _v in headers}
                headers += [(k, v) for k, v in HEADERS.items() if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)
