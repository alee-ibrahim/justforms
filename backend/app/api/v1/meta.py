"""``GET /api/v1/meta``: version and enabled features, used by the SPA at start-up."""

from urllib.parse import urlsplit

from fastapi import APIRouter

from app import __version__
from app.api.v1.common import ApiModel
from app.auth.deps import SettingsDep
from app.config import Settings, parse_dsn

router = APIRouter(tags=["meta"])


class Features(ApiModel):
    ai: bool
    # The model can read images ("Start from a paper form").
    ai_vision: bool = False
    # Who receives what the AI is sent (named in the paper-form dialog).
    oidc: bool
    # Signed-out visitors go straight to the IdP (JUSTFORMS_OIDC_AUTO_REDIRECT).
    oidc_auto_redirect: bool = False
    local_login: bool
    # A demo sign-in code is configured (JUSTFORMS_DEMO_LOGIN_CODE): the sign-in page says so.
    demo: bool = False
    # Email notifications can be sent (JUSTFORMS_SMTP_HOST is set).
    email: bool
    # CAPTCHA provider for forms that turn spam protection on ("none": not available).
    captcha: str
    captcha_busy_threshold: int


class Telemetry(ApiModel):
    """Browser error reporting. Reports go through the same-origin tunnel, so the DSN's host
    is this install's own (the real error tracker's address is never sent to browsers)."""

    dsn: str
    tunnel: str = "/api/v1/telemetry/envelope"
    environment: str
    release: str
    traces_sample_rate: float = 0.0


def browser_telemetry(settings: Settings) -> Telemetry | None:
    dsn = parse_dsn(settings.sentry_browser) if settings.sentry_browser else None
    if dsn is None:
        return None
    public = urlsplit(settings.public_url)
    scheme, host = public.scheme or "https", public.netloc or "localhost"
    return Telemetry(
        dsn=f"{scheme}://{dsn.public_key}@{host}/{dsn.project_id}",
        environment=settings.sentry_environment or settings.environment,
        release=__version__,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )


class Meta(ApiModel):
    version: str
    features: Features
    thaana_font_css_url: str
    # Days deleted forms and submissions stay restorable (JUSTFORMS_TRASH_DAYS).
    trash_days: int = 30
    # Error reporting from browsers; null when off.
    telemetry: Telemetry | None = None


@router.get("/meta", response_model=Meta)
async def meta(settings: SettingsDep) -> Meta:
    return Meta(
        version=__version__,
        features=Features(
            ai=settings.ai_enabled,
            ai_vision=settings.ai_vision_enabled,
            oidc=settings.oidc_enabled,
            oidc_auto_redirect=settings.oidc_enabled and settings.oidc_auto_redirect,
            local_login=settings.local_login_enabled,
            demo=settings.demo_login_enabled,
            email=settings.smtp_enabled,
            captcha=settings.captcha_provider,
            captcha_busy_threshold=settings.captcha_busy_threshold,
        ),
        thaana_font_css_url=settings.thaana_font_css_url,
        trash_days=settings.trash_days,
        telemetry=browser_telemetry(settings),
    )
