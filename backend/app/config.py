"""Application settings, loaded from environment variables (prefix ``JUSTFORMS_``)."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger(__name__)

# Only used outside production when JUSTFORMS_SECRET_KEY is unset. Not a secret: production
# refuses to start without a real key.
_DEV_SECRET_KEY = "justforms-insecure-development-key"
# Production refuses shorter keys and the placeholders shipped in examples.
MIN_SECRET_KEY_BYTES = 32
_PLACEHOLDER_SECRET_PREFIXES = ("change-me", "changeme", "replace-me", "your-secret")


def _csv(value: object) -> object:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


CsvList = Annotated[list[str], NoDecode]

# Thaana fonts a form theme offers by default (JUSTFORMS_THAANA_FONTS).
DEFAULT_THAANA_FONTS = (
    "Faruma",
    "MV Faseyha",
    "MV A Waheed",
    "MV Typewriter",
    "MV Lhohi",
    "MV Ilham",
    "MV Elaaf",
    "MV Iyyu Formal",
    "Bolhu",
    "Kolhu",
    "Fanara",
    "Hawwa",
    "Gurafiku",
    "Haluvidhaa",
)


@dataclass(frozen=True)
class Dsn:
    """A Sentry DSN: ``scheme://public_key@host[:port][/prefix]/project_id``."""

    scheme: str
    public_key: str
    netloc: str  # host[:port], no credentials
    prefix: str  # path before the project id, "" or "/something"
    project_id: str

    @property
    def envelope_url(self) -> str:
        return f"{self.scheme}://{self.netloc}{self.prefix}/api/{self.project_id}/envelope/"


def parse_dsn(value: str) -> Dsn | None:
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    path = parts.path.rstrip("/")
    prefix, _, project = path.rpartition("/")
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or not parts.username
        or not project.isdigit()
        or parts.query
        or parts.fragment
    ):
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    netloc = f"{host}:{port}" if port else host
    return Dsn(parts.scheme, parts.username, netloc, prefix, project)


def weak_code(code: str) -> bool:
    """True for 6-digit codes people guess first: one digit, runs, repeated short patterns."""
    digits = [int(c) for c in code]
    steps = {b - a for a, b in pairwise(digits)}
    if len(steps) == 1 and steps <= {-1, 0, 1}:
        return True  # 000000, 123456, 654321
    if code[:3] == code[3:] or code[:2] * 3 == code:
        return True  # 123123, 121212
    if code[:3] == code[3:][::-1]:
        return True  # 123321
    return code in {"159753", "147258", "102030", "112233", "696969", "131313", "142536"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JUSTFORMS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    # Public base URL of the app (scheme://host[:port]); used for redirects and Origin checks.
    public_url: str = "http://localhost:5173"
    # Signs respondent tokens and keys HMACs of one-time codes. Required in production.
    secret_key: SecretStr | None = None

    # Postgres (async driver). Example: postgresql+asyncpg://user:pass@host:5432/db
    database_url: str = "postgresql+asyncpg://justforms:justforms@localhost:5432/justforms"

    # Redis: sessions, one-time codes, OIDC state, arq queue.
    redis_url: str = "redis://localhost:6379/0"

    # -- sessions ---------------------------------------------------------------------------
    session_idle_seconds: int = Field(default=8 * 3600, ge=60)
    session_absolute_seconds: int = Field(default=7 * 24 * 3600, ge=60)
    # Secure cookie flag; defaults to on in production. Secure cookies get the __Host- prefix.
    cookie_secure: bool | None = None
    # Interactive API docs (/api/docs, /api/redoc) and the OpenAPI document. Unset: on outside
    # production, off in production.
    api_docs: bool | None = None

    # -- staff login ------------------------------------------------------------------------
    # OIDC (e.g. Entra ID, Keycloak). When the issuer is set, local email-code login is off.
    oidc_issuer: str | None = None
    # Optional discovery URL the backend fetches when the issuer URL is not reachable from
    # the backend (e.g. Keycloak in Docker); defaults to {issuer}/.well-known/openid-configuration.
    oidc_discovery_url: str | None = None
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid email profile"
    oidc_groups_claim: str = "groups"
    # IdP groups mapped to roles in the default organisation at sign-in (comma-separated):
    # admin > creator (can create forms) > member (only forms shared with them).
    oidc_admin_groups: CsvList = Field(default_factory=list)
    oidc_creator_groups: CsvList = Field(default_factory=list)
    oidc_member_groups: CsvList = Field(default_factory=list)
    # IdP groups whose people are superadmins (every organisation and instance settings),
    # checked at each sign-in, independently of the role mapping above. Exact strings: group
    # names or IDs, whatever the groups claim carries. When set, people no longer in a listed
    # group lose superadmin at sign-in, unless it was granted locally (create-admin).
    oidc_superadmin_groups: CsvList = Field(default_factory=list)
    # Without group mapping: the role someone gets in the default organisation the first time
    # they sign in with OIDC, or "none" (people join only by invitation).
    oidc_default_role: Literal["creator", "member", "none"] = "creator"
    # With OIDC on, the sign-in page (and any studio page while signed out) goes straight to
    # the IdP without a button press. Never right after signing out or a failed sign-in.
    oidc_auto_redirect: bool = True
    # Accounts are matched by email only when the IdP vouches for the address: the ID token has
    # email_verified=true, or this is on. Turn it on only for an IdP whose email claim users
    # can't set themselves, e.g. a single-tenant Microsoft Entra ID (which sends no
    # email_verified) where administrators manage addresses. Never for multi-tenant or guest
    # sign-in, or an IdP where people edit their own email.
    oidc_trust_email: bool = False
    # Claims read for the email when the ID token has no "email" claim, in order (e.g.
    # "preferred_username" or "upn" for Entra ID accounts without a mailbox). Addresses from
    # these count as verified only with JUSTFORMS_OIDC_TRUST_EMAIL. Empty: "email" only.
    oidc_email_fallback_claims: CsvList = Field(default_factory=list)

    # Local email-code login (only when OIDC is not configured).
    login_code_ttl_seconds: int = Field(default=600, ge=60)
    login_code_max_attempts: int = Field(default=5, ge=1)
    # DEMO INSTANCES ONLY. A fixed 6-digit code that also signs in the listed addresses
    # (exact, comma-separated; required). Sign-in still goes through "email me a code" and
    # its limits. Off by default; never set it on a real install.
    demo_login_code: SecretStr | None = None
    demo_login_emails: CsvList = Field(default_factory=list)

    # The organisation new users join (self-hosters normally run one).
    default_org_name: str = "JustForms"
    default_org_slug: str = "default"

    # -- email (sent by the worker) ---------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "JustForms <no-reply@localhost>"
    smtp_security: Literal["none", "starttls", "tls"] = "starttls"

    # -- file storage -----------------------------------------------------------------------
    #   local: files on a directory / mounted volume (default, no extra services).
    #   s3:    any external S3-compatible service, configured with the JUSTFORMS_S3_* vars.
    storage_backend: Literal["local", "s3"] = "local"
    # Root directory for the local backend. Relative paths resolve against the working dir;
    # the Docker image sets /data/storage and expects a volume there.
    storage_local_path: Path = Path("data/storage")

    # S3 backend only. Leave the endpoint empty for AWS S3.
    s3_endpoint_url: str | None = None
    # Endpoint put into presigned upload/download URLs, for when browsers reach the service at
    # another address than the backend does (e.g. the backend uses an internal service name and
    # browsers a public hostname). Empty: presigned URLs use s3_endpoint_url.
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # "path" for most self-hosted services, "virtual" for AWS/R2, "auto" lets botocore decide.
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"

    # Global cap on a single uploaded file, in megabytes.
    max_upload_mb: int = Field(default=25, ge=1)
    # How long a started upload may take before its upload URL/token expires.
    upload_url_ttl_seconds: int = Field(default=900, ge=60)
    # Uploads never attached to a submission are purged after this many hours.
    pending_upload_ttl_hours: int = Field(default=24, ge=1)
    # Jotform API key for `justforms fetch-imported-files` (files behind imported links need
    # it). Read from the environment for that run only; never stored or logged.
    jotform_api_key: SecretStr | None = None
    # With a key, submission imports take each row's exact submit time from Jotform's API
    # (the export file only has dates). Jotform reports API times in US Eastern time.
    jotform_api_region: Literal["us", "eu", "hipaa"] = "us"
    jotform_api_timezone: str = "America/New_York"

    # Time zone for dates staff see in exports and PDFs, and for "today" in date limits.
    timezone: str = "UTC"

    # Proxies (IPs or CIDRs, comma-separated) whose X-Forwarded-For is trusted for the
    # client IP recorded with submissions and signatures. Empty: use the peer address.
    trusted_proxies: CsvList = Field(default_factory=list)

    # -- signed PDFs ------------------------------------------------------------------------
    # By default each install signs with its own self-signed key, created on first use and
    # stored encrypted with JUSTFORMS_SECRET_KEY. To sign with an organisation certificate
    # instead, mount a PKCS#12 file and set its path and password.
    pdf_signing_p12: Path | None = None
    pdf_signing_p12_password: SecretStr | None = None
    # Optional RFC 3161 timestamp authority (PAdES-B-T).
    pdf_tsa_url: str | None = None
    # Name in the self-signed certificate's subject.
    pdf_signer_name: str = "JustForms document signing"

    # -- fonts ------------------------------------------------------------------------------
    # Stylesheet that provides Faruma (the Thaana face Dhivehi readers expect). Loaded at
    # runtime by the studio and the public form; Faruma files are never shipped with JustForms.
    # Default: the public dvfonts CDN (a third party sees respondents' IP addresses). Set it to
    # a self-hosted copy (e.g. /fonts/faruma.css) or to an empty string to disable; Noto Sans
    # Thaana (bundled) is always the fallback.
    thaana_font_css_url: str = "https://dvfonts.yashau.com/css2?family=Faruma&display=swap"
    # Thaana fonts a form theme can choose (family names; the first is the default). With a
    # css2-style font service as JUSTFORMS_THAANA_FONT_CSS_URL (the default) each family loads
    # from it when a form uses it; with a self-hosted stylesheet, list only families your
    # /fonts/fonts.css provides. Noto Sans Thaana (bundled) is always offered.
    thaana_fonts: CsvList = Field(default_factory=lambda: list(DEFAULT_THAANA_FONTS))
    # Thaana TrueType/OpenType font for server-side rendering (signed PDFs, link-preview
    # images), e.g. a licensed Faruma mounted into the container. Empty: the bundled Noto Sans
    # Thaana. Checked at first use (Thaana coverage; for PDFs, embedding permissions); an
    # unusable file falls back to the bundled face with a warning. The bold file is optional
    # (the regular one is used for bold text when it is not set).
    thaana_font_file: str = ""
    thaana_font_bold_file: str = ""

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"JUSTFORMS_TIMEZONE {value!r} is not a known time zone") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @field_validator("thaana_font_css_url")
    @classmethod
    def _font_css_url(cls, value: str) -> str:
        value = value.strip()
        if value and not (value.startswith("https://") or value.startswith("/")):
            raise ValueError("JUSTFORMS_THAANA_FONT_CSS_URL must be an https:// URL or a /path")
        return value

    # -- respondent access (DESIGN 8.2) ------------------------------------------------------
    respondent_code_ttl_seconds: int = Field(default=600, ge=60)
    respondent_code_max_attempts: int = Field(default=5, ge=1)
    # Lockout for every emailed code (staff login per address, respondent codes per form and
    # address, approver codes per step): after this many wrong guesses within
    # code_lockout_seconds, codes are refused until the window passes, whatever codes are
    # requested in between. Bounds guessing to a few dozen tries a day.
    code_lockout_failures: int = Field(default=10, ge=1)
    code_lockout_seconds: int = Field(default=86400, ge=60)
    # Lifetime of the respondent token issued after a correct code.
    respondent_token_seconds: int = Field(default=2 * 3600, ge=300)
    # Approvals: how long an approver's emailed link works (sending it again makes a new one).
    approval_link_days: int = Field(default=14, ge=1, le=365)
    # How long an invitation to join an organisation stays open (a resend restarts it).
    invite_days: int = Field(default=14, ge=1, le=365)
    # Deleted forms and submissions stay in the trash (restorable) this many days, then the
    # nightly job erases them with their files (DESIGN 14.5).
    trash_days: int = Field(default=30, ge=1, le=3650)

    # -- abuse controls (DESIGN 14.1, 14.2) ---------------------------------------------------
    rate_limit_enabled: bool = True
    # Overrides of the built-in limits, e.g. "public_submit=20/60,upload_init=60/60"
    # (name=count/seconds). Names are listed in app/ratelimit.py.
    rate_limits: CsvList = Field(default_factory=list)
    # CAPTCHA: none (default), altcha (built-in proof of work, no third party), turnstile or
    # hcaptcha. Forms choose off / always / when busy.
    captcha_provider: Literal["none", "altcha", "turnstile", "hcaptcha"] = "none"
    captcha_site_key: str = ""
    captcha_secret_key: SecretStr | None = None
    # "When busy": the check turns on after this many responses to one form in an hour.
    captcha_busy_threshold: int = Field(default=1000, ge=1)
    # Proof-of-work difficulty for altcha (largest secret number).
    altcha_max_number: int = Field(default=100_000, ge=1000)
    # Receipts to typed (unconfirmed) addresses, for forms that opt in: at most this many per
    # form an hour (each address also gets at most 3 an hour per form). 0 = none.
    receipt_unverified_per_hour: int = Field(default=100, ge=0)

    # -- webhooks (DESIGN 11.2) ----------------------------------------------------------------
    # Private, loopback and link-local addresses are refused unless inside one of these
    # ranges (comma-separated CIDRs). Plain http is only allowed to these ranges.
    webhook_allowed_cidrs: CsvList = Field(default_factory=list)
    webhook_timeout_seconds: float = Field(default=10.0, gt=0)

    # -- AI assistant (DESIGN 12) ------------------------------------------------------------
    # none (default: every AI feature is hidden), gemini, anthropic or openai_compat (any Chat
    # Completions endpoint with tools: OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio...).
    # "fake" plays scripted tool calls (development and tests only; refused in production).
    ai_provider: Literal["none", "gemini", "anthropic", "openai_compat", "fake"] = "none"
    ai_model: str = ""
    # Give JustForms its own key; never share another application's.
    ai_api_key: SecretStr | None = None
    # Endpoint override; required for openai_compat (e.g. http://ollama:11434/v1).
    ai_base_url: str | None = None
    # Model for "Start from a paper form" (defaults to ai_model).
    ai_vision_model: str | None = None
    # Whether the model reads images. Unset: on for gemini and anthropic, off for openai_compat.
    ai_vision: bool | None = None
    # Deprecated and ignored: the studio never names the AI provider (it says "the AI
    # service"). Kept so existing deployments that set it still start.
    ai_provider_label: str = ""
    ai_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    ai_max_tool_calls: int = Field(default=40, ge=1, le=200)
    ai_turn_seconds: int = Field(default=120, ge=10, le=900)
    ai_request_timeout_seconds: float = Field(default=90.0, gt=0)
    # Daily token allowances (input + output); 0 turns the allowance off.
    ai_daily_tokens_per_user: int = Field(default=300_000, ge=0)
    ai_daily_tokens_per_org: int = Field(default=3_000_000, ge=0)
    # Forms larger than this (characters of JSON) are not sent to the provider.
    ai_max_form_chars: int = Field(default=80_000, ge=1000)
    # Scripted turns for the fake provider (JSON file; see app/ai/providers/fake.py).
    ai_fake_script: Path | None = None

    # -- branding (instance defaults; each organisation can override them in Settings) -------
    # Empty values fall back to JustForms' own identity.
    brand_name: str = ""
    # "#RRGGBB"; adjusted for contrast like an organisation's colour.
    brand_primary_color: str | None = None
    # https:// or mailto: link shown in form and email footers.
    brand_support_url: str | None = None
    # PNG or SVG files read by the API (e.g. a mounted ConfigMap); validated like uploads.
    brand_logo_file: Path | None = None
    brand_logo_dark_file: Path | None = None
    brand_icon_file: Path | None = None
    # "optional": organisations may hide "Powered by JustForms"; "always": it always shows.
    brand_powered_by: Literal["optional", "always"] = "optional"

    # Error tracking (Sentry protocol, e.g. GlitchTip). Unset: off. The API and the worker
    # report to this DSN; personal data is scrubbed before sending (docs/security.md).
    sentry_dsn: str | None = None
    # DSN for browser errors (studio, public form, document pages). Browsers send through the
    # same-origin tunnel /api/v1/telemetry/envelope, which forwards only to this DSN's host, so
    # it may be an internal address. Unset: the same as sentry_dsn; "off": no browser reporting.
    sentry_browser_dsn: str | None = None
    # Browsers report through the same-origin tunnel (default). False: browsers send straight
    # to the browser DSN, which must then be publicly reachable and allowed in the CSP
    # (JUSTFORMS_CSP_EXTRA_CONNECT_SRC).
    sentry_browser_tunnel: bool = True
    # Environment tag. Unset: JUSTFORMS_ENVIRONMENT.
    sentry_environment: str | None = None
    # Share of requests traced (0 to 1). Default 0: errors only.
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Origins allowed to call the API from a browser (the SPA is normally same-origin).
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator(
        "secret_key",
        "oidc_issuer",
        "oidc_discovery_url",
        "oidc_client_secret",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "pdf_signing_p12",
        "pdf_signing_p12_password",
        "pdf_tsa_url",
        "captcha_secret_key",
        "ai_api_key",
        "ai_base_url",
        "ai_vision_model",
        "ai_vision",
        "ai_fake_script",
        "brand_primary_color",
        "brand_support_url",
        "brand_logo_file",
        "brand_logo_dark_file",
        "brand_icon_file",
        "demo_login_code",
        "api_docs",
        "sentry_dsn",
        "sentry_browser_dsn",
        "sentry_environment",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # Compose passes unset variables as empty strings.
        return None if value == "" else value

    @field_validator(
        "oidc_admin_groups",
        "oidc_creator_groups",
        "oidc_member_groups",
        "oidc_superadmin_groups",
        "oidc_email_fallback_claims",
        "cors_origins",
        "trusted_proxies",
        "rate_limits",
        "webhook_allowed_cidrs",
        "demo_login_emails",
        "thaana_fonts",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _csv(value)

    @field_validator("demo_login_emails")
    @classmethod
    def _demo_emails(cls, value: list[str]) -> list[str]:
        emails = [v.strip().lower() for v in value]
        for email in emails:
            if "@" not in email:
                raise ValueError(f"JUSTFORMS_DEMO_LOGIN_EMAILS: {email!r} is not an email address")
        return emails

    @field_validator("sentry_dsn", "sentry_browser_dsn")
    @classmethod
    def _dsn(cls, value: str | None) -> str | None:
        if value is None or value.strip().lower() == "off":
            return value and "off"
        if parse_dsn(value) is None:
            raise ValueError("not a Sentry DSN; expected https://<public key>@<host>/<project id>")
        return value.strip()

    @property
    def sentry_browser(self) -> str | None:
        """The DSN browsers report to, or ``None`` when browser reporting is off."""
        if self.sentry_browser_dsn == "off":
            return None
        dsn = self.sentry_browser_dsn or self.sentry_dsn
        return None if dsn == "off" else dsn

    @model_validator(mode="after")
    def _production_requirements(self) -> Self:
        if self.environment == "production":
            self._check_production_secret()
            if self.demo_login_code is not None:
                raise ValueError(
                    "JUSTFORMS_DEMO_LOGIN_CODE is for demo instances only and is refused with "
                    "JUSTFORMS_ENVIRONMENT=production"
                )
        if self.captcha_provider in ("turnstile", "hcaptcha") and (
            not self.captcha_site_key or self.captcha_secret_key is None
        ):
            raise ValueError(
                "JUSTFORMS_CAPTCHA_SITE_KEY and JUSTFORMS_CAPTCHA_SECRET_KEY are required for "
                f"JUSTFORMS_CAPTCHA_PROVIDER={self.captcha_provider}"
            )
        if self.ai_provider == "fake" and self.environment == "production":
            raise ValueError("JUSTFORMS_AI_PROVIDER=fake is for development and tests only")
        if self.ai_provider not in ("none", "fake") and not self.ai_model:
            raise ValueError(
                f"JUSTFORMS_AI_MODEL is required for JUSTFORMS_AI_PROVIDER={self.ai_provider}"
            )
        if self.ai_provider in ("gemini", "anthropic") and self.ai_api_key is None:
            raise ValueError(
                f"JUSTFORMS_AI_API_KEY is required for JUSTFORMS_AI_PROVIDER={self.ai_provider}"
            )
        if self.ai_provider == "openai_compat" and not self.ai_base_url:
            raise ValueError(
                "JUSTFORMS_AI_BASE_URL is required for JUSTFORMS_AI_PROVIDER=openai_compat"
            )
        if self.oidc_issuer and not self.oidc_client_id:
            raise ValueError(
                "JUSTFORMS_OIDC_CLIENT_ID is required when JUSTFORMS_OIDC_ISSUER is set"
            )
        self._check_demo_login()
        return self

    def _check_production_secret(self) -> None:
        if self.secret_key is None:
            raise ValueError("JUSTFORMS_SECRET_KEY is required in production")
        key = self.secret_key.get_secret_value()
        if key == _DEV_SECRET_KEY or key.strip().lower().startswith(_PLACEHOLDER_SECRET_PREFIXES):
            raise ValueError(
                "JUSTFORMS_SECRET_KEY is a placeholder; generate one, e.g. "
                '`python -c "import secrets; print(secrets.token_urlsafe(48))"`'
            )
        if len(key.encode()) < MIN_SECRET_KEY_BYTES:
            raise ValueError(
                f"JUSTFORMS_SECRET_KEY must be at least {MIN_SECRET_KEY_BYTES} bytes in production"
            )

    def _check_demo_login(self) -> None:
        if self.demo_login_code is None:
            if self.demo_login_emails:
                raise ValueError(
                    "JUSTFORMS_DEMO_LOGIN_EMAILS is set without JUSTFORMS_DEMO_LOGIN_CODE"
                )
            return
        code = self.demo_login_code.get_secret_value().strip()
        if not (len(code) == 6 and code.isascii() and code.isdigit()):
            raise ValueError("JUSTFORMS_DEMO_LOGIN_CODE must be exactly 6 digits")
        if weak_code(code):
            raise ValueError("JUSTFORMS_DEMO_LOGIN_CODE is too easy to guess; pick a random code")
        if not self.demo_login_emails:
            raise ValueError(
                "JUSTFORMS_DEMO_LOGIN_EMAILS is required with JUSTFORMS_DEMO_LOGIN_CODE "
                "(the code only works for the listed addresses)"
            )
        self.demo_login_code = SecretStr(code)

    @property
    def demo_login_enabled(self) -> bool:
        return self.demo_login_code is not None and self.local_login_enabled

    @property
    def api_docs_enabled(self) -> bool:
        if self.api_docs is not None:
            return self.api_docs
        return self.environment != "production"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer)

    @property
    def oidc_group_mapping(self) -> bool:
        """IdP groups decide roles in the default organisation (DESIGN 7)."""
        return self.oidc_enabled and bool(
            self.oidc_admin_groups or self.oidc_creator_groups or self.oidc_member_groups
        )

    @property
    def local_login_enabled(self) -> bool:
        return not self.oidc_enabled

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"

    @property
    def secret_key_bytes(self) -> bytes:
        if self.secret_key is not None:
            return self.secret_key.get_secret_value().encode()
        log.warning("JUSTFORMS_SECRET_KEY is not set; using the insecure development key")
        return _DEV_SECRET_KEY.encode()

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "none"

    @property
    def ai_vision_enabled(self) -> bool:
        if not self.ai_enabled:
            return False
        if self.ai_vision is not None:
            return self.ai_vision
        return self.ai_provider in ("gemini", "anthropic", "fake")

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def public_origin(self) -> str:
        return self.public_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
