import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.config import get_settings
from app.security import SecurityHeadersMiddleware

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if os.environ.get("FORWARDED_ALLOW_IPS", "").strip() == "*":
        # uvicorn would take the left-most X-Forwarded-For hop, which the client writes.
        message = (
            "FORWARDED_ALLOW_IPS='*' lets any client choose its IP address (rate limits, audit "
            "and signature records). Set it to the web container's addresses, the same as "
            "JUSTFORMS_TRUSTED_PROXIES."
        )
        if settings.environment == "production":
            raise RuntimeError(message)
        log.warning(message)
    if settings.demo_login_code is not None:
        if settings.demo_login_enabled:
            log.warning(
                "DEMO LOGIN ENABLED: JUSTFORMS_DEMO_LOGIN_CODE signs in %d allow-listed "
                "address(es) without an emailed code. Demo instances only; unset it on a real "
                "install.",
                len(settings.demo_login_emails),
            )
        else:
            log.warning("JUSTFORMS_DEMO_LOGIN_CODE is set but ignored: OIDC sign-in is configured")
    if settings.oidc_member_groups and not settings.oidc_creator_groups:
        log.warning(
            "JUSTFORMS_OIDC_MEMBER_GROUPS now maps to the member role, which can't create "
            "forms. Put groups whose people create forms in JUSTFORMS_OIDC_CREATOR_GROUPS."
        )
    app = FastAPI(
        title="JustForms API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(api_router)
    return app


app = create_app()
