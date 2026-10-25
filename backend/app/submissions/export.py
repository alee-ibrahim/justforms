"""The ``.xlsx`` export (DESIGN 15.2), built by the worker with openpyxl ``write_only=True``.

- Sheet "Submissions": one row per submission. Fixed columns ``#``, ``Submitted at`` (in
  ``JUSTFORMS_TIMEZONE``), ``Status``, ``Version``, ``Language``, ``Respondent email`` (the
  confirmed address of email-code and staff-only forms), then one column per question
  across the union of all versions: ordered by the latest version, removed questions at the
  end with "(version N)" after the label, N being the last version that asked them. Headers
  are ``Label (key)`` with labels in the form's language; the fixed headers and words (status,
  language, "Yes"/"No") are English for every form.
- Each repeater gets its own sheet: ``Submission #``, ``Row``, then its questions. With version
  field mappings in the form's settings (``app/submissions/version_map.py``), submissions of a
  version without the repeater get rows there too, read from the mapped fixed questions, and
  those questions get no columns of their own.
- Choices show option labels (multi choice joined with ``; ``), files and signatures are links
  to the app (never presigned URLs), numbers stay numbers and everything else is text.
- dv forms get right-to-left sheets. Cells starting with ``= + - @`` (or a tab or carriage
  return) are prefixed with ``'`` so a spreadsheet never runs them as formulas.
"""

from __future__ import annotations

import logging
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.answers import answer_text, mask
from app.config import Settings
from app.logic.index import FormIndex
from app.models import Export, ExportStatus, FormRecord, FormVersion, Signature, Submission
from app.pdf.render import leaf_fields
from app.schemas.form import (
    FieldElement,
    FileField,
    Form,
    HiddenField,
    NumberField,
    RatingField,
    RepeaterElement,
    SignatureField,
)
from app.services.users import audit
from app.storage import Storage
from app.submissions import version_map
from app.submissions.query import ListFilters, apply_filters

log = logging.getLogger(__name__)

BATCH = 500
EXPIRY = timedelta(hours=24)
STATUS_WORDS = {
    "new": "New",
    "in_review": "In review",
    "approved": "Approved",
    "rejected": "Rejected",
}
LANGUAGE_WORDS = {"en": "English", "dv": "Dhivehi"}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def safe_text(value: str) -> str:
    """Neutralise spreadsheet formula injection."""
    return "'" + value if value.startswith(_FORMULA_START) else value


@dataclass
class Column:
    id: str
    label: str
    field: FieldElement


@dataclass
class RepeaterSheet:
    id: str
    label: str
    columns: list[Column] = field(default_factory=list)


@dataclass
class Layout:
    columns: list[Column]
    repeaters: list[RepeaterSheet]


def layout(
    forms: list[Form],
    numbers: list[int] | None = None,
    mapped: set[str] | frozenset[str] = frozenset(),
) -> Layout:
    """Columns across all versions, latest first; ``forms`` is oldest to newest, ``numbers``
    their version numbers. Questions in ``mapped`` (read as repeater rows) get no column."""
    columns: dict[str, Column] = {}
    repeaters: dict[str, RepeaterSheet] = {}
    numbers = numbers or list(range(1, len(forms) + 1))
    latest = True
    for form, number in zip(reversed(forms), reversed(numbers), strict=True):
        index = FormIndex.build(form)
        for info in index.elements.values():
            el = info.element
            if isinstance(el, RepeaterElement):
                sheet = repeaters.setdefault(el.id, RepeaterSheet(el.id, el.label))
                known = {c.id for c in sheet.columns}
                for child in leaf_fields(el.elements):
                    if child.id not in known:
                        sheet.columns.append(Column(child.id, child.label, child))
                continue
            if info.kind != "field" or info.repeater_id is not None:
                continue
            if info.id not in columns and not (info.id in mapped and not latest):
                label = el.label if latest else f"{el.label} (version {number})"  # type: ignore[attr-defined]
                columns[info.id] = Column(info.id, label, el)  # type: ignore[arg-type]
        latest = False
    return Layout(list(columns.values()), list(repeaters.values()))


def sheet_title(label: str, used: set[str]) -> str:
    base = _SHEET_BAD.sub(" ", label).strip()[:28] or "Repeater"
    title, n = base, 2
    while title.lower() in used or title.lower() == "submissions":
        title = f"{base[:25]} {n}"
        n += 1
    used.add(title.lower())
    return title


@dataclass
class Context:
    settings: Settings
    language: str
    signatures: dict[uuid.UUID, dict[str, Signature]]
    mask_sensitive: bool = False

    def local(self, dt: datetime) -> str:
        return dt.astimezone(self.settings.tz).strftime("%Y-%m-%d %H:%M:%S")

    def link(self, path: str) -> str:
        return f"{self.settings.public_origin}/api/v1/{path}"


def cell_value(col: Column, value: Any, sub: Submission, ctx: Context) -> Any:
    f = col.field
    if value is None or value == "" or value == []:
        return None
    if ctx.mask_sensitive and f.sensitive:
        return mask(answer_text(f, value, ctx.language))
    if isinstance(f, NumberField | RatingField) and isinstance(value, int | float):
        return value if not isinstance(value, bool) else str(value)
    if isinstance(f, FileField) and isinstance(value, list):
        return "\n".join(
            f"{v.get('name', 'file')}: {ctx.link('files/' + str(v.get('fileId')))}"
            for v in value
            if isinstance(v, dict)
        )
    if isinstance(f, SignatureField):
        sig = ctx.signatures.get(sub.id, {}).get(col.id)
        when = ctx.local(sig.received_at) if sig else ""
        return f"Signed {when} ({ctx.link(f'submissions/{sub.id}/pdf')})".replace("  ", " ")
    if isinstance(f, HiddenField):
        return safe_text(str(value))
    text = answer_text(f, value, ctx.language, list_sep="; ")
    return safe_text(text) if text else None


def _header(ws: Any, labels: list[str]) -> None:
    cells = []
    for label in labels:
        c = WriteOnlyCell(ws, value=safe_text(label))
        c.font = Font(bold=True)
        c.alignment = Alignment(vertical="top")
        cells.append(c)
    ws.append(cells)


async def build_export(
    db: AsyncSession, storage: Storage, settings: Settings, export_id: uuid.UUID
) -> bool:
    export = await db.get(Export, export_id)
    if export is None:
        return False
    try:
        await _build(db, storage, settings, export)
        return True
    except Exception:
        log.exception("export %s failed", export_id)
        await db.rollback()
        export = await db.get(Export, export_id)
        if export is not None:
            export.status = ExportStatus.FAILED
            await db.commit()
        return False


async def _brand_name(db: AsyncSession, settings: Settings, form_rec: FormRecord) -> str:
    from app.branding.service import brand_for_org_id

    return (await brand_for_org_id(db, settings, form_rec.org_id)).name


def set_properties(
    wb: Workbook, org: str, forms: list[Form], title: str, url: str | None = None
) -> None:
    """Workbook metadata: the organisation as creator (DESIGN 18.2), the form as title and its
    public address as the identifier."""
    props = wb.properties
    props.creator = org[:255]
    props.lastModifiedBy = org[:255]
    props.title = ((forms[-1].settings.title if forms else "") or title)[:255]
    props.subject = "Submissions"
    props.description = f"Exported from {org} with JustForms"[:255]
    if url:
        props.identifier = url[:255]


async def _build(db: AsyncSession, storage: Storage, settings: Settings, export: Export) -> None:
    form_rec = await db.get(FormRecord, export.form_id)
    assert form_rec is not None
    versions = (
        await db.scalars(
            select(FormVersion)
            .where(FormVersion.form_id == form_rec.id)
            .order_by(FormVersion.version)
        )
    ).all()
    forms = [Form.model_validate(v.schema) for v in versions]
    version_no = {v.id: v.version for v in versions}
    language = forms[-1].settings.language if forms else "en"
    mappings = {
        m.repeater: m for m in version_map.parse((form_rec.settings or {}).get("versionMappings"))
    }
    mapped = {src for m in mappings.values() for src in m.sources}
    lay = layout(forms, [v.version for v in versions], mapped)
    # Per version: the mapped repeaters it lacks (their rows come from the mapping).
    by_mapping = {
        v.id: [r for r in mappings if not version_map.has_repeater(f, r)]
        for v, f in zip(versions, forms, strict=True)
    }
    raw = dict(export.filters or {})
    masked = bool(raw.pop("maskSensitive", False))
    filters = ListFilters.model_validate(raw)
    base = apply_filters(
        select(Submission).where(Submission.form_id == form_rec.id), filters, settings.tz
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    export.status = ExportStatus.RUNNING
    export.row_count = int(total or 0)
    export.rows_done = 0
    await db.commit()

    wb = Workbook(write_only=True)
    set_properties(
        wb,
        await _brand_name(db, settings, form_rec),
        forms,
        form_rec.title,
        f"{settings.public_origin}/{form_rec.slug}",
    )
    main = wb.create_sheet("Submissions")
    used: set[str] = {"submissions"}
    rep_sheets = [(r, wb.create_sheet(sheet_title(r.label, used))) for r in lay.repeaters]
    for ws in [main, *(s for _r, s in rep_sheets)]:
        if language == "dv":
            ws.sheet_view.rightToLeft = True
    _header(
        main,
        ["#", "Submitted at", "Status", "Version", "Language", "Respondent email"]
        + [f"{c.label} ({c.id})" for c in lay.columns],
    )
    for rep, ws in rep_sheets:
        _header(ws, ["Submission #", "Row"] + [f"{c.label} ({c.id})" for c in rep.columns])

    last_seq = 0
    done = 0
    while True:
        batch = (
            await db.scalars(
                base.where(Submission.seq > last_seq).order_by(Submission.seq).limit(BATCH)
            )
        ).all()
        if not batch:
            break
        ids = [s.id for s in batch]
        sigs: dict[uuid.UUID, dict[str, Signature]] = {}
        for sig in (
            await db.scalars(select(Signature).where(Signature.submission_id.in_(ids)))
        ).all():
            sigs.setdefault(sig.submission_id, {})[sig.field_id] = sig
        ctx = Context(settings, language, sigs, masked)
        for sub in batch:
            main.append(
                [
                    sub.seq,
                    ctx.local(sub.submitted_at),
                    STATUS_WORDS.get(sub.status.value, sub.status.value),
                    version_no.get(sub.form_version_id),
                    LANGUAGE_WORDS.get(sub.language, sub.language),
                    safe_text(sub.respondent_email) if sub.respondent_email else None,
                    *(cell_value(c, sub.data.get(c.id), sub, ctx) for c in lay.columns),
                ]
            )
            from_mapping = by_mapping.get(sub.form_version_id, [])
            for rep, ws in rep_sheets:
                rows = (
                    version_map.mapped_rows(mappings[rep.id], sub.data)
                    if rep.id in from_mapping
                    else sub.data.get(rep.id)
                )
                for i, row in enumerate(rows if isinstance(rows, list) else []):
                    if not isinstance(row, dict):
                        continue
                    ws.append(
                        [
                            sub.seq,
                            i + 1,
                            *(cell_value(c, row.get(c.id), sub, ctx) for c in rep.columns),
                        ]
                    )
        last_seq = batch[-1].seq
        done += len(batch)
        export.rows_done = done
        await db.commit()

    with tempfile.TemporaryFile() as tmp:
        wb.save(tmp)
        tmp.seek(0)
        key = f"exports/{export.id}.xlsx"
        await storage.put(
            key,
            tmp,  # type: ignore[arg-type, unused-ignore]
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    export.storage_key = key
    export.status = ExportStatus.READY
    export.expires_at = datetime.now(UTC) + EXPIRY
    await audit(
        db,
        "submissions.export",
        org_id=form_rec.org_id,
        actor_id=export.requested_by,
        target_type="form",
        target_id=form_rec.id,
        meta={"export_id": str(export.id), "rows": done},
    )
    await db.commit()


async def purge_expired_exports(db: AsyncSession, storage: Storage) -> int:
    rows = (
        await db.scalars(
            select(Export).where(
                Export.expires_at.is_not(None), Export.expires_at < datetime.now(UTC)
            )
        )
    ).all()
    for row in rows:
        if row.storage_key:
            await storage.delete(row.storage_key)
        await db.delete(row)
    await db.commit()
    return len(rows)
