"""``GET /api/v1/meta``: version and enabled features, used by the SPA at start-up."""

from fastapi import APIRouter

from app import __version__
from app.api.v1.common import ApiModel
from app.auth.deps import SettingsDep

router = APIRouter(tags=["meta"])


class Features(ApiModel):
    ai: bool
    # The model can read images ("Start from a paper form").
    ai_vision: bool = False
    # Who receives what the AI is sent (named in the paper-form dialog).
    ai_provider_label: str = ""
    oidc: bool
    local_login: bool
    # A demo sign-in code is configured (JUSTFORMS_DEMO_LOGIN_CODE): the sign-in page says so.
    demo: bool = False
    # Email notifications can be sent (JUSTFORMS_SMTP_HOST is set).
    email: bool
    # CAPTCHA provider for forms that turn spam protection on ("none": not available).
    captcha: str
    captcha_busy_threshold: int


class Meta(ApiModel):
    version: str
    features: Features
    thaana_font_css_url: str


@router.get("/meta", response_model=Meta)
async def meta(settings: SettingsDep) -> Meta:
    return Meta(
        version=__version__,
        features=Features(
            ai=settings.ai_enabled,
            ai_vision=settings.ai_vision_enabled,
            ai_provider_label=settings.ai_label,
            oidc=settings.oidc_enabled,
            local_login=settings.local_login_enabled,
            demo=settings.demo_login_enabled,
            email=settings.smtp_enabled,
            captcha=settings.captcha_provider,
            captcha_busy_threshold=settings.captcha_busy_threshold,
        ),
        thaana_font_css_url=settings.thaana_font_css_url,
    )
