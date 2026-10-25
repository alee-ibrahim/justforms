"""Imports from Jotform (DESIGN 13): a form from its HTML, a public URL or the API, and
submissions from an Excel/CSV export with a column-mapping step."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import select

from app.answers import answer_text
from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, SettingsDep, StorageDep
from app.importers import service
from app.importers.jotform import api_source
from app.importers.jotform import logo as jf_logo
from app.importers.jotform.convert import (
    COVER_IMAGE,
    Conversion,
    ConversionError,
    convert,
    field_count,
)
from app.importers.jotform.fetch import FetchError, fetch_form_html
from app.importers.jotform.html_source import NotAJotform, read_html
from app.importers.jotform.model import JfSource
from app.importers.jotform.submissions import (
    IGNORE,
    MAX_FILE_BYTES,
    SAMPLE_ROWS,
    TableError,
    convert_row,
    importable_fields,
    jsonable,
    read_table,
    suggest_mapping,
    targets,
)
from app.models import (
    FormRecord,
    FormRole,
    FormVersion,
    Import,
    ImportKind,
    ImportStatus,
    OrgRole,
    SubmissionStatus,
    User,
)
from app.permissions import (
    FormOwner,
    OrgCreator,
    effective_form_role,
    has_form_role,
    has_org_role,
    org_role,
)
from app.queue import JobQueue, get_queue
from app.schemas.form import Form, FormLanguage

router = APIRouter(tags=["imports"])
QueueDep = Annotated[JobQueue, Depends(get_queue)]

MAX_HTML_CHARS = 5 * 1024 * 1024
ApiKey = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9]{16,64}$")]
JotformId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{1,24}$")]


# -- payloads --------------------------------------------------------------------------------


class JotformHtmlIn(ApiModel):
    """Exactly one of ``html`` (pasted or read from an uploaded file) and ``url``."""

    html: Annotated[str, StringConstraints(max_length=MAX_HTML_CHARS)] | None = None
    url: Annotated[str, StringConstraints(max_length=2000, strip_whitespace=True)] | None = None
    # None: detect from the text (mostly Thaana -> dv).
    language: FormLanguage | None = None
    # Collapsible sections become steps (pages). None: on when the form has no page breaks.
    collapse_as_pages: bool | None = None

    @model_validator(mode="after")
    def _one_source(self) -> JotformHtmlIn:
        if bool(self.html and self.html.strip()) == bool(self.url):
            raise ValueError("give either html or url")
        return self


class JotformApiKeyIn(ApiModel):
    api_key: ApiKey
    region: api_source.Region = "us"


class JotformApiFormIn(JotformApiKeyIn):
    form_id: JotformId
    language: FormLanguage | None = None
    collapse_as_pages: bool | None = None


class JotformFormOut(ApiModel):
    id: str
    title: str
    count: int
    status: str
    updated_at: str | None = None


class FormImportOut(ApiModel):
    id: uuid.UUID
    kind: ImportKind
    status: ImportStatus
    schema_: dict[str, Any] = Field(alias="schema")
    report: dict[str, Any]
    language: FormLanguage
    detected_language: FormLanguage
    source_url: str | None = None
    jotform_form_id: str | None = None
    field_count: int
    page_count: int
    # Collapsible sections in the source (0: the option does not apply) and the choice made.
    collapse_sections: int = 0
    collapse_as_pages: bool = False
    form_id: uuid.UUID | None = None


class FormImportOptionsIn(ApiModel):
    collapse_as_pages: bool


class CreateFormIn(ApiModel):
    title: (
        Annotated[str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)]
        | None
    ) = None
    language: FormLanguage | None = None


class CreatedOut(ApiModel):
    form_id: uuid.UUID


class ColumnOut(ApiModel):
    index: int
    header: str
    samples: list[str]
    target: str


class TargetOut(ApiModel):
    value: str
    label: str
    type: str


class SubmissionImportOut(ApiModel):
    id: uuid.UUID
    form_id: uuid.UUID
    status: ImportStatus
    filename: str
    row_count: int
    version: int
    columns: list[ColumnOut]
    targets: list[TargetOut]
    date_order: Literal["auto", "mdy", "dmy"] = "auto"
    report: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MappingIn(ApiModel):
    columns: Annotated[list[str], Field(max_length=1000)]
    date_order: Literal["auto", "mdy", "dmy"] = "auto"


class PreviewCell(ApiModel):
    column: int
    text: str
    problem: str | None = None


class PreviewRow(ApiModel):
    row: int
    cells: list[PreviewCell]


class MappingPreviewOut(ApiModel):
    rows: list[PreviewRow]
    problems: int
    duplicate_targets: list[str]
    has_submission_id: bool


class StartIn(ApiModel):
    status: SubmissionStatus = SubmissionStatus.NEW


# -- form import ---------------------------------------------------------------------------


def _form_out(imp: Import) -> FormImportOut:
    src = imp.source
    schema = src["form"]
    return FormImportOut(
        id=imp.id,
        kind=imp.kind,
        status=imp.status,
        schema_=schema,
        report=imp.report,
        language=schema["settings"]["language"],
        detected_language=src.get("detectedLanguage", "en"),
        source_url=src.get("sourceUrl"),
        jotform_form_id=src.get("jotformFormId"),
        field_count=field_count(schema),
        page_count=len(schema["pages"]),
        collapse_sections=src.get("collapseSections", 0),
        collapse_as_pages=bool(src.get("collapseAsPages")),
        form_id=imp.form_id,
    )


async def _save_preview(
    db: DbDep,
    storage: StorageDep,
    settings: SettingsDep,
    user: User,
    org_id: uuid.UUID,
    kind: ImportKind,
    src: JfSource,
    conv: Conversion,
    source_url: str | None,
    other: Conversion | None = None,
) -> FormImportOut:
    """Store the preview. The form's logo is downloaded now (so the report is accurate before
    a draft exists) and kept at ``imports/{id}/logo.{ext}`` until the draft is created.

    ``other`` is the same form converted with the opposite collapsible-section choice; both
    are kept so the preview can switch without reading the source again."""
    logo = await jf_logo.import_logo(src.logo_url, source_url, settings)

    def finished(c: Conversion) -> dict[str, Any]:
        report = c.report.as_json()
        if logo.image is not None:
            report["dropped"] = [d for d in report["dropped"] if d != COVER_IMAGE]
        report["logo"] = logo.report
        return report

    report = finished(conv)
    variants: dict[str, Any] = {}
    if other is not None:
        for c in (conv, other):
            key = "pages" if c.collapse_as_pages else "sections"
            variants[key] = {"form": c.form, "report": finished(c)}
    imp = Import(
        org_id=org_id,
        kind=kind,
        status=ImportStatus.PREVIEW,
        source={
            "form": conv.form,
            "detectedLanguage": conv.detected_language,
            "sourceUrl": source_url,
            "jotformFormId": src.form_id,
            "captcha": conv.captcha,
            "collapseSections": conv.collapse_sections,
            "collapseAsPages": conv.collapse_as_pages,
            "variants": variants,
        },
        report=report,
        created_by=user.id,
    )
    db.add(imp)
    if logo.image is not None:
        await db.flush()
        img = logo.image
        key = f"imports/{imp.id}/logo.{img.ext}"
        await storage.put(key, img.data, content_type=img.mime)
        imp.source = {
            **imp.source,
            "logo": {"key": key, "mime": img.mime, "width": img.width, "height": img.height},
        }
    await db.commit()
    await db.refresh(imp)
    return _form_out(imp)


def _convert(
    src: JfSource, language: str | None, settings: Any, kind: str, collapse_as_pages: bool | None
) -> tuple[Conversion, Conversion | None]:
    """The conversion asked for, and the one with the opposite collapsible-section choice
    when the form has collapsible sections."""
    try:
        conv = convert(
            src,
            language=language,
            max_upload_mb=settings.max_upload_mb,
            source_kind=kind,
            collapse_as_pages=collapse_as_pages,
        )
        other = None
        if conv.collapse_sections:
            other = convert(
                src,
                language=language,
                max_upload_mb=settings.max_upload_mb,
                source_kind=kind,
                collapse_as_pages=not conv.collapse_as_pages,
            )
    except ConversionError as exc:  # pragma: no cover - a bug in the importer
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "conversion_failed") from exc
    return conv, other


@router.post(
    "/orgs/{org_id}/imports/jotform/html",
    response_model=FormImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_jotform_html(
    org_id: uuid.UUID,
    body: JotformHtmlIn,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    _: OrgCreator,
) -> Any:
    """Parse a Jotform form (pasted/uploaded HTML, or fetched from its public URL) into a
    preview with an import report. Nothing is created until ``POST /imports/{id}/form``."""
    source_url = None
    html = body.html or ""
    if body.url:
        try:
            source_url, html = await fetch_form_html(body.url, settings)
        except FetchError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"fetch_{exc.code}") from exc
    try:
        src = read_html(html)
    except NotAJotform as exc:
        return JSONResponse(
            {"detail": "not_a_jotform", "formUrl": exc.form_url},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    conv, other = _convert(src, body.language, settings, "html", body.collapse_as_pages)
    return await _save_preview(
        db, storage, settings, user, org_id, ImportKind.JOTFORM_HTML, src, conv, source_url, other
    )


def _api_error(exc: api_source.JotformApiError) -> HTTPException:
    code = status.HTTP_422_UNPROCESSABLE_CONTENT
    if exc.code == "rate_limited":
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif exc.code == "unavailable":
        code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(code, f"jotform_{exc.code}")


@router.post("/orgs/{org_id}/imports/jotform/api/forms", response_model=list[JotformFormOut])
async def list_jotform_forms(
    org_id: uuid.UUID, body: JotformApiKeyIn, _user: CurrentUser, _: OrgCreator
) -> list[JotformFormOut]:
    """The account's forms. The key is used for this call only and never stored."""
    try:
        forms = await api_source.list_forms(body.region, body.api_key)
    except api_source.JotformApiError as exc:
        raise _api_error(exc) from exc
    return [JotformFormOut.model_validate(f) for f in forms]


@router.post(
    "/orgs/{org_id}/imports/jotform/api",
    response_model=FormImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_jotform_api(
    org_id: uuid.UUID,
    body: JotformApiFormIn,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    _: OrgCreator,
) -> FormImportOut:
    """Read one form through the API (questions and conditions). The key is not stored."""
    try:
        src = await api_source.read_form(body.region, body.api_key, body.form_id)
    except api_source.JotformApiError as exc:
        raise _api_error(exc) from exc
    if not src.questions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_a_jotform")
    conv, other = _convert(src, body.language, settings, "api", body.collapse_as_pages)
    return await _save_preview(
        db, storage, settings, user, org_id, ImportKind.JOTFORM_API, src, conv, None, other
    )


# -- loading an import -----------------------------------------------------------------------


async def _load(db: DbDep, user: CurrentUser, import_id: uuid.UUID) -> Import:
    imp = await db.get(Import, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    if imp.kind == ImportKind.JOTFORM_SUBMISSIONS:
        form = await db.get(FormRecord, imp.form_id) if imp.form_id else None
        role = await effective_form_role(db, user, form) if form and not form.deleted_at else None
        if not has_form_role(role, FormRole.OWNER):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    elif imp.created_by != user.id and await org_role(db, user, imp.org_id) != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    return imp


Loaded = Annotated[Import, Depends(_load)]


@router.patch("/imports/{import_id}/options", response_model=FormImportOut)
async def set_form_import_options(
    body: FormImportOptionsIn, db: DbDep, imp: Loaded
) -> FormImportOut:
    """Switch a preview between collapsible sections as steps (pages) and as sections."""
    if imp.kind == ImportKind.JOTFORM_SUBMISSIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_import_kind")
    if imp.status != ImportStatus.PREVIEW or imp.form_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_created")
    src = imp.source
    if bool(src.get("collapseAsPages")) != body.collapse_as_pages:
        variant = (src.get("variants") or {}).get("pages" if body.collapse_as_pages else "sections")
        if variant is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "option_not_available")
        imp.source = {**src, "form": variant["form"], "collapseAsPages": body.collapse_as_pages}
        imp.report = variant["report"]
        await db.commit()
        await db.refresh(imp)
    return _form_out(imp)


@router.post("/imports/{import_id}/form", response_model=CreatedOut, status_code=201)
async def create_form_from_import(
    body: CreateFormIn, db: DbDep, storage: StorageDep, user: CurrentUser, imp: Loaded
) -> CreatedOut:
    """Create the draft form from a preview (once), with the imported logo as its own."""
    if imp.kind == ImportKind.JOTFORM_SUBMISSIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_import_kind")
    if imp.status != ImportStatus.PREVIEW or imp.form_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_created")
    if not has_org_role(await org_role(db, user, imp.org_id), OrgRole.CREATOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_org_role")
    temp = (imp.source.get("logo") or {}).get("key")
    form = await service.create_form(
        db, imp, user.id, title=body.title, language=body.language, storage=storage
    )
    await db.commit()
    if temp:
        await storage.delete(temp)
    return CreatedOut(form_id=form.id)


# -- submissions import ----------------------------------------------------------------------


async def _version(db: DbDep, imp: Import) -> tuple[FormVersion, Form]:
    version = await db.get(FormVersion, uuid.UUID(imp.source["versionId"]))
    if version is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "version_gone")
    return version, Form.model_validate(version.schema)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


async def _submissions_out(db: DbDep, imp: Import) -> SubmissionImportOut:
    version, form = await _version(db, imp)
    src = imp.source
    headers: list[str] = src["headers"]
    sample: list[list[Any]] = src["sample"]
    mapping: list[str] = imp.mapping.get("columns") or [IGNORE] * len(headers)
    return SubmissionImportOut(
        id=imp.id,
        form_id=imp.form_id,
        status=imp.status,
        filename=src.get("filename", ""),
        row_count=src.get("rowCount", 0),
        version=version.version,
        columns=[
            ColumnOut(
                index=i,
                header=h,
                samples=[_text(r[i]) for r in sample[:3] if i < len(r) and r[i] not in (None, "")],
                target=mapping[i] if i < len(mapping) else IGNORE,
            )
            for i, h in enumerate(headers)
        ],
        targets=[TargetOut.model_validate(t) for t in targets(form)],
        date_order=imp.mapping.get("dateOrder", "auto"),
        report=imp.report,
        stats=imp.stats,
        created_at=imp.created_at,
    )


@router.post(
    "/forms/{form_id}/imports/submissions",
    response_model=SubmissionImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_submissions(
    request: Request,
    db: DbDep,
    storage: StorageDep,
    access: FormOwner,
    filename: Annotated[str, Query(max_length=255)] = "export.csv",
) -> SubmissionImportOut:
    """Upload a Jotform export (raw ``.xlsx``/``.csv`` body). Returns the columns with a
    suggested mapping onto the form's current version."""
    form_rec = access.form
    if form_rec.current_version_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_published")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    try:
        table = read_table(bytes(body), filename)
    except TableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"file_{exc.code}") from exc
    version = await db.get(FormVersion, form_rec.current_version_id)
    assert version is not None
    form = Form.model_validate(version.schema)
    ext = ".xlsx" if bytes(body[:2]) == b"PK" else ".csv"
    imp = Import(
        org_id=form_rec.org_id,
        form_id=form_rec.id,
        kind=ImportKind.JOTFORM_SUBMISSIONS,
        status=ImportStatus.PREVIEW,
        source={
            "filename": filename,
            "headers": table.headers,
            "sample": [[jsonable(v) for v in r] for r in table.rows[:SAMPLE_ROWS]],
            "rowCount": len(table.rows),
            "versionId": str(version.id),
        },
        mapping={"columns": suggest_mapping(table.headers, form), "dateOrder": "auto"},
        created_by=access.user.id,
    )
    db.add(imp)
    await db.flush()
    key = f"imports/{imp.id}/source{ext}"
    await storage.put(key, bytes(body), max_bytes=MAX_FILE_BYTES)
    imp.source_key = key
    await db.commit()
    await db.refresh(imp)
    return await _submissions_out(db, imp)


@router.get("/imports/{import_id}", response_model=None)
async def get_import(db: DbDep, imp: Loaded) -> SubmissionImportOut | FormImportOut:
    if imp.kind == ImportKind.JOTFORM_SUBMISSIONS:
        return await _submissions_out(db, imp)
    return _form_out(imp)


def _check_mapping(columns: list[str], headers: list[str], form: Form) -> list[str]:
    if len(columns) != len(headers):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mapping_length")
    allowed = {t["value"] for t in targets(form)} | {IGNORE}
    if any(c not in allowed for c in columns):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mapping_target")
    used = [c for c in columns if c != IGNORE]
    return sorted({c for c in used if used.count(c) > 1})


@router.put("/imports/{import_id}/mapping", response_model=MappingPreviewOut)
async def set_mapping(
    body: MappingIn, db: DbDep, settings: SettingsDep, imp: Loaded
) -> MappingPreviewOut:
    """Save the column mapping and preview the first rows converted with it."""
    if imp.kind != ImportKind.JOTFORM_SUBMISSIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_import_kind")
    if imp.status != ImportStatus.PREVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_started")
    _version_row, form = await _version(db, imp)
    headers: list[str] = imp.source["headers"]
    duplicates = _check_mapping(body.columns, headers, form)
    imp.mapping = {**imp.mapping, "columns": body.columns, "dateOrder": body.date_order}
    await db.commit()

    fields = {f.id: f for f in importable_fields(form)}
    language = form.settings.language
    rows: list[PreviewRow] = []
    problems = 0
    for n, row in enumerate(imp.source["sample"], start=2):
        res = convert_row(row, body.columns, fields, settings.tz, body.date_order)
        bad = {col: code for col, code, _text in res.problems}
        problems += len(bad)
        cells: list[PreviewCell] = []
        for col, target in enumerate(body.columns):
            if target == IGNORE:
                continue
            text = ""
            if target == "meta:submitted_at" and res.submitted_at:
                text = res.submitted_at.strftime("%Y-%m-%d %H:%M")
            elif target == "meta:external_id":
                text = res.external_id or ""
            elif target == "meta:ip":
                text = res.ip or ""
            elif target.startswith("field:"):
                fid = target[6:]
                if fid in res.links:
                    text = "\n".join(res.links[fid])
                elif fid in res.data:
                    text = answer_text(fields[fid], res.data[fid], language)
            cells.append(PreviewCell(column=col, text=text, problem=bad.get(col)))
        rows.append(PreviewRow(row=n, cells=cells))
    return MappingPreviewOut(
        rows=rows,
        problems=problems,
        duplicate_targets=duplicates,
        has_submission_id="meta:external_id" in body.columns,
    )


@router.post("/imports/{import_id}/start", response_model=None)
async def start_import(
    body: StartIn, db: DbDep, queue: QueueDep, imp: Loaded
) -> SubmissionImportOut:
    """Queue the import with the saved mapping. Rows whose Jotform submission id is already
    on the form are skipped, so a repeated import adds nothing twice."""
    if imp.kind != ImportKind.JOTFORM_SUBMISSIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_import_kind")
    if imp.status != ImportStatus.PREVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_started")
    columns = imp.mapping.get("columns") or []
    if not any(c.startswith("field:") for c in columns):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_mapped")
    _version_row, form = await _version(db, imp)
    if _check_mapping(columns, imp.source["headers"], form):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mapping_duplicate")
    imp.mapping = {**imp.mapping, "status": body.status.value}
    imp.status = ImportStatus.RUNNING
    imp.stats = {"rowsDone": 0}
    await db.commit()
    await queue.enqueue("import_submissions", import_id=str(imp.id))
    await db.refresh(imp)
    return await _submissions_out(db, imp)


@router.get("/forms/{form_id}/imports", response_model=list[SubmissionImportOut])
async def list_submission_imports(db: DbDep, access: FormOwner) -> list[SubmissionImportOut]:
    """Earlier submission imports into this form, newest first."""
    rows = (
        await db.scalars(
            select(Import)
            .where(
                Import.form_id == access.form.id,
                Import.kind == ImportKind.JOTFORM_SUBMISSIONS,
                Import.status != ImportStatus.PREVIEW,
            )
            .order_by(Import.created_at.desc())
            .limit(20)
        )
    ).all()
    return [await _submissions_out(db, imp) for imp in rows]
