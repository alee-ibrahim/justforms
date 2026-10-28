"""Optional error tracking with the Sentry SDK (any Sentry-protocol server, e.g. GlitchTip).

Off unless ``JUSTFORMS_SENTRY_DSN`` is set. Events carry the release (``X.Y.Z``) and the
environment, never personal data: no default PII, no local variables, no request bodies, no
breadcrumbs, and every event goes through :func:`app.telemetry.scrub.before_send`.
"""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlsplit

from app import __version__
from app.config import Settings
from app.telemetry.scrub import before_send

log = logging.getLogger(__name__)

Component = Literal["api", "worker", "cli"]


def init_sentry(settings: Settings, component: Component) -> bool:
    """Start the SDK for this process. Returns whether error tracking is on."""
    dsn = settings.sentry_dsn
    if not dsn or dsn == "off":
        return False
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    integrations: list[object] = [
        # Errors logged with log.exception() become events; log lines are not breadcrumbs.
        LoggingIntegration(level=None, event_level=logging.ERROR),
    ]
    if component == "worker":
        from sentry_sdk.integrations.arq import ArqIntegration

        integrations.append(ArqIntegration())
    sentry_sdk.init(
        dsn=dsn,
        release=__version__,
        environment=settings.sentry_environment or settings.environment,
        server_name=f"justforms-{component}",
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=True,
        max_request_body_size="never",
        max_breadcrumbs=0,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=0.0,
        before_send=before_send,  # type: ignore[arg-type]
        before_send_transaction=None,
        integrations=integrations,  # type: ignore[arg-type]
    )
    sentry_sdk.set_tag("component", component)
    log.info("error tracking on (%s, %s)", urlsplit(dsn).hostname, component)
    return True
