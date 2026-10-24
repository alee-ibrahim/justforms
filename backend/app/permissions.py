"""Role resolution (DESIGN section 7).

``effective_form_role`` is the single resolver: superadmin > org admin (acts as owner on
every form in the org) > per-form grant. Every form-scoped endpoint goes through
``require_form_role``; forms the user cannot see are reported as 404, not 403.

Organisation roles rank admin > creator > member: creators (and admins) create forms;
members only open forms shared with them.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, DbDep
from app.models import FormPermission, FormRecord, FormRole, OrgMembership, OrgRole, User

FORM_ROLE_RANK = {FormRole.VIEWER: 1, FormRole.EDITOR: 2, FormRole.OWNER: 3}
ORG_ROLE_RANK = {OrgRole.MEMBER: 1, OrgRole.CREATOR: 2, OrgRole.ADMIN: 3}


async def org_role(db: AsyncSession, user: User, org_id: uuid.UUID) -> OrgRole | None:
    if user.is_superadmin:
        return OrgRole.ADMIN
    membership = await db.get(OrgMembership, (org_id, user.id))
    return membership.role if membership else None


async def effective_form_role(db: AsyncSession, user: User, form: FormRecord) -> FormRole | None:
    if user.is_superadmin:
        return FormRole.OWNER
    if await org_role(db, user, form.org_id) == OrgRole.ADMIN:
        return FormRole.OWNER
    grant = await db.get(FormPermission, (form.id, user.id))
    return grant.role if grant else None


def has_form_role(role: FormRole | None, minimum: FormRole) -> bool:
    return role is not None and FORM_ROLE_RANK[role] >= FORM_ROLE_RANK[minimum]


def has_org_role(role: OrgRole | None, minimum: OrgRole) -> bool:
    return role is not None and ORG_ROLE_RANK[role] >= ORG_ROLE_RANK[minimum]


def higher_org_role(a: OrgRole | None, b: OrgRole) -> OrgRole:
    return b if a is None or ORG_ROLE_RANK[b] > ORG_ROLE_RANK[a] else a


def higher_form_role(a: FormRole | None, b: FormRole) -> FormRole:
    return b if a is None or FORM_ROLE_RANK[b] > FORM_ROLE_RANK[a] else a


class FormAccess:
    def __init__(self, form: FormRecord, role: FormRole, user: User) -> None:
        self.form = form
        self.role = role
        self.user = user


def require_form_role(minimum: FormRole) -> Callable[..., Awaitable[FormAccess]]:
    async def dependency(form_id: uuid.UUID, db: DbDep, user: CurrentUser) -> FormAccess:
        form = await db.get(FormRecord, form_id)
        if form is None or form.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
        role = await effective_form_role(db, user, form)
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
        if not has_form_role(role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
        return FormAccess(form, role, user)

    return dependency


def require_org_role(minimum: OrgRole) -> Callable[..., Awaitable[OrgRole]]:
    async def dependency(org_id: uuid.UUID, db: DbDep, user: CurrentUser) -> OrgRole:
        role = await org_role(db, user, org_id)
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "org_not_found")
        if ORG_ROLE_RANK[role] < ORG_ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_org_role")
        return role

    return dependency


FormViewer = Annotated[FormAccess, Depends(require_form_role(FormRole.VIEWER))]
FormEditor = Annotated[FormAccess, Depends(require_form_role(FormRole.EDITOR))]
FormOwner = Annotated[FormAccess, Depends(require_form_role(FormRole.OWNER))]
OrgMember = Annotated[OrgRole, Depends(require_org_role(OrgRole.MEMBER))]
# Can create, import and duplicate forms.
OrgCreator = Annotated[OrgRole, Depends(require_org_role(OrgRole.CREATOR))]
OrgAdmin = Annotated[OrgRole, Depends(require_org_role(OrgRole.ADMIN))]
