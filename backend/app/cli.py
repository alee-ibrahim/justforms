"""Admin CLI.

uv run python -m app.cli create-admin --email you@example.org [--name "Your Name"]
uv run python -m app.cli init-signing-key [--rotate]
uv run python -m app.cli verify-pdf submission-0042.pdf
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db import get_sessionmaker


async def _create_admin(email: str, name: str) -> None:
    from app.services.users import create_admin

    async with get_sessionmaker()() as db:
        user = await create_admin(db, get_settings(), email, name)
        await db.commit()
        print(f"admin ready: {user.email}")


async def _init_signing_key(rotate: bool) -> None:
    from sqlalchemy import select

    from app.models import SigningKey
    from app.signing.keys import create_key, pretty_fingerprint

    settings = get_settings()
    async with get_sessionmaker()() as db:
        row = await db.scalar(select(SigningKey).where(SigningKey.active))
        if row is None or rotate:
            row = await create_key(db, settings)
            await db.commit()
            print("created a new PDF signing key")
        print(f"subject:     {row.subject}")
        print(f"fingerprint: {pretty_fingerprint(row.fingerprint_sha256)}")
        print(f"valid until: {row.not_after:%Y-%m-%d}")
        print("Publish the fingerprint so others can check that PDFs come from this install.")


VERDICTS = {
    "genuine": "Genuine and unchanged: the signature is valid, made by this install, and the "
    "PDF matches the submission as it is stored now.",
    "modified": "Changed after signing: the signature does not cover the file's current contents.",
    "not_ours": "Not signed by this install: the signing certificate is unknown here.",
    "unsigned": "This PDF has no digital signature.",
    "data_changed": "The PDF is genuine, but the stored submission no longer matches it.",
    "not_found": "The PDF is genuine, but its submission no longer exists.",
}


async def _verify_pdf(pdf: bytes) -> int:
    from app.pdf.service import check_pdf_against_db
    from app.signing.keys import pretty_fingerprint

    async with get_sessionmaker()() as db:
        report = await check_pdf_against_db(db, get_settings(), pdf)
    print(VERDICTS[report.verdict])
    fp = report.pdf.get("signer_fingerprint")
    if fp:
        print(f"signer:       {report.pdf.get('signer_subject')}")
        print(f"fingerprint:  {pretty_fingerprint(fp)}")
    if report.pdf.get("signed_at"):
        print(f"signed at:    {report.pdf['signed_at']}")
    if report.submission:
        sub = report.submission
        print(f"submission:   #{sub['seq']:04d} of {sub['formTitle']} ({sub['id']})")
        print(f"hash in PDF:  {sub['contentHashInPdf']}")
        print(f"hash now:     {sub['contentHashComputed']}")
    return 0 if report.verdict == "genuine" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="justforms")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create or promote the first administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="")
    key = sub.add_parser("init-signing-key", help="create the PDF signing key if missing")
    key.add_argument("--rotate", action="store_true", help="replace the active key")
    verify = sub.add_parser("verify-pdf", help="check a signed submission PDF")
    verify.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        asyncio.run(_create_admin(args.email, args.name))
    elif args.command == "init-signing-key":
        asyncio.run(_init_signing_key(args.rotate))
    elif args.command == "verify-pdf":
        with open(args.path, "rb") as f:
            return asyncio.run(_verify_pdf(f.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
