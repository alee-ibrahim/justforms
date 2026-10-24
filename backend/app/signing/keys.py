"""The install's PDF signing identity (DESIGN 9.5, decision 22.1.3).

Default: a self-signed RSA-3072 key and certificate, generated on first use (or with
``justforms init-signing-key``) and kept in ``signing_keys`` with the private key encrypted by
a Fernet key derived from ``JUSTFORMS_SECRET_KEY``. Changing the secret key makes the stored
key unreadable; ``init-signing-key --rotate`` then creates a new one (older PDFs stay
verifiable with the old certificate, which is kept).

Optional: an organisation certificate as PKCS#12 (``JUSTFORMS_PDF_SIGNING_P12`` and
``..._PASSWORD``), for example one issued by the organisation's own PKI.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SigningKey

KEY_BITS = 3072
VALID_YEARS = 10


class SigningKeyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SigningIdentity:
    cert_pem: bytes
    key_pem: bytes  # unencrypted PKCS#8, kept in memory only
    fingerprint: str  # SHA-256 of the DER certificate, hex
    subject: str
    source: str  # "self_signed" | "p12"

    @property
    def cert(self) -> asn1_x509.Certificate:
        der = x509.load_pem_x509_certificate(self.cert_pem).public_bytes(serialization.Encoding.DER)
        return asn1_x509.Certificate.load(der)

    @property
    def key(self) -> asn1_keys.PrivateKeyInfo:
        der = serialization.load_pem_private_key(self.key_pem, password=None).private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        return asn1_keys.PrivateKeyInfo.load(der)


def fingerprint(cert_pem: bytes) -> str:
    der = x509.load_pem_x509_certificate(cert_pem).public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def pretty_fingerprint(hex_digest: str) -> str:
    return ":".join(hex_digest[i : i + 2] for i in range(0, len(hex_digest), 2)).upper()


def _fernet(settings: Settings) -> Fernet:
    digest = hashlib.sha256(b"justforms:pdf-signing-key:" + settings.secret_key_bytes).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def generate(settings: Settings) -> tuple[bytes, bytes]:
    """A new self-signed key and certificate (PEM)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, settings.pdf_signer_name[:64]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, settings.default_org_name[:64]),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365 * VALID_YEARS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


async def create_key(db: AsyncSession, settings: Settings) -> SigningKey:
    """Generate and store a new active key, retiring the current one."""
    cert_pem, key_pem = generate(settings)
    cert = x509.load_pem_x509_certificate(cert_pem)
    await db.execute(update(SigningKey).where(SigningKey.active).values(active=False))
    row = SigningKey(
        subject=cert.subject.rfc4514_string(),
        cert_pem=cert_pem.decode(),
        key_encrypted=_fernet(settings).encrypt(key_pem),
        fingerprint_sha256=fingerprint(cert_pem),
        not_after=cert.not_valid_after_utc,
        active=True,
    )
    db.add(row)
    await db.flush()
    return row


async def ensure_key(db: AsyncSession, settings: Settings) -> SigningKey:
    """The active self-signed key, created on first use."""
    row = await db.scalar(select(SigningKey).where(SigningKey.active))
    if row is None:
        try:
            row = await create_key(db, settings)
            await db.commit()
        except IntegrityError:  # another process created it first
            await db.rollback()
            row = await db.scalar(select(SigningKey).where(SigningKey.active))
            if row is None:
                raise
    return row


def _from_p12(settings: Settings) -> SigningIdentity:
    assert settings.pdf_signing_p12 is not None
    password = (
        settings.pdf_signing_p12_password.get_secret_value().encode()
        if settings.pdf_signing_p12_password
        else None
    )
    try:
        key, cert, _extra = pkcs12.load_key_and_certificates(
            settings.pdf_signing_p12.read_bytes(), password
        )
    except (OSError, ValueError) as exc:
        raise SigningKeyError(f"cannot read JUSTFORMS_PDF_SIGNING_P12: {exc}") from exc
    if key is None or cert is None:
        raise SigningKeyError("JUSTFORMS_PDF_SIGNING_P12 must hold a key and its certificate")
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return SigningIdentity(
        cert_pem, key_pem, fingerprint(cert_pem), cert.subject.rfc4514_string(), "p12"
    )


async def signing_identity(db: AsyncSession, settings: Settings) -> SigningIdentity:
    if settings.pdf_signing_p12:
        return _from_p12(settings)
    row = await ensure_key(db, settings)
    try:
        key_pem = _fernet(settings).decrypt(row.key_encrypted)
    except InvalidToken as exc:
        raise SigningKeyError(
            "the stored PDF signing key cannot be decrypted with JUSTFORMS_SECRET_KEY; "
            "run `justforms init-signing-key --rotate` to create a new one"
        ) from exc
    return SigningIdentity(
        row.cert_pem.encode(), key_pem, row.fingerprint_sha256, row.subject, "self_signed"
    )


async def known_certificates(db: AsyncSession, settings: Settings) -> dict[str, str]:
    """Fingerprint → certificate PEM of every certificate this install has signed with."""
    rows = (await db.scalars(select(SigningKey))).all()
    out = {r.fingerprint_sha256: r.cert_pem for r in rows}
    if settings.pdf_signing_p12:
        ident = _from_p12(settings)
        out[ident.fingerprint] = ident.cert_pem.decode()
    return out
