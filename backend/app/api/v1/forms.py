"""Studio form endpoints: list/create, settings, draft editing and publishing (DESIGN 17)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy import case, func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.api.v1.common import ApiModel
from app.approvals.config import active as approvals_active
from app.approvals.config import load_config as load_approvals
from app.auth.deps import CurrentUser, DbDep, SettingsDep, StorageDep
from app.captcha import CaptchaMode, form_mode
from app.config import Settings
from app.models import (
    AccessMode,
    ApprovalState,
    FormDraftHistory,
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
    OrgMember,
    effective_form_role,
    has_form_role,
    has_org_role,
    org_role,
)
from app.schemas.form import Form, FormLanguage
from app.services import form_diff, slugs
from app.services import forms as svc
from app.services.progress import DEFAULT_SAVE_PROGRESS_DAYS, MAX_SAVE_PROGRESS_DAYS, progress_out
from app.services.users import audit
from app.submissions import retention, version_map

router = APIRouter(tags=["forms"])


class FormOut(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    org_slug: str
    slug: str
    # The public address, https://<host>/<slug>.
    url: str
    # Earlier addresses that redirect to this one (newest first; not in list rows).
    previous_slugs: list[str] = Field(default_factory=list)
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
    # Respondents' answers are kept in their browser while they fill in the form.
    save_progress: bool = True
    save_progress_days: int = DEFAULT_SAVE_PROGRESS_DAYS
    # Questions shown on submission cards (None: chosen automatically).
    card_fields: list[str] | None = None
    # Older versions' fixed questions shown as rows of a newer repeater (export).
    version_mappings: list[dict[str, Any]] = Field(default_factory=list)
    # "Ask your submissions" may send the text of answers to the AI provider (Settings > AI).
    ai_read_answers: bool = False
    submission_count: int = 0
    new_count: int = 0
    created_at: datetime
    updated_at: datetime


class PersonRef(ApiModel):
    id: uuid.UUID
    name: str
    email: str


class FormListItem(FormOut):
    """A row of the forms list (docs/ux/FORMS-LIST-SCREENS.md): the form plus who owns it and
    its activity. Only what anyone with a role on the form may see (Share and Submissions)."""

    language: FormLanguage = "en"
    # Published, and the draft differs from the live version.
    has_unpublished_changes: bool = False
    # The creator while they are an owner, else the earliest owner; owner_count counts all
    # explicit owners (organisation admins are owners implicitly and not counted).
    owner: PersonRef | None = None
    owner_count: int = 0
    # The viewer holds an explicit owner grant.
    owned_by_me: bool = False
    # Submissions that arrived in the last RECENT_DAYS days.
    recent_count: int = 0
    approvals_on: bool = False
    pending_approval_count: int = 0
    last_submission_at: datetime | None = None
    # The latest draft edit (or the creation) and who made it.
    last_edited_at: datetime
    last_edited_by: PersonRef | None = None
    # "jotform" for forms brought in by the importer.
    imported_from: str | None = None


RECENT_DAYS = 7


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

MAX_CARD_FIELDS = 6
FieldKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]


class VersionMappingIn(ApiModel):
    """A repeater and, per row, which question of an older version fills each of its
    questions (``app/submissions/version_map.py``)."""

    repeater: FieldKey
    rows: list[Annotated[dict[FieldKey, FieldKey], Field(min_length=1)]] = Field(
        min_length=1, max_length=version_map.MAX_ROWS
    )


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
    save_progress: bool | None = None
    save_progress_days: Annotated[int, Field(ge=1, le=MAX_SAVE_PROGRESS_DAYS)] | None = None
    # Questions shown on submission cards; an empty list goes back to the automatic choice.
    card_fields: list[FieldKey] | None = Field(default=None, max_length=MAX_CARD_FIELDS)
    # Older versions' fixed questions read as repeater rows; an empty list removes them.
    version_mappings: list[VersionMappingIn] | None = Field(
        default=None, max_length=version_map.MAX_MAPPINGS
    )
    # Owners: let "Ask your submissions" send the text of answers to the AI provider.
    ai_read_answers: bool | None = None


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


class DraftChangesOut(ApiModel):
    """What publishing would change: the draft against the live version (form_diff)."""

    # None before the first publish (everything is new; no list).
    base_version: int | None
    revision: int
    has_changes: bool
    summary: str
    counts: dict[str, int]
    language: FormLanguage
    settings: list[dict[str, Any]]
    pages: list[dict[str, Any]]


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
        previous_slugs=await slugs.aliases(db, form.id),
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
        **progress_out(form.settings),
        card_fields=(form.settings or {}).get("cardFields") or None,
        version_mappings=[
            m.as_json() for m in version_map.parse((form.settings or {}).get("versionMappings"))
        ],
        ai_read_answers=bool((form.settings or {}).get("aiReadAnswers", False)),
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


def _person(pid: uuid.UUID | None, name: str | None, email: str | None) -> PersonRef | None:
    return PersonRef(id=pid, name=name or "", email=email) if pid and email else None


@router.get("/orgs/{org_id}/forms", response_model=list[FormListItem])
async def list_forms(
    org_id: uuid.UUID, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> list[FormListItem]:
    """Every form the user can open, with its owner and activity, in one query (no N+1).

    Organisation admins see every form; everyone else the forms they hold a role on.
    """
    is_admin = await org_role(db, user, org_id) == OrgRole.ADMIN
    f = FormRecord
    mine = aliased(FormPermission)
    editor = aliased(User)
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)

    stats = (
        select(
            func.count().label("total"),
            func.count().filter(Submission.status == SubmissionStatus.NEW).label("new"),
            func.count().filter(Submission.submitted_at >= since).label("recent"),
            func.count()
            .filter(Submission.approval_state == ApprovalState.PENDING)
            .label("pending"),
            func.max(Submission.submitted_at).label("last_at"),
        )
        .where(Submission.form_id == f.id, Submission.deleted_at.is_(None))
        .lateral("stats")
    )
    owner = (
        select(User.id, User.display_name, User.email, func.count().over().label("n"))
        .join(FormPermission, FormPermission.user_id == User.id)
        .where(FormPermission.form_id == f.id, FormPermission.role == FormRole.OWNER)
        .order_by(
            case((User.id == f.created_by, 0), else_=1), FormPermission.created_at, User.email
        )
        .limit(1)
        .lateral("owner")
    )
    edit = (
        select(FormDraftHistory.created_at, FormDraftHistory.actor_id)
        .where(FormDraftHistory.form_id == f.id, FormDraftHistory.undone.is_(False))
        .order_by(FormDraftHistory.revision.desc())
        .limit(1)
        .lateral("edit")
    )
    edited_at = func.coalesce(edit.c.created_at, f.created_at)

    query = (
        select(
            f.id,
            f.slug,
            f.title,
            f.status,
            f.access_mode,
            f.draft_revision,
            f.settings,
            f.created_at,
            f.updated_at,
            f.draft_schema["settings"]["language"].astext.label("language"),
            FormVersion.version,
            (f.draft_schema != FormVersion.schema).label("changed"),
            mine.role.label("my_role"),
            stats.c.total,
            stats.c.new,
            stats.c.recent,
            stats.c.pending,
            stats.c.last_at,
            owner.c.id.label("owner_id"),
            owner.c.display_name.label("owner_name"),
            owner.c.email.label("owner_email"),
            owner.c.n.label("owner_count"),
            edited_at.label("edited_at"),
            editor.id.label("editor_id"),
            editor.display_name.label("editor_name"),
            editor.email.label("editor_email"),
        )
        .outerjoin(FormVersion, FormVersion.id == f.current_version_id)
        .outerjoin(mine, (mine.form_id == f.id) & (mine.user_id == user.id))
        .join(stats, true())
        .outerjoin(owner, true())
        .outerjoin(edit, true())
        .outerjoin(editor, editor.id == func.coalesce(edit.c.actor_id, f.created_by))
        .where(f.org_id == org_id, f.deleted_at.is_(None))
        .order_by(edited_at.desc(), f.id)
    )
    if not is_admin:
        query = query.where(mine.user_id.is_not(None))
    rows = (await db.execute(query)).all()

    org = await db.get(Organization, org_id)
    out: list[FormListItem] = []
    for r in rows:
        extra = r.settings or {}
        out.append(
            FormListItem(
                id=r.id,
                org_id=org_id,
                org_slug=org.slug if org else "",
                slug=r.slug,
                url=f"{settings.public_origin}{slugs.public_path(r.slug)}",
                title=r.title,
                status=r.status,
                access_mode=r.access_mode,
                draft_revision=r.draft_revision,
                current_version=r.version,
                role=FormRole.OWNER if is_admin else r.my_role,
                embed_origins=list(extra.get("embedOrigins", [])),
                retention_days=extra.get("retentionDays"),
                otp_allowed_domains=list(extra.get("otpAllowedDomains", [])),
                otp_one_response=bool(extra.get("otpOneResponse", False)),
                captcha=form_mode(extra),
                **progress_out(extra),
                submission_count=r.total,
                new_count=r.new,
                created_at=r.created_at,
                updated_at=r.updated_at,
                language="dv" if r.language == "dv" else "en",
                has_unpublished_changes=r.version is not None and bool(r.changed),
                owner=_person(r.owner_id, r.owner_name, r.owner_email),
                owner_count=r.owner_count or 0,
                owned_by_me=r.my_role == FormRole.OWNER,
                recent_count=r.recent,
                approvals_on=approvals_active(load_approvals(extra)),
                pending_approval_count=r.pending,
                last_submission_at=r.last_at,
                last_edited_at=r.edited_at,
                last_edited_by=_person(r.editor_id, r.editor_name, r.editor_email),
                imported_from=extra.get("importedFrom"),
            )
        )
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


async def _set_version_mappings(db: DbDep, form: FormRecord, items: list[VersionMappingIn]) -> None:
    mappings = version_map.parse([i.model_dump() for i in items])
    if any(len(row) > version_map.MAX_ROW_FIELDS for m in mappings for row in m.rows):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_version_mapping")
    if mappings:
        published = (
            await db.scalars(select(FormVersion.schema).where(FormVersion.form_id == form.id))
        ).all()
        found = version_map.problems(
            mappings,
            Form.model_validate(form.draft_schema),
            [Form.model_validate(s) for s in published],
        )
        if found:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "bad_version_mapping", "problems": found[:20]},
            )
    rest = {k: v for k, v in (form.settings or {}).items() if k != "versionMappings"}
    stored = [m.as_json() for m in mappings]
    form.settings = {**rest, **({"versionMappings": stored} if stored else {})}


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
            body.save_progress,
            body.save_progress_days,
            body.ai_read_answers,
        )
    )
    if owner_only and not has_form_role(access.role, FormRole.OWNER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    is_owner = has_form_role(access.role, FormRole.OWNER)
    current_origins = list((form.settings or {}).get("embedOrigins", []))
    if body.embed_origins is not None and body.embed_origins != current_origins and not is_owner:
        # Which websites may frame the form is the owner's decision.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "embed_origins_owner_only")
    if body.status == FormStatus.DRAFT and form.status != FormStatus.DRAFT:
        # Once published a form is live, closed or archived; "draft" would look unpublished
        # in the studio while the link keeps working.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cannot_return_to_draft")
    if body.slug is not None and body.slug != form.slug:
        await _check_slug(db, body.slug, form.id)
        await slugs.change(db, form, body.slug)
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
    if body.save_progress is not None:
        extra["saveProgress"] = body.save_progress
    if body.save_progress_days is not None:
        extra["saveProgressDays"] = body.save_progress_days
    if body.ai_read_answers is not None:
        extra["aiReadAnswers"] = body.ai_read_answers
    if extra:
        form.settings = {**(form.settings or {}), **extra}
    if body.card_fields is not None:
        rest = {k: v for k, v in (form.settings or {}).items() if k != "cardFields"}
        cards = list(dict.fromkeys(body.card_fields))
        form.settings = {**rest, **({"cardFields": cards} if cards else {})}
    if body.version_mappings is not None:
        await _set_version_mappings(db, form, body.version_mappings)
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
    """To the trash: the form, its link and its submissions are hidden until restored or
    erased after JUSTFORMS_TRASH_DAYS (DESIGN 14.5). Its submissions keep their own state, so
    restoring the form brings back exactly what was there."""
    form = access.form
    form.deleted_at = datetime.now(UTC)
    form.deleted_by = access.user.id
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


# -- the trash ------------------------------------------------------------------------------


class TrashPerson(ApiModel):
    id: uuid.UUID
    name: str
    email: str


class TrashedForm(ApiModel):
    id: uuid.UUID
    title: str
    slug: str
    status: FormStatus
    language: str
    deleted_at: datetime
    deleted_by: TrashPerson | None
    # When the nightly job erases it (and its submissions) for good.
    purge_at: datetime
    # Submissions that come back with it (ones deleted on their own stay in its trash).
    submission_count: int
    # Another form took the address meanwhile: restoring needs a new one.
    slug_taken: bool
    slug_suggestion: str | None = None


class RestoreIn(ApiModel):
    slug: Annotated[str, StringConstraints(pattern=slugs.SLUG_PATTERN)] | None = None


@router.get("/orgs/{org_id}/forms/trash", response_model=list[TrashedForm])
async def list_trash(
    org_id: uuid.UUID, db: DbDep, user: CurrentUser, settings: SettingsDep, role: OrgMember
) -> list[TrashedForm]:
    """Deleted forms the person may restore: every one in the organisation for admins and
    superadmins, else the ones they own. Most recently deleted first."""
    is_admin = role == OrgRole.ADMIN
    by = aliased(User)
    query = (
        select(FormRecord, by)
        .outerjoin(by, by.id == FormRecord.deleted_by)
        .where(FormRecord.org_id == org_id, FormRecord.deleted_at.is_not(None))
        .order_by(FormRecord.deleted_at.desc(), FormRecord.id.desc())
    )
    if not is_admin:
        query = query.join(
            FormPermission,
            (FormPermission.form_id == FormRecord.id)
            & (FormPermission.user_id == user.id)
            & (FormPermission.role == FormRole.OWNER),
        )
    rows = (await db.execute(query)).all()
    counts: dict[uuid.UUID, int] = {}
    if rows:
        counts = {
            fid: n
            for fid, n in (
                await db.execute(
                    select(Submission.form_id, func.count())
                    .where(
                        Submission.form_id.in_([f.id for f, _ in rows]),
                        Submission.deleted_at.is_(None),
                    )
                    .group_by(Submission.form_id)
                )
            ).all()
        }
    out: list[TrashedForm] = []
    for form, person in rows:
        taken = await slugs.taken(db, form.slug, form.id)
        assert form.deleted_at is not None
        out.append(
            TrashedForm(
                id=form.id,
                title=form.title,
                slug=form.slug,
                status=form.status,
                language="dv"
                if (form.draft_schema or {}).get("settings", {}).get("language") == "dv"
                else "en",
                deleted_at=form.deleted_at,
                deleted_by=TrashPerson(
                    id=person.id, name=person.display_name or "", email=person.email
                )
                if person
                else None,
                purge_at=retention.form_purge_at(form, settings.trash_days) or form.deleted_at,
                submission_count=counts.get(form.id, 0),
                slug_taken=taken,
                slug_suggestion=await slugs.unique_slug(db, form.slug, form.id) if taken else None,
            )
        )
    return out


async def _trashed(db: DbDep, user: CurrentUser, form_id: uuid.UUID) -> FormRecord:
    """A deleted form the person owns (admins own every form of their organisation)."""
    form = await db.get(FormRecord, form_id)
    role = await effective_form_role(db, user, form) if form is not None else None
    if form is None or form.deleted_at is None or role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
    if not has_form_role(role, FormRole.OWNER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    return form


@router.post("/forms/{form_id}/restore", response_model=FormOut)
async def restore_form(
    form_id: uuid.UUID, body: RestoreIn, db: DbDep, user: CurrentUser, settings: SettingsDep
) -> FormOut | JSONResponse:
    """Bring a form back from the trash with its link, versions and submissions. When another
    form took the address meanwhile, answers 409 ``slug_taken`` with a suggestion; send
    ``slug`` to restore it at a new address."""
    form = await _trashed(db, user, form_id)
    slug = body.slug or form.slug
    found = await slugs.problem(db, slug, form.id)
    if found == "taken" and body.slug is None:
        return JSONResponse(
            {
                "detail": "slug_taken",
                "slug": form.slug,
                "suggestion": await slugs.unique_slug(db, form.slug, form.id),
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    if found is not None:
        await _check_slug(db, slug, form.id)
    deleted_at, previous = form.deleted_at, form.slug
    # Its old address went to another form meanwhile: nothing to redirect from.
    await slugs.change(db, form, slug, keep_old=False)
    form.deleted_at = None
    form.deleted_by = None
    await audit(
        db,
        "form.restore",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="form",
        target_id=form.id,
        meta={
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            **({"slug": slug, "previous_slug": previous} if slug != previous else {}),
        },
    )
    try:
        await db.commit()
    except IntegrityError:  # another form took the address between the check and the commit
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug_taken") from None
    role = await effective_form_role(db, user, form)
    assert role is not None
    return await form_out(db, settings, form, role)


@router.delete("/forms/{form_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def erase_form(
    form_id: uuid.UUID, db: DbDep, user: CurrentUser, storage: StorageDep
) -> Response:
    """Owners: erase a form in the trash now, with every submission and file. No undo."""
    form = await _trashed(db, user, form_id)
    await retention.erase_form(db, storage, form, reason="owner", actor_id=user.id)
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


@router.get("/forms/{form_id}/draft/changes", response_model=DraftChangesOut)
async def draft_changes(db: DbDep, access: FormEditor) -> DraftChangesOut:
    """Changes in the draft that publishing would make live (DESIGN 17, Review changes)."""
    form = access.form
    live = await svc.live_schema(db, form)
    language = form.draft_schema.get("settings", {}).get("language", "en")
    if live is None:
        return DraftChangesOut(
            base_version=None,
            revision=form.draft_revision,
            has_changes=True,
            summary="Not published yet",
            counts={"added": 0, "removed": 0, "changed": 0, "moved": 0},
            language="dv" if language == "dv" else "en",
            settings=[],
            pages=[],
        )
    number, schema = live
    result = form_diff.diff(schema, form.draft_schema)
    return DraftChangesOut(base_version=number, revision=form.draft_revision, **result)


@router.post("/forms/{form_id}/draft/discard", response_model=DraftOut)
async def discard_draft(body: HistoryStep, db: DbDep, access: FormEditor) -> Any:
    """Reset the draft to the live version (one undoable edit). 409 before the first publish."""
    form = access.form
    try:
        version = await svc.discard_draft(db, form, body.base_revision, access.user.id)
    except svc.DraftConflictError:
        current = form.draft_revision
        await db.rollback()
        return _conflict(current)
    except svc.NeverPublishedError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "never_published") from None
    if version is not None:
        await audit(
            db,
            "form.draft_discard",
            org_id=form.org_id,
            actor_id=access.user.id,
            target_type="form",
            target_id=form.id,
            meta={"version": version, "revision": form.draft_revision},
        )
    await db.commit()
    return await draft_out(db, form)


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
    if not has_form_role(access.role, FormRole.OWNER):
        live = await svc.live_schema(db, form)
        unflagged = svc.unflagged_sensitive(live[1], form.draft_schema) if live else []
        if unflagged:
            names = ", ".join(label for _key, label in unflagged)
            return JSONResponse(
                {
                    "detail": "sensitive_owner_only",
                    "issues": [
                        {
                            "code": "sensitive_owner_only",
                            "message": "Only the form's owner can turn off Sensitive on a "
                            f"published question ({names}). Ask an owner to publish, or "
                            "turn Sensitive back on.",
                            "target": unflagged[0][0],
                        }
                    ],
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )
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
