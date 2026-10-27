"""Security headers on every API response (DESIGN 14.4).

API responses are JSON or file downloads, never pages, so the policy is as strict as it gets.
Responses that set their own ``Content-Security-Policy`` (image previews) keep it. The pages
themselves get their headers from nginx (``frontend/nginx.conf``).

Caching: responses of staff routes (everything outside ``/api/v1/public/``), of public routes
called with a bearer token, and of token links (approver, verify) are ``Cache-Control:
no-store``, whatever the route set: they hold personal data, and presigned download redirects
must not be cached past their expiry. Other public responses called with a session cookie get
``no-store`` unless the route chose its own caching (logos, theme files).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.sessions import SESSION_COOKIE, SESSION_COOKIE_HOST

HEADERS: dict[bytes, bytes] = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
    b"x-frame-options": b"DENY",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'; sandbox",
    b"cross-origin-resource-policy": b"same-origin",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
}


PUBLIC_PREFIX = "/api/v1/public/"
TOKEN_PREFIXES = ("/api/v1/public/approvals/", "/api/v1/public/verify/")
_COOKIES = (SESSION_COOKIE.encode(), SESSION_COOKIE_HOST.encode())


def _cache_policy(scope: Scope) -> str | None:
    """ "force" (always no-store), "default" (no-store unless the route set caching), or None."""
    path: str = scope.get("path", "")
    if not path.startswith("/api/"):
        return None
    if not path.startswith(PUBLIC_PREFIX) or path.startswith(TOKEN_PREFIXES):
        return "force"
    headers = dict(scope.get("headers") or [])
    if headers.get(b"authorization"):
        return "force"
    cookie = headers.get(b"cookie", b"")
    if any(name + b"=" in cookie for name in _COOKIES):
        return "default"
    return None


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        policy = _cache_policy(scope)

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _v in headers}
                headers += [(k, v) for k, v in HEADERS.items() if k not in present]
                if policy == "force" or (policy == "default" and b"cache-control" not in present):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)
