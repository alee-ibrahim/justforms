"""Studio form endpoints: list/create, settings, draft editing and publishing (DESIGN 17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, SettingsDep
from app.captcha import CaptchaMode, form_mode
from app.config import Settings
from app.models import (
    AccessMode,
    FormPermission,
    FormRecord,
    FormRole,
    FormStatus,
    FormVersion,
    Organization,
    OrgRole,
    Submission,
    SubmissionStatus,
    User,
)
from app.permissions import (
    FormAccess,
    FormEditor,
    FormOwner,
    FormViewer,
    OrgCreator,
    has_form_role,
    has_org_role,
    org_role,
)
from app.schemas.form import FormLanguage
from app.services import forms as svc
from app.services import slugs
from app.services.users import audit

router = APIRouter(tags=["forms"])


class FormOut(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    org_slug: str
    slug: str
    # The public address, https://<host>/<slug>.
    url: str
    title: str
    status: FormStatus
    access_mode: AccessMode
    draft_revision: int
    current_version: int | None = None
    role: FormRole
    embed_origins: list[str] = Field(default_factory=list)
    # Erase submissions this many days after they arrive (None: keep).
    retention_days: int | None = None
    # Access mode "otp": allowed email domains (empty: any) and one response per address.
    otp_allowed_domains: list[str] = Field(default_factory=list)
    otp_one_response: bool = False
    captcha: CaptchaMode = "off"
    submission_count: int = 0
    new_count: int = 0
    created_at: datetime
    updated_at: datetime


class FormCreate(ApiModel):
    title: Annotated[str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)]
    language: FormLanguage = "en"
    # The address; taken from the title when missing (a taken one gets -2, -3...).
    slug: Annotated[str, StringConstraints(pattern=slugs.SLUG_PATTERN)] | None = None


Domain = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$",
        max_length=253,
    ),
]

Origin = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$"),
]


class FormPatch(ApiModel):
    slug: Annotated[str, StringConstraints(pattern=slugs.SLUG_PATTERN)] | None = None
    status: FormStatus | None = None
    access_mode: AccessMode | None = None
    embed_origins: list[Origin] | None = Field(default=None, max_length=50)
    # 0 turns retention off.
    retention_days: Annotated[int, Field(ge=0, le=36500)] | None = None
    otp_allowed_domains: list[Domain] | None = Field(default=None, max_length=50)
    otp_one_response: bool | None = None
    captcha: CaptchaMode | None = None


class DraftOut(ApiModel):
    schema_: dict[str, Any] = Field(alias="schema")
    revision: int
    can_undo: bool = False
    can_redo: bool = False


class HistoryStep(ApiModel):
    base_revision: int


class DraftPatch(ApiModel):
    base_revision: int
    patch: list[dict[str, Any]]


class VersionOut(ApiModel):
    id: uuid.UUID
    version: int
    schema_hash: str
    published_at: datetime
    published_by: uuid.UUID | None
    published_by_name: str | None = None


class VersionDetail(VersionOut):
    schema_: dict[str, Any] = Field(alias="schema")


async def _version_number(db: DbDep, form: FormRecord) -> int | None:
    if form.current_version_id is None:
        return None
    version = await db.get(FormVersion, form.current_version_id)
    return version.version if version else None


async def _counts(db: DbDep, form_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """(all, new) submission counts per form, deleted ones excluded."""
    rows = await db.execute(
        select(
            Submission.form_id,
            func.count(),
            func.count().filter(Submission.status == SubmissionStatus.NEW),
        )
        .where(Submission.form_id.in_(form_ids), Submission.deleted_at.is_(None))
        .group_by(Submission.form_id)
    )
    return {fid: (total, new) for fid, total, new in rows.all()}


async def form_out(
    db: DbDep,
    settings: Settings,
    form: FormRecord,
    role: FormRole,
    counts: tuple[int, int] | None = None,
) -> FormOut:
    await db.refresh(form)
    if counts is None:
        counts = (await _counts(db, [form.id])).get(form.id, (0, 0))
    org = await db.get(Organization, form.org_id)
    return FormOut(
        id=form.id,
        org_id=form.org_id,
        org_slug=org.slug if org else "",
        slug=form.slug,
        url=f"{settings.public_origin}{slugs.public_path(form.slug)}",
        title=form.title,
        status=form.status,
        access_mode=form.access_mode,
        draft_revision=form.draft_revision,
        current_version=await _version_number(db, form),
        role=role,
        embed_origins=list((form.settings or {}).get("embedOrigins", [])),
        retention_days=(form.settings or {}).get("retentionDays"),
        otp_allowed_domains=list((form.settings or {}).get("otpAllowedDomains", [])),
        otp_one_response=bool((form.settings or {}).get("otpOneResponse", False)),
        captcha=form_mode(form.settings),
        submission_count=counts[0],
        new_count=counts[1],
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


async def _check_slug(db: DbDep, slug: str, exclude: uuid.UUID | None = None) -> None:
    found = await slugs.problem(db, slug, exclude)
    if found == "taken":
        raise HTTPException(status.HTTP_409_CONFLICT, "slug_taken")
    if found is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"slug_{found}")


class SlugCheck(ApiModel):
    slug: str
    available: bool
    # invalid | reserved | taken
    problem: str | None = None
    suggestion: str | None = None
    url: str


@router.get("/forms/slug-check", response_model=SlugCheck)
async def slug_check(
    db: DbDep,
    settings: SettingsDep,
    _: CurrentUser,
    slug: Annotated[str, Query(max_length=200)],
    form_id: Annotated[uuid.UUID | None, Query(alias="formId")] = None,
) -> SlugCheck:
    """Live availability check for the address field (create and rename)."""
    found = await slugs.problem(db, slug, form_id)
    suggestion = None
    if found is not None:
        base = slug if found != "invalid" else slugs.slugify(slug)
        suggestion = await slugs.unique_slug(db, base, form_id)
    return SlugCheck(
        slug=slug,
        available=found is None,
        problem=found,
        suggestion=suggestion,
        url=f"{settings.public_origin}/{suggestion or slug}",
    )


@router.get("/orgs/{org_id}/forms", response_model=list[FormOut])
async def list_forms(
    org_id: uuid.UUID, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> list[FormOut]:
    role_in_org = await org_role(db, user, org_id)
    base = select(FormRecord).where(FormRecord.org_id == org_id, FormRecord.deleted_at.is_(None))
    out: list[FormOut] = []
    if role_in_org == OrgRole.ADMIN:
        rows = (await db.execute(base.order_by(FormRecord.updated_at.desc()))).scalars().all()
        counts = await _counts(db, [f.id for f in rows])
        for form in rows:
            out.append(
                await form_out(db, settings, form, FormRole.OWNER, counts.get(form.id, (0, 0)))
            )
        return out
    query = (
        select(FormRecord, FormPermission.role)
        .join(FormPermission, FormPermission.form_id == FormRecord.id)
        .where(
            FormRecord.org_id == org_id,
            FormRecord.deleted_at.is_(None),
            or_(FormPermission.user_id == user.id),
        )
        .order_by(FormRecord.updated_at.desc())
    )
    granted = (await db.execute(query)).all()
    counts = await _counts(db, [f.id for f, _r in granted])
    for form, role in granted:
        out.append(await form_out(db, settings, form, role, counts.get(form.id, (0, 0))))
    return out


@router.post("/orgs/{org_id}/forms", response_model=FormOut, status_code=status.HTTP_201_CREATED)
async def create_form(
    org_id: uuid.UUID,
    body: FormCreate,
    db: DbDep,
    settings: SettingsDep,
    user: CurrentUser,
    _: OrgCreator,
) -> FormOut:
    draft = svc.new_draft(body.title, body.language)
    if body.slug is not None:
        await _check_slug(db, body.slug)
    form = FormRecord(
        org_id=org_id,
        slug=body.slug or await slugs.unique_slug(db, slugs.slugify(body.title)),
        title=svc.form_title(draft),
        draft_schema=draft,
        created_by=user.id,
    )
    db.add(form)
    await db.flush()
    db.add(FormPermission(form_id=form.id, user_id=user.id, role=FormRole.OWNER))
    await audit(
        db, "form.create", org_id=org_id, actor_id=user.id, target_type="form", target_id=form.id
    )
    await db.commit()
    return await form_out(db, settings, form, FormRole.OWNER)


@router.get("/forms/{form_id}", response_model=FormOut)
async def get_form(db: DbDep, settings: SettingsDep, access: FormViewer) -> FormOut:
    return await form_out(db, settings, access.form, access.role)


@router.patch("/forms/{form_id}", response_model=FormOut)
async def patch_form(
    body: FormPatch, db: DbDep, settings: SettingsDep, access: FormEditor
) -> FormOut:
    form = access.form
    owner_only = any(
        v is not None
        for v in (
            body.status,
            body.access_mode,
            body.retention_days,
            body.otp_allowed_domains,
            body.otp_one_response,
            body.captcha,
        )
    )
    if owner_only and not has_form_role(access.role, FormRole.OWNER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    if body.slug is not None and body.slug != form.slug:
        await _check_slug(db, body.slug, form.id)
        form.slug = body.slug
    if body.status is not None:
        form.status = body.status
    if body.access_mode is not None:
        form.access_mode = body.access_mode
    if body.embed_origins is not None:
        form.settings = {**(form.settings or {}), "embedOrigins": body.embed_origins}
    extra: dict[str, Any] = {}
    if body.otp_allowed_domains is not None:
        extra["otpAllowedDomains"] = list(dict.fromkeys(body.otp_allowed_domains))
    if body.otp_one_response is not None:
        extra["otpOneResponse"] = body.otp_one_response
    if body.captcha is not None:
        extra["captcha"] = body.captcha
    if extra:
        form.settings = {**(form.settings or {}), **extra}
    if body.retention_days is not None:
        rest = {k: v for k, v in (form.settings or {}).items() if k != "retentionDays"}
        form.settings = {
            **rest,
            **({"retentionDays": body.retention_days} if body.retention_days else {}),
        }
    await audit(
        db,
        "form.update",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta=body.model_dump(mode="json", exclude_none=True),
    )
    try:
        await db.commit()
    except IntegrityError:  # another form took the address between the check and the commit
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug_taken") from None
    return await form_out(db, settings, form, access.role)


@router.delete("/forms/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(db: DbDep, access: FormOwner) -> Response:
    form = access.form
    form.deleted_at = datetime.now().astimezone()
    await audit(
        db,
        "form.delete",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def draft_out(db: DbDep, form: FormRecord) -> DraftOut:
    can_undo, can_redo = await svc.history_state(db, form)
    return DraftOut(
        schema_=form.draft_schema,
        revision=form.draft_revision,
        can_undo=can_undo,
        can_redo=can_redo,
    )


def _conflict(revision: int) -> JSONResponse:
    return JSONResponse(
        {"detail": "revision_conflict", "revision": revision},
        status_code=status.HTTP_409_CONFLICT,
    )


@router.get("/forms/{form_id}/draft", response_model=DraftOut)
async def get_draft(db: DbDep, access: FormEditor) -> DraftOut:
    return await draft_out(db, access.form)


@router.patch("/forms/{form_id}/draft", response_model=DraftOut)
async def patch_draft(body: DraftPatch, db: DbDep, access: FormEditor) -> DraftOut | JSONResponse:
    form = access.form
    try:
        await svc.apply_draft_patch(db, form, body.base_revision, body.patch, access.user.id)
    except svc.DraftConflictError:
        current = form.draft_revision
        await db.rollback()
        return _conflict(current)
    except svc.DraftPatchError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad_patch: {exc}") from exc
    except ValidationError as exc:
        await db.rollback()
        return JSONResponse(
            {"detail": jsonable_encoder(exc.errors(include_url=False, include_input=False))},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    await db.commit()
    return await draft_out(db, form)


async def _step(body: HistoryStep, db: DbDep, access: FormAccess, *, redo: bool) -> Any:
    form = access.form
    try:
        await svc.step_history(db, form, body.base_revision, redo=redo)
    except svc.DraftConflictError:
        current = form.draft_revision
        await db.rollback()
        return _conflict(current)
    except (svc.DraftPatchError, ValidationError):
        await db.commit()  # keeps the dropped history
        raise HTTPException(status.HTTP_409_CONFLICT, "history_unavailable") from None
    await db.commit()
    return await draft_out(db, form)


@router.post("/forms/{form_id}/draft/undo", response_model=DraftOut)
async def undo_draft(body: HistoryStep, db: DbDep, access: FormEditor) -> Any:
    return await _step(body, db, access, redo=False)


@router.post("/forms/{form_id}/draft/redo", response_model=DraftOut)
async def redo_draft(body: HistoryStep, db: DbDep, access: FormEditor) -> Any:
    return await _step(body, db, access, redo=True)


@router.post(
    "/forms/{form_id}/duplicate", response_model=FormOut, status_code=status.HTTP_201_CREATED
)
async def duplicate_form(db: DbDep, settings: SettingsDep, access: FormEditor) -> FormOut:
    src = access.form
    if not has_org_role(await org_role(db, access.user, src.org_id), OrgRole.CREATOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_org_role")
    title = f"{src.title} (copy)" if src.title else "Untitled form (copy)"
    schema = {**src.draft_schema, "settings": {**src.draft_schema["settings"], "title": title}}
    form = FormRecord(
        org_id=src.org_id,
        slug=await slugs.unique_slug(db, slugs.slugify(title)),
        title=svc.form_title(schema),
        draft_schema=schema,
        created_by=access.user.id,
    )
    db.add(form)
    await db.flush()
    db.add(FormPermission(form_id=form.id, user_id=access.user.id, role=FormRole.OWNER))
    await audit(
        db,
        "form.duplicate",
        org_id=src.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={"source": str(src.id)},
    )
    await db.commit()
    return await form_out(db, settings, form, FormRole.OWNER)


@router.post("/forms/{form_id}/publish", response_model=VersionOut)
async def publish_form(db: DbDep, access: FormEditor) -> VersionOut | JSONResponse:
    form = access.form
    try:
        version = await svc.publish(db, form, access.user.id)
    except svc.PublishError as exc:
        await db.rollback()
        return JSONResponse(
            {"detail": "publish_failed", "issues": [i.as_dict() for i in exc.issues]},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    await audit(
        db,
        "form.publish",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={"version": version.version},
    )
    await db.commit()
    return VersionOut.model_validate(version)


@router.get("/forms/{form_id}/versions", response_model=list[VersionOut])
async def list_versions(db: DbDep, access: FormViewer) -> list[VersionOut]:
    rows = await db.execute(
        select(FormVersion, User.display_name, User.email)
        .outerjoin(User, User.id == FormVersion.published_by)
        .where(FormVersion.form_id == access.form.id)
        .order_by(FormVersion.version.desc())
    )
    out: list[VersionOut] = []
    for version, name, email in rows.all():
        item = VersionOut.model_validate(version)
        item.published_by_name = name or email
        out.append(item)
    return out


@router.get("/forms/{form_id}/versions/{number}", response_model=VersionDetail)
async def get_version(number: int, db: DbDep, access: FormViewer) -> VersionDetail:
    version = await db.scalar(
        select(FormVersion).where(
            FormVersion.form_id == access.form.id, FormVersion.version == number
        )
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version_not_found")
    return VersionDetail.model_validate(version)
