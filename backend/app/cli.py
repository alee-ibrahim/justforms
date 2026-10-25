"""Admin CLI.

uv run python -m app.cli create-admin --email you@example.org [--name "Your Name"]
uv run python -m app.cli init-signing-key [--rotate]
uv run python -m app.cli verify-pdf submission-0042.pdf
JUSTFORMS_JOTFORM_API_KEY=... uv run python -m app.cli fetch-imported-files --form <id|slug>
JUSTFORMS_JOTFORM_API_KEY=... uv run python -m app.cli rebuild-jotform-import --form <id|slug>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Any

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


async def _find_form_and_actor(
    db: Any, form_ref: str, actor_email: str | None
) -> tuple[Any, uuid.UUID | None] | None:
    from sqlalchemy import select

    from app.models import FormRecord, User

    try:
        cond = FormRecord.id == uuid.UUID(form_ref)
    except ValueError:
        cond = FormRecord.slug == form_ref
    form = await db.scalar(select(FormRecord).where(cond, FormRecord.deleted_at.is_(None)))
    if form is None:
        print(f"form not found: {form_ref}")
        return None
    actor = None
    if actor_email:
        actor = await db.scalar(select(User.id).where(User.email == actor_email.lower()))
        if actor is None:
            print(f"user not found: {actor_email}")
            return None
    return form, actor


async def _fetch_imported_files(
    form_ref: str, dry_run: bool, actor_email: str | None
) -> tuple[int, dict[str, Any] | None]:
    from app.importers.imported_files import fetch_form_files
    from app.storage import get_storage

    settings = get_settings()
    key = settings.jotform_api_key.get_secret_value() if settings.jotform_api_key else None
    if not key and not dry_run:
        print("JUSTFORMS_JOTFORM_API_KEY is not set: Jotform serves uploads only with a key.")
        return 2, None
    async with get_sessionmaker()() as db:
        found = await _find_form_and_actor(db, form_ref, actor_email)
        if found is None:
            return 2, None
        form, actor = found
        report = await fetch_form_files(
            db, get_storage(), settings, form.id, api_key=key, dry_run=dry_run, actor_id=actor
        )
    # Counts and positions only: file names and links can carry personal data.
    for r in report.results:
        if r.status != "skipped":
            reason = f" ({r.reason})" if r.reason else ""
            print(f"#{r.seq:04d} {r.field_id}[{r.index}] {r.kind or '-'}: {r.status}{reason}")
    print(
        f"submissions: {report.submissions}  "
        + "  ".join(f"{k}: {v}" for k, v in sorted(report.counts().items()))
    )
    return (1 if report.counts().get("failed") else 0), report.as_json()


async def _rebuild_import(
    form_ref: str, jotform_id: str | None, dry_run: bool, actor_email: str | None
) -> tuple[int, dict[str, Any] | None]:
    from app.importers.rebuild import RebuildRefused, rebuild_imported
    from app.importers.service import exact_times

    settings = get_settings()
    async with get_sessionmaker()() as db:
        found = await _find_form_and_actor(db, form_ref, actor_email)
        if found is None:
            return 2, None
        form, actor = found
        times, source = await exact_times(settings, form, jotform_id)
        if source["source"] != "jotform_api":
            print(f"no exact times from Jotform's API ({source.get('reason')})")
            return 2, None
        print(f"Jotform API: {len(times)} submission times")
        try:
            report = await rebuild_imported(
                db, form.id, times, time_source="jotform_api", dry_run=dry_run, actor_id=actor
            )
        except RebuildRefused as exc:
            await db.rollback()
            print(f"refused, some imported rows have moved on: {exc}")
            return 1, None
        if not dry_run:
            await db.commit()
    print(
        f"imported rows: {report.rows}  retimed: {report.retimed}  "
        f"renumbered: {report.renumbered}  without an API time: {report.missing_time}"
        + ("  (dry run, nothing changed)" if dry_run else "")
    )
    return 0, report.as_json()


def _write_report(path: str | None, data: dict[str, Any] | None) -> None:
    if path and data is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)


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
    fetch = sub.add_parser(
        "fetch-imported-files",
        help="copy the files behind imported Jotform links into storage "
        "(key in JUSTFORMS_JOTFORM_API_KEY)",
    )
    fetch.add_argument("--form", required=True, help="form id or address (slug)")
    fetch.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    fetch.add_argument("--actor", help="email of the user recorded in the audit log")
    fetch.add_argument("--report", help="write the per-file report (JSON) here")
    rebuild = sub.add_parser(
        "rebuild-jotform-import",
        help="give imported submissions their exact Jotform submit times and number them "
        "oldest first (untouched imported rows only; key in JUSTFORMS_JOTFORM_API_KEY)",
    )
    rebuild.add_argument("--form", required=True, help="form id or address (slug)")
    rebuild.add_argument("--jotform-form", help="Jotform form id (default: from the import)")
    rebuild.add_argument("--dry-run", action="store_true", help="show the changes only")
    rebuild.add_argument("--actor", help="email of the user recorded in the audit log")
    rebuild.add_argument("--report", help="write the report (JSON) here")
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        asyncio.run(_create_admin(args.email, args.name))
    elif args.command == "init-signing-key":
        asyncio.run(_init_signing_key(args.rotate))
    elif args.command == "verify-pdf":
        with open(args.path, "rb") as f:
            return asyncio.run(_verify_pdf(f.read()))
    elif args.command == "fetch-imported-files":
        code, data = asyncio.run(_fetch_imported_files(args.form, args.dry_run, args.actor))
        _write_report(args.report, data)
        return code
    elif args.command == "rebuild-jotform-import":
        code, data = asyncio.run(
            _rebuild_import(args.form, args.jotform_form, args.dry_run, args.actor)
        )
        _write_report(args.report, data)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
