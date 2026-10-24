"""Outgoing email over SMTP (used by the worker only) and message templates."""

from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import aiosmtplib

from app.config import Settings

log = logging.getLogger(__name__)

LOGIN_CODE_SUBJECT = "Your {name} sign-in code"
LOGIN_CODE_BODY = (
    "Your sign-in code is {code}.\n\nIt expires in {minutes} minutes. "
    "If you did not try to sign in, you can ignore this email."
)


def login_code_message(code: str, minutes: int, name: str = "JustForms") -> tuple[str, str]:
    """Staff sign-in code; ``name`` is the default organisation's brand (DESIGN 18.2)."""
    subject = LOGIN_CODE_SUBJECT.format(name=" ".join(name.split())[:80] or "JustForms")
    return subject, LOGIN_CODE_BODY.format(code=code, minutes=minutes)


def sender(smtp_from: str, name: str | None) -> str:
    """``smtp_from`` with its display name replaced by the organisation's (the address stays
    the install's, so SPF/DKIM keep working)."""
    if not name:
        return smtp_from
    _, address = parseaddr(smtp_from)
    if not address:
        return smtp_from
    return formataddr((" ".join(name.split())[:80], address))


async def send_email(
    settings: Settings,
    to: str,
    subject: str,
    text: str,
    *,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    from_name: str | None = None,
) -> bool:
    """Send one message (text, optional HTML alternative, optional attachments). Returns
    False when SMTP is not configured; raises on delivery errors so the job can retry."""
    if not settings.smtp_host:
        log.warning("SMTP is not configured (JUSTFORMS_SMTP_HOST); email not sent")
        return False
    msg = EmailMessage()
    msg["From"] = sender(settings.smtp_from, from_name)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(
            data, maintype=maintype, subtype=subtype or "octet-stream", filename=name
        )
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        start_tls=settings.smtp_security == "starttls",
        use_tls=settings.smtp_security == "tls",
    )
    return True
