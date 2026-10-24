"""The install's PDF signing key (DESIGN 9.5).

Each install signs PDFs with its own self-signed RSA-3072 key and certificate, generated on
first use (or with ``justforms init-signing-key``). The private key is stored encrypted with a
key derived from ``JUSTFORMS_SECRET_KEY``; the certificate and its fingerprint are public.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, LargeBinary, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin


class SigningKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "signing_keys"
    __table_args__ = (
        # At most one active key.
        Index(
            "uq_signing_keys_active",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    subject: Mapped[str] = mapped_column(String(500))
    cert_pem: Mapped[str] = mapped_column(Text)
    key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
